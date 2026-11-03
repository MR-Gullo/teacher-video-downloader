# Mac Firefox companion installer

## Decision and current status

The teacher flow is a Developer ID signed, notarized app containing an offline payload. The extension downloads its ZIP. The teacher extracts the ZIP, opens the app, approves the normal macOS prompt, clicks Install, then returns to Firefox and chooses Connect. No Terminal, Homebrew or dependency downloads are part of installation. A downloaded `.command` exposes Terminal and execution-permission problems. A signed `.pkg` remains an option for school IT, but this per-user app needs no sudo or administrator password.

Mozilla assigns native-app installation to the operating system. A host manifest must exist before native messaging can start it. Both Firefox and Chrome restrict `downloads.open` to a user action, so download completion cannot silently launch the installer. [Mozilla native messaging](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging), [Firefox downloads.open](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/downloads/open), [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).

Real Apple Silicon and Intel FFmpeg builds and real offline tool payloads are staged locally. The Windows packaging route is documented in [WINDOWS-INSTALLER.md](WINDOWS-INSTALLER.md). These are review candidates. No teacher installer has been published. The current inventory contains local and Apple Development identities, but no Developer ID Application identity. The latter is required for this distribution. No private key, account, MFA or notarization credential was accessed.

## Shared runtime contract

A Mac payload contains `runtime/bin/python3`, `companion/*.py`, `tools/yt-dlp`, `tools/ffmpeg`, `tools/ffprobe`, `tools/N_m3u8DL-RE`, `tools/deno`, `installer/install_payload.py`, license notices and provenance. `payload.json` uses schema 2, target `macos-arm64` or `macos-x64`, semantic version, one exact Firefox ID and SHA-256 for every payload file. All files must be listed. Symbolic links are rejected; the assembler dereferences the verified Python runtime's internal links.

The host is `org.teacher.video_downloader`. Installs retain the sealed `LessonShelf Companion.app` inside `~/Library/Application Support/Teacher Video Downloader/app`. The Firefox manifest points to `app/LessonShelf Companion.app/Contents/MacOS/LessonShelfHost`. Its native launcher reads the install record outside the sealed bundle, so installation changes no signed payload files. The launcher sets `TVD_STATE_DIR` to the parent state folder and `YTDL_OUTPUT_DIR` to the preserved output directory. Bundled tools come first on PATH; Homebrew is not needed. Bundled Python runs the presealed path-relative host bootstrap in isolated mode. Runtime files live under the companion app's `Contents/Resources/payload`; companion source and tools remain siblings there. Worker code must honor these environment variables and use `worker.lock` relative to the state directory. Mac uses `flock`; Windows uses a first-byte `msvcrt.locking` lock.

The installer refuses an active worker, unknown registration, unregistered app folder or interrupted installer lock. It stages and verifies a new payload before switching program files. An identical verified reinstall is a no-op. Upgrades retain the previous app and registration under `rollback/`. The queue, job partials, saved media and custom output location remain in place. A failed registration restores only the program and registration owned by that transaction. An interrupted process retains `.installer-lock` and recovery evidence for review; it does not silently remove uncertain files.

The selected Firefox ID is either `teacher-video-downloader@local.invalid` for the signed extension or `lessonshelf-preview@local.invalid` for preview testing. Registration grants only the selected ID. Chrome remains paused. Windows ARM64 is outside this candidate.

The runtime can inspect the sealed app's `Contents/Resources/payload/payload.json` and `PROVENANCE.json` for installed-file integrity and the exact pinned N release. It must identify the approved binary, then check compatibility for each video. The authentic unsigned 0.6.0-beta executable SHA-256 values are:

| Target | Binary SHA-256 |
| --- | --- |
| Mac arm64 | `c332b463aa42975c25217d56a51a2ea32fddfd86b4ae8338a8f7416b0bc196e7` |
| Mac Intel | `8d4ce04c28f0fa9e2aea9c53af2a5895882f353e12425c5c3fcafaa4370a216a` |
| Windows x64 | `35e7c16983f0315bba2a3f37dc392fdfa074be614c8effb642b78376b18ba272` |

