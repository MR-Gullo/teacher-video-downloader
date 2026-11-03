# Windows Firefox companion installer

## Contract for the runtime and CI

The offline payload layout is `runtime/python.exe`, `companion/*.py`, `tools/yt-dlp.exe`, `tools/ffmpeg.exe`, `tools/ffprobe.exe`, `tools/N_m3u8DL-RE.exe`, `installer/install_payload.py` and `installer/launch-host.exe`. Its `payload.json` uses schema 2, target `windows-x64`, semantic version, one exact Firefox ID and SHA-256 for every payload file. `PROVENANCE.json` records the locked inputs and source snapshot.

The native host is `org.teacher.video_downloader`. Real installs use `%LOCALAPPDATA%\LessonShelf\app`. The manifest at `%LOCALAPPDATA%\LessonShelf\native-host.json` points to `app\launch-host.exe`. The default value of `HKCU\Software\Mozilla\NativeMessagingHosts\org.teacher.video_downloader` points to that manifest. No machine registry key or administrator rights are required.

The launcher sets `TVD_STATE_DIR` to `%LOCALAPPDATA%\LessonShelf` and `YTDL_OUTPUT_DIR` from the preserved install record, initially the account's Downloads/youtube-downloads directory. It puts bundled tools first on PATH, removes PYTHONPATH/PYTHONHOME and uses bundled Python in isolated mode. Companion code must honor the state environment variable for the queue, jobs and `worker.lock`. The Windows worker lock must cover the first byte through `msvcrt.locking`; the installer takes the same lock before replacing program files. Mac uses `flock` on the same state-relative filename. No active process is killed.

Only Windows x64 is supported by this candidate. The bootstrap rejects Windows ARM64 and 32-bit Windows clearly. Do not label this as support for every Windows machine. Chrome is outside this release.

## Build on a Windows runner

Run from the repository using the runner's Python and installed .NET Framework compiler. Python 3.11+ is required for build tools, not for teachers. The bundled runtime is independent of the runner Python.

```powershell
$task = Join-Path $PWD '.scratch/mac-installer-20261103'
$cache = Join-Path $task 'upstream'
python scripts/macos/fetch_dependencies.py --cache $cache --package python-windows-x64 --package python-licenses-windows-x64 --package n-windows-x64 --package ytdlp-windows-x64 --package ffmpeg-windows-x64 --package n-license --package ytdlp-license --package ytdlp-third-party
python scripts/windows/build_installer.py --output "$task/launch-host.exe"
python scripts/macos/prepare_payload.py --target windows-x64 --version 0.3.0 --firefox-id teacher-video-downloader@local.invalid --cache $cache --windows-launcher "$task/launch-host.exe" --output "$task/payload-windows-x64"
python scripts/windows/build_installer.py --payload "$task/payload-windows-x64" --output "$task/LessonShelf-0.3.0-windows-x64.exe"
```

Builders refuse existing output paths. Use a fresh runner or explicit new task-owned output paths. Mac can cross-compile the same C# sources with the pinned Microsoft SDK and .NET 4.8 reference assemblies recorded in `scripts/windows/build-tools.lock.json`. That produces real Windows PE executables; it does not prove Windows execution.

The GUI installs after the teacher clicks Install. It keeps the window responsive while extraction, checks and installation run. CI can run these modes with `Start-Process -Wait -PassThru` and inspect the exit code:

```powershell
# No registry writes. Install into a disposable simulated account.
Start-Process "$task/LessonShelf-0.3.0-windows-x64.exe" -ArgumentList @('--stage-root', 'C:\test-account') -Wait -PassThru
# Real current-user registration on the disposable Windows runner.
Start-Process "$task/LessonShelf-0.3.0-windows-x64.exe" -ArgumentList '--install' -Wait -PassThru
```

`--dry-run` is accepted after the staging directory. An extracted embedded archive is checked against the SHA-256 compiled into the bootstrap. The Python backend then verifies every payload file. Temporary extraction files belong only to that invocation. Reinstalling identical verified files is a no-op. An upgrade retains the old app and its prior registration under `rollback/`; it preserves the queue, jobs, partials, downloads and saved output location. Unknown registrations and app folders are refused. An active worker or interrupted installer stops the update. A failed registration restores the old program and registration. An interrupted process leaves recovery evidence for review.

## Release gates

The current Windows candidate is built locally and has not yet run on Windows. Parent-owned CI must execute the installer, run all four real tools and bundled Python, verify native messaging and perform the Firefox download acceptance test. Mac staging and registry projection tests do not count as Windows evidence.

The input lock pins CPython 3.13.18 from the official Astral Python Build Standalone release 20261026, yt-dlp 2026.10.26, N_m3u8DL-RE 0.6.0-beta and the yt-dlp project's versioned FFmpeg build. Upstream SHA-256 values are verified before assembly. FFmpeg's upstream project publishes source; this Windows binary is explicitly a downstream yt-dlp project build. Keep the GPL license and review complete corresponding-source availability before public distribution. Do not describe that gate as complete.

The candidate has no Authenticode signature or SmartScreen reputation evidence. Before colleague sharing, inventory the appropriate code-signing identity on the Windows signing host, sign the reviewed executable, verify its signature, and test an actual browser download under normal Windows security policy. Do not instruct teachers to bypass security warnings or change execution policy. Public artifact publication and the extension link remain parent-owned review steps. No local Windows install, registry edit, workflow write, publication or browser change occurred in this installer chat.
