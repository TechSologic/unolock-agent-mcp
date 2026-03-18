from __future__ import annotations

import copy
import time
from dataclasses import replace

from unolock_mcp.domain.models import CallbackAction, FlowSession


class SessionStore:
    ACTIVE_SESSION_ID = "active"
    RECORDS_ARCHIVE_CACHE_TTL_SECONDS = 300

    def __init__(self) -> None:
        self._active_session: FlowSession | None = None
        self._records_archive_snapshots: dict[str, dict] = {}
        self._auth_context: dict | None = None

    def put(self, session: FlowSession) -> FlowSession:
        stored = replace(session, session_id=self.ACTIVE_SESSION_ID)
        self._active_session = stored
        if stored.authorized and stored.current_callback.type == "SUCCESS" and isinstance(stored.current_callback.result, dict):
            self._auth_context = copy.deepcopy(stored.current_callback.result)
        return stored

    def get(self) -> FlowSession:
        if self._active_session is None:
            raise KeyError("No active flow is available")
        return self._active_session

    def delete(self) -> None:
        self._active_session = None
        self._records_archive_snapshots.clear()
        self._auth_context = None

    def list(self) -> list[dict]:
        if self._active_session is None:
            return []
        return [self._active_session.summary()]

    def clear(self) -> None:
        self._active_session = None
        self._records_archive_snapshots.clear()
        self._auth_context = None

    def has_active_flow(self, *, authorized: bool | None = None, incomplete_only: bool = False) -> bool:
        session = self._active_session
        if session is None:
            return False
        if authorized is not None and session.authorized is not authorized:
            return False
        if incomplete_only and session.current_callback.type in {"SUCCESS", "FAILED"}:
            return False
        return True

    def get_auth_context(self) -> dict:
        if self._auth_context is None:
            raise KeyError("No active auth context is available")
        return copy.deepcopy(self._auth_context)

    def put_records_archive_snapshot(self, archive_id: str, snapshot: dict) -> None:
        stored = copy.deepcopy(snapshot)
        stored["cached_at"] = time.time()
        self._records_archive_snapshots[archive_id] = stored

    def get_records_archive_snapshot(
        self,
        archive_id: str,
        *,
        max_age_seconds: int | None = None,
        now: float | None = None,
    ) -> dict:
        try:
            snapshot = self._records_archive_snapshots[archive_id]
        except KeyError as exc:
            raise KeyError(f"Unknown cached records archive for archive_id={archive_id}") from exc
        if max_age_seconds is not None:
            cached_at = snapshot.get("cached_at")
            current_time = time.time() if now is None else now
            if not isinstance(cached_at, (int, float)) or current_time - float(cached_at) > max_age_seconds:
                raise KeyError(f"Stale cached records archive for archive_id={archive_id}")
        return copy.deepcopy(snapshot)

    def update(
        self,
        *,
        state: str | None = None,
        current_callback: CallbackAction | None = None,
        exp: int | None = None,
        last_nonce: str | None = None,
        authorized: bool | None = None,
    ) -> FlowSession:
        session = self.get()
        updated = replace(
            session,
            state=session.state if state is None else state,
            current_callback=session.current_callback if current_callback is None else current_callback,
            exp=session.exp if exp is None else exp,
            last_nonce=session.last_nonce if last_nonce is None else last_nonce,
            authorized=session.authorized if authorized is None else authorized,
        )
        return self.put(updated)
