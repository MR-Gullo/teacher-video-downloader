# LessonShelf

LessonShelf saves permitted classroom videos and YouTube clips. It defaults to a compatible MP4 with H.264 video and AAC audio at up to 720p. Firefox and Zen use a companion that includes the download tools on Windows x64 and Mac.

## Install

Use the [LessonShelf installation page](https://mr-gullo.github.io/teacher-video-downloader/#setup). It shows only available release downloads. Install the Firefox extension, then the companion for your computer. Return to LessonShelf and choose **Check connection**.

The Mozilla-signed Firefox / Zen 0.3.1 extension is available in the [testing release](https://github.com/MR-Gullo/teacher-video-downloader/releases/tag/v0.3.1). The Windows x64 companion is available from the installation page. See the [visual guide](docs/qa/LessonShelf-feature-and-UX-guide.pdf) for tested paths and current limits. The Windows companion has passed real Windows Firefox fixture tests. It is not yet code-signed. The normal Mac installer still needs Developer ID signing and notarization. Chrome, Windows ARM64 and mobile browsers are outside this beta. Source archives and temporary add-ons are for development, not teacher installation.

## Download a video

1. Open the video and start playback.
2. Open LessonShelf and choose **Download video**.
3. When it says Saved, choose **Show in folder** on Windows or **Show in Finder** on Mac.

If a page has more than one video, choose the intended player. **Paste link** accepts one HTTP or HTTPS video link. Direct MP4, WebM and audio files can use the browser download path without the companion. Browser downloads keep the source quality and use the browser's destination folder.

## Download a YouTube clip

On a supported YouTube watch page, open **Download settings** and enable **Download a clip**. In starts at the current playhead, rounded down to a second. Out starts at the end. Drag the two handles, use their arrow keys, or enter times. Choose Download.

Changing the range prepares the next clip. It does not change or stop a submitted job. Click Download for the new range to queue it behind the running job. The original range and progress stay visible. A repeated active range does not create a duplicate. Clips use standard MP4 video and omit captions and extra copies. Ads, live streams and unsupported player contexts cannot be clipped.

## Settings and output

- Fresh installs default to video and audio, up to 720p, English captions if available, and no extra copy. Light mode is the default; dark mode is available.
- Quality caps include 480p and 720p. The shorter side is capped, so portrait video uses its width. Low-resolution video is not enlarged.
- Standard MP4 uses H.264/yuv420p and AAC for compatibility. Original preserves the source format. AV1 is an optional storage format and may not play on older classroom equipment. Audio-only saves M4A.
- The companion chooses a compatible engine for each video. It includes yt-dlp, FFmpeg, FFprobe, N_m3u8DL-RE and Deno. Teachers do not install these separately.
- Missing captions produce a warning. No cloud transcription runs automatically.
- Companion downloads normally go to the user's Downloads/youtube-downloads folder. A course subfolder is optional. Source metadata stays in private job storage; new JSON sidecars are not published beside the video.

## Queue and recovery

Downloads shows running, queued and saved jobs. Closing the popup or browser does not stop an already-started companion job while the computer remains awake. Pause and Cancel retain partial files. Resume and Retry reuse the job's private directory; an engine can re-download segments. After a worker or operating-system interruption, interrupted jobs become paused and need Resume. Completed jobs are reused when the same video and settings are requested.

Updates preserve the queue, partials, downloaded files and output location. They refuse active workers and unknown installations. The previous program and registration are retained for rollback.

## Access and privacy

Download only videos you have permission to save. Sites can refuse access or limit requests. Protected media, DRM removal and sign-in or geographic bypass are not supported. The companion does not read browser profiles or export cookies or Authorization headers. Browser-managed downloads may send normal site cookies. Firefox asks permission before selected page and video links are sent to the companion on this computer. Private browsing is unavailable.

## Verification and development

[Windows Firefox acceptance](https://github.com/MR-Gullo/teacher-video-downloader/actions/workflows/windows-firefox-qa.yml) runs the real Windows installer, bundled tools, Firefox/native messaging, clip media, progress, recovery and worker isolation on a Windows runner. Local media fixtures establish those paths, not support for every provider. The visual feature guide and its evidence inventory record live provider results separately.

```sh
python3 -m unittest discover -s tests -v
node tests/ui-unit.cjs
node tests/clip-ui.cjs
node tests/clip-running.cjs
node tests/background-consent.cjs
node tests/progress-unit.cjs
python3 scripts/build.py
```

See [architecture](docs/ARCHITECTURE.md), [Windows packaging](docs/WINDOWS-INSTALLER.md), [Mac packaging](docs/MAC-INSTALLER.md), and [engine notes](docs/ENGINE-NOTES.md). Temporary add-ons are removed when Firefox or Zen closes. Published tester installation uses a Mozilla-signed XPI.
