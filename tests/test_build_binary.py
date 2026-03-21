from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_binary import _collect_oqs_runtime_binaries, binary_archive_name, build_binary


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
            patch("shutil.make_archive", return_value="/tmp/unolock-agent-linux-x86_64.tar.gz"),
            patch("shutil.rmtree"),
            patch("platform.system", return_value="Linux"),
        ):
            artifact = build_binary(clean=False)

        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIn("--runtime-hook", cmd)
        self.assertIn("--onedir", cmd)
        self.assertNotIn("--onefile", cmd)
        hook_index = cmd.index("--runtime-hook") + 1
        self.assertTrue(cmd[hook_index].endswith("scripts/pyinstaller_runtime_hook.py"))
        self.assertEqual(Path(artifact).name, "unolock-agent-linux-x86_64.tar.gz")

    def test_binary_archive_name_uses_platform_archive_suffix(self) -> None:
        with patch("platform.system", return_value="Linux"):
            with patch("platform.machine", return_value="x86_64"):
                self.assertEqual(binary_archive_name(), "unolock-agent-linux-x86_64.tar.gz")
        with patch("platform.system", return_value="Darwin"):
            with patch("platform.machine", return_value="arm64"):
                self.assertEqual(binary_archive_name(), "unolock-agent-macos-arm64.tar.gz")
        with patch("platform.system", return_value="Windows"):
            with patch("platform.machine", return_value="AMD64"):
                self.assertEqual(binary_archive_name(), "unolock-agent-windows-amd64.zip")


if __name__ == "__main__":
    unittest.main()
