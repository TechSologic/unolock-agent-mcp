from __future__ import annotations

import secrets
import time
from typing import Any

from unolock_mcp.crypto.callback_crypto import CallbackCrypto
from unolock_mcp.domain.models import (
    UNENCRYPTED_CALLBACK_TYPES,
    CallbackAction,
    CallbackEnvelope,
)


class CallbackDtoCodec:
    _NONE_REASON_TYPES = frozenset(
        {
            "AgentRegistrationCode",
            "AgentKeyRegistration",
            "AgentChallenge",
            "AgentWrappedKeys",
            "DecodeKey",
            "GetPin",
            "GetSafeAccessID",
            "SafeConfig",
        }
    )

    @staticmethod
    def parse_dto(dto: dict[str, Any], session_key: bytes | None) -> tuple[CallbackEnvelope, CallbackAction]:
        envelope = CallbackEnvelope(
            state=dto["state"],
            encrypted_action=dto.get("e"),
            unencrypted_action=dto.get("u"),
            exp=dto.get("exp"),
        )

        if envelope.encrypted_action and envelope.unencrypted_action:
            raise ValueError("Invalid callback DTO: both encrypted and unencrypted actions are set")

        if envelope.unencrypted_action is not None:
            callback_type = envelope.unencrypted_action.get("type")
            if callback_type not in UNENCRYPTED_CALLBACK_TYPES:
                raise ValueError(f"Unexpected unencrypted callback type: {callback_type}")
            action = CallbackAction.from_payload(callback_type, envelope.unencrypted_action)
            return envelope, action

        if envelope.encrypted_action is None:
            raise ValueError("Invalid callback DTO: missing action payload")
        if session_key is None:
            raise ValueError("Encrypted callback DTO requires a negotiated session key")

        decrypted_payload = CallbackCrypto.decrypt_g2_json(envelope.encrypted_action, session_key)
        callback_type = decrypted_payload.pop("type")
        action = CallbackAction.from_payload(callback_type, decrypted_payload)
        return envelope, action

    @staticmethod
    def build_dto(
        *,
        state: str,
        callback_type: str,
        request: Any | None = None,
        result: Any | None = None,
        message: list[str] | None = None,
        reason: str | None = None,
        session_key: bytes | None,
        nonce: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        resolved_nonce = nonce or secrets.token_urlsafe(16)
        action = CallbackAction(
            type=callback_type,
            message=message or [],
            reason=CallbackDtoCodec.default_reason(callback_type, reason),
            request={} if request is None else request,
            result={} if result is None else result,
            nonce=resolved_nonce,
            time=int(time.time()),
        )
        payload = action.to_payload()
        dto: dict[str, Any] = {"state": state}

        if callback_type in UNENCRYPTED_CALLBACK_TYPES:
            dto["u"] = payload
            return dto, resolved_nonce

        if session_key is None:
            raise ValueError("Encrypted callback DTO requires a negotiated session key")
        dto["e"] = CallbackCrypto.encrypt_g2_json(payload, session_key)
        return dto, resolved_nonce

    @staticmethod
    def default_reason(callback_type: str, explicit_reason: str | None = None) -> str:
        if explicit_reason is not None:
            return explicit_reason
        if callback_type in CallbackDtoCodec._NONE_REASON_TYPES:
            return "NONE"
        return ""
