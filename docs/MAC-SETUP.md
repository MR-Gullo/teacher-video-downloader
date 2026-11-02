# Mac setup — run these on your Mac only when ready

This is a source preview, not a signed store release. Review the files before running. The preview is not a signed store release. Keep the extracted folder in a stable location (for example `~/Applications/teacher-video-downloader`).

For direct MP4, WebM, MP3, M4A or WAV links, the extension can use the browser download manager without the companion. The steps below add support for page downloads, conversion and the local queue.

## 1. Dependencies

Use your already-installed trusted package manager. If Homebrew is already installed:

```sh
brew install python yt-dlp ffmpeg
# Helpful for current YouTube extractor JavaScript challenges:
brew install deno
# Optional only; not used by this preview's adapter:
brew install aria2
```

Do not run an unknown install script just because a webpage suggests it. Current yt-dlp YouTube support may need a supported JavaScript runtime and matching EJS components; consult its official EJS guide. Remote component downloads are deliberately disabled in our adapter. Package-manager builds may include the needed components; verify on your Mac rather than assuming.

For **N_m3u8DL-RE**, use the official project release page linked in ENGINE-NOTES. Choose the macOS build matching Apple silicon (`arm64`) or Intel (`x64`); inspect its publisher and any provided checksums/signatures. Extract the executable into a trusted directory such as `/usr/local/bin` or `/opt/homebrew/bin` with normal user-approved installation. No N binary is bundled here and no unverified binary was downloaded in the VM. Review macOS security prompts; this project does not tell you to disable Gatekeeper.

Confirm:

```sh
python3 --version
yt-dlp --version
ffmpeg -version
ffprobe -version
N_m3u8DL-RE --help
```

N must expose `--no-config`, `--disable-update-check`, `--write-meta-json` and the documented current stream-selection flags. Old releases may be rejected or fail; install a current official build. `python3 companion/cli.py --doctor` reports installed paths, not a guarantee of live-site support.

## 2. Build browser folders

In Terminal, `cd` into the extracted project:

```sh
python3 scripts/build.py
```

This writes `build/chrome/` and `build/firefox/` from the same source. The ZIP already contains these folders; rebuilding is optional.

### Chrome

1. Open `chrome://extensions` yourself, enable Developer mode.
2. Choose **Load unpacked**, select `build/chrome`.
3. Copy its32-letter extension ID. Keep this folder in place; moving it can change an unpacked ID.
4. Install the companion allowlist using that exact ID:

```sh
python3 scripts/install-macos.py --chrome-id YOUR_32_LETTER_ID
```

### Firefox

Open `about:debugging#/runtime/this-firefox` yourself, choose **Load Temporary Add-on**, select `build/firefox/manifest.json`.

```sh
python3 scripts/install-macos.py --firefox
```

For both browsers, use **one install command**, e.g.:

```sh
python3 scripts/install-macos.py --chrome-id YOUR_32_LETTER_ID --firefox
```

Temporary Firefox add-ons disappear after Firefox restarts. Reload the same manifest to reconnect to the durable queue. Persistent normal-release Firefox installation requires Mozilla signing, which has **not** been obtained. The fixed add-on ID is `teacher-video-downloader@local.invalid`.

The installer refuses an existing app or matching host manifest rather than silently replacing it. For an update or to add another browser: pause jobs, uninstall (below), then install with both desired flags. Installation is per-user only; no sudo, TCP service or LaunchAgent is created.

## 3. Output location and first connection

Default: `~/Downloads/youtube-downloads`. For a persistent different location, add `--output-dir '/Volumes/Teaching/Video'` to the install command. The destination must be writable. APFS/HFS+ local storage is recommended; atomic publication uses hard links and fails safely on a filesystem that does not support them (for example some network/removable filesystems). Output directories with untrusted symlinks should not be used.

`YTDL_OUTPUT_DIR=/path python3 companion/host.py` also overrides output for a manually launched host. A browser launched from the Dock does not normally inherit Terminal environment variables; use the installer option instead. Native host launcher adds the standard Homebrew paths and pins the installing Python executable. If Python is removed/upgraded to a new path, reinstall the companion.

Open the extension → **Reconnect**, **Dependency check**. If missing companion:
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
