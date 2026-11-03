# Mac Firefox companion installer

## Decision and current status

The teacher flow is a Developer ID signed, notarized app containing an offline payload. The extension downloads its ZIP. The teacher extracts the ZIP, opens the app, approves the normal macOS prompt, clicks Install, then returns to Firefox and chooses Connect. No Terminal, Homebrew or dependency downloads are part of installation. A downloaded `.command` exposes Terminal and execution-permission problems. A signed `.pkg` remains an option for school IT, but this per-user app needs no sudo or administrator password.

Mozilla assigns native-app installation to the operating system. A host manifest must exist before native messaging can start it. Both Firefox and Chrome restrict `downloads.open` to a user action, so download completion cannot silently launch the installer. [Mozilla native messaging](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging), [Firefox downloads.open](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/downloads/open), [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).

Real Apple Silicon and Intel FFmpeg builds and real offline tool payloads are staged locally. The Windows packaging route is documented in [WINDOWS-INSTALLER.md](WINDOWS-INSTALLER.md). These are review candidates. No teacher installer has been published. The current inventory contains local and Apple Development identities, but no Developer ID Application identity. The latter is required for this distribution. No private key, account, MFA or notarization credential was accessed.

## Shared runtime contract

A Mac payload contains `runtime/bin/python3`, `companion/*.py`, `tools/yt-dlp`, `tools/ffmpeg`, `tools/ffprobe`, `tools/N_m3u8DL-RE`, `installer/install_payload.py`, license notices and provenance. `payload.json` uses schema 2, target `macos-arm64` or `macos-x64`, semantic version, one exact Firefox ID and SHA-256 for every payload file. All files must be listed. Symbolic links are rejected; the assembler dereferences the verified Python runtime's internal links.

The host is `org.teacher.video_downloader`. Installs retain the sealed `LessonShelf Companion.app` inside `~/Library/Application Support/Teacher Video Downloader/app`. The Firefox manifest points to `app/LessonShelf Companion.app/Contents/MacOS/LessonShelfHost`. Its native launcher reads the install record outside the sealed bundle, so installation changes no signed payload files. The launcher sets `TVD_STATE_DIR` to the parent state folder and `YTDL_OUTPUT_DIR` to the preserved output directory. Bundled tools come first on PATH; Homebrew is not needed. Bundled Python runs the presealed path-relative host bootstrap in isolated mode. Runtime files live under the companion app's `Contents/Resources/payload`; companion source and tools remain siblings there. Worker code must honor these environment variables and use `worker.lock` relative to the state directory. Mac uses `flock`; Windows uses a first-byte `msvcrt.locking` lock.

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

All intermediates and candidates belong in `.scratch/mac-installer-20261103`. Build tools require Python 3.11+, Xcode Command Line Tools, CMake, Ninja, pkg-config and tar with zstd support. These are developer requirements only. Builders refuse existing output paths. Use a clean reviewed source commit and new versioned paths.

The build has two components. `build_companion.py --payload DIRECTORY --output COMPANION.app` builds the installed native host app. `build_installer.py --companion-app COMPANION.app --output INSTALLER.app` embeds that app under `Contents/Helpers`. The latter requires a valid stapled companion ticket by default. `--allow-unnotarized-test` creates a local test candidate that the signing script refuses to sign for distribution.

The credential-free preparation sequence is:

```sh
rtk proxy python3 scripts/macos/fetch_dependencies.py --cache .scratch/mac-installer-20261103/upstream
rtk proxy python3 scripts/macos/build_ffmpeg.py --architecture arm64 --cache .scratch/mac-installer-20261103/upstream --work .scratch/mac-installer-20261103/ffmpeg-arm64
rtk proxy python3 scripts/macos/prepare_payload.py --target macos-arm64 --version 0.3.0 --firefox-id teacher-video-downloader@local.invalid --cache .scratch/mac-installer-20261103/upstream --ffmpeg-build .scratch/mac-installer-20261103/ffmpeg-arm64 --output .scratch/mac-installer-20261103/payload-macos-arm64
rtk proxy python3 scripts/macos/build_companion.py --payload .scratch/mac-installer-20261103/payload-macos-arm64 --output '.scratch/mac-installer-20261103/LessonShelf Companion unsigned.app'
```

For Intel, build FFmpeg with architecture `x86_64`, assemble target `macos-x64` and use distinct output paths. Swift can cross-compile the Intel apps on Apple Silicon. The builders inspect every Mach-O object's architecture and do not run Intel code through Rosetta or claim Intel runtime validation.

`sign_installer.py` signs a copy only. It requires the full reviewed source commit and a clean-source build. It signs nested Mach-O objects before the companion app, refreshes payload hashes, preserves upstream tool provenance and verifies strict code signatures. When signing the outer installer, it verifies and preserves the embedded companion. No library-validation exception or other entitlement is added. `--adhoc-test` exercises this path with no credentials and always marks the result unsuitable for distribution.

Mac yt-dlp uses the official universal Python zipapp with a small launcher into bundled CPython. It avoids a second embedded Python runtime and PyInstaller extraction. Windows keeps the official standalone executable.

