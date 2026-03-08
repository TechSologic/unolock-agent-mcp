from __future__ import annotations

import base64
import hashlib
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock

from unolock_mcp.auth.agent_auth import AgentAuthClient
from unolock_mcp.auth.registration_store import RegistrationStore
from unolock_mcp.domain.models import RegistrationState
from unolock_mcp.tpm.test_tpm import TestTpmDao


class AgentAuthClientTest(unittest.TestCase):
    def test_build_agent_pin_hash_matches_server_material(self) -> None:
        access_id = "access-123"
        challenge = "pin-challenge-456"
        pin = "2468"

        expected = base64.b64encode(
            hashlib.sha256(f"UnoLock:GetPin:{access_id}:{challenge}:{pin}".encode("utf8")).digest()
        ).decode("ascii")

        self.assertEqual(AgentAuthClient._build_agent_pin_hash(access_id, challenge, pin), expected)

    def test_test_tpm_uses_raw_p256_signature_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir))
            dao.create_key("agent-test")
            signature = dao.sign("agent-test", b"challenge")
            self.assertEqual(len(signature), 64)

    def test_runtime_status_includes_tpm_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir))
            client = AgentAuthClient(None, None, None, tpm_dao=dao)  # type: ignore[arg-type]
            status = client.runtime_status()
            self.assertIn("tpm_provider", status)
            self.assertIn("tpm_production_ready", status)
            self.assertIn("tpm_available", status)

    def test_tpm_diagnostics_has_advice_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir))
            client = AgentAuthClient(None, None, None, tpm_dao=dao)  # type: ignore[arg-type]
            diagnostics = client.tpm_diagnostics()
            self.assertEqual(diagnostics["provider_name"], "test")
            self.assertIn("summary", diagnostics)
            self.assertIn("advice", diagnostics)

    def test_authenticate_registered_agent_reports_provider_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir))
            store = Mock(spec=RegistrationStore)
            store.load.return_value = RegistrationState(
                registered=True,
                access_id="access-123",
                key_id="agent-access-123",
                tpm_provider="windows-tpm",
            )
            client = AgentAuthClient(Mock(), Mock(), store, tpm_dao=dao)
            result = client.authenticate_registered_agent()
            self.assertEqual(result["reason"], "tpm_provider_mismatch")
            self.assertEqual(result["stored_tpm_provider"], "windows-tpm")
            self.assertEqual(result["current_tpm_provider"], "test")


if __name__ == "__main__":
    unittest.main()
