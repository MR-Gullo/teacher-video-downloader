#!/usr/bin/env python3
import argparse,json,subprocess
from pathlib import Path
from core import doctor
from media import copy_plan,validate_copy
p=argparse.ArgumentParser(description='Teacher Video Downloader: local diagnostics and non-destructive copy preview')
p.add_argument('--doctor',action='store_true');p.add_argument('--input',type=Path);p.add_argument('--mode',choices=['none','classroom','av1'],default='classroom');p.add_argument('--execute',action='store_true',help='Actually create copy; default prints argv only')
a=p.parse_args()
if a.doctor:print(json.dumps(doctor(),indent=2))
elif a.input:
    source=a.input.expanduser().resolve(strict=True);plan,note=copy_plan(source,a.mode);print(note)
    if plan:
        args,dest,info=plan;print(json.dumps(args,indent=2))
        if a.execute:
            subprocess.run(args,check=True)
            if not validate_copy(info,dest,source,a.mode):dest.unlink();print('Discarded: less than 15% saving')
else:p.print_help()
