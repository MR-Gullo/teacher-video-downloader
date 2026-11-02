#!/usr/bin/env python3
import json,shutil
from pathlib import Path
root=Path(__file__).resolve().parents[1]
for browser in ('chrome','firefox'):
 target=root/'build'/browser;target.mkdir(parents=True,exist_ok=True)
 for name in ('background.js','popup.html','popup.js','style.css'):
  shutil.copy2(root/'extension'/name,target/name)
 shutil.copytree(root/'extension'/'icons',target/'icons',dirs_exist_ok=True)
 manifest=json.loads((root/'extension'/f'manifest.{browser}.json').read_text())
 (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print(target)
