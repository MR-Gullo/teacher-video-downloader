#!/usr/bin/env python3
"""Build a LOCAL ONLY app without distribution signing from a complete, hash-locked offline payload."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import platform
import shlex
import sys
import shutil
import subprocess
import tempfile


def validate_architecture(payload, architecture):
    # Inspect every Mach-O object, including Python extensions and libraries.
    for path in payload.rglob('*'):
        if path.is_symlink():
            raise ValueError('Payload symbolic links are not supported')
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            magic = stream.read(4)
        if magic in (bytes.fromhex(x) for x in ('cffaedfe', 'feedfacf', 'cefaedfe', 'feedface', 'cafebabe', 'bebafeca', 'cafebabf')):
            arches = subprocess.check_output(['/usr/bin/lipo', '-archs', str(path)], text=True).split()
            if architecture not in arches:
                raise ValueError(f'Wrong architecture: {path.relative_to(payload)}')


def build(payload, output):
    payload, output = payload.resolve(), output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Refusing to replace an existing output')
    if output.suffix != '.app':
        raise ValueError('Output must end in .app')
    if output.resolve().is_relative_to(payload):
        raise ValueError('Output must be outside the payload')
    spec = json.loads((payload / 'payload.json').read_text())
    if spec.get('prototype') is not True:
        raise ValueError('This builder creates test-only prototypes. Release signing is not implemented.')
    architecture = spec['architecture']
    if architecture not in ('arm64', 'x86_64'):
        raise ValueError('Unsupported architecture')
    if architecture != platform.machine():
        raise ValueError('Build and verify natively on the matching Mac architecture')
    validate_architecture(payload, architecture)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mac-installer-', dir=output.parent) as temporary:
        temporary = Path(temporary)
        app = temporary / output.name
        contents = app / 'Contents'
        executable = contents / 'MacOS' / 'LessonShelfInstaller'
        executable.parent.mkdir(parents=True)
        resources = contents / 'Resources'
        resources.mkdir()
        shutil.copytree(payload, resources / 'payload')
        subprocess.run(['xcrun', 'swiftc', '-target', architecture + '-apple-macosx12.0',
                        '-module-cache-path', str(temporary / 'module-cache'),
                        str(Path(__file__).with_name('Installer.swift')), '-o', str(executable)], check=True)
        # Use the same verifier as installation, against the copied payload.
        subprocess.run([str(executable), '--payload', str(resources / 'payload'),
                        '--stage-root', str(temporary / 'test-account'), '--dry-run'], check=True)
        with (contents / 'Info.plist').open('wb') as stream:
            plistlib.dump(dict(CFBundleIdentifier='org.lessonshelf.installer.prototype',
                              CFBundleName='LessonShelf installer prototype',
                              CFBundleExecutable=executable.name, CFBundlePackageType='APPL',
                              CFBundleVersion='1', CFBundleShortVersionString='0.1.0',
                              LSMinimumSystemVersion='12.0', NSHighResolutionCapable=True), stream)
        (resources / 'PROTOTYPE.txt').write_text('Test-only prototype without distribution signing. Staging installs only. Not for teachers.\n')
        # Hashes are local review evidence, not a publisher signature.
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        (resources / 'BUILD.json').write_text(json.dumps(dict(architecture=architecture, executableSHA256=digest,
            signedForDistribution=False, notarized=False,
            generatedAt=datetime.now(timezone.utc).isoformat(), purpose='Local staging review only',
            sourceProject=str(Path(__file__).resolve().parents[2]),
            sourceCommit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).parent, text=True).strip(),
            sourceDirty=subprocess.check_output(['git', 'status', '--porcelain'], cwd=Path(__file__).parent, text=True).splitlines(),
            payloadManifestSHA256=hashlib.sha256((resources / 'payload/payload.json').read_bytes()).hexdigest()), indent=2) + '\n')
        os.rename(app, output)
    return output


def demo_payload(directory):
    """Developer-only fixture. Uses this Mac's Python and fake media tools."""
    root = Path(__file__).resolve().parents[2]
    interpreter = directory / 'runtime/bin/python3'
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
    interpreter.chmod(0o700)
    shutil.copytree(root / 'companion', directory / 'companion', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for tool in ('yt-dlp', 'ffmpeg', 'ffprobe'):
        target = directory / 'tools' / tool
        target.parent.mkdir(exist_ok=True)
        target.write_text('#!/bin/sh\necho "Prototype fixture, no media tool installed" >&2\nexit 1\n')
        target.chmod(0o700)
    (directory / 'LICENSES.txt').write_text('Developer-only fixture. No third-party media binaries distributed.\n')
    spec = dict(schema=1, architecture=platform.machine(), prototype=True,
                firefoxID='lessonshelf-preview@local.invalid', files={
                    p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in directory.rglob('*') if p.is_file()})
    (directory / 'payload.json').write_text(json.dumps(spec, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--payload', type=Path)
    group.add_argument('--demo', action='store_true', help='Use test fixtures, not real dependencies')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.demo:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='demo-payload-', dir=args.output.parent) as temporary:
                demo_payload(Path(temporary))
                print(build(Path(temporary), args.output))
        else:
            print(build(args.payload, args.output))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Build stopped: {error}\n')
