from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from unolock_mcp.config import default_state_dir
from unolock_mcp.sync.config_note import DEFAULT_SYNC_DEBOUNCE_SECONDS, DEFAULT_SYNC_POLL_SECONDS, SyncJobConfig


RUNTIME_STATE_VERSION = 1


def _chmod_if_supported(path: Path, mode: int) -> None:
    if os.name != "nt":
        path.chmod(mode)


@dataclass(frozen=True)
class SyncRuntimeJob:
    sync_id: str
    space_id: int
    archive_id: str | None
    local_path: str
    local_path_resolved: str
    name: str
    mime_type: str | None
    mode: str
    enabled: bool
    poll_seconds: int
    debounce_seconds: int
    created_at: str | None = None
    updated_at: str | None = None
    last_uploaded_at: str | None = None
    last_restored_at: str | None = None
    last_uploaded_sha256: str | None = None
    last_downloaded_at: str | None = None
    last_remote_revision: str | None = None
    last_remote_sha256: str | None = None
    last_seen_size: int | None = None
    last_seen_mtime_ns: int | None = None
    status: str = "new"
    last_error: str | None = None
    last_error_event_key: str | None = None
    last_error_event_at: str | None = None

    def __post_init__(self) -> None:
        config = SyncJobConfig(
            sync_id=self.sync_id,
            space_id=self.space_id,
            local_path=self.local_path,
            name=self.name,
            mime_type=self.mime_type,
            archive_id=self.archive_id,
            mode=self.mode,
            enabled=self.enabled,
            poll_seconds=self.poll_seconds,
            debounce_seconds=self.debounce_seconds,
        )
        object.__setattr__(self, "sync_id", config.sync_id)
        object.__setattr__(self, "space_id", config.space_id)
        object.__setattr__(self, "archive_id", config.archive_id)
        object.__setattr__(self, "local_path", config.local_path)
        object.__setattr__(self, "local_path_resolved", config.local_path)
        object.__setattr__(self, "name", config.name)
        object.__setattr__(self, "mime_type", config.mime_type)
        object.__setattr__(self, "mode", config.mode)
        object.__setattr__(self, "enabled", config.enabled)
        object.__setattr__(self, "poll_seconds", config.poll_seconds)
        object.__setattr__(self, "debounce_seconds", config.debounce_seconds)
        if self.last_seen_size is not None:
            if int(self.last_seen_size) < 0:
                raise ValueError("last_seen_size must be zero or greater.")
            object.__setattr__(self, "last_seen_size", int(self.last_seen_size))
        if self.last_seen_mtime_ns is not None:
            if int(self.last_seen_mtime_ns) < 0:
                raise ValueError("last_seen_mtime_ns must be zero or greater.")
            object.__setattr__(self, "last_seen_mtime_ns", int(self.last_seen_mtime_ns))

    @classmethod
    def from_config(cls, config: SyncJobConfig) -> "SyncRuntimeJob":
        return cls(
            sync_id=config.sync_id,
            space_id=config.space_id,
            archive_id=config.archive_id,
            local_path=config.local_path,
            local_path_resolved=config.local_path,
            name=config.name,
            mime_type=config.mime_type,
            mode=config.mode,
            enabled=config.enabled,
            poll_seconds=config.poll_seconds,
            debounce_seconds=config.debounce_seconds,
        )

    def to_json(self) -> dict[str, Any]:
        payload = {
            "sync_id": self.sync_id,
            "space_id": self.space_id,
            "local_path": self.local_path,
            "local_path_resolved": self.local_path_resolved,
            "name": self.name,
            "mode": self.mode,
            "enabled": self.enabled,
            "poll_seconds": self.poll_seconds,
            "debounce_seconds": self.debounce_seconds,
            "status": self.status,
        }
        optional_fields = {
            "archive_id": self.archive_id,
            "mime_type": self.mime_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_uploaded_at": self.last_uploaded_at,
            "last_restored_at": self.last_restored_at,
            "last_uploaded_sha256": self.last_uploaded_sha256,
            "last_downloaded_at": self.last_downloaded_at,
            "last_remote_revision": self.last_remote_revision,
            "last_remote_sha256": self.last_remote_sha256,
            "last_seen_size": self.last_seen_size,
            "last_seen_mtime_ns": self.last_seen_mtime_ns,
            "last_error": self.last_error,
            "last_error_event_key": self.last_error_event_key,
            "last_error_event_at": self.last_error_event_at,
        }
        for key, value in optional_fields.items():
            if value is not None:
                payload[key] = value
        return payload

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "SyncRuntimeJob":
        if not isinstance(raw, dict):
            raise ValueError("sync runtime job must be a JSON object.")
        local_path = str(raw.get("local_path_resolved") or raw.get("local_path") or "")
        return cls(
            sync_id=str(raw.get("sync_id", "")),
            space_id=int(raw.get("space_id") or 0),
            archive_id=str(raw["archive_id"]) if raw.get("archive_id") is not None else None,
            local_path=local_path,
            local_path_resolved=local_path,
            name=str(raw.get("name", "")),
            mime_type=str(raw["mime_type"]) if raw.get("mime_type") is not None else None,
            mode=str(raw.get("mode") or "push"),
            enabled=bool(raw.get("enabled", True)),
            poll_seconds=int(raw.get("poll_seconds") or DEFAULT_SYNC_POLL_SECONDS),
            debounce_seconds=int(raw.get("debounce_seconds") or DEFAULT_SYNC_DEBOUNCE_SECONDS),
            created_at=str(raw["created_at"]) if raw.get("created_at") is not None else None,
            updated_at=str(raw["updated_at"]) if raw.get("updated_at") is not None else None,
            last_uploaded_at=str(raw["last_uploaded_at"]) if raw.get("last_uploaded_at") is not None else None,
            last_restored_at=str(raw["last_restored_at"]) if raw.get("last_restored_at") is not None else None,
            last_uploaded_sha256=str(raw["last_uploaded_sha256"]) if raw.get("last_uploaded_sha256") is not None else None,
            last_downloaded_at=str(raw["last_downloaded_at"]) if raw.get("last_downloaded_at") is not None else None,
            last_remote_revision=str(raw["last_remote_revision"]) if raw.get("last_remote_revision") is not None else None,
            last_remote_sha256=str(raw["last_remote_sha256"]) if raw.get("last_remote_sha256") is not None else None,
            last_seen_size=int(raw["last_seen_size"]) if raw.get("last_seen_size") is not None else None,
            last_seen_mtime_ns=int(raw["last_seen_mtime_ns"]) if raw.get("last_seen_mtime_ns") is not None else None,
            status=str(raw.get("status") or "new"),
            last_error=str(raw["last_error"]) if raw.get("last_error") is not None else None,
            last_error_event_key=str(raw["last_error_event_key"]) if raw.get("last_error_event_key") is not None else None,
            last_error_event_at=str(raw["last_error_event_at"]) if raw.get("last_error_event_at") is not None else None,
        )


