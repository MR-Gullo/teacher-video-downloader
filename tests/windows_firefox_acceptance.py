#!/usr/bin/env python3
"""Run a real Firefox/native-host smoke test in a disposable Windows account.

Requires an unpacked Windows installer payload, an XPI, Selenium, Firefox and
geckodriver. It installs to a temporary staging root and registers that exact
host in HKCU only if no registration already exists. This exercises an actual
Firefox process and bundled tools, not a mocked browser or downloader.
"""
import argparse
import contextlib
import http.server
import json
import os
import queue
import sqlite3
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

HOST = 'org.teacher.video_downloader'
EXTENSION_ID = 'teacher-video-downloader@local.invalid'
KEY = r'Software\Mozilla\NativeMessagingHosts' + chr(92) + HOST


def check_worker_crash_isolation(runtime, companion, root):
    """Prove a killed Windows worker cannot leave its child process alive."""
    import ctypes
    from ctypes import wintypes
    state=root/'worker-isolation';state.mkdir()
    script=root/'worker-isolation.py'
    script.write_text("""import msvcrt,os,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from windows_job import attach_worker
state=Path(sys.argv[2]);lock=open(state/'worker.lock','a+b')
lock.seek(0,os.SEEK_END)
if not lock.tell():lock.write(b'0');lock.flush()
lock.seek(0)
try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
except OSError:print('LOCKED',flush=True);sys.exit(0)
if sys.argv[3]=='probe':print('FREE',flush=True);sys.exit(0)
job=attach_worker(state)
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print(child.pid,flush=True)
time.sleep(120)
""",encoding='utf-8')
    command=[str(runtime),'-B',str(script),str(companion),str(state)]
    parent=subprocess.Popen(command+['hold'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    handle=None
    try:
        lines=queue.Queue(maxsize=1)
        threading.Thread(target=lambda:lines.put(parent.stdout.readline().strip()),daemon=True).start()
        try:line=lines.get(timeout=15)
        except queue.Empty:raise RuntimeError('Timed out starting the worker isolation check.') from None
        if not line.isdigit():raise RuntimeError('Worker isolation setup failed: '+line)
        child_pid=int(line)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x00100000,False,child_pid)
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        probe=subprocess.run(command+['probe'],capture_output=True,text=True,timeout=15,check=True)
        if probe.stdout.strip()!='LOCKED':raise RuntimeError('Second worker did not respect the active worker lock.')
        parent.kill();parent.wait(timeout=15)
        if kernel.WaitForSingleObject(handle,15000)!=0:raise RuntimeError('Engine child survived a killed Windows worker.')
        probe=subprocess.run(command+['probe'],capture_output=True,text=True,timeout=15,check=True)
        if probe.stdout.strip()!='FREE':raise RuntimeError('Worker lock was not released after termination.')
    finally:
        if parent.poll() is None:parent.kill();parent.wait(timeout=15)
        if handle:kernel.CloseHandle(handle)
        if parent.stdout:parent.stdout.close()
        if parent.stderr:parent.stderr.close()


def check_packaged_worker(runtime, companion, tools, root, url):
    """Start the shipped worker against a separate, synthetic queue."""
    state=root/'direct-worker-state';output=root/'direct-worker-output'
    env=os.environ.copy();env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None)
    env.update(TVD_STATE_DIR=str(state),YTDL_OUTPUT_DIR=str(output),PATH=str(tools)+os.pathsep+env.get('PATH',''))
    script=("import json,sys;sys.path.insert(0,sys.argv[1]);import core;"
            "core.handle({'op':'enqueue','jobs':[{'url':sys.argv[2],'captions':False,'outputFormat':'standard'}]},False)")
    subprocess.run([str(runtime),'-B','-c',script,str(companion),url],env=env,check=True,capture_output=True,timeout=15)
    worker=subprocess.Popen([str(runtime),'-B',str(companion/'worker.py')],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            with contextlib.closing(sqlite3.connect(state/'queue.sqlite',timeout=3)) as db:
                row=db.execute('SELECT status,attempts FROM jobs').fetchone()
            if row and row[1]>0:
                print('Packaged worker started a queued job:',row[0],flush=True)
                return
            if worker.poll() is not None:
                error=worker.stderr.read().decode('utf-8','replace')
                # The isolated probe contains only a synthetic URL. Report just the
                # exception class, never arbitrary engine output or local paths.
                last=error.strip().splitlines()[-1] if error.strip() else ''
                category=last.split(':',1)[0] if last and len(last.split(':',1)[0])<80 else 'none'
                raise RuntimeError(f'Packaged worker exited before starting a job (exit {worker.returncode}; error {category}).')
            time.sleep(.2)
        raise RuntimeError('Packaged worker did not start its isolated queued job within 25 seconds.')
    finally:
        if worker.poll() is None:worker.terminate()
        try:worker.wait(timeout=15)
        except subprocess.TimeoutExpired:worker.kill();worker.wait(timeout=15)
        worker.stderr.close()


def stop_staged_processes(root, app):
    """Stop only executables inside this test's unique staged installation."""
    if not app.resolve().is_relative_to(root.resolve()) or not app.is_dir():
        raise RuntimeError('Refusing process cleanup outside the disposable staging root.')
    env=os.environ.copy();env['LESSONSHELF_TEST_APP']=str(app.resolve())
    script=r'''$prefix = $env:LESSONSHELF_TEST_APP + '\'
$deadline = (Get-Date).AddSeconds(15)
do {
  $owned = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) })
  foreach ($process in $owned) { Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue }
  if ($owned.Count -gt 0) { Start-Sleep -Milliseconds 250 }
} while ($owned.Count -gt 0 -and (Get-Date) -lt $deadline)
if ($owned.Count -gt 0) { exit 1 }'''
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],env=env,check=True,timeout=25,capture_output=True)


