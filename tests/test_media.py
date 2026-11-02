import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'companion'))
import media
class Media(unittest.TestCase):
 def test_10bit_not_stream_copied(self):
  info={'streams':[{'codec_type':'video','codec_name':'h264','height':1080,'pix_fmt':'yuv444p10le'}]}
  with patch.object(media,'probe',return_value=info):plan,_=media.copy_plan(Path('/tmp/source.mkv'),'classroom')
  args=plan[0];self.assertEqual(args[args.index('-c:v')+1],'libx264')
 def test_real_classroom_captions_chapters_framerate(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'sub.srt').write_text('1\n00:00:00,000 --> 00:00:00,800\nHello classroom\n');(p/'meta').write_text(';FFMETADATA1\ntitle=Fixture\ncomment=https://example.com/lesson\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=900\ntitle=Opening\n')
   source=p/'source.mkv'
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=24000/1001','-f','lavfi','-i','sine=frequency=440','-i',str(p/'sub.srt'),'-i',str(p/'meta'),'-t','1','-map','0:v','-map','1:a','-map','2:s','-map_metadata','3','-map_chapters','3','-c:v','libx264','-c:a','aac','-c:s','srt',str(source)],check=True)
   plan,_=media.copy_plan(source,'classroom');args,dest,info=plan;subprocess.run(args,check=True)
   self.assertTrue(media.validate_copy(info,dest,source,'classroom'));new=media.probe(dest)
   self.assertEqual(next(s for s in new['streams'] if s['codec_type']=='subtitle')['codec_name'],'mov_text');self.assertTrue(source.exists());self.assertEqual(len(new['chapters']),1)
   self.assertEqual(next(s for s in new['streams'] if s['codec_type']=='video')['r_frame_rate'],'24000/1001')
if __name__=='__main__':unittest.main()
