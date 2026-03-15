from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from unolock_mcp.auth.flow_client import UnoLockFlowClient
from unolock_mcp.domain.models import CallbackAction, FlowSession, PqExchangeRequest, UnoLockConfig


class UnoLockFlowClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = UnoLockConfig(
            base_url="https://api.example.test",
            app_version="0.20.21",
            signing_public_key_b64="signing-key",
        )

    @patch("unolock_mcp.auth.flow_client.CallbackDtoCodec.build_dto")
    @patch("unolock_mcp.auth.flow_client.CallbackDtoCodec.parse_dto")
    @patch("unolock_mcp.auth.flow_client.PqSessionNegotiator")
    @patch("unolock_mcp.auth.flow_client.HttpClient")
    def test_start_performs_pq_exchange_and_returns_session(
        self,
        http_cls,
        pq_cls,
        parse_dto,
        build_dto,
    ) -> None:
        http = http_cls.return_value
        http.get_json.return_value = {"state": "state-1", "u": {"type": "PQ_KEY_EXCHANGE"}}
        http.post_json.return_value = {"state": "state-2", "u": {"type": "AgentRegistrationCode"}, "exp": 123}
        parse_dto.side_effect = [
            (
                SimpleNamespace(state="state-1", exp=None),
                CallbackAction(type="PQ_KEY_EXCHANGE", request={"pk": "public", "sig": "signature"}),
            ),
            (
                SimpleNamespace(state="state-2", exp=123),
                CallbackAction(type="AgentRegistrationCode", request={}, result={}),
            ),
        ]
        pq_cls.return_value.perform_exchange.return_value = SimpleNamespace(
            cipher_text_b64="ciphertext",
            shared_secret=b"shared-secret",
        )
        build_dto.return_value = ({"state": "state-1", "u": {"type": "PQ_KEY_EXCHANGE"}}, "nonce-1")

        client = UnoLockFlowClient(self.config)
        session = client.start("agentRegister", args='{"x":1}')

        http.get_json.assert_called_once_with("/start?type=agentRegister&args=%7B%22x%22%3A1%7D")
        pq_cls.return_value.perform_exchange.assert_called_once_with(
            PqExchangeRequest(public_key_b64="public", signature_b64="signature")
        )
        http.post_json.assert_called_once_with("/start", {"state": "state-1", "u": {"type": "PQ_KEY_EXCHANGE"}})
        self.assertEqual(session.flow, "agentRegister")
        self.assertEqual(session.state, "state-2")
        self.assertEqual(session.current_callback.type, "AgentRegistrationCode")
        self.assertEqual(session.last_nonce, "nonce-1")
        self.assertFalse(session.authorized)

    @patch("unolock_mcp.auth.flow_client.CallbackDtoCodec.parse_dto")
    @patch("unolock_mcp.auth.flow_client.PqSessionNegotiator")
    @patch("unolock_mcp.auth.flow_client.HttpClient")
    def test_start_rejects_non_pq_start_callback(self, http_cls, pq_cls, parse_dto) -> None:
        http_cls.return_value.get_json.return_value = {"state": "state-1", "u": {"type": "Captcha"}}
        parse_dto.return_value = (
            SimpleNamespace(state="state-1", exp=None),
            CallbackAction(type="Captcha", request={}, result={}),
        )

        client = UnoLockFlowClient(self.config)

        with self.assertRaisesRegex(RuntimeError, "Unexpected start callback type: Captcha"):
            client.start("access")

        pq_cls.return_value.perform_exchange.assert_not_called()

    @patch("unolock_mcp.auth.flow_client.CallbackDtoCodec.build_dto")
    @patch("unolock_mcp.auth.flow_client.CallbackDtoCodec.parse_dto")
    @patch("unolock_mcp.auth.flow_client.PqSessionNegotiator")
    @patch("unolock_mcp.auth.flow_client.HttpClient")
    def test_continue_flow_reuses_current_callback_type_when_omitted(
        self,
        http_cls,
        pq_cls,
        parse_dto,
        build_dto,
    ) -> None:
        build_dto.return_value = ({"state": "state-1", "e": "cipher"}, "nonce-2")
        parse_dto.return_value = (
            SimpleNamespace(state="state-2", exp=999),
            CallbackAction(type="GetPin", request={}, result={}),
        )
        session = FlowSession(
            session_id="session-1",
            flow="agentRegister",
            state="state-1",
            shared_secret=b"secret",
            current_callback=CallbackAction(type="AgentChallenge", request={}, result={}),
        )

        client = UnoLockFlowClient(self.config)
        updated = client.continue_flow(session, result={"ok": True})

        build_dto.assert_called_once_with(
            state="state-1",
            callback_type="AgentChallenge",
            request=None,
            result={"ok": True},
            reason=None,
            message=None,
            session_key=b"secret",
        )
        http_cls.return_value.post_json.assert_called_once_with("/start", {"state": "state-1", "e": "cipher"})
        self.assertEqual(updated.current_callback.type, "GetPin")
        self.assertEqual(updated.last_nonce, "nonce-2")
        self.assertEqual(updated.exp, 999)

    @patch("unolock_mcp.auth.flow_client.CallbackDtoCodec.build_dto")
    @patch("unolock_mcp.auth.flow_client.CallbackDtoCodec.parse_dto")
    @patch("unolock_mcp.auth.flow_client.PqSessionNegotiator")
    @patch("unolock_mcp.auth.flow_client.HttpClient")
    def test_call_api_returns_updated_session_and_callback(
        self,
        http_cls,
        pq_cls,
        parse_dto,
        build_dto,
    ) -> None:
        build_dto.return_value = ({"state": "state-1", "e": "cipher"}, "nonce-3")
        callback = CallbackAction(type="GetSpaces", result={"spaces": []})
        parse_dto.return_value = (SimpleNamespace(state="state-2", exp=777), callback)
        session = FlowSession(
            session_id="session-1",
            flow="agentAccess",
            state="state-1",
            shared_secret=b"secret",
            current_callback=CallbackAction(type="SUCCESS", request={}, result={}),
            authorized=True,
        )

        client = UnoLockFlowClient(self.config)
        updated_session, returned_callback = client.call_api(session, action="GetSpaces", request={"x": 1})

        http_cls.return_value.post_json.assert_called_once_with("/api", {"state": "state-1", "e": "cipher"})
        self.assertEqual(updated_session.state, "state-2")
        self.assertTrue(updated_session.authorized)
        self.assertEqual(updated_session.last_nonce, "nonce-3")
        self.assertIs(returned_callback, callback)

    def test_probe_summary_serializes_probe_shape(self) -> None:
        session = FlowSession(
            session_id="session-1",
            flow="access",
            state="state-1",
            shared_secret=b"secret",
            current_callback=CallbackAction(type="SUCCESS", result={"ok": True}),
        )

        summary = UnoLockFlowClient.probe_summary(
            session,
            PqExchangeRequest(public_key_b64="pk", signature_b64="sig"),
        )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["start_callback_type"], "PQ_KEY_EXCHANGE")
        self.assertEqual(summary["pq_request"]["public_key_b64"], "pk")
        self.assertEqual(summary["next_callback_type"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
