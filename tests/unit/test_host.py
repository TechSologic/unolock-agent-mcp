from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from unolock_mcp.host import LocalHostError, ToolHostController


class ToolHostControllerTest(unittest.TestCase):
    def test_list_tools_and_call_tool(self) -> None:
        fake_server = SimpleNamespace(
            _tool_manager=SimpleNamespace(
                _tools={
                    "echo": SimpleNamespace(fn=lambda text="": {"ok": True, "text": text}),
                    "ping": SimpleNamespace(fn=lambda: {"ok": True, "pong": True}),
                }
            )
        )
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
        fake_server = SimpleNamespace(
            _tool_manager=SimpleNamespace(_tools={}),
            instructions="uno instructions",
        )
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
        async def fake_list_tools():
            return []

        fake_server = SimpleNamespace(
            _tool_manager=SimpleNamespace(
                _tools={"echo": SimpleNamespace(fn=lambda text="": {"ok": True, "text": text})}
            ),
            instructions="uno instructions",
            list_tools=fake_list_tools,
        )
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


if __name__ == "__main__":
    unittest.main()
