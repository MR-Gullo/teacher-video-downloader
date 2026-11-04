"""Exercise the bundled N engine on an unencrypted local HLS master with captured output."""
import argparse
import functools
import http.server
import json
import os
from pathlib import Path
import runpy
import subprocess
import threading


def check(payload, report, work):
    work.mkdir(parents=True, exist_ok=False)
    tools = payload / 'tools'
    suffix = '.exe' if os.name == 'nt' else ''
    ffmpeg, ffprobe, engine = (tools / (name + suffix) for name in ('ffmpeg', 'ffprobe', 'N_m3u8DL-RE'))
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ.get('PATH', ''), DENO_NO_UPDATE_CHECK='1')
    fixture = work / 'fixture'
    fixture.mkdir()
    subprocess.run([str(ffmpeg), '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=10',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '6', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-g', '20', '-sc_threshold', '0', '-c:a', 'aac', '-f', 'hls',
                    '-hls_time', '2', '-hls_playlist_type', 'vod', str(fixture / 'media.m3u8')], check=True, env=env, timeout=60)
    (fixture / 'master.m3u8').write_text('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=640x360,CODECS="avc1.42E01E,mp4a.40.2"\nmedia.m3u8\n')
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(fixture)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = work / 'output'
    output.mkdir()
    core = runpy.run_path(str(payload / 'companion/core.py'))
    data = {'engine': 'n', '_known_n': True, '_n_path': str(engine), 'audio': False, 'captions': False,
            'quality': '720', 'url': f'http://127.0.0.1:{server.server_port}/master.m3u8'}
    argv = core['engine_argv'](data, output)
    evidence = {'platform': os.name, 'fixture': 'local clear HLS master with muxed H264/AAC', 'outputMode': 'captured pipes', 'ok': False}
    try:
        child = subprocess.run(argv, cwd=output, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=90)
        log = (child.stdout + child.stderr).decode(errors='replace')
        evidence.update(exitCode=child.returncode, outputTail=log[-10000:])
        files = [path for path in output.iterdir() if path.is_file() and path.suffix in ('.mkv', '.mp4')]
        if child.returncode == 0 and files:
            media = max(files, key=lambda path: path.stat().st_size)
            probe = json.loads(subprocess.check_output([str(ffprobe), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(media)], env=env))
            subprocess.run([str(ffmpeg), '-v', 'error', '-xerror', '-i', str(media), '-f', 'null', '-'], check=True, env=env, timeout=60)
            evidence.update(ok=True, streams=[{'codec': stream.get('codec_name'), 'type': stream.get('codec_type')} for stream in probe['streams']], duration=probe['format'].get('duration'), fullDecode=True)
    except (OSError, subprocess.SubprocessError) as error:
        evidence['error'] = str(error)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'ok': evidence['ok'], 'report': str(report)}))
    return evidence['ok']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if check(args.payload.resolve(), args.report.resolve(), args.work.resolve()) else 1)
