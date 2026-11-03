"""Local-only durable queue. No server, shell evaluation, cookie extraction or telemetry."""
import contextlib, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, time, uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

APP = Path(__file__).resolve().parent
STATE = Path(os.environ.get('TVD_STATE_DIR', str(Path.home()/ 'Library/Application Support/Teacher Video Downloader'))).expanduser()
OUTPUT = Path(os.environ.get('YTDL_OUTPUT_DIR', str(Path.home()/'Downloads/youtube-downloads'))).expanduser()
MAX_JOBS = 500

def setup():
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE, 0o700)
    db = sqlite3.connect(STATE/'queue.sqlite', timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, data TEXT NOT NULL, status TEXT NOT NULL, progress REAL DEFAULT 0, message TEXT DEFAULT "", files TEXT DEFAULT "[]", attempts INTEGER DEFAULT 0, next_at REAL DEFAULT 0, created REAL NOT NULL)')
    db.commit()
    return db

def safe_name(s):
    s = re.sub(r'[^\w .-]', '_', str(s), flags=re.UNICODE).strip(' .')[:100]
    return s if s and s not in {'.','..'} else 'Video'

def valid_url(s):
    if not isinstance(s, str) or len(s)>8192 or any(ord(c)<33 for c in s): raise ValueError('Invalid URL')
    if re.fullmatch(r'[\w-]{11}',s): s='https://www.youtube.com/watch?v='+s
    p=urlsplit(s)
    if p.scheme not in ('https','http') or not p.hostname or p.username or p.password: raise ValueError('Only HTTP(S) URLs without embedded credentials are supported')
    return urlunsplit((p.scheme,p.netloc,p.path,p.query,''))

def public_url(s):
    p=urlsplit(s)
    query=''
    if p.hostname in ('www.youtube.com','youtube.com','m.youtube.com'):
        video=parse_qs(p.query).get('v',[''])[0]
        if re.fullmatch(r'[A-Za-z0-9_-]{11}',video):query=urlencode({'v':video})
    return urlunsplit((p.scheme,p.netloc,p.path,query,''))

def normalize(j):
    if not isinstance(j,dict): raise ValueError('Invalid job')
    u=valid_url(j.get('url',''))
    engine=j.get('engine','auto'); quality=str(j.get('quality','720')); copy=j.get('copy','none'); output_format=j.get('outputFormat','standard')
    if engine not in ('yt-dlp','n','auto') or quality not in ('1080','720','best') or copy not in ('none','classroom','av1') or output_format not in ('standard','original','av1'): raise ValueError('Invalid settings')
    if j.get('cookies') or j.get('headers'): raise ValueError('Authentication transfer is not enabled in this build')
    page=valid_url(j['pageUrl']) if j.get('pageUrl') else u
    return dict(url=u,pageUrl=public_url(page),title=safe_name(j.get('title') or urlsplit(u).hostname),engine=engine,quality=quality,copy=copy,outputFormat=output_format,audio=bool(j.get('audio',False)),captions=bool(j.get('captions',True)),course=safe_name(j['course']) if j.get('course') else '',verifiedManifest=bool(j.get('verifiedManifest',False)))

def status(db):
    out=[]
    for r in db.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 100'):
        d=json.loads(r['data']); d['url']=public_url(d['url'])[:512]; d['pageUrl']=d['pageUrl'][:512]
        d.update({k:r[k] for k in ('id','status','progress','message','attempts')});d['files']=[str(p)[:1024] for p in json.loads(r['files'])[:8]];out.append(d)
    # Native messaging has a strict size ceiling. Return newest entries within budget.
    while len(json.dumps(out).encode())>400000 and out:out.pop()
    return out

def update(db,id,**kw):
    allowed={'status','progress','message','files','attempts','next_at'}
    if not set(kw)<=allowed: raise ValueError('Invalid field')
    db.execute('UPDATE jobs SET '+','.join(k+'=?' for k in kw)+' WHERE id=?', [*kw.values(),id]);db.commit()

