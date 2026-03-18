from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from unolock_mcp.host import (
    LocalDaemonState,
    LocalHostError,
    ToolHostController,
    _ensure_state_dir,
    _write_daemon_state,
    daemon_state_path,
    load_daemon_state,
)


class ToolHostControllerTest(unittest.TestCase):
    def _fake_server(self):
        async def fake_list_tools():
            return []

        async def fake_list_resources():
            return [{"uri": "unolock://usage/quickstart", "name": "Quickstart"}]

        async def fake_list_resource_templates():
            return []

        async def fake_read_resource(uri: str):
            return [{"uri": uri, "text": "hello"}]

        async def fake_list_prompts():
            return [{"name": "uno"}]

        async def fake_get_prompt(name: str, arguments=None):
            return {"name": name, "arguments": arguments or {}}

        return SimpleNamespace(
            _tool_manager=SimpleNamespace(
                _tools={
                    "echo": SimpleNamespace(fn=lambda text="": {"ok": True, "text": text}),
                    "ping": SimpleNamespace(fn=lambda: {"ok": True, "pong": True}),
                }
            ),
            instructions="uno instructions",
            list_tools=fake_list_tools,
            list_resources=fake_list_resources,
            list_resource_templates=fake_list_resource_templates,
            read_resource=fake_read_resource,
            list_prompts=fake_list_prompts,
            get_prompt=fake_get_prompt,
        )

    def test_list_tools_and_call_tool(self) -> None:
        fake_server = self._fake_server()
        with patch("unolock_mcp.host.create_mcp_server", return_value=fake_server):
            controller = ToolHostController()

        tools = controller.list_tools()
        result = controller.call_tool("echo", {"text": "hello"})

        self.assertEqual(tools["tools"], ["echo", "ping"])
        self.assertEqual(result, {"ok": True, "text": "hello"})

    def test_call_tool_rejects_unknown_tool(self) -> None:
        fake_server = SimpleNamespace(
            _tool_manager=SimpleNamespace(
                _tools={"ping": SimpleNamespace(fn=lambda: {"ok": True})}
            )
        )
        with patch("unolock_mcp.host.create_mcp_server", return_value=fake_server):
            controller = ToolHostController()

        with self.assertRaisesRegex(LocalHostError, "Unknown UnoLock tool"):
            controller.call_tool("missing", {})

    def test_call_tool_requires_object_arguments(self) -> None:
        fake_server = SimpleNamespace(
            _tool_manager=SimpleNamespace(
                _tools={"ping": SimpleNamespace(fn=lambda: {"ok": True})}
            )
        )
        with patch("unolock_mcp.host.create_mcp_server", return_value=fake_server):
            controller = ToolHostController()

        with self.assertRaisesRegex(LocalHostError, "arguments must be a JSON object"):
            controller.call_tool("ping", ["bad"])

    def test_handle_mcp_request_initialize_returns_capabilities(self) -> None:
        fake_server = self._fake_server()
        with patch("unolock_mcp.host.create_mcp_server", return_value=fake_server):
            controller = ToolHostController()

        response = controller.handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26"},
            }
        )

        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(response["result"]["instructions"], "uno instructions")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_handle_mcp_request_tools_call_wraps_result(self) -> None:
        fake_server = self._fake_server()
        with patch("unolock_mcp.host.create_mcp_server", return_value=fake_server):
            controller = ToolHostController()

        response = controller.handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "hello"}},
            }
        )

        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 2)
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(response["result"]["structuredContent"], {"ok": True, "text": "hello"})

    def test_handle_mcp_request_supports_standard_notification_and_ping(self) -> None:
        fake_server = self._fake_server()
        with patch("unolock_mcp.host.create_mcp_server", return_value=fake_server):
            controller = ToolHostController()

        self.assertIsNone(
            controller.handle_mcp_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )
        ping_response = controller.handle_mcp_request({"jsonrpc": "2.0", "id": 3, "method": "ping"})
        self.assertEqual(ping_response["result"], {})

    def test_handle_mcp_request_supports_resources_and_prompts(self) -> None:
        fake_server = self._fake_server()
        with patch("unolock_mcp.host.create_mcp_server", return_value=fake_server):
            controller = ToolHostController()

        resources = controller.handle_mcp_request({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
        templates = controller.handle_mcp_request(
            {"jsonrpc": "2.0", "id": 5, "method": "resources/templates/list"}
        )
        read = controller.handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "resources/read",
                "params": {"uri": "unolock://usage/quickstart"},
            }
        )
        prompts = controller.handle_mcp_request({"jsonrpc": "2.0", "id": 7, "method": "prompts/list"})
        prompt = controller.handle_mcp_request(
            {"jsonrpc": "2.0", "id": 8, "method": "prompts/get", "params": {"name": "uno"}}
        )

        self.assertEqual(resources["result"]["resources"][0]["uri"], "unolock://usage/quickstart")
        self.assertEqual(templates["result"]["resourceTemplates"], [])
        self.assertEqual(read["result"]["contents"][0]["uri"], "unolock://usage/quickstart")
        self.assertEqual(prompts["result"]["prompts"][0]["name"], "uno")
        self.assertEqual(prompt["result"]["name"], "uno")


class DaemonStateFilesystemTest(unittest.TestCase):
    def test_state_dir_is_private_on_posix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "cfg" / "config.json"
            with patch("unolock_mcp.host.default_config_path", return_value=config_path):
                _ensure_state_dir()
                state_dir = config_path.parent
                self.assertTrue(state_dir.exists())
                if os.name != "nt":
                    self.assertEqual(oct(state_dir.stat().st_mode & 0o777), "0o700")

    def test_write_and_load_daemon_state_preserves_socket_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "cfg" / "config.json"
            with patch("unolock_mcp.host.default_config_path", return_value=config_path):
                state = LocalDaemonState(
                    pid=123,
                    token="secret",
                    version="0.1.0",
                    started_at=1.0,
                    socket_path=str(config_path.parent / "daemon.sock"),
                )
                _write_daemon_state(state)
                loaded = load_daemon_state()
                self.assertEqual(loaded.socket_path, state.socket_path)
                self.assertIsNone(loaded.port)
                raw = json.loads(daemon_state_path().read_text(encoding="utf8"))
                self.assertEqual(raw["socket_path"], state.socket_path)
                if os.name != "nt":
                    self.assertEqual(oct(daemon_state_path().stat().st_mode & 0o777), "0o600")

    def test_load_daemon_state_accepts_legacy_port_only_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "cfg" / "config.json"
            with patch("unolock_mcp.host.default_config_path", return_value=config_path):
                config_path.parent.mkdir(parents=True, exist_ok=True)
                daemon_state_path().write_text(
                    json.dumps(
                        {
                            "pid": 123,
                            "port": 4000,
                            "token": "secret",
                            "version": "0.1.0",
                            "started_at": 1.0,
                        }
                    ),
                    encoding="utf8",
                )
                loaded = load_daemon_state()
                self.assertEqual(loaded.port, 4000)
                self.assertIsNone(loaded.socket_path)


if __name__ == "__main__":
    unittest.main()
