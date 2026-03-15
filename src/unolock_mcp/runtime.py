from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _platform_lib_dir_name() -> str:
    return "bin" if sys.platform.startswith("win") else "lib"


def _platform_search_names() -> tuple[str, ...]:
    if sys.platform.startswith("win"):
        return ("oqs.dll", "liboqs.dll")
    if sys.platform == "darwin":
        return ("liboqs.dylib",)
    return ("liboqs.so",)


def _platform_env_var() -> str:
    if sys.platform.startswith("win"):
        return "PATH"
    if sys.platform == "darwin":
        return "DYLD_LIBRARY_PATH"
    return "LD_LIBRARY_PATH"


def _candidate_ca_bundle_paths() -> tuple[Path, ...]:
    candidates: list[Path] = []
    try:
        import certifi  # type: ignore

        certifi_bundle = certifi.where()
        if certifi_bundle:
            candidates.append(Path(certifi_bundle))
    except Exception:
        pass

    candidates.extend(
        [
            Path("/etc/ssl/cert.pem"),
            Path("/etc/ssl/certs/ca-certificates.crt"),
            Path("/etc/pki/tls/certs/ca-bundle.crt"),
        ]
    )

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return tuple(unique)


def configure_tls_runtime() -> None:
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE"):
        return

    for candidate in _candidate_ca_bundle_paths():
        if not candidate.is_file():
            continue
        bundle_path = str(candidate)
        os.environ["SSL_CERT_FILE"] = bundle_path
        os.environ["REQUESTS_CA_BUNDLE"] = bundle_path
        return


def configure_frozen_oqs_runtime() -> None:
    if os.environ.get("OQS_INSTALL_PATH"):
        return
    if not getattr(sys, "frozen", False):
        return

    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return

    extracted_root = Path(meipass)
    candidates: list[Path] = []
    for pattern in _platform_search_names():
        candidates.extend(extracted_root.rglob(pattern))
    if not candidates:
        return

    install_root = Path(tempfile.mkdtemp(prefix="unolock-agent-mcp-oqs-"))
    runtime_dir = install_root / _platform_lib_dir_name()
    runtime_dir.mkdir(parents=True, exist_ok=True)

    for candidate in candidates:
        target = runtime_dir / candidate.name
        if not target.exists():
            shutil.copy2(candidate, target)

    os.environ["OQS_INSTALL_PATH"] = str(install_root)
    env_key = _platform_env_var()
    existing = os.environ.get(env_key, "")
    prefix = str(runtime_dir)
    os.environ[env_key] = prefix if not existing else f"{prefix}{os.pathsep}{existing}"

    atexit.register(shutil.rmtree, install_root, ignore_errors=True)
