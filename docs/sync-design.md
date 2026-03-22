# Sync Design For UnoLock Agent

This document proposes a daemon-backed sync feature for `unolock-agent`.

The feature goal is narrow:

* watch a configured list of local files
* automatically upload changed files into UnoLock Cloud storage
* allow explicit restore back to the local filesystem
* expose current status in one JSON-shaped CLI surface

This is intentionally a small-file sync feature, not a full bidirectional sync system.

## Why This Fits The Current Agent Model

The current agent runtime already has the required primitives:

* a local daemon process
* persisted local state under the UnoLock config directory
* current-Space selection
* Cloud file upload, replace, download, and list operations

That means sync should be built as one more daemon-managed local capability, not as a separate long-running helper.

## Product Guardrails

Hard rules for v1:

* Sync only works for `Cloud` files.
* Sync requires a Cloud-capable Safe/Space and a writable Agent Key.
* Restore can work with read-only access, but only for already-backed-up files.
* Free Safe should be treated as unsupported for this feature if Cloud files are not available.
* The CLI must fail with a specific tier/capability message instead of a generic upload failure.
* Sync watches local files only in v1. No recursive directory watching yet.
* Empty files remain unsupported until normal Cloud upload supports them.

Recommended user-facing error:

* `feature_not_supported: Sync and restore require UnoLock Cloud files, which are not available for this Safe or Space.`

## User Model

One sync job maps one local file to one UnoLock Cloud archive in one Space.

The daemon owns:

* watching the local file
* deciding when it changed
* uploading a first copy or replacing the existing Cloud file
* remembering the last successful local digest
* reporting whether the job is idle, dirty, syncing, blocked, or failed

The user or agent still triggers restore explicitly. Remote changes are not auto-pulled down.

Future direction:

* once the web client can edit sync notes and users can update remote files intentionally, the daemon can evolve from `push` to optional `pull` or `bidirectional` mode
* that should be added as a later phase, not silently folded into v1

## Configuration Source Of Truth

The configured watch list should live in a reserved UnoLock note, not only in local disk state.

Recommended split:

* reserved note in UnoLock: desired sync configuration
* local state file: runtime cache, digests, timestamps, transient status, and in-flight work

This fits the agent product better because:

* configuration follows the Safe instead of one workstation
* a new daemon instance can rehydrate its watch list after authentication
* configuration stays inside client-side encrypted UnoLock data
* local state can still stay optimized for polling and status without constant note rewrites

The schema should also leave room for future bidirectional sync, even if v1 stays local-to-remote plus explicit restore.

### Reserved Note Convention

Use a reserved title namespace instead of an ordinary human note title.

Recommended title pattern:

* `@unolock-agent.sync-config:<key_id>`

Why include `key_id`:

* avoids collisions if multiple agent keys exist in the same Space
* avoids one device or agent key overwriting another agent's local-path config
* keeps the reserved note deterministic and discoverable

If `key_id` is unavailable, the daemon should block config writes instead of inventing an unstable fallback.

Use a separate reserved note for human-readable sync events.

Recommended title pattern:

* `@unolock-agent.sync-events:<key_id>`

This note is for diagnostics and operator visibility only. It must not be the source of truth for config or runtime state.

### Reserved Note Body

The note body should store declarative config only.

Example:

```json
{
  "schema_version": 1,
  "key_id": "unolock-agent",
  "jobs": [
    {
      "sync_id": "syn_01",
      "space_id": 1773,
      "local_path": "/abs/path/to/file.txt",
      "name": "file.txt",
      "mime_type": "text/plain",
      "archive_id": "12345",
      "mode": "push",
      "enabled": true,
      "poll_seconds": 60,
      "debounce_seconds": 10
    }
  ]
}
```

Do not put high-churn fields in the note body:

* no last-upload timestamps
* no current status
* no last-error text
* no per-save digest history

Those fields would cause unnecessary note rewrites and version conflicts.

Reserve `mode` now so future UI and CLI can support:

* `push`: local changes auto-upload, remote changes do not auto-download
* `pull`: remote changes auto-download, local changes do not auto-upload
* `bidirectional`: whichever side changes first can propagate, subject to conflict rules

