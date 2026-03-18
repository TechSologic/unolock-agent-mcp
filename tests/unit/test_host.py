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


if __name__ == "__main__":
    unittest.main()
