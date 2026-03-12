from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from unolock_mcp.tpm.host_diagnostics import detect_host_environment, detect_host_tpm_state


class HostDiagnosticsTest(unittest.TestCase):
    def test_detect_host_environment_marks_docker(self) -> None:
        with patch("unolock_mcp.tpm.host_diagnostics._detect_linux_container_runtime", return_value="docker"):
            environment = detect_host_environment(system="linux", release="6.8.0-generic")
        self.assertTrue(environment["is_container"])
        self.assertEqual(environment["container_runtime"], "docker")

    def test_detect_host_tpm_state_reports_container_specific_advice(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("platform.system", return_value="Linux"):
                with patch("platform.release", return_value="6.8.0-generic"):
                    with patch("unolock_mcp.tpm.host_diagnostics._detect_linux_container_runtime", return_value="docker"):
                        with patch("shutil.which", return_value=None):
                            diagnostics = detect_host_tpm_state("linux-tpm", production_ready=True)

        self.assertFalse(diagnostics.available)
        self.assertIn("docker", diagnostics.summary.lower())
        self.assertIn("environment", diagnostics.details)
        self.assertTrue(diagnostics.details["environment"]["is_container"])
        self.assertTrue(any("docs.unolock.com" in item for item in diagnostics.advice))

    def test_detect_host_tpm_state_reports_macos_software_fallback_context(self) -> None:
        with patch("platform.system", return_value="Darwin"):
            with patch("platform.release", return_value="24.0.0"):
                diagnostics = detect_host_tpm_state("software", production_ready=False)

        self.assertFalse(diagnostics.production_ready)
        self.assertIn("secure enclave", diagnostics.summary.lower())
        self.assertTrue(any("keychain" in item.lower() for item in diagnostics.advice))


if __name__ == "__main__":
    unittest.main()