For v1, only `push` is supported.

## Reserved Events Note

The daemon may append important sync events to the reserved sync-events note after authentication.

This is useful for:

* agent-visible diagnostics
* user-visible audit breadcrumbs inside the Safe
* preserving notable failures across daemon restarts

It should not be used for:

* high-frequency status updates
* per-poll heartbeat logging
* replacing `syncs.json`
* replacing normal CLI `sync-status`

Recommended event types:

* sync added
* initial upload completed
* sync blocked
* sync resumed
* upload failed
* remote file missing
* conflict detected in a future bidirectional mode

Avoid logging routine success noise like every unchanged poll or every successful periodic replace.

### Events Note Format

The simplest safe model is append-only text with one JSON object per line.

Example line:

```json
{"ts":"2026-03-21T14:22:11Z","level":"error","space_id":1773,"sync_id":"syn_01","event":"upload_failed","reason":"space_read_only","message":"Write access is no longer available for this Space."}
```

Recommended rules:

* append only
* one event per line
* newest events at the end
* no requirement to parse old prose or reformatted text

### Event Logging Guardrails

The events note should be rate-limited and size-bounded.

Recommended rules:

* append only significant transitions, not repeated identical failures every poll
* coalesce duplicate events for the same `sync_id` and `reason`
* rotate or compact once the note reaches a defined size threshold
* preserve recent high-signal events, drop stale noise first

Security rules:

* never log plaintext file contents
* never log PINs, session secrets, raw callback payloads, or private keys
* avoid unnecessary local path detail when a `sync_id` and file name are enough
* prefer reason codes and short operator messages over raw exception dumps

Architecture rule:

* event logging should be one sink called by the sync service after meaningful state transitions
* failures to append to the events note must never block sync itself

## CLI Shape

To match the current flat command style, prefer flat sync commands over nested `sync ...` subcommands.

### Add A Watch

```bash
unolock-agent sync-add /abs/path/to/file.txt
unolock-agent sync-add /abs/path/to/file.txt --space-id 1773 --title notes.txt
unolock-agent sync-add /abs/path/to/file.txt --archive-id 12345
```

Arguments:

* `local_path` required
* `--space-id <id>` optional, defaults to current Space
* `--title <name>` optional remote file name override
* `--mime-type <type>` optional remote MIME override
* `--archive-id <id>` optional if binding to an existing Cloud file instead of creating a new one
* `--poll-seconds <n>` optional per-job override, default from daemon config
* `--debounce-seconds <n>` optional per-job override, defaults to `2`
* `--disabled` optional, create the watch without enabling uploads yet

Behavior:

* verifies the local file exists
* verifies the Space is Cloud-capable
* verifies the session can write if auto-sync is enabled
* writes the declarative job into the reserved sync-config note
* creates the first remote copy immediately unless `--disabled` is used
* updates local runtime state so daemon restarts keep watching it

### Remove A Watch

```bash
unolock-agent sync-remove <sync_id>
```

Arguments:

* `sync_id` required
* `--delete-remote` optional, only if we explicitly want removal to also delete the Cloud file

Default behavior should remove only the watch, not the remote file.

### Enable / Disable A Watch

```bash
unolock-agent sync-enable <sync_id>
unolock-agent sync-disable <sync_id>
```

This is simpler and safer than overloading `sync-add` for all lifecycle changes.

### Trigger Sync Now

```bash
unolock-agent sync-run <sync_id>
unolock-agent sync-run --all
```

Behavior:

* performs an immediate scan
* uploads any dirty jobs now
* returns per-job results

### Restore

```bash
unolock-agent sync-restore <sync_id>
unolock-agent sync-restore <sync_id> --output-path /tmp/restore.txt --overwrite
```

Arguments:

* `sync_id` required
* `--output-path <path>` optional, defaults to the watched local path
* `--overwrite` optional

Behavior:

* downloads the bound Cloud archive
* writes to the requested local path
* updates local job metadata to the restored digest only if the restore target is the watched path

### List / Status

```bash
unolock-agent sync-list
unolock-agent sync-status
unolock-agent sync-status <sync_id>
```

