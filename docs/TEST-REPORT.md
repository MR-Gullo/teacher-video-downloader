# Verification report — 2026-11-02

This is an unsigned tester preview. No signed distribution or production release has been verified.

## Current Mac checks

- Fifteen Python tests passed on this Mac. They cover queue controls, native-message framing, local HTTP Range and recovery with a **stub downloader**, and synthetic FFmpeg media and collision checks.
- DOM-shim assertions passed for selection, validation and queue logic. A Chrome page fixture with synthetic extension APIs showed media selection, direct-download and queue responses, and the dark theme. It is not an installed extension or native browser integration test.
- Installed yt-dlp downloaded a generated local HTTP video with a matching hash. The native-framed host and real yt-dlp worker also downloaded a generated local HTTP video with a matching hash. This did not involve an installed browser extension.
- Chrome unpacked and Zen temporary extensions were loaded on this Mac. Both reported the registered companion connected. Chrome downloaded the MDN sample through browser downloads and its native queue; Zen downloaded the sample through browser downloads and could read the completed shared queue. Zen also completed a native-queue sample with a classroom MP4 copy and a missing-caption warning. Both browser downloads and both native originals matched by SHA-256; ffprobe read the original and classroom files. Chrome popup close/reopen preserved its dark theme, and Zen dashboard reload preserved its queue and dark theme. Live Pages detected each browser and each downloaded the preview ZIP. Chrome repeated the direct-file download successfully. Full browser restart, Windows runtime, signing and permanent installs remain unverified. Chrome showed a webRequest host-permission registration warning when no optional site access had been granted. Optional stream observation remains unverified; the tested Find media button works without it. Opening the dashboard with no active web page now leaves all tabs unselected, verified in Zen after reloading the add-on. N_m3u8DL-RE, YouTube and other live-site extractors have not been tested on this Mac.

## Supplied historical evidence

The original VM test output is retained in `test-output.txt`. Its HTTP download fixture used a stub downloader, and its browser launch and browser-native integration were blocked. Those old limits describe that VM run, not the current Mac fixture. Its FFmpeg tests used synthetic media. No independent review is asserted here.

Do not rely on a download for a lesson until you have tested it on the target computer and source. See `MAC-ACCEPTANCE.md` for remaining checks. Cookies are not exported; protected or DRM media is unsupported. N retains partial directories but may re-download segments after restart.

The browser-native tests retained the sample downloads and private queue locally. Queue pause/resume was verified by the stub integration suite, not through an installed browser. In the installed Chrome popup, Tab reached a visibly outlined Find media button; Enter selected the sample, then Tab and Enter started a browser download that completed. The popup itself was opened with a pointer. Missing-companion recovery remains untested. Zen direct-download testing used its extension dashboard with a pasted sample URL. After adding the action shortcut, Option+Shift+V opened the real Zen action popup on the live sample page. Find media selected the MDN file and the browser download completed. Chrome also opened the action with the same shortcut and completed the same live sample flow.
