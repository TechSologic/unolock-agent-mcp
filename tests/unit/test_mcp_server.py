from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unolock_mcp.auth.registration_store import RegistrationStore
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.domain.models import RegistrationState

from unolock_mcp.mcp.server import _registration_status_payload, _tool_error_response


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
            "reduced_assurance_acknowledged": True,
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
            self.assertEqual(payload["registration_state"], "registered")
            self.assertNotIn("registration_mode", payload)
            self.assertIn("unolock_get_registration_status", payload["primary_tools"])
            self.assertIn("unolock_list_records", payload["primary_tools"])
            self.assertIn("unolock_list_files", payload["primary_tools"])
            self.assertEqual(payload["advanced_tools"], [])
            self.assertIn("unolock_append_note", payload["write_tools"])
            self.assertIn("unolock_upload_file", payload["write_tools"])
            self.assertIn("unolock://usage/about", payload["explanation_resources"])
            self.assertIn("unolock://usage/security-model", payload["explanation_resources"])
            self.assertIn("unolock://usage/updates", payload["explanation_resources"])

    def test_unregistered_agent_without_connection_url_requests_agent_key_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = _registration_status_payload(
                RegistrationStore(Path(tmpdir) / "registration.json"),
                SessionStore(),
                _FakeAgentAuth(has_agent_pin=False),
            )

            self.assertEqual(payload["recommended_next_action"], "ask_for_connection_url")
            self.assertIn("Agent Key URL", payload["guidance"])
            self.assertIn("safe.unolock.com", payload["guidance"])
            self.assertIn("agent PIN", payload["guidance"])
            self.assertEqual(payload["registration_state"], "waiting_for_connection_url")
            self.assertNotIn("registration_mode", payload)
            self.assertIn("Check registration status first.", payload["workflow_summary"])
            self.assertIn("unolock://usage/quickstart", payload["explanation_resources"])
            self.assertIn("Do not narrate raw internal MCP state names to the user.", payload["agent_behavior_rules"])

    def test_unacknowledged_reduced_assurance_changes_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = _FakeAgentAuth(has_agent_pin=False)
            auth.runtime_status = lambda: {
                "has_agent_pin": False,
                "pin_mode": "unset",
                "tpm_provider": "software",
                "tpm_production_ready": False,
                "tpm_available": False,
                "registered_tpm_provider": None,
                "bootstrap_secret_available": False,
                "tpm_provider_mismatch": False,
                "tpm_provider_mismatch_detail": None,
                "reduced_assurance_acknowledged": False,
                "security_warning": {"message": "reduced assurance"},
            }
            auth.tpm_diagnostics = lambda: {
                "provider_name": "software",
                "provider_type": "software",
                "production_ready": False,
                "available": False,
                "summary": "software fallback",
                "details": {},
                "advice": [],
            }

            payload = _registration_status_payload(
                RegistrationStore(Path(tmpdir) / "registration.json"),
                SessionStore(),
                auth,
            )

            self.assertEqual(payload["recommended_next_action"], "acknowledge_reduced_assurance")
            self.assertIn("unolock_bootstrap_agent", payload["primary_tools"])


class ToolErrorResponseTest(unittest.TestCase):
    def test_structured_space_read_only_error(self) -> None:
        payload = _tool_error_response(ValueError("space_read_only: This agent has read-only access."))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "space_read_only")
        self.assertIn("read-only access", payload["message"])
        self.assertIn("allowed_operations", payload["suggested_action"])

    def test_structured_conflict_error(self) -> None:
        payload = _tool_error_response(
            ValueError("write_conflict_requires_reread: Read the target record again and retry.")
        )
        self.assertEqual(payload["reason"], "write_conflict_requires_reread")
        self.assertIn("Reread", payload["suggested_action"])

    def test_generic_error_falls_back_to_operation_failed(self) -> None:
        payload = _tool_error_response(ValueError("unexpected failure"))
        self.assertEqual(payload["reason"], "operation_failed")
        self.assertEqual(payload["message"], "unexpected failure")


if __name__ == "__main__":
    unittest.main()
