#!/usr/bin/env python3
"""User-scoped install. Run on the Mac only after reviewing this source."""
import argparse,json,os,re,shutil,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--chrome-id',help='32-letter ID from chrome://extensions');p.add_argument('--firefox',action='store_true');p.add_argument('--output-dir',type=Path,help='Persist a custom downloads directory in the launcher');p.add_argument('--uninstall',action='store_true');a=p.parse_args()
if sys.platform!='darwin':p.error('This installer is for macOS; it has not run on your Mac')
home=Path.home();base=home/'Library/Application Support/Teacher Video Downloader';install=base/'app';name='org.teacher.video_downloader'
locations=[home/'Library/Application Support/Google/Chrome/NativeMessagingHosts'/f'{name}.json',home/'Library/Application Support/Mozilla/NativeMessagingHosts'/f'{name}.json']
if a.uninstall:
    for path in locations:
        if path.exists():
            try:d=json.loads(path.read_text())
            except Exception:continue
            if d.get('name')==name and d.get('path')==str(install/'launch-host'):path.unlink();print('Removed',path)
    if install.exists():shutil.rmtree(install)
    print('Queue, partial files and downloads kept. Stop running jobs before uninstalling.');sys.exit()
if not a.chrome_id and not a.firefox:p.error('Pass --chrome-id ID and/or --firefox')
if a.chrome_id and not re.fullmatch('[a-p]{32}',a.chrome_id):p.error('Invalid Chrome extension ID')
for enabled,path in [(a.chrome_id,locations[0]),(a.firefox,locations[1])]:
    if enabled and path.exists():p.error(f'Refusing to replace an existing host manifest: {path}')
source=Path(__file__).resolve().parents[1]/'companion';base.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(base,0o700)
if install.exists():p.error('Already installed. Pause jobs, uninstall (data kept), then install the updated version')
shutil.copytree(source,install,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
# Absolute interpreter prevents browser PATH selecting another Python. Dependency PATH covers Homebrew.
launcher=install/'launch-host';launcher.write_text('#!'+sys.executable+'\nimport os,sys\nos.environ["PATH"]="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:"+os.environ.get("PATH","")\nos.execv(sys.executable,[sys.executable,'+repr(str(install/'host.py'))+']+sys.argv[1:])\n');launcher.chmod(0o700)
if a.output_dir:
    custom=str(a.output_dir.expanduser().resolve());launcher.write_text(launcher.read_text().replace('os.execv(', 'os.environ["YTDL_OUTPUT_DIR"]='+repr(custom)+'\nos.execv('))
common={'name':name,'description':'Local teacher video queue','path':str(launcher),'type':'stdio'}
for enabled,path,allow in [(a.chrome_id,locations[0],{'allowed_origins':[f'chrome-extension://{a.chrome_id}/']}),(a.firefox,locations[1],{'allowed_extensions':['teacher-video-downloader@local.invalid']})]:
    if enabled:
        if path.exists():p.error(f'Refusing to replace an existing host manifest: {path}')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(common|allow,indent=2));path.chmod(0o600);print('Installed',path)
print('Installed local companion. No launch agent/server added. Open extension → Dependency check.')