`sync-list` is the static configured view.

`sync-status` is the live daemon/runtime view and should include:

* whether the daemon is running
* whether sync monitoring is active
* count of jobs by state
* per-job last success, pending change, or error details

## CLI JSON Response Shape

Keep the current CLI convention: one compact JSON object on success.

### `sync-add`

```json
{
  "sync": {
    "sync_id": "syn_01",
    "space_id": 1773,
    "archive_id": "12345",
    "local_path": "/abs/path/to/file.txt",
    "name": "file.txt",
    "enabled": true,
    "status": "synced"
  }
}
```

### `sync-status`

```json
{
  "daemon_running": true,
  "monitoring": true,
  "count": 2,
  "states": {
    "synced": 1,
    "dirty": 0,
    "syncing": 0,
    "blocked": 1,
    "error": 0
  },
  "syncs": [
    {
      "sync_id": "syn_01",
      "space_id": 1773,
      "archive_id": "12345",
      "local_path": "/abs/path/to/file.txt",
      "enabled": true,
      "status": "synced",
      "last_uploaded_at": "2026-03-21T14:22:11Z",
      "last_local_change_at": "2026-03-21T14:21:59Z",
      "last_error": null
    }
  ]
}
```

## New Internal MCP Tool Layer

The CLI should stay thin. The daemon should expose sync operations as normal internal tools so both direct CLI and MCP-hosted agent flows can use the same implementation.

Suggested tool names:

* `unolock_sync_add`
* `unolock_sync_remove`
* `unolock_sync_enable`
* `unolock_sync_disable`
* `unolock_sync_list`
* `unolock_sync_status`
* `unolock_sync_run`
* `unolock_sync_restore`

These should remain local-runtime tools. They are about local filesystem orchestration plus normal UnoLock Cloud file operations.

## Local Persistent State

Store sync configuration separately from registration state:

* `registration.json` keeps registration and current Space
* new `syncs.json` keeps watch definitions and sync metadata

Recommended path:

* `<default_state_dir()>/syncs.json`

Recommended top-level shape:

```json
{
  "version": 1,
  "defaults": {
    "poll_seconds": 60,
    "debounce_seconds": 10
  },
  "jobs": [
    {
      "sync_id": "syn_01",
      "space_id": 1773,
      "archive_id": "12345",
      "local_path": "/abs/path/to/file.txt",
      "mode": "push",
      "local_path_resolved": "/abs/path/to/file.txt",
      "name": "file.txt",
      "mime_type": "text/plain",
      "enabled": true,
      "poll_seconds": 60,
      "debounce_seconds": 10,
      "created_at": "2026-03-21T14:20:00Z",
      "updated_at": "2026-03-21T14:22:11Z",
      "last_uploaded_at": "2026-03-21T14:22:11Z",
      "last_restored_at": null,
      "last_uploaded_sha256": "abc123...",
      "last_downloaded_at": null,
      "last_remote_revision": null,
      "last_remote_sha256": null,
      "last_seen_size": 4821,
      "last_seen_mtime_ns": 1742575311123456789,
      "status": "synced",
      "last_error": null
    }
  ]
}
```

Notes:

* keep file mode private like the other local state files
* store absolute resolved paths to avoid duplicate watches through symlinks or relative paths
* keep status persisted for diagnostics, but treat live in-memory state as authoritative while daemon is running
* treat this file as a cache and runtime overlay, not the declarative source of truth

Reserve remote-tracking fields now even if v1 does not fully use them. That avoids a later storage migration just to support remote-change detection.

## Authentication-Time Reconciliation

On successful authentication, the daemon should fetch the reserved sync-config note and reconcile local monitor state.

Recommended flow:

1. Authenticate normally.
2. Read the reserved config note for the active agent key in each relevant Space.
3. If the note exists, parse the manifest and reconcile it against local runtime state.
4. If the note does not exist, keep local runtime state empty until the first `sync-add`.
5. If the note is malformed, mark sync as `blocked` with `invalid_sync_config_note`.

Reconciliation rule:

* remote reserved note is the source of truth for configured jobs
* local runtime state keeps only cached operational fields for those jobs
* local jobs not present in the reserved note should be dropped from active monitoring

