from __future__ import annotations

import unittest
import json
from unittest.mock import patch
from types import SimpleNamespace

from unolock_mcp import cli
from unolock_mcp.domain.models import ConnectionUrlInfo, RegistrationState
from unolock_mcp.host import (
    DEFAULT_DAEMON_CALL_TIMEOUT,
    DEFAULT_DAEMON_START_TIMEOUT,
)


class CliEntryPointTest(unittest.TestCase):
    def test_help_hides_advanced_daemon_commands(self) -> None:
        parser = cli.build_parser()

        help_text = parser.format_help()

        self.assertIn("register", help_text)
        self.assertIn("sync-list", help_text)
        self.assertIn("sync-enable", help_text)
        self.assertIn("sync-disable", help_text)
        self.assertNotIn("tools", help_text)
        self.assertNotIn("call", help_text)
        self.assertNotIn("bootstrap", help_text)

    def test_sync_add_cli_request_mapping(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "sync-add",
                "/tmp/file.txt",
                "--space-id",
                "1773",
                "--title",
                "file.txt",
                "--mime-type",
                "text/plain",
                "--archive-id",
                "archive-1",
                "--disabled",
                "--poll-seconds",
                "9",
                "--debounce-seconds",
                "4",
            ]
        )

        tool_name, payload = cli._cli_tool_request_from_args(args)

        self.assertEqual(tool_name, "unolock_sync_add")
        self.assertEqual(
            payload,
            {
                "local_path": "/tmp/file.txt",
                "space_id": 1773,
                "title": "file.txt",
                "mime_type": "text/plain",
                "archive_id": "archive-1",
                "enabled": False,
                "poll_seconds": 9,
                "debounce_seconds": 4,
            },
        )

    def test_cli_success_value_formats_sync_status(self) -> None:
        payload = cli._cli_success_value(
            "unolock_sync_status",
            {
                "daemon_running": True,
                "monitoring": True,
                "count": 1,
                "states": {"synced": 1},
                "syncs": [
                    {
                        "sync_id": "syn_01",
                        "space_id": 1773,
                        "archive_id": "archive-1",
                        "local_path": "/tmp/file.txt",
                        "name": "file.txt",
                        "mode": "push",
                        "enabled": True,
                        "status": "synced",
                        "last_uploaded_at": "2026-03-21T14:22:11Z",
                    }
                ],
            },
        )

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["states"], {"synced": 1})
        self.assertEqual(payload["syncs"][0]["sync_id"], "syn_01")
        self.assertEqual(payload["syncs"][0]["mode"], "push")

    def test_sync_run_cli_request_mapping(self) -> None:
        args = cli.build_parser().parse_args(["sync-run", "syn_01"])

        tool_name, payload = cli._cli_tool_request_from_args(args)

        self.assertEqual(tool_name, "unolock_sync_run")
        self.assertEqual(payload, {"sync_id": "syn_01", "run_all": False})

    def test_sync_remove_cli_request_mapping(self) -> None:
        args = cli.build_parser().parse_args(["sync-remove", "syn_01", "--delete-remote"])

        tool_name, payload = cli._cli_tool_request_from_args(args)

        self.assertEqual(tool_name, "unolock_sync_remove")
        self.assertEqual(payload, {"sync_id": "syn_01", "delete_remote": True})

    def test_sync_enable_cli_request_mapping(self) -> None:
        args = cli.build_parser().parse_args(["sync-enable", "syn_01"])

        tool_name, payload = cli._cli_tool_request_from_args(args)

        self.assertEqual(tool_name, "unolock_sync_enable")
        self.assertEqual(payload, {"sync_id": "syn_01"})

    def test_sync_disable_cli_request_mapping(self) -> None:
        args = cli.build_parser().parse_args(["sync-disable", "syn_01"])

        tool_name, payload = cli._cli_tool_request_from_args(args)

        self.assertEqual(tool_name, "unolock_sync_disable")
        self.assertEqual(payload, {"sync_id": "syn_01"})

    def test_sync_restore_cli_request_mapping(self) -> None:
        args = cli.build_parser().parse_args(["sync-restore", "syn_01", "--output-path", "/tmp/out.txt", "--overwrite"])

        tool_name, payload = cli._cli_tool_request_from_args(args)

        self.assertEqual(tool_name, "unolock_sync_restore")
        self.assertEqual(payload, {"sync_id": "syn_01", "output_path": "/tmp/out.txt", "overwrite": True})

    def test_main_prints_help_without_subcommand(self) -> None:
        with patch.object(cli.argparse.ArgumentParser, "print_help") as help_mock:
            with patch.object(cli, "proxy_stdio_to_daemon", return_value=0) as proxy_mock:
                result = cli.main([])

        self.assertEqual(result, 0)
        help_mock.assert_called_once()
        proxy_mock.assert_not_called()

    def test_main_runs_stdio_mcp_with_explicit_subcommand(self) -> None:
        with patch.object(cli, "proxy_stdio_to_daemon", return_value=0) as proxy_mock:
            result = cli.main(["mcp"])

        self.assertEqual(result, 0)
        proxy_mock.assert_called_once_with(auto_start=True, timeout=None)

    def test_mcp_main_passes_top_level_version_through(self) -> None:
        with patch.object(cli, "main", return_value=0) as main_mock:
            with patch("sys.argv", ["unolock-agent", "--version"]):
                result = cli.mcp_main()

        self.assertEqual(result, 0)
        main_mock.assert_called_once_with(["--version"])

    def test_mcp_main_passes_through_empty_argv(self) -> None:
        with patch.object(cli, "main", return_value=0) as main_mock:
            with patch("sys.argv", ["unolock-agent"]):
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

    def test_cli_blocked_result_adds_link_agent_key_guidance(self) -> None:
        with patch.object(
            cli,
            "call_daemon_tool",
            return_value={
                "ok": True,
                "result": {
                    "ok": False,
                    "blocked": True,
                    "reason": "missing_connection_url",
                    "message": "Need setup.",
                },
            },
        ):
            with patch("builtins.print") as print_mock:
                result = cli.main(["list-spaces"])

        self.assertEqual(result, 1)
        self.assertEqual(
            print_mock.call_args.args[0],
            "Registration required.\nAsk the user for the one-time UnoLock Agent Key URL and PIN.\nRun: unolock-agent register '<agent-key-url>' '<pin>'",
        )

    def test_cli_blocked_result_adds_set_agent_pin_guidance(self) -> None:
        with patch.object(
            cli,
            "call_daemon_tool",
            return_value={
                "ok": True,
                "result": {
                    "ok": False,
                    "blocked": True,
                    "reason": "missing_agent_pin",
                    "message": "Need PIN.",
                },
            },
        ):
            with patch("builtins.print") as print_mock:
                result = cli.main(["list-spaces"])

        self.assertEqual(result, 1)
        self.assertEqual(
            print_mock.call_args.args[0],
            "PIN required.\nAsk the user for the UnoLock PIN.\nRun: unolock-agent set-pin '<pin>'",
        )

    def test_start_uses_local_daemon_helper(self) -> None:
        with patch.object(cli, "ensure_daemon_running", return_value={"ok": True, "running": True, "pid": 1234}) as start_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["start"])

        self.assertEqual(result, 0)
        start_mock.assert_called_once_with(timeout=DEFAULT_DAEMON_START_TIMEOUT)
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
            timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
        )
        self.assertIn('"ok": true', print_mock.call_args.args[0])

    def test_call_rejects_non_object_json_args(self) -> None:
        with patch("builtins.print") as print_mock:
            result = cli.main(["call", "unolock_set_agent_pin", "--args", '["bad"]'])

        self.assertEqual(result, 1)
        self.assertIn("--args must decode to a JSON object", print_mock.call_args.args[0])

    def test_link_agent_key_cli_command_calls_matching_tool(self) -> None:
        with patch.object(cli, "call_daemon_tool", return_value={"ok": True, "result": {"ok": True, "linked": True}}) as call_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["register", "https://safe.test/#/agent-register/x/y/z", "1"])

        self.assertEqual(result, 0)
        call_mock.assert_called_once_with(
            "unolock_register",
            {"connection_url": "https://safe.test/#/agent-register/x/y/z", "pin": "1"},
            auto_start=True,
            timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
        )
        self.assertEqual(print_mock.call_args.args[0], json.dumps({"linked": True}, indent=2))

    def test_set_pin_cli_returns_small_success_object(self) -> None:
        payload = {
            "ok": True,
            "result": {
                "ok": True,
                "has_agent_pin": True,
                "pin_mode": "ephemeral_memory",
                "resumed_operation": {
                    "tool": "unolock_list_spaces",
                    "result": {"ok": True, "spaces": []},
                },
            },
        }
        with patch.object(cli, "call_daemon_tool", return_value=payload) as call_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["set-pin", "1"])

        self.assertEqual(result, 0)
        call_mock.assert_called_once_with(
            "unolock_set_agent_pin",
            {"pin": "1"},
            auto_start=True,
            timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
        )
        self.assertEqual(print_mock.call_args.args[0], json.dumps({"pin_set": True}, indent=2))

    def test_set_pin_cli_verbose_returns_full_payload(self) -> None:
        payload = {
            "ok": True,
            "result": {
                "ok": True,
                "has_agent_pin": True,
                "pin_mode": "ephemeral_memory",
            },
        }
        with patch.object(cli, "call_daemon_tool", return_value=payload) as call_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["set-pin", "1", "--verbose"])

        self.assertEqual(result, 0)
        call_mock.assert_called_once_with(
            "unolock_set_agent_pin",
            {"pin": "1"},
            auto_start=True,
            timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
        )
        self.assertEqual(print_mock.call_args.args[0], json.dumps(payload, indent=2))

    def test_list_files_cli_command_calls_matching_tool(self) -> None:
        with patch.object(cli, "call_daemon_tool", return_value={"ok": True, "result": {"space_id": 1, "count": 0, "files": []}}) as call_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["list-files"])

        self.assertEqual(result, 0)
        call_mock.assert_called_once_with(
            "unolock_list_files",
            {},
            auto_start=True,
            timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
        )
        self.assertEqual(print_mock.call_args.args[0], json.dumps({"space_id": 1, "count": 0, "files": []}, indent=2))

    def test_list_files_cli_command_verbose_prints_full_payload(self) -> None:
        payload = {"ok": True, "result": {"space_id": 1, "files": []}}
        with patch.object(cli, "call_daemon_tool", return_value=payload) as call_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["list-files", "--verbose"])

        self.assertEqual(result, 0)
        call_mock.assert_called_once_with(
            "unolock_list_files",
            {},
            auto_start=True,
            timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
        )
        self.assertEqual(print_mock.call_args.args[0], json.dumps(payload, indent=2))

    def test_create_note_cli_command_calls_matching_tool(self) -> None:
        with patch.object(cli, "call_daemon_tool", return_value={"ok": True, "result": {"record_ref": "a:b"}}) as call_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["create-note", "todo", "remember this"])

        self.assertEqual(result, 0)
        call_mock.assert_called_once_with(
            "unolock_create_note",
            {"title": "todo", "text": "remember this"},
            auto_start=True,
            timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
        )
        self.assertEqual(print_mock.call_args.args[0], json.dumps({"record": {"record_ref": "a:b"}}, indent=2))

    def test_list_notes_cli_trims_internal_record_fields(self) -> None:
        payload = {
            "ok": True,
            "result": {
                "kind_filter": "note",
                "space_id_filter": 7,
                "space_id": 7,
                "count": 1,
                "records": [
                    {
                        "record_ref": "a:b",
                        "id": 1,
                        "version": 2,
                        "archive_id": "arch-1",
                        "space_id": 7,
                        "space_name": "Agent",
                        "kind": "note",
                        "title": "Todo",
                        "plain_text": "Remember this",
                        "pinned": False,
                        "labels": [],
                        "message_meta": None,
                        "checklist_items": [],
                        "raw_delta": "{\"ops\":[]}",
                        "raw_checkboxes": [],
                        "read_only": False,
                        "locked": False,
                        "writable": True,
                        "allowed_operations": ["get_record", "update_note"],
                    }
                ],
            },
        }
        with patch.object(cli, "call_daemon_tool", return_value=payload):
            with patch("builtins.print") as print_mock:
                result = cli.main(["list-notes"])

        self.assertEqual(result, 0)
        self.assertEqual(
            print_mock.call_args.args[0],
            json.dumps(
                {
                    "space_id": 7,
                    "count": 1,
                    "notes": [
                        {
                            "record_ref": "a:b",
                            "version": 2,
                            "space_id": 7,
                            "kind": "note",
                            "title": "Todo",
                            "plain_text": "Remember this",
                            "pinned": False,
                            "labels": [],
                            "locked": False,
                            "writable": True,
                            "allowed_operations": ["get_record", "update_note"],
                        }
                    ],
                },
                indent=2,
            ),
        )

    def test_get_record_cli_trims_internal_record_fields(self) -> None:
        payload = {
            "ok": True,
            "result": {
                "record": {
                    "record_ref": "a:b",
                    "id": 1,
                    "version": 2,
                    "archive_id": "arch-1",
                    "space_id": 7,
                    "space_name": "Agent",
                    "kind": "note",
                    "title": "Todo",
                    "plain_text": "Remember this",
                    "pinned": False,
                    "labels": [],
                    "message_meta": None,
                    "checklist_items": [],
                    "raw_delta": "{\"ops\":[]}",
                    "raw_checkboxes": [],
                    "read_only": False,
                    "locked": False,
                    "writable": True,
                    "allowed_operations": ["get_record", "update_note"],
                }
            },
        }
        with patch.object(cli, "call_daemon_tool", return_value=payload):
            with patch("builtins.print") as print_mock:
                result = cli.main(["get-record", "a:b"])

        self.assertEqual(result, 0)
        self.assertEqual(
            print_mock.call_args.args[0],
            json.dumps(
                {
                    "record": {
                        "record_ref": "a:b",
                        "version": 2,
                        "space_id": 7,
                        "kind": "note",
                        "title": "Todo",
                        "plain_text": "Remember this",
                        "pinned": False,
                        "labels": [],
                        "locked": False,
                        "writable": True,
                        "allowed_operations": ["get_record", "update_note"],
                    }
                },
                indent=2,
            ),
        )

    def test_get_file_cli_trims_internal_file_fields(self) -> None:
        payload = {
            "ok": True,
            "result": {
                "file": {
                    "archive_id": "arch-1",
                    "space_id": 7,
                    "space_name": "Agent",
                    "name": "notes.txt",
                    "mime_type": "text/plain",
                    "size": 12,
                    "etag": "abc",
                    "writable": True,
                    "allowed_operations": ["get_file", "download_file"],
                }
            },
        }
        with patch.object(cli, "call_daemon_tool", return_value=payload):
            with patch("builtins.print") as print_mock:
                result = cli.main(["get-file", "arch-1"])

        self.assertEqual(result, 0)
        self.assertEqual(
            print_mock.call_args.args[0],
            json.dumps(
                {
                    "file": {
                        "archive_id": "arch-1",
                        "space_id": 7,
                        "name": "notes.txt",
                        "mime_type": "text/plain",
                        "size": 12,
                        "writable": True,
                        "allowed_operations": ["get_file", "download_file"],
                    }
                },
                indent=2,
            ),
        )

    def test_update_note_cli_command_allows_text_only_by_default(self) -> None:
        with patch.object(cli, "call_daemon_tool", return_value={"ok": True, "result": {"ok": True}}) as call_mock:
            with patch("builtins.print"):
                result = cli.main(["update-note", "a:b", "--text", "text"])

        self.assertEqual(result, 0)
        call_mock.assert_called_once_with(
            "unolock_update_note",
            {"record_ref": "a:b", "text": "text"},
            auto_start=True,
            timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
        )

    def test_update_note_cli_command_accepts_optional_expected_version_flag(self) -> None:
        with patch.object(cli, "call_daemon_tool", return_value={"ok": True, "result": {"ok": True}}) as call_mock:
            with patch("builtins.print"):
                result = cli.main(
                    ["update-note", "a:b", "--expected-version", "7", "--title", "title", "--text", "text"]
                )

        self.assertEqual(result, 0)
        call_mock.assert_called_once_with(
            "unolock_update_note",
            {"record_ref": "a:b", "expected_version": 7, "title": "title", "text": "text"},
            auto_start=True,
            timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
        )

    def test_update_note_cli_command_rejects_missing_title_and_text(self) -> None:
        with patch("builtins.print") as print_mock:
            result = cli.main(["update-note", "a:b"])

        self.assertEqual(result, 1)
        self.assertIn("requires --title and/or --text", print_mock.call_args.args[0])

    def test_create_checklist_cli_rejects_non_array_items_json(self) -> None:
        with patch("builtins.print") as print_mock:
            result = cli.main(["create-checklist", "tasks", "--items", '{"bad":true}'])

        self.assertEqual(result, 1)
        self.assertIn("--items must decode to a JSON array", print_mock.call_args.args[0])

    def test_subcommand_help_uses_standard_argparse_help(self) -> None:
        with self.assertRaises(SystemExit) as exc:
            cli.main(["register", "--help"])

        self.assertEqual(exc.exception.code, 0)

    def test_list_notes_cli_returns_nonzero_when_agent_key_is_missing(self) -> None:
        blocked = {
            "ok": False,
            "blocked": True,
            "reason": "missing_connection_url",
            "message": "Ask the user for the one-time UnoLock Agent Key URL and PIN, then call unolock_register.",
        }
        with patch.object(cli, "call_daemon_tool", return_value={"ok": True, "result": blocked}) as call_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["list-notes"])

        self.assertEqual(result, 1)
        call_mock.assert_called_once_with(
            "unolock_list_notes",
            {"pinned": None, "label": None},
            auto_start=True,
            timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
        )
        self.assertEqual(
            print_mock.call_args.args[0],
            "Registration required.\nAsk the user for the one-time UnoLock Agent Key URL and PIN.\nRun: unolock-agent register '<agent-key-url>' '<pin>'",
        )

    def test_list_files_cli_returns_nonzero_when_pin_is_needed(self) -> None:
        blocked = {
            "ok": False,
            "blocked": True,
            "reason": "missing_agent_pin",
            "message": "Ask the user for the UnoLock agent PIN and call unolock_set_agent_pin.",
        }
        with patch.object(cli, "call_daemon_tool", return_value={"ok": True, "result": blocked}) as call_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["list-files"])

        self.assertEqual(result, 1)
        call_mock.assert_called_once_with(
            "unolock_list_files",
            {},
            auto_start=True,
            timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
        )
        self.assertEqual(print_mock.call_args.args[0], "PIN required.\nAsk the user for the UnoLock PIN.\nRun: unolock-agent set-pin '<pin>'")

    def test_list_files_cli_verbose_returns_full_blocked_payload(self) -> None:
        blocked = {
            "ok": False,
            "blocked": True,
            "reason": "missing_agent_pin",
            "message": "Ask the user for the UnoLock agent PIN and call unolock_set_agent_pin.",
        }
        payload = {"ok": True, "result": blocked}
        with patch.object(cli, "call_daemon_tool", return_value=payload) as call_mock:
            with patch("builtins.print") as print_mock:
                result = cli.main(["list-files", "--verbose"])

        self.assertEqual(result, 1)
        call_mock.assert_called_once_with(
            "unolock_list_files",
            {},
            auto_start=True,
            timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
        )
        self.assertEqual(print_mock.call_args.args[0], json.dumps(payload, indent=2))


if __name__ == "__main__":
    unittest.main()
