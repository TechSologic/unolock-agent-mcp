from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.serialization import load_der_public_key

from unolock_mcp.tpm.test_tpm import TestTpmDao


class TestTpmDaoTest(unittest.TestCase):
    def test_create_key_persists_and_signs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dao = TestTpmDao(Path(temp_dir))
            created = dao.create_key("agent-aid")
            signature = dao.sign("agent-aid", b"challenge")

            public_key = load_der_public_key(created.public_key)
            self.assertIsInstance(public_key, ec.EllipticCurvePublicKey)
            self.assertEqual(len(signature), 64)
            der_signature = encode_dss_signature(
                int.from_bytes(signature[:32], "big"),
                int.from_bytes(signature[32:], "big"),
            )
            public_key.verify(der_signature, b"challenge", ec.ECDSA(hashes.SHA256()))

            reloaded = TestTpmDao(Path(temp_dir))
            self.assertEqual(reloaded.get_public_key("agent-aid"), created.public_key)

    def test_diagnose_reports_test_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dao = TestTpmDao(Path(temp_dir))
            diagnostics = dao.diagnose()
            self.assertEqual(diagnostics.provider_name, "test")
            self.assertIn("persisted_key_count", diagnostics.details)
            self.assertIsInstance(diagnostics.advice, list)


if __name__ == "__main__":
    unittest.main()