This is the part your suggestion improves materially: the daemon does not need a manually copied local config file to know what it should watch after auth.

## Daemon Architecture

Use the existing daemon process, but do not overload the auth keepalive hook with full file scanning.

Recommended structure:

* keep the existing auth/session keepalive loop
* add a dedicated `SyncMonitor` service inside the daemon
* start it when `ToolHostController` starts
* stop it when `ToolHostController.close()` runs

Reason:

* auth keepalive and file watching have different timing needs
* auth keepalive can stay coarse
* sync scanning needs a shorter cadence and debouncing
* this avoids making session maintenance depend on filesystem work

### Monitor Loop

For v1, polling is the safer implementation than OS-native watchers.

Use:

* `stat()` change detection on `mtime_ns` and `size`
* SHA-256 calculation only after `stat()` indicates a change
* debounce before upload so editor save bursts collapse into one replace

Why polling first:

* no extra native dependency like `watchdog`
* simpler cross-platform packaging for npm binary and source installs
* easier deterministic testing

Suggested defaults:

* global scan every `5s`
* per-file debounce `2s`
* only one active upload per `sync_id`
* low global concurrency, for example `2`

For future bidirectional mode, add a second coarse remote poll loop, for example every `30s` or `60s`, rather than trying to poll the remote side as aggressively as the local filesystem.

## Upload Semantics

For each enabled job:

1. Resolve and `stat()` the local file.
2. If missing, mark `blocked` with `local_file_missing`.
3. If unchanged, do nothing.
4. If changed, wait until debounce expires.
5. Compute SHA-256 of plaintext local file.
6. If digest matches `last_uploaded_sha256`, clear dirty state and update local stat metadata only.
7. If `archive_id` is missing, call upload-file semantics.
8. If `archive_id` exists, call replace-file semantics.
9. Persist new digest, timestamps, and success status.

This avoids needless re-upload when tools rewrite the file without changing content.

## Future Remote Polling

Bidirectional sync will need remote-change detection.

Recommended model:

* local side: frequent polling based on `stat()` plus digest on change
* remote side: slower polling based on `list-files` and `get-file`
* only fetch remote content when metadata suggests the bound archive changed

The remote poll should track at least:

* current `archive_id`
* remote size
* remote name
* some revision signal if available from the API
* a cached digest of the last downloaded remote content when we had to fetch it

If the API does not expose a stable revision field, the daemon can still treat changed remote size or other metadata drift as a signal to download once and recompute the remote digest client-side.

## Restore Semantics

Restore should stay explicit.

Rules:

* `sync-restore` restores from the bound `archive_id`
* default target is the watched local path
* if the target exists and `--overwrite` is not passed, fail
* if the target is the watched path and restore succeeds, refresh local stat and digest metadata

Important limitation:

* v1 does not auto-detect remote-side edits made outside this daemon
* sync is single-writer by design in v1
* if remote changes matter, the user or agent must run explicit restore

## Future Bidirectional Semantics

Eventually, bidirectional sync should be supported so a user can upload an updated file and the agent daemon will download it automatically.

That should be introduced as an explicit per-job mode, not as a silent change to all sync jobs.

Recommended future behavior:

* `push`: current v1 behavior
* `pull`: daemon auto-downloads remote changes into the watched local path
* `bidirectional`: daemon can propagate both local and remote changes

In `bidirectional` mode, each job should track both sides independently:

* last synced local digest
* last synced remote digest
* last local observation time
* last remote observation time

Then the daemon can classify each job as:

* `local_dirty`: local changed since last sync, remote did not
* `remote_dirty`: remote changed since last sync, local did not
* `conflicted`: both changed since last sync

Recommended conflict rule:

* do not auto-merge
* do not silently choose a winner
* mark the job `conflicted`
* require an explicit resolution command later, for example `sync-resolve --prefer local` or `sync-resolve --prefer remote`

That is the main reason not to promise full bidirectional behavior in v1: once both sides can change, conflict handling becomes the real product boundary.

## Status Model

Per-job statuses:

