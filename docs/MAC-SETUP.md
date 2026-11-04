# Set up LessonShelf on Mac

The normal Mac installer is waiting for Developer ID signing and notarization. Do not send a source ZIP or temporary add-on to non-technical testers as a normal installer. The [installation page](https://mr-gullo.github.io/teacher-video-downloader/#setup) will link to the Mac download when it is available.

## Existing preview installations

Open LessonShelf, expand **Help & setup**, and choose **Check connection**, then **Check local tools**. The current companion includes yt-dlp, FFmpeg, FFprobe, N_m3u8DL-RE and Deno. No Homebrew or separate tool installation is needed for this bundle. Firefox will ask permission before selected video links are sent to the companion.

The default is a compatible H.264/AAC MP4 at up to 720p, saved in Downloads/youtube-downloads. Course folders are optional. Private provenance and recovery files stay in the application support folder.

## Updates and recovery

Let active downloads finish or pause them before an update. The installer preserves the queue, partials, downloaded files and output location. It keeps the previous program and registration for rollback. An unknown installation, active worker or interrupted installer stops an update rather than replacing uncertain files.

Temporary Firefox and Zen previews are removed when the browser closes. They are separate from the forthcoming signed installer path. Do not delete application support data to reconnect or update.

## School IT and release maintainers

See [Mac installer architecture and signing](MAC-INSTALLER.md). The account holder must provide Developer ID signing and notarization readiness. Private keys and passwords must not be sent in chat. Chrome remains paused. Source, local checks and an ad hoc signature do not establish a normal Gatekeeper-approved install.
