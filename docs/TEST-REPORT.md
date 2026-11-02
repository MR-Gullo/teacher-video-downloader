# Verification report — 2026-11-02

This is an unsigned tester preview. No signed distribution or production release has been verified.

## Current Mac checks

- Fifteen Python tests passed on this Mac. They cover queue controls, native-message framing, local HTTP Range and recovery with a **stub downloader**, and synthetic FFmpeg media and collision checks.
- DOM-shim assertions passed for selection, validation and queue logic. A Chrome page fixture with synthetic extension APIs showed media selection, direct-download and queue responses, and the dark theme. It is not an installed extension or native browser integration test.
- Installed yt-dlp downloaded a generated local HTTP video with a matching hash. The native-framed host and real yt-dlp worker also downloaded a generated local HTTP video with a matching hash. This did not involve an installed browser extension.
- Chrome and Zen installation, native-host discovery, actual browser download, restart/reopen, Windows runtime, signing and permanent installs remain unverified. N_m3u8DL-RE, YouTube and other live-site extractors have not been tested on this Mac.

## Supplied historical evidence

The original VM test output is retained in `test-output.txt`. Its HTTP download fixture used a stub downloader, and its browser launch and browser-native integration were blocked. Those old limits describe that VM run, not the current Mac fixture. Its FFmpeg tests used synthetic media. No independent review is asserted here.

Do not rely on a download for a lesson until you have tested it on the target computer and source. See `MAC-ACCEPTANCE.md` for remaining checks. Cookies are not exported; protected or DRM media is unsupported. N retains partial directories but may re-download segments after restart.