Code signing changes Mac executable bytes. `PROVENANCE.json` retains `toolSourceSHA256` from verified upstream inputs. Recompute `payload.json` file hashes after signing, but preserve these source hashes. The runtime owner must account for the signed-file receipt when identifying the approved build.

The runtime recognizes these verified source binaries. For a signed Mac N executable, it verifies the code signature and compares the normalized Mach-O content against the pinned source build. It still checks required help options and each video. A receipt alone must not force an available status or skip per-video checks.

## Reproducible local build

All intermediates and candidates belong in `.scratch/mac-installer-20261103`. Build tools require Python 3.11+, Xcode Command Line Tools, CMake, Ninja, pkg-config and tar with zstd support. These are developer requirements only. Builders refuse existing output paths. Use a clean reviewed source commit and new versioned paths.

The build has two components. `build_companion.py --payload DIRECTORY --output COMPANION.app` builds the installed native host app. `build_installer.py --companion-app COMPANION.app --output INSTALLER.app` embeds that app under `Contents/Helpers`. The latter requires a valid stapled companion ticket by default. `--allow-unnotarized-test` creates a local test candidate that the signing script refuses to sign for distribution.

The credential-free preparation sequence is:

```sh
rtk proxy python3 scripts/macos/fetch_dependencies.py --cache .scratch/mac-installer-20261103/upstream
rtk proxy python3 scripts/macos/build_ffmpeg.py --architecture arm64 --cache .scratch/mac-installer-20261103/upstream --work .scratch/mac-installer-20261103/ffmpeg-arm64
rtk proxy python3 scripts/macos/prepare_payload.py --target macos-arm64 --version 0.3.1 --firefox-id teacher-video-downloader@local.invalid --cache .scratch/mac-installer-20261103/upstream --ffmpeg-build .scratch/mac-installer-20261103/ffmpeg-arm64 --output .scratch/mac-installer-20261103/payload-macos-arm64
rtk proxy python3 scripts/macos/build_companion.py --payload .scratch/mac-installer-20261103/payload-macos-arm64 --output '.scratch/mac-installer-20261103/LessonShelf Companion unsigned.app'
```

For Intel, build FFmpeg with architecture `x86_64`, assemble target `macos-x64` and use distinct output paths. Swift can cross-compile the Intel apps on Apple Silicon. The builders inspect every Mach-O object's architecture and do not run Intel code through Rosetta or claim Intel runtime validation.

`sign_installer.py` signs a copy only. It requires the full reviewed source commit and a clean-source build. It signs nested Mach-O objects before the companion app, refreshes payload hashes, preserves upstream tool provenance and verifies strict code signatures. When signing the outer installer, it verifies and preserves the embedded companion. Only the Deno executable receives `com.apple.security.cs.allow-jit`. The installer app, companion app and Python receive no entitlements. Library validation and hardened runtime remain enabled. `--adhoc-test` exercises this path with no credentials and always marks the result unsuitable for distribution.

Mac yt-dlp uses the official universal Python zipapp with a small launcher into bundled CPython. It avoids a second embedded Python runtime and PyInstaller extraction. Windows keeps the official standalone executable.

The dependency lock pins CPython 3.13.18 from the official Astral Python Build Standalone release 20261026, yt-dlp 2026.10.26 and N_m3u8DL-RE 0.6.0-beta. Astral's runtime is a maintained relocatable CPython build, not a Python Software Foundation installer. Its full distribution supplies transitive license notices and licensing metadata. All archive hashes match upstream release metadata. Mac FFmpeg 9.0.2 is built with pinned upstream x264 and AOM 3.14.1 sources. Its detached signature verified against the fingerprint published on ffmpeg.org. The bundle includes the source archives, build commands and applicable notices. [Python Build Standalone](https://github.com/astral-sh/python-build-standalone), [FFmpeg downloads and verification](https://ffmpeg.org/download.html), [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases), [N releases](https://github.com/nilaoda/N_m3u8DL-RE/releases).

The self-contained N binaries for all three targets embed .NET 10.0.9. `scripts/macos/licenses/n-runtime` retains that runtime's MIT license and third-party notices, plus System.CommandLine and Spectre.Console/Ansi notices. Its provenance records the official NuGet package hashes and source commits. The assembler copies these notices into each payload.

