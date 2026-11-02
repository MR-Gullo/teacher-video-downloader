# LessonShelf · Local Video

**Reviewable preview for Mac testing — not yet live-site or browser-integration validated.**

A Chrome/Firefox extension and small Python native-messaging companion for saving videos you have permission to use in class. No web service, account, telemetry, remote download proxy, cloud transcription, or bundled third-party executable. Built in the VM; nothing has been installed on your Mac.

## Start here

1. Read [Mac setup](docs/MAC-SETUP.md).
2. Load the appropriate extension build and install the user-scoped companion.
3. Open **Dependency check**, then try one short, freely downloadable video before a lesson batch.
4. Follow the [Mac acceptance checklist](docs/MAC-ACCEPTANCE.md). See [test evidence and gaps](docs/TEST-REPORT.md) before relying on it.

### Teacher defaults

- Save under `~/Downloads/youtube-downloads`; optional course folder. `YTDL_OUTPUT_DIR` overrides the location; installer `--output-dir` persists it for browser launches.
- Prefer a source at or below 1080p; retain it. Also prepare a broadly compatible H.264, 8-bit yuv420p / AAC MP4 classroom copy. Compatible H.264 video and AAC audio are copied instead of recompressed. No forced frame-rate reduction.
- Request English manual and automatic captions; yt-dlp converts to SRT and embeds selectable subtitles. Classroom MP4 uses selectable `mov_text`, **not** burned-in captions. Availability varies; missing captions are a warning, never invented. Temporary SRTs are removed after success; originals/sidecars remain on failures.
- Keep chapters. Save sanitized source provenance beside the video; classroom copy also embeds that source in its comment. Signed query parameters are excluded (YouTube video ID retained). Provider-origin metadata may remain in source media.
- Optional AV1 storage copy is slower and less projector-compatible. It is attempted only for sources at least 720p and not already AV1/HEVC/VP9; capped at1080p; kept only after full decode/track/chapter/frame-rate checks **and** at least15% reduction. Original remains.
- Stable names look like `00_Lesson title_1a2b3c4d_original.mkv` and `00_Lesson title_1a2b3c4d_classroom.mp4`. The short job ID prevents collisions; files are published atomically without replacement. Original format is not falsely labelled MP4.

### Everyday flow

Open the extension on the lesson page. Choose current page, open tabs or detected direct media; check the videos wanted. Select all/Clear only changes selection: **Download selected** is the only queue-start action. You can also paste HTTP(S) links or11-character YouTube IDs, separated by new lines or comma+space. Commas *inside* URLs are retained. Batch maximum50.

The advanced N_m3u8DL-RE engine takes direct `.m3u8` / `.mpd` URLs, not an ordinary webpage. Enable detection only for the site you choose, then play/reload the video. A `blob:` URL is not independently downloadable. **N does not have a documented general cross-process resume switch: Restart may re-download segments even though its temporary files are retained.** Site/CDN permissions and browser security can limit detection. Having a playing video does not guarantee a reproducible download.

Close the popup or browser: already-started jobs continue locally while the Mac is awake. Reopen to see the durable queue. Pause/cancel retains partial files; Resume/Retry uses the same private job directory. After worker/OS interruption, the next connection marks interrupted jobs paused; explicitly Resume. Sleep suspends execution; this is not a power-management tool.

### Important boundaries

- No DRM key extraction, decryption-key entry, access/geographic restriction bypass, or browser-profile dumping.
- **Authenticated-cookie export is not implemented in this preview.** No cookies or authorization headers are read/sent. Public or already-authorized signed media URLs may work until expiry. N's domain-scoped cookie feature is not exposed here. Do not paste secrets into titles/logs.
- **Spokenly is explicitly not configured.** Its actual interface and backend privacy were not supplied or verified; no invented flags and no automatic cloud fallback. Doctor states this clearly.
- yt-dlp, FFmpeg and N must be installed separately. N's real adapter is present; the binary and live services were unavailable to verify here. aria2c is optional for a future/external direct-file workflow; this build does not invoke it.
- Original downloads, failed partials and queue history are intentionally retained. They consume disk. No automatic cleanup erases recovery data; see the setup guide for deliberate cleanup.

## Development / audit

Python3.11+ standard library; no Python runtime dependency to install for the companion itself.

```sh
python3 -m unittest discover -s tests -v
node tests/ui-unit.cjs
python3 scripts/build.py
python3 companion/cli.py --doctor
# Preview a non-destructive copy; prints argv, does not encode by default:
python3 companion/cli.py --input /path/to/video.mkv --mode classroom
# Explicitly create/validate a copy (will not overwrite an existing copy):
python3 companion/cli.py --input /path/to/video.mkv --mode av1 --execute
# No compression:
python3 companion/cli.py --input /path/to/video.mkv --mode none
```

Browser tests need Playwright and a permitted local Chromium launch. They are prepared, but this VM's Chromium launch/browser URL policies blocked visual and integration tests. They are not labelled passed. See [architecture/security](docs/ARCHITECTURE.md) and [official capability references](docs/ENGINE-NOTES.md).
