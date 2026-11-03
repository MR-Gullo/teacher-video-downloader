# Mac companion installer

## Decision and status

Use a Developer ID signed, notarized installer app, distributed as a ZIP containing the app. Bundle Python, yt-dlp, FFmpeg and ffprobe so teachers need no Terminal, Homebrew or dependency downloads. Install for the current account without sudo. This is the proposed distribution path, not an available teacher download.

The local prototype implements installation and packaging. It uses a developer Python fixture and fake media tools. It refuses normal installation from its app window. Only an explicit staging destination works. It is not signed for distribution or notarized. No dependency versions or release download URLs have been approved or published.

| Format | Teacher experience | Decision |
| --- | --- | --- |
| Downloaded `.command` | Opens Terminal if execution permissions and macOS policy allow it. Can require executable permissions, security troubleshooting and dependency setup. | Unsuitable for the intended audience. |
| Signed, notarized `.app` in ZIP | Extract, open, approve the normal macOS prompt, click Install, return to extension. Can install per user. | Recommended. |
| Signed, notarized `.pkg` | Familiar Installer wizard. Useful for managed deployment. Package scripts and per-user registration need a separate design. | Consider for school IT later. |

The browser can initiate a download. It cannot silently install a native host. Mozilla explicitly assigns native-app installation to the operating system. Chrome requires a host manifest before native messaging works. Both browsers restrict `downloads.open` to a user action. An asynchronous download completion does not preserve that action. Prefer the browser's Downloads interface to open the downloaded ZIP. [Mozilla native messaging](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging), [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging), [Chrome downloads.open](https://developer.chrome.com/docs/extensions/reference/api/downloads#method-open), [Firefox downloads.open](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/downloads/open).

