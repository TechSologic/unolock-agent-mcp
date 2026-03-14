from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unolock_mcp.runtime import (
    _platform_env_var,
    _platform_lib_dir_name,
    _platform_search_names,
    configure_frozen_oqs_runtime,
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


if __name__ == "__main__":
    unittest.main()
