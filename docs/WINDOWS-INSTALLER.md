# Windows Firefox companion installer

## Contract for the runtime and CI

The offline payload layout is `runtime/python.exe`, `companion/*.py`, `tools/yt-dlp.exe`, `tools/ffmpeg.exe`, `tools/ffprobe.exe`, `tools/N_m3u8DL-RE.exe`, `tools/deno.exe`, `installer/install_payload.py` and `installer/launch-host.exe`. Its `payload.json` uses schema 2, target `windows-x64`, semantic version, one exact Firefox ID and SHA-256 for every payload file. `PROVENANCE.json` records the locked inputs and source snapshot.

The native host is `org.teacher.video_downloader`. Real installs use `%LOCALAPPDATA%\LessonShelf\app`. The manifest at `%LOCALAPPDATA%\LessonShelf\native-host.json` points to `app\launch-host.exe`. The default value of `HKCU\Software\Mozilla\NativeMessagingHosts\org.teacher.video_downloader` points to that manifest. No machine registry key or administrator rights are required.

The launcher sets `TVD_STATE_DIR` to `%LOCALAPPDATA%\LessonShelf` and `YTDL_OUTPUT_DIR` from the preserved install record, initially the account's Downloads/youtube-downloads directory. It puts bundled tools first on PATH, removes PYTHONPATH/PYTHONHOME and uses bundled Python in isolated mode. Companion code must honor the state environment variable for the queue, jobs and `worker.lock`. The Windows worker lock must cover the first byte through `msvcrt.locking`; the installer takes the same lock before replacing program files. Mac uses `flock` on the same state-relative filename. No active process is killed.

Only Windows x64 is supported by this candidate. The bootstrap rejects Windows ARM64 and 32-bit Windows clearly. Do not label this as support for every Windows machine. Chrome is outside this release.

## Build on a Windows runner

Run from the repository using the runner's Python and installed .NET Framework compiler. Python 3.11+ is required for build tools, not for teachers. The bundled runtime is independent of the runner Python.

```powershell
$task = Join-Path $PWD '.scratch/mac-installer-20261103'
$cache = Join-Path $task 'upstream'
python scripts/macos/fetch_dependencies.py --cache $cache --package python-windows-x64 --package python-licenses-windows-x64 --package n-windows-x64 --package deno-windows-x64 --package deno-source --package ytdlp-windows-x64 --package ffmpeg-windows-x64 --package n-license --package ytdlp-license --package ytdlp-third-party
python scripts/windows/build_installer.py --output "$task/launch-host.exe"
python scripts/macos/prepare_payload.py --target windows-x64 --version 0.3.1 --firefox-id teacher-video-downloader@local.invalid --cache $cache --windows-launcher "$task/launch-host.exe" --output "$task/payload-windows-x64"
python scripts/windows/build_installer.py --payload "$task/payload-windows-x64" --output "$task/LessonShelf-0.3.1-windows-x64.exe"
```

Builders refuse existing output paths. Use a fresh runner or explicit new task-owned output paths. Mac can cross-compile the same C# sources with the pinned Microsoft SDK and .NET 4.8 reference assemblies recorded in `scripts/windows/build-tools.lock.json`. That produces real Windows PE executables; it does not prove Windows execution.

The GUI installs after the teacher clicks Install. It keeps the window responsive while extraction, checks and installation run. CI can run these modes with `Start-Process -Wait -PassThru` and inspect the exit code:

```powershell
# No registry writes. Install into a disposable simulated account.
Start-Process "$task/LessonShelf-0.3.1-windows-x64.exe" -ArgumentList @('--stage-root', 'C:\test-account') -Wait -PassThru
# Real current-user registration on the disposable Windows runner.
Start-Process "$task/LessonShelf-0.3.1-windows-x64.exe" -ArgumentList '--install' -Wait -PassThru
```

