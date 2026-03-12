from __future__ import annotations

import argparse
import os
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


def _prepare_windows_oqs_runtime(install_root: Path) -> None:
    if platform.system().lower() != "windows":
        return
    bin_dir = install_root / "bin"
    lib_dir = install_root / "lib"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("oqs.dll", "liboqs.dll"):
        target = bin_dir / name
        if target.exists():
            continue
        for source in (lib_dir / name, install_root / name):
            if source.exists():
                shutil.copy2(source, target)
                break


def _collect_oqs_runtime_binaries(install_root: Path) -> list[Path]:
    candidates: list[Path] = []
    system = platform.system().lower()
    if system == "windows":
        names = ("oqs.dll", "liboqs.dll")
        search_dirs = (install_root / "bin", install_root / "lib", install_root)
    elif system == "darwin":
        names = ("liboqs.dylib",)
        search_dirs = (install_root / "lib", install_root / "lib64", install_root)
    else:
        names = ("liboqs.so",)
        search_dirs = (install_root / "lib", install_root / "lib64", install_root)
    seen: set[Path] = set()
    for search_dir in search_dirs:
        for name in names:
            path = search_dir / name
            if path.exists() and path not in seen:
                seen.add(path)
                candidates.append(path)
    return candidates


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

    env = os.environ.copy()
    oqs_install_path = env.get("OQS_INSTALL_PATH")
    if oqs_install_path:
        install_root = Path(oqs_install_path)
        _prepare_windows_oqs_runtime(install_root)
        runtime_dirs = []
        if platform.system().lower() == "windows":
            runtime_dirs.extend(
                [
                    install_root / "bin",
                    install_root / "lib",
                ]
            )
            path_key = "PATH"
            separator = ";"
        else:
            runtime_dirs.extend(
                [
                    install_root / "lib",
                    install_root / "lib64",
                ]
            )
            path_key = "LD_LIBRARY_PATH" if platform.system().lower() == "linux" else "DYLD_LIBRARY_PATH"
            separator = ":"
        existing = env.get(path_key, "")
        additions = [str(path) for path in runtime_dirs if path.exists()]
        if additions:
            env[path_key] = separator.join(additions + ([existing] if existing else []))

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
    if oqs_install_path:
        for binary in _collect_oqs_runtime_binaries(Path(oqs_install_path)):
            cmd.extend(["--add-binary", f"{binary}{os.pathsep}."])
    else:
        cmd.extend(["--collect-binaries", "oqs"])
    subprocess.run(cmd, check=True, cwd=ROOT, env=env)
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
