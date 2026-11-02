# LessonShelf extension

Run `python3 scripts/build.py` from the project root. Load `build/chrome` as an unpacked Chrome extension, or load `build/firefox/manifest.json` as a temporary Firefox or Zen add-on. The Firefox ID is `teacher-video-downloader@local.invalid`. The two browser-specific manifests are the source of their respective builds.

Open LessonShelf on a video page with Option+Shift+V on Mac or Alt+Shift+V on Windows. If the shortcut is already in use, change the extension shortcut in the browser. Select Find media, then use Download direct files in browser. Direct file downloads use the browser download manager and its normal site requests. The optional Mac companion handles its local queue and conversion. Selecting checkboxes alone does not start a download.

The companion does not read or export browser cookies, profiles or authorization headers. Browser-managed downloads may send normal site cookies. Signed URLs may be sensitive. Candidate URLs remain in extension local storage until tab cleanup; queue URLs remain in the private companion state. Do not publish browser state or the queue database. The interface displays URL host and path without query strings.

Stream detection needs an explicit site permission grant and may miss cross-origin CDN requests. See `docs/TEST-REPORT.md` for current evidence and unverified paths.
