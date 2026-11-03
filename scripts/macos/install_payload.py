#!/usr/bin/env python3
"""Transactional per-user Firefox companion install. No downloads or privileged writes."""
import argparse
import ast
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid

HOST = 'org.teacher.video_downloader'
IDS = {'teacher-video-downloader@local.invalid', 'lessonshelf-preview@local.invalid'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def no_links(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise ValueError('Symbolic links are not allowed in installer paths')


def validate(payload, target=None):
    no_links(payload)
    spec = json.loads((payload / 'payload.json').read_text())
    target = target or ('windows-x64' if sys.platform == 'win32' else 'macos-' + ('arm64' if platform.machine() == 'arm64' else 'x64'))
    if spec.get('schema') != 2 or spec.get('target') != target:
        raise ValueError('Download the installer for this operating system and processor')
    if spec.get('firefoxID') not in IDS or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?', spec.get('version', '')):
        raise ValueError('Invalid release identity')
    windows = target == 'windows-x64'
    required = {'runtime/python.exe' if windows else 'runtime/bin/python3', 'companion/host.py', 'companion/worker.py',
                'installer/install_payload.py', 'LICENSES.txt', 'PROVENANCE.json'}
    if windows:
        required.add('installer/launch-host.exe')
    required.update('tools/' + name + ('.exe' if windows else '') for name in ('yt-dlp', 'ffmpeg', 'ffprobe', 'N_m3u8DL-RE'))
    files = spec.get('files', {})
    if not required <= files.keys():
        raise ValueError('Offline dependency bundle is incomplete')
    actual = set()
    for path in payload.rglob('*'):
        if path.is_symlink():
            raise ValueError('Payload contains a symbolic link')
        if path.is_file():
            actual.add(path.relative_to(payload).as_posix())
        elif not path.is_dir():
            raise ValueError('Payload contains an unsupported file type')
    if actual != set(files) | {'payload.json'}:
        raise ValueError('Payload contains missing or unlisted files')
    for name, expected in files.items():
        if not name or '\\' in name or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/')):
            raise ValueError('Invalid payload path')
        if not re.fullmatch('[a-f0-9]{64}', expected) or digest(payload / name) != expected:
            raise ValueError('Installer integrity check failed. Download it again')
    if not windows:
        for name in required:
            if name.startswith(('runtime/bin/', 'tools/')) and not os.access(payload / name, os.X_OK):
                raise ValueError('Bundled dependency is not executable')
    return spec


@contextlib.contextmanager
def worker_guard(base):
    path = base / 'worker.lock'
    with path.open('a+b') as lock:
        try:
            if sys.platform == 'win32':
                import msvcrt
                if path.stat().st_size == 0:
                    lock.write(b'\0'); lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('A download is active. Wait for it to finish, close Firefox, then try again') from None
        try:
            yield
        finally:
            if sys.platform == 'win32':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def write_atomic(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.lessonshelf-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def output_setting(app, default):
    record = app / '.installation.json'
    if record.exists():
        return json.loads(record.read_text())['outputDir']
    # Parse a legacy launcher as inert syntax. Never run it.
    legacy = app / 'launch-host'
    if legacy.is_file():
        try:
            tree = ast.parse(legacy.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    for target in node.targets:
                        if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant) and target.slice.value == 'YTDL_OUTPUT_DIR':
                            return node.value.value
        except (SyntaxError, UnicodeError):
            pass
    return str(default)


def registration_owned(data, app):
    try:
        old = json.loads(data)
        return old.get('name') == HOST and old.get('path') in (str(app / 'launch-host'), str(app / 'launch-host.exe'))
    except (ValueError, TypeError):
        return False


def registry_read():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Mozilla\NativeMessagingHosts' + chr(92) + HOST) as key:
            return winreg.QueryValueEx(key, '')
    except FileNotFoundError:
        return None


def registry_write(value):
    import winreg
    key_path = r'Software\Mozilla\NativeMessagingHosts' + chr(92) + HOST
    if value is None:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except FileNotFoundError:
            pass
    else:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, '', 0, value[1], value[0])


def install(payload, account, *, staging=False, dry_run=False, target=None):
    payload, account = Path(payload).absolute(), Path(account).absolute()
    spec = validate(payload, target)
    windows = spec['target'] == 'windows-x64'
    if spec.get('prototype') and not staging:
        raise ValueError('Test payloads can install only into a separate staging directory')
    if staging and account in (Path.home(), Path(account.anchor)):
        raise ValueError('Use a separate staging directory')
    no_links(account)
    base = (Path(os.environ['LOCALAPPDATA']) / 'LessonShelf') if windows and not staging else account / ('AppData/Local/LessonShelf' if windows else 'Library/Application Support/Teacher Video Downloader')
    app = base / 'app'
    manifest = (base / 'native-host.json') if windows else account / 'Library/Application Support/Mozilla/NativeMessagingHosts' / (HOST + '.json')
    for path in (base, app, manifest):
        no_links(path)
    old_manifest = manifest.read_bytes() if manifest.exists() else None
    if old_manifest is not None and not registration_owned(old_manifest, app):
        raise ValueError('An unrelated native-host registration exists. Nothing was replaced')
    if app.exists() and old_manifest is None:
        raise ValueError('An unregistered app folder exists. Nothing was replaced')
    old_registry = registry_read() if windows and not staging else None
    if old_registry is not None and old_registry[0] != str(manifest):
        raise ValueError('A different Windows native-host registration exists. Nothing was replaced')
    if dry_run:
        return {'ok': True, 'changed': False, 'destination': str(base), 'version': spec['version']}
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = base / '.installer-lock'
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        raise ValueError('Another or interrupted installation needs review. Nothing was replaced') from None
    keep_lock = False
    try:
        with worker_guard(base):
            # Snapshot ownership again while holding the installation lock.
            if (manifest.read_bytes() if manifest.exists() else None) != old_manifest:
                raise ValueError('Browser registration changed during installation. Try again')
            if windows and not staging and registry_read() != old_registry:
                raise ValueError('Windows registration changed during installation. Try again')
            staged = lock / 'app'
            shutil.copytree(payload, staged)
            validate(staged, spec['target'])
            installed_record = app / '.installation.json'
            if installed_record.exists() and json.loads(installed_record.read_text()).get('payloadSHA256') == digest(payload / 'payload.json'):
                if all((app / name).is_file() and digest(app / name) == expected for name, expected in spec['files'].items()):
                    if old_manifest is not None and json.loads(old_manifest).get('allowed_extensions') == [spec['firefoxID']] and (not windows or staging or old_registry is not None):
                        return {'ok': True, 'changed': False, 'version': spec['version'], 'destination': str(base)}
            output = output_setting(app, account / 'Downloads/youtube-downloads')
            record = {'schema': 1, 'version': spec['version'], 'outputDir': output, 'payloadSHA256': digest(payload / 'payload.json')}
            (staged / '.installation.json').write_text(json.dumps(record, indent=2) + '\n')
            python = app / ('runtime/python.exe' if windows else 'runtime/bin/python3')
            source = app / 'companion'
            bootstrap = 'import runpy,sys;sys.path.insert(0,' + repr(str(source)) + ');runpy.run_path(' + repr(str(source / 'host.py')) + ',run_name="__main__")'
            if windows:
                launcher = app / 'launch-host.exe'
                shutil.copyfile(staged / 'installer/launch-host.exe', staged / launcher.name)
                (staged / 'installer/run_host.py').write_text(bootstrap + '\n', encoding='utf-8')
                text = None
            else:
                launcher = app / 'launch-host'
                text = '#!/bin/sh\numask 077\nexport PATH=' + shlex.quote(str(app / 'tools') + ':/usr/bin:/bin') + '\nexport PYTHONNOUSERSITE=1\nexport PYTHONDONTWRITEBYTECODE=1\nunset PYTHONPATH PYTHONHOME\nexport TVD_STATE_DIR=' + shlex.quote(str(base)) + '\nexport YTDL_OUTPUT_DIR=' + shlex.quote(output) + '\nexec ' + shlex.quote(str(python)) + ' -B -I -c ' + shlex.quote(bootstrap) + ' "$@"\n'
            if text is not None:
                (staged / launcher.name).write_text(text)
            (staged / launcher.name).chmod(0o700)
            registration = json.dumps({'name': HOST, 'description': 'LessonShelf local companion', 'type': 'stdio', 'path': str(launcher), 'allowed_extensions': [spec['firefoxID']]}, indent=2).encode()
            rollback = None
            moved_old = False
            installed = False
            published = False
            registry_changed = False
            try:
                if app.exists():
                    # Keep all old program files as explicit recovery evidence. Never touch queue or media.
                    recovery = base / 'rollback'
                    recovery.mkdir(exist_ok=True)
                    rollback = recovery / ('app-' + uuid.uuid4().hex)
                    write_atomic(recovery / (rollback.name + '-manifest.json'), old_manifest)
                    if old_registry is not None:
                        write_atomic(recovery / (rollback.name + '-registry.json'), json.dumps(old_registry).encode())
                    write_atomic(lock / 'recovery.json', json.dumps({'app': str(app), 'rollbackApp': str(rollback), 'manifest': str(manifest)}).encode())
                    os.rename(app, rollback); moved_old = True
                if (manifest.read_bytes() if manifest.exists() else None) != old_manifest:
                    raise ValueError('Browser registration changed while preparing. Nothing was replaced')
                no_links(manifest)
                os.rename(staged, app); installed = True
                write_atomic(manifest, registration); published = True
                if windows and not staging:
                    import winreg
                    registry_changed = True
                    registry_write((str(manifest), winreg.REG_SZ))
                if windows and staging:
                    write_atomic(base / 'registry-projection.json', json.dumps({'key': r'HKCU\Software\Mozilla\NativeMessagingHosts' + chr(92) + HOST, 'value': str(manifest)}).encode())
                return {'ok': True, 'changed': True, 'version': spec['version'], 'destination': str(base), 'rollbackApp': str(rollback) if rollback else None}
            except Exception as error:
                try:
                    if registry_changed:
                        registry_write(old_registry)
                    if published:
                        if old_manifest is None:
                            manifest.unlink()
                        else:
                            write_atomic(manifest, old_manifest)
                    if installed:
                        shutil.rmtree(app)
                    if moved_old:
                        os.rename(rollback, app)
                except Exception as rollback_error:
                    keep_lock = True
                    raise RuntimeError('Rollback needs manual review. Recovery evidence remains at ' + str(lock)) from rollback_error
                raise error
    finally:
        if not keep_lock:
            shutil.rmtree(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', required=True, type=Path)
    parser.add_argument('--stage-root', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--install', action='store_true', help='Explicit GUI-approved install for this account')
    args = parser.parse_args()
    if not args.stage_root and not args.install:
        parser.error('Select an explicit staging root or --install')
    if sys.platform == 'win32':
        architecture = os.environ.get('PROCESSOR_ARCHITEW6432', os.environ.get('PROCESSOR_ARCHITECTURE', '')).upper()
        if architecture != 'AMD64':
            parser.error('This installer supports Windows x64. ARM64 and 32-bit Windows are not supported')
    try:
        result = install(args.payload, args.stage_root or Path.home(), staging=bool(args.stage_root), dry_run=args.dry_run)
        print(json.dumps(result))
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