Intel CI found that Google's generated Git archive changes compressed bytes between requests, although all 1,445 source files were identical. The lock now uses the static `libaom-3.14.1.tar.gz` release archive linked by AOMedia. Its SHA-256 is `44bf90dbd23e734d50e70a8c41c285193922938bd0d3bc2ee56764d181d55ef5`. A fresh fetch passes the hash check, and every source file matches the previous archive. Earlier source builds remain retained as evidence. [AOMedia release and archive](https://aomedia.org/blog%20posts/AOMedia-Announces-Availability-of-Libaom-v3_14/).

The replacement archive also completes a fresh Apple Silicon FFmpeg build. The sealed companion built at clean source `a4e2c0e` passes the full bundled-tool, native-doctor, AV1-to-H.264/AAC and decode check. Evidence is `.scratch/mac-installer-20261103/a4e2c0e/sealed-arm64-check.json`. The earlier `af352d8` outer native installer also passes isolated installation, idempotent reinstall and unchanged-seal checks in `af352d8/outer-native-check.json`. Both generations remain test candidates with ad hoc signatures. Intel CI requires another run with the archive repair.

## Verification and release boundary

```sh
rtk proxy python3 -m unittest discover -s tests -p test_macos_installer.py -v
rtk proxy python3 scripts/macos/verify_payload.py --companion-app 'PATH/TO/SEALED-COMPANION.app' --work .scratch/mac-installer-20261103/sealed-check --report .scratch/mac-installer-20261103/sealed-check.json
```

All 23 focused tests pass on this Apple Silicon Mac. They include byte-for-byte sealed-bundle preservation after installation and native launch, tamper refusal, legacy upgrade preservation, strict inner/outer code-signature checks and refusal to submit an ad hoc app for notarization. Windows registry projection tests prove portable transaction logic only. The real Apple Silicon sealed-bundle check at source `af352d8` passes with bundled Python and all four tools. It stages installation, checks the native doctor, creates AV1/AAC synthetic media, converts it to H.264/AAC MP4 and decodes the result. The installed app remains byte-for-byte unchanged. Evidence is retained at `.scratch/mac-installer-20261103/af352d8/sealed-arm64-check.json`. A new check is required for each final source snapshot. No OS security setting or quarantine attribute is changed.

The manual `.github/workflows/macos-intel-qa.yml` workflow runs the equivalent native Intel acceptance on the standard `macos-15-intel` runner. It builds the pinned codec sources, uses ad hoc signatures only and runs the native outer installer against an explicit scratch account. It retains synthetic reports and build diagnostics for seven days. It has no signing secrets, publication step or GUI test. Parent review owns dispatch and result review.

Apple explicitly requires two notarization passes for a custom installer. First sign and notarize the companion app and staple its ticket. Then embed that exact app in the outer installer, sign the outer installer, notarize it, staple its ticket and create the final ZIP. Standalone binaries cannot hold stapled tickets, which is why the installed payload is now a sealed app. [Apple workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow).

`notarize_app.py` is read-only by default. It reports whether a reviewed app has Developer ID signing, a secure timestamp and hardened runtime. Its explicit `--submit --keychain-profile NAME` mode uploads only after those checks. It accepts a profile handle, never a password or key file. It retains the exact submission ZIP, request status and any rejection log, staples accepted app copies, verifies them and writes the final ZIP/hash. It never publishes an artifact. A successful development-Mac assessment does not replace a clean-Mac browser-download test.

## What the account holder must do

