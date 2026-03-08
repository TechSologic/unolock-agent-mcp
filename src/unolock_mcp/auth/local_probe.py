from __future__ import annotations

import json
import urllib.parse
from dataclasses import asdict

from unolock_mcp.auth.flow_client import UnoLockFlowClient
from unolock_mcp.domain.models import PqExchangeRequest, UnoLockConfig


class LocalServerProbe:
    def __init__(self, base_url: str, app_version: str, signing_public_key_b64: str) -> None:
        self._config = UnoLockConfig(
            base_url=base_url,
            app_version=app_version,
            signing_public_key_b64=signing_public_key_b64,
        )
        self._flow_client = UnoLockFlowClient(self._config)

    def run(self, flow: str = "access") -> dict:
        from unolock_mcp.transport.http_client import HttpClient

        http = HttpClient(base_url=self._config.base_url, app_version=self._config.app_version)
        start_dto = http.get_json(f"/start?{urllib.parse.urlencode({'type': flow})}")
        start_action = start_dto["u"]
        request = PqExchangeRequest(
            public_key_b64=start_action["request"]["pk"],
            signature_b64=start_action["request"]["sig"],
        )
        session = self._flow_client.start(flow=flow)
        return {
            "ok": True,
            "flow": flow,
            "start_callback_type": "PQ_KEY_EXCHANGE",
            "pq_request": asdict(request),
            "next_callback_type": session.current_callback.type,
            "next_action": session.current_callback.to_payload(),
            "session_id": session.session_id,
        }

    @staticmethod
    def to_json(result: dict) -> str:
        return json.dumps(result, indent=2)
