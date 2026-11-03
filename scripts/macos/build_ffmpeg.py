#!/usr/bin/env python3
"""Build relocatable Mac FFmpeg/ffprobe from locked upstream FFmpeg, x264 and AOM sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def extract(archive, destination):
    destination.mkdir(parents=True)
    with tarfile.open(archive) as stream:
        stream.extractall(destination, filter='data')
    children = list(destination.iterdir())
    return children[0] if len(children) == 1 and children[0].is_dir() else destination


def build(architecture, work, cache):
    work, cache = work.resolve(), cache.resolve()
    if work.exists():
        raise ValueError('Refusing to replace an existing build directory')
    lock = json.loads(Path(__file__).with_name('dependencies.lock.json').read_text())['packages']
    for name in ('ffmpeg-source', 'x264-source', 'aom-source'):
        spec = lock[name]
        path = cache / spec['filename']
        if hashlib.sha256(path.read_bytes()).hexdigest() != spec['sha256']:
            raise ValueError('Source hash mismatch: ' + name)
    work.mkdir(parents=True)
    prefix = work / 'prefix'
    prefix.mkdir()
    commands = []
    env = dict(os.environ, MACOSX_DEPLOYMENT_TARGET='12.0', PKG_CONFIG_PATH=str(prefix / 'lib/pkgconfig'),
               PKG_CONFIG_LIBDIR=str(prefix / 'lib/pkgconfig'))
    log = work / 'build.log'

    def run(argv, cwd):
        commands.append({'argv': argv, 'cwd': str(cwd)})
        (work / 'build-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        with log.open('ab') as output:
            subprocess.run(argv, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT, check=True)

    x264 = extract(cache / lock['x264-source']['filename'], work / 'x264')
    flags = '-arch ' + architecture + ' -mmacosx-version-min=12.0'
    run(['./configure', '--prefix=' + str(prefix), '--enable-static', '--disable-cli', '--disable-opencl', '--disable-asm',
         '--host=' + ('aarch64-apple-darwin' if architecture == 'arm64' else 'x86_64-apple-darwin'),
         '--extra-cflags=' + flags, '--extra-ldflags=' + flags], x264)
    run(['make', '-j4'], x264); run(['make', 'install'], x264)
    aom = extract(cache / lock['aom-source']['filename'], work / 'aom')
    aom_build = work / 'aom-build'
    run(['cmake', '-S', str(aom), '-B', str(aom_build), '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
         '-DCMAKE_INSTALL_PREFIX=' + str(prefix), '-DCMAKE_OSX_ARCHITECTURES=' + architecture,
         '-DCMAKE_OSX_DEPLOYMENT_TARGET=12.0', '-DBUILD_SHARED_LIBS=OFF', '-DENABLE_TESTS=OFF',
         '-DENABLE_EXAMPLES=OFF', '-DENABLE_TOOLS=OFF', '-DENABLE_DOCS=OFF', '-DENABLE_NASM=OFF',
         '-DAOM_TARGET_CPU=' + ('arm64' if architecture == 'arm64' else 'generic'), '-DENABLE_ASM=OFF'], work)
    run(['cmake', '--build', str(aom_build), '--parallel', '4'], work)
    run(['cmake', '--install', str(aom_build)], work)
    ffmpeg = extract(cache / lock['ffmpeg-source']['filename'], work / 'ffmpeg')
    run(['./configure', '--prefix=' + str(prefix), '--arch=' + architecture, '--target-os=darwin',
         '--cc=clang', '--cxx=clang++', '--enable-cross-compile', '--disable-shared', '--enable-static',
         '--disable-autodetect', '--enable-gpl', '--enable-libx264', '--enable-libaom', '--enable-securetransport',
         '--enable-zlib', '--disable-x86asm', '--disable-doc', '--disable-ffplay', '--pkg-config-flags=--static',
         '--extra-cflags=' + flags + ' -I' + str(prefix / 'include'),
         '--extra-ldflags=' + flags + ' -L' + str(prefix / 'lib'), '--extra-libs=-lc++'], ffmpeg)
    run(['make', '-j4', 'ffmpeg', 'ffprobe'], ffmpeg)
    run(['make', 'install-progs'], ffmpeg)
    (work / 'SOURCE-LOCK.json').write_text(json.dumps({k: lock[k] for k in ('ffmpeg-source', 'x264-source', 'aom-source')}, indent=2) + '\n')
    print(prefix / 'bin')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--architecture', choices=('arm64', 'x86_64'), required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    args = parser.parse_args()
    build(args.architecture, args.work, args.cache)
