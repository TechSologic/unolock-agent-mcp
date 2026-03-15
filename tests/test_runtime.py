from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unolock_mcp.runtime import (
    _candidate_ca_bundle_paths,
    _platform_env_var,
    _platform_lib_dir_name,
    _platform_search_names,
    configure_frozen_oqs_runtime,
    configure_tls_runtime,
)


class FrozenOqsRuntimeTest(unittest.TestCase):
    def test_noop_when_not_frozen(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.frozen", False, create=True):
                configure_frozen_oqs_runtime()
        self.assertNotIn("OQS_INSTALL_PATH", os.environ)

    def test_sets_oqs_install_path_from_frozen_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_root = Path(tmpdir)
            libdir = bundle_root / "nested"
            libdir.mkdir(parents=True, exist_ok=True)
            libfile = libdir / _platform_search_names()[0]
            libfile.write_bytes(b"fake-oqs")

            with patch.dict(os.environ, {}, clear=True):
                with patch("sys.frozen", True, create=True), patch("sys._MEIPASS", tmpdir, create=True):
                    configure_frozen_oqs_runtime()
                    install_root = os.environ.get("OQS_INSTALL_PATH")
                    self.assertIsNotNone(install_root)
                    runtime_copy = Path(install_root) / _platform_lib_dir_name() / libfile.name
                    self.assertTrue(runtime_copy.exists())
                    self.assertIn(str(runtime_copy.parent), os.environ.get(_platform_env_var(), ""))


class TlsRuntimeTest(unittest.TestCase):
    def test_sets_tls_bundle_from_candidate_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = Path(tmpdir) / "cacert.pem"
            bundle.write_text("fake", encoding="utf8")

            with patch.dict(os.environ, {}, clear=True):
                with patch("unolock_mcp.runtime._candidate_ca_bundle_paths", return_value=(bundle,)):
                    configure_tls_runtime()

                self.assertEqual(os.environ.get("SSL_CERT_FILE"), str(bundle))
                self.assertEqual(os.environ.get("REQUESTS_CA_BUNDLE"), str(bundle))

    def test_does_not_override_existing_tls_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = str(Path(tmpdir) / "existing.pem")
            with patch.dict(os.environ, {"SSL_CERT_FILE": existing}, clear=True):
                with patch("unolock_mcp.runtime._candidate_ca_bundle_paths", return_value=()):
                    configure_tls_runtime()

                self.assertEqual(os.environ.get("SSL_CERT_FILE"), existing)
                self.assertIsNone(os.environ.get("REQUESTS_CA_BUNDLE"))


if __name__ == "__main__":
    unittest.main()
