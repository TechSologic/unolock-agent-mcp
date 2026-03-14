from __future__ import annotations

import base64
import json
import hashlib
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock

from unolock_mcp.auth.agent_auth import AgentAuthClient
from unolock_mcp.auth.registration_store import RegistrationStore
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.domain.models import CallbackAction, FlowSession, RegistrationState
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

    def test_flow_session_summary_does_not_require_tpm_provider(self) -> None:
        session = FlowSession(
            session_id="session-1",
            flow="agentAccess",
            state="state",
            shared_secret=b"secret",
            current_callback=CallbackAction(type="GetPin"),
        )

        summary = session.summary()

        self.assertEqual(summary["session_id"], "session-1")
        self.assertEqual(summary["current_callback_type"], "GetPin")

    def test_tpm_diagnostics_has_advice_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir))
            client = AgentAuthClient(None, None, None, tpm_dao=dao)  # type: ignore[arg-type]
            diagnostics = client.tpm_diagnostics()
            self.assertEqual(diagnostics["provider_name"], "software")
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
            client.acknowledge_reduced_assurance()
            result = client.authenticate_registered_agent()
            self.assertEqual(result["reason"], "tpm_provider_mismatch")
            self.assertEqual(result["stored_tpm_provider"], "windows-tpm")
            self.assertEqual(result["current_tpm_provider"], "software")

    def test_authenticate_registered_agent_reports_insecure_provider_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir))
            store = Mock(spec=RegistrationStore)
            store.load.return_value = RegistrationState(
                registered=True,
                access_id="access-123",
                key_id="agent-access-123",
                tpm_provider="software",
            )
            client = AgentAuthClient(Mock(), Mock(), store, tpm_dao=dao)
            result = client.authenticate_registered_agent()
            self.assertEqual(result["reason"], "reduced_assurance_acknowledgement_required")

    def test_acknowledge_reduced_assurance_unblocks_software_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir))
            store = Mock(spec=RegistrationStore)
            store.load.return_value = RegistrationState(
                registered=True,
                access_id="access-123",
                key_id="agent-access-123",
                tpm_provider="software",
            )
            flow_client = Mock()
            flow_client.start.return_value = FlowSession(
                session_id="session-1",
                flow="agentAccess",
                state="state",
                shared_secret=b"secret",
                current_callback=CallbackAction(type="FAILED"),
            )
            session_store = SessionStore()
            client = AgentAuthClient(flow_client, session_store, store, tpm_dao=dao)

            client.acknowledge_reduced_assurance()
            result = client.authenticate_registered_agent()

            self.assertFalse(result["ok"])
            self.assertFalse(result["completed"])
            self.assertFalse(result["authorized"])
            flow_client.start.assert_called_once()
            self.assertEqual(flow_client.start.call_args.kwargs, {"flow": "agentAccess"})

    def test_load_registration_restores_bootstrap_secret_from_provider_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir))
            dao.store_secret("bootstrap-access-123", b"pp:bootstrap")
            store = Mock(spec=RegistrationStore)
            store.load.return_value = RegistrationState(
                registered=True,
                access_id="access-123",
                key_id="agent-access-123",
                tpm_provider="software",
            )
            client = AgentAuthClient(Mock(), Mock(), store, tpm_dao=dao)

            registration = client._load_registration()
            self.assertEqual(registration.bootstrap_secret, "pp:bootstrap")

    def test_submit_connection_url_stores_bootstrap_secret_only_in_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir))
            store = RegistrationStore(Path(tmpdir) / "registration.json")
            client = AgentAuthClient(Mock(), Mock(), store, tpm_dao=dao)

            summary = client.submit_connection_url(
                "http://localhost:4200/#/agent-register/"
                "YWNjZXNzLTEyMw/Y29kZS0xMjM/cHA6Ym9vdHN0cmFw"
            )

            self.assertFalse(summary["has_bootstrap_secret"])
            self.assertNotIn("access_id", summary)
            self.assertEqual(dao.load_secret("bootstrap-access-123"), b"pp:bootstrap")
            self.assertEqual(
                json.loads(dao.load_secret("registration-material").decode("utf8")),
                {"access_id": "access-123", "registration_code": "code-123"},
            )
            self.assertEqual(summary["security_warning"]["reason"], "insecure_tpm_provider")

    def test_submit_connection_url_replaces_previous_local_registration_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir) / "tpm")
            dao.create_key("agent-old-access")
            dao.store_secret("bootstrap-old-access", b"pp:old-bootstrap")
            dao.store_secret("aidk-old-access", b"old-aidk")
            dao.store_secret("registered-access-id", b"old-access")
            dao.store_secret(
                "registration-material",
                json.dumps({"access_id": "old-access", "registration_code": "old-code"}).encode("utf8"),
            )
            store = RegistrationStore(Path(tmpdir) / "registration.json")
            store.save(
                RegistrationState(
                    registered=True,
                    registration_mode="registered",
                    access_id="old-access",
                    key_id="agent-old-access",
                    tpm_provider="software",
                )
            )
            session_store = SessionStore()
            session_store.put(
                FlowSession(
                    session_id="session-1",
                    flow="agentAccess",
                    state="state",
                    shared_secret=b"secret",
                    current_callback=CallbackAction(type="GetPin"),
                )
            )
            client = AgentAuthClient(Mock(), session_store, store, tpm_dao=dao)
            client.set_agent_pin("1111")

            summary = client.submit_connection_url(
                "http://localhost:4200/#/agent-register/"
                "bmV3LWFjY2Vzcw/bmV3LWNvZGU/cHA6bmV3LWJvb3RzdHJhcA"
            )

            self.assertTrue(summary["has_connection_url"])
            self.assertEqual(store.load().registration_mode, "pending_connection_url")
            self.assertIsNone(dao.load_secret("registered-access-id"))
            self.assertIsNone(dao.load_secret("bootstrap-old-access"))
            self.assertIsNone(dao.load_secret("aidk-old-access"))
            self.assertEqual(
                json.loads(dao.load_secret("registration-material").decode("utf8")),
                {"access_id": "new-access", "registration_code": "new-code"},
            )
            with self.assertRaises(KeyError):
                dao.get_public_key("agent-old-access")
            self.assertEqual(session_store.list(), [])
            self.assertFalse(client.runtime_status()["has_agent_pin"])

    def test_submit_connection_url_rejects_regular_register_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir))
            store = RegistrationStore(Path(tmpdir) / "registration.json")
            client = AgentAuthClient(Mock(), Mock(), store, tpm_dao=dao)

            result = client.submit_connection_url(
                "http://localhost:4200/#/register/"
                "YWNjZXNzLTEyMw/Y29kZS0xMjM"
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "wrong_connection_url_type")
            self.assertIn("regular key registration URL", result["message"])

    def test_disconnect_removes_local_registration_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir) / "tpm")
            dao.create_key("agent-access-123")
            dao.store_secret("bootstrap-access-123", b"pp:bootstrap")
            dao.store_secret("aidk-access-123", b"a" * 32)
            store = RegistrationStore(Path(tmpdir) / "registration.json")
            store.save(
                RegistrationState(
                    registered=True,
                    registration_mode="registered",
                    access_id="access-123",
                    key_id="agent-access-123",
                    tpm_provider="software",
                )
            )
            session_store = SessionStore()
            session_store.put(
                FlowSession(
                    session_id="session-1",
                    flow="agentAccess",
                    state="state",
                    shared_secret=b"secret",
                    current_callback=CallbackAction(type="GetPin"),
                )
            )
            client = AgentAuthClient(Mock(), session_store, store, tpm_dao=dao)
            client.set_agent_pin("1")

            result = client.disconnect()

            self.assertTrue(result["ok"])
            self.assertTrue(result["disconnected"])
            self.assertIsNone(dao.load_secret("bootstrap-access-123"))
            self.assertIsNone(dao.load_secret("aidk-access-123"))
            with self.assertRaises(KeyError):
                dao.get_public_key("agent-access-123")
            self.assertEqual(store.load().registration_mode, "unconfigured")
            self.assertFalse(store.load().registered)
            self.assertEqual(session_store.list(), [])
            self.assertFalse(client.runtime_status()["has_agent_pin"])

    def test_software_mode_stores_aidk_via_provider_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dao = TestTpmDao(Path(tmpdir))
            client = AgentAuthClient(None, None, None, tpm_dao=dao)  # type: ignore[arg-type]
            client.set_agent_pin("1234")

            aidk = client._load_or_create_agent_aidk("access-123")
            stored = dao.load_secret("aidk-access-123")

            self.assertIsNotNone(stored)
            self.assertEqual(stored, aidk)


if __name__ == "__main__":
    unittest.main()
