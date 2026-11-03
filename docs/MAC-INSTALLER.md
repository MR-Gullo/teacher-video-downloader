# Mac Firefox companion installer

## Decision and current status

The teacher flow is a Developer ID signed, notarized app containing an offline payload. The extension downloads its ZIP. The teacher extracts the ZIP, opens the app, approves the normal macOS prompt, clicks Install, then returns to Firefox and chooses Connect. No Terminal, Homebrew or dependency downloads are part of installation. A downloaded `.command` exposes Terminal and execution-permission problems. A signed `.pkg` remains an option for school IT, but this per-user app needs no sudo or administrator password.

Mozilla assigns native-app installation to the operating system. A host manifest must exist before native messaging can start it. Both Firefox and Chrome restrict `downloads.open` to a user action, so download completion cannot silently launch the installer. [Mozilla native messaging](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging), [Firefox downloads.open](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/downloads/open), [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).

Real Apple Silicon and Intel FFmpeg builds and real offline tool payloads are staged locally. The Windows packaging route is documented in [WINDOWS-INSTALLER.md](WINDOWS-INSTALLER.md). These are review candidates. No teacher installer has been published. The local signing inventory found zero valid code-signing identities on 2026-11-03. No private key, account, MFA or notarization credential was accessed.

## Shared runtime contract

A Mac payload contains `runtime/bin/python3`, `companion/*.py`, `tools/yt-dlp`, `tools/ffmpeg`, `tools/ffprobe`, `tools/N_m3u8DL-RE`, `installer/install_payload.py`, license notices and provenance. `payload.json` uses schema 2, target `macos-arm64` or `macos-x64`, semantic version, one exact Firefox ID and SHA-256 for every payload file. All files must be listed. Symbolic links are rejected; the assembler dereferences the verified Python runtime's internal links.

The host is `org.teacher.video_downloader`. Installs use `~/Library/Application Support/Teacher Video Downloader/app`. The Firefox manifest points to `app/launch-host`. The launcher sets `TVD_STATE_DIR` to the parent state folder and `YTDL_OUTPUT_DIR` to the preserved output directory. Bundled tools come first on PATH; Homebrew is not needed. Bundled Python runs the host with an explicit import directory and isolated mode. Worker code must honor these environment variables and use `worker.lock` relative to the state directory. Mac uses `flock`; Windows uses a first-byte `msvcrt.locking` lock.

The installer refuses an active worker, unknown registration, unregistered app folder or interrupted installer lock. It stages and verifies a new payload before switching program files. An identical verified reinstall is a no-op. Upgrades retain the previous app and registration under `rollback/`. The queue, job partials, saved media and custom output location remain in place. A failed registration restores only the program and registration owned by that transaction. An interrupted process retains `.installer-lock` and recovery evidence for review; it does not silently remove uncertain files.

The selected Firefox ID is either `teacher-video-downloader@local.invalid` for the signed extension or `lessonshelf-preview@local.invalid` for preview testing. Registration grants only the selected ID. Chrome remains paused. Windows ARM64 is outside this candidate.

The runtime can inspect `app/payload.json` and `app/PROVENANCE.json` for installed-file integrity and the exact pinned N release. It must compare the executable against the approved binary hash, then check compatibility for each video. The authentic 0.6.0-beta executable SHA-256 values are:

| Target | Binary SHA-256 |
| --- | --- |
| Mac arm64 | `c332b463aa42975c25217d56a51a2ea32fddfd86b4ae8338a8f7416b0bc196e7` |
| Mac Intel | `8d4ce04c28f0fa9e2aea9c53af2a5895882f353e12425c5c3fcafaa4370a216a` |
| Windows x64 | `35e7c16983f0315bba2a3f37dc392fdfa074be614c8effb642b78376b18ba272` |

Code signing changes Mac executable bytes. `PROVENANCE.json` retains `toolSourceSHA256` from verified upstream inputs. Recompute `payload.json` file hashes after signing, but preserve these source hashes. The runtime owner must account for the signed-file receipt when identifying the approved build.

The runtime recognizes these verified source binaries and still checks required help options and each video. The signing path needs the signed-file receipt integration described above. A receipt alone must not force an available status or skip per-video checks.

## Reproducible local build

All intermediates and candidates belong in `.scratch/mac-installer-20261103`. Build tools require Python 3.11+, Xcode Command Line Tools, CMake, Ninja, pkg-config and a tar implementation with zstd support. These are developer requirements only. Builders refuse existing output paths.

