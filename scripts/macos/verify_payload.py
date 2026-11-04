#!/usr/bin/env python3
"""Run real bundled tools and a staged native-messaging/MP4 check on the matching host."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import queue
import signal
import struct
import subprocess
import tempfile
import threading
from install_payload import digest, install, validate, check_bundle, bundle_digest


class NativeTransportError(RuntimeError):
    def __init__(self, message, evidence):
        super().__init__(message)
        self.evidence = evidence


def native_doctor(argv, env, timeout=60, exit_timeout=10):
    """Receive one complete reply while the browser's input pipe remains open."""
    evidence = {'launcher': str(argv[0]), 'requestBytesWritten': 0, 'stdoutBytes': 0,
                'headerBytes': 0, 'responseBytes': 0, 'trailingStdoutBytes': 0, 'stderrBytes': 0,
                'stdinOpenWhenResponseReceived': False, 'inputClosedAfterResponse': False,
                'timedOut': False, 'cleanupPerformed': False, 'phase': 'start'}
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   bufsize=0, env=env, **options)
    except OSError as error:
        evidence.update(ok=False, exitCode=None, stderr=str(error))
        raise NativeTransportError('Native launcher could not start: ' + str(error), evidence) from error
    evidence['pid'] = process.pid
    replies = queue.Queue()
    stderr = bytearray()

    def read_exact(size, counter):
        data = bytearray()
        while len(data) < size:
            chunk = process.stdout.read(size - len(data))
            if not chunk:
                raise RuntimeError('Native response ended before ' + counter)
            data.extend(chunk)
            evidence[counter] += len(chunk)
            evidence['stdoutBytes'] += len(chunk)
        return bytes(data)

    def reader():
        try:
            prefix = read_exact(4, 'headerBytes')
            size = struct.unpack('=I', prefix)[0]
            evidence['frameDeclaredBytes'] = size
            if not 0 < size <= 512 * 1024:
                raise RuntimeError('Invalid native response frame length')
            response = json.loads(read_exact(size, 'responseBytes'))
            replies.put(response)
            while chunk := process.stdout.read(8192):
                evidence['stdoutBytes'] += len(chunk)
                evidence['trailingStdoutBytes'] += len(chunk)
        except Exception as error:
            replies.put(error)

    def error_reader():
        try:
            while chunk := process.stderr.read(8192):
                evidence['stderrBytes'] += len(chunk)
                stderr.extend(chunk[:max(0, 4096 - len(stderr))])
        except (OSError, ValueError) as error:
            evidence['stderrReadError'] = str(error)

    threads = [threading.Thread(target=reader, daemon=True), threading.Thread(target=error_reader, daemon=True)]
    for thread in threads:
        thread.start()
    failure = None
    response = None
    try:
        evidence['phase'] = 'send_request'
        message = json.dumps({'op': 'doctor'}).encode()
        frame = struct.pack('=I', len(message)) + message
        while evidence['requestBytesWritten'] < len(frame):
            count = process.stdin.write(frame[evidence['requestBytesWritten']:])
            if not count:
                raise RuntimeError('Native request pipe closed')
            evidence['requestBytesWritten'] += count
        process.stdin.flush()
        evidence['phase'] = 'read_response'
        response = replies.get(timeout=timeout)
        if isinstance(response, Exception):
            raise response
        evidence['stdinOpenWhenResponseReceived'] = not process.stdin.closed
        if not isinstance(response, dict) or not response.get('ok'):
            raise RuntimeError('Dependency doctor returned an unsuccessful response')
        process.stdin.close()
        evidence['inputClosedAfterResponse'] = True
        evidence['phase'] = 'wait_for_exit'
        process.wait(timeout=exit_timeout)
        for thread in threads:
            thread.join(timeout=1)
        if process.returncode != 0:
            raise RuntimeError('Native launcher exited with ' + str(process.returncode))
        if any(thread.is_alive() for thread in threads):
            raise RuntimeError('Native launcher left a response or error pipe open')
        if 'stderrReadError' in evidence:
            raise RuntimeError('Could not read native launcher error pipe')
        if evidence['trailingStdoutBytes']:
            raise RuntimeError('Unexpected bytes after the native response frame')
        evidence['phase'] = 'complete'
    except (queue.Empty, subprocess.TimeoutExpired):
        evidence['timedOut'] = True
        failure = 'Native launcher timed out during ' + evidence['phase']
    except Exception as error:
        failure = str(error)
    finally:
        try:
            if process.poll() is None:
                # Preserve a naturally exiting child's code before terminating a hung tree.
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    evidence['cleanupPerformed'] = True
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                    else:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired) as error:
            evidence['cleanupError'] = str(error)
            failure = failure or 'Native launcher cleanup failed'
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
        for thread in threads:
            thread.join(timeout=1)
        evidence['exitCode'] = process.returncode
        evidence['stderr'] = stderr.decode(errors='replace')
        evidence['ok'] = failure is None
    if failure:
        raise NativeTransportError(failure, evidence)
    return response, evidence


def n_identity_evidence(installed_payload, env):
    """Use the installed runtime's recognition code, not the checkout's allowlist."""
    core = installed_payload / 'companion/core.py'
    script = '''import json, runpy, sys
from pathlib import Path
core = runpy.run_path(sys.argv[1])
binary = Path(sys.argv[2])
result = {'macho_content_digest': None}
try:
    result['macho_content_digest'] = core['macho_content_digest'](binary)
except (ValueError, OSError) as error:
    result['macho_content_digest_error'] = type(error).__name__ + ': ' + str(error)
result['signed_known_n'] = core['signed_known_n'](binary)
print(json.dumps(result))
'''
    child = subprocess.run([str(installed_payload / 'runtime/bin/python3'), '-B', '-I', '-c', script,
                            str(core), str(installed_payload / 'tools/N_m3u8DL-RE')],
                           env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=True)
    return {**json.loads(child.stdout), 'coreSHA256': digest(core)}


