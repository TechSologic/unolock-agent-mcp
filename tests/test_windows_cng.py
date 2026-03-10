from __future__ import annotations

import base64
import unittest

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.serialization import load_der_public_key

from unolock_mcp.tpm.windows_cng import WindowsCngDao


class WindowsCngDaoTest(unittest.TestCase):
    def test_public_blob_conversion_produces_spki_der(self) -> None:
        private_key = ec.generate_private_key(ec.SECP256R1())
        numbers = private_key.public_key().public_numbers()
        x = numbers.x.to_bytes(32, "big")
        y = numbers.y.to_bytes(32, "big")
        blob = b"ECS1" + (32).to_bytes(4, "little") + x + y
        der = WindowsCngDao._public_blob_to_spki_der(base64.b64encode(blob).decode("ascii"))
        public_key = load_der_public_key(der)
        self.assertEqual(public_key.key_size, 256)

    def test_normalize_signature_accepts_raw_p1363(self) -> None:
        signature = bytes(range(64))
        self.assertEqual(WindowsCngDao._normalize_signature(signature), signature)

    def test_normalize_signature_converts_der_to_raw(self) -> None:
        r = int.from_bytes(bytes([1] * 32), "big")
        s = int.from_bytes(bytes([2] * 32), "big")
        der = encode_dss_signature(r, s)
        raw = WindowsCngDao._normalize_signature(der)
        self.assertEqual(raw[:32], bytes([1] * 32))
        self.assertEqual(raw[32:], bytes([2] * 32))


if __name__ == "__main__":
    unittest.main()
