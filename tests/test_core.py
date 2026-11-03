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
 def test_status_hides_legacy_json_without_changing_queue(self):
  result=core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video'}]},False);id=result['jobIds'][0]
  recorded=['/videos/item_source.json','/videos/second.JSON','/videos/item.mp4']
  db=core.setup();core.update(db,id,status='complete',files=json.dumps(recorded));db.close()
  self.assertEqual(core.handle({'op':'status'},False)['jobs'][0]['files'],['/videos/item.mp4'])
  db=core.setup();self.assertEqual(json.loads(db.execute('SELECT files FROM jobs WHERE id=?',(id,)).fetchone()[0]),recorded);db.close()
 def test_dedupe_and_control(self):
  request={'op':'enqueue','jobs':[{'url':'https://example.com/v'}]}
  core.handle(request,False);r=core.handle(request,False);self.assertEqual(len(r['jobs']),1);id=r['jobs'][0]['id']
  self.assertEqual(core.handle({'op':'pause','id':id},False)['jobs'][0]['status'],'paused')
  self.assertEqual(core.handle({'op':'resume','id':id},False)['jobs'][0]['status'],'queued')
 def test_atomic_batch(self):
  with self.assertRaises(ValueError):core.handle({'op':'enqueue','jobs':[{'url':'https://good.com'},{'url':'file:///bad'}]},False)
  self.assertEqual(core.handle({'op':'status'},False)['jobs'],[])
 def test_windows_worker_requests_permitted_job_breakaway(self):
  with patch.object(core.sys,'platform','win32'),patch.object(core.subprocess,'CREATE_NEW_PROCESS_GROUP',0x200,create=True),patch.object(core.subprocess,'DETACHED_PROCESS',0x8,create=True),patch.object(core.subprocess,'CREATE_BREAKAWAY_FROM_JOB',0x1000000,create=True),patch.object(core.subprocess,'Popen') as spawn:
   core.ensure_worker();self.assertEqual(spawn.call_args.kwargs['creationflags'],0x1000208)
   spawn.side_effect=PermissionError()
   with self.assertRaisesRegex(ValueError,'job remains queued'):core.ensure_worker()
 def test_worker_starts_only_for_queued_work(self):
  with patch.object(core,'ensure_worker') as spawn,patch.object(core,'doctor',return_value={}):
   core.handle({'op':'doctor'});core.handle({'op':'status'});spawn.assert_not_called()
   result=core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video'}]});id=result['jobIds'][0]
   self.assertEqual(spawn.call_count,1)
   core.handle({'op':'doctor'});self.assertEqual(spawn.call_count,1)
   core.handle({'op':'status'});self.assertEqual(spawn.call_count,2)
   core.handle({'op':'pause','id':id});core.handle({'op':'status'});self.assertEqual(spawn.call_count,2)
   core.handle({'op':'resume','id':id});self.assertEqual(spawn.call_count,3)
 def test_denied_worker_leaves_job_queued(self):
  with patch.object(core,'ensure_worker',side_effect=ValueError('Windows prevented worker startup')):
   with self.assertRaisesRegex(ValueError,'prevented'):core.handle({'op':'enqueue','jobs':[{'url':'https://example.com/video'}]})
  self.assertEqual(core.handle({'op':'status'},False)['jobs'][0]['status'],'queued')
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
 def test_bundled_n_requires_pinned_binary_and_appropriate_flags(self):
  from types import SimpleNamespace
  root=Path(self.tmp.name);app=root/'app';tools=app/'tools';tools.mkdir(parents=True)
  binary=tools/'N_m3u8DL-RE';binary.write_bytes(b'not-the-real-binary');binary.chmod(0o700)
  help_text=b'--disable-update-check --write-meta-json -sv -sa'
  with patch.object(core,'APP',app/'companion'),patch.object(core.Path,'home',return_value=root),patch.object(core.shutil,'which',return_value=None),patch.object(core.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=help_text)):
   for digest in core.KNOWN_N_060:
    with self.subTest(digest=digest),patch.object(core,'n_digest',return_value=digest):
     self.assertEqual(core.find_n(),(str(binary.resolve()),True))
   # A name or a claimed version does not grant the pinned adapter.
   with patch.object(core,'n_digest',return_value='0'*64):self.assertEqual(core.find_n(),(None,False))
   strict=help_text+b' --no-config --vod-select-parts -ds'
   with patch.object(core,'n_digest',return_value='0'*64),patch.object(core.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=strict)):
    self.assertEqual(core.find_n(),(str(binary.resolve()),False))
 def test_signed_macho_identity_excludes_only_signature_changes(self):
  import struct
  from types import SimpleNamespace
  path=Path(self.tmp.name)/'engine'
  header=struct.pack('<8I',0xfeedfacf,0x100000c,0,2,2,88,0,0)
  segment=struct.pack('<II16sQQQQIIII',0x19,72,b'__LINKEDIT',0,4096,120,32,0,0,0,0)
  signature=struct.pack('<IIII',0x1d,16,136,16)
  original=header+segment+signature+b'official-code-00'+b'signature-000000'
  path.write_bytes(original);expected=core.macho_content_digest(path)
  # Simulate a new signature that changes only the signature size and segment sizes.
  signed=bytearray(original[:136]);struct.pack_into('<Q',signed,32+32,4096);struct.pack_into('<Q',signed,32+48,40);struct.pack_into('<I',signed,104+12,24);signed+=b'signed-data-'+b'0'*12;path.write_bytes(signed)
  self.assertEqual(core.macho_content_digest(path),expected)
  with patch.object(core.sys,'platform','darwin'),patch.object(core,'KNOWN_N_MACHO_CONTENT',{expected}),patch.object(core.subprocess,'run',return_value=SimpleNamespace(returncode=0)):
   self.assertTrue(core.signed_known_n(path))
   signed[120]^=1;path.write_bytes(signed);self.assertFalse(core.signed_known_n(path))
   signed[120]^=1;path.write_bytes(signed)
   with patch.object(core.subprocess,'run',return_value=SimpleNamespace(returncode=1)):self.assertFalse(core.signed_known_n(path))
   struct.pack_into('<Q',signed,32+32,10**9);path.write_bytes(signed);self.assertFalse(core.signed_known_n(path))
  path.write_bytes(b'invalid')
  with self.assertRaises(ValueError):core.macho_content_digest(path)
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
