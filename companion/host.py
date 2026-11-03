#!/usr/bin/env python3
"""Length-prefixed native messaging only. Browser allowlists live in host manifests."""
import json, os, struct, sys
from core import handle
os.umask(0o077)
if sys.platform=='win32':
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(),os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(),os.O_BINARY)
MAX=512*1024

def main():
    while True:
        raw=sys.stdin.buffer.read(4)
        if not raw:return
        if len(raw)!=4:return
        n=struct.unpack('=I',raw)[0]
        if not 0<n<=MAX:return
        data=sys.stdin.buffer.read(n)
        if len(data)!=n:return
        try:result=handle(json.loads(data))
        except Exception as e:result={'ok':False,'error':str(e) if isinstance(e,ValueError) else 'Companion error; check local setup and disk space'}
        output=json.dumps(result).encode()
        if len(output)>MAX:output=b'{"ok":false,"error":"Response too large; reduce queue history"}'
        sys.stdout.buffer.write(struct.pack('=I',len(output))+output);sys.stdout.buffer.flush()
if __name__=='__main__':main()
