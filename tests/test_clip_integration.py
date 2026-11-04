"""Run the clip path with synthetic media and real local yt-dlp/FFmpeg."""
import contextlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'companion'))
import core,worker

@unittest.skipUnless(all(shutil.which(x) for x in ('yt-dlp','ffmpeg','ffprobe')),'Local media tools unavailable')
class ClipIntegration(unittest.TestCase):
 def test_ytdlp_section_produces_verified_clip(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);video=root/'fixture.mp4'
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=25','-f','lavfi','-i','sine=frequency=440','-t','10','-c:v','libx264','-preset','ultrafast','-g','100','-c:a','aac',str(video)],check=True,timeout=60)
   class Handler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):self.serve(False)
    def do_GET(self):self.serve(True)
    def serve(self,body):
     if self.path!='/fixture.mp4':self.send_error(404);return
     size=video.stat().st_size;start=0;end=size-1;header=self.headers.get('Range','')
     if header.startswith('bytes='):
      a,b=header[6:].split('-',1);start=int(a or 0);end=min(int(b) if b else end,end)
     if start>end:self.send_error(416);return
     self.send_response(206 if header else 200);self.send_header('Content-Type','video/mp4');self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
     if header:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
     self.end_headers()
     if body:
      try:
       with video.open('rb') as f:
        f.seek(start);remaining=end-start+1
        while remaining:
         chunk=f.read(min(65536,remaining))
         if not chunk:break
         self.wfile.write(chunk);remaining-=len(chunk)
      except (BrokenPipeError,ConnectionResetError):pass
    def log_message(self,*args):pass
   server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    with patch.object(core,'STATE',root/'state'),patch.object(worker,'STATE',root/'state'),patch.object(worker,'OUTPUT',root/'out'):
     db=core.setup();url='https://www.youtube.com/watch?v=abcdefghijk'
     core.handle({'op':'enqueue-clip','jobs':[{'url':url,'clip':{'start':2,'end':6,'duration':10},'captions':False}]},False)
     row=db.execute('SELECT * FROM jobs').fetchone();real=worker.engine_argv
     def local_argv(*args,**kwargs):
      argv=real(*args,**kwargs);argv[-1]=f'http://127.0.0.1:{server.server_port}/fixture.mp4';return argv
     fd=os.open(root/'lock',os.O_CREAT|os.O_RDWR,0o600);started=threading.Event();proceed=threading.Event();errors=[];real_run=worker.run
     def slow_run(*args,**kwargs):
      started.set()
      if not proceed.wait(10):raise RuntimeError('Test download was not released')
      return real_run(*args,**kwargs)
     def first_job():
      connection=core.setup()
      try:worker.process(connection,connection.execute('SELECT * FROM jobs WHERE id=?',(row['id'],)).fetchone(),fd)
      except Exception as e:errors.append(e)
      finally:connection.close()
     try:
      with patch.object(worker,'engine_argv',side_effect=local_argv),patch.object(worker,'run',side_effect=slow_run):
       job_thread=threading.Thread(target=first_job);job_thread.start()
       try:
        self.assertTrue(started.wait(10),'first clip did not start')
        before=db.execute('SELECT status,attempts,data FROM jobs WHERE id=?',(row['id'],)).fetchone()
        second=core.handle({'op':'enqueue-clip','jobs':[{'url':url,'clip':{'start':6,'end':9,'duration':10},'captions':False}]},False)['jobIds'][0]
        self.assertNotEqual(second,row['id']);self.assertEqual(tuple(before),tuple(db.execute('SELECT status,attempts,data FROM jobs WHERE id=?',(row['id'],)).fetchone()));self.assertEqual(before['status'],'running')
        self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?',(second,)).fetchone()[0],'queued')
       finally:proceed.set();job_thread.join(timeout=60)
       self.assertFalse(job_thread.is_alive());self.assertEqual(errors,[])
       worker.process(db,db.execute('SELECT * FROM jobs WHERE id=?',(second,)).fetchone(),fd)
     finally:os.close(fd)
     result=db.execute('SELECT status,files FROM jobs').fetchone();self.assertEqual(result['status'],'complete')
     files=json.loads(result['files']);self.assertEqual(len(files),1);output=Path(files[0]);self.assertIn('00h00m02s000-00h00m06s000',output.name)
     info=worker.probe(output);self.assertTrue(worker.clip_duration_ok(info,{'start':2,'end':6,'duration':10}));self.assertTrue(any(s.get('codec_name')=='h264' and s.get('pix_fmt')=='yuv420p' for s in info['streams']));self.assertTrue(any(s.get('codec_name')=='aac' for s in info['streams']))
     def frame(path,seconds):return subprocess.check_output(['ffmpeg','-v','error','-ss',str(seconds),'-i',str(path),'-frames:v','1','-vf','scale=64:36,format=gray','-f','rawvideo','-'],timeout=20)
     for clip_time in (.5,3.5):
      actual=frame(output,clip_time);expected=frame(video,clip_time+2);self.assertEqual(len(actual),len(expected));self.assertLess(sum(abs(a-b) for a,b in zip(actual,expected))/len(actual),15,'Clip frame did not match the selected source section')
     private=json.loads((root/'state/jobs'/row['id']/'provenance.json').read_text());self.assertEqual(private['clip'],{'start':2,'end':6,'duration':10})
     subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(output),'-f','null','-'],check=True,timeout=60)
     later=db.execute('SELECT status,files FROM jobs WHERE id=?',(second,)).fetchone();self.assertEqual(later['status'],'complete');later_file=Path(json.loads(later['files'])[0]);self.assertTrue(worker.clip_duration_ok(worker.probe(later_file),{'start':6,'end':9,'duration':10}));subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(later_file),'-f','null','-'],check=True,timeout=60)
     for clip_time in (.5,2.5):
      actual=frame(later_file,clip_time);expected=frame(video,clip_time+6);self.assertEqual(len(actual),len(expected));self.assertLess(sum(abs(a-b) for a,b in zip(actual,expected))/len(actual),15,'Second clip frame did not match its selected source section')
     self.assertEqual(list((root/'out').glob('*.json')),[]);db.close()
   finally:server.shutdown();server.server_close();thread.join(timeout=5)

if __name__=='__main__':unittest.main()
