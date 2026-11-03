# LessonShelf · Local Video

**Local 0.3.0 Firefox/Zen preview.** The redesigned extension can save supported direct media files through the browser. The Mac companion adds a local queue. This 0.3.0 preview is temporary and unsigned; the separate 0.2.1 release was signed for self-distribution. Chrome release work is paused, and Windows has not been verified.

## Start here

Build the local preview with `python3 scripts/build.py`. Load `build/firefox/manifest.json` as a temporary add-on in Firefox or Zen. Temporary add-ons must be reloaded after a browser restart. Published downloads and documentation may still describe an older version.

Open LessonShelf on a video page and choose **Download video**. On Mac, the normal shortcut is Option+Shift+V. The separately installed temporary preview may use a different shortcut. Paste a direct MP4, WebM, MP3, M4A or WAV link to use **Download original in browser**. Browser downloads use the browser’s download folder and may send normal site cookies. Sites can refuse access, and protected media is unsupported.

On Mac, the optional local companion provides page extraction, queue recovery, and conversion. Follow [Mac setup](docs/MAC-SETUP.md) and the [acceptance checklist](docs/MAC-ACCEPTANCE.md). See [test evidence](docs/TEST-REPORT.md). The companion and its tools are not available on Windows in this preview.

### Teacher defaults

- Companion output defaults to `~/Downloads/youtube-downloads`; optional course folder. `YTDL_OUTPUT_DIR` can override the location.
- Default to video and audio at up to 720p, measured on the shorter side so portrait and landscape videos use the same limit. Retain the downloaded file without an additional encode. An optional projector or storage copy can be selected in Download settings. A companion video with an unknown dimension or a shorter side above the selected limit is retained privately but not published as a completed result.
- English captions and chapters are requested when available. Missing captions are reported. An optional AV1 copy is for storage and may take longer.
- The original and partial files are retained. No automatic cleanup deletes recovery data.

### Direct file downloads

Choose **Paste link**, enter a direct MP4, WebM, MP3, M4A or WAV link, and choose **Download original in browser**. The browser controls the download and destination; this path does not use the companion, conversion or durable queue. A link ending in one of these extensions does not guarantee the server will allow a download.

### Everyday flow

Open the extension on the current lesson page and choose **Download video**. If several players are present, select the intended video. You can also use **Paste link** for one HTTP(S) link. The main popup shows progress and offers **Show in Finder** when a file is saved. Download settings and Help & setup are available below the main controls. Firefox asks for permission before sending page and candidate media links to the local companion.

The companion identifies a matching clear HLS master when the page provides enough evidence. It uses a compatible local engine automatically and can fall back to yt-dlp on a startup or compatibility failure. It does not bypass access, geographic restrictions or protected media. A site can remain unsupported, and an expired signed link may need to be refreshed. An N download can restart segments even when its temporary files are retained. If an engine cannot report progress, the progress bar is indeterminate. Sources confirmed to have no audio are saved with a warning.

Close the popup or browser: already-started jobs continue locally while the Mac is awake. Reopen to see the durable queue. Pause/cancel retains partial files; Resume/Retry uses the same private job directory. After worker/OS interruption, the next connection marks interrupted jobs paused; explicitly Resume. Sleep suspends execution; this is not a power-management tool.

### Important boundaries

- No DRM key extraction, decryption-key entry, access/geographic restriction bypass, or browser-profile dumping.
- **Authenticated-cookie export is not implemented in this preview.** The companion does not read or export cookies or authorization headers. Browser-managed downloads make normal site requests and may send the browser's site cookies. Public or already-authorized signed media URLs may work until expiry. N's domain-scoped cookie feature is not exposed here. Do not paste secrets into titles/logs.
- **Spokenly is explicitly not configured.** Its actual interface and backend privacy were not supplied or verified; no invented flags and no automatic cloud fallback. Doctor states this clearly.
- yt-dlp and FFmpeg must be installed separately. N_m3u8DL-RE is optional and is used only when its compatibility checks pass. The Knowledge Network preview used yt-dlp after N did not complete its metadata check; a successful N media download was not verified.
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