@dataclass(frozen=True)
class SyncRuntimeState:
    jobs: tuple[SyncRuntimeJob, ...] = ()
    version: int = RUNTIME_STATE_VERSION
    defaults: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if int(self.version) != RUNTIME_STATE_VERSION:
            raise ValueError(f"Unsupported sync runtime state version: {self.version}")
        object.__setattr__(self, "version", int(self.version))
        defaults = dict(self.defaults or {})
        defaults.setdefault("poll_seconds", DEFAULT_SYNC_POLL_SECONDS)
        defaults.setdefault("debounce_seconds", DEFAULT_SYNC_DEBOUNCE_SECONDS)
        object.__setattr__(self, "defaults", defaults)
        seen_sync_ids: set[str] = set()
        normalized_jobs: list[SyncRuntimeJob] = []
        for job in self.jobs:
            if not isinstance(job, SyncRuntimeJob):
                raise ValueError("jobs must contain SyncRuntimeJob values.")
            if job.sync_id in seen_sync_ids:
                raise ValueError(f"Duplicate sync_id in sync runtime state: {job.sync_id}")
            seen_sync_ids.add(job.sync_id)
            normalized_jobs.append(job)
        object.__setattr__(self, "jobs", tuple(normalized_jobs))

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "defaults": dict(self.defaults or {}),
            "jobs": [job.to_json() for job in self.jobs],
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "SyncRuntimeState":
        if not isinstance(raw, dict):
            raise ValueError("sync runtime state must be a JSON object.")
        jobs = raw.get("jobs") or []
        if not isinstance(jobs, list):
            raise ValueError("sync runtime jobs must be a JSON array.")
        return cls(
            version=int(raw.get("version") or RUNTIME_STATE_VERSION),
            defaults=dict(raw.get("defaults") or {}),
            jobs=tuple(SyncRuntimeJob.from_json(job) for job in jobs),
        )


class SyncRuntimeStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (default_state_dir() / "syncs.json")

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> SyncRuntimeState:
        if not self._path.exists():
            return SyncRuntimeState()
        raw = json.loads(self._path.read_text(encoding="utf8"))
        return SyncRuntimeState.from_json(raw)

    def save(self, state: SyncRuntimeState) -> SyncRuntimeState:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        _chmod_if_supported(self._path.parent, 0o700)
        temp_path = self._path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(state.to_json(), indent=2), encoding="utf8")
        _chmod_if_supported(temp_path, 0o600)
        temp_path.replace(self._path)
        _chmod_if_supported(self._path, 0o600)
        return state

    def reset(self) -> SyncRuntimeState:
        self._path.unlink(missing_ok=True)
        return SyncRuntimeState()
