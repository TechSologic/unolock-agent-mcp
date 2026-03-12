from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_binary import _collect_oqs_runtime_binaries, build_binary


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

    def test_build_binary_uses_runtime_hook(self) -> None:
        commands: list[list[str]] = []

        def fake_run(cmd, check, cwd, env):
            commands.append(cmd)

        with (
            patch("shutil.which", return_value="pyinstaller"),
            patch("subprocess.run", side_effect=fake_run),
            patch("platform.system", return_value="Linux"),
        ):
            build_binary(clean=False)

        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIn("--runtime-hook", cmd)
        hook_index = cmd.index("--runtime-hook") + 1
        self.assertTrue(cmd[hook_index].endswith("scripts/pyinstaller_runtime_hook.py"))


if __name__ == "__main__":
    unittest.main()
