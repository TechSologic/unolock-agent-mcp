from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from unolock_mcp.tpm.macos_keychain import MACOS_KEYCHAIN_HELPER, MacKeychainDao


class MacKeychainDaoTest(unittest.TestCase):
    def test_build_command_uses_xcrun_when_present(self) -> None:
        dao = MacKeychainDao(swift_path="/usr/bin/xcrun")
        command = dao._build_command(Path("/tmp/helper.swift"))
        self.assertEqual(command, ["/usr/bin/xcrun", "swift", "/tmp/helper.swift"])

    def test_build_compile_command_uses_xcrun_when_present(self) -> None:
        dao = MacKeychainDao(swift_path="/usr/bin/xcrun")
        dao._swiftc = "/usr/bin/xcrun"
        command = dao._build_compile_command(Path("/tmp/helper.swift"), Path("/tmp/helper"))
        self.assertEqual(command, ["/usr/bin/xcrun", "swiftc", "/tmp/helper.swift", "-o", "/tmp/helper"])

    def test_normalize_signature_converts_der_to_raw(self) -> None:
        r = int.from_bytes(bytes([7] * 32), "big")
        s = int.from_bytes(bytes([8] * 32), "big")
        der = encode_dss_signature(r, s)
        raw = MacKeychainDao._normalize_signature(der)
        self.assertEqual(raw[:32], bytes([7] * 32))
        self.assertEqual(raw[32:], bytes([8] * 32))

    def test_helper_uses_data_protection_keychain(self) -> None:
        self.assertIn("kSecUseDataProtectionKeychain", MACOS_KEYCHAIN_HELPER)
        self.assertNotIn("kSecAttrTokenIDSecureEnclave", MACOS_KEYCHAIN_HELPER)

    def test_helper_uses_when_unlocked_device_only_accessibility(self) -> None:
        self.assertIn("kSecAttrAccessibleWhenUnlockedThisDeviceOnly", MACOS_KEYCHAIN_HELPER)

    def test_diagnose_reports_keychain_failure_helpfully(self) -> None:
        dao = MacKeychainDao(swift_path="/usr/bin/swift")
        with patch("platform.system", return_value="Darwin"):
            with patch.object(dao, "_run_helper", side_effect=RuntimeError("keychain unavailable")):
                diagnostics = dao.diagnose()

        self.assertFalse(diagnostics.production_ready)
        self.assertEqual(diagnostics.provider_type, "platform")
        self.assertIn("Keychain", diagnostics.summary)
        self.assertTrue(any("login keychain" in item for item in diagnostics.advice))


if __name__ == "__main__":
    unittest.main()
