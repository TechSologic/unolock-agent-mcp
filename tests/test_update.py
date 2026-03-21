from __future__ import annotations

import unittest
from unittest.mock import patch

from unolock_mcp.update import (
    RuntimeVersionInfo,
    detect_runtime_version_info,
    get_update_status,
)


class UpdateStatusTest(unittest.TestCase):
    def test_detect_runtime_version_info_prefers_wrapper_binary_version(self) -> None:
        runtime = detect_runtime_version_info(
            {
                "UNOLOCK_AGENT_INSTALL_CHANNEL": "npm-wrapper",
                "UNOLOCK_AGENT_WRAPPER_VERSION": "0.1.13",
                "UNOLOCK_AGENT_BINARY_VERSION": "0.1.11",
            }
        )

        self.assertEqual(runtime.install_channel, "npm-wrapper")
        self.assertEqual(runtime.wrapper_version, "0.1.13")
        self.assertEqual(runtime.binary_release_version, "0.1.11")
        self.assertEqual(runtime.current_version, "0.1.11")

    def test_get_update_status_reports_update_for_release_binary(self) -> None:
        with patch("unolock_mcp.update.fetch_latest_release_version", return_value=("0.2.0", "https://example.test/release")):
            payload = get_update_status(env={"UNOLOCK_AGENT_INSTALL_CHANNEL": "release-binary"})

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["update_available"])
        self.assertEqual(payload["latest_version"], "0.2.0")
        self.assertIn("Download the latest GitHub Release binary", payload["recommended_action"])

    def test_get_update_status_handles_network_failure(self) -> None:
        with patch("unolock_mcp.update.fetch_latest_release_version", side_effect=RuntimeError("boom")):
            payload = get_update_status(
                env={
                    "UNOLOCK_AGENT_INSTALL_CHANNEL": "npm-wrapper",
                    "UNOLOCK_AGENT_WRAPPER_VERSION": "0.1.13",
                    "UNOLOCK_AGENT_BINARY_VERSION": "0.1.11",
                }
            )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "update_check_failed")
        self.assertIn("npm install -g @techsologic/unolock-agent@latest", payload["recommended_action"])


if __name__ == "__main__":
    unittest.main()
