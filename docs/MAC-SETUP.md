# Set up the optional Mac companion

Direct MP4, WebM, MP3, M4A and WAV files can be downloaded by the extension through your browser. The local queue, HLS streams and video conversion need this separate Mac companion and its tools. The extension does not include them. Windows does not currently have a companion.

The redesigned 0.3.0 Firefox / Zen build is an unsigned temporary preview. Install the intended extension before following these companion steps. Only save videos you have permission to use. Protected media is not supported.

## 1. Install the required tools

If you already use Homebrew on your Mac, open Terminal and run:

```sh
brew install python yt-dlp ffmpeg
```

The companion uses Python, yt-dlp and FFmpeg installed on your Mac. It does not export your browser cookies. Some sites or media may not be supported. The optional N_m3u8DL-RE engine has additional setup in [ENGINE-NOTES.md](ENGINE-NOTES.md); it is not required for the default engine.

## 2. Install the companion for Firefox / Zen

1. Open the [LessonShelf source repository](https://github.com/MR-Gullo/teacher-video-downloader). Choose **Code**, then **Download ZIP**.
2. Unzip the download and open the extracted folder in Terminal. Review the source before running its installer.
3. Run:

```sh
python3 scripts/install-macos.py --firefox
```

4. Open LessonShelf, expand **Help & setup**, and choose **Check connection**, then **Check local tools**. The fixed Firefox add-on ID is `teacher-video-downloader@local.invalid`.

The installer works per user and does not need sudo. It stops if it finds an existing companion or Firefox host manifest. Do not replace an existing setup until its queue, browser registrations, and active downloads have been checked.

## Download the current video

On a supported page, start the video, open LessonShelf, and choose **Download video**. If several players are present, select the intended video. The companion attempts to identify a matching stream and otherwise tries the page link. A page can be unsupported even when it plays in the browser. Review the result before class; protected media is not supported.

## 3. Output location and first connection

Default: `~/Downloads/youtube-downloads`. For a persistent different location, add `--output-dir '/Volumes/Teaching/Video'` to the install command. The destination must be writable. APFS/HFS+ local storage is recommended; atomic publication uses hard links and fails safely on a filesystem that does not support them (for example some network/removable filesystems). Output directories with untrusted symlinks should not be used.

`YTDL_OUTPUT_DIR=/path python3 companion/host.py` also overrides output for a manually launched host. A browser launched from the Dock does not normally inherit Terminal environment variables; use the installer option instead. Native host launcher adds the standard Homebrew paths and pins the installing Python executable. If Python is removed/upgraded to a new path, reinstall the companion.

Open the extension → **Help & setup** → **Check connection** or **Check local tools**. If missing companion:
- Confirm extension ID and native-manifest allowlist match.
- Confirm Python still exists at its installed absolute path.
- Confirm the app directory and host manifest belong to your user.
- Reload extension after reinstalling. Do not grant arbitrary all-site permissions to fix a host connection.

## 4. Updates, removal, and deliberate cleanup

Pause active jobs first. Run:

```sh
python3 scripts/install-macos.py --uninstall
```

This removes only this app copy and matching host manifests. It does **not** delete downloads or private queue/partial files. Remove the browser extension yourself. After confirming nothing is running and no recovery is needed, you may manually delete `~/Library/Application Support/Teacher Video Downloader` to erase local queue URLs and partials. No such cleanup has been performed for you. Pause/cancel alone is deliberately not delete.

Private queue history is limited to500 entries; status shows at most100 newest entries, further capped by message size. Archive the state directory with the worker stopped to start a fresh queue when needed. There is no automatic queue-history eviction.
