from __future__ import annotations

import secrets
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from unolock_mcp.sync.config_note import (
    DEFAULT_SYNC_DEBOUNCE_SECONDS,
    DEFAULT_SYNC_POLL_SECONDS,
    SYNC_CONFIG_NOTE_PREFIX,
    SYNC_EVENTS_NOTE_PREFIX,
    SyncJobConfig,
    SyncManifest,
    reserved_sync_config_note_title,
    reserved_sync_events_note_title,
)
from unolock_mcp.sync.engine import run_push_job, sha256_file, utc_now_iso
from unolock_mcp.sync.events import SyncEvent
from unolock_mcp.sync.reconciler import reconcile_manifests
from unolock_mcp.sync.runtime_store import SyncRuntimeJob, SyncRuntimeState, SyncRuntimeStore


def _normalize_title(local_path: str, title: str | None) -> str:
    if isinstance(title, str) and title.strip():
        return title.strip()
    return Path(local_path).name or "sync-file"


def _normalize_lookup_path(value: str) -> str:
    return str(Path(value).expanduser().resolve(strict=False))


def _state_counts(state: SyncRuntimeState) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in state.jobs:
        counts[job.status] = counts.get(job.status, 0) + 1
    return counts


ERROR_EVENT_DEDUPE_WINDOW_SECONDS = 300


def _event_key(reason: str, message: str) -> str:
    return f"{reason.strip()}|{message.strip()}"


def _parse_iso_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _poll_due(last_updated_at: str | None, poll_seconds: int) -> bool:
    if poll_seconds <= 0:
        return True
    last_updated = _parse_iso_timestamp(last_updated_at)
    if last_updated is None:
        return True
    return (datetime.now(timezone.utc) - last_updated).total_seconds() >= poll_seconds


