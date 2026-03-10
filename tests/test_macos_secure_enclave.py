from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from unolock_mcp.tpm.macos_secure_enclave import MacSecureEnclaveDao


class MacSecureEnclaveDaoTest(unittest.TestCase):
    def test_build_command_uses_xcrun_when_present(self) -> None:
        dao = MacSecureEnclaveDao(swift_path="/usr/bin/xcrun")
        command = dao._build_command(Path("/tmp/helper.swift"))
        self.assertEqual(command, ["/usr/bin/xcrun", "swift", "/tmp/helper.swift"])

    def test_build_command_uses_swift_directly(self) -> None:
        dao = MacSecureEnclaveDao(swift_path="/usr/bin/swift")
        command = dao._build_command(Path("/tmp/helper.swift"))
        self.assertEqual(command, ["/usr/bin/swift", "/tmp/helper.swift"])

    def test_build_compile_command_uses_xcrun_when_present(self) -> None:
        dao = MacSecureEnclaveDao(swift_path="/usr/bin/xcrun")
        dao._swiftc = "/usr/bin/xcrun"
        command = dao._build_compile_command(Path("/tmp/helper.swift"), Path("/tmp/helper"))
        self.assertEqual(
            command,
            ["/usr/bin/xcrun", "swiftc", "/tmp/helper.swift", "-o", "/tmp/helper"],
        )

    def test_build_compile_command_uses_swiftc_directly(self) -> None:
        dao = MacSecureEnclaveDao(swift_path="/usr/bin/swift")
        dao._swiftc = "/usr/bin/swiftc"
        command = dao._build_compile_command(Path("/tmp/helper.swift"), Path("/tmp/helper"))
        self.assertEqual(
            command,
            ["/usr/bin/swiftc", "/tmp/helper.swift", "-o", "/tmp/helper"],
        )

    def test_normalize_signature_converts_der_to_raw(self) -> None:
        r = int.from_bytes(bytes([3] * 32), "big")
        s = int.from_bytes(bytes([4] * 32), "big")
        der = encode_dss_signature(r, s)
        raw = MacSecureEnclaveDao._normalize_signature(der)
        self.assertEqual(raw[:32], bytes([3] * 32))
        self.assertEqual(raw[32:], bytes([4] * 32))

    def test_diagnose_reports_osstatus_34018_helpfully(self) -> None:
        dao = MacSecureEnclaveDao(swift_path="/usr/bin/swift")
        with patch("platform.system", return_value="Darwin"):
            with patch.object(dao, "_run_helper", side_effect=RuntimeError("OSStatus error -34018")):
                diagnostics = dao.diagnose()

        self.assertFalse(diagnostics.production_ready)
        self.assertIn("-34018", diagnostics.summary)
        self.assertTrue(any("login keychain" in item for item in diagnostics.advice))


if __name__ == "__main__":
    unittest.main()
