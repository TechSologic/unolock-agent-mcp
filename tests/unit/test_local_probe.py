from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from unolock_mcp.domain.models import CallbackAction, FlowSession
from unolock_mcp.auth.local_probe import LocalServerProbe


class LocalServerProbeTest(unittest.TestCase):
    @patch("unolock_mcp.auth.local_probe.UnoLockFlowClient")
    @patch("unolock_mcp.transport.http_client.HttpClient")
    def test_run_fetches_start_dto_and_returns_probe_summary(self, http_cls, flow_client_cls) -> None:
        http_cls.return_value.get_json.return_value = {
            "state": "state-1",
            "u": {"type": "PQ_KEY_EXCHANGE", "request": {"pk": "public", "sig": "signature"}},
        }
        flow_client_cls.return_value.start.return_value = FlowSession(
            session_id="session-1",
            flow="access",
            state="state-2",
            shared_secret=b"secret",
            current_callback=CallbackAction(type="AgentChallenge", request={"challenge": "abc"}),
        )

        probe = LocalServerProbe(
            base_url="https://api.example.test",
            app_version="0.20.21",
            signing_public_key_b64="signing-key",
        )
        result = probe.run(flow="agentAccess")

        http_cls.return_value.get_json.assert_called_once_with("/start?type=agentAccess")
        flow_client_cls.return_value.start.assert_called_once_with(flow="agentAccess")
        self.assertTrue(result["ok"])
        self.assertEqual(result["start_callback_type"], "PQ_KEY_EXCHANGE")
        self.assertEqual(result["pq_request"]["public_key_b64"], "public")
        self.assertEqual(result["next_callback_type"], "AgentChallenge")
        self.assertNotIn("session_id", result)

    def test_to_json_formats_pretty_json(self) -> None:
        result = LocalServerProbe.to_json({"ok": True, "value": 1})

        self.assertEqual(json.loads(result), {"ok": True, "value": 1})
        self.assertIn("\n", result)


if __name__ == "__main__":
    unittest.main()
