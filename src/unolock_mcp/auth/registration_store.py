from __future__ import annotations

import base64
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from unolock_mcp.domain.models import ConnectionUrlInfo, RegistrationState


class RegistrationStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (Path.home() / ".config" / "unolock-agent-mcp" / "registration.json")

    def load(self) -> RegistrationState:
        if not self._path.exists():
            return RegistrationState()
        raw = json.loads(self._path.read_text(encoding="utf8"))
        connection_url_raw = raw.get("connection_url")
        connection_url = ConnectionUrlInfo(**connection_url_raw) if connection_url_raw else None
        return RegistrationState(
            registered=bool(raw.get("registered", False)),
            registration_mode=str(raw.get("registration_mode", "unconfigured")),
            connection_url=connection_url,
            session_id=raw.get("session_id"),
            registered_at=raw.get("registered_at"),
            access_id=raw.get("access_id"),
            key_id=raw.get("key_id"),
            bootstrap_secret=raw.get("bootstrap_secret"),
            tpm_provider=raw.get("tpm_provider"),
        )

    def save(self, state: RegistrationState) -> RegistrationState:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if state.connection_url is not None:
            state.connection_url = _sanitize_connection_info(state.connection_url)
        payload = asdict(state)
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf8")
        return state

    def set_connection_url(self, connection_url: str) -> RegistrationState:
        parsed = parse_connection_url(connection_url)
        sanitized = _sanitize_connection_info(parsed)
        state = RegistrationState(
            registered=False,
            registration_mode="pending_connection_url",
            connection_url=sanitized,
            session_id=None,
            registered_at=None,
            access_id=sanitized.access_id,
            key_id=None,
            bootstrap_secret=None,
            tpm_provider=None,
        )
        return self.save(state)

    def clear_connection_url(self) -> RegistrationState:
        current = self.load()
        state = RegistrationState(
            registered=current.registered,
            registration_mode="registered" if current.registered else "unconfigured",
            connection_url=None,
            session_id=current.session_id,
            registered_at=current.registered_at,
            access_id=current.access_id,
            key_id=current.key_id,
            bootstrap_secret=current.bootstrap_secret,
            tpm_provider=current.tpm_provider,
        )
        return self.save(state)

    def reset(self) -> RegistrationState:
        self._path.unlink(missing_ok=True)
        return RegistrationState()

    def mark_registered(
        self,
        *,
        session_id: str | None = None,
        access_id: str | None = None,
        key_id: str | None = None,
        bootstrap_secret: str | None = None,
        tpm_provider: str | None = None,
    ) -> RegistrationState:
        current = self.load()
        resolved_access_id = access_id or current.access_id or (current.connection_url.access_id if current.connection_url else None)
        state = RegistrationState(
            registered=True,
            registration_mode="registered",
            connection_url=None,
            session_id=session_id or current.session_id,
            registered_at=datetime.now(timezone.utc).isoformat(),
            access_id=resolved_access_id,
            key_id=key_id or current.key_id,
            bootstrap_secret=bootstrap_secret if bootstrap_secret is not None else current.bootstrap_secret,
            tpm_provider=tpm_provider or current.tpm_provider,
        )
        return self.save(state)


def parse_connection_url(connection_url: str) -> ConnectionUrlInfo:
    parsed = urlparse(connection_url.strip())
    query = parse_qs(parsed.query)
    if parsed.fragment:
        hash_info = _parse_hash_connection_url(connection_url, parsed.fragment)
        if hash_info:
            return hash_info

    flow = _first(query, "type")
    args = _first(query, "args")
    registration_code = _first(query, "registrationCode", "regCode", "code", "connectionCode")
    if flow or args or registration_code:
        return ConnectionUrlInfo(
            raw_url=connection_url,
            flow=flow,
            args=args,
            registration_code=registration_code,
            source="query",
        )

    return ConnectionUrlInfo(
        raw_url=connection_url,
        flow=None,
        args=None,
        source="raw",
    )


def _parse_hash_connection_url(connection_url: str, fragment: str) -> ConnectionUrlInfo | None:
    parts = [segment.strip() for segment in fragment.split("/") if segment.strip()]
    if not parts:
        return None
    if parts[0] in {"agent-register", "agent-access"}:
        action = parts[0]
        access_id = _decode_base64url(parts[1]) if len(parts) > 1 else None
        registration_code = _decode_base64url(parts[2]) if action == "agent-register" and len(parts) > 2 else None
        bootstrap_secret = _decode_base64url(parts[3]) if action == "agent-register" and len(parts) > 3 else None
        args = None
        if access_id and registration_code:
            args = json.dumps(
                {
                    "accessID": access_id,
                    "registrationCode": registration_code,
                    "connectionUrl": connection_url,
                }
            )
        return ConnectionUrlInfo(
            raw_url=connection_url,
            flow="agentRegister" if action == "agent-register" else "agentAccess",
            args=args,
            action=action,
            access_id=access_id,
            passphrase=bootstrap_secret,
            registration_code=registration_code,
            source="hash",
        )
    action = parts[0] if parts[0] in {"register", "access"} else None
    if not action:
        if parts[0] == "createFIDO2":
            args = parts[1] if len(parts) > 1 else ""
            return ConnectionUrlInfo(
                raw_url=connection_url,
                flow="createFIDO2",
                args=args,
                source="hash",
            )
        return None

    access_id = _decode_base64url(parts[1]) if len(parts) > 1 else None
    passphrase = _decode_base64url(parts[2]) if len(parts) > 2 else None
    key_name = _decode_base64url(parts[3]) if len(parts) > 3 else None
    return ConnectionUrlInfo(
        raw_url=connection_url,
        flow="agentRegister" if action == "register" else "agentAccess",
        args=None,
        action=action,
        access_id=access_id,
        passphrase=passphrase,
        key_name=key_name,
        source="hash",
    )


def _decode_base64url(value: str) -> str | None:
    if not value:
        return None
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        return base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf8")
    except Exception:
        return None


def _first(values: dict[str, list[str]], *keys: str) -> str | None:
    for key in keys:
        items = values.get(key)
        if items:
            return items[0]
    return None


def _sanitize_connection_info(info: ConnectionUrlInfo) -> ConnectionUrlInfo:
    sanitized_args = info.args
    if info.access_id and info.registration_code and info.flow == "agentRegister":
        sanitized_args = json.dumps(
            {
                "accessID": info.access_id,
                "registrationCode": info.registration_code,
            }
        )
    return ConnectionUrlInfo(
        raw_url="",
        flow=info.flow,
        args=sanitized_args,
        action=info.action,
        access_id=info.access_id,
        passphrase=None,
        key_name=info.key_name,
        registration_code=info.registration_code,
        source=info.source,
    )
