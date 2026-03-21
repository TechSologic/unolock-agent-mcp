from __future__ import annotations

import os
import builtins
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
    def test_prefers_system_trust_store_when_available(self) -> None:
        class _Truststore:
            def __init__(self) -> None:
                self.injected = False

            def inject_into_ssl(self) -> None:
                self.injected = True

        truststore = _Truststore()
        with patch.dict(os.environ, {}, clear=True):
            with patch.dict("sys.modules", {"truststore": truststore}):
                configure_tls_runtime()

            self.assertTrue(truststore.injected)
            self.assertIsNone(os.environ.get("SSL_CERT_FILE"))
            self.assertIsNone(os.environ.get("REQUESTS_CA_BUNDLE"))

    def test_sets_tls_bundle_from_candidate_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = Path(tmpdir) / "cacert.pem"
            bundle.write_text("fake", encoding="utf8")

            with patch.dict(os.environ, {}, clear=True):
                with patch.dict("sys.modules", {"truststore": None}):
                    with patch("unolock_mcp.runtime._candidate_ca_bundle_paths", return_value=(bundle,)):
                        configure_tls_runtime()

                self.assertEqual(os.environ.get("SSL_CERT_FILE"), str(bundle))
                self.assertEqual(os.environ.get("REQUESTS_CA_BUNDLE"), str(bundle))

    def test_falls_back_to_tls_bundle_when_truststore_import_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = Path(tmpdir) / "cacert.pem"
            bundle.write_text("fake", encoding="utf8")
            original_import = builtins.__import__

            with patch.dict(os.environ, {}, clear=True):
                with patch("builtins.__import__", side_effect=self._import_without_truststore(original_import)):
                        with patch("unolock_mcp.runtime._candidate_ca_bundle_paths", return_value=(bundle,)):
                            configure_tls_runtime()

                self.assertEqual(os.environ.get("SSL_CERT_FILE"), str(bundle))
                self.assertEqual(os.environ.get("REQUESTS_CA_BUNDLE"), str(bundle))

    def _import_without_truststore(self, original_import):
        def _import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "truststore":
                raise ImportError("missing truststore")
            return original_import(name, globals, locals, fromlist, level)

        return _import

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
