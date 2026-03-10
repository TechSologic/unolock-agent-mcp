from __future__ import annotations

import unittest
from unittest.mock import patch
from types import SimpleNamespace

from unolock_mcp import cli


class CliEntryPointTest(unittest.TestCase):
    def test_mcp_main_passes_top_level_version_through(self) -> None:
        with patch.object(cli, "main", return_value=0) as main_mock:
            with patch("sys.argv", ["unolock-agent-mcp", "--version"]):
                result = cli.mcp_main()

        self.assertEqual(result, 0)
        main_mock.assert_called_once_with(["--version"])

    def test_mcp_main_defaults_to_mcp_subcommand(self) -> None:
        with patch.object(cli, "main", return_value=0) as main_mock:
            with patch("sys.argv", ["unolock-agent-mcp"]):
                result = cli.mcp_main()

        self.assertEqual(result, 0)
        main_mock.assert_called_once_with(["mcp"])

    def test_tpm_check_main_defaults_to_tpm_check_subcommand(self) -> None:
        with patch.object(cli, "main", return_value=0) as main_mock:
            with patch("sys.argv", ["unolock-agent-tpm-check"]):
                result = cli.tpm_check_main()

        self.assertEqual(result, 0)
        main_mock.assert_called_once_with(["tpm-check"])

    def test_self_test_main_defaults_to_self_test_subcommand(self) -> None:
        with patch.object(cli, "main", return_value=0) as main_mock:
            with patch("sys.argv", ["unolock-agent-self-test"]):
                result = cli.self_test_main()

        self.assertEqual(result, 0)
        main_mock.assert_called_once_with(["self-test"])

    def test_self_test_returns_ready_for_bootstrap_when_tpm_is_ready(self) -> None:
        with patch.object(cli, "AgentAuthClient") as agent_auth_cls:
            with patch.object(cli, "RegistrationStore") as registration_store_cls:
                with patch.object(cli, "resolve_unolock_config") as resolve_config:
                    with patch("builtins.print") as print_mock:
                        registration_store_cls.return_value.load.return_value.summary.return_value = {
                            "registered": False,
                            "access_id": None,
                            "tpm_provider": None,
                            "api_base_url": None,
                            "transparency_origin": None,
                        }
                        agent_auth_cls.return_value.tpm_diagnostics.return_value = {
                            "provider_name": "windows-tpm",
                            "provider_type": "hardware",
                            "production_ready": True,
                            "available": True,
                            "summary": "Windows Platform Crypto Provider created a TPM-backed P-256 key.",
                            "details": {
                                "environment": {"is_container": False, "container_runtime": "", "is_wsl": True},
                                "docs": {"agentic_safe_access": "https://safe.unolock.com/docs/features/agentic-safe-access/"},
                            },
                            "advice": [],
                        }
                        resolve_config.return_value = SimpleNamespace(
                            base_url=None,
                            transparency_origin=None,
                            app_version=None,
                            signing_public_key_b64=None,
                        )

                        result = cli.main(["self-test", "--json"])

        self.assertEqual(result, 0)
        payload = print_mock.call_args.args[0]
        self.assertIn('"recommended_next_action": "ask_for_connection_url"', payload)
        self.assertIn('"ok": true', payload)


if __name__ == "__main__":
    unittest.main()
