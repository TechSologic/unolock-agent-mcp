from __future__ import annotations

import base64
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from unolock_mcp.config import default_state_dir, derive_api_base_url
from unolock_mcp.domain.models import ConnectionUrlInfo, RegistrationState


class RegistrationStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (default_state_dir() / "registration.json")

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
            current_space_id=raw.get("current_space_id"),
            registered_at=raw.get("registered_at"),
            access_id=raw.get("access_id"),
            key_id=raw.get("key_id"),
            bootstrap_secret=raw.get("bootstrap_secret"),
            tpm_provider=raw.get("tpm_provider"),
            api_base_url=raw.get("api_base_url"),
            transparency_origin=raw.get("transparency_origin"),
            app_version=raw.get("app_version"),
            signing_public_key_b64=raw.get("signing_public_key_b64"),
        )

    def save(self, state: RegistrationState) -> RegistrationState:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if state.connection_url is not None:
            state.connection_url = _sanitize_connection_info(state.connection_url)
        payload = asdict(state)
        payload["bootstrap_secret"] = None
        payload["access_id"] = None
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf8")
        if os.name != "nt":
            self._path.chmod(0o600)
        return state

    def set_connection_url(self, connection_url: str) -> RegistrationState:
        current = self.load()
        parsed = parse_connection_url(connection_url)
        sanitized = _sanitize_connection_info(parsed)
        state = RegistrationState(
            registered=False,
            registration_mode="pending_connection_url",
            connection_url=sanitized,
            current_space_id=None,
            registered_at=None,
            access_id=None,
            key_id=None,
            bootstrap_secret=None,
            tpm_provider=None,
            api_base_url=sanitized.api_base_url or current.api_base_url,
            transparency_origin=sanitized.site_origin or current.transparency_origin,
            app_version=current.app_version,
            signing_public_key_b64=current.signing_public_key_b64,
        )
        return self.save(state)

    def clear_connection_url(self) -> RegistrationState:
        current = self.load()
        state = RegistrationState(
            registered=current.registered,
            registration_mode="registered" if current.registered else "unconfigured",
            connection_url=None,
            current_space_id=current.current_space_id,
            registered_at=current.registered_at,
            access_id=None,
            key_id=current.key_id,
            bootstrap_secret=current.bootstrap_secret,
            tpm_provider=current.tpm_provider,
            api_base_url=current.api_base_url,
            transparency_origin=current.transparency_origin,
            app_version=current.app_version,
            signing_public_key_b64=current.signing_public_key_b64,
        )
        return self.save(state)

    def reset(self) -> RegistrationState:
        self._path.unlink(missing_ok=True)
        return RegistrationState()

    def mark_registered(
        self,
        *,
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
            current_space_id=current.current_space_id,
            registered_at=datetime.now(timezone.utc).isoformat(),
            access_id=None,
            key_id=key_id or current.key_id,
            bootstrap_secret=bootstrap_secret if bootstrap_secret is not None else current.bootstrap_secret,
            tpm_provider=tpm_provider or current.tpm_provider,
            api_base_url=current.api_base_url or (current.connection_url.api_base_url if current.connection_url else None),
            transparency_origin=current.transparency_origin or (current.connection_url.site_origin if current.connection_url else None),
            app_version=current.app_version,
            signing_public_key_b64=current.signing_public_key_b64,
        )
        return self.save(state)

    def update_runtime_config(
        self,
        *,
        base_url: str | None = None,
        transparency_origin: str | None = None,
        app_version: str | None = None,
        signing_public_key_b64: str | None = None,
    ) -> RegistrationState:
        current = self.load()
        state = RegistrationState(
            registered=current.registered,
            registration_mode=current.registration_mode,
            connection_url=current.connection_url,
            current_space_id=current.current_space_id,
            registered_at=current.registered_at,
            access_id=current.access_id,
            key_id=current.key_id,
            bootstrap_secret=current.bootstrap_secret,
            tpm_provider=current.tpm_provider,
            api_base_url=base_url or current.api_base_url,
            transparency_origin=transparency_origin or current.transparency_origin,
            app_version=app_version or current.app_version,
            signing_public_key_b64=signing_public_key_b64 or current.signing_public_key_b64,
        )
        return self.save(state)

    def set_current_space(self, current_space_id: int | None) -> RegistrationState:
        current = self.load()
        state = RegistrationState(
            registered=current.registered,
            registration_mode=current.registration_mode,
            connection_url=current.connection_url,
            current_space_id=current_space_id,
            registered_at=current.registered_at,
            access_id=current.access_id,
            key_id=current.key_id,
            bootstrap_secret=current.bootstrap_secret,
            tpm_provider=current.tpm_provider,
            api_base_url=current.api_base_url,
            transparency_origin=current.transparency_origin,
            app_version=current.app_version,
            signing_public_key_b64=current.signing_public_key_b64,
        )
        return self.save(state)


def parse_connection_url(connection_url: str) -> ConnectionUrlInfo:
    parsed = urlparse(connection_url.strip())
    site_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else None
    api_base_url = derive_api_base_url(site_origin)
    query = parse_qs(parsed.query)
    if parsed.fragment:
        hash_info = _parse_hash_connection_url(connection_url, parsed.fragment)
        if hash_info:
            merged = asdict_without_raw(hash_info)
            merged["site_origin"] = hash_info.site_origin or site_origin
            merged["api_base_url"] = hash_info.api_base_url or api_base_url
            return ConnectionUrlInfo(raw_url=connection_url, **merged)

    flow = _first(query, "type")
    args = _first(query, "args")
    registration_code = _first(query, "registrationCode", "regCode", "code", "connectionCode")
    if flow or args or registration_code:
        return ConnectionUrlInfo(
            raw_url=connection_url,
            flow=flow,
            args=args,
            site_origin=site_origin,
            api_base_url=api_base_url,
            registration_code=registration_code,
            source="query",
        )

    return ConnectionUrlInfo(
        raw_url=connection_url,
        flow=None,
        args=None,
        site_origin=site_origin,
        api_base_url=api_base_url,
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
            site_origin=None,
            api_base_url=None,
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
                site_origin=None,
                api_base_url=None,
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
        site_origin=None,
        api_base_url=None,
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
    return ConnectionUrlInfo(
        raw_url="",
        flow=info.flow,
        args=None,
        action=info.action,
        access_id=None,
        site_origin=info.site_origin,
        api_base_url=info.api_base_url,
        passphrase=None,
        key_name=info.key_name,
        registration_code=None,
        source=info.source,
    )


def asdict_without_raw(info: ConnectionUrlInfo) -> dict[str, Any]:
    return {
        "flow": info.flow,
        "args": info.args,
        "action": info.action,
        "access_id": info.access_id,
        "site_origin": info.site_origin,
        "api_base_url": info.api_base_url,
        "passphrase": info.passphrase,
        "key_name": info.key_name,
        "registration_code": info.registration_code,
        "source": info.source,
    }
