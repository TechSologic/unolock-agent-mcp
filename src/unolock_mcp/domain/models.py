from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


UNENCRYPTED_CALLBACK_TYPES = frozenset({"Captcha", "ECDHE", "PQ_KEY_EXCHANGE", "FAILED"})


@dataclass(frozen=True)
class UnoLockConfig:
    base_url: str
    app_version: str
    signing_public_key_b64: str


@dataclass(frozen=True)
class UnoLockResolvedConfig:
    base_url: str | None
    transparency_origin: str | None
    app_version: str | None
    signing_public_key_b64: str | None
    sources: dict[str, str]

    def is_complete(self) -> bool:
        return bool(self.base_url and self.app_version and self.signing_public_key_b64)


@dataclass(frozen=True)
class PqExchangeRequest:
    public_key_b64: str
    signature_b64: str


@dataclass(frozen=True)
class PqExchangeResult:
    cipher_text_b64: str
    shared_secret: bytes


@dataclass(frozen=True)
class CallbackEnvelope:
    state: str
    encrypted_action: str | None
    unencrypted_action: dict[str, Any] | None
    exp: int | None = None


@dataclass(frozen=True)
class CallbackAction:
    type: str
    message: list[str] = field(default_factory=list)
    reason: str = ""
    request: Any = field(default_factory=dict)
    result: Any = field(default_factory=dict)
    nonce: str | None = None
    time: int | None = None
    safe_exp: int | None = None

    @classmethod
    def from_payload(cls, callback_type: str, payload: dict[str, Any]) -> "CallbackAction":
        return cls(
            type=callback_type,
            message=list(payload.get("message", [])),
            reason=str(payload.get("reason", "")),
            request=payload.get("request", {}),
            result=payload.get("result", {}),
            nonce=payload.get("nonce"),
            time=payload.get("time"),
            safe_exp=payload.get("safeExp"),
        )

    def to_payload(self, *, include_type: bool = True) -> dict[str, Any]:
        payload = {
            "message": self.message,
            "reason": self.reason,
            "request": self.request,
            "result": self.result,
        }
        if self.nonce is not None:
            payload["nonce"] = self.nonce
        if self.time is not None:
            payload["time"] = self.time
        if self.safe_exp is not None:
            payload["safeExp"] = self.safe_exp
        if include_type:
            payload["type"] = self.type
        return payload

@dataclass
class FlowSession:
    session_id: str
    flow: str
    state: str
    shared_secret: bytes
    current_callback: CallbackAction
    exp: int | None = None
    authorized: bool = False
    last_nonce: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "flow": self.flow,
            "authorized": self.authorized,
            "exp": self.exp,
            "current_callback_type": self.current_callback.type,
            "current_callback": self.current_callback.to_payload(),
        }


@dataclass(frozen=True)
class ConnectionUrlInfo:
    raw_url: str
    flow: str | None
    args: str | None
    action: str | None = None
    access_id: str | None = None
    site_origin: str | None = None
    api_base_url: str | None = None
    passphrase: str | None = None
    key_name: str | None = None
    registration_code: str | None = None
    source: str = "unknown"

    def summary(self) -> dict[str, Any]:
        return {
            "flow": self.flow,
            "has_args": self.args is not None,
            "action": self.action,
            "access_id": self.access_id,
            "site_origin": self.site_origin,
            "api_base_url": self.api_base_url,
            "has_passphrase": self.passphrase is not None,
            "key_name": self.key_name,
            "has_registration_code": self.registration_code is not None,
            "source": self.source,
            "has_raw_url": bool(self.raw_url),
            "one_time_use": True,
        }


@dataclass
class RegistrationState:
    registered: bool = False
    registration_mode: str = "unconfigured"
    connection_url: ConnectionUrlInfo | None = None
    session_id: str | None = None
    registered_at: str | None = None
    access_id: str | None = None
    key_id: str | None = None
    bootstrap_secret: str | None = None
    tpm_provider: str | None = None
    api_base_url: str | None = None
    transparency_origin: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "registered": self.registered,
            "registration_mode": self.registration_mode,
            "needs_connection_url": not self.registered and self.connection_url is None,
            "has_connection_url": self.connection_url is not None,
            "access_id": self.access_id or (self.connection_url.access_id if self.connection_url else None),
            "key_id": self.key_id,
            "has_bootstrap_secret": bool(self.bootstrap_secret),
            "session_id": self.session_id,
            "registered_at": self.registered_at,
            "tpm_provider": self.tpm_provider,
            "api_base_url": self.api_base_url,
            "transparency_origin": self.transparency_origin,
            "connection_url": self.connection_url.summary() if self.connection_url else None,
            "agent_instruction": (
                "If registration is needed, ask the user for the one-time-use UnoLock agent key connection URL and "
                "pass it to unolock_submit_connection_url. The connection URL is for enrollment only and should not "
                "be treated as a reusable credential."
            ),
        }
