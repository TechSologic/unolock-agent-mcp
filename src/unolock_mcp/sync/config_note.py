from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SYNC_SCHEMA_VERSION = 1
DEFAULT_SYNC_POLL_SECONDS = 60
DEFAULT_SYNC_DEBOUNCE_SECONDS = 10
VALID_SYNC_MODES = frozenset({"push", "pull", "bidirectional"})
SYNC_CONFIG_NOTE_TITLE = "@unolock-agent.sync-config"
SYNC_CONFIG_NOTE_PREFIX = f"{SYNC_CONFIG_NOTE_TITLE}:"
SYNC_EVENTS_NOTE_TITLE = "@unolock-agent.sync-events"
SYNC_EVENTS_NOTE_PREFIX = f"{SYNC_EVENTS_NOTE_TITLE}:"


def _require_non_empty_string(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


def _normalize_local_path(local_path: str) -> str:
    normalized = _require_non_empty_string(local_path, "local_path")
    return str(Path(normalized).expanduser().resolve(strict=False))


def _normalize_mode(mode: str | None) -> str:
    candidate = (mode or "push").strip().lower()
    if candidate not in VALID_SYNC_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(VALID_SYNC_MODES))}.")
    return candidate


def reserved_sync_config_note_title(key_id: str | None = None) -> str:
    return SYNC_CONFIG_NOTE_TITLE


def reserved_sync_events_note_title(key_id: str | None = None) -> str:
    return SYNC_EVENTS_NOTE_TITLE


def is_reserved_sync_config_note_title(title: str) -> bool:
    normalized = title.strip()
    return normalized == SYNC_CONFIG_NOTE_TITLE or normalized.startswith(SYNC_CONFIG_NOTE_PREFIX)


def is_reserved_sync_events_note_title(title: str) -> bool:
    normalized = title.strip()
    return normalized == SYNC_EVENTS_NOTE_TITLE or normalized.startswith(SYNC_EVENTS_NOTE_PREFIX)


@dataclass(frozen=True)
class SyncJobConfig:
    sync_id: str
    space_id: int
    local_path: str
    name: str
    mime_type: str | None = None
    archive_id: str | None = None
    mode: str = "push"
    enabled: bool = True
    poll_seconds: int = DEFAULT_SYNC_POLL_SECONDS
    debounce_seconds: int = DEFAULT_SYNC_DEBOUNCE_SECONDS

    def __post_init__(self) -> None:
        object.__setattr__(self, "sync_id", _require_non_empty_string(self.sync_id, "sync_id"))
        if int(self.space_id) <= 0:
            raise ValueError("space_id must be a positive integer.")
        object.__setattr__(self, "space_id", int(self.space_id))
        object.__setattr__(self, "local_path", _normalize_local_path(self.local_path))
        object.__setattr__(self, "name", _require_non_empty_string(self.name, "name"))
        object.__setattr__(self, "mode", _normalize_mode(self.mode))
        object.__setattr__(self, "enabled", bool(self.enabled))
        if int(self.poll_seconds) <= 0:
            raise ValueError("poll_seconds must be a positive integer.")
        object.__setattr__(self, "poll_seconds", int(self.poll_seconds))
        if int(self.debounce_seconds) < 0:
            raise ValueError("debounce_seconds must be zero or greater.")
        object.__setattr__(self, "debounce_seconds", int(self.debounce_seconds))
        if self.mime_type is not None:
            object.__setattr__(self, "mime_type", _require_non_empty_string(self.mime_type, "mime_type"))
        if self.archive_id is not None:
            object.__setattr__(self, "archive_id", _require_non_empty_string(self.archive_id, "archive_id"))

    def to_json(self) -> dict[str, Any]:
        payload = {
            "sync_id": self.sync_id,
            "space_id": self.space_id,
            "local_path": self.local_path,
            "name": self.name,
            "mode": self.mode,
            "enabled": self.enabled,
            "poll_seconds": self.poll_seconds,
            "debounce_seconds": self.debounce_seconds,
        }
        if self.mime_type is not None:
            payload["mime_type"] = self.mime_type
        if self.archive_id is not None:
            payload["archive_id"] = self.archive_id
        return payload

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "SyncJobConfig":
        if not isinstance(raw, dict):
            raise ValueError("sync job config must be a JSON object.")
        return cls(
            sync_id=str(raw.get("sync_id", "")),
            space_id=int(raw.get("space_id") or 0),
            local_path=str(raw.get("local_path", "")),
            name=str(raw.get("name", "")),
            mime_type=str(raw["mime_type"]) if raw.get("mime_type") is not None else None,
            archive_id=str(raw["archive_id"]) if raw.get("archive_id") is not None else None,
            mode=str(raw.get("mode") or "push"),
            enabled=bool(raw.get("enabled", True)),
            poll_seconds=int(raw.get("poll_seconds") or DEFAULT_SYNC_POLL_SECONDS),
            debounce_seconds=int(raw.get("debounce_seconds") or DEFAULT_SYNC_DEBOUNCE_SECONDS),
        )


@dataclass(frozen=True)
class SyncManifest:
    jobs: tuple[SyncJobConfig, ...]
    key_id: str | None = None
    schema_version: int = DEFAULT_SYNC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        normalized_key_id = None
        if self.key_id is not None:
            normalized_key_id = _require_non_empty_string(self.key_id, "key_id")
        object.__setattr__(self, "key_id", normalized_key_id)
        if int(self.schema_version) != DEFAULT_SYNC_SCHEMA_VERSION:
            raise ValueError(f"Unsupported sync schema_version: {self.schema_version}")
        object.__setattr__(self, "schema_version", int(self.schema_version))
        seen_sync_ids: set[str] = set()
        seen_local_paths: set[str] = set()
        normalized_jobs: list[SyncJobConfig] = []
        for job in self.jobs:
            if not isinstance(job, SyncJobConfig):
                raise ValueError("jobs must contain SyncJobConfig values.")
            if job.sync_id in seen_sync_ids:
                raise ValueError(f"Duplicate sync_id in sync manifest: {job.sync_id}")
            if job.local_path in seen_local_paths:
                raise ValueError(f"Duplicate local_path in sync manifest: {job.local_path}")
            seen_sync_ids.add(job.sync_id)
            seen_local_paths.add(job.local_path)
            normalized_jobs.append(job)
        object.__setattr__(self, "jobs", tuple(normalized_jobs))

    def to_json(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "jobs": [job.to_json() for job in self.jobs],
        }
        if self.key_id is not None:
            payload["key_id"] = self.key_id
        return payload

    def to_note_text(self) -> str:
        return json.dumps(self.to_json(), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "SyncManifest":
        if not isinstance(raw, dict):
            raise ValueError("sync manifest must be a JSON object.")
        jobs_raw = raw.get("jobs") or []
        if not isinstance(jobs_raw, list):
            raise ValueError("sync manifest jobs must be a JSON array.")
        return cls(
            schema_version=int(raw.get("schema_version") or DEFAULT_SYNC_SCHEMA_VERSION),
            key_id=str(raw["key_id"]) if raw.get("key_id") is not None else None,
            jobs=tuple(SyncJobConfig.from_json(job) for job in jobs_raw),
        )

    @classmethod
    def from_note_text(cls, note_text: str) -> "SyncManifest":
        try:
            payload = json.loads(note_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid sync note JSON: {exc}") from exc
        return cls.from_json(payload)
