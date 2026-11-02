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
    if diagnostic is not None and b'unsupported url' in buf.lower():diagnostic.append('unsupported_url')
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

def process(db,r,lockfd):
    id=r['id'];d=json.loads(r['data']);work=STATE/'jobs'/id;work.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not transition(db,id,r['status'],status='running',message='Starting locally',attempts=r['attempts']+1):return
    help_text=None
    if d['engine']=='n':
        p=subprocess.run(['N_m3u8DL-RE','--help'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=15);help_text=p.stdout.decode(errors='replace')
        update(db,id,message='Advanced engine: retries preserve files, but restart may re-download segments')
    argv=engine_argv(d,work,help_text)
    diagnostic=[]
    code=run(db,id,argv,lockfd,diagnostic=diagnostic)
    if code is None or not active(db,id,'running'):return
    if code:
        if 'unsupported_url' in diagnostic:
            transition(db,id,'running',status='failed',message='This page is not supported by the downloader. Try Find media for a direct file; some sites do not expose downloadable media. Partial files retained.')
            return
        if r['attempts']<2:
            transition(db,id,'running',status='retrying',next_at=time.time()+min(60,2**(r['attempts']+1)),message='Network/engine failure; bounded retry pending. Partials retained. Expired URLs may need refreshing.');return
        raise RuntimeError('Engine failed after 3 attempts. Original/partial files retained. Check access, URL expiry and dependency versions; no DRM bypass is supported.')
    sources=[p for p in work.glob('source.*') if p.suffix.lower() in ('.mkv','.mp4','.webm','.m4a','.mp3','.opus','.mov','.ts') and p.is_file()]
    if not sources:raise RuntimeError('Engine reported success but no output media was found')
    source=max(sources,key=lambda p:p.stat().st_size);info=probe(source)
    if not info.get('streams'):raise RuntimeError('Empty media result')
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
