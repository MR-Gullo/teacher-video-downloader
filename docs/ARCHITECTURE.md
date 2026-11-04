# Architecture, durability and security

Extension-owned popup/dashboard → background `sendNativeMessage` → framed stdin/stdout host → private SQLite queue → detached Python worker → argv-only engine processes. **There is no HTTP control service.** The HTTP server in tests is only a loopback media fixture, never installed.

## Queue and ownership

- Native messages are limited to512KiB; response history capped at100 newest jobs and400,000 encoded bytes. Input50 jobs/batch, durable history500. URLs8KiB max, titles/course names sanitized. Only HTTP(S), no userinfo/control characters or file/blob URLs.
- SQLite WAL with transactional inserts, URL+settings fingerprint deduplication (title/page provenance changes do not create duplicate jobs). Existing complete jobs are not automatically re-downloaded by double click; re-download with changed settings or deliberate state archival.
- One worker's nonblocking OS file lock serializes execution. Lock descriptor is passed to the download/FFmpeg child to prevent concurrent output writers if the worker is SIGKILLed. On crash recovery, active entries become **paused**, not silently complete. Actual third-party engines' descriptor behavior still needs Mac testing; cooperative stub behavior was verified.
- Native pipe disconnect does not terminate detached worker. Child process groups receive TERM then KILL on pause/cancel. Progress is advisory, capped99 until finalized. Bounded engine retries (8 HTTP/fragments) plus up to3 full attempts with2/4-second queue backoff; yt-dlp's per-request exponential delay caps30 seconds. This can still take a while during outages.
- Run directory is stable per UUID; `.part`, fragment state and N segments are never removed on interruption. N retry preserves the directory **but does not promise segment resume**. yt-dlp native continuation still depends on extractor/server behavior. Signed URL expiry may require a newly captured URL and new job; no automatic browser-auth refresh exists.
- Cancellation changes persistent state immediately. Running child is checked every200ms and allowed5 seconds to terminate. Short media probing (up to60 seconds), hashing and atomic publication are not preempted mid-system-call; the state transition is guarded so pause/cancel is not overwritten by completion. A fully published original can remain after cancellation; data preservation is intentional.
- Source validation uses ffprobe. Generated copies also undergo full FFmpeg decode, duration, audio/subtitle count, chapter count and frame-rate checks (0.2% tolerance for container time-base rounding). This is not a perceptual-quality guarantee. Failed source/copy processing does not delete original/partial files.
- Final publication stages and fsyncs a complete file then atomically creates a hard link without overwrite. Stable job-specific names plus content hash make crash retry idempotent. Unsupported destination filesystems fail safely. Hidden `.tvd-publish-*` staging leftovers after a hard crash can be manually removed only after stopping work.

## YouTube clips

The popup reads the active YouTube watch-page player's video ID, current time and finite duration. Clip controls are optional and start with In at the current playhead, rounded down to a second, and Out at the end. Two timeline handles and editable time fields share one range. Unknown durations, live streams, ads and unsupported player contexts leave clipping unavailable.

Before submission, the popup checks that the same page and video are still active. The native request carries an immutable `clip` object with `start`, `end` and source `duration`. The host rejects non-finite numbers, booleans and ranges outside `0 <= start < end <= duration`. The selected range participates in job deduplication and stays attached to retries and the saved filename.

Clip requests use separate `enqueue-clip`, `resume-clip` and `retry-clip` operations. An older host rejects these operations instead of silently downloading the whole video. Ordinary enqueue rejects a clip payload. Clips use yt-dlp download sections and FFmpeg keyframe cuts, then the standard H.264/AAC MP4 output path. They omit captions and extra copies. The worker checks the resulting duration before publication; a mismatched full video cannot be reported as a saved clip. Source metadata and range provenance stay in private job storage, not beside the downloaded video.

YouTube extraction uses the bundled Deno runtime through an explicit path. It disables remote components and unrelated system JavaScript runtimes. Both native launchers disable Deno update checks. Detached Python workers start with `-B` so they do not write bytecode inside the sealed application.

## Privacy

Queue/state/app directory mode0700; host/worker umask0077. Full signed download URLs necessarily live in private job data for retry. Native status strips query tokens and bounds display fields. No raw engine output is persisted: only fixed progress/error text, avoiding accidental token logs. Processes still carry URL argv; other processes running as the same user may see them. This is not a hardened secret vault against same-user malware.

Browser stream observation is **opt-in per origin**. Captures are bounded, cleared on tab navigation/close, site-disable and browser startup. Signed captured URLs may exist briefly in the browser's local extension storage. No sync storage is used. No page-content-to-native message bridge; only extension-owned pages send queue commands. Native host manifests allow only the exact Chrome extension ID and fixed Firefox add-on ID. Manifest files are not authentication between processes of the same OS user; user-local process access is trusted.

No cookie permissions, cookie values, Authorization header capture, profile scraping, arbitrary engine switches, shell execution, external pages for configuration, or DRM key interfaces. Source provenance strips arbitrary query strings; a valid YouTube `v` identifier is retained. Do not assume provider's source media itself contains no metadata. Downloads are for content the user has permission to save.

## Known deliberately missing features

Authenticated cookie/session transfer; verified Spokenly adapter; aria2 integration; live recording UI; quality/track enumeration before download; job URL refresh in-place; queue-history management UI; signed Firefox distribution; automatic Mac updates; system-login auto-start. No claims of full wrapper parity.
