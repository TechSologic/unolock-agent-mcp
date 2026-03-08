from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from unolock_mcp.auth.registration_store import RegistrationStore, parse_connection_url


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
        self.assertIsNotNone(parsed.args)
        self.assertIn(access_id, parsed.args or "")
        self.assertIn(registration_code, parsed.args or "")

    def test_store_persists_bootstrap_secret_without_exposing_it_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RegistrationStore(Path(temp_dir) / "registration.json")
            state = store.set_connection_url(
                f"http://localhost:4200/#/agent-register/{_b64url('aid')}/{_b64url('code')}/{_b64url('bootstrap')}"
            )

            self.assertEqual(state.bootstrap_secret, "bootstrap")
            self.assertTrue(state.summary()["has_bootstrap_secret"])
            self.assertNotIn("bootstrap_secret", state.summary())


if __name__ == "__main__":
    unittest.main()
