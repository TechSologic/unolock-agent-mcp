from __future__ import annotations

import copy
import time
from dataclasses import replace

from unolock_mcp.domain.models import CallbackAction, FlowSession


class SessionStore:
    RECORDS_ARCHIVE_CACHE_TTL_SECONDS = 300

    def __init__(self) -> None:
        self._sessions: dict[str, FlowSession] = {}
        self._records_archive_snapshots: dict[str, dict[str, dict]] = {}

    def put(self, session: FlowSession) -> FlowSession:
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> FlowSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Unknown session_id: {session_id}") from exc

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._records_archive_snapshots.pop(session_id, None)

    def list(self) -> list[dict]:
        return [session.summary() for session in self._sessions.values()]

    def clear(self) -> None:
        self._sessions.clear()
        self._records_archive_snapshots.clear()

    def put_records_archive_snapshot(self, session_id: str, archive_id: str, snapshot: dict) -> None:
        archives = self._records_archive_snapshots.setdefault(session_id, {})
        stored = copy.deepcopy(snapshot)
        stored["cached_at"] = time.time()
        archives[archive_id] = stored

    def get_records_archive_snapshot(
        self,
        session_id: str,
        archive_id: str,
        *,
        max_age_seconds: int | None = None,
        now: float | None = None,
    ) -> dict:
        try:
            snapshot = self._records_archive_snapshots[session_id][archive_id]
        except KeyError as exc:
            raise KeyError(f"Unknown cached records archive for session_id={session_id} archive_id={archive_id}") from exc
        if max_age_seconds is not None:
            cached_at = snapshot.get("cached_at")
            current_time = time.time() if now is None else now
            if not isinstance(cached_at, (int, float)) or current_time - float(cached_at) > max_age_seconds:
                raise KeyError(f"Stale cached records archive for session_id={session_id} archive_id={archive_id}")
        return copy.deepcopy(snapshot)

    def update(
        self,
        session_id: str,
        *,
        state: str | None = None,
        current_callback: CallbackAction | None = None,
        exp: int | None = None,
        last_nonce: str | None = None,
        authorized: bool | None = None,
    ) -> FlowSession:
        session = self.get(session_id)
        updated = replace(
            session,
            state=session.state if state is None else state,
            current_callback=session.current_callback if current_callback is None else current_callback,
            exp=session.exp if exp is None else exp,
            last_nonce=session.last_nonce if last_nonce is None else last_nonce,
            authorized=session.authorized if authorized is None else authorized,
        )
        self._sessions[session_id] = updated
        return updated