def find_n():
    known=Path.home()/'Library/Application Support/Teacher Video Downloader/tools/N_m3u8DL-RE-0.6.0-beta'
    expected='c332b463aa42975c25217d56a51a2ea32fddfd86b4ae8338a8f7416b0bc196e7'
    candidates=[]
    try:
        if known.is_file() and os.access(known,os.X_OK) and hashlib.sha256(known.read_bytes()).hexdigest()==expected:candidates.append((str(known),True))
    except OSError:pass
    path=shutil.which('N_m3u8DL-RE')
    if path:candidates.append((path,False))
    for path,known_version in candidates:
        try:
            p=subprocess.run([path,'--help'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=15)
            text=p.stdout.decode(errors='replace')
            required=('--disable-update-check','--write-meta-json','-sv','-sa') if known_version else ('--no-config','--disable-update-check','--write-meta-json','--vod-select-parts','-sv','-sa','-ds')
            if p.returncode==0 and all(x in text for x in required):return path,known_version
        except (OSError,subprocess.TimeoutExpired):pass
    return None,False

def doctor():
    result={}
    for tool in ('yt-dlp','ffmpeg','ffprobe','aria2c'):
        path=shutil.which(tool)
        result[tool]={'available':bool(path),'path':path}
    path,_=find_n();result['N_m3u8DL-RE']={'available':bool(path),'path':path}
    result['spokenly']={'available':False,'message':'Not configured. No cloud ASR is invoked. The actual adapter interface and privacy must be verified before integration.'}
    result['outputDir']=str(OUTPUT);result['stateDir']=str(STATE)
    return result

def ensure_worker():
    # Worker flock prevents duplicate workers; detached process survives browser exit.
    subprocess.Popen([sys.executable,str(APP/'worker.py')],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,close_fds=True)

def handle(req, start=True):
    if not isinstance(req,dict): raise ValueError('Invalid request')
    op=req.get('op')
    if op=='resolve':
        from resolve import resolve
        candidates=req.get('candidates',[])
        if not isinstance(candidates,list) or len(candidates)>24:raise ValueError('Too many media candidates')
        candidates=[valid_url(x) for x in candidates]
        duration=req.get('duration');quality=req.get('quality','720');limit=1080 if quality=='1080' else 720
        found=resolve(candidates,duration,limit)
        return {'ok':True,'url':found}
    db=setup();result={'ok':True}
    try:
        if op=='enqueue':
            jobs=req.get('jobs',[])
            if not isinstance(jobs,list) or not 1<=len(jobs)<=50: raise ValueError('Choose 1–50 videos at a time')
            jobs=[normalize(j) for j in jobs]
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM jobs').fetchone()[0]+len(jobs)>MAX_JOBS: raise ValueError('Queue history limit reached (500); archive the local queue before adding more')
            job_ids=[]
            for d in jobs:
                fingerprint=hashlib.sha256(json.dumps({k:v for k,v in d.items() if k not in ('title','pageUrl')},sort_keys=True).encode()).hexdigest()
                db.execute('INSERT OR IGNORE INTO jobs(id,fingerprint,data,status,created) VALUES(?,?,?,?,?)',(uuid.uuid4().hex,fingerprint,json.dumps(d),'queued',time.time()))
                job_ids.append(db.execute('SELECT id FROM jobs WHERE fingerprint=?',(fingerprint,)).fetchone()[0])
            db.commit();result['jobIds']=job_ids
        elif op in ('pause','resume','cancel','retry'):
            id=req.get('id');r=db.execute('SELECT status,data FROM jobs WHERE id=?',(id,)).fetchone()
            if not r: raise ValueError('Job not found')
            current=r[0]
            if op=='pause' and current in ('queued','running','retrying','processing'): update(db,id,status='paused',message='Paused; partial files retained')
            elif op=='cancel' and current not in ('complete','complete-warning'): update(db,id,status='cancelled',message='Cancelled; partial files retained')
            elif op in ('resume','retry') and current in ('paused','failed','cancelled','retrying'): update(db,id,status='queued',attempts=0,next_at=0,message=('Restart queued; files retained, but N may re-download segments' if json.loads(r['data'])['engine']=='n' else 'Queued using existing partial files'))
        elif op=='reveal':
            row=db.execute('SELECT status,files FROM jobs WHERE id=?',(req.get('id'),)).fetchone()
            if not row or row['status'] not in ('complete','complete-warning'):raise ValueError('No completed download is available to show.')
            files=json.loads(row['files']);target=next((Path(x) for x in files if Path(x).suffix.lower() in ('.mkv','.mp4','.webm','.m4a','.mp3','.opus','.mov','.ts') and Path(x).is_file()),None)
            if not target:raise ValueError('The saved media file could not be found.')
            if sys.platform!='darwin':raise ValueError('Show in Finder is available on Mac.')
            subprocess.Popen(['/usr/bin/open','-R',str(target)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
        elif op=='doctor':result['doctor']=doctor()
        elif op!='status':raise ValueError('Unknown operation')
        result['jobs']=status(db)
    finally:db.close()
    if start:ensure_worker()
    return result

def quality_resolution_pattern(quality):
    bounded=r'([1-9][0-9]?|[1-6][0-9]{2}|7[01][0-9]|720)'
    if quality=='1080':bounded=r'([1-9][0-9]?|[1-9][0-9]{2}|10[0-7][0-9]|1080)'
    return f'^([0-9]+x{bounded}|{bounded}x[0-9]+)$'

def engine_argv(d,work, help_text=None):
    if d['engine'] in ('yt-dlp','auto'):
        a=['yt-dlp','--ignore-config','--no-plugin-dirs','--no-remote-components','--no-playlist','--no-overwrites','--continue','--part','--retries','8','--fragment-retries','8','--retry-sleep','http:exp=1:30','--retry-sleep','fragment:exp=1:30','--abort-on-unavailable-fragments','--newline','--progress','--progress-template','download:TVD:%(progress._percent_str)s','--no-write-info-json','--no-cookies-from-browser','--no-cookies','--embed-chapters','--no-embed-info-json','-o',str(work/'source.%(ext)s')]
        if d['audio']:a+=['-f','bestaudio/best','-x','--audio-format','m4a']
        else:
            q=d['quality'];f='bv*+ba/b'
            if q!='best':
                pattern=quality_resolution_pattern(q);f=f'bv*[resolution~=?"{pattern}"]+ba/b[resolution~=?"{pattern}"]'
            a+=['-f',f,'--merge-output-format','mkv']
            if q!='best':a+=['-S',f'res:{q},vcodec:h264,acodec:aac']
            else:a+=['-S','vcodec:h264,acodec:aac']
        if d['captions'] and not d['audio']:a+=['--write-subs','--write-auto-subs','--sub-langs','en.*,en','--convert-subs','srt','--embed-subs']
        return a+['--',d['url']]
    known=d.get('_known_n',False)
    if help_text is not None and any(f not in help_text for f in (('--disable-update-check','--write-meta-json') if known else ('--no-config','--disable-update-check','--write-meta-json','--vod-select-parts'))): raise RuntimeError('N_m3u8DL-RE version lacks required privacy controls')
    a=[d.get('_n_path','N_m3u8DL-RE'),d['url']]+([] if known else ['--no-config'])+['--disable-update-check','--no-log','--write-meta-json','false','--use-system-proxy','false','--save-dir',str(work),'--tmp-dir',str(work/'segments'),'--save-name','source','--thread-count','4','--download-retry-count','8','--http-request-timeout','30','--del-after-done','false','--check-segments-count','true','--no-ansi-color']+([] if known else ['--vod-select-parts','false'])+['-M','format=mkv:keep=true','-sa','for=best']
    if d['audio']:a+=['-dv','all']
    elif d['quality']=='best':a+=['-sv','for=best']
    elif d['quality']!='best':
        # Bound the shorter dimension for both landscape and portrait renditions.
        a+=['-sv',f"res={quality_resolution_pattern(d['quality'])}:for=best"]
    if d['captions']:a+=['-ss','lang=^(en|eng)(-|$):for=all','--sub-format','SRT']
    else:a+=['-ds','all']
    return a
