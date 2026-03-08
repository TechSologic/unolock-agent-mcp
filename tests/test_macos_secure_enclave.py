from __future__ import annotations

import unittest
from pathlib import Path

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

    def test_normalize_signature_converts_der_to_raw(self) -> None:
        r = int.from_bytes(bytes([3] * 32), "big")
        s = int.from_bytes(bytes([4] * 32), "big")
        der = encode_dss_signature(r, s)
        raw = MacSecureEnclaveDao._normalize_signature(der)
        self.assertEqual(raw[:32], bytes([3] * 32))
        self.assertEqual(raw[32:], bytes([4] * 32))


if __name__ == "__main__":
    unittest.main()
