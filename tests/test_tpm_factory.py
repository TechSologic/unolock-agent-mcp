from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from unolock_mcp.tpm.base import TpmDiagnostics
from unolock_mcp.tpm.factory import create_tpm_dao
from unolock_mcp.tpm.linux_tpm import LinuxTpmDao
from unolock_mcp.tpm.macos_secure_enclave import MacSecureEnclaveDao
from unolock_mcp.tpm.test_tpm import TestTpmDao
from unolock_mcp.tpm.windows_tpm import WindowsTpmDao


class TpmFactoryTest(unittest.TestCase):
    def test_forced_test_provider_requires_explicit_insecure_override(self) -> None:
        with patch.dict(
            os.environ,
            {"UNOLOCK_TPM_PROVIDER": "test", "UNOLOCK_ALLOW_INSECURE_PROVIDER": ""},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                create_tpm_dao()

    def test_forced_test_provider_returns_test_dao_with_insecure_override(self) -> None:
        with patch.dict(os.environ, {"UNOLOCK_TPM_PROVIDER": "test", "UNOLOCK_ALLOW_INSECURE_PROVIDER": "1"}, clear=False):
            dao = create_tpm_dao()
            self.assertIsInstance(dao, TestTpmDao)

    def test_forced_linux_provider_returns_linux_dao(self) -> None:
        with patch.dict(os.environ, {"UNOLOCK_TPM_PROVIDER": "linux"}, clear=False):
            dao = create_tpm_dao()
            self.assertIsInstance(dao, LinuxTpmDao)

    def test_forced_mac_provider_returns_macos_dao(self) -> None:
        with patch.dict(os.environ, {"UNOLOCK_TPM_PROVIDER": "mac"}, clear=False):
            dao = create_tpm_dao()
            self.assertIsInstance(dao, MacSecureEnclaveDao)

    def test_auto_provider_fails_closed_when_linux_tpm_unavailable(self) -> None:
        with patch.dict(
            os.environ,
            {"UNOLOCK_TPM_PROVIDER": "auto", "UNOLOCK_ALLOW_INSECURE_PROVIDER": ""},
            clear=False,
        ):
            with patch("platform.system", return_value="Linux"):
                with patch("platform.release", return_value="6.8.0-generic"):
                    with patch.object(LinuxTpmDao, "diagnose") as diagnose:
                        diagnose.return_value = TpmDiagnostics(
                            provider_name="linux-tpm",
                            provider_type="hardware",
                            production_ready=False,
                            available=False,
                            summary="missing linux tpm",
                            details={},
                            advice=["no device"],
                        )
                        with self.assertRaises(ValueError):
                            create_tpm_dao()

    def test_auto_provider_can_fall_back_to_test_with_explicit_insecure_override(self) -> None:
        with patch.dict(
            os.environ,
            {"UNOLOCK_TPM_PROVIDER": "auto", "UNOLOCK_ALLOW_INSECURE_PROVIDER": "1"},
            clear=False,
        ):
            with patch("platform.system", return_value="Linux"):
                with patch("platform.release", return_value="6.8.0-generic"):
                    with patch.object(LinuxTpmDao, "diagnose") as diagnose:
                        diagnose.return_value = TpmDiagnostics(
                            provider_name="linux-tpm",
                            provider_type="hardware",
                            production_ready=False,
                            available=False,
                            summary="missing linux tpm",
                            details={},
                            advice=["no device"],
                        )
                        dao = create_tpm_dao()
                        self.assertIsInstance(dao, TestTpmDao)

    def test_auto_provider_prefers_windows_tpm_on_wsl(self) -> None:
        with patch.dict(os.environ, {"UNOLOCK_TPM_PROVIDER": "auto"}, clear=False):
            with patch("platform.system", return_value="Linux"):
                with patch("platform.release", return_value="5.15.0-microsoft-standard-WSL2"):
                    with patch.object(WindowsTpmDao, "diagnose") as diagnose:
                        diagnose.return_value = TpmDiagnostics(
                            provider_name="windows-tpm",
                            provider_type="hardware",
                            production_ready=True,
                            available=True,
                            summary="ok",
                            details={},
                            advice=[],
                        )
                        dao = create_tpm_dao()
                        self.assertIsInstance(dao, WindowsTpmDao)

    def test_auto_provider_prefers_macos_secure_enclave_on_darwin(self) -> None:
        with patch.dict(os.environ, {"UNOLOCK_TPM_PROVIDER": "auto"}, clear=False):
            with patch("platform.system", return_value="Darwin"):
                with patch.object(MacSecureEnclaveDao, "diagnose") as diagnose:
                    diagnose.return_value = TpmDiagnostics(
                        provider_name="mac-secure-enclave",
                        provider_type="hardware",
                        production_ready=True,
                        available=True,
                        summary="ok",
                        details={},
                        advice=[],
                    )
                    dao = create_tpm_dao()
                    self.assertIsInstance(dao, MacSecureEnclaveDao)


if __name__ == "__main__":
    unittest.main()
