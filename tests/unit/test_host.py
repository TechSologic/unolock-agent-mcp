from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from unolock_mcp.host import LocalHostError, ToolHostController


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


if __name__ == "__main__":
    unittest.main()
