#!/usr/bin/env python3
"""Package reviewed cargo-about output and pinned upstream V8 notices for Deno."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(archive, name, content):
    if name.startswith('/') or '..' in Path(name).parts:
        raise ValueError('Invalid notice archive path')
    info = ZipInfo(name, (2020, 1, 1, 0, 0, 0))
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content, compress_type=ZIP_DEFLATED)


def generate(audit, output):
    data = json.loads((audit / 'deno-notices.json').read_text())
    inventory = json.loads((audit / 'cargo-notice-file-inventory.json').read_text())
    v8 = json.loads((audit / 'v8-notices-index.json').read_text())
    build_only = {'build', 'tools/clang', 'third_party/rust', 'tools/win'}
    if any(not item['files'] and item['component'] not in build_only for item in v8):
        raise ValueError('A V8 runtime component has no collected notice')
    source = audit / 'source/deno'
    lock = tomllib.loads((source / 'Cargo.lock').read_text())
    checksums = {(p['name'], p['version']): p.get('checksum') for p in lock['package']}
    output.mkdir(parents=True, exist_ok=False)
    packages = [{'name': item['package']['name'], 'version': item['package']['version'],
                 'license': item['license'], 'repository': item['package'].get('repository'),
                 'registryChecksum': checksums.get((item['package']['name'], item['package']['version']))}
                for item in data['crates']]
    (output / 'PACKAGE-LICENSES.json').write_text(json.dumps(packages, indent=2) + '\n')
    text = ['Deno 2.9.8 third-party notices',
            'Generated with cargo-about 0.9.3 from the hash-verified Deno release source.',
            'Targets: Windows x64, macOS Apple Silicon and Intel. Development dependencies are excluded.',
            'This is a conservative combined inventory; not every component is linked into every target.',
            'Original vendored license and notice files are in LICENSE-FILES.zip.',
            'Source for the five MPL dependencies is in MPL-SOURCES.zip.', '']
    for license in data['licenses']:
        used = sorted({item['crate']['name'] + ' ' + item['crate']['version'] for item in license['used_by']})
        text.extend(['=' * 72, license['name'] + ' [' + license['id'] + ']', 'Used by: ' + ', '.join(used), '', license['text'], ''])
    (output / 'THIRD-PARTY-NOTICES.txt').write_text('\n'.join(text))
    members = {}
    with ZipFile(output / 'LICENSE-FILES.zip', 'x', compression=ZIP_DEFLATED) as archive:
        for item in sorted(inventory, key=lambda x: (x['package'], x['version'], x['file'])):
            path = Path(item['path']).resolve()
            if not path.is_relative_to(audit / 'cargo-home/registry/src'):
                raise ValueError('Notice file is outside the verified registry source cache')
            name = 'crates/' + item['package'] + '-' + item['version'] + '/' + item['file']
            content = path.read_bytes()
            put(archive, name, content)
            members[name] = hashlib.sha256(content).hexdigest()
        for component in v8:
            for item in component['files']:
                path = audit / 'v8-notices' / item['filename']
                if sha(path) != item['sha256']:
                    raise ValueError('V8 notice hash mismatch')
                name = 'v8/' + item['filename']
                if name not in members:
                    content = path.read_bytes()
                    put(archive, name, content)
                    members[name] = item['sha256']
    registry = audit / 'cargo-home/registry/cache'
    mpl = []
    with ZipFile(output / 'MPL-SOURCES.zip', 'x', compression=ZIP_DEFLATED) as archive:
        for package in packages:
            if 'MPL-2.0' not in package['license']:
                continue
            filename = package['name'] + '-' + package['version'] + '.crate'
            matches = list(registry.glob('*/' + filename))
            if len(matches) != 1 or sha(matches[0]) != package['registryChecksum']:
                raise ValueError('MPL source archive does not match Deno Cargo.lock')
            put(archive, filename, matches[0].read_bytes())
            mpl.append({'filename': filename, 'sha256': package['registryChecksum'],
                        'url': 'https://static.crates.io/crates/' + package['name'] + '/' + filename})
        put(archive, 'README.txt', b'Unmodified crate source archives for Deno MPL dependencies. Extract with standard ZIP/tar tools. Each crate retains its license. See PROVENANCE.json for exact upstream hashes and URLs.\n')
    if len(mpl) != 5:
        raise ValueError('Unexpected MPL dependency set; review required')
    provenance = {'schema': 1, 'denoVersion': '2.9.8', 'cargoAboutVersion': '0.9.3',
                  'cargoAboutArchiveSHA256': '45520df8680978a6e7c4023ace0e3f311c73efc208cd68e5a7f4ed4822fa0349',
                  'cargoLockSHA256': sha(source / 'Cargo.lock'), 'cargoAboutOutputSHA256': sha(audit / 'deno-notices.json'),
                  'targets': ['aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-pc-windows-msvc'],
                  'developmentDependenciesIncluded': False, 'resolvedPackages': len(packages),
                  'licenseTextVariants': len(data['licenses']), 'licenseArchiveMembers': members,
                  'mplSources': mpl, 'v8Components': [{k: value for k, value in item.items() if k != 'errors'} for item in v8],
                  'excludedBuildInfrastructure': sorted(build_only), 'runtimeNoticeCoverageReviewed': True}
    provenance['files'] = {path.name: sha(path) for path in sorted(output.iterdir()) if path.is_file()}
    (output / 'PROVENANCE.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(json.dumps({'packages': len(packages), 'noticeFiles': len(members), 'mplSources': len(mpl), 'output': str(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    generate(args.audit.resolve(), args.output.resolve())
