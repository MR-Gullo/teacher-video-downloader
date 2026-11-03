#!/usr/bin/env python3
"""Fetch only exact, hash-pinned build inputs. Never run installers or change system tools."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def fetch(cache, keys=None):
    lock = json.loads(Path(__file__).with_name('dependencies.lock.json').read_text())['packages']
    cache.mkdir(parents=True, exist_ok=True)
    for name in keys or lock:
        spec = lock[name]
        destination = cache / spec['filename']
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != spec['sha256']:
                raise ValueError('Corrupt cached input. Preserve or remove this exact file before retry: ' + str(destination))
            continue
        with tempfile.TemporaryDirectory(prefix='fetch-', dir=cache) as temporary:
            candidate = Path(temporary) / 'download'
            subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location', '--proto', '=https', '--proto-redir', '=https',
                            '--retry', '2', '--connect-timeout', '20', '--max-time', '600', spec['url'], '-o', str(candidate)], check=True)
            if hashlib.sha256(candidate.read_bytes()).hexdigest() != spec['sha256']:
                raise ValueError('Upstream content failed its pinned hash: ' + name)
            candidate.replace(destination)
        print('Verified ' + name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--package', action='append')
    args = parser.parse_args()
    fetch(args.cache.resolve(), args.package)
