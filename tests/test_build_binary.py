from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_binary import _collect_oqs_runtime_binaries


class BuildBinaryTest(unittest.TestCase):
    def test_collects_windows_oqs_binaries_from_install_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            lib_dir = root / "lib"
            bin_dir.mkdir()
            lib_dir.mkdir()
            oqs_dll = bin_dir / "oqs.dll"
            liboqs_dll = lib_dir / "liboqs.dll"
            oqs_dll.write_bytes(b"oqs")
            liboqs_dll.write_bytes(b"liboqs")
            with patch("platform.system", return_value="Windows"):
                binaries = _collect_oqs_runtime_binaries(root)
            self.assertEqual(binaries, [oqs_dll, liboqs_dll])


if __name__ == "__main__":
    unittest.main()