def trace_staged_worker(companion, root):
    """Instrument only the disposable installation with privacy-safe startup phases."""
    worker=companion/'worker.py';source=worker.read_text(encoding='utf-8')
    trace_dir=root/'worker-startup-trace';trace_dir.mkdir()
    replacements={
        '    db=setup();lock=open(STATE/\'worker.lock\',\'a+b\');os.chmod(STATE/\'worker.lock\',0o600)':
            "    _acceptance_trace('before_setup')\n    db=setup();_acceptance_trace('after_setup');lock=open(STATE/'worker.lock','a+b');os.chmod(STATE/'worker.lock',0o600)",
        '        except OSError:db.close();lock.close();return':
            "        except OSError as error:_acceptance_trace('lock_failed',error);db.close();lock.close();return",
        '        from windows_job import attach_worker':
            "        _acceptance_trace('lock_acquired')\n        from windows_job import attach_worker",
        '        except (OSError,RuntimeError):db.close();lock.close();return':
            "        except (OSError,RuntimeError) as error:_acceptance_trace('job_failed',error);db.close();lock.close();return\n        _acceptance_trace('job_attached')",
        "if __name__=='__main__':main()":
            "if __name__=='__main__':\n    try:main()\n    except BaseException as error:_acceptance_trace('exception',error);raise\n    finally:_acceptance_trace('exit')",
    }
    for old,new in replacements.items():
        if source.count(old)!=1:raise RuntimeError('Cannot safely instrument the staged worker for startup diagnosis.')
        source=source.replace(old,new,1)
    prefix=("import json as _qa_json, os as _qa_os\n"
            "def _acceptance_trace(phase,error=None,exit_code=None,stderr_kind=None):\n"
            "    try:\n"
            f"        with open(_qa_os.path.join({str(trace_dir)!r},str(_qa_os.getpid())+'.jsonl'),'a',encoding='utf-8') as log:\n"
            "            log.write(_qa_json.dumps({'phase':phase,'errorType':type(error).__name__ if error else None,'winerror':getattr(error,'winerror',None),'exitCode':exit_code,'stderrKind':stderr_kind})+'\\n')\n"
            "    except OSError:pass\n"
            "_acceptance_trace('python_started')\n")
    worker.write_text(prefix+source,encoding='utf-8')
    core=companion/'core.py';core_source=core.read_text(encoding='utf-8')
    spawn="    subprocess.Popen([sys.executable,str(APP/'worker.py')],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True,**options)"
    if core_source.count(spawn)!=1:raise RuntimeError('Cannot safely instrument the staged host for startup diagnosis.')
    diagnostic=("    _acceptance_trace('before_spawn')\n"
        f"    _qa_error_path=_qa_os.path.join({str(trace_dir)!r},'stderr-'+str(_qa_os.getpid()))\n"
        "    with open(_qa_error_path,'wb') as _qa_error:\n"
        "        _qa_child=subprocess.Popen([sys.executable,str(APP/'worker.py')],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=_qa_error,close_fds=True,**options)\n"
        "        _acceptance_trace('spawn_returned')\n"
        "        try:_qa_code=_qa_child.wait(timeout=2)\n"
        "        except subprocess.TimeoutExpired:_qa_code=None\n"
        "    try:\n"
        "        with open(_qa_error_path,'rb') as _qa_stream:_qa_stderr=_qa_stream.read(65536).lower()\n"
        "        _qa_kind=next((name for name,marker in [('module_not_found',b'modulenotfounderror'),('import_error',b'importerror'),('permission_error',b'permissionerror'),('fatal_python',b'fatal python error'),('open_failed',b\"can't open file\"),('dll_load',b'dll load failed')] if marker in _qa_stderr),None)\n"
        "    except OSError:_qa_kind='unreadable'\n"
        "    _acceptance_trace('after_wait',exit_code=_qa_code,stderr_kind=_qa_kind)")
    core_source=core_source.replace(spawn,diagnostic,1)
    core.write_text(prefix.replace("str(_qa_os.getpid())+'.jsonl'","'host-'+str(_qa_os.getpid())+'.jsonl'").replace("_acceptance_trace('python_started')\n",'')+core_source,encoding='utf-8')
    return trace_dir


