from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


VALID_EVENT_LEVELS = frozenset({"error", "warn", "info"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


@dataclass(frozen=True)
class SyncEvent:
    event: str
    message: str
    level: str = "error"
    ts: str | None = None
    space_id: int | None = None
    sync_id: str | None = None
    reason: str | None = None
    archive_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event", _non_empty(self.event, "event"))
        object.__setattr__(self, "message", _non_empty(self.message, "message"))
        level = _non_empty(self.level, "level").lower()
        if level not in VALID_EVENT_LEVELS:
            raise ValueError(f"level must be one of: {', '.join(sorted(VALID_EVENT_LEVELS))}.")
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "ts", _non_empty(self.ts, "ts") if self.ts else _utc_now_iso())
        if self.space_id is not None:
            if int(self.space_id) <= 0:
                raise ValueError("space_id must be a positive integer.")
            object.__setattr__(self, "space_id", int(self.space_id))
        if self.sync_id is not None:
            object.__setattr__(self, "sync_id", _non_empty(self.sync_id, "sync_id"))
        if self.reason is not None:
            object.__setattr__(self, "reason", _non_empty(self.reason, "reason"))
        if self.archive_id is not None:
            object.__setattr__(self, "archive_id", _non_empty(self.archive_id, "archive_id"))

    def to_json(self) -> dict[str, Any]:
        payload = {
            "ts": self.ts,
            "level": self.level,
            "event": self.event,
            "message": self.message,
        }
        if self.space_id is not None:
            payload["space_id"] = self.space_id
        if self.sync_id is not None:
            payload["sync_id"] = self.sync_id
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.archive_id is not None:
            payload["archive_id"] = self.archive_id
        return payload

    def to_json_line(self) -> str:
        return json.dumps(self.to_json(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "SyncEvent":
        if not isinstance(raw, dict):
            raise ValueError("sync event must be a JSON object.")
        return cls(
            ts=str(raw.get("ts", "")) or None,
            level=str(raw.get("level") or "error"),
            event=str(raw.get("event", "")),
            message=str(raw.get("message", "")),
            space_id=int(raw["space_id"]) if raw.get("space_id") is not None else None,
            sync_id=str(raw["sync_id"]) if raw.get("sync_id") is not None else None,
            reason=str(raw["reason"]) if raw.get("reason") is not None else None,
            archive_id=str(raw["archive_id"]) if raw.get("archive_id") is not None else None,
        )
