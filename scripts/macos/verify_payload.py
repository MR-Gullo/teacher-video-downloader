#!/usr/bin/env python3
"""Run real bundled tools and a staged native-messaging/MP4 check on the matching host."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile
from install_payload import digest, install, validate


def verify(payload, work, report):
    spec = validate(payload)
    windows = os.name == 'nt'
    work.mkdir(parents=True, exist_ok=True)
    account = work / 'Test teacher account'
    result = install(payload, account, staging=True)
    base = Path(result['destination']); app = base / 'app'; tools = app / 'tools'
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ.get('PATH', ''), PYTHONDONTWRITEBYTECODE='1')
    ext = '.exe' if windows else ''
    commands = [('python', [str(app / ('runtime/python.exe' if windows else 'runtime/bin/python3')), '-B', '-I', '-c', 'import sqlite3,ssl,sys;print(sys.version);print(sqlite3.sqlite_version);print(ssl.OPENSSL_VERSION)']),
                ('yt-dlp', [str(tools / ('yt-dlp' + ext)), '--version']),
                ('ffmpeg', [str(tools / ('ffmpeg' + ext)), '-version']),
                ('ffprobe', [str(tools / ('ffprobe' + ext)), '-version']),
                ('N_m3u8DL-RE', [str(tools / ('N_m3u8DL-RE' + ext)), '--help'])]
    evidence = {}
    n_help = ''
    for name, argv in commands:
        child = subprocess.run(argv, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=60)
        if child.returncode:
            raise RuntimeError(name + ' failed: ' + child.stderr[:2000])
        output = child.stdout + child.stderr
        evidence[name] = {'exitCode': child.returncode, 'output': output[:12000], 'sha256': digest(Path(argv[0]))}
        if name == 'N_m3u8DL-RE': n_help = output
    required = ('--disable-update-check', '--write-meta-json', '-sv', '-sa')
    if not all(flag in n_help for flag in required):
        raise RuntimeError('Bundled N_m3u8DL-RE lacks required engine controls')
    evidence['N_m3u8DL-RE']['capabilities'] = {flag: flag in n_help for flag in (*required, '--no-config', '--vod-select-parts', '-ds')}
    message = json.dumps({'op': 'doctor'}).encode()
    launcher = app / ('launch-host.exe' if windows else 'launch-host')
    child = subprocess.run([str(launcher)], input=struct.pack('=I', len(message)) + message, capture_output=True, env=env, timeout=60)
    if child.returncode or len(child.stdout) < 4:
        raise RuntimeError('Native launcher failed: ' + child.stderr.decode(errors='replace')[:2000])
    if struct.unpack('=I', child.stdout[:4])[0] != len(child.stdout[4:]):
        raise RuntimeError('Invalid native-message framing')
    doctor = json.loads(child.stdout[4:])
    if not doctor.get('ok'):
        raise RuntimeError('Dependency doctor failed')
    errors = []
    for tool in ('yt-dlp', 'ffmpeg', 'ffprobe', 'N_m3u8DL-RE'):
        # The runtime owns per-video N compatibility. It must still identify the installed tool.
        if str(tools / (tool + ext)) not in json.dumps(doctor):
            errors.append('Doctor did not identify bundled ' + tool)
    source = work / 'synthetic-av1.mkv'; output = work / 'synthetic-h264.mp4'
    ffmpeg = str(tools / ('ffmpeg' + ext)); ffprobe = str(tools / ('ffprobe' + ext))
    subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=25', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '0.4', '-c:v', 'libaom-av1', '-cpu-used', '8', '-c:a', 'aac', str(source)], env=env, check=True, timeout=90)
    subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i', str(source), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', str(output)], env=env, check=True, timeout=90)
    probe = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(output)], env=env))
    if not any(s.get('codec_name') == 'h264' and s.get('pix_fmt') == 'yuv420p' for s in probe['streams']):
        raise RuntimeError('Synthetic MP4 is not compatible H.264 yuv420p')
    if not any(s.get('codec_name') == 'aac' for s in probe['streams']):
        raise RuntimeError('Synthetic MP4 lacks AAC audio')
    subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(output), '-f', 'null', '-'], env=env, check=True, timeout=60)
    validate(payload)  # Tool checks must not mutate the payload being packaged.
    evidence.update({'schema': 1, 'target': spec['target'], 'host': platform.platform(), 'generatedAt': datetime.now(timezone.utc).isoformat(),
                     'payloadSHA256': digest(payload / 'payload.json'), 'nativeDoctor': doctor, 'syntheticMP4': probe,
                     'syntheticSHA256': digest(output), 'ok': not errors, 'errors': errors, 'browserVerified': False, 'gatekeeperOrSmartScreenVerified': False})
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(evidence, indent=2) + '\n')
    print(report)
    if errors:
        raise RuntimeError('; '.join(errors))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    verify(args.payload.resolve(), args.work.resolve(), args.report.resolve())