class SyncService:
    def __init__(
        self,
        readonly_records,
        writable_records,
        readonly_files,
        writable_files,
        runtime_store: SyncRuntimeStore,
    ) -> None:
        self._readonly_records = readonly_records
        self._writable_records = writable_records
        self._readonly_files = readonly_files
        self._writable_files = writable_files
        self._runtime_store = runtime_store

    def _generate_sync_id(self) -> str:
        return f"syn_{secrets.token_hex(4)}"

    def _resolve_runtime_job(self, state: SyncRuntimeState, identifier: str) -> SyncRuntimeJob:
        candidate = identifier.strip()
        if not candidate:
            raise ValueError("invalid_input: sync identifier must not be empty.")
        target_job = next((job for job in state.jobs if job.sync_id == candidate), None)
        if target_job is not None:
            return target_job
        normalized_path = _normalize_lookup_path(candidate)
        target_job = next(
            (
                job
                for job in state.jobs
                if _normalize_lookup_path(job.local_path_resolved) == normalized_path
            ),
            None,
        )
        if target_job is not None:
            return target_job
        raise ValueError("record_not_found: Sync job not found for sync_id or local_path.")

    def _list_space_summaries(self, session_id: str) -> list[dict[str, Any]]:
        payload = self._readonly_records.list_spaces(session_id)
        spaces = payload.get("spaces") or []
        if not isinstance(spaces, list):
            return []
        return [space for space in spaces if isinstance(space, dict)]

    def _get_space_summary(self, session_id: str, space_id: int) -> dict[str, Any]:
        for space in self._list_space_summaries(session_id):
            if int(space.get("space_id") or 0) == space_id:
                return space
        raise ValueError("record_not_found: The requested space_id is not available to this agent.")

    def _find_reserved_config_note(self, session_id: str, *, space_id: int) -> dict[str, Any] | None:
        return self._find_reserved_note(
            session_id,
            space_id=space_id,
            title=reserved_sync_config_note_title(),
            legacy_prefix=SYNC_CONFIG_NOTE_PREFIX,
            error_kind="sync config",
        )

    def _find_reserved_events_note(self, session_id: str, *, space_id: int) -> dict[str, Any] | None:
        return self._find_reserved_note(
            session_id,
            space_id=space_id,
            title=reserved_sync_events_note_title(),
            legacy_prefix=SYNC_EVENTS_NOTE_PREFIX,
            error_kind="sync events",
        )

    def _find_reserved_note(
        self,
        session_id: str,
        *,
        space_id: int,
        title: str,
        legacy_prefix: str | None = None,
        error_kind: str = "reserved note",
    ) -> dict[str, Any] | None:
        payload = self._readonly_records.list_records(session_id, kind="note", space_id=space_id)
        records = payload.get("records") or []
        matches = [
            record
            for record in records
            if isinstance(record, dict) and str(record.get("title", "")).strip() == title
        ]
        if len(matches) > 1:
            raise ValueError(f"invalid_sync_config_note: Multiple reserved {error_kind} notes named {title!r} exist in space {space_id}.")
        if matches:
            return matches[0]
        if legacy_prefix is None:
            return None
        legacy_matches = [
            record
            for record in records
            if isinstance(record, dict) and str(record.get("title", "")).strip().startswith(legacy_prefix)
        ]
        if len(legacy_matches) > 1:
            raise ValueError(
                f"invalid_sync_config_note: Multiple reserved {error_kind} notes with prefix {legacy_prefix!r} exist in space {space_id}."
            )
        return legacy_matches[0] if legacy_matches else None

    def _parse_reserved_manifest_note(self, note: dict[str, Any]) -> SyncManifest:
        try:
            return SyncManifest.from_note_text(str(note.get("plain_text", "")))
        except ValueError as exc:
            raise ValueError(f"invalid_sync_config_note: {exc}") from exc

    def _load_manifests(self, session_id: str, *, key_id: str) -> list[SyncManifest]:
        manifests: list[SyncManifest] = []
        for space in self._list_space_summaries(session_id):
            space_id = int(space.get("space_id") or 0)
            if space_id <= 0:
                continue
            note = self._find_reserved_config_note(session_id, space_id=space_id)
            if note is None:
                continue
            manifest = self._parse_reserved_manifest_note(note)
            for job in manifest.jobs:
                if job.space_id != space_id:
                    raise ValueError("invalid_sync_config_note: Sync job space_id does not match the containing Space.")
            manifests.append(manifest)
        return manifests

    def _upsert_manifest(self, session_id: str, *, space_id: int, key_id: str, manifest: SyncManifest) -> dict[str, Any]:
        title = reserved_sync_config_note_title()
        current = self._find_reserved_config_note(session_id, space_id=space_id)
        if current is None:
            return self._writable_records.create_note(
                session_id,
                space_id=space_id,
                title=title,
                text=manifest.to_note_text(),
            )
        return self._writable_records.update_note(
            session_id,
            record_ref=str(current.get("record_ref", "")),
            expected_version=int(current.get("version") or 0),
            title=title,
            text=manifest.to_note_text(),
        )

    def _persist_job_archive_binding(
        self,
        session_id: str,
        *,
        job: SyncRuntimeJob,
    ) -> None:
        if not job.archive_id:
            return
        note = self._find_reserved_config_note(session_id, space_id=job.space_id)
        if note is None:
            return
        manifest = self._parse_reserved_manifest_note(note)
        target = next((config_job for config_job in manifest.jobs if config_job.sync_id == job.sync_id), None)
        if target is None or target.archive_id == job.archive_id:
            return
        next_manifest = SyncManifest(
            jobs=tuple(
                replace(config_job, archive_id=job.archive_id) if config_job.sync_id == job.sync_id else config_job
                for config_job in manifest.jobs
            ),
        )
        self._upsert_manifest(
            session_id,
            space_id=job.space_id,
            key_id=None,
            manifest=next_manifest,
        )

    def _append_error_event(
        self,
        session_id: str,
        *,
        space_id: int,
        sync_id: str,
        archive_id: str | None,
        reason: str,
        message: str,
    ) -> None:
        title = reserved_sync_events_note_title()
        event = SyncEvent(
            level="error",
            event=reason,
            message=message,
            space_id=space_id,
            sync_id=sync_id,
            archive_id=archive_id,
            reason=reason,
        )
        line = event.to_json_line()
        current = self._find_reserved_events_note(session_id, space_id=space_id)
        try:
            if current is None:
                self._writable_records.create_note(
                    session_id,
                    space_id=space_id,
                    title=title,
                    text=line,
                )
                return
            self._writable_records.append_note(
                session_id,
                record_ref=str(current.get("record_ref", "")),
                expected_version=int(current.get("version") or 0),
                append_text=line,
            )
        except Exception:
            return

    def _record_error_event_if_needed(
        self,
        session_id: str,
        *,
        job: SyncRuntimeJob,
        reason: str,
        message: str,
    ) -> SyncRuntimeJob:
        key = _event_key(reason, message)
        now = datetime.now(timezone.utc)
        previous_key = (job.last_error_event_key or "").strip()
        previous_at = _parse_iso_timestamp(job.last_error_event_at)
        if previous_key == key and previous_at is not None:
            if (now - previous_at).total_seconds() < ERROR_EVENT_DEDUPE_WINDOW_SECONDS:
                return job
        self._append_error_event(
            session_id,
            space_id=job.space_id,
            sync_id=job.sync_id,
            archive_id=job.archive_id,
            reason=reason,
            message=message,
        )
        return replace(
            job,
            last_error_event_key=key,
            last_error_event_at=utc_now_iso(),
        )

    def refresh_from_remote(self, session_id: str, *, key_id: str | None) -> dict[str, Any]:
        manifests = self._load_manifests(session_id, key_id=(key_id or ""))
        runtime = self._runtime_store.load()
        reconciled = reconcile_manifests(manifests, runtime)
        self._runtime_store.save(reconciled)
        return {
            "count": len(reconciled.jobs),
            "syncs": [job.to_json() for job in reconciled.jobs],
        }

    def list_syncs(self, session_id: str, *, key_id: str | None) -> dict[str, Any]:
        manifests = self._load_manifests(session_id, key_id=(key_id or ""))
        runtime = self._runtime_store.load()
        reconciled = reconcile_manifests(manifests, runtime)
        self._runtime_store.save(reconciled)
        return {
            "count": len(reconciled.jobs),
            "syncs": [job.to_json() for job in reconciled.jobs],
        }

    def sync_status(self, session_id: str, *, key_id: str | None, monitoring: bool = True) -> dict[str, Any]:
        payload = self.list_syncs(session_id, key_id=key_id)
        state = self._runtime_store.load()
        return {
            "daemon_running": True,
            "monitoring": monitoring,
            "count": payload["count"],
            "states": _state_counts(state),
            "syncs": payload["syncs"],
        }

    def _run_job(self, session_id: str, job: SyncRuntimeJob) -> tuple[SyncRuntimeJob, dict[str, Any]]:
        if job.mode != "push":
            updated = replace(
                job,
                status="blocked",
                last_error=f"unsupported_sync_mode: Sync mode '{job.mode}' is not supported yet.",
                updated_at=utc_now_iso(),
            )
            return updated, {
                "sync_id": job.sync_id,
                "status": updated.status,
                "changed": False,
                "reason": "unsupported_sync_mode",
                "message": updated.last_error,
            }
        if not job.enabled:
            updated = replace(
                job,
                status="disabled",
                updated_at=utc_now_iso(),
            )
            return updated, {
                "sync_id": job.sync_id,
                "status": updated.status,
                "changed": False,
            }
        return run_push_job(session_id, job, self._writable_files)

    def run_syncs(
        self,
        session_id: str,
        *,
        key_id: str | None,
        sync_id: str | None = None,
        run_all: bool = False,
        force: bool = True,
    ) -> dict[str, Any]:
        if not run_all and not (isinstance(sync_id, str) and sync_id.strip()):
            raise ValueError("invalid_input: sync-run requires a sync_id or --all.")
        self.list_syncs(session_id, key_id=key_id)
        state = self._runtime_store.load()
        target_sync_id = sync_id.strip() if isinstance(sync_id, str) else ""
        selected_jobs = [
            job
            for job in state.jobs
            if run_all or job.sync_id == target_sync_id
        ]
        if not selected_jobs:
            raise ValueError("record_not_found: Sync job not found for sync_id.")

        updated_jobs: list[SyncRuntimeJob] = []
        results: list[dict[str, Any]] = []
        selected_ids = {job.sync_id for job in selected_jobs}
        for job in state.jobs:
            if job.sync_id not in selected_ids:
                updated_jobs.append(job)
                continue
            if not force and not _poll_due(job.updated_at, job.poll_seconds):
                updated_jobs.append(job)
                results.append(
                    {
                        "sync_id": job.sync_id,
                        "status": job.status,
                        "changed": False,
                        "skipped": True,
                        "reason": "poll_interval_not_elapsed",
                    }
                )
                continue
            updated_job, result = self._run_job(session_id, job)
            if updated_job.archive_id and updated_job.archive_id != job.archive_id:
                self._persist_job_archive_binding(
                    session_id,
                    job=updated_job,
                )
            if updated_job.status in {"blocked", "error"}:
                updated_job = self._record_error_event_if_needed(
                    session_id,
                    job=updated_job,
                    reason=str(result.get("reason") or "sync_failed"),
                    message=str(result.get("message") or result.get("reason") or "sync_failed"),
                )
            updated_jobs.append(updated_job)
            results.append(result)

        updated_state = SyncRuntimeState(
            version=state.version,
            defaults=state.defaults,
            jobs=tuple(updated_jobs),
        )
        self._runtime_store.save(updated_state)
        return {
            "count": len(results),
            "results": results,
            "states": _state_counts(updated_state),
        }

    def add_sync(
        self,
        session_id: str,
        *,
        key_id: str | None,
        space_id: int,
        local_path: str,
        title: str | None = None,
        mime_type: str | None = None,
        archive_id: str | None = None,
        enabled: bool = True,
        poll_seconds: int = DEFAULT_SYNC_POLL_SECONDS,
        debounce_seconds: int = DEFAULT_SYNC_DEBOUNCE_SECONDS,
    ) -> dict[str, Any]:
        source_path = Path(local_path).expanduser().resolve(strict=False)
        if not source_path.exists() or not source_path.is_file():
            raise ValueError("invalid_input: local_path must point to an existing file.")
        space = self._get_space_summary(session_id, space_id)
        if not bool(space.get("writable")):
            raise ValueError("space_read_only: This agent cannot write sync configuration in the requested Space.")

        sync_job = SyncJobConfig(
            sync_id=self._generate_sync_id(),
            space_id=space_id,
            local_path=str(source_path),
            name=_normalize_title(str(source_path), title),
            mime_type=mime_type,
            archive_id=archive_id,
            mode="push",
            enabled=enabled,
            poll_seconds=poll_seconds,
            debounce_seconds=debounce_seconds,
        )

        manifests = self._load_manifests(session_id, key_id=(key_id or ""))
        target_note = self._find_reserved_config_note(session_id, space_id=space_id)
        target_manifest = SyncManifest(jobs=())
        if target_note is not None:
            target_manifest = self._parse_reserved_manifest_note(target_note)

        next_jobs = tuple([*target_manifest.jobs, sync_job])
        next_manifest = SyncManifest(jobs=next_jobs)
        all_manifests = [
            manifest
            for manifest in manifests
            if not manifest.jobs or manifest.jobs[0].space_id != space_id
        ]
        all_manifests.append(next_manifest)

        reconciled = reconcile_manifests(all_manifests, self._runtime_store.load())
        self._upsert_manifest(session_id, space_id=space_id, key_id=None, manifest=next_manifest)
        refreshed_job = next(job for job in reconciled.jobs if job.sync_id == sync_job.sync_id)
        self._runtime_store.save(reconciled)
        return {
            "ok": True,
            "sync": refreshed_job.to_json(),
        }

    def _set_sync_enabled(
        self,
        session_id: str,
        *,
        key_id: str | None,
        sync_id: str,
        enabled: bool,
    ) -> dict[str, Any]:
        self.list_syncs(session_id, key_id=key_id)
        state = self._runtime_store.load()
        target_job = next((job for job in state.jobs if job.sync_id == sync_id), None)
        if target_job is None:
            raise ValueError("record_not_found: Sync job not found for sync_id.")

        manifests = self._load_manifests(session_id, key_id=(key_id or ""))
        target_manifest = next(
            (
                manifest
                for manifest in manifests
                if any(job.sync_id == sync_id for job in manifest.jobs)
            ),
            None,
        )
        if target_manifest is None:
            raise ValueError("invalid_sync_config_note: Sync job is missing from the reserved sync config note.")

        next_manifest = SyncManifest(
            jobs=tuple(
                replace(job, enabled=enabled) if job.sync_id == sync_id else job
                for job in target_manifest.jobs
            ),
        )
        self._upsert_manifest(
            session_id,
            space_id=target_job.space_id,
            key_id=None,
            manifest=next_manifest,
        )

        updated_jobs: list[SyncRuntimeJob] = []
        updated_target = target_job
        for job in state.jobs:
            if job.sync_id != sync_id:
                updated_jobs.append(job)
                continue
            next_status = job.status
            if not enabled:
                next_status = "disabled"
            elif job.status == "disabled":
                next_status = "new"
            updated_target = replace(
                job,
                enabled=enabled,
                status=next_status,
                updated_at=utc_now_iso(),
            )
            updated_jobs.append(updated_target)

        self._runtime_store.save(
            SyncRuntimeState(
                version=state.version,
                defaults=state.defaults,
                jobs=tuple(updated_jobs),
            )
        )
        return {
            "ok": True,
            "enabled": enabled,
            "sync": updated_target.to_json(),
        }

    def enable_sync(
        self,
        session_id: str,
        *,
        key_id: str | None,
        sync_id: str,
    ) -> dict[str, Any]:
        return self._set_sync_enabled(
            session_id,
            key_id=key_id,
            sync_id=sync_id,
            enabled=True,
        )

    def disable_sync(
        self,
        session_id: str,
        *,
        key_id: str | None,
        sync_id: str,
    ) -> dict[str, Any]:
        return self._set_sync_enabled(
            session_id,
            key_id=key_id,
            sync_id=sync_id,
            enabled=False,
        )

    def remove_sync(
        self,
        session_id: str,
        *,
        key_id: str | None,
        sync_id: str,
        delete_remote: bool = False,
    ) -> dict[str, Any]:
        self.list_syncs(session_id, key_id=key_id)
        state = self._runtime_store.load()
        target_job = self._resolve_runtime_job(state, sync_id)

        manifests = self._load_manifests(session_id, key_id=(key_id or ""))
        target_manifest = next(
            (
                manifest
                for manifest in manifests
                if any(job.sync_id == target_job.sync_id for job in manifest.jobs)
            ),
            None,
        )
        if target_manifest is None:
            raise ValueError("invalid_sync_config_note: Sync job is missing from the reserved sync config note.")

        next_manifest = SyncManifest(
            jobs=tuple(job for job in target_manifest.jobs if job.sync_id != target_job.sync_id),
        )
        self._upsert_manifest(
            session_id,
            space_id=target_job.space_id,
            key_id=None,
            manifest=next_manifest,
        )

        deleted_remote = False
        if delete_remote and target_job.archive_id:
            self._writable_files.delete_file(session_id, archive_id=target_job.archive_id)
            deleted_remote = True

        next_state = SyncRuntimeState(
            version=state.version,
            defaults=state.defaults,
            jobs=tuple(job for job in state.jobs if job.sync_id != target_job.sync_id),
        )
        self._runtime_store.save(next_state)
        return {
            "ok": True,
            "removed": True,
            "deleted_remote": deleted_remote,
            "sync": target_job.to_json(),
        }

    def restore_sync(
        self,
        session_id: str,
        *,
        key_id: str | None,
        sync_id: str,
        output_path: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        self.list_syncs(session_id, key_id=key_id)
        state = self._runtime_store.load()
        target_job = self._resolve_runtime_job(state, sync_id)
        if not target_job.archive_id:
            raise ValueError("record_not_found: Sync job is not yet bound to a Cloud file.")

        destination = output_path if isinstance(output_path, str) and output_path.strip() else target_job.local_path_resolved
        try:
            result = self._readonly_files.download_file(
                session_id,
                archive_id=target_job.archive_id,
                output_path=destination,
                overwrite=overwrite,
            )
        except Exception as exc:
            self._append_error_event(
                session_id,
                space_id=target_job.space_id,
                sync_id=target_job.sync_id,
                archive_id=target_job.archive_id,
                reason="restore_failed",
                message=str(exc).strip() or "restore_failed",
            )
            raise

        resolved_destination = str(Path(result.get("output_path", destination)).expanduser().resolve(strict=False))
        watched_path = str(Path(target_job.local_path_resolved).expanduser().resolve(strict=False))
        if resolved_destination != watched_path:
            return {
                "ok": True,
                "sync": target_job.to_json(),
                "output_path": result.get("output_path"),
                "bytes_written": result.get("bytes_written"),
            }

        restored_digest = sha256_file(Path(watched_path))
        stat_result = Path(watched_path).stat()
        updated_jobs: list[SyncRuntimeJob] = []
        updated_target = target_job
        for job in state.jobs:
            if job.sync_id != sync_id:
                updated_jobs.append(job)
                continue
            updated_target = replace(
                job,
                status="synced",
                last_error=None,
                last_downloaded_at=utc_now_iso(),
                last_uploaded_sha256=restored_digest,
                last_remote_sha256=restored_digest,
                last_seen_size=stat_result.st_size,
                last_seen_mtime_ns=stat_result.st_mtime_ns,
                updated_at=utc_now_iso(),
            )
            updated_jobs.append(updated_target)
        self._runtime_store.save(
            SyncRuntimeState(
                version=state.version,
                defaults=state.defaults,
                jobs=tuple(updated_jobs),
            )
        )
        return {
            "ok": True,
            "sync": updated_target.to_json(),
            "output_path": result.get("output_path"),
            "bytes_written": result.get("bytes_written"),
        }
