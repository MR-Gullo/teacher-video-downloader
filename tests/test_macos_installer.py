"""Native installer tests. All destinations and state are explicit disposable paths."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / '.scratch/mac-installer-20261103'
SOURCE = ROOT / 'scripts/macos/Installer.swift'
HOST = 'org.teacher.video_downloader.json'


@unittest.skipUnless(sys.platform == 'darwin', 'macOS native installer')
class InstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        cls.build_temp = tempfile.TemporaryDirectory(dir=SCRATCH)
        cls.executable = Path(cls.build_temp.name) / 'installer'
        subprocess.run(['xcrun', 'swiftc', '-module-cache-path', str(Path(cls.build_temp.name) / 'cache'),
                        str(SOURCE), '-o', str(cls.executable)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.payload = self.root / 'payload'
        self.account = self.root / "Test teacher's account"
        self.base = self.account / 'Library/Application Support/Teacher Video Downloader'
        self.app = self.base / 'app'
        self.manifest = self.account / 'Library/Application Support/Mozilla/NativeMessagingHosts' / HOST
        self.payload.mkdir()
        # Fixture delegates to this developer Python. Never a distributable runtime.
        interpreter = self.payload / 'runtime/bin/python3'
        interpreter.parent.mkdir(parents=True)
        import shlex
        interpreter.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
        interpreter.chmod(0o700)
        shutil.copytree(ROOT / 'companion', self.payload / 'companion', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for tool in ('yt-dlp', 'ffmpeg', 'ffprobe'):
            target = self.payload / 'tools' / tool
            target.parent.mkdir(exist_ok=True)
            target.write_text('#!/bin/sh\necho fixture-only\n')
            target.chmod(0o700)
        (self.payload / 'LICENSES.txt').write_text('Test fixture. Not a dependency distribution.\n')
        self.lock()

    def lock(self, **changes):
        spec = dict(schema=1, architecture=platform.machine(), prototype=True,
                    firefoxID='lessonshelf-preview@local.invalid', files={
                        p.relative_to(self.payload).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in self.payload.rglob('*') if p.is_file() and p.name != 'payload.json'})
        spec.update(changes)
        (self.payload / 'payload.json').write_text(json.dumps(spec))

    def run_install(self, dry=False):
        return subprocess.run([str(self.executable), '--payload', str(self.payload), '--stage-root', str(self.account)] +
                              (['--dry-run'] if dry else []), capture_output=True, text=True)

    def test_dry_run_makes_no_destination(self):
        result = self.run_install(dry=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.account.exists())

    def test_install_and_native_messaging_handshake(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.manifest.read_text())
        self.assertEqual(manifest['allowed_extensions'], ['lessonshelf-preview@local.invalid'])
        self.assertEqual(manifest['path'], str(self.app / 'launch-host'))
        env = dict(os.environ, TVD_STATE_DIR=str(self.root / 'state'), YTDL_OUTPUT_DIR=str(self.root / 'downloads'))
        request = json.dumps({'op': 'doctor'}).encode()
        process = subprocess.run([manifest['path']], input=struct.pack('=I', len(request)) + request,
                                 capture_output=True, env=env, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        size = struct.unpack('=I', process.stdout[:4])[0]
        response = json.loads(process.stdout[4:])
        self.assertEqual(size, len(process.stdout[4:]))
        self.assertTrue(response['ok'])
        self.assertIn(str(self.app / 'tools'), process.stdout.decode(errors='replace'))
        self.assertFalse((self.base / '.installer-lock').exists())
        self.assertEqual(self.manifest.stat().st_mode & 0o777, 0o600)

    def test_existing_app_and_queue_preserved(self):
        self.app.mkdir(parents=True)
        (self.app / 'sentinel').write_text('existing app')
        (self.base / 'queue.sqlite').write_bytes(b'queue evidence')
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.app / 'sentinel').read_text(), 'existing app')
        self.assertEqual((self.base / 'queue.sqlite').read_bytes(), b'queue evidence')
        self.assertFalse(self.manifest.exists())

    def test_existing_registration_preserved(self):
        self.manifest.parent.mkdir(parents=True)
        self.manifest.write_bytes(b'original registration')
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assertEqual(self.manifest.read_bytes(), b'original registration')
        self.assertFalse(self.app.exists())

    def test_incomplete_offline_payload(self):
        (self.payload / 'tools/ffmpeg').unlink()
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assertFalse(self.account.exists())

    def test_hash_failure_then_retry(self):
        target = self.payload / 'tools/ffmpeg'
        original = target.read_bytes()
        target.write_bytes(b'corrupted or truncated transfer')
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assertFalse(self.account.exists())
        target.write_bytes(original)
        self.assertEqual(self.run_install().returncode, 0)

    def test_wrong_architecture(self):
        self.lock(architecture='x86_64' if platform.machine() == 'arm64' else 'arm64')
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assertFalse(self.account.exists())

    def test_unlisted_file_and_symlink_rejected(self):
        extra = self.payload / 'unlisted'
        extra.write_text('extra')
        self.assertNotEqual(self.run_install().returncode, 0)
        extra.unlink()
        extra.symlink_to('/etc/hosts')
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assertFalse(self.account.exists())

    def test_destination_symlink_rejected(self):
        self.account.mkdir()
        (self.account / 'Library').symlink_to(self.root / 'elsewhere')
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assertFalse((self.root / 'elsewhere').exists())

    def test_interrupted_install_lock_preserved(self):
        lock = self.base / '.installer-lock'
        lock.mkdir(parents=True)
        (lock / 'evidence').write_text('interrupted preparation')
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assertEqual((lock / 'evidence').read_text(), 'interrupted preparation')

    def test_registration_failure_rolls_back_only_new_app(self):
        self.manifest.parent.mkdir(parents=True)
        self.base.mkdir(parents=True)
        (self.base / 'queue.sqlite').write_bytes(b'preserve queue')
        self.manifest.parent.chmod(0o500)
        try:
            result = self.run_install()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('rolled back', result.stderr)
            self.assertFalse(self.app.exists())
            self.assertFalse(self.manifest.exists())
            self.assertEqual((self.base / 'queue.sqlite').read_bytes(), b'preserve queue')
            self.assertFalse((self.base / '.installer-lock').exists())
        finally:
            self.manifest.parent.chmod(0o700)
        self.assertEqual(self.run_install().returncode, 0)

    def test_build_app_and_refuse_replacement(self):
        spec = importlib.util.spec_from_file_location('builder', ROOT / 'scripts/macos/build_installer.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = self.root / 'LessonShelf prototype.app'
        module.build(self.payload, output)
        self.assertTrue((output / 'Contents/MacOS/LessonShelfInstaller').is_file())
        with self.assertRaises(ValueError):
            module.build(self.payload, output)

    def test_builder_rejects_wrong_macho_architecture(self):
        spec = importlib.util.spec_from_file_location('builder', ROOT / 'scripts/macos/build_installer.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        binary = self.payload / 'tools/ffmpeg'
        binary.write_bytes(bytes.fromhex('cffaedfe') + b'fixture Mach-O header')
        wrong = 'x86_64' if platform.machine() == 'arm64' else 'arm64'
        with mock.patch.object(module.subprocess, 'check_output', return_value=wrong):
            with self.assertRaisesRegex(ValueError, 'Wrong architecture'):
                module.validate_architecture(self.payload, platform.machine())

    def test_real_account_root_rejected(self):
        result = subprocess.run([str(self.executable), '--payload', str(self.payload), '--stage-root', str(Path.home())],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('separate test directory', result.stderr)

    def test_builder_rejects_release_claim(self):
        self.lock(prototype=False)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/macos/build_installer.py'),
                                 '--payload', str(self.payload), '--output', str(self.root / 'release.app')],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'release.app').exists())


if __name__ == '__main__':
    unittest.main()
