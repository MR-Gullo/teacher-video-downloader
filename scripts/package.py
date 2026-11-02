#!/usr/bin/env python3
"""Build browser folders and a reproducible preview ZIP."""
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

root = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, str(root / 'scripts/build.py')], check=True)
paths = ['README.md', 'companion', 'scripts', 'build', 'docs']
files = []
for path in paths:
    item = root / path
    files.extend([item] if item.is_file() else (p for p in item.rglob('*') if p.is_file()))
output = root / 'downloads/lessonshelf-preview.zip'
output.parent.mkdir(exist_ok=True)
with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
    for file in sorted(files):
        if '__pycache__' in file.parts or file.suffix == '.pyc':
            continue
        info = ZipInfo('LessonShelf/' + file.relative_to(root).as_posix(), (2020, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, file.read_bytes())
print(output)