1. Confirm an active Apple Developer Program membership. In Xcode, open Settings, then Accounts, sign in and choose the paid developer team rather than a Personal Team. Leave sign-in and MFA to the account holder.
2. Open Manage Certificates, click + and create **Developer ID Application**. Apple Development, Mac Distribution and Developer ID Installer are different certificate types. For the account website route, the Account Holder opens Certificates, Identifiers & Profiles, adds Developer ID Application, creates a certificate signing request on this Mac, uploads the request, downloads the certificate and double-clicks it to install. The certificate must have its matching private key under Keychain Access > My Certificates. Do not export or send the key. [Apple certificate instructions](https://developer.apple.com/help/account/certificates/create-developer-id-certificates).
3. At [account.apple.com](https://account.apple.com), open Sign-In and Security, then App-Specific Passwords, and create a password for notarization. Two-factor authentication must be enabled. In the account holder's own Terminal window, run the following command. Supply the Apple ID, Team ID and app-specific password only to its interactive prompts. The tool validates and stores the credentials in Keychain. [Apple password instructions](https://support.apple.com/en-us/102654).

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

Both signing calls take `--identity 'Developer ID Application: ...'` and `--reviewed-source FULL_COMMIT`. Both notarization calls take `--keychain-profile LessonShelf-notary --submit` and its own reviewed component commit. The outer installer records the embedded companion source commit separately, so later installer changes never require altering a previously notarized companion. All commands take new `--output` paths. Account credentials stay in the approved signing environment. No signing credential or notarization submission was used for the preparation tests.

Before release, complete native Intel execution, real Windows Firefox acceptance, the actual Mac installer UI task, clean-Mac browser-download and offline launch checks, and the Windows source/license and Authenticode review. The staged Mac GUI check is blocked because Computer Use reports the Mac is locked and automatic unlock is paused. It must wait for a human unlock. Parent review owns publication and extension download links. No installed companion, live registration, queue, download, browser UI or public setup page was changed by this installer work. Earlier candidates and staging evidence remain retained in the task scratch folder while release work is unfinished.

## Bundled JavaScript runtime in 0.3.1

YouTube extraction requires an external JavaScript runtime, even though the official yt-dlp zipapp and Windows executable already include EJS. The offline payload now requires official Deno 2.9.8 at `tools/deno`, or `tools/deno.exe` on Windows. Lock keys are `deno-macos-arm64`, `deno-macos-x64`, `deno-windows-x64` and common `deno-source`. Binary and source archive hashes match official GitHub release metadata. Both Mac binaries declare minimum macOS 12.0, matching the apps. [yt-dlp EJS requirements](https://github.com/yt-dlp/yt-dlp/wiki/EJS), [Deno release](https://github.com/denoland/deno/releases/tag/v2.9.8).

The original Deno signature has five entitlement exceptions. Re-signing without an entitlement crashes during actual JavaScript execution. A hardened ad hoc copy with only `com.apple.security.cs.allow-jit` runs the restricted offline script. The signer grants that single entitlement only to `Contents/Resources/payload/tools/deno`, verifies its exact dictionary and records it in `codeObjectEntitlements`. It does not preserve the upstream exceptions for unsigned executable memory, executable-page protection, dyld environment variables or library validation.

The payload verifier checks the pinned Deno version and executes a local script through the installed signed binary. That script exercises dynamic functions and reports denied read, write, network, environment, subprocess, FFI and system permissions. Remote modules, npm resolution, config discovery and update checks are disabled. Native doctor, media conversion and unchanged-seal requirements still apply. The 24 focused installer tests include refusal of a payload that omits Deno even after updating its file manifest.

License material currently covered is Deno MIT, Node type declarations, Undici type declarations and WebGPU notices from the hash-verified official release source archive. The full source and Cargo.lock are preserved under `sources/deno-2.9.8-source.tar.gz`. Cargo.lock has 1,048 registry entries across runtime, build, development and platform targets; it is not a complete binary notice bundle or SBOM. Rusty V8 MIT and V8 BSD notices are also retained under `licenses/deno/v8`, with provenance from Deno Cargo.lock and the Rusty V8 source gitlink. The published v8 crate excludes LICENSE files, so these texts were fetched from the exact upstream source references. V8 externally maintained libraries and remaining third-party copyright/license coverage still require review, recorded as `denoThirdPartyNoticesReviewed: false`. A bounded follow-up can use the maintained [cargo-about](https://github.com/EmbarkStudios/cargo-about) tool against the exact source/dependency graph, then review platform-specific dependencies and V8 bundled components. No Rust toolchain or global license tool was installed for this preparation.

Both native launchers force `DENO_NO_UPDATE_CHECK=1` for the host and worker descendants. The verifier sets it before every bundled-tool check. The candidate does not need a global Deno installation.
