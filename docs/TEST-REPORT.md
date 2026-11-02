# Verification report — 2026-11-02

**Status: reviewable Mac-testing preview. Not production-ready or full wrapper parity.** Independent read-only review completed; identified cancellation, publication, sizing, naming, compatibility and manifest issues were fixed and regression-tested.

## Passed

- **15 Python tests**, full suite: URL/settings validation; path sanitization; transactional batch; duplicate enqueue/control; safe engine argv; signed-query redaction; native-messaging binary framing/doctor roundtrip; real loopback HTTP Range fixture pause/resume with byte-identical output; worker SIGTERM/restart/resume; SIGKILL inherited-lock exclusion and paused recovery; real FFmpeg classroom copy preserving selectable subtitle, chapter and frame rate; 10-bit H264 forces compatible encode; concurrent no-overwrite publication and idempotent retry; cancel-at-engine-exit race; native-response size budget.
- **14 DOM-shim UI assertions**: selection/mixed checkbox, select all/clear, no enqueue on selection change, URL/YouTube-ID parsing including commas, duplicate-click guard, validation, media-discovery logic. These are logic fixtures, **not browser rendering**.
- Python compile, extension JavaScript syntax, Chrome/Firefox JSON manifests, build folder generation.
- Extra actual FFmpeg AV1 experiment: one-second1280×720/24fps synthetic H264 source1,010,703 bytes → validated AV1 copy283,408 bytes (~72% smaller); original retained. This validates local encoder path on a synthetic sample, not general quality or Mac speed.

`test-output.txt` records the final Python suite. Tests create temporary data outside the source bundle; no user media/session data is included.

## What the engine tests actually mean

yt-dlp and N binaries were absent. HTTP Range download tests use an explicitly named **stub executable** that recognizes the adapter's output path and performs real loopback HTTP requests. Queue/IPC/process/state/file integrity is real. These tests do **not** prove yt-dlp/N flags, third-party child-descriptor behavior, extractor support, or resumption on real websites. Official current documentation informed actual adapter arguments, but the Mac must verify its installed versions.

Actual FFmpeg/ffprobe were available and executed. The original strict average-frame-rate string check initially failed on harmless Matroska→MP4 timestamp rounding (24000/1001 versus24/1 average, unchanged nominal rate). Validation now uses rational0.2% tolerance; the full suite passes after the fix.

## Blocked / not run

- Real Chromium launch: browser's AF_UNIX `socket()` denied (`Operation not permitted`). One review/UI escalation failed before launch because sandbox infrastructure could not create a denied sessions path; no bypass attempted. A main-worker fixture-only launch after local TCP evidence hit the same socket restriction.
- Supported VM browser was inspected, but its policy denied `file://` and `chrome://extensions`. Permitted HTTP fixture returned connection refused because shell server/browser contexts did not share reachable loopback. No extension installed via alternate UI.
- Consequently **no visual browser QA, screenshots, actual extension→native-host wiring, browser restart integration, Firefox runtime test, or live-site download test passed**. Runnable browser test scripts and manual acceptance checklist are supplied. No screenshots have been fabricated.
- yt-dlp, N_m3u8DL-RE, aria2c absent; no executable bundled. Live Knowledge link and authenticated playback success remain user-reported only.
- Mac installer/uninstaller only statically inspected/compiled; not executed on Mac. Native host frame test was a direct Python process, not browser-host discovery.

## Wrapper differences and limitations

Cookie/session transfer absent and rejected; Spokenly not configured/no automatic ASR; aria2c not invoked; no in-place expired-URL refresh; no signed Firefox distribution. yt-dlp native continuation is implemented; **N preserves partial directories but restart may re-download segments**. Classroom H264/AAC default replaces legacy AV1 default; AV1 remains opt-in and source-preserving. File names include a short job ID for safe/idempotent collision handling. Download/provenance data remains local; signed input URL must persist privately for retry.

Read MAC-ACCEPTANCE.md for the exact next tests. Do not schedule a classroom lesson around an untested live download.
