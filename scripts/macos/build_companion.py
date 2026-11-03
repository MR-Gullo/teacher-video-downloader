#!/usr/bin/env python3
"""Build the sealed-layout Mac payload app. Sign/notarize it before release packaging."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
from build_installer import validate_architecture
from install_payload import digest, validate


def build(payload, output):
    payload, output = payload.resolve(), output.absolute()
    if output.exists() or output.is_symlink() or output.suffix != '.app' or output.resolve().is_relative_to(payload):
        raise ValueError('Use a new .app output outside the payload')
    spec = json.loads((payload / 'payload.json').read_text())
    validate(payload, spec['target'])
    if spec['target'] not in ('macos-arm64', 'macos-x64') or 'installer/run_host.py' not in spec['files']:
        raise ValueError('Reassemble a current Mac payload with its sealed bootstrap')
    architecture = 'arm64' if spec['target'] == 'macos-arm64' else 'x86_64'
    validate_architecture(payload, architecture)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='companion-build-', dir=output.parent) as temporary:
        temporary = Path(temporary)
        bundle = temporary / output.name
        contents = bundle / 'Contents'; resources = contents / 'Resources'
        resources.mkdir(parents=True)
        shutil.copytree(payload, resources / 'payload')
        executable = contents / 'MacOS/LessonShelfHost'; executable.parent.mkdir()
        subprocess.run(['xcrun', 'swiftc', '-target', architecture + '-apple-macosx12.0', '-module-cache-path', str(temporary / 'module-cache'),
                        str(Path(__file__).with_name('HostLauncher.swift')), '-o', str(executable)], check=True)
        with (contents / 'Info.plist').open('wb') as stream:
            plistlib.dump(dict(CFBundleIdentifier='org.lessonshelf.companion', CFBundleName='LessonShelf companion',
                              CFBundleExecutable='LessonShelfHost', CFBundlePackageType='APPL', CFBundleVersion='1',
                              CFBundleShortVersionString=spec['version'].split('-')[0], LSMinimumSystemVersion='12.0', LSBackgroundOnly=True), stream)
        provenance = json.loads((payload / 'PROVENANCE.json').read_text())
        (resources / 'BUILD.json').write_text(json.dumps({'component': 'companion', 'sourceCommit': provenance['sourceCommit'],
            'sourceDirty': provenance['sourceDirty'], 'architecture': architecture, 'executableSHA256': digest(executable),
            'payloadManifestSHA256': digest(payload / 'payload.json'), 'signedForDistribution': False, 'notarized': False}, indent=2) + '\n')
        (resources / 'REVIEW-ONLY.txt').write_text('Companion payload candidate. Sign and notarize before distribution.\n')
        os.rename(bundle, output)
    print(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.payload, args.output)
