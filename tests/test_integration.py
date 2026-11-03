"""Real SQLite/worker/native IPC + HTTP Range fixture; downloader is an explicit stub.
This does NOT prove yt-dlp or N_m3u8DL-RE compatibility on real services.
"""
import hashlib,http.server,json,os,signal,struct,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'companion'))
import core
STUB='''#!{python}
import os,sys,time,urllib.request
from pathlib import Path
args=sys.argv[1:]; out=Path(args[args.index('-o')+1].replace('%(ext)s','mp4'));part=out.with_suffix('.mp4.part');part.parent.mkdir(parents=True,exist_ok=True)
if out.exists():sys.exit(0)
n=part.stat().st_size if part.exists() else 0
request=urllib.request.Request(args[-1],headers={{'Range':'bytes='+str(n)+'-'}} if n else {{}})
with urllib.request.urlopen(request,timeout=5) as r:
 if n and r.status!=206:n=0
 with part.open('ab' if n else 'wb') as f:
  while True:
   chunk=r.read(4096)
   if not chunk:break
   f.write(chunk);f.flush();os.fsync(f.fileno());time.sleep(.025)
part.replace(out)
'''
class Integration(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();cls.base=Path(cls.temp.name);cls.video=cls.base/'fixture.mp4'
  subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=24','-f','lavfi','-i','sine=frequency=440','-t','5','-c:v','libx264','-preset','ultrafast','-c:a','aac',str(cls.video)],check=True)
  cls.payload=cls.video.read_bytes();cls.ranges=[]
  class Handler(http.server.BaseHTTPRequestHandler):
   def do_GET(self):
    r=self.headers.get('Range');cls.ranges.append(r);start=int(r.split('=')[1].split('-')[0]) if r else 0
    self.send_response(206 if r else 200);self.send_header('Content-Length',str(len(cls.payload)-start));self.send_header('Accept-Ranges','bytes')
    if r:self.send_header('Content-Range',f'bytes {start}-{len(cls.payload)-1}/{len(cls.payload)}')
    self.end_headers()
    try:self.wfile.write(cls.payload[start:])
    except (BrokenPipeError,ConnectionResetError):pass
   def log_message(self,*_):pass
  cls.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=cls.server.serve_forever,daemon=True).start()
  cls.bin=cls.base/'bin';cls.bin.mkdir();stub=cls.bin/'yt-dlp';stub.write_text(STUB.format(python=sys.executable));stub.chmod(0o700)
 @classmethod
 def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.temp.cleanup()
 def setUp(self):
  self.state=self.base/('state-'+str(time.time_ns()));self.output=self.state/'output';core.STATE=self.state;self.workers=[]
  self.env=os.environ|{'TVD_STATE_DIR':str(self.state),'YTDL_OUTPUT_DIR':str(self.output),'PATH':str(self.bin)+os.pathsep+os.environ['PATH']}
 def tearDown(self):
  for p in self.workers:
   if p.poll() is None:p.terminate();p.wait(timeout=10)
   if p.stderr:p.stderr.close()
 def worker(self):
  p=subprocess.Popen([sys.executable,str(ROOT/'companion/worker.py')],env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE);self.workers.append(p);return p
 def job(self,output_format='original'):return core.handle({'op':'enqueue','jobs':[{'outputFormat':output_format,'url':f'http://127.0.0.1:{self.server.server_port}/fixture.mp4','title':'Fixture','copy':'none','captions':False}]},False)['jobs'][0]['id']
 def status(self):return core.handle({'op':'status'},False)['jobs'][0]
 def wait(self,predicate,seconds=20):
  deadline=time.time()+seconds
  while time.time()<deadline:
   if predicate():return
   time.sleep(.05)
  self.fail('Timeout: '+str(self.status()))
 def test_pause_resume_range_and_original_hash(self):
  id=self.job();self.worker();partial=self.state/'jobs'/id/'source.mp4.part';self.wait(lambda:partial.exists() and partial.stat().st_size>8192)
  core.handle({'op':'pause','id':id},False);time.sleep(.4);saved=partial.stat().st_size;self.assertGreater(saved,0)
  core.handle({'op':'resume','id':id},False);self.wait(lambda:self.status()['status']=='complete')
  self.assertIn('bytes='+str(saved)+'-',self.ranges)
  result=next(Path(p) for p in self.status()['files'] if p.endswith('.mp4'));self.assertEqual(hashlib.sha256(result.read_bytes()).digest(),hashlib.sha256(self.payload).digest())
 def test_standard_default_publishes_one_compatible_file_and_retains_source(self):
  id=self.job('standard');self.worker();self.wait(lambda:self.status()['status'] in ('complete','failed'),seconds=30)
  state=self.status();self.assertEqual(state['status'],'complete',state['message']);self.assertEqual(len(state['files']),1)
  source=self.state/'jobs'/id/'source.mp4';self.assertEqual(hashlib.sha256(source.read_bytes()).digest(),hashlib.sha256(self.payload).digest())
  result=Path(state['files'][0]);self.assertEqual(result.suffix,'.mp4')
  meta=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(result)],check=True,capture_output=True).stdout)
  v=next(x for x in meta['streams'] if x['codec_type']=='video');a=next(x for x in meta['streams'] if x['codec_type']=='audio')
  self.assertEqual((v['codec_name'],v['pix_fmt'],a['codec_name']),('h264','yuv420p','aac'))
 def test_termination_restart_requires_resume(self):
  id=self.job();p=self.worker();partial=self.state/'jobs'/id/'source.mp4.part';self.wait(lambda:partial.exists() and partial.stat().st_size>8192)
  p.terminate();p.wait(timeout=10);self.assertEqual(self.status()['status'],'paused');saved=partial.stat().st_size
  self.worker();time.sleep(.3);self.assertEqual(self.status()['status'],'paused')
  core.handle({'op':'resume','id':id},False);self.wait(lambda:self.status()['status']=='complete');self.assertIn('bytes='+str(saved)+'-',self.ranges)
 def test_sigkill_lock_and_recovery(self):
  id=self.job();p=self.worker();partial=self.state/'jobs'/id/'source.mp4.part';self.wait(lambda:partial.exists() and partial.stat().st_size>8192)
  p.kill();p.wait(timeout=10)
  other=self.worker();other.wait(timeout=5);self.assertEqual(self.status()['status'],'running')
  source=partial.with_suffix('');self.wait(lambda:source.exists())
  time.sleep(.3);self.worker();self.wait(lambda:self.status()['status']=='paused')
  core.handle({'op':'resume','id':id},False);self.wait(lambda:self.status()['status']=='complete')
 def test_native_framed_roundtrip(self):
  req=json.dumps({'op':'doctor'}).encode();p=subprocess.run([sys.executable,str(ROOT/'companion/host.py')],input=struct.pack('=I',len(req))+req,capture_output=True,env=self.env,timeout=10)
  length=struct.unpack('=I',p.stdout[:4])[0];data=json.loads(p.stdout[4:4+length]);self.assertTrue(data['ok']);self.assertIn('ffmpeg',data['doctor']);self.assertEqual(p.stderr,b'')
if __name__=='__main__':unittest.main()
