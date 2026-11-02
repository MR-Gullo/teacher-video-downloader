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
 def test_status_is_native_message_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   core.STATE=Path(d)
   for n in range(2):core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/'+str(n*50+i)+'x'*8000,'title':'測'*100} for i in range(50)]},False)
   self.assertLess(len(json.dumps(core.handle({'op':'status'},False)).encode()),512*1024)
if __name__=='__main__':unittest.main()
