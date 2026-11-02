# LessonShelf · Local Video

**Unsigned Windows and Mac tester preview.** The extension can save supported direct media files through the browser. The optional companion adds a local queue and conversion on Mac. Chrome and Zen preview installs and native messaging were tested on this Mac; Windows and signed distribution remain unverified.

## Start here

Open the [tester setup page](https://mr-gullo.github.io/teacher-video-downloader/) for browser-specific steps. In this source folder, open `index.html` in a browser. Get the preview ZIP, load the Chrome folder unpacked or load the Firefox manifest as a temporary add-on, then try the sample video on the page. Firefox and Zen require reloading the temporary add-on after restart. Chrome developer mode is required. This is not a signed store release.

On either platform, press Option+Shift+V on Mac or Alt+Shift+V on Windows to open LessonShelf on a video page, choose **Find media**, and use **Download direct files in browser** for a selected MP4, WebM, MP3, M4A or WAV link. Browser downloads use the browser's downloads folder and may send the browser's normal cookies for the requested site. Sites can refuse access, and protected media is unsupported.

On Mac, the optional local companion provides page extraction, queue recovery, and conversion. Follow [Mac setup](docs/MAC-SETUP.md) and the [acceptance checklist](docs/MAC-ACCEPTANCE.md). See [test evidence](docs/TEST-REPORT.md). The companion and its tools are not available on Windows in this preview.

### Teacher defaults

- Companion output defaults to `~/Downloads/youtube-downloads`; optional course folder. `YTDL_OUTPUT_DIR` can override the location.
- Prefer a source at or below 1080p; retain it. If a direct file has no reported height, its resolution cannot be checked before download. An optional H.264/AAC MP4 copy is prepared for projectors.
- English captions and chapters are requested when available. Missing captions are reported. An optional AV1 copy is for storage and may take longer.
- The original and partial files are retained. No automatic cleanup deletes recovery data.

### Direct file downloads

Select or paste a direct MP4, WebM, MP3, M4A or WAV file link and choose **Download direct files in browser**. The browser controls the download and destination; this path does not use the companion, conversion or durable queue. A link ending in one of these extensions does not guarantee the server will allow a download.

### Everyday flow

Open the extension on the lesson page. Choose current page, open tabs or detected direct media; check the videos wanted. Select all/Clear only changes selection: **Download selected** is the only queue-start action. You can also paste HTTP(S) links or11-character YouTube IDs, separated by new lines or comma+space. Commas *inside* URLs are retained. Batch maximum50.

The advanced N_m3u8DL-RE engine takes direct `.m3u8` / `.mpd` URLs, not an ordinary webpage. Enable detection only for the site you choose, then play/reload the video. A `blob:` URL is not independently downloadable. **N does not have a documented general cross-process resume switch: Restart may re-download segments even though its temporary files are retained.** Site/CDN permissions and browser security can limit detection. Having a playing video does not guarantee a reproducible download.

Close the popup or browser: already-started jobs continue locally while the Mac is awake. Reopen to see the durable queue. Pause/cancel retains partial files; Resume/Retry uses the same private job directory. After worker/OS interruption, the next connection marks interrupted jobs paused; explicitly Resume. Sleep suspends execution; this is not a power-management tool.

### Important boundaries

- No DRM key extraction, decryption-key entry, access/geographic restriction bypass, or browser-profile dumping.
- **Authenticated-cookie export is not implemented in this preview.** The companion does not read or export cookies or authorization headers. Browser-managed downloads make normal site requests and may send the browser's site cookies. Public or already-authorized signed media URLs may work until expiry. N's domain-scoped cookie feature is not exposed here. Do not paste secrets into titles/logs.
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

See [test evidence](docs/TEST-REPORT.md), [architecture/security](docs/ARCHITECTURE.md), and [capability references](docs/ENGINE-NOTES.md).