The dependency lock pins CPython 3.13.18 from the official Astral Python Build Standalone release 20261026, yt-dlp 2026.10.26 and N_m3u8DL-RE 0.6.0-beta. Astral's runtime is a maintained relocatable CPython build, not a Python Software Foundation installer. Its full distribution supplies transitive license notices and licensing metadata. All archive hashes match upstream release metadata. Mac FFmpeg 9.0.2 is built with pinned upstream x264 and AOM 3.14.1 sources. Its detached signature verified against the fingerprint published on ffmpeg.org. The bundle includes the source archives, build commands and applicable notices. [Python Build Standalone](https://github.com/astral-sh/python-build-standalone), [FFmpeg downloads and verification](https://ffmpeg.org/download.html), [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases), [N releases](https://github.com/nilaoda/N_m3u8DL-RE/releases).

## Verification and release boundary

```sh
rtk proxy python3 -m unittest discover -s tests -p test_macos_installer.py -v
rtk proxy python3 scripts/macos/verify_payload.py --companion-app 'PATH/TO/SEALED-COMPANION.app' --work .scratch/mac-installer-20261103/sealed-check --report .scratch/mac-installer-20261103/sealed-check.json
```

All 23 focused tests pass on this Apple Silicon Mac. They include byte-for-byte sealed-bundle preservation after installation and native launch, tamper refusal, legacy upgrade preservation, strict inner/outer code-signature checks and refusal to submit an ad hoc app for notarization. Windows registry projection tests prove portable transaction logic only. The real Apple Silicon payload checker runs bundled Python and all four tools, stages installation, checks the native doctor, creates AV1/AAC synthetic media, converts it to H.264/AAC MP4 and decodes the result. The current unsigned-payload checks pass. A new real sealed-bundle check is required for each final source snapshot. No OS security setting or quarantine attribute is changed.

Apple explicitly requires two notarization passes for a custom installer. First sign and notarize the companion app and staple its ticket. Then embed that exact app in the outer installer, sign the outer installer, notarize it, staple its ticket and create the final ZIP. Standalone binaries cannot hold stapled tickets, which is why the installed payload is now a sealed app. [Apple workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow).

`notarize_app.py` is read-only by default. It reports whether a reviewed app has Developer ID signing, a secure timestamp and hardened runtime. Its explicit `--submit --keychain-profile NAME` mode uploads only after those checks. It accepts a profile handle, never a password or key file. It retains the exact submission ZIP, request status and any rejection log, staples accepted app copies, verifies them and writes the final ZIP/hash. It never publishes an artifact. A successful development-Mac assessment does not replace a clean-Mac browser-download test.

## What the account holder must do

1. Confirm an active Apple Developer Program membership. In Xcode, open Settings, then Accounts, sign in and choose the paid developer team rather than a Personal Team. Leave sign-in and MFA to the account holder.
2. Open Manage Certificates, click + and create **Developer ID Application**. Apple Development, Mac Distribution and Developer ID Installer are different certificate types. For the account website route, the Account Holder opens Certificates, Identifiers & Profiles, adds Developer ID Application, creates a certificate signing request on this Mac, uploads the request, downloads the certificate and double-clicks it to install. The certificate must have its matching private key under Keychain Access > My Certificates. Do not export or send the key. [Apple certificate instructions](https://developer.apple.com/help/account/certificates/create-developer-id-certificates).
3. In the Apple Account security settings, create an app-specific password for notarization. In the account holder's own Terminal window, run the following command. Supply the Apple ID, Team ID and app-specific password only to its interactive prompts. The tool validates and stores the credentials in Keychain.

```sh
xcrun notarytool store-credentials "LessonShelf-notary"
```

4. Tell the installer coordinator that the Developer ID Application identity is installed and the `LessonShelf-notary` profile is saved. Its certificate identity name and Team ID are public identifiers that can be shared. Do not send a password, private key, `.p12` file or API key in chat.

After parent review, the remaining automated sequence for each architecture is:

```text
sign_installer.py       unsigned companion -> Developer ID signed companion
notarize_app.py         signed companion -> accepted, stapled companion
build_installer.py      stapled companion -> unsigned outer installer
sign_installer.py       outer installer -> Developer ID signed outer installer
notarize_app.py         outer installer -> accepted, stapled installer and final ZIP
```

Credential-enabled signing and submission also require `--reviewed-bundle-sha256` matching the exact parent-reviewed app fingerprint. The signing sidecar records the output fingerprint for the notarization review.

Both signing calls take `--identity 'Developer ID Application: ...'` and `--reviewed-source FULL_COMMIT`. Both notarization calls take `--keychain-profile LessonShelf-notary --submit` and the same reviewed commit. All commands take new `--output` paths. Account credentials stay in the approved signing environment. No signing credential or notarization submission was used for the preparation tests.

Before release, complete native Intel execution, real Windows Firefox acceptance, the actual Mac installer UI task, clean-Mac browser-download and offline launch checks, and the Windows source/license and Authenticode review. Parent review owns publication and extension download links. No installed companion, live registration, queue, download, browser UI or public setup page was changed by this installer work. Earlier candidates and staging evidence remain retained in the task scratch folder while release work is unfinished.
