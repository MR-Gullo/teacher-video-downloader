#!/usr/bin/env python3
"""Build an unsigned Firefox submission archive from the maintained sources."""
import argparse
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', type=Path, help='new ZIP file to create')
args = parser.parse_args()
output = args.output.resolve()
if output.exists():
    parser.error('output already exists; choose a new path')
subprocess.run([sys.executable, str(root / 'scripts/build.py')], check=True, cwd=root)
source = root / 'build/firefox'
with ZipFile(output, 'x', compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(p for p in source.rglob('*') if p.is_file()):
        info = ZipInfo(path.relative_to(source).as_posix(), (2020, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
print(output)
