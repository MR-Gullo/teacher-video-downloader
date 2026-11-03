import concurrent.futures,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'companion'))
import core,worker
class Worker(unittest.TestCase):
 def test_clip_duration_mismatch_never_publishes(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);core.STATE=root;worker.STATE=root;worker.OUTPUT=root/'out';db=core.setup()
   url='https://www.youtube.com/watch?v=abcdefghijk';core.handle({'op':'enqueue','jobs':[{'url':url,'clip':{'start':2,'end':6,'duration':10},'captions':False}]},False);row=db.execute('SELECT * FROM jobs').fetchone()
   dest=root/'jobs'/row['id']/'standard-output.mp4';info={'format':{'duration':'10'},'streams':[{'codec_type':'video','width':640,'height':360,'avg_frame_rate':'25/1'},{'codec_type':'audio'}]}
   def run(db,id,argv,lockfd,*args,**kwargs):
    if argv[0]=='yt-dlp':(root/'jobs'/id/'source.mp4').write_bytes(b'fixture')
    if argv[0]=='encode':dest.write_bytes(b'wrong duration')
    return 0
   with patch.object(worker,'run',side_effect=run),patch.object(worker,'probe',return_value=info),patch.object(worker,'standard_plan',return_value=(['encode'],dest,info)),patch.object(worker,'validate_copy',return_value=True):
    with self.assertRaisesRegex(RuntimeError,'not published'):worker.process(db,row,1)
   self.assertFalse((root/'out').exists());self.assertEqual(db.execute('SELECT files FROM jobs').fetchone()[0],'[]');db.close()
 def test_legacy_job_keeps_provenance_private_on_retry(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);core.STATE=root;worker.STATE=root;worker.OUTPUT=root/'output';db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video','captions':False}]},False)
   row=db.execute('SELECT * FROM jobs').fetchone();data=json.loads(row['data']);del data['outputFormat']
   db.execute('UPDATE jobs SET data=? WHERE id=?',(json.dumps(data),row['id']));db.commit()
   def execute(db,id,argv,lockfd,**kwargs):
    if argv[0]=='yt-dlp':(root/'jobs'/id/'source.mp4').write_bytes(b'fixture')
    return 0
   info={'streams':[{'codec_type':'video','width':1280,'height':720},{'codec_type':'audio'}]}
   with patch.object(worker,'run',side_effect=execute),patch.object(worker,'probe',return_value=info):
    worker.process(db,db.execute('SELECT * FROM jobs').fetchone(),1)
    first=db.execute('SELECT status,files FROM jobs').fetchone();self.assertEqual(first['status'],'complete')
    saved=json.loads(first['files']);self.assertEqual(len(saved),1);self.assertEqual(Path(saved[0]).suffix,'.mp4')
    self.assertTrue((root/'jobs'/row['id']/'provenance.json').is_file())
    self.assertEqual(list((root/'output').glob('*.json')),[])
    db.execute("UPDATE jobs SET status='queued' WHERE id=?",(row['id'],));db.commit()
    worker.process(db,db.execute('SELECT * FROM jobs').fetchone(),1)
    self.assertEqual(json.loads(db.execute('SELECT files FROM jobs').fetchone()[0]),saved)
    self.assertEqual(len(list((root/'output').glob('*.mp4'))),1)
    self.assertEqual(list((root/'output').glob('*.json')),[])
   db.close()
 def test_atomic_publish_collision_and_idempotence(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);a=root/'a.mp4';b=root/'b.mp4';a.write_bytes(b'a'*100000);b.write_bytes(b'b'*100000);out=root/'out'
   with concurrent.futures.ThreadPoolExecutor(2) as pool:
    files=list(pool.map(lambda src:worker.publish(src,out,'00_Test'),[a,b]))
   self.assertEqual(len(set(files)),2);self.assertEqual({Path(p).read_bytes() for p in files},{a.read_bytes(),b.read_bytes()})
   self.assertEqual(worker.publish(a,out,'00_Test'),files[0]);self.assertFalse(list(out.glob('.tvd-publish-*')))
 def test_threaded_pipe_reader_reports_progress_and_failure_category(self):
  import sqlite3
  with tempfile.TemporaryDirectory() as d:
   core.STATE=Path(d);db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video'}]},False)
   row=db.execute('SELECT * FROM jobs').fetchone();core.update(db,row['id'],status='running');diagnostic=[]
   command=[sys.executable,'-c',"import sys,time;print('TVD: 42%',flush=True);time.sleep(.1);print('HTTP Error 429',flush=True);sys.exit(1)"]
   with patch.object(worker.subprocess,'CREATE_NEW_PROCESS_GROUP',0,create=True):
    self.assertEqual(worker.run_windows(db,row['id'],command,'running',diagnostic),1)
   self.assertEqual(db.execute('SELECT progress FROM jobs').fetchone()[0],42)
   self.assertIn('rate_limited',diagnostic);db.close()
 def test_cancel_at_engine_exit_is_not_completed(self):
  with tempfile.TemporaryDirectory() as d:
   core.STATE=Path(d);worker.STATE=core.STATE;db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/video','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
   def cancelled(*args,**kwargs):core.update(db,r['id'],status='cancelled');return 0
   with patch.object(worker,'run',side_effect=cancelled):worker.process(db,r,1)
   self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()[0],'cancelled');db.close()
 def test_unsupported_page_fails_without_retry_or_leaking_output(self):
  import os
  with tempfile.TemporaryDirectory() as d:
   core.STATE=Path(d);worker.STATE=core.STATE;db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/page','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
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
    core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/video','verifiedManifest':True,'quality':'720','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone();engines=[]
    def argv(data,*args):engines.append(data['engine']);return [data['engine']]
    def fake_run(db,id,argv,lockfd,**kwargs):
     if argv[0]=='n':kwargs['diagnostic'].append(first);return 1
     (root/'jobs'/id/'ytdlp-fallback'/'source.mp4').write_bytes(b'fixture');return 0
    with patch.object(worker,'choose_engine',return_value='n'),patch.object(worker,'n_preflight',return_value=True),patch.object(worker.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'')),patch.object(worker,'engine_argv',side_effect=argv),patch.object(worker,'run',side_effect=fake_run),patch.object(worker,'probe',return_value={'streams':[{'codec_type':'video','width':1280,'height':720},{'codec_type':'audio'}]}):worker.process(db,r,1)
    row=db.execute('SELECT status,attempts FROM jobs').fetchone()
    self.assertEqual(row['attempts'],1)
    if first=='unsupported_option':self.assertEqual(engines,['n','yt-dlp']);self.assertEqual(row['status'],'complete')
    else:self.assertEqual(engines,['n']);self.assertEqual(row['status'],'failed')
    db.close()
 def test_known_engine_console_crash_falls_back_without_exposing_output(self):
  self.assertIn('engine_console_error',worker.output_categories(b'Unhandled exception: Spectre.Console.LiveRenderable'))
  self.assertNotIn('engine_console_error',worker.output_categories(b'normal engine error'))
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);core.STATE=root;worker.STATE=root;worker.OUTPUT=root/'output';db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/video','verifiedManifest':True,'captions':False}]},False);row=db.execute('SELECT * FROM jobs').fetchone();engines=[]
   def argv(data,*args):engines.append(data['engine']);return [data['engine']]
   def run(db,id,args,lockfd,**kwargs):
    if args[0]=='n':kwargs['diagnostic'].append('engine_console_error');return 1
    (root/'jobs'/id/'ytdlp-fallback'/'source.mp4').write_bytes(b'fixture');return 0
   info={'streams':[{'codec_type':'video','width':1280,'height':720},{'codec_type':'audio'}]}
   with patch.object(worker,'choose_engine',return_value='n'),patch.object(worker,'n_preflight',return_value=True),patch.object(worker.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'')),patch.object(worker,'engine_argv',side_effect=argv),patch.object(worker,'run',side_effect=run),patch.object(worker,'probe',return_value=info):worker.process(db,row,1)
   self.assertEqual(engines,['n','yt-dlp']);self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()[0],'complete');db.close()
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
   core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/video','verifiedManifest':True,'captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone();engines=[]
   def argv(data,*args):engines.append(data['engine']);return [data['engine']]
   def done(db,id,argv,lockfd,**kwargs):
    (root/'jobs'/id/'source.mp4').write_bytes(b'fixture');return 0
   with patch.object(worker,'choose_engine',return_value='n'),patch.object(worker,'n_preflight',return_value=False),patch.object(worker.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'')),patch.object(worker,'engine_argv',side_effect=argv),patch.object(worker,'run',side_effect=done),patch.object(worker,'probe',return_value={'streams':[{'codec_type':'video','width':1280,'height':720},{'codec_type':'audio'}]}):worker.process(db,r,1)
   self.assertEqual(engines,['yt-dlp']);self.assertEqual(db.execute('SELECT status,attempts FROM jobs').fetchone()[:],('complete',1));db.close()
 def test_failed_media_sample_never_publishes(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);core.STATE=root;worker.STATE=root;worker.OUTPUT=root/'output';db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/video','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
   def execute(db,id,argv,lockfd,**kwargs):
    if argv[0]=='yt-dlp':(root/'jobs'/id/'source.mp4').write_bytes(b'fixture');return 0
    return 1
   with patch.object(worker,'run',side_effect=execute),patch.object(worker,'probe',return_value={'streams':[{'codec_type':'video','width':1280,'height':720},{'codec_type':'audio'}]}):
    with self.assertRaisesRegex(RuntimeError,'sample decoding'):worker.process(db,r,1)
   self.assertEqual(db.execute('SELECT files FROM jobs').fetchone()[0],'[]');self.assertFalse((root/'output').exists());db.close()
 def test_standard_conversion_failure_retains_source_without_publishing(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);core.STATE=root;worker.STATE=root;worker.OUTPUT=root/'output';db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video','outputFormat':'standard','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
   def execute(db,id,argv,lockfd,*args,**kwargs):
    if argv[0]=='yt-dlp':(root/'jobs'/id/'source.mp4').write_bytes(b'fixture');return 0
    if argv[0]=='encode':return 1
    return 0
   info={'streams':[{'codec_type':'video','width':640,'height':360},{'codec_type':'audio'}]}
   with patch.object(worker,'run',side_effect=execute),patch.object(worker,'probe',return_value=info),patch.object(worker,'standard_plan',return_value=(['encode'],root/'jobs'/r['id']/'standard-output.mp4',info)):
    with self.assertRaisesRegex(RuntimeError,'original retained'):worker.process(db,r,1)
   self.assertTrue((root/'jobs'/r['id']/'source.mp4').exists());self.assertFalse((root/'output').exists());db.close()
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
   core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/video','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
   def execute(db,id,argv,lockfd,**kwargs):
    if argv[0]=='yt-dlp':(root/'jobs'/id/'source.mp4').write_bytes(b'fixture')
    return 0
   with patch.object(worker,'run',side_effect=execute),patch.object(worker,'source_is_silent',return_value=True),patch.object(worker,'probe',return_value={'streams':[{'codec_type':'video','width':480,'height':492}]}):worker.process(db,r,1)
   row=db.execute('SELECT status,message,files FROM jobs').fetchone();self.assertEqual(row['status'],'complete-warning');self.assertIn('no audio',row['message']);self.assertTrue(json.loads(row['files']));db.close()
 def test_only_explicit_subtitle_rate_limit_retries_without_subtitles(self):
  self.assertIn('subtitle_rate_limited',worker.output_categories(b"ERROR: Unable to download video subtitles for en: HTTP Error 429: Too Many Requests"))
  self.assertNotIn('subtitle_rate_limited',worker.output_categories(b'[info] subtitles available\nERROR: Unable to download video data: HTTP Error 429'))
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);core.STATE=root;worker.STATE=root;worker.OUTPUT=root/'output';db=core.setup();core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/video','captions':True}]},False);r=db.execute('SELECT * FROM jobs').fetchone();calls=[]
   def execute(db,id,argv,lockfd,**kwargs):
    if argv[0]=='yt-dlp':
     calls.append(argv)
     if len(calls)==1:kwargs['diagnostic'].extend(['rate_limited','subtitle_rate_limited']);return 1
     (root/'jobs'/id/'source.mp4').write_bytes(b'fixture')
    return 0
   with patch.object(worker,'run',side_effect=execute),patch.object(worker,'probe',return_value={'streams':[{'codec_type':'video','width':1280,'height':720},{'codec_type':'audio'}]}):worker.process(db,r,1)
   row=db.execute('SELECT status,message,attempts FROM jobs').fetchone();self.assertEqual(row['status'],'complete-warning');self.assertIn('captions could not be fetched',row['message']);self.assertEqual(row['attempts'],1);self.assertEqual(len(calls),2);self.assertIn('--write-auto-subs',calls[0]);self.assertNotIn('--write-auto-subs',calls[1]);db.close()
 def test_media_rate_limit_never_falls_back_even_if_subtitle_was_limited(self):
  output=(b"ERROR: Unable to download video subtitles for en: HTTP Error 429: Too Many Requests\n"
          b"ERROR: Unable to download video data: HTTP Error 429: Too Many Requests")
  categories=worker.output_categories(output);self.assertIn('subtitle_rate_limited',categories);self.assertIn('media_rate_limited',categories)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);core.STATE=root;worker.STATE=root;db=core.setup();core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/video','captions':True}]},False);r=db.execute('SELECT * FROM jobs').fetchone();calls=[]
   def run_once(db,id,argv,lockfd,**kwargs):calls.append(argv);kwargs['diagnostic'].extend(categories);return 1
   with patch.object(worker,'run',side_effect=run_once):worker.process(db,r,1)
   self.assertEqual(len(calls),1);self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()[0],'failed');db.close()
 def test_rate_limit_is_not_retried_or_treated_as_url_text(self):
  self.assertIn('rate_limited',worker.output_categories(b'ERROR: HTTP Error 429: Too Many Requests'))
  self.assertNotIn('rate_limited',worker.output_categories(b'Loading https://example.com/video?token=429'))
  with tempfile.TemporaryDirectory() as d:
   core.STATE=Path(d);worker.STATE=core.STATE;db=core.setup();core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/video'}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
   def rate_limited(*args,**kwargs):kwargs['diagnostic'].append('rate_limited');return 1
   with patch.object(worker,'run',side_effect=rate_limited):worker.process(db,r,1)
   row=db.execute('SELECT status,message,attempts FROM jobs').fetchone();self.assertEqual(row['status'],'failed');self.assertIn('rate-limit',row['message']);self.assertEqual(row['attempts'],1);db.close()
 def test_orientation_aware_quality_limit_and_unknown_dimensions(self):
  for width,height,allowed in ((1280,720,True),(720,1280,True),(1920,1080,False),(None,720,False)):
   with self.subTest(width=width,height=height),tempfile.TemporaryDirectory() as d:
    root=Path(d);core.STATE=root;worker.STATE=root;worker.OUTPUT=root/'output';db=core.setup();core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/video','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
    def execute(db,id,argv,lockfd,**kwargs):
     if argv[0]=='yt-dlp':(root/'jobs'/id/'source.mp4').write_bytes(b'fixture')
     return 0
    with patch.object(worker,'run',side_effect=execute),patch.object(worker,'probe',return_value={'streams':[{'codec_type':'video','width':width,'height':height},{'codec_type':'audio'}]}):
     if allowed:worker.process(db,r,1);self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()[0],'complete')
     else:
      with self.assertRaisesRegex(RuntimeError,'quality limit'):worker.process(db,r,1)
    db.close()
 def test_quality_limit_rejects_oversize_output(self):
  with tempfile.TemporaryDirectory() as d:
   core.STATE=Path(d);worker.STATE=core.STATE;db=core.setup()
   core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/video','quality':'720','captions':False}]},False);r=db.execute('SELECT * FROM jobs').fetchone()
   def pretend_download(*args,**kwargs):
    work=Path(d)/'jobs'/r['id'];(work/'source.mp4').write_bytes(b'fixture');return 0
   with patch.object(worker,'run',side_effect=pretend_download),patch.object(worker,'probe',return_value={'streams':[{'codec_type':'video','width':1920,'height':1080},{'codec_type':'audio'}]}):
    with self.assertRaisesRegex(RuntimeError,'quality limit'):worker.process(db,r,1)
   self.assertEqual(db.execute('SELECT files FROM jobs').fetchone()[0],'[]');db.close()
 def test_status_is_native_message_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   core.STATE=Path(d)
   for n in range(2):core.handle({'op':'enqueue','jobs':[{'outputFormat':'original','url':'https://example.com/'+str(n*50+i)+'x'*8000,'title':'測'*100} for i in range(50)]},False)
   self.assertLess(len(json.dumps(core.handle({'op':'status'},False)).encode()),512*1024)
if __name__=='__main__':unittest.main()