def worker_startup_diagnostics(trace_dir):
    traces=[]
    for path in sorted(trace_dir.glob('*.jsonl'))[:50]:
        try:
            entries=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()[:20]]
            traces.append(entries)
        except (OSError,ValueError):traces.append([{'phase':'unreadable'}])
    return traces


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', required=True, type=Path)
    parser.add_argument('--extension', required=True, type=Path, help='Firefox XPI; temporary unless --signed is specified')
    parser.add_argument('--artifacts', required=True, type=Path)
    parser.add_argument('--firefox', type=Path)
    parser.add_argument('--geckodriver', type=Path)
    parser.add_argument('--signed', action='store_true', help='Test a signed XPI as a normal non-temporary installation')
    args = parser.parse_args()
    if sys.platform != 'win32':parser.error('This test requires an actual Windows machine.')
    import winreg
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.support.ui import Select, WebDriverWait

    payload=args.payload.resolve(strict=True);xpi=args.extension.resolve(strict=True)
    artifacts=args.artifacts.resolve();artifacts.mkdir(parents=True,exist_ok=True)
    runtime=payload/'runtime/python.exe';install=payload/'installer/install_payload.py'
    ffmpeg=payload/'tools/ffmpeg.exe';ffprobe=payload/'tools/ffprobe.exe'
    for path in (runtime,install,ffmpeg,ffprobe,payload/'tools/yt-dlp.exe'):
        if not path.is_file():raise RuntimeError('Missing packaged tool: '+str(path))
    with zipfile.ZipFile(xpi) as package:
        manifest=json.loads(package.read('manifest.json'))
    if manifest.get('browser_specific_settings',{}).get('gecko',{}).get('id') != EXTENSION_ID:
        raise RuntimeError('XPI Firefox ID does not match the native host allowlist.')
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY):
            raise RuntimeError('Existing Firefox native-host registration found; refusing to overwrite it.')
    except FileNotFoundError:pass

    with tempfile.TemporaryDirectory(prefix='lessonshelf-win-acceptance-') as temp:
        root=Path(temp);stage=root/'staging';stage.mkdir();media=root/'sample.mp4'
        subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=size=1280x720:rate=24',
                        '-f','lavfi','-i','sine=frequency=440','-t','8','-c:v','libx264',
                        '-preset','ultrafast','-c:a','aac',str(media)],check=True,timeout=90)
        subprocess.run([str(runtime),'-B','-I',str(install),'--payload',str(payload),'--stage-root',str(stage)],
                       check=True,capture_output=True,text=True,timeout=180)
        base=stage/'AppData/Local/LessonShelf';native=base/'native-host.json';app=base/'app'
        registration=json.loads(native.read_text(encoding='utf-8'))
        if registration.get('name')!=HOST or registration.get('allowed_extensions')!=[EXTENSION_ID]:
            raise RuntimeError('Staged host manifest is not bound to the intended Firefox extension.')
        launcher=Path(registration['path'])
        if not launcher.is_file() or launcher.resolve()!=(app/'launch-host.exe').resolve():
            raise RuntimeError('Native host launcher is missing or outside the staged app.')
        for relative in ('runtime/python.exe','tools/yt-dlp.exe','tools/ffmpeg.exe','tools/ffprobe.exe','companion/worker.py'):
            if not (app/relative).is_file():raise RuntimeError('Installed payload is missing '+relative)

        check_worker_crash_isolation(app/'runtime/python.exe',app/'companion',root)
        print('Worker crash isolation passed',flush=True)

        request_counts={"HEAD":0,"GET":0}
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):self.serve(False)
            def do_GET(self):self.serve(True)
            def serve(self,body):
                if self.path!='/sample.mp4':self.send_error(404);return
                request_counts[self.command]=request_counts.get(self.command,0)+1
                size=media.stat().st_size;start=0;header=self.headers.get('Range','')
                if header.startswith('bytes='):
                    try:start=int(header[6:].split('-',1)[0] or '0')
                    except ValueError:self.send_error(416);return
                if start>=size:self.send_error(416);return
                self.send_response(206 if header else 200);self.send_header('Content-Type','video/mp4')
                self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(size-start))
                if header:self.send_header('Content-Range',f'bytes {start}-{size-1}/{size}')
                self.end_headers()
                if body:
                    try:
                        with media.open('rb') as f:
                            f.seek(start)
                            while data:=f.read(32768):self.wfile.write(data);self.wfile.flush();time.sleep(.04)
                    except (BrokenPipeError,ConnectionResetError):pass
            def log_message(self,*_):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        registry_written=False;driver=None;status_history=[]
        trace_dir=None
        try:
            check_packaged_worker(app/'runtime/python.exe',app/'companion',app/'tools',root,f'http://127.0.0.1:{server.server_port}/sample.mp4')
            request_counts.update(HEAD=0,GET=0)
            trace_dir=trace_staged_worker(app/'companion',root)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,KEY) as key:
                winreg.SetValueEx(key,'',0,winreg.REG_SZ,str(native))
            registry_written=True
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as key:
                assert winreg.QueryValueEx(key,'')[0]==str(native)
            options=Options();options.add_argument('-headless')
            if args.firefox:options.binary_location=str(args.firefox.resolve(strict=True))
            service=Service(executable_path=str(args.geckodriver.resolve(strict=True)) if args.geckodriver else None, service_args=['--allow-system-access','--log','debug'], log_output=str(artifacts/'geckodriver.log'))
            driver=webdriver.Firefox(options=options,service=service)
            print('Firefox started',flush=True)
            addon=driver.install_addon(str(xpi),temporary=not args.signed)
            if addon!=EXTENSION_ID:raise RuntimeError('Firefox installed a different extension ID.')
            # Read the UUID assigned by this disposable Firefox profile.
            driver.set_context('chrome')
            uuids=driver.execute_script("return Services.prefs.getStringPref('extensions.webextensions.uuids');")
            driver.set_context('content')
            uuid=json.loads(uuids)[EXTENSION_ID];popup=f'moz-extension://{uuid}/popup.html'
            driver.get(popup);wait=WebDriverWait(driver,30)
            wait.until(lambda d:d.find_element(By.ID,'paste').is_displayed())
            driver.find_element(By.ID,'paste').click()
            driver.find_element(By.ID,'url').send_keys(f'http://127.0.0.1:{server.server_port}/sample.mp4')
            driver.find_element(By.CSS_SELECTOR,'#settings-panel summary').click()
            Select(driver.find_element(By.ID,'captions')).select_by_value('off')
            assert Select(driver.find_element(By.ID,'quality')).first_selected_option.get_attribute('value')=='720'
            assert Select(driver.find_element(By.ID,'output-format')).first_selected_option.get_attribute('value')=='standard'
            driver.find_element(By.ID,'download').click()
            # Accept only the extension's own permission panel in this disposable profile.
            driver.set_context('chrome')
            with contextlib.suppress(Exception):
                WebDriverWait(driver,5).until(lambda d:d.execute_script("return !!(window.PopupNotifications && PopupNotifications.panel && PopupNotifications.panel.firstElementChild && PopupNotifications.panel.state==='open');"))
                driver.execute_script("let n=PopupNotifications.panel.firstElementChild;if(n && n.button)n.button.click();")
            driver.set_context('content')
            allowed=driver.execute_async_script("let done=arguments[arguments.length-1];browser.permissions.contains({data_collection:['browsingActivity','websiteContent']}).then(done,()=>done(false));")
            print('Firefox companion permission granted:',allowed,flush=True)
            if not allowed:raise RuntimeError('Firefox did not grant the expected extension permission; test did not enqueue.')
            observed_progress=False;deadline=time.monotonic()+180;queued_since=None
            while time.monotonic()<deadline:
                status=driver.find_element(By.ID,'status').text
                if not status_history or status_history[-1]!=status:
                    status_history.append(status[:300]);status_history=status_history[-40:];print('Popup status:',status[:300] or '(empty)',flush=True)
                progress=driver.find_element(By.ID,'download-progress')
                observed_progress |= progress.is_displayed()
                if 'Saved' in status:break
                if any(x in status.lower() for x in ('could not','failed','not connected','did not respond')):raise RuntimeError('Download failed: '+status)
                database=base/'queue.sqlite'
                if database.is_file():
                    try:
                        with contextlib.closing(sqlite3.connect('file:'+database.as_posix()+'?mode=ro',uri=True,timeout=3)) as db:
                            row=db.execute('SELECT status,attempts FROM jobs ORDER BY created LIMIT 1').fetchone()
                    except sqlite3.OperationalError:row=None
                    if row and row==('queued',0):
                        if queued_since is None:queued_since=time.monotonic()
                        elif time.monotonic()-queued_since>25:raise RuntimeError('Firefox queued the test job, but its worker did not start within 25 seconds.')
                    else:queued_since=None
                time.sleep(.1)
            else:raise RuntimeError('Timed out waiting for an actual saved download.')
            if not observed_progress:raise RuntimeError('No progress indicator was observed during the local transfer.')
            driver.save_screenshot(str(artifacts/'firefox-saved.png'))
            driver.get(popup);wait.until(lambda d:d.find_element(By.ID,'downloads').is_displayed())
            driver.find_element(By.ID,'downloads').click()
            wait.until(lambda d:'Saved' in d.find_element(By.ID,'jobs').text)
            jobs=driver.find_element(By.ID,'jobs').text
            if 'Show in Finder' not in jobs and 'Show in folder' not in jobs:raise RuntimeError('Saved job has no reveal action.')
            driver.save_screenshot(str(artifacts/'firefox-reopened-queue.png'))
            driver.find_element(By.ID,'back').click()
            driver.find_element(By.CSS_SELECTOR,'#help-panel summary').click()
            driver.find_element(By.ID,'doctor').click()
            wait.until(lambda d:'yt-dlp:' in d.find_element(By.ID,'doctor-result').text)
            tools=driver.find_element(By.ID,'doctor-result').text
            for required in ('yt-dlp: available','ffmpeg: available','ffprobe: available'):
                if required not in tools:raise RuntimeError('Bundled required tool did not pass the real tool check: '+required)
            optional=app/'tools/N_m3u8DL-RE.exe'
            if optional.exists():
                if 'N_m3u8DL-RE: available; checked per video' not in tools:
                    raise RuntimeError('Bundled optional engine did not pass the real tool check.')
                hidden=optional.with_name(optional.name+'.acceptance-hidden')
                if hidden.exists():raise RuntimeError('Refusing to overwrite an existing staged test file.')
                optional.rename(hidden)
                try:
                    driver.find_element(By.ID,'doctor').click()
                    wait.until(lambda d:'N_m3u8DL-RE: not found' in d.find_element(By.ID,'doctor-result').text)
                finally:hidden.rename(optional)
            elif 'N_m3u8DL-RE: not found' not in tools:
                raise RuntimeError('Missing optional engine was not reported honestly.')
            driver.save_screenshot(str(artifacts/'firefox-tool-check.png'))
            files=list((stage/'Downloads/youtube-downloads').glob('*.mp4'))
            if len(files)!=1:raise RuntimeError('Expected exactly one published MP4; found '+str(len(files)))
            report=json.loads(subprocess.run([str(ffprobe),'-v','error','-show_streams','-show_format','-of','json',str(files[0])],check=True,capture_output=True,text=True,timeout=30).stdout)
            video=next(s for s in report['streams'] if s['codec_type']=='video');audio=next(s for s in report['streams'] if s['codec_type']=='audio')
            if (video.get('codec_name'),video.get('pix_fmt'),audio.get('codec_name'))!=('h264','yuv420p','aac') or min(video['width'],video['height'])>720:
                raise RuntimeError('Output codecs or dimensions do not meet the standard profile.')
            subprocess.run([str(ffmpeg),'-v','error','-xerror','-i',str(files[0]),'-f','null','-'],check=True,timeout=120)
            result={'platform':'Windows x64','browser':'Firefox headless','addon':'signed' if args.signed else 'temporary',
                    'progress_observed':observed_progress,'reopened_queue':True,'worker_crash_isolation':True,'required_tools':True,'optional_engine_missing_check':True,'codec':'H.264 yuv420p + AAC',
                    'width':video['width'],'height':video['height'],'duration':report['format'].get('duration')}
            (artifacts/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(result))
        except Exception as error:
            # This profile, queue and video are created by this test. Never dump URLs,
            # environment variables or arbitrary engine output into CI artifacts.
            failure={'error':str(error)[:500],'statusHistory':status_history,'httpRequests':request_counts}
            if trace_dir:failure['workerStartup']=worker_startup_diagnostics(trace_dir)
            database=base/'queue.sqlite'
            if database.is_file():
                try:
                    with contextlib.closing(sqlite3.connect('file:'+database.as_posix()+'?mode=ro',uri=True,timeout=3)) as db:
                        rows=db.execute('SELECT status, progress, attempts FROM jobs ORDER BY created').fetchall()
                    failure['jobs']=[{'status':status,'progress':progress,'attempts':attempts} for status,progress,attempts in rows]
                except Exception as diagnostic_error:failure['queueReadError']=type(diagnostic_error).__name__
            if driver:
                with contextlib.suppress(Exception):
                    driver.set_context('content');driver.save_screenshot(str(artifacts/'firefox-failure.png'))
                    failure['primaryText']=driver.find_element(By.ID,'download').text[:100]
            (artifacts/'failure.json').write_text(json.dumps(failure,indent=2)+'\n',encoding='utf-8')
            print('Acceptance failure diagnostics:',json.dumps(failure),flush=True)
            raise
        finally:
            if driver:
                with contextlib.suppress(Exception):driver.quit()
            try:
                stop_staged_processes(root,app)
            finally:
                if trace_dir:
                    (artifacts/'worker-startup.json').write_text(json.dumps(worker_startup_diagnostics(trace_dir),indent=2)+'\n',encoding='utf-8')
                server.shutdown();server.server_close();thread.join(timeout=5)
                if registry_written:
                    try:
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as key:current=winreg.QueryValueEx(key,'')[0]
                        if current==str(native):winreg.DeleteKey(winreg.HKEY_CURRENT_USER,KEY)
                        else:raise RuntimeError('Native-host registration changed during the test; it was preserved.')
                    except FileNotFoundError:pass
    return 0

if __name__=='__main__':raise SystemExit(main())
