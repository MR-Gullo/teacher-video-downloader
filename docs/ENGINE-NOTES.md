# Engine capability notes — official docs reviewed 2026-11-02

## yt-dlp

Primary adapter uses `--continue`/`.part`, native fragment state, bounded retry/backoff and aborts on missing fragments rather than silently accepting holes. Ignores user config/plugins and disables remote components and browser-cookie loading. Requests English manual+auto subtitles, converts to SRT and embeds. Chapters are embedded; broad `--embed-metadata` is deliberately avoided because its webpage URL comment can contain signed query credentials. Sanitized provenance is saved separately and embedded in classroom copies.

Official docs: https://github.com/yt-dlp/yt-dlp (Download Options, Filesystem Options, Post-Processing Options).
YouTube JS runtime/EJS setup: https://github.com/yt-dlp/yt-dlp/wiki/EJS . Current compatibility must be tested on the Mac. The VM could not install/run yt-dlp; adapter arguments were inspected and stub-tested, not a live engine claim.

## N_m3u8DL-RE

Real adapter selects tracks, downloads to a stable private segment directory and muxes through FFmpeg. The adapter disables log/meta JSON, update checks and the system proxy, and bounds segment retries while retaining segments. Unknown binaries must support explicit no-config and VOD prompting controls. The three pinned 0.6.0-beta executables are identified by exact SHA-256 and use their version-specific flags; that version does not expose those two switches. It never supplies keys, key files, custom decryption options or cookie headers. English subtitle filter is requested, availability unverified. No documented generic cross-process resume switch was found; **there is no fabricated `--continue` flag**. Restart can fetch segments again. The advanced UI warning and Restart label make that distinction visible.

Official current English reference: https://github.com/nilaoda/N_m3u8DL-RE/blob/main/README.en.md . Releases: https://github.com/nilaoda/N_m3u8DL-RE/releases . Current reference identifies0.6.0/20261012; installed older binaries can differ. The adapter checks required privacy options before downloading. On a local Mac HLS fixture, the pinned arm64 engine passed preflight but its redirected console crashed during download. The worker detects this specific console failure and retries the same job with yt-dlp in a separate private directory; that fallback completed the fixture. A tool check or preflight alone does not prove the engine can complete a given video. Windows and Intel Mac execution remain unverified. The user's report of success while the Knowledge video streamed is not independently verified by this project; it is not a promise this adapter handles that protected/authenticated session.

## FFmpeg

Actual VM synthetic-media tests run successfully. Encoder availability differs by package; use `ffmpeg -encoders` on the Mac to confirm libx264, AAC and optional libsvtav1. Official tools and stream mapping: https://ffmpeg.org/ffmpeg.html . No shell string interpolation. Original source kept. AV1 is an opt-in storage copy, not the recommended projector format.

## aria2c

Not invoked in this preview. Engine-native continuation is used instead. If added later for direct HTTP files, it needs stable output names, `.aria2` control files, Range support and validator-aware handling; `-c` alone cannot guarantee every interrupted server download resumes. Official documentation: https://aria2.github.io/manual/en/html/aria2c.html . There is no unauthenticated aria2 RPC service here.
