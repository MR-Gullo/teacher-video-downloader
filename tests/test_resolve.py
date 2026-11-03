import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'companion'))
import resolve
class Resolve(unittest.TestCase):
 def test_selects_only_correlated_master_with_duration_and_cap(self):
  master='https://video.example/master.m3u8?token=one';child='https://video.example/720.m3u8?token=two';ad='https://video.example/ad.m3u8'
  docs={master:'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2000,RESOLUTION=1280x720\n'+child+'\n',child:'#EXTM3U\n#EXTINF:60,\nsegment.ts\n#EXT-X-ENDLIST',ad:'#EXTM3U\n#EXTINF:15,\nsegment.ts\n#EXT-X-ENDLIST'}
  self.assertEqual(resolve.resolve([ad,child,master],60,720,docs.get),master)
  self.assertIsNone(resolve.resolve([ad,child,master],15,720,docs.get))
  self.assertIsNone(resolve.resolve([ad,child,master],60,480,docs.get))
 def test_encrypted_and_unrelated_masters_never_selected(self):
  master='https://video.example/master.m3u8';child='https://video.example/child.m3u8';other='https://other.example/master.m3u8';other_child='https://other.example/child.m3u8'
  docs={master:'#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1280x720\n'+child,child:'#EXTM3U\n#EXTINF:60,\na.ts\n#EXT-X-ENDLIST',other:'#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1280x720\n'+other_child,other_child:'#EXTM3U\n#EXTINF:60,\nb.ts\n#EXT-X-ENDLIST'}
  self.assertIsNone(resolve.resolve(list(docs),60,720,docs.get))
  docs[child]='#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="private"\n#EXTINF:60,\na.ts\n#EXT-X-ENDLIST'
  self.assertIsNone(resolve.resolve([master,child],60,720,docs.get))
 def test_fetches_unobserved_variants_and_accepts_proven_aliases(self):
  a='https://video.example/a.m3u8';b='https://video.example/b.m3u8';high='https://video.example/high.m3u8';low='https://video.example/low.m3u8'
  playlist='#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1920x1080\n'+high+'\n#EXT-X-STREAM-INF:RESOLUTION=1280x720\n'+low
  docs={a:playlist,b:playlist,high:'#EXTM3U\n#EXTINF:60,\nhigh.ts\n#EXT-X-ENDLIST',low:'#EXTM3U\n#EXTINF:60,\nlow.ts\n#EXT-X-ENDLIST'}
  self.assertEqual(resolve.resolve([a,b,high],60,720,docs.get),a)
  docs[low]='#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="private"\n#EXTINF:60,\nlow.ts\n#EXT-X-ENDLIST'
  self.assertIsNone(resolve.resolve([a,b,high],60,720,docs.get))
 def test_portrait_rendition_uses_shorter_dimension(self):
  master='https://video.example/master.m3u8';child='https://video.example/portrait.m3u8'
  docs={master:'#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=720x1280\n'+child,child:'#EXTM3U\n#EXTINF:60,\na.ts\n#EXT-X-ENDLIST'}
  self.assertEqual(resolve.resolve([master,child],60,720,docs.get),master)
  self.assertIsNone(resolve.resolve([master,child],60,480,docs.get))
 def test_rejects_local_hosts(self):
  self.assertFalse(resolve.public_target('http://127.0.0.1/private'))
if __name__=='__main__':unittest.main()
