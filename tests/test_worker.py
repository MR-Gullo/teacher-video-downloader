import concurrent.futures,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'companion'))
import core,worker
class Worker(unittest.TestCase):
 def test_atomic_publish_collision_and_idempotence(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);a=root/'a.mp4';b=root/'b.mp4';a.write_bytes(b'a'*100000);b.write_bytes(b'b'*100000);out=root/'out'
   with concurrent.futures.ThreadPoolExecutor(2) as pool:
    files=list(pool.map(lambda src:worker.publish(src,out,'00_Test'),[a,b]))
   self.assertEqual(len(set(files)),2);self.assertEqual({Path(p).read_bytes() for p in files},{a.read_bytes(),b.read_bytes()})
   self.assertEqual(worker.publish(a,out,'00_Test'),files[0]);self.assertFalse(list(out.glob('.tvd-publish-*')))
 def test_cancel_at_engine_exit_is_not_completed(self):
  with tempfile.TemporaryDirectory() as d:
   core.STATE=Path(d);worker.STATE=core.STATE;db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
   def cancelled(*args,**kwargs):core.update(db,r['id'],status='cancelled');return 0
   with patch.object(worker,'run',side_effect=cancelled):worker.process(db,r,1)
   self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()[0],'cancelled');db.close()
 def test_unsupported_page_fails_without_retry_or_leaking_output(self):
  import os
  with tempfile.TemporaryDirectory() as d:
   core.STATE=Path(d);worker.STATE=core.STATE;db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/page','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
   fd=os.open(Path(d)/'lock',os.O_CREAT|os.O_RDWR,0o600)
   try:
    with patch.object(worker,'engine_argv',return_value=[sys.executable,'-c',"import sys; print('ERROR: Unsupported URL: https://example.com/?token=secret',file=sys.stderr); sys.exit(1)"]):worker.process(db,r,fd)
    job=db.execute('SELECT status,message,attempts FROM jobs').fetchone()
    self.assertEqual(job['status'],'failed');self.assertEqual(job['attempts'],1);self.assertIn('not supported',job['message']);self.assertNotIn('secret',job['message'])
   finally:os.close(fd);db.close()
 def test_auto_engine_falls_back_only_for_unavailable_engine(self):
  with patch.object(worker.Path,'is_file',return_value=False),patch.object(worker.shutil,'which',return_value=None):
   self.assertEqual(worker.choose_engine({'engine':'auto','verifiedManifest':True}),'yt-dlp')
  with patch.object(worker.shutil,'which',side_effect=AssertionError('must not inspect advanced engine')):
   self.assertEqual(worker.choose_engine({'engine':'auto','verifiedManifest':False}),'yt-dlp')
 def test_unsupported_option_falls_back_in_same_job_but_auth_does_not(self):
  from types import SimpleNamespace
  for first in ('unsupported_option','access_denied'):
   with self.subTest(first=first),tempfile.TemporaryDirectory() as d:
    root=Path(d);core.STATE=root;worker.STATE=root;worker.OUTPUT=root/'output';db=core.setup()
    core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video','verifiedManifest':True,'quality':'720','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone();engines=[]
    def argv(data,*args):engines.append(data['engine']);return [data['engine']]
    def fake_run(db,id,argv,lockfd,**kwargs):
     if argv[0]=='n':kwargs['diagnostic'].append(first);return 1
     (root/'jobs'/id/'source.mp4').write_bytes(b'fixture');return 0
    with patch.object(worker,'choose_engine',return_value='n'),patch.object(worker,'n_preflight',return_value=True),patch.object(worker.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'')),patch.object(worker,'engine_argv',side_effect=argv),patch.object(worker,'run',side_effect=fake_run),patch.object(worker,'probe',return_value={'streams':[{'codec_type':'video','height':720},{'codec_type':'audio'}]}):worker.process(db,r,1)
    row=db.execute('SELECT status,attempts FROM jobs').fetchone()
    self.assertEqual(row['attempts'],1)
    if first=='unsupported_option':self.assertEqual(engines,['n','yt-dlp']);self.assertEqual(row['status'],'complete')
    else:self.assertEqual(engines,['n']);self.assertEqual(row['status'],'failed')
    db.close()
 def test_n_preflight_timeout_falls_back_and_protection_stops(self):
  from types import SimpleNamespace
  d={'engine':'n'}
  with patch.object(worker,'engine_argv',return_value=['N','--http-request-timeout','30']):
   with patch.object(worker.subprocess,'run',side_effect=worker.subprocess.TimeoutExpired('N',12)):
    self.assertFalse(worker.n_preflight(d,Path('/tmp'),None))
   for message in (b'HTTP 403 Forbidden',b'Widevine DRM protected',b'not available in your country'):
    with patch.object(worker.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout=message)):
     with self.assertRaisesRegex(RuntimeError,'protected'):worker.n_preflight(d,Path('/tmp'),None)
   with patch.object(worker.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout=b'Loading URL: https://example.com/asset401403drm?token=401403')):
    self.assertFalse(worker.n_preflight(d,Path('/tmp'),None))
   with patch.object(worker.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout=b'client unavailable')):
    self.assertFalse(worker.n_preflight(d,Path('/tmp'),None))
 def test_auto_preflight_failure_uses_ytdlp_in_same_job(self):
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);core.STATE=root;worker.STATE=root;worker.OUTPUT=root/'output';db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video','verifiedManifest':True,'captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone();engines=[]
   def argv(data,*args):engines.append(data['engine']);return [data['engine']]
   def done(db,id,argv,lockfd,**kwargs):
    (root/'jobs'/id/'source.mp4').write_bytes(b'fixture');return 0
   with patch.object(worker,'choose_engine',return_value='n'),patch.object(worker,'n_preflight',return_value=False),patch.object(worker.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'')),patch.object(worker,'engine_argv',side_effect=argv),patch.object(worker,'run',side_effect=done),patch.object(worker,'probe',return_value={'streams':[{'codec_type':'video','height':720},{'codec_type':'audio'}]}):worker.process(db,r,1)
   self.assertEqual(engines,['yt-dlp']);self.assertEqual(db.execute('SELECT status,attempts FROM jobs').fetchone()[:],('complete',1));db.close()
 def test_failed_media_sample_never_publishes(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);core.STATE=root;worker.STATE=root;worker.OUTPUT=root/'output';db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
   def execute(db,id,argv,lockfd,**kwargs):
    if argv[0]=='yt-dlp':(root/'jobs'/id/'source.mp4').write_bytes(b'fixture');return 0
    return 1
   with patch.object(worker,'run',side_effect=execute),patch.object(worker,'probe',return_value={'streams':[{'codec_type':'video','height':720},{'codec_type':'audio'}]}):
    with self.assertRaisesRegex(RuntimeError,'sample decoding'):worker.process(db,r,1)
   self.assertEqual(db.execute('SELECT files FROM jobs').fetchone()[0],'[]');self.assertFalse((root/'output').exists());db.close()
 def test_silent_source_requires_explicit_metadata(self):
  from types import SimpleNamespace
  d={'url':'https://example.com/video'}
  samples=[({'formats':[{'vcodec':'h264','acodec':'none'}]},True),({'formats':[{'vcodec':'h264','acodec':None}]},False),({'formats':[{'vcodec':'h264','acodec':'none'},{'vcodec':'none','acodec':'aac'}]},False),({'formats':[]},False)]
  for meta,expected in samples:
   with patch.object(worker.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(meta).encode())):self.assertEqual(worker.source_is_silent(d),expected)
 def test_x_unknown_direct_formats_are_probed_before_accepting_silence(self):
  from types import SimpleNamespace
  d={'url':'https://x.com/person/status/123'};meta={'formats':[{'vcodec':'h264','acodec':'none'},{'vcodec':None,'acodec':None,'url':'https://video.twimg.com/example.mp4'}]}
  video=SimpleNamespace(returncode=0,stdout=json.dumps({'streams':[{'codec_type':'video'}]}).encode())
  audio=SimpleNamespace(returncode=0,stdout=json.dumps({'streams':[{'codec_type':'video'},{'codec_type':'audio'}]}).encode())
  for probe,expected in ((video,True),(audio,False)):
   with patch.object(worker.subprocess,'run',side_effect=[SimpleNamespace(returncode=0,stdout=json.dumps(meta).encode()),probe]):self.assertEqual(worker.source_is_silent(d),expected)
  meta['formats'][1]['url']='https://127.0.0.1/private'
  with patch.object(worker.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(meta).encode())):self.assertFalse(worker.source_is_silent(d))
 def test_confirmed_silent_video_is_published_with_warning(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);core.STATE=root;worker.STATE=root;worker.OUTPUT=root/'output';db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
   def execute(db,id,argv,lockfd,**kwargs):
    if argv[0]=='yt-dlp':(root/'jobs'/id/'source.mp4').write_bytes(b'fixture')
    return 0
   with patch.object(worker,'run',side_effect=execute),patch.object(worker,'source_is_silent',return_value=True),patch.object(worker,'probe',return_value={'streams':[{'codec_type':'video','height':492}]}):worker.process(db,r,1)
   row=db.execute('SELECT status,message,files FROM jobs').fetchone();self.assertEqual(row['status'],'complete-warning');self.assertIn('no audio',row['message']);self.assertTrue(json.loads(row['files']));db.close()
 def test_quality_limit_rejects_oversize_output(self):
  with tempfile.TemporaryDirectory() as d:
   core.STATE=Path(d);worker.STATE=core.STATE;db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video','quality':'720','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
   def pretend_download(*args,**kwargs):
    work=Path(d)/'jobs'/r['id'];(work/'source.mp4').write_bytes(b'fixture');return 0
   with patch.object(worker,'run',side_effect=pretend_download),patch.object(worker,'probe',return_value={'streams':[{'codec_type':'video','height':1080},{'codec_type':'audio'}]}):
    with self.assertRaisesRegex(RuntimeError,'quality limit'):worker.process(db,r,1)
   self.assertEqual(db.execute('SELECT files FROM jobs').fetchone()[0],'[]');db.close()
 def test_status_is_native_message_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   core.STATE=Path(d)
   for n in range(2):core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/'+str(n*50+i)+'x'*8000,'title':'測'*100} for i in range(50)]},False)
   self.assertLess(len(json.dumps(core.handle({'op':'status'},False)).encode()),512*1024)
if __name__=='__main__':unittest.main()
