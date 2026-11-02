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
    engine=j.get('engine','yt-dlp'); quality=str(j.get('quality','1080')); copy=j.get('copy','classroom')
    if engine not in ('yt-dlp','n') or quality not in ('1080','720','best') or copy not in ('none','classroom','av1'): raise ValueError('Invalid settings')
    if j.get('cookies') or j.get('headers'): raise ValueError('Authentication transfer is not enabled in this build')
    page=valid_url(j['pageUrl']) if j.get('pageUrl') else u
    return dict(url=u,pageUrl=public_url(page),title=safe_name(j.get('title') or urlsplit(u).hostname),engine=engine,quality=quality,copy=copy,audio=bool(j.get('audio',False)),captions=bool(j.get('captions',True)),course=safe_name(j['course']) if j.get('course') else '')

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

def doctor():
    result={}
    for tool in ('yt-dlp','ffmpeg','ffprobe','N_m3u8DL-RE','aria2c'):
        path=shutil.which(tool)
        result[tool]={'available':bool(path),'path':path}
    result['spokenly']={'available':False,'message':'Not configured. No cloud ASR is invoked. The actual adapter interface and privacy must be verified before integration.'}
    result['outputDir']=str(OUTPUT);result['stateDir']=str(STATE)
    return result

def ensure_worker():
    # Worker flock prevents duplicate workers; detached process survives browser exit.
    subprocess.Popen([sys.executable,str(APP/'worker.py')],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,close_fds=True)

def handle(req, start=True):
    if not isinstance(req,dict): raise ValueError('Invalid request')
    db=setup();op=req.get('op');result={'ok':True}
    try:
        if op=='enqueue':
            jobs=req.get('jobs',[])
            if not isinstance(jobs,list) or not 1<=len(jobs)<=50: raise ValueError('Choose 1–50 videos at a time')
            jobs=[normalize(j) for j in jobs]
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM jobs').fetchone()[0]+len(jobs)>MAX_JOBS: raise ValueError('Queue history limit reached (500); archive the local queue before adding more')
            for d in jobs:
                fingerprint=hashlib.sha256(json.dumps({k:v for k,v in d.items() if k not in ('title','pageUrl')},sort_keys=True).encode()).hexdigest()
                db.execute('INSERT OR IGNORE INTO jobs(id,fingerprint,data,status,created) VALUES(?,?,?,?,?)',(uuid.uuid4().hex,fingerprint,json.dumps(d),'queued',time.time()))
            db.commit()
        elif op in ('pause','resume','cancel','retry'):
            id=req.get('id');r=db.execute('SELECT status,data FROM jobs WHERE id=?',(id,)).fetchone()
            if not r: raise ValueError('Job not found')
            current=r[0]
            if op=='pause' and current in ('queued','running','retrying','processing'): update(db,id,status='paused',message='Paused; partial files retained')
            elif op=='cancel' and current not in ('complete','complete-warning'): update(db,id,status='cancelled',message='Cancelled; partial files retained')
            elif op in ('resume','retry') and current in ('paused','failed','cancelled','retrying'): update(db,id,status='queued',attempts=0,next_at=0,message=('Restart queued; files retained, but N may re-download segments' if json.loads(r['data'])['engine']=='n' else 'Queued using existing partial files'))
        elif op=='doctor':result['doctor']=doctor()
        elif op!='status':raise ValueError('Unknown operation')
        result['jobs']=status(db)
    finally:db.close()
    if start:ensure_worker()
    return result

def engine_argv(d,work, help_text=None):
    if d['engine']=='yt-dlp':
        a=['yt-dlp','--ignore-config','--no-plugin-dirs','--no-remote-components','--no-playlist','--no-overwrites','--continue','--part','--retries','8','--fragment-retries','8','--retry-sleep','http:exp=1:30','--retry-sleep','fragment:exp=1:30','--abort-on-unavailable-fragments','--newline','--progress','--progress-template','download:TVD:%(progress._percent_str)s','--no-write-info-json','--no-cookies-from-browser','--no-cookies','--embed-chapters','--no-embed-info-json','-o',str(work/'source.%(ext)s')]
        if d['audio']:a+=['-f','bestaudio/best','-x','--audio-format','m4a']
        else:
            q=d['quality'];f='bv*+ba/b' if q=='best' else f'bv*[height<={q}]+ba/b[height<={q}]/b[height<=?{q}]'
            a+=['-f',f,'--merge-output-format','mkv']
        if d['captions'] and not d['audio']:a+=['--write-subs','--write-auto-subs','--sub-langs','en.*,en','--convert-subs','srt','--embed-subs']
        return a+['--',d['url']]
    if help_text is not None and any(f not in help_text for f in ('--no-config','--disable-update-check','--write-meta-json')): raise RuntimeError('N_m3u8DL-RE version lacks required privacy controls; install a current official build')
    a=['N_m3u8DL-RE',d['url'],'--no-config','--disable-update-check','--no-log','--write-meta-json','false','--use-system-proxy','false','--save-dir',str(work),'--tmp-dir',str(work/'segments'),'--save-name','source','--thread-count','4','--download-retry-count','8','--http-request-timeout','30','--del-after-done','false','--check-segments-count','true','--no-ansi-color','--auto-select','--vod-select-parts','false','-M','format=mkv:keep=true','-sa','best']
    if d['audio']:a+=['-dv','all']
    elif d['quality']!='best':
        # Explicit upper bound by height, not a fabricated generic continue flag.
        heights='144|240|360|480|540|576|720'+('|900|1080' if d['quality']=='1080' else '')
        a+=['-sv',f'res=^[0-9]+x({heights})$:for=best']
    if d['captions']:a+=['-ss','lang=^(en|eng)(-|$):for=all','--sub-format','SRT']
    else:a+=['-ds','all']
    return a
