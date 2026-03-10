from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unolock_mcp.auth.registration_store import RegistrationStore
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.domain.models import RegistrationState
from unolock_mcp.mcp.server import _registration_status_payload


class _FakeAgentAuth:
    def __init__(self, *, has_agent_pin: bool) -> None:
        self._has_agent_pin = has_agent_pin

    def runtime_status(self) -> dict[str, object]:
        return {
            "has_agent_pin": self._has_agent_pin,
            "pin_mode": "unset" if not self._has_agent_pin else "ephemeral_memory",
            "tpm_provider": "windows-tpm",
            "tpm_production_ready": True,
            "tpm_available": True,
            "registered_tpm_provider": "windows-tpm",
            "bootstrap_secret_available": False,
            "tpm_provider_mismatch": False,
            "tpm_provider_mismatch_detail": None,
        }

    def tpm_diagnostics(self) -> dict[str, object]:
        return {
            "provider_name": "windows-tpm",
            "provider_type": "hardware",
            "production_ready": True,
            "available": True,
            "summary": "Windows Platform Crypto Provider created a TPM-backed P-256 key.",
            "details": {},
            "advice": [],
        }


class RegistrationStatusPayloadTest(unittest.TestCase):
    def test_registered_agent_without_pin_requests_auth_or_pin_not_connection_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registration_store = RegistrationStore(Path(tmpdir) / "registration.json")
            registration_store.save(
                RegistrationState(
                    registered=True,
                    registration_mode="registered",
                    access_id="access-123",
                    key_id="agent-access-123",
                    tpm_provider="windows-tpm",
                )
            )

            payload = _registration_status_payload(
                registration_store,
                SessionStore(),
                _FakeAgentAuth(has_agent_pin=False),
            )

            self.assertEqual(payload["recommended_next_action"], "authenticate_or_set_pin")
            self.assertIn("agent PIN", payload["guidance"])
            self.assertFalse(payload["needs_connection_url"])

    def test_unregistered_agent_without_connection_url_requests_agent_key_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = _registration_status_payload(
                RegistrationStore(Path(tmpdir) / "registration.json"),
                SessionStore(),
                _FakeAgentAuth(has_agent_pin=False),
            )

            self.assertEqual(payload["recommended_next_action"], "ask_for_connection_url")
            self.assertIn("agent key connection URL", payload["guidance"])
            self.assertIn("one-time-use", payload["guidance"])
            self.assertIn("agent PIN", payload["guidance"])


if __name__ == "__main__":
    unittest.main()