```sh
rtk proxy python3 scripts/macos/fetch_dependencies.py --cache .scratch/mac-installer-20261103/upstream
rtk proxy python3 scripts/macos/build_ffmpeg.py --architecture arm64 --cache .scratch/mac-installer-20261103/upstream --work .scratch/mac-installer-20261103/ffmpeg-arm64
rtk proxy python3 scripts/macos/prepare_payload.py --target macos-arm64 --version 0.3.0 --firefox-id teacher-video-downloader@local.invalid --cache .scratch/mac-installer-20261103/upstream --ffmpeg-build .scratch/mac-installer-20261103/ffmpeg-arm64 --output .scratch/mac-installer-20261103/payload-macos-arm64
rtk proxy python3 scripts/macos/build_installer.py --payload .scratch/mac-installer-20261103/payload-macos-arm64 --output .scratch/mac-installer-20261103/LessonShelf-0.3.0-macos-arm64.app
```

For Intel, build FFmpeg with architecture `x86_64`, assemble target `macos-x64` and use distinct output paths. Swift can cross-compile the Intel app on Apple Silicon, but the builder does not run Intel code through Rosetta or claim Intel runtime validation. The builder inspects every Mach-O object's architecture.

Mac yt-dlp uses the official universal Python zipapp with a small launcher into bundled CPython. It avoids a second embedded Python runtime and PyInstaller extraction. Windows keeps the official standalone executable.

The dependency lock pins CPython 3.13.18 from the official Astral Python Build Standalone release 20261026, yt-dlp 2026.10.26 and N_m3u8DL-RE 0.6.0-beta. Astral's runtime is a maintained relocatable CPython build, not a Python Software Foundation installer. Its full distribution supplies transitive license notices and licensing metadata. All archive hashes match upstream release metadata. Mac FFmpeg 9.0.2 is built with pinned upstream x264 and AOM 3.14.1 sources. Its detached signature verified against the fingerprint published on ffmpeg.org. The bundle includes the source archives, build commands and applicable notices. [Python Build Standalone](https://github.com/astral-sh/python-build-standalone), [FFmpeg downloads and verification](https://ffmpeg.org/download.html), [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases), [N releases](https://github.com/nilaoda/N_m3u8DL-RE/releases).

## Verification and release boundary

```sh
rtk proxy python3 -m unittest discover -s tests -p test_macos_installer.py -v
rtk proxy python3 scripts/macos/verify_payload.py --payload .scratch/mac-installer-20261103/payload-macos-arm64 --work .scratch/mac-installer-20261103/real-arm64-check --report .scratch/mac-installer-20261103/real-arm64-check.json
```

The 19 focused tests passed on this Apple Silicon Mac. They cover staging, hash and platform rejection, links, existing-install preservation, active locks, idempotent reinstall, retained upgrade evidence, rollback, custom output preservation, native framing and Mac app packaging. The Windows registry projection test proves portable transaction logic only.

The real payload checker runs bundled Python and all four tools, stages installation, checks the native doctor, creates AV1/AAC synthetic media, converts it to H.264/AAC MP4 and decodes the result. It records failures as failures. The initial sandbox run could not start yt-dlp's PyInstaller semaphore. The named staging checker received explicit tool approval, and the real tools then ran successfully. No OS security setting or quarantine attribute changed. The current Apple Silicon zipapp payload passes the complete checker, including all four doctor availability checks, native framing, AV1-to-H.264/AAC conversion and full decode. The earlier failure report remains retained as prior staging evidence.

Before release, rebuild from the reviewed integrated source commit, complete native Apple Silicon, Intel and Windows tests, and check the actual installer UI and browser download flow. The app window and normal Gatekeeper path have not been verified. Windows corresponding-source review and Authenticode checks remain explicit gates.

The exact Mac account step is for the Apple Developer account holder to obtain a Developer ID Application signing identity with its private key in the approved signing environment. Sign nested executable code and libraries first, recompute payload hashes, then sign the outer app with hardened runtime settings. The account holder submits the reviewed archive through Xcode or `notarytool`, checks acceptance, staples and validates the app, then archives the stapled app. A ZIP cannot be stapled directly. Keep quarantine enabled and test an actual browser download on clean Macs. [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution), [Apple workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow).

Parent review owns publication and extension download links. No installed companion, live registration, queue, download, browser UI or public setup page was changed by this installer work. The earlier fixture prototype remains retained in scratch as prior review evidence; current candidates contain real dependencies. Source build trees, verified caches and test evidence remain staged while release work is unfinished.