Apple requires the appropriate Developer ID signing and notarization for the normal Gatekeeper distribution path. An app uses Developer ID Application. A signed package uses Developer ID Installer. A ZIP cannot carry a stapled ticket directly. Staple the app and archive it again after acceptance. [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution), [Apple workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow), [Installer certificate](https://help.apple.com/xcode/mac/current/en.lproj/deve51ce7c3d.html).

## Intended teacher flow

1. Click Get Mac companion. The eventual release page offers Apple Silicon and Intel downloads with clear labels. Do not guess architecture from a reduced browser user agent.
2. Open the downloaded ZIP, then open LessonShelf Installer. Approve the normal macOS prompt.
3. Click Install. The app verifies its bundled files and installs into the teacher's account.
4. Read the success message, return to the Firefox extension and choose Connect.

The prototype covers the installation backend. Browser download, quarantine handling, the app window, keyboard access, progress feedback, real dependency relocation and Connect in Firefox have not been tested. A production app needs responsive progress while it checks and copies the runtime. An existing installation stops this fresh-install prototype. Updating an active companion needs a separate job-preserving workflow.

## Local review

Run from the repository with Python 3.10+ and Xcode Command Line Tools. These are developer requirements only.

```sh
rtk proxy python3 -m unittest discover -s tests -p test_macos_installer.py -v
rtk proxy python3 scripts/macos/build_installer.py --demo --output '.scratch/mac-installer-20261103/LessonShelf Installer Prototype.app'
```

The builder refuses an existing output. The demo fixture uses the Python interpreter that builds it and contains no functioning media tools. Keep it local. To exercise installation, pass the app's bundled `Contents/Resources/payload` to `Contents/MacOS/LessonShelfInstaller` with `--payload DIRECTORY --stage-root EMPTY_TEST_DIRECTORY`. Add `--dry-run` for verification without destination writes. Never use a real teacher account as the staging root. Tests allocate disposable destinations and explicit state/output directories. They do not use the installed companion.

On 2026-11-03, all 15 focused tests passed on this Apple Silicon Mac. They covered the app build, staging handshake, dry run, architecture and hash rejection, missing files, links, existing artifacts, interrupted locks, registration rollback and retry. This is local backend evidence only.

The app accepts a hash-locked offline payload through `--payload DIRECTORY` instead of `--demo`. Its `payload.json` must have schema `1`, architecture `arm64` or `x86_64`, `prototype: true`, one exact `firefoxID`, and a `files` object mapping each relative file path to its SHA-256. The manifest excludes itself. Every file must be listed. Symbolic links are rejected, so supply a dereferenced runtime. Required files are:

```text
runtime/bin/python3
companion/host.py
companion/worker.py
tools/yt-dlp
tools/ffmpeg
tools/ffprobe
LICENSES.txt
```

Include the complete companion source and all Python runtime libraries and standard modules. Build natively on the matching Mac architecture. The builder checks the architecture of every Mach-O file. The installer rechecks file hashes before and after staging. These checks detect corruption, not publisher identity. Code signing must supply authenticity in a real release. `BUILD.json` records local source provenance and artifact hashes.

Installation creates `Library/Application Support/Teacher Video Downloader/app` and the Firefox native-host manifest beneath the supplied account root. The launcher uses the bundled interpreter, isolates the host import path and puts bundled tools first. No Homebrew paths are added. It preserves the existing queue, partial files and downloads. It refuses an existing app, registration or installer lock. A failed registration rolls back only the new app. Empty parent folders can remain. An interrupted process can leave `.installer-lock` and possibly a new app for manual review; it never silently repairs or overwrites that state.

The browser registration allows either `lessonshelf-preview@local.invalid` or `teacher-video-downloader@local.invalid`, selected at build time. It never grants both automatically. Chrome registration is deliberately absent while Chrome release is paused. Windows is outside this task.

## Work before teacher distribution

1. Select and pin a complete relocatable CPython runtime and official yt-dlp release separately for each architecture. Build FFmpeg and ffprobe from an official pinned FFmpeg source release if strict upstream provenance is required. FFmpeg's website delegates macOS binary builds to third parties. Record the exact version, upstream URL, publisher verification and SHA-256 for every input. Do not download dependencies on the teacher's Mac. [CPython releases](https://www.python.org/downloads/source/), [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases), [FFmpeg downloads](https://ffmpeg.org/download.html).
2. Audit relocation and dynamic-library paths on clean Apple Silicon and Intel Macs without developer Python or Homebrew. Include CPython and all transitive dependency notices. Include yt-dlp notices and FFmpeg build configuration, license and corresponding-source obligations for the selected build. The prototype's `LICENSES.txt` presence check does not perform that audit. Optional N_m3u8DL-RE is excluded from the initial bundle.
3. Have the Apple Developer account holder create or obtain Developer ID Application signing credentials through Apple's account tools. Keep the private key and notarization credentials in the approved human-controlled boundary. No credentials were accessed for this prototype.
4. Implement and review the production packaging route. Sign nested executable code and runtime libraries, then the app with the required hardened runtime settings. Recompute the payload hashes after nested signing and before sealing the outer app. Do not use a blanket signing operation as a substitute for reviewing nested code. The current builder intentionally rejects `prototype: false`.
5. The account holder submits the exact archive using Xcode or `notarytool`, checks acceptance, staples and validates the app ticket, then archives the stapled app. Validate the final artifact with Gatekeeper on clean Macs after an actual browser download, including an offline launch with the stapled ticket. Keep quarantine enabled. No Gatekeeper bypass is part of this workflow.
6. Test the complete teacher flow, real dependency checks, queue operation, cancellation, errors and installation recovery. Verify the stable Firefox extension ID. Existing-install updates remain separate.
7. Obtain separate release approval, publish versioned artifacts and checksums, then wire the extension button to that real release. The public MAC-SETUP page is older than this checkout and was not updated. Do not label the prototype as available to teachers.

There is no dependency downloader in the prototype. Missing or corrupt offline files stop installation before destination writes; retry means obtaining the complete artifact again. Tests cover these failures instead of simulating an unused network installer. No account actions, signing, publication, live registration, installed-companion changes or browser interaction occurred.
