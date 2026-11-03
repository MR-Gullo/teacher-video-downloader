#!/usr/bin/env python3
"""Assemble real offline payloads from an explicit hash-locked cache. Never install."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def extract(path, destination):
    destination.mkdir(parents=True)
    if path.suffix == '.zip':
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.startswith(('/', '\\')) or '..' in Path(name).parts:
                    raise ValueError('Unsafe archive path')
            archive.extractall(destination)
    else:
        with tarfile.open(path) as archive:
            archive.extractall(destination, filter='data')


def assemble(target, version, firefox_id, cache, output, ffmpeg_build=None, windows_launcher=None):
    if output.exists():
        raise ValueError('Refusing to replace an existing payload')
    lock = json.loads(Path(__file__).with_name('dependencies.lock.json').read_text())['packages']
    windows = target == 'windows-x64'
    keys = ['python-' + target, 'n-' + target, 'ytdlp-windows-x64' if windows else 'ytdlp-python', 'n-license', 'ytdlp-license', 'ytdlp-third-party']
    keys += ['python-licenses-' + target]
    keys += ['ffmpeg-windows-x64'] if windows else ['ffmpeg-source', 'x264-source', 'aom-source']
    for key in keys:
        path = cache / lock[key]['filename']
        if not path.is_file() or sha(path) != lock[key]['sha256']:
            raise ValueError('Missing or corrupt dependency: ' + key)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='payload-build-', dir=output.parent) as temporary:
        work = Path(temporary)
        payload = work / 'payload'
        payload.mkdir()
        py = work / 'python'
        extract(cache / lock['python-' + target]['filename'], py)
        shutil.copytree(py / 'python', payload / 'runtime', symlinks=False)
        # Omit build-time pip, which teachers do not need. Preserve stdlib licenses.
        for site in (payload / 'runtime').rglob('site-packages'):
            if site.is_dir():
                shutil.rmtree(site); site.mkdir()
        shutil.copytree(ROOT / 'companion', payload / 'companion', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        tools = payload / 'tools'; tools.mkdir()
        ext = '.exe' if windows else ''
        if windows:
            shutil.copyfile(cache / lock[keys[2]]['filename'], tools / 'yt-dlp.exe')
        else:
            shutil.copyfile(cache / lock[keys[2]]['filename'], tools / 'yt-dlp.pyz')
            (tools / 'yt-dlp').write_text('#!/bin/sh\nHERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || exit 1\nexec "$HERE/../runtime/bin/python3" -B -I "$HERE/yt-dlp.pyz" "$@"\n')
        n = work / 'n'
        extract(cache / lock['n-' + target]['filename'], n)
        shutil.copyfile(next(n.rglob('N_m3u8DL-RE' + ext)), tools / ('N_m3u8DL-RE' + ext))
        notices = payload / 'licenses'; notices.mkdir()
        licensing = work / 'python-notices'; licensing.mkdir()
        licensing_archive = cache / lock['python-licenses-' + target]['filename']
        # Current macOS and Windows runner bsdtar can read zstd without a Python add-on.
        entries = subprocess.check_output(['tar', '-tf', str(licensing_archive)], text=True).splitlines()
        selected = [name for name in entries if name.startswith('python/licenses/') or name == 'python/PYTHON.json']
        if not selected or any('..' in Path(name).parts or name.startswith('/') for name in selected):
            raise ValueError('Invalid Python licensing archive')
        subprocess.run(['tar', '-xf', str(licensing_archive), '-C', str(licensing), *selected], check=True)
        shutil.copytree(licensing / 'python/licenses', notices / 'python')
        shutil.copyfile(licensing / 'python/PYTHON.json', notices / 'PYTHON-DISTRIBUTION.json')
        for key in ('n-license', 'ytdlp-license', 'ytdlp-third-party'):
            shutil.copyfile(cache / lock[key]['filename'], notices / lock[key]['filename'])
        if windows:
            if windows_launcher is None:
                raise ValueError('Windows requires the compiled Launcher.cs executable')
            ff = work / 'ffmpeg'; extract(cache / lock['ffmpeg-windows-x64']['filename'], ff)
            for name in ('ffmpeg.exe', 'ffprobe.exe'):
                shutil.copyfile(next(ff.rglob(name)), tools / name)
            shutil.copyfile(next(ff.rglob('LICENSE.txt')), notices / 'FFmpeg-GPL.txt')
        else:
            if ffmpeg_build is None:
                raise ValueError('Mac requires an explicit architecture-matched source build')
            for name in ('ffmpeg', 'ffprobe'):
                shutil.copyfile(ffmpeg_build / 'prefix/bin' / name, tools / name)
            sources = payload / 'sources'; sources.mkdir()
            for key in ('ffmpeg-source', 'x264-source', 'aom-source'):
                shutil.copyfile(cache / lock[key]['filename'], sources / lock[key]['filename'])
            shutil.copyfile(Path(__file__).with_name('build_ffmpeg.py'), sources / 'build_ffmpeg.py')
            shutil.copyfile(ffmpeg_build / 'build-commands.json', sources / 'build-commands.json')
            shutil.copyfile(ffmpeg_build / 'SOURCE-LOCK.json', sources / 'SOURCE-LOCK.json')
            shutil.copyfile(next((ffmpeg_build / 'ffmpeg').rglob('COPYING.GPLv2')), notices / 'FFmpeg-GPLv2.txt')
            shutil.copyfile(next((ffmpeg_build / 'x264').rglob('COPYING')), notices / 'x264-GPLv2.txt')
            shutil.copyfile(ffmpeg_build / 'aom/LICENSE', notices / 'AOM-LICENSE.txt')
            shutil.copyfile(ffmpeg_build / 'aom/PATENTS', notices / 'AOM-PATENTS.txt')
        installer = payload / 'installer'; installer.mkdir()
        shutil.copyfile(Path(__file__).with_name('install_payload.py'), installer / 'install_payload.py')
        if windows:
            shutil.copyfile(windows_launcher, installer / 'launch-host.exe')
        else:
            for path in tools.iterdir(): path.chmod(0o755)
        (payload / 'LICENSES.txt').write_text('LessonShelf bundles CPython from Astral Python Build Standalone, yt-dlp, FFmpeg/ffprobe and N_m3u8DL-RE.\nSee licenses/, the Python runtime LICENSE.txt, PROVENANCE.json and sources/ where present.\nWindows FFmpeg uses upstream yt-dlp FFmpeg-Builds. Its complete corresponding-source distribution must be reviewed before public release.\n')
        provenance = {'toolSourceSHA256': {path.name: sha(path) for path in tools.iterdir() if path.is_file()}, 'generatedAt': datetime.now(timezone.utc).isoformat(), 'target': target, 'dependencies': {key: lock[key] for key in keys},
                      'sourceProject': ROOT.name, 'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                      'sourceDirty': subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).splitlines(),
                      'productionReleaseApproved': False, 'windowsCorrespondingSourceReviewed': False if windows else None}
        (payload / 'PROVENANCE.json').write_text(json.dumps(provenance, indent=2) + '\n')
        manifest = {'schema': 2, 'target': target, 'version': version, 'prototype': False, 'firefoxID': firefox_id,
                    'files': {path.relative_to(payload).as_posix(): sha(path) for path in sorted(payload.rglob('*')) if path.is_file()}}
        (payload / 'payload.json').write_text(json.dumps(manifest, indent=2) + '\n')
        os.rename(payload, output)
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=('macos-arm64', 'macos-x64', 'windows-x64'), required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--firefox-id', choices=('teacher-video-downloader@local.invalid', 'lessonshelf-preview@local.invalid'), required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ffmpeg-build', type=Path)
    parser.add_argument('--windows-launcher', type=Path)
    args = parser.parse_args()
    assemble(args.target, args.version, args.firefox_id, args.cache.resolve(), args.output.absolute(), args.ffmpeg_build.resolve() if args.ffmpeg_build else None, args.windows_launcher.resolve() if args.windows_launcher else None)
