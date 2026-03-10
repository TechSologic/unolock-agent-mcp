from __future__ import annotations

import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
