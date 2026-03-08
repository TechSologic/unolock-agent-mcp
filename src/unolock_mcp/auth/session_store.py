from __future__ import annotations

from dataclasses import replace

from unolock_mcp.domain.models import CallbackAction, FlowSession


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, FlowSession] = {}

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

    def list(self) -> list[dict]:
        return [session.summary() for session in self._sessions.values()]

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
