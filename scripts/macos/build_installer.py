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
from install_payload import validate


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
    validate(payload, spec['target'])
    architecture = 'arm64' if spec['target'] == 'macos-arm64' else 'x86_64'
    if spec['target'] not in ('macos-arm64', 'macos-x64'):
        raise ValueError('Use the Windows builder for Windows payloads')
    if architecture not in ('arm64', 'x86_64'):
        raise ValueError('Unsupported architecture')
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
        if architecture == platform.machine():
            subprocess.run([str(executable), '--payload', str(resources / 'payload'),
                            '--stage-root', str(temporary / 'test-account'), '--dry-run'], check=True)
        with (contents / 'Info.plist').open('wb') as stream:
            plistlib.dump(dict(CFBundleIdentifier='org.lessonshelf.installer',
                              CFBundleName='LessonShelf installer',
                              CFBundleExecutable=executable.name, CFBundlePackageType='APPL',
                              CFBundleVersion='1', CFBundleShortVersionString=spec['version'].split('-')[0],
                              LSMinimumSystemVersion='12.0', NSHighResolutionCapable=True), stream)
        (resources / 'REVIEW-ONLY.txt').write_text('Local release candidate without distribution signing or notarization. Do not publish.\n')
        # Hashes are local review evidence, not a publisher signature.
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        (resources / 'BUILD.json').write_text(json.dumps(dict(architecture=architecture, executableSHA256=digest,
            signedForDistribution=False, notarized=False, macNativeDryRun=architecture == platform.machine(),
            generatedAt=datetime.now(timezone.utc).isoformat(), purpose='Local staging review only',
            sourceProject=str(Path(__file__).resolve().parents[2]),
            sourceCommit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).parent, text=True).strip(),
            sourceDirty=subprocess.check_output(['git', 'status', '--porcelain'], cwd=Path(__file__).parent, text=True).splitlines(),
            payloadManifestSHA256=hashlib.sha256((resources / 'payload/payload.json').read_bytes()).hexdigest()), indent=2) + '\n')
        os.rename(app, output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(build(args.payload, args.output))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Build stopped: {error}\n')