* `new`: configured but not uploaded yet
* `synced`: local file matches last successful uploaded digest
* `dirty`: local change detected, waiting to upload
* `syncing`: upload in progress
* `blocked`: upload cannot proceed until a known blocker is fixed
* `error`: last attempt failed unexpectedly
* `disabled`: watch exists but monitoring is off

Reserve future statuses:

* `local_dirty`
* `remote_dirty`
* `downloading`
* `conflicted`

Recommended blocker reasons:

* `feature_not_supported`
* `space_read_only`
* `missing_current_space`
* `local_file_missing`
* `archive_missing`
* `authentication_required`

## Tier And Capability Detection

Do this up front at `sync-add` time and on every upload attempt.

A Space is sync-capable only if:

* the agent session can write, and
* `_resolve_cloud_upload_location(...)` succeeds for that Space

If capability disappears later:

* keep the job
* set status to `blocked`
* preserve the last successful sync metadata
* report a clear upgrade/capability message in `sync-status`

## Reserved Note Write Rules

Every config-changing command should use note read-modify-write semantics:

1. read the reserved config note
2. parse manifest JSON
3. apply one config change
4. write back with the latest `record_ref` and version
5. if a write conflict happens, reread, merge, and retry once

This is safer than treating the local cache as authoritative because normal UnoLock note updates already have a version model.

## Interaction With Current Space

Current Space should remain the default for sync commands.

Rules:

* `sync-add` without `--space-id` binds to the current Space at creation time
* later changes to current Space must not silently move existing jobs
* every job stores its own `space_id`

That avoids surprising cross-Space sync targets after the user switches context for unrelated work.

## Security And Privacy Constraints

Keep the existing safety model:

* no plaintext file content leaves the client unencrypted
* no plaintext synced content is written into extra local cache files
* only hashes, file paths, status, and job metadata are persisted locally
* local state files stay private on disk

Acceptable local metadata to persist:

* absolute local path
* file size
* file `mtime_ns`
* last successful local SHA-256
* remote archive ID
* status and timestamps

## Recommended Implementation Phases

### Phase 1

* add `syncs.json` store
* add CLI and internal tools for `sync-add`, `sync-list`, `sync-run`, `sync-status`
* first upload works, but no background monitor yet

### Phase 2

* add daemon `SyncMonitor`
* add automatic polling, debounce, and status transitions
* add `sync-enable`, `sync-disable`, `sync-remove`

### Phase 3

* add `sync-restore`
* add clearer blocked reasons for unsupported Free Safe / non-Cloud tiers
* add docs and site copy

### Phase 4

* add remote metadata polling
* add `mode` support in config note and CLI
* support `pull` mode first

### Phase 5

* add full `bidirectional` mode
* add conflict detection and explicit resolution commands
* add web-client UI for per-job direction and conflict state

## Testing Strategy

Add unit coverage for:

* job store read/write and path normalization
* duplicate watch rejection for the same resolved path
* add-watch failure on non-existent local file
* add-watch failure on non-Cloud-capable Space
* digest-based no-op when content is unchanged
* replace vs create behavior
* blocked status when local file disappears
* restore overwrite guard
* daemon reload of persisted jobs on startup

Add integration coverage for:

* create watch, edit local file, daemon uploads replacement
* restart daemon, persisted watch resumes
* read-only Agent Key can restore but cannot auto-sync

## Open Questions

These do not block v1, but they should be decided explicitly:

* Should `sync-remove` ever delete the remote file, or should that always remain a separate explicit action?
* Should `sync-add` create the first remote copy immediately, or only after the first observed change?
* Do we want a global pause switch for all monitoring?
* Do we want future directory support, or should that stay out of scope for the agent product entirely?
* What remote metadata is stable enough to use as a revision signal without downloading the whole file every poll?
* Should future bidirectional jobs default to blocking on conflict, or should the user have to opt into a conflict policy?

## Recommendation

Build v1 as a single-file, upload-first sync feature with explicit restore, but reserve the schema and local state needed for future remote polling and bidirectional mode.

That gives the agent a durable way to protect important local working artifacts now, while keeping a clean path to future automatic remote-to-local updates when the web client starts managing sync notes directly.
