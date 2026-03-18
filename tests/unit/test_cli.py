from __future__ import annotations

import unittest
import json
from unittest.mock import patch
from types import SimpleNamespace

from unolock_mcp import cli
from unolock_mcp.domain.models import ConnectionUrlInfo, RegistrationState


class CliEntryPointTest(unittest.TestCase):
    def test_main_defaults_to_stdio_mcp_without_subcommand(self) -> None:
        server = SimpleNamespace(run=lambda transport: None)
        with patch.object(cli, "create_mcp_server", return_value=server):
            with patch.object(server, "run") as run_mock:
                result = cli.main([])

        self.assertEqual(result, 0)
        run_mock.assert_called_once_with("stdio")

    def test_mcp_main_passes_top_level_version_through(self) -> None:
        with patch.object(cli, "main", return_value=0) as main_mock:
            with patch("sys.argv", ["unolock-agent-mcp", "--version"]):
                result = cli.mcp_main()

        self.assertEqual(result, 0)
        main_mock.assert_called_once_with(["--version"])

    def test_mcp_main_passes_through_empty_argv(self) -> None:
        with patch.object(cli, "main", return_value=0) as main_mock:
            with patch("sys.argv", ["unolock-agent-mcp"]):
                result = cli.mcp_main()

        self.assertEqual(result, 0)
        main_mock.assert_called_once_with([])

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
                                "docs": {"agentic_safe_access": "https://docs.unolock.com/features/agentic-safe-access.html"},
                            },
                            "advice": [],
                        }
                        resolve_config.return_value = SimpleNamespace(
                            base_url="http://127.0.0.1:3000",
                            transparency_origin=None,
                            app_version=None,
                            signing_public_key_b64=None,
                            sources={"base_url": "default"},
                        )

                        result = cli.main(["self-test", "--json"])

        self.assertEqual(result, 0)
        payload = print_mock.call_args.args[0]
        self.assertIn('"recommended_next_action": "ask_for_connection_url"', payload)
        self.assertIn('"ok": true', payload)
        self.assertIn('"base_url": null', payload)
        self.assertNotIn("app_version", payload)

    def test_config_check_hides_internal_default_localhost_base_url(self) -> None:
        with patch.object(cli, "RegistrationStore") as registration_store_cls:
            with patch.object(cli, "resolve_unolock_config") as resolve_config:
                with patch("builtins.print") as print_mock:
                    registration_store_cls.return_value.load.return_value = RegistrationState()
                    resolve_config.return_value = SimpleNamespace(
                        base_url="http://127.0.0.1:3000",
                        transparency_origin=None,
                        app_version=None,
                        signing_public_key_b64=None,
                        is_complete=lambda: False,
                        sources={"base_url": "default"},
                    )

                    result = cli.main(["config-check"])

        self.assertEqual(result, 1)
        payload = print_mock.call_args.args[0]
        self.assertIn('"base_url": null', payload)
        self.assertNotIn("app_version", payload)

    def test_bootstrap_uses_pending_connection_url_runtime_fields(self) -> None:
        registration = RegistrationState(
            registered=False,
            registration_mode="pending_connection_url",
            connection_url=ConnectionUrlInfo(
                raw_url="http://localhost:4200/#/agent-register/a/b/c",
                flow="agentRegister",
                args="{}",
                action="agent-register",
                access_id="aid",
                site_origin="http://localhost:4200",
                api_base_url="http://127.0.0.1:3000",
                registration_code="code",
                source="hash",
            ),
            api_base_url=None,
            transparency_origin=None,
            app_version="0.20.21",
            signing_public_key_b64="pq-key",
        )

        with patch.object(cli, "RegistrationStore") as registration_store_cls:
            with patch.object(cli, "load_unolock_config") as load_config:
                with patch.object(cli, "resolve_unolock_config") as resolve_config:
                    with patch.object(cli, "UnoLockFlowClient") as flow_client_cls:
                        with patch.object(cli, "AgentAuthClient") as agent_auth_cls:
                            with patch("builtins.print"):
                                registration_store_cls.return_value.load.return_value = registration
                                load_config.return_value = SimpleNamespace(
                                    base_url="http://127.0.0.1:3000",
                                    app_version="0.1.0",
                                    signing_public_key_b64="abc",
                                )
                                resolve_config.return_value = SimpleNamespace(
                                    base_url="http://127.0.0.1:3000",
                                    transparency_origin="http://localhost:4200",
                                    app_version="0.20.21",
                                    signing_public_key_b64="pq-key",
                                )
                                agent_auth = agent_auth_cls.return_value
                                agent_auth.start_registration_from_stored_url.return_value = {"ok": False, "authorized": False}

                                result = cli.main(["bootstrap"])

        self.assertEqual(result, 1)
        resolve_config.assert_called_once_with(
            base_url="http://127.0.0.1:3000",
            transparency_origin="http://localhost:4200",
            app_version="0.20.21",
            signing_public_key_b64="pq-key",
        )
        load_config.assert_called_once_with(
            base_url="http://127.0.0.1:3000",
            transparency_origin="http://localhost:4200",
            app_version="0.20.21",
            signing_public_key_b64="pq-key",
        )
        registration_store_cls.return_value.update_runtime_config.assert_called_once_with(
            base_url="http://127.0.0.1:3000",
            transparency_origin="http://localhost:4200",
            app_version="0.20.21",
            signing_public_key_b64="pq-key",
        )
        flow_client_cls.assert_called_once()
        agent_auth_cls.return_value.set_flow_client.assert_called_once_with(flow_client_cls.return_value)

    def test_bootstrap_list_records_uses_session_store_for_record_writeability(self) -> None:
        registration = RegistrationState(
            registered=True,
            registration_mode="registered",
            api_base_url="http://127.0.0.1:3000",
            transparency_origin="http://localhost:4200",
            app_version="0.20.21",
            signing_public_key_b64="pq-key",
        )

        with patch.object(cli, "RegistrationStore") as registration_store_cls:
            with patch.object(cli, "load_unolock_config") as load_config:
                with patch.object(cli, "resolve_unolock_config") as resolve_config:
                    with patch.object(cli, "UnoLockFlowClient") as flow_client_cls:
                        with patch.object(cli, "AgentAuthClient") as agent_auth_cls:
                            with patch.object(cli, "UnoLockApiClient") as api_client_cls:
                                with patch.object(cli, "UnoLockReadonlyRecordsClient") as records_client_cls:
                                    with patch("builtins.print"):
                                        registration_store_cls.return_value.load.return_value = registration
                                        load_config.return_value = SimpleNamespace(
                                            base_url="http://127.0.0.1:3000",
                                            app_version="0.1.0",
                                            signing_public_key_b64="abc",
                                        )
                                        resolve_config.return_value = SimpleNamespace(
                                            base_url="http://127.0.0.1:3000",
                                            transparency_origin="http://localhost:4200",
                                            app_version="0.20.21",
                                            signing_public_key_b64="pq-key",
                                        )
                                        agent_auth = agent_auth_cls.return_value
                                        agent_auth.authenticate_registered_agent.return_value = {
                                            "ok": True,
                                            "authorized": True,
                                            "session": {"flow": "agentAccess"},
                                        }
                                        records_client_cls.return_value.list_records.return_value = {"count": 0, "records": []}

                                        result = cli.main(["bootstrap", "--list-records"])

        self.assertEqual(result, 0)
        session_store = api_client_cls.call_args.args[1]
        records_client_cls.assert_called_once_with(
            api_client_cls.return_value,
            agent_auth_cls.return_value,
            session_store,
        )
        records_client_cls.return_value.list_records.assert_called_once_with(cli.SessionStore.ACTIVE_SESSION_ID)

    def test_mcporter_config_defaults_to_npm_keep_alive(self) -> None:
        with patch("builtins.print") as print_mock:
            result = cli.main(["mcporter-config"])

        self.assertEqual(result, 0)
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["mcpServers"]["unolock-agent"]["type"], "stdio")
        self.assertEqual(payload["mcpServers"]["unolock-agent"]["command"], "npx")
        self.assertEqual(payload["mcpServers"]["unolock-agent"]["args"], ["@techsologic/unolock-agent-mcp@latest"])
        self.assertEqual(payload["mcpServers"]["unolock-agent"]["lifecycle"], "keep-alive")

    def test_mcporter_config_binary_mode_uses_binary_path(self) -> None:
        with patch("builtins.print") as print_mock:
            result = cli.main(["mcporter-config", "--mode", "binary", "--binary-path", "/opt/unolock-agent-mcp"])

        self.assertEqual(result, 0)
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["mcpServers"]["unolock-agent"]["type"], "stdio")
        self.assertEqual(payload["mcpServers"]["unolock-agent"]["command"], "/opt/unolock-agent-mcp")
        self.assertEqual(payload["mcpServers"]["unolock-agent"]["args"], [])
        self.assertEqual(payload["mcpServers"]["unolock-agent"]["lifecycle"], "keep-alive")

    def test_check_update_json_uses_update_status_helper(self) -> None:
        with patch.object(cli, "get_update_status", return_value={"ok": True, "update_available": False}) as update_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["check-update", "--json"])

        self.assertEqual(result, 0)
        update_mock.assert_called_once_with()
        self.assertIn('"update_available": false', print_mock.call_args.args[0])

    def test_check_update_text_mode_prints_status(self) -> None:
        with patch.object(
            cli,
            "get_update_status",
            return_value={"ok": True, "update_available": True, "recommended_action": "restart the runner"},
        ):
            with patch("builtins.print") as print_mock:
                result = cli.main(["check-update"])

        self.assertEqual(result, 0)
        self.assertEqual(print_mock.call_args.args[0], "UPDATE_AVAILABLE: restart the runner")

    def test_start_uses_local_daemon_helper(self) -> None:
        with patch.object(cli, "ensure_daemon_running", return_value={"ok": True, "running": True, "pid": 1234}) as start_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["start"])

        self.assertEqual(result, 0)
        start_mock.assert_called_once_with(timeout=15.0)
        self.assertIn('"running": true', print_mock.call_args.args[0])

    def test_tools_uses_local_daemon_helper(self) -> None:
        with patch.object(cli, "list_daemon_tools", return_value={"ok": True, "result": {"tools": ["unolock_list_spaces"]}}) as tools_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["tools"])

        self.assertEqual(result, 0)
        tools_mock.assert_called_once_with(auto_start=True)
        self.assertIn("unolock_list_spaces", print_mock.call_args.args[0])

    def test_call_uses_local_daemon_helper(self) -> None:
        with patch.object(cli, "call_daemon_tool", return_value={"ok": True, "result": {"ok": True}}) as call_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["call", "unolock_set_agent_pin", "--args", '{"pin":"1"}'])

        self.assertEqual(result, 0)
        call_mock.assert_called_once_with(
            "unolock_set_agent_pin",
            {"pin": "1"},
            auto_start=True,
            timeout=30.0,
        )
        self.assertIn('"ok": true', print_mock.call_args.args[0])

    def test_call_rejects_non_object_json_args(self) -> None:
        with patch("builtins.print") as print_mock:
            result = cli.main(["call", "unolock_set_agent_pin", "--args", '["bad"]'])

        self.assertEqual(result, 1)
        self.assertIn("--args must decode to a JSON object", print_mock.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
