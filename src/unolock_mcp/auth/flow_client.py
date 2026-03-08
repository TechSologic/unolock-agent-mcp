from __future__ import annotations

import uuid
import urllib.parse
from dataclasses import asdict
from typing import Any

from unolock_mcp.crypto.pq import PqSessionNegotiator
from unolock_mcp.domain.models import CallbackAction, FlowSession, PqExchangeRequest, UnoLockConfig
from unolock_mcp.transport.callback_codec import CallbackDtoCodec
from unolock_mcp.transport.http_client import HttpClient


class UnoLockFlowClient:
    def __init__(self, config: UnoLockConfig) -> None:
        self._config = config
        self._http = HttpClient(base_url=config.base_url, app_version=config.app_version)
        self._pq = PqSessionNegotiator(config.signing_public_key_b64)

    @property
    def http_client(self) -> HttpClient:
        return self._http

    def start(self, flow: str, args: str | None = None) -> FlowSession:
        params = {"type": flow}
        if args:
            params["args"] = args
        start_dto = self._http.get_json(f"/start?{urllib.parse.urlencode(params)}")
        _, start_action = CallbackDtoCodec.parse_dto(start_dto, session_key=None)
        if start_action.type != "PQ_KEY_EXCHANGE":
            raise RuntimeError(f"Unexpected start callback type: {start_action.type}")

        request = PqExchangeRequest(
            public_key_b64=start_action.request["pk"],
            signature_b64=start_action.request["sig"],
        )
        pq_result = self._pq.perform_exchange(request)

        reply_dto, nonce = CallbackDtoCodec.build_dto(
            state=start_dto["state"],
            callback_type="PQ_KEY_EXCHANGE",
            request={},
            result={"cipherText": pq_result.cipher_text_b64},
            session_key=None,
        )
        next_dto = self._http.post_json("/start", reply_dto)
        envelope, next_action = CallbackDtoCodec.parse_dto(next_dto, pq_result.shared_secret)
        return FlowSession(
            session_id=str(uuid.uuid4()),
            flow=flow,
            state=envelope.state,
            shared_secret=pq_result.shared_secret,
            current_callback=next_action,
            exp=envelope.exp,
            authorized=next_action.type == "SUCCESS",
            last_nonce=nonce,
        )

    def continue_flow(
        self,
        session: FlowSession,
        *,
        callback_type: str | None = None,
        request: Any | None = None,
        result: Any | None = None,
        reason: str | None = None,
        message: list[str] | None = None,
    ) -> FlowSession:
        action_type = callback_type or session.current_callback.type
        dto, nonce = CallbackDtoCodec.build_dto(
            state=session.state,
            callback_type=action_type,
            request=request,
            result=result,
            reason=reason,
            message=message,
            session_key=session.shared_secret,
        )
        response_dto = self._http.post_json("/start", dto)
        envelope, next_action = CallbackDtoCodec.parse_dto(response_dto, session.shared_secret)
        return FlowSession(
            session_id=session.session_id,
            flow=session.flow,
            state=envelope.state,
            shared_secret=session.shared_secret,
            current_callback=next_action,
            exp=envelope.exp,
            authorized=next_action.type == "SUCCESS",
            last_nonce=nonce,
        )

    def call_api(
        self,
        session: FlowSession,
        *,
        action: str,
        request: Any | None = None,
        result: Any | None = None,
        reason: str | None = None,
        message: list[str] | None = None,
    ) -> tuple[FlowSession, CallbackAction]:
        dto, nonce = CallbackDtoCodec.build_dto(
            state=session.state,
            callback_type=action,
            request=request,
            result=result,
            reason=reason,
            message=message,
            session_key=session.shared_secret,
        )
        response_dto = self._http.post_json("/api", dto)
        envelope, callback = CallbackDtoCodec.parse_dto(response_dto, session.shared_secret)
        updated_session = FlowSession(
            session_id=session.session_id,
            flow=session.flow,
            state=envelope.state,
            shared_secret=session.shared_secret,
            current_callback=callback,
            exp=envelope.exp,
            authorized=session.authorized,
            last_nonce=nonce,
        )
        return updated_session, callback

    @staticmethod
    def probe_summary(session: FlowSession, request: PqExchangeRequest) -> dict[str, Any]:
        return {
            "ok": True,
            "flow": session.flow,
            "start_callback_type": "PQ_KEY_EXCHANGE",
            "pq_request": asdict(request),
            "next_callback_type": session.current_callback.type,
            "next_action": session.current_callback.to_payload(),
            "session_id": session.session_id,
        }
