#!/usr/bin/env python3
"""Real Windows EXE native-messaging transport check. Keeps stdin open between requests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import threading


def receive(stream):
    prefix = stream.read(4)
    if len(prefix) != 4: raise RuntimeError('Launcher closed before a native response header')
    size = struct.unpack('=I', prefix)[0]
    if not 0 < size <= 512 * 1024: raise RuntimeError('Invalid response frame length')
    payload = stream.read(size)
    if len(payload) != size: raise RuntimeError('Launcher returned a truncated native response')
    return json.loads(payload)


def check(app, report):
    if sys.platform != 'win32': raise RuntimeError('This acceptance check requires real Windows')
    launcher = app / 'launch-host.exe'
    process = subprocess.Popen([str(launcher)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    replies = queue.Queue()
    stderr = []
    def reader():
        try:
            for _ in range(2): replies.put(receive(process.stdout))
        except Exception as error: replies.put(error)
    def error_reader(): stderr.append(process.stderr.read().decode(errors='replace'))
    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=error_reader, daemon=True).start()
    evidence = {'realWindowsExecuted': True, 'ok': False, 'requests': [], 'launcher': str(launcher)}
    try:
        for op in ('doctor', 'status'):
            message = json.dumps({'op': op}).encode()
            process.stdin.write(struct.pack('=I', len(message)) + message); process.stdin.flush()
            try: response = replies.get(timeout=30)
            except queue.Empty: raise RuntimeError('No native reply while the browser input pipe remains open') from None
            if isinstance(response, Exception): raise response
            if not response.get('ok'): raise RuntimeError('Native operation failed: ' + op)
            evidence['requests'].append({'op': op, 'response': response})
        doctor = evidence['requests'][0]['response']['doctor']
        for name in ('yt-dlp', 'ffmpeg', 'ffprobe', 'N_m3u8DL-RE'):
            expected = str((app / 'tools' / (name + '.exe')).resolve())
            tool = doctor[name]
            if not tool.get('available') or os.path.normcase(str(Path(tool.get('path', '')).resolve())) != os.path.normcase(expected):
                raise RuntimeError('Native doctor did not select bundled ' + name)
        if not (app.parent / 'queue.sqlite').is_file(): raise RuntimeError('Native host did not create its isolated queue')
        process.stdin.close()
        process.wait(timeout=10)
        if process.returncode != 0: raise RuntimeError('Launcher exited with ' + str(process.returncode))
        with launcher.open('rb') as stream: evidence['launcherSHA256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        evidence['ok'] = True
    except Exception as error:
        evidence['error'] = str(error)
        raise
    finally:
        if process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            process.wait(timeout=10)
        evidence['stderr'] = ''.join(stderr)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(evidence, indent=2) + '\n')
    print(report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    check(args.app.resolve(), args.report.resolve())
