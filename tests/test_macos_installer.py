"""Installer transaction and packaging tests. Destinations are disposable staging accounts."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / '.scratch/mac-installer-20261103'
SCRIPTS = ROOT / 'scripts/macos'
sys.path.insert(0, str(SCRIPTS))
import install_payload as backend
import build_installer as builder


def fixture(payload, target=None, version='0.3.0'):
    target = target or ('windows-x64' if sys.platform == 'win32' else 'macos-' + ('arm64' if platform.machine() == 'arm64' else 'x64'))
    windows = target == 'windows-x64'
    payload.mkdir()
    interpreter = payload / ('runtime/python.exe' if windows else 'runtime/bin/python3')
    interpreter.parent.mkdir(parents=True)
    if windows:
        shutil.copyfile(sys.executable, interpreter)
    else:
        interpreter.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
    interpreter.chmod(0o700)
    shutil.copytree(ROOT / 'companion', payload / 'companion', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for tool in ('yt-dlp', 'ffmpeg', 'ffprobe', 'N_m3u8DL-RE'):
        path = payload / 'tools' / (tool + ('.exe' if windows else ''))
        path.parent.mkdir(exist_ok=True)
        path.write_text('#!/bin/sh\necho "fixture-only --no-config --disable-update-check --write-meta-json --vod-select-parts -sv -sa -ds"\n')
        path.chmod(0o700)
    (payload / 'installer').mkdir()
    shutil.copyfile(SCRIPTS / 'install_payload.py', payload / 'installer/install_payload.py')
    if windows:
        (payload / 'installer/launch-host.exe').write_bytes(b'test fixture, not executable')
    (payload / 'LICENSES.txt').write_text('Test fixtures. Not a distribution.\n')
    (payload / 'PROVENANCE.json').write_text('{"prototype":true}\n')
    spec = dict(schema=2, target=target, version=version, prototype=True, firefoxID='lessonshelf-preview@local.invalid', files={
        p.relative_to(payload).as_posix(): backend.digest(p) for p in payload.rglob('*') if p.is_file()})
    (payload / 'payload.json').write_text(json.dumps(spec))
    return spec


class TransactionTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.payload = self.root / 'payload'
        self.spec = fixture(self.payload)
        self.account = self.root / "Test teacher's account"
        self.base = self.account / ('AppData/Local/LessonShelf' if sys.platform == 'win32' else 'Library/Application Support/Teacher Video Downloader')
        self.app = self.base / 'app'
        self.manifest = self.base / 'native-host.json' if sys.platform == 'win32' else self.account / 'Library/Application Support/Mozilla/NativeMessagingHosts/org.teacher.video_downloader.json'

    def install(self, **kwargs):
        return backend.install(self.payload, self.account, staging=True, **kwargs)

    def test_dry_run_no_writes(self):
        self.assertFalse(self.install(dry_run=True)['changed'])
        self.assertFalse(self.account.exists())

    def test_fresh_registration_and_idempotent_reinstall(self):
        self.assertTrue(self.install()['changed'])
        manifest = json.loads(self.manifest.read_text())
        self.assertEqual(manifest['allowed_extensions'], ['lessonshelf-preview@local.invalid'])
        self.assertEqual(manifest['name'], backend.HOST)
        self.assertFalse(self.install()['changed'])
        self.assertFalse((self.base / 'rollback').exists())
        self.assertFalse((self.base / '.installer-lock').exists())

    def test_corrupt_hash_and_retry(self):
        path = self.payload / 'LICENSES.txt'; old = path.read_bytes()
        path.write_bytes(b'corrupt transfer')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.install()
        self.assertFalse(self.account.exists())
        path.write_bytes(old)
        self.assertTrue(self.install()['ok'])

    def test_wrong_architecture_or_platform(self):
        self.spec['target'] = 'unsupported'
        (self.payload / 'payload.json').write_text(json.dumps(self.spec))
        with self.assertRaisesRegex(ValueError, 'processor'):
            self.install()
        self.assertFalse(self.account.exists())

    def test_required_dependency_missing(self):
        ext = '.exe' if sys.platform == 'win32' else ''
        (self.payload / ('tools/N_m3u8DL-RE' + ext)).unlink()
        with self.assertRaises(ValueError): self.install()
        self.assertFalse(self.account.exists())

    def test_unlisted_file(self):
        (self.payload / 'unlisted').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'unlisted'): self.install()

    @unittest.skipIf(sys.platform == 'win32', 'Creating links may need Windows developer mode')
    def test_payload_and_destination_symlink_refused(self):
        (self.payload / 'link').symlink_to('/etc/hosts')
        with self.assertRaises(ValueError): self.install()
        (self.payload / 'link').unlink()
        self.account.mkdir()
        (self.account / 'Library').symlink_to(self.root / 'unrelated')
        with self.assertRaises(ValueError): self.install()
        self.assertFalse((self.root / 'unrelated').exists())

    def test_unrelated_registration_preserved(self):
        self.manifest.parent.mkdir(parents=True)
        self.manifest.write_bytes(b'original registration')
        with self.assertRaisesRegex(ValueError, 'unrelated'): self.install()
        self.assertEqual(self.manifest.read_bytes(), b'original registration')
        self.assertFalse(self.app.exists())

    def test_unregistered_app_preserved(self):
        self.app.mkdir(parents=True)
        (self.app / 'sentinel').write_text('teacher work')
        with self.assertRaisesRegex(ValueError, 'unregistered'): self.install()
        self.assertEqual((self.app / 'sentinel').read_text(), 'teacher work')

    def test_interrupted_lock_preserved(self):
        lock = self.base / '.installer-lock'; lock.mkdir(parents=True)
        (lock / 'evidence').write_text('interrupted state')
        with self.assertRaisesRegex(ValueError, 'interrupted'): self.install()
        self.assertEqual((lock / 'evidence').read_text(), 'interrupted state')

    def test_active_worker_refuses_install(self):
        self.base.mkdir(parents=True)
        with backend.worker_guard(self.base):
            with self.assertRaisesRegex(ValueError, 'active'): self.install()
        self.assertFalse(self.app.exists())
        self.assertTrue(self.install()['ok'])

    def legacy(self):
        self.app.mkdir(parents=True)
        (self.app / 'sentinel').write_text('old app evidence')
        (self.app / 'launch-host').write_text('import os\nos.environ["YTDL_OUTPUT_DIR"]=' + repr(str(self.root / 'Saved media')) + '\n')
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.write_text(json.dumps({'name': backend.HOST, 'path': str(self.app / 'launch-host'), 'allowed_extensions': ['teacher-video-downloader@local.invalid']}))
        (self.base / 'queue.sqlite').write_bytes(b'queue evidence')
        (self.base / 'jobs').mkdir()
        (self.base / 'jobs/partial').write_bytes(b'partial evidence')

    def test_legacy_upgrade_preserves_state_and_output_and_backup(self):
        self.legacy(); result = self.install()
        self.assertEqual((self.base / 'queue.sqlite').read_bytes(), b'queue evidence')
        self.assertEqual((self.base / 'jobs/partial').read_bytes(), b'partial evidence')
        self.assertEqual((Path(result['rollbackApp']) / 'sentinel').read_text(), 'old app evidence')
        self.assertEqual(json.loads((self.app / '.installation.json').read_text())['outputDir'], str(self.root / 'Saved media'))

    def test_failed_registration_restores_legacy_app_and_manifest(self):
        self.legacy(); old = self.manifest.read_bytes()
        original = backend.write_atomic
        def fail_registration(path, data, *args, **kwargs):
            if path == self.manifest: raise OSError('simulated disk failure')
            return original(path, data, *args, **kwargs)
        with mock.patch.object(backend, 'write_atomic', side_effect=fail_registration):
            with self.assertRaises(OSError): self.install()
        self.assertEqual((self.app / 'sentinel').read_text(), 'old app evidence')
        self.assertEqual(self.manifest.read_bytes(), old)
        self.assertEqual((self.base / 'queue.sqlite').read_bytes(), b'queue evidence')
        self.assertFalse((self.base / '.installer-lock').exists())

    def test_real_account_and_test_payload_refused(self):
        with self.assertRaisesRegex(ValueError, 'separate staging'): backend.install(self.payload, self.account, staging=False)
        with self.assertRaisesRegex(ValueError, 'separate staging'):
            backend.install(self.payload, Path.home(), staging=True)

    @unittest.skipUnless(sys.platform == 'darwin', 'Mac host handshake')
    def test_native_protocol_with_spaces_and_apostrophe(self):
        self.install()
        data = json.dumps({'op': 'doctor'}).encode()
        child = subprocess.run([str(self.app / 'launch-host')], input=struct.pack('=I', len(data)) + data, capture_output=True, timeout=30)
        self.assertEqual(child.returncode, 0, child.stderr)
        size = struct.unpack('=I', child.stdout[:4])[0]
        self.assertEqual(size, len(child.stdout[4:]))
        response = json.loads(child.stdout[4:])
        self.assertTrue(response['ok'])
        self.assertIn(str(self.app / 'tools'), child.stdout.decode(errors='replace'))

    @unittest.skipUnless(sys.platform == 'darwin', 'Mac packaging')
    def test_build_mac_app(self):
        output = self.root / 'LessonShelf.app'
        builder.build(self.payload, output)
        self.assertTrue((output / 'Contents/MacOS/LessonShelfInstaller').is_file())
        with self.assertRaisesRegex(ValueError, 'existing'): builder.build(self.payload, output)

    def test_macho_wrong_architecture(self):
        path = self.payload / 'tools/binary'
        path.write_bytes(bytes.fromhex('cffaedfe'))
        with mock.patch.object(builder.subprocess, 'check_output', return_value='wrong'):
            with self.assertRaisesRegex(ValueError, 'Wrong architecture'):
                builder.validate_architecture(self.payload, platform.machine())

    def test_windows_registration_projection_only(self):
        payload = self.root / 'windows-payload'; fixture(payload, 'windows-x64')
        result = backend.install(payload, self.account, staging=True, target='windows-x64')
        self.assertTrue(result['ok'])
        projection = self.account / 'AppData/Local/LessonShelf/registry-projection.json'
        self.assertIn('HKCU', json.loads(projection.read_text())['key'])
        # This tests portable transaction logic. It does not claim Windows execution.


class WindowsPackagingTests(unittest.TestCase):
    def test_pe_architecture_is_checked(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as temporary:
            payload = Path(temporary) / 'payload'; spec = fixture(payload, 'windows-x64')
            pe = bytearray(80); pe[:2] = b'MZ'; struct.pack_into('<I', pe, 60, 64); pe[64:68] = b'PE\0\0'; struct.pack_into('<H', pe, 68, 0x8664)
            for path in payload.rglob('*.exe'): path.write_bytes(pe)
            spec['files'] = {p.relative_to(payload).as_posix(): backend.digest(p) for p in payload.rglob('*') if p.is_file() and p.name != 'payload.json'}
            (payload / 'payload.json').write_text(json.dumps(spec))
            module_spec = importlib.util.spec_from_file_location('windows_builder', ROOT / 'scripts/windows/build_installer.py')
            module = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(module)
            module.validate_windows_payload(payload)
            struct.pack_into('<H', pe, 68, 0xAA64)
            (payload / 'tools/ffmpeg.exe').write_bytes(pe)
            spec['files']['tools/ffmpeg.exe'] = backend.digest(payload / 'tools/ffmpeg.exe')
            (payload / 'payload.json').write_text(json.dumps(spec))
            with self.assertRaisesRegex(ValueError, 'architecture'):
                module.validate_windows_payload(payload)


if __name__ == '__main__': unittest.main()
