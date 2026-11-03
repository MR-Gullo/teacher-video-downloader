import json,os,re,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'companion'))
import core
from unittest.mock import patch
class Core(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();core.STATE=Path(self.tmp.name)/'state'
 def tearDown(self):self.tmp.cleanup()
 def test_validation(self):
  for url in ['file:///etc/passwd','--exec=touch','https://a:b@example.com/x','https://x/\nfoo','blob:https://x/y']:
   with self.assertRaises(ValueError):core.valid_url(url)
  self.assertEqual(core.valid_url('abcdefghijk'),'https://www.youtube.com/watch?v=abcdefghijk')
 def test_no_path_traversal(self):
  d=core.normalize({'url':'https://example.com/a','course':'../../../../etc','title':'a/b'});self.assertNotIn('/',d['course']);self.assertNotIn('/',d['title'])
 def test_dedupe_and_control(self):
  request={'op':'enqueue','jobs':[{'url':'https://example.com/v'}]}
  core.handle(request,False);r=core.handle(request,False);self.assertEqual(len(r['jobs']),1);id=r['jobs'][0]['id']
  self.assertEqual(core.handle({'op':'pause','id':id},False)['jobs'][0]['status'],'paused')
  self.assertEqual(core.handle({'op':'resume','id':id},False)['jobs'][0]['status'],'queued')
 def test_atomic_batch(self):
  with self.assertRaises(ValueError):core.handle({'op':'enqueue','jobs':[{'url':'https://good.com'},{'url':'file:///bad'}]},False)
  self.assertEqual(core.handle({'op':'status'},False)['jobs'],[])
 def test_reveal_only_recorded_completed_media(self):
  result=core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video'}]},False);id=result['jobs'][0]['id']
  with self.assertRaisesRegex(ValueError,'No completed download'):core.handle({'op':'reveal','id':id},False)
  media=Path(self.tmp.name)/'file.mp4';media.write_bytes(b'fixture');db=core.setup();core.update(db,id,status='complete',files=json.dumps([str(media)]));db.close()
  with patch.object(core.sys,'platform','darwin'),patch.object(core.subprocess,'Popen') as run:
   core.handle({'op':'reveal','id':id,'path':'/etc/passwd'},False)
   self.assertEqual(run.call_args.args[0],['/usr/bin/open','-R',str(media)])
  with self.assertRaisesRegex(ValueError,'No completed download'):core.handle({'op':'reveal','id':'not-a-job'},False)
 def test_doctor_reports_same_optional_engine_lookup(self):
  with patch.object(core,'find_n',return_value=('/verified/versioned/N_m3u8DL-RE',True)):
   n=core.doctor()['N_m3u8DL-RE'];self.assertTrue(n['available']);self.assertEqual(n['path'],'/verified/versioned/N_m3u8DL-RE')
 def test_argv(self):
  d=core.normalize({'url':'https://x/a.m3u8'});a=core.engine_argv(d,Path('/tmp/job'))
  for flag in ['--continue','--abort-on-unavailable-fragments','--ignore-config','--no-cookies-from-browser']:self.assertIn(flag,a)
  self.assertEqual(a[a.index('-S')+1],'res:720,vcodec:h264,acodec:aac');self.assertIn('resolution~=?',a[a.index('-f')+1]);self.assertEqual(a[-2: ],['--',d['url']]);d['engine']='n';a=core.engine_argv(d,Path('/tmp/job'))
  self.assertNotIn('--continue',a);self.assertIn('--disable-update-check',a);self.assertIn('--no-config',a)
 def test_n_quality_filter_accepts_both_orientations(self):
  d=core.normalize({'url':'https://example.com/video.m3u8','engine':'n','quality':'720'});a=core.engine_argv(d,Path('/tmp/job'));pattern=a[a.index('-sv')+1].removeprefix('res=').removesuffix(':for=best')
  for resolution in ('1280x720','720x1280','404x720'):self.assertIsNotNone(re.fullmatch(pattern,resolution))
  for resolution in ('1920x1080','1080x1920'):self.assertIsNone(re.fullmatch(pattern,resolution))
 def test_no_secrets_status(self):
  r=core.handle({'op':'enqueue','jobs':[{'url':'https://x/a?token=secret'}]},False)
  self.assertNotIn('secret',json.dumps(r))
if __name__=='__main__':unittest.main()