def verify(payload, work, report, companion_app=None):
    spec = validate(payload)
    windows = os.name == 'nt'
    work.mkdir(parents=True, exist_ok=True)
    account = work / 'Test teacher account'
    result = install(payload, account, staging=True, companion_app=companion_app)
    base = Path(result['destination']); app = base / 'app'
    installed_payload = app / 'LessonShelf Companion.app/Contents/Resources/payload' if companion_app else app
    tools = installed_payload / 'tools'
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ.get('PATH', ''), PYTHONDONTWRITEBYTECODE='1', DENO_NO_UPDATE_CHECK='1')
    ext = '.exe' if windows else ''
    commands = [('python', [str(installed_payload / ('runtime/python.exe' if windows else 'runtime/bin/python3')), '-B', '-I', '-c', 'import sqlite3,ssl,sys;print(sys.version);print(sqlite3.sqlite_version);print(ssl.OPENSSL_VERSION)']),
                ('yt-dlp', [str(tools / ('yt-dlp' + ext)), '--version']),
                ('ffmpeg', [str(tools / ('ffmpeg' + ext)), '-version']),
                ('ffprobe', [str(tools / ('ffprobe' + ext)), '-version']),
                ('deno', [str(tools / ('deno' + ext)), '--version']),
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
    provenance = json.loads((installed_payload / 'PROVENANCE.json').read_text())
    expected_deno = provenance['dependencies']['deno-' + spec['target']]['version']
    if not evidence['deno']['output'].startswith('deno ' + expected_deno + ' '):
        raise RuntimeError('Bundled Deno version differs from pinned provenance')
    # A version check does not initialize V8's JIT. Exercise JavaScript in the
    # installed signed executable with no network, imports, npm or OS permissions.
    js = '''const f = new Function('x', 'return x + 1');
let sum = 0; for (let i = 0; i < 50000; i++) sum += f(i);
const permissions = {};
for (const name of ['read', 'write', 'net', 'env', 'run', 'ffi', 'sys']) {
  permissions[name] = (await Deno.permissions.query({name})).state;
}
console.log(JSON.stringify({version: Deno.version.deno, sum, permissions}));
'''
    js_env = dict(env, DENO_NO_UPDATE_CHECK='1', DENO_NO_PACKAGE_JSON='1', DENO_DIR=str(work / 'deno-cache'))
    js_result = subprocess.run([str(tools / ('deno' + ext)), 'run', '--no-config', '--no-remote', '--no-npm',
                                '--no-lock', '--cached-only', '--no-prompt',
                                '--deny-read', '--deny-write', '--deny-net', '--deny-env', '--deny-run', '--deny-ffi', '--deny-sys', '-'],
                               input=js, capture_output=True, text=True, env=js_env, check=True, timeout=30)
    js_evidence = json.loads(js_result.stdout)
    if js_evidence['version'] != expected_deno or js_evidence['sum'] != 1250025000 or any(state != 'denied' for state in js_evidence['permissions'].values()):
        raise RuntimeError('Bundled Deno failed restricted offline JavaScript execution')
    evidence['deno']['restrictedOfflineJavaScript'] = js_evidence
    required = ('--disable-update-check', '--write-meta-json', '-sv', '-sa')
    if not all(flag in n_help for flag in required):
        raise RuntimeError('Bundled N_m3u8DL-RE lacks required engine controls')
    evidence['N_m3u8DL-RE']['capabilities'] = {flag: flag in n_help for flag in (*required, '--no-config', '--vod-select-parts', '-ds')}
    if not windows:
        identity_env = dict(env, TVD_STATE_DIR=str(base), YTDL_OUTPUT_DIR=str(account / 'Downloads/youtube-downloads'))
        evidence['N_m3u8DL-RE']['identity'] = n_identity_evidence(installed_payload, identity_env)
    launcher = app / 'LessonShelf Companion.app/Contents/MacOS/LessonShelfHost' if companion_app else app / ('launch-host.exe' if windows else 'launch-host')
    try:
        doctor, transport = native_doctor([str(launcher)], env)
    except NativeTransportError as error:
        evidence.update({'ok': False, 'errors': [str(error)], 'nativeTransport': error.evidence,
                         'target': spec['target'], 'browserVerified': False, 'gatekeeperOrSmartScreenVerified': False})
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(evidence, indent=2) + '\n')
        raise
    evidence['nativeTransport'] = transport
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
    if companion_app:
        installed_bundle = app / 'LessonShelf Companion.app'
        check_bundle(installed_bundle)
        if bundle_digest(installed_bundle) != bundle_digest(companion_app):
            raise RuntimeError('Installed sealed companion changed')
    evidence.update({'installedSealedBundleUnchanged': True if companion_app else None, 'schema': 1, 'target': spec['target'], 'host': platform.platform(), 'generatedAt': datetime.now(timezone.utc).isoformat(),
                     'payloadSHA256': digest(payload / 'payload.json'), 'nativeDoctor': doctor, 'syntheticMP4': probe,
                     'syntheticSHA256': digest(output), 'ok': not errors, 'errors': errors, 'browserVerified': False, 'gatekeeperOrSmartScreenVerified': False})
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(evidence, indent=2) + '\n')
    print(report)
    if errors:
        raise RuntimeError('; '.join(errors))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--payload', type=Path)
    group.add_argument('--companion-app', type=Path)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    companion = args.companion_app.resolve() if args.companion_app else None
    payload = companion / 'Contents/Resources/payload' if companion else args.payload.resolve()
    verify(payload, args.work.resolve(), args.report.resolve(), companion)
