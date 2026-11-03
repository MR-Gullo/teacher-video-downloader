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

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):self.serve(False)
            def do_GET(self):self.serve(True)
            def serve(self,body):
                if self.path!='/sample.mp4':self.send_error(404);return
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
        registry_written=False;driver=None
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,KEY) as key:
                winreg.SetValueEx(key,'',0,winreg.REG_SZ,str(native))
            registry_written=True
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as key:
                assert winreg.QueryValueEx(key,'')[0]==str(native)
            options=Options();options.add_argument('-headless');options.add_argument('-remote-allow-system-access')
            if args.firefox:options.binary_location=str(args.firefox.resolve(strict=True))
            service=Service(executable_path=str(args.geckodriver.resolve(strict=True))) if args.geckodriver else Service()
            driver=webdriver.Firefox(options=options,service=service)
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
            if not allowed:raise RuntimeError('Firefox did not grant the expected extension permission; test did not enqueue.')
            observed_progress=False;deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                status=driver.find_element(By.ID,'status').text
                progress=driver.find_element(By.ID,'download-progress')
                observed_progress |= progress.is_displayed()
                if 'Saved' in status:break
                if any(x in status.lower() for x in ('could not','failed','not connected')):raise RuntimeError('Download failed: '+status)
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
                    'progress_observed':observed_progress,'reopened_queue':True,'required_tools':True,'optional_engine_missing_check':True,'codec':'H.264 yuv420p + AAC',
                    'width':video['width'],'height':video['height'],'duration':report['format'].get('duration')}
            (artifacts/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(result))
        finally:
            if driver:
                with contextlib.suppress(Exception):driver.quit()
            server.shutdown();server.server_close();thread.join(timeout=5)
            if registry_written:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as key:current=winreg.QueryValueEx(key,'')[0]
                    if current==str(native):winreg.DeleteKey(winreg.HKEY_CURRENT_USER,KEY)
                    else:raise RuntimeError('Native-host registration changed during the test; it was preserved.')
                except FileNotFoundError:pass
    return 0

if __name__=='__main__':raise SystemExit(main())
