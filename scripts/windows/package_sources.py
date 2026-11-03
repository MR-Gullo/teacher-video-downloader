#!/usr/bin/env python3
"""Prepare the exact supplier FFmpeg source inputs for separate parent-reviewed distribution."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import zipfile


def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_index(path):
    entries = []
    with zipfile.ZipFile(path) as archive:
        with archive.open('cache.tar.gz') as source, tarfile.open(fileobj=source, mode='r|gz') as tar:
            for item in tar:
                record = {'path': item.name, 'bytes': item.size, 'type': item.type.decode(errors='replace')}
                if item.issym(): record['linkTarget'] = item.linkname
                if item.isfile():
                    digest = hashlib.sha256()
                    with tar.extractfile(item) as content:
                        while block := content.read(1024 * 1024): digest.update(block)
                    record['sha256'] = digest.hexdigest()
                entries.append(record)
    return entries


def package(cache, output):
    if output.exists(): raise ValueError('Refusing to replace an existing source package')
    lock_path = Path(__file__).with_name('source-distribution.lock.json')
    lock = json.loads(lock_path.read_text())
    for key in ('sourceCache', 'recipe', 'ffmpeg'):
        item = lock[key]; source = cache / item['filename']
        if source.stat().st_size != item['bytes'] or sha(source) != item['sha256']:
            raise ValueError('Source input failed its pinned hash: ' + key)
    dependencies = json.loads((Path(__file__).parents[1] / 'macos/dependencies.lock.json').read_text())['packages']
    binary = dependencies[lock['binaryPackageKey']]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='source-package-', dir=output.parent) as temporary:
        folder = Path(temporary) / output.name; folder.mkdir()
        index = source_index(cache / lock['sourceCache']['filename'])
        (folder / 'source-cache-index.json').write_text(json.dumps(index, indent=2) + '\n')
        shutil.copyfile(lock_path, folder / 'source-distribution.lock.json')
        pieces = []
        # Bounded transport pieces preserve the supplier ZIP exactly, without unpacking source code.
        with (cache / lock['sourceCache']['filename']).open('rb') as source:
            counter = 0
            while True:
                first = source.read(1024 * 1024)
                if not first: break
                counter += 1; piece = folder / f'ffmpeg-source-cache.zip.part{counter:02d}'
                with piece.open('wb') as destination:
                    destination.write(first)
                    remaining = 1024 ** 3 - len(first)
                    while remaining and (block := source.read(min(1024 * 1024, remaining))):
                        destination.write(block); remaining -= len(block)
                pieces.append({'filename': piece.name, 'sha256': sha(piece), 'bytes': piece.stat().st_size})
        for key in ('recipe', 'ffmpeg'):
            shutil.copyfile(cache / lock[key]['filename'], folder / lock[key]['filename'])
        with zipfile.ZipFile(cache / binary['filename']) as archive:
            name = next(n for n in archive.namelist() if n.endswith('/LICENSE.txt'))
            (folder / 'FFmpeg-binary-LICENSE.txt').write_bytes(archive.read(name))
        executable_hashes = {}
        with zipfile.ZipFile(cache / binary['filename']) as archive:
            for tool in ('ffmpeg.exe', 'ffprobe.exe'):
                name = next(n for n in archive.namelist() if n.endswith('/bin/' + tool))
                with archive.open(name) as stream: executable_hashes[tool] = hashlib.file_digest(stream, 'sha256').hexdigest()
        manifest = {'binaryExecutablesSHA256': executable_hashes, 'schema': 1, 'purpose': 'Source-distribution preparation; parent release review required',
                    'binary': binary, 'supplierBuildRun': lock['supplierBuildRun'], 'sourceCache': lock['sourceCache'],
                    'parts': pieces, 'recipe': lock['recipe'], 'ffmpeg': lock['ffmpeg'],
                    'sourceArchiveCount': sum(e['type'] == '0' for e in index), 'allInputHashesVerified': True,
                    'published': False, 'legalReviewApproved': False}
        (folder / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (folder / 'restore-cache.py').write_text('''from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parent
m=json.loads((root/'MANIFEST.json').read_text())
target=root/'ffmpeg-source-cache.zip'
if target.exists(): raise SystemExit('Refusing to replace an existing restored cache')
for item in m['parts']:
    if Path(item['filename']).name!=item['filename'] or not item['filename'].startswith('ffmpeg-source-cache.zip.part'): raise ValueError('Invalid part path')
    with (root/item['filename']).open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=item['sha256']: raise ValueError('Part hash failed')
try:
    with target.open('xb') as out:
        for item in m['parts']:
            with (root/item['filename']).open('rb') as source:
                while block:=source.read(1024*1024): out.write(block)
    with target.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=m['sourceCache']['sha256']: raise ValueError('Restored cache hash failed')
except Exception:
    target.unlink(missing_ok=True)
    raise
print('Verified supplier source cache restored')
''')
        (folder / 'README.txt').write_text('''FFmpeg source-distribution preparation

This developer source bundle corresponds to the Windows FFmpeg/ffprobe binaries identified in MANIFEST.json.
It contains the exact upstream build-run download cache, the matching build recipes and the exact FFmpeg source commit.
The cache includes inputs for additional supplier build variants. License texts remain within the respective source archives.
No source scripts were executed to prepare this package.

Restore the exact supplier ZIP with Python 3.11+: python restore-cache.py
The restore helper verifies each part and the restored ZIP. Unpack cache.tar.gz from that ZIP, then unpack it at the
root of the supplied FFmpeg-Builds recipe checkout to restore .cache/downloads. Consult the upstream build.sh,
variants/win64-gpl.sh, variants/defaults-gpl.sh and Docker build files. The FFmpeg source archive pins the source
commit embedded in the binary filename. A bit-for-bit rebuild has not been claimed.

Publish all source parts, restore helper, manifest, index, source archives, recipes and licenses alongside the binary
release after parent review. Keeping only a temporary Actions artifact URL is not a durable source offer.
The teacher installer is a separate artifact and does not need this source bundle to run.
''')
        folder.rename(output)
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package(args.cache.resolve(), args.output.absolute())
