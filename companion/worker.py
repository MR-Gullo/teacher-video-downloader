#!/usr/bin/env python3
import fcntl, hashlib, json, os, re, select, shutil, signal, subprocess, sys, tempfile, time
from pathlib import Path
from core import APP, STATE, OUTPUT, setup, update, engine_argv, safe_name
from media import probe, copy_plan, validate_copy
STOP=False
CHILD=None

def stop(*_):
    global STOP
    STOP=True
    if CHILD and CHILD.poll() is None:
        try:os.killpg(CHILD.pid,signal.SIGTERM)
        except ProcessLookupError:pass

signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)

def output_categories(output):
    # URL tokens and asset identifiers are not status codes or error messages.
    text=re.sub(rb'https?://[^\s"<>]+',b'[url]',output.lower())
    categories=[]
    if b'unsupported url' in text:categories.append('unsupported_url')
    if re.search(rb'(?:http(?:/\d(?:\.\d)?)?(?:\s+error)?|status(?:\s+code)?|response(?:\s+code)?)\s*[:=]?\s*(?:401|403)\b',text) or any(x in text for x in (b'unauthorized',b'forbidden')):categories.append('access_denied')
    if any(x in text for x in (b'widevine',b'playready',b'drm protected',b'drm protection',b'encrypted content',b'geoblock',b'geo-block',b'not available in your country',b'451 unavailable')):categories.append('protected')
    if any(x in text for x in (b'unrecognized option',b'unknown option',b'unrecognized command or argument')):categories.append('unsupported_option')
    return categories

