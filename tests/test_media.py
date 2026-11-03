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
 def test_standard_cap_preserves_orientation_without_upscaling(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for size,expected in [('960x540',(640,360)),('540x960',(360,640))]:
    source=root/(size+'.mkv')
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size='+size+':rate=10','-t','0.3','-c:v','libx264','-preset','ultrafast',str(source)],check=True)
    args,dest,info=media.standard_plan(source,'360');dest.unlink(missing_ok=True);subprocess.run(args,check=True)
    video=next(x for x in media.probe(dest)['streams'] if x['codec_type']=='video')
    self.assertEqual((video['width'],video['height']),expected)
 def test_av1_encoder_selection(self):
  from types import SimpleNamespace
  samples=[(' V..... libaom-av1 AOM\n V..... libsvtav1 SVT\n','libaom-av1'),(' V..... libsvtav1 SVT\n','libsvtav1')]
  for text,name in samples:
   with self.subTest(name=name),patch.object(media.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=text)):
    args=media.av1_options();self.assertEqual(args[args.index('-c:v')+1],name)
    self.assertIn('-cpu-used' if name=='libaom-av1' else '-preset',args)
  with patch.object(media.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=' V..... libx264 x264\n')):
   with self.assertRaisesRegex(RuntimeError,'no supported AV1 encoder'):media.av1_options()
 def test_actual_av1_output_validates(self):
  with tempfile.TemporaryDirectory() as tmp:
   source=Path(tmp)/'source.mkv'
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=24','-f','lavfi','-i','sine=frequency=440','-t','0.5','-c:v','libx264','-c:a','aac',str(source)],check=True)
   args,dest,info=media.standard_plan(source,'720',codec='av1');subprocess.run(args,check=True)
   self.assertTrue(media.validate_copy(info,dest,source,'av1-output'));actual=media.probe(dest)
   self.assertEqual(next(s for s in actual['streams'] if s['codec_type']=='video')['codec_name'],'av1')
   self.assertEqual(next(s for s in actual['streams'] if s['codec_type']=='audio')['codec_name'],'aac');self.assertTrue(source.exists())
 def test_standard_mp4_real_codecs(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for codec in ('libx264','libvpx-vp9','libsvtav1'):
    source=root/(codec+'.mkv')
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=24','-f','lavfi','-i','sine=frequency=440','-t','1','-c:v',codec,'-c:a','aac',str(source)],check=True)
    args,dest,info=media.standard_plan(source,'720')
    if dest.exists():dest.unlink()
    subprocess.run(args,check=True)
    self.assertTrue(media.validate_copy(info,dest,source,'standard'))
    result=media.probe(dest);v=next(x for x in result['streams'] if x['codec_type']=='video');a=next(x for x in result['streams'] if x['codec_type']=='audio')
    self.assertEqual((v['codec_name'],v['pix_fmt'],a['codec_name']),('h264','yuv420p','aac'))
    self.assertEqual((v['width'],v['height']),(320,180));self.assertTrue(source.exists())
    self.assertEqual(args[args.index('-c:v')+1],'copy' if codec=='libx264' else 'libx264')
if __name__=='__main__':unittest.main()
