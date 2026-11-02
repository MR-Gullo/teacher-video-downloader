import json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'companion'))
import core
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
 def test_argv(self):
  d=core.normalize({'url':'https://x/a.m3u8'});a=core.engine_argv(d,Path('/tmp/job'))
  for flag in ['--continue','--abort-on-unavailable-fragments','--ignore-config','--no-cookies-from-browser']:self.assertIn(flag,a)
  self.assertIn('b[height<=?1080]',a[a.index('-f')+1]);self.assertEqual(a[-2: ],['--',d['url']]);d['engine']='n';a=core.engine_argv(d,Path('/tmp/job'))
  self.assertNotIn('--continue',a);self.assertIn('--disable-update-check',a);self.assertIn('--no-config',a)
 def test_no_secrets_status(self):
  r=core.handle({'op':'enqueue','jobs':[{'url':'https://x/a?token=secret'}]},False)
  self.assertNotIn('secret',json.dumps(r))
if __name__=='__main__':unittest.main()