def run(db,id,argv,lockfd,phase='running',diagnostic=None):
    global CHILD
    # Engine inherits flock: even SIGKILL of worker cannot permit concurrent writer.
    CHILD=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True,pass_fds=(lockfd,))
    os.set_blocking(CHILD.stdout.fileno(),False);buf=b'';last=0
    while CHILD.poll() is None:
        row=db.execute('SELECT status FROM jobs WHERE id=?',(id,)).fetchone()
        if STOP or row[0]!=phase:
            try:os.killpg(CHILD.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:CHILD.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(CHILD.pid,signal.SIGKILL);CHILD.wait()
            return None
        ready,_,_=select.select([CHILD.stdout],[],[],.2)
        if ready:
            chunk=CHILD.stdout.read(8192) or b'';buf=(buf+chunk)[-16384:]
            # Never persist arbitrary engine output: it can contain signed URLs/tokens.
            matches=re.findall(rb'TVD:\s*([0-9.]+)%',buf)
            if matches and time.time()-last>.5:
                update(db,id,progress=min(99,float(matches[-1])),message='Downloading');last=time.time();buf=b''
    # Drain output written immediately before exit; retain only a fixed category.
    try:buf=(buf+(CHILD.stdout.read() or b''))[-16384:]
    except BlockingIOError:pass
    if diagnostic is not None:
        lower=re.sub(rb'https?://[^\s"<>]+',b'[url]',buf.lower())
        diagnostic.extend(output_categories(lower))
    return CHILD.returncode

def active(db,id,phase):
    return not STOP and db.execute('SELECT status FROM jobs WHERE id=?',(id,)).fetchone()[0]==phase

def transition(db,id,old,**kw):
    cur=db.execute('UPDATE jobs SET '+','.join(k+'=?' for k in kw)+' WHERE id=? AND status=?', [*kw.values(),id,old]);db.commit()
    return cur.rowcount==1

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.digest()

def publish(src,folder,prefix):
    # Complete staging file, fsync, then hard-link atomically without replacing anything.
    # Stable job-specific name and content comparison make crash retries idempotent.
    folder.mkdir(parents=True,exist_ok=True)
    for i in range(10000):
        target=folder/(prefix+('' if i==0 else f' ({i})')+src.suffix)
        if target.exists():
            if target.is_file() and target.stat().st_size==src.stat().st_size and digest(target)==digest(src):return str(target)
            continue
        fd,tmp=tempfile.mkstemp(prefix='.tvd-publish-',dir=folder)
        try:
            with os.fdopen(fd,'wb') as f,src.open('rb') as inp:
                shutil.copyfileobj(inp,f);f.flush();os.fsync(f.fileno())
            try:os.link(tmp,target)
            except FileExistsError:continue
            return str(target)
        finally:os.unlink(tmp)
    raise RuntimeError('Too many filename collisions')

def choose_engine(d):
    if d.get('engine')!='auto':return d['engine']
    if not d.get('verifiedManifest'):return 'yt-dlp'
    known=Path.home()/'Library/Application Support/Teacher Video Downloader/tools/N_m3u8DL-RE-0.6.0-beta'
    expected='c332b463aa42975c25217d56a51a2ea32fddfd86b4ae8338a8f7416b0bc196e7'
    try:
        if known.is_file() and os.access(known,os.X_OK) and hashlib.sha256(known.read_bytes()).hexdigest()==expected:
            p=subprocess.run([str(known),'--help'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=15)
            text=p.stdout.decode(errors='replace')
            if p.returncode==0 and all(x in text for x in ('--disable-update-check','--write-meta-json','-sv','-sa')):
                d['_n_path']=str(known);d['_known_n']=True;return 'n'
    except (OSError,subprocess.TimeoutExpired):pass
    path=shutil.which('N_m3u8DL-RE')
    if not path:return 'yt-dlp'
    try:
        p=subprocess.run([path,'--help'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=15)
        text=p.stdout.decode(errors='replace')
        required=('--no-config','--disable-update-check','--write-meta-json','--vod-select-parts','-sv','-sa','-ds')
        if p.returncode==0 and all(x in text for x in required):d['_n_path']=path;return 'n'
    except (OSError,subprocess.TimeoutExpired):pass
    return 'yt-dlp'

def n_preflight(d,work,help_text):
    # Parse only: no segments or output media. Bound a broken local runtime.
    argv=engine_argv(d,work,help_text)
    argv[argv.index('--http-request-timeout')+1]='8'
    try:
        p=subprocess.run(argv+['--skip-download','true'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=12)
    except (OSError,subprocess.TimeoutExpired):return False
    if any(x in output_categories(p.stdout) for x in ('access_denied','protected')):
        raise RuntimeError('Access was denied or the media is protected. No alternate engine was tried.')
    return p.returncode==0

def process(db,r,lockfd):
    id=r['id'];d=json.loads(r['data']);work=STATE/'jobs'/id;work.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not transition(db,id,r['status'],status='running',message='Starting locally',attempts=r['attempts']+1):return
    automatic=d.get('engine')=='auto'
    d['engine']=choose_engine(d)
    help_text=None
    if d['engine']=='n':
        try:
            p=subprocess.run([d.get('_n_path','N_m3u8DL-RE'),'--help'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=15)
            if p.returncode:raise OSError('Engine unavailable')
            help_text=p.stdout.decode(errors='replace')
            if automatic and not n_preflight(d,work,help_text):
                d['engine']='yt-dlp';update(db,id,message='Using the compatible local downloader');argv=engine_argv(d,work)
            else:argv=engine_argv(d,work,help_text)
        except RuntimeError as e:
            if not automatic or str(e)!='N_m3u8DL-RE version lacks required privacy controls':raise
            d['engine']='yt-dlp';argv=engine_argv(d,work)
        except (OSError,subprocess.TimeoutExpired):
            if not automatic:raise
            d['engine']='yt-dlp';argv=engine_argv(d,work)
        else:
            if d['engine']=='n':update(db,id,message='Advanced engine: retries preserve files, but restart may re-download segments')
    else:argv=engine_argv(d,work)
    diagnostic=[]
    try:code=run(db,id,argv,lockfd,diagnostic=diagnostic)
    except OSError:
        if not automatic or d['engine']!='n':raise
        d['engine']='yt-dlp';code=run(db,id,engine_argv(d,work),lockfd,diagnostic=diagnostic)
    if code and automatic and d['engine']=='n' and 'unsupported_option' in diagnostic and not any(x in diagnostic for x in ('access_denied','protected')) and active(db,id,'running'):
        d['engine']='yt-dlp';update(db,id,message='Trying the compatible local downloader')
        diagnostic=[];code=run(db,id,engine_argv(d,work),lockfd,diagnostic=diagnostic)
    if code is None or not active(db,id,'running'):return
    if code:
        if 'access_denied' in diagnostic or 'protected' in diagnostic:
            transition(db,id,'running',status='failed',message='Access was denied or the media is protected. No alternate engine was tried; partial files retained.')
            return
        if 'unsupported_url' in diagnostic:
            transition(db,id,'running',status='failed',message='This page is not supported by the downloader. Try a direct video link; some sites do not expose downloadable media. Partial files retained.')
            return
        if r['attempts']<2:
            transition(db,id,'running',status='retrying',next_at=time.time()+min(60,2**(r['attempts']+1)),message='Network/engine failure; bounded retry pending. Partials retained. Expired URLs may need refreshing.');return
        raise RuntimeError('Engine failed after 3 attempts. Original/partial files retained. Check access, URL expiry and dependency versions; no DRM bypass is supported.')
    sources=[p for p in work.glob('source.*') if p.suffix.lower() in ('.mkv','.mp4','.webm','.m4a','.mp3','.opus','.mov','.ts') and p.is_file()]
    if not sources:raise RuntimeError('Engine reported success but no output media was found')
    source=max(sources,key=lambda p:p.stat().st_size);info=probe(source)
    if not info.get('streams'):raise RuntimeError('Empty media result')
    if not any(x.get('codec_type')=='audio' for x in info['streams']):
        raise RuntimeError('The downloaded media has no audio. Original retained in the local job folder.')
    if not d['audio'] and d['quality']!='best':
        video=[x for x in info['streams'] if x.get('codec_type')=='video']
        cap=int(d['quality'])
        if not video or any(not x.get('height') or x['height']>cap for x in video):
            raise RuntimeError('Downloaded video does not meet the selected quality limit. Original retained in the local job folder.')
    try:duration=float(info.get('format',{}).get('duration',0) or 0)
    except (TypeError,ValueError):duration=0
    points=sorted(set([0,max(0,duration/2-1),max(0,duration-3)])) if duration>6 else [0]
    for point in points:
        args=['ffmpeg','-nostdin','-v','error','-xerror','-ss',str(point),'-i',str(source),'-t','2']
        if not d['audio']:args+=['-map','0:v:0']
        args+=['-map','0:a:0','-f','null','-']
        result=run(db,id,args,lockfd)
        if result is None or not active(db,id,'running'):return
        if result:raise RuntimeError('Downloaded media failed sample decoding. Original retained in the local job folder.')
    if not transition(db,id,'running',status='processing',progress=99,message='Validating original and preparing classroom copy'):return
    files=[];warning='';course=OUTPUT/d['course'] if d['course'] else OUTPUT
    # Publishing original first ensures captions/copy failures cannot destroy it.
    prefix=f"{db.execute('SELECT count(*) FROM jobs WHERE created < ?',(r['created'],)).fetchone()[0]:02d}_{safe_name(d['title'])}_{id[:8]}"
    if not active(db,id,'processing'):return
    files.append(publish(source,course,prefix+'_original'))
    update(db,id,files=json.dumps(files))
    if not d['audio'] and d['copy']!='none':
        try:
            plan,note=copy_plan(source,d['copy'],d['pageUrl'])
            if plan:
                args,dest,source_info=plan
                if dest.exists():dest.unlink() # only our generated, non-original temp copy
                code=run(db,id,args,lockfd,'processing')
                if code is None:return
                if code:raise RuntimeError('Copy encoding failed; original kept')
                if validate_copy(source_info,dest,source,d['copy'],lambda a:run(db,id,a,lockfd,'processing')):
                    if not active(db,id,'processing'):return
                    files.append(publish(dest,course,prefix+('_classroom' if d['copy']=='classroom' else '_storage-av1')))
                else:dest.unlink();warning='AV1 copy discarded: less than 15% saving. Original kept.'
            else:warning=note
        except InterruptedError:return
        except Exception:warning='Classroom/storage copy failed validation or encoding. Original is safe; inspect dependencies and source format.'
    if not active(db,id,'processing'):return
    if d['captions'] and not any(x.get('codec_type')=='subtitle' for x in info['streams']) and not d['audio']:
        warning=(warning+' ' if warning else '')+'No embedded English captions were found; no automatic cloud transcription was attempted.'
    if not warning:
        for p in work.glob('*.srt'):p.unlink() # only remove sidecars after successful embedded result
    # Store provenance without signed query credentials.
    provenance={'source':d['pageUrl'],'engine':d['engine'],'captions_requested':d['captions']}
    meta=work/'provenance.json';meta.write_text(json.dumps(provenance,indent=2));files.append(publish(meta,course,prefix+'_source'))
    transition(db,id,'processing',status='complete-warning' if warning else 'complete',progress=100,message=warning or 'Ready for class. Original retained.',files=json.dumps(files))

def main():
    db=setup();lock=open(STATE/'worker.lock','a');os.chmod(STATE/'worker.lock',0o600)
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return
    db.execute("UPDATE jobs SET status='paused', message='Worker interrupted. Partial files retained; Resume to continue.' WHERE status IN ('running','processing')");db.commit()
    idle=time.time()
    while not STOP:
        r=db.execute("SELECT * FROM jobs WHERE status IN ('queued','retrying') AND next_at<=? ORDER BY created LIMIT 1",(time.time(),)).fetchone()
        if r:
            idle=time.time()
            try:process(db,r,lock.fileno())
            except FileNotFoundError:
                for phase in ('running','processing'):transition(db,r['id'],phase,status='failed',message='Required engine or FFmpeg is missing. Open dependency check and install it.')
            except Exception as e:
                for phase in ('running','processing'):transition(db,r['id'],phase,status='failed',message=str(e) if isinstance(e,RuntimeError) else 'Local processing failed; partials retained. Check disk space and dependencies.')
        elif time.time()-idle>15 and not db.execute("SELECT 1 FROM jobs WHERE status='retrying'").fetchone():break
        else:time.sleep(.25)
    if STOP:db.execute("UPDATE jobs SET status='paused', message='Companion stopped; partial files retained' WHERE status IN ('running','processing')");db.commit()
    db.close()

if __name__=='__main__':main()
