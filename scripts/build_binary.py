from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "src" / "unolock_mcp" / "__main__.py"
DIST = ROOT / "dist"
BUILD = ROOT / "build" / "pyinstaller"


def platform_suffix() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        return f"macos-{machine}"
    if system == "windows":
        return f"windows-{machine}"
    return f"linux-{machine}"


def binary_name() -> str:
    return f"unolock-agent-mcp-{platform_suffix()}"


def build_binary(clean: bool = False) -> Path:
    pyinstaller = shutil.which("pyinstaller") or shutil.which("pyinstaller.exe")
    if not pyinstaller:
        raise SystemExit(
            "PyInstaller is not installed. Install it with: python3 -m pip install -e .[dev]"
        )
    if clean and BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)

    cmd = [
        pyinstaller,
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        binary_name(),
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        "--specpath",
        str(BUILD),
        "--paths",
        str(ROOT / "src"),
        "--hidden-import",
        "oqs",
        str(ENTRYPOINT),
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)
    suffix = ".exe" if platform.system().lower() == "windows" else ""
    return DIST / f"{binary_name()}{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a standalone UnoLock Agent MCP binary.")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    artifact = build_binary(clean=args.clean)
    print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