`--dry-run` is accepted after the staging directory. An extracted embedded archive is checked against the SHA-256 compiled into the bootstrap. The Python backend then verifies every payload file. Temporary extraction files belong only to that invocation. Reinstalling identical verified files is a no-op. An upgrade retains the old app and its prior registration under `rollback/`; it preserves the queue, jobs, partials, downloads and saved output location. Unknown registrations and app folders are refused. An active worker or interrupted installer stops the update. A failed registration restores the old program and registration. An interrupted process leaves recovery evidence for review.

## Native launcher transport check

After the staged EXE install, test the actual managed launcher before browser automation:

```powershell
python tests/windows_launcher_acceptance.py --app "$stage/AppData/Local/LessonShelf/app" --report "$task/reports/native-launcher.json"
```

This Windows-only check keeps stdin open while it sends doctor and status frames. It requires replies before EOF, all five bundled tool paths, a real isolated queue database and a clean launcher exit. The C# launcher forwards binary stdin/stdout/stderr explicitly and flushes each chunk. A Python-host-only test cannot qualify this transport.

## FFmpeg source distribution preparation

The exact supplier source cache from build run `41537430436` has been retrieved and verified against its upstream SHA-256. Its 129 source-input archives are indexed without running their code. The accompanying FFmpeg source is commit `f80a436ffd922aebb6d64824b301884da2cc1ee4`; build recipes are commit `58084b7cf4984303a34b610ba3ad8f04059d5d89`. The original download artifacts and hashes are pinned in `scripts/windows/source-distribution.lock.json`.

`package_sources.py --cache DIRECTORY --output NEW_DIRECTORY` verifies these inputs, splits the supplier cache into bounded transport parts, preserves the source archives and supplier license, and creates a manifest, per-archive index and restore helper. The restore helper's output has been verified against the complete upstream ZIP hash. The manifest also identifies the exact FFmpeg and ffprobe executable hashes. This package is separate from the teacher installer.

The staged package is `.scratch/mac-installer-20261103/source-distribution/ffmpeg-windows-20261102`. Before publication, parent review must approve the complete source offer and publish its parts, manifest, helper, recipes, source archive and licenses alongside the binary release. An expiring Actions artifact is not the intended durable source offer. [GNU guidance on binary/source access](https://www.gnu.org/licenses/gpl-faq.en.html#SourceAndBinaryOnDifferentSites).

## Release gates

Real Windows CI has fetched the pinned inputs, compiled the native launcher and installer, assembled the full payload and executed a staged EXE install successfully. Native-message/browser acceptance passed at e455372 in run 41775735474. The 480p and layout changes are being checked on the next source revision. The early transport check above tests the actual launch-host.exe. Mac staging and registry projection tests do not count as Windows evidence.

The input lock pins CPython 3.13.18 from the official Astral Python Build Standalone release 20261026, yt-dlp 2026.10.26, N_m3u8DL-RE 0.6.0-beta and the yt-dlp project's versioned FFmpeg build. Upstream SHA-256 values are verified before assembly. FFmpeg's upstream project publishes source; this Windows binary is explicitly a downstream yt-dlp project build. The corresponding source package is prepared and hash checked as described above. Parent source-offer review and publication remain pending; no legal approval or published source offer is claimed.

The beta candidate has no Authenticode signature or SmartScreen reputation evidence. Its release page must label this explicitly. Windows or school policy may block installation; testers should contact the maintainer rather than disable security checks or change execution policy. A warning-free production installer needs a trusted code-signing identity and a normal browser-download check on Windows. Public artifact publication and the extension link remain parent-owned review steps. No local Windows install, registry edit, workflow write, publication or browser change occurred in this installer chat.

The 0.3.1 payload also requires official Deno 2.9.8 for yt-dlp EJS. Add `--package deno-windows-x64 --package deno-source` to dependency fetching. The assembler copies `tools/deno.exe`, included notices and the pinned upstream source archive. PE validation covers Deno as well as every other executable. Native Windows acceptance must run the version and restricted offline JavaScript checks; Mac cross-compilation is not Windows execution evidence. Deno transitive notice coverage remains an explicit parent release gate; see [MAC-INSTALLER.md](MAC-INSTALLER.md#bundled-javascript-runtime-in-031).
