from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from unolock_mcp.auth.registration_store import RegistrationStore, parse_connection_url
from unolock_mcp.domain.models import RegistrationState


def _b64url(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf8")).decode("ascii").rstrip("=")


class RegistrationStoreTest(unittest.TestCase):
    def test_parse_agent_register_hash_url(self) -> None:
        access_id = "agent-access"
        registration_code = "reg-code"
        bootstrap_secret = "bootstrap"
        url = (
            f"http://localhost:4200/#/agent-register/"
            f"{_b64url(access_id)}/{_b64url(registration_code)}/{_b64url(bootstrap_secret)}"
        )

        parsed = parse_connection_url(url)

        self.assertEqual(parsed.flow, "agentRegister")
        self.assertEqual(parsed.access_id, access_id)
        self.assertEqual(parsed.registration_code, registration_code)
        self.assertEqual(parsed.passphrase, bootstrap_secret)
        self.assertEqual(parsed.site_origin, "http://localhost:4200")
        self.assertEqual(parsed.api_base_url, "http://127.0.0.1:3000")
        self.assertIsNotNone(parsed.args)
        self.assertIn(access_id, parsed.args or "")
        self.assertIn(registration_code, parsed.args or "")

    def test_store_persists_bootstrap_secret_without_exposing_it_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RegistrationStore(Path(temp_dir) / "registration.json")
            state = store.set_connection_url(
                f"http://localhost:4200/#/agent-register/{_b64url('aid')}/{_b64url('code')}/{_b64url('bootstrap')}"
            )

            self.assertEqual(state.bootstrap_secret, None)
            self.assertFalse(state.summary()["has_bootstrap_secret"])
            self.assertNotIn("bootstrap_secret", state.summary())
            self.assertFalse(state.summary()["connection_url"]["has_passphrase"])
            self.assertFalse(state.summary()["connection_url"]["has_raw_url"])
            self.assertNotIn("passphrase", state.summary()["connection_url"])
            self.assertNotIn("raw_url", state.summary()["connection_url"])
            persisted = json.loads((Path(temp_dir) / "registration.json").read_text(encoding="utf8"))
            self.assertIsNone(persisted["bootstrap_secret"])
            self.assertIsNone(persisted["access_id"])
            self.assertIsNone(persisted["connection_url"]["access_id"])
            self.assertIsNone(persisted["connection_url"]["registration_code"])
            self.assertIsNone(persisted["connection_url"]["args"])

    def test_mark_registered_clears_spent_connection_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RegistrationStore(Path(temp_dir) / "registration.json")
            store.set_connection_url(
                f"http://localhost:4200/#/agent-register/{_b64url('aid')}/{_b64url('code')}/{_b64url('bootstrap')}"
            )

            state = store.mark_registered(session_id="session-1", key_id="agent-aid", tpm_provider="windows-tpm")

            self.assertTrue(state.registered)
            self.assertEqual(state.registration_mode, "registered")
            self.assertIsNone(state.connection_url)
            self.assertIsNone(state.access_id)
            self.assertIsNone(state.bootstrap_secret)
            self.assertFalse(state.summary()["has_connection_url"])
            self.assertEqual(state.api_base_url, "http://127.0.0.1:3000")
            self.assertEqual(state.transparency_origin, "http://localhost:4200")

    def test_runtime_config_is_preserved_across_new_connection_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RegistrationStore(Path(temp_dir) / "registration.json")
            store.update_runtime_config(
                base_url="http://127.0.0.1:3000",
                transparency_origin="http://localhost:4200",
                app_version="0.20.21",
                signing_public_key_b64="pq-key",
            )

            state = store.set_connection_url(
                f"http://localhost:4200/#/agent-register/{_b64url('new-aid')}/{_b64url('new-code')}/{_b64url('new-bootstrap')}"
            )

            self.assertEqual(state.api_base_url, "http://127.0.0.1:3000")
            self.assertEqual(state.transparency_origin, "http://localhost:4200")
            self.assertEqual(state.app_version, "0.20.21")
            self.assertEqual(state.signing_public_key_b64, "pq-key")

    def test_new_connection_url_resets_stale_registration_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RegistrationStore(Path(temp_dir) / "registration.json")
            store.save(
                store.load().__class__(
                    registered=True,
                    registration_mode="registered",
                    connection_url=None,
                    session_id="old-session",
                    registered_at="2026-03-09T00:00:00Z",
                    access_id="old-aid",
                    key_id="old-key",
                    bootstrap_secret="pp:old-bootstrap",
                    tpm_provider="windows-tpm",
                )
            )

            state = store.set_connection_url(
                f"http://localhost:4200/#/agent-register/{_b64url('new-aid')}/{_b64url('new-code')}/{_b64url('new-bootstrap')}"
            )

            self.assertFalse(state.registered)
            self.assertEqual(state.registration_mode, "pending_connection_url")
            self.assertIsNone(state.access_id)
            self.assertIsNone(state.session_id)
            self.assertIsNone(state.registered_at)
            self.assertIsNone(state.key_id)
            self.assertIsNone(state.bootstrap_secret)
            self.assertIsNone(state.tpm_provider)

    def test_reset_removes_registration_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "registration.json"
            store = RegistrationStore(path)
            store.set_connection_url(
                f"http://localhost:4200/#/agent-register/{_b64url('aid')}/{_b64url('code')}/{_b64url('bootstrap')}"
            )

            state = store.reset()

            self.assertFalse(path.exists())
            self.assertFalse(state.registered)
            self.assertIsNone(state.connection_url)

    def test_save_never_writes_bootstrap_secret_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "registration.json"
            store = RegistrationStore(path)
            state = RegistrationState(
                registered=False,
                registration_mode="pending_connection_url",
                bootstrap_secret="pp:secret",
            )

            store.save(state)

            persisted = json.loads(path.read_text(encoding="utf8"))
            self.assertIsNone(persisted["bootstrap_secret"])
            self.assertEqual(state.bootstrap_secret, "pp:secret")


if __name__ == "__main__":
    unittest.main()
