from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from unolock_mcp.sync.runtime_store import SyncRuntimeJob


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _reason_from_exception(exc: Exception) -> str:
    raw_message = str(exc).strip()
    if ": " in raw_message:
        prefix, _ = raw_message.split(": ", 1)
        if prefix and prefix.replace("_", "").isalnum() and prefix == prefix.lower():
            return prefix
    return "operation_failed"


def run_push_job(session_id: str, job: SyncRuntimeJob, writable_files) -> tuple[SyncRuntimeJob, dict[str, Any]]:
    source_path = Path(job.local_path_resolved)
    if not source_path.exists() or not source_path.is_file():
        updated = replace(
            job,
            status="blocked",
            last_error="local_file_missing",
            updated_at=utc_now_iso(),
        )
        return updated, {
            "sync_id": job.sync_id,
            "status": updated.status,
            "changed": False,
            "reason": "local_file_missing",
        }

    stat_result = source_path.stat()
    local_digest = sha256_file(source_path)
    if local_digest == job.last_uploaded_sha256 and job.archive_id:
        updated = replace(
            job,
            status="synced",
            last_error=None,
            last_seen_size=stat_result.st_size,
            last_seen_mtime_ns=stat_result.st_mtime_ns,
            updated_at=utc_now_iso(),
        )
        return updated, {
            "sync_id": job.sync_id,
            "status": updated.status,
            "changed": False,
            "archive_id": job.archive_id,
        }

    try:
        if job.archive_id:
            result = writable_files.replace_file(
                session_id,
                archive_id=job.archive_id,
                local_path=job.local_path_resolved,
                name=job.name,
                mime_type=job.mime_type,
            )
        else:
            result = writable_files.upload_file(
                session_id,
                space_id=job.space_id,
                local_path=job.local_path_resolved,
                name=job.name,
                mime_type=job.mime_type,
            )
    except Exception as exc:
        reason = _reason_from_exception(exc)
        next_status = "blocked" if reason in {"space_read_only", "operation_not_allowed"} else "error"
        updated = replace(
            job,
            status=next_status,
            last_error=str(exc).strip() or reason,
            updated_at=utc_now_iso(),
            last_seen_size=stat_result.st_size,
            last_seen_mtime_ns=stat_result.st_mtime_ns,
        )
        return updated, {
            "sync_id": job.sync_id,
            "status": updated.status,
            "changed": False,
            "reason": reason,
            "message": updated.last_error,
        }

    file_payload = result.get("file") if isinstance(result, dict) else None
    archive_id = (
        str(file_payload.get("archive_id", "")).strip()
        if isinstance(file_payload, dict)
        else ""
    ) or job.archive_id
    updated = replace(
        job,
        archive_id=archive_id,
        status="synced",
        last_error=None,
        last_uploaded_at=utc_now_iso(),
        last_uploaded_sha256=local_digest,
        last_seen_size=stat_result.st_size,
        last_seen_mtime_ns=stat_result.st_mtime_ns,
        updated_at=utc_now_iso(),
    )
    return updated, {
        "sync_id": job.sync_id,
        "status": updated.status,
        "changed": True,
        "archive_id": archive_id,
    }
