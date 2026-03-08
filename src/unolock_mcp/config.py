from __future__ import annotations

import json
import os
import re
from pathlib import Path

from unolock_mcp.domain.models import UnoLockConfig


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_signing_key(default_root: Path | None = None) -> str | None:
    root = default_root or repo_root()
    env_path = root / "client" / "src" / "environments" / "environment.local.ts"
    if not env_path.exists():
        return None
    content = env_path.read_text(encoding="utf8")
    match = re.search(r'serverPQSigningValidationKey:\s*"([^"]+)"', content)
    return match.group(1) if match else None


def load_app_version(default_root: Path | None = None) -> str | None:
    root = default_root or repo_root()
    package_path = root / "server" / "safe-server" / "package.json"
    if not package_path.exists():
        return None
    return json.loads(package_path.read_text(encoding="utf8"))["version"]


def load_unolock_config(
    *,
    base_url: str | None = None,
    app_version: str | None = None,
    signing_public_key_b64: str | None = None,
) -> UnoLockConfig:
    resolved_base_url = base_url or os.environ.get("UNOLOCK_BASE_URL") or "http://127.0.0.1:3000"
    resolved_app_version = app_version or os.environ.get("UNOLOCK_APP_VERSION") or load_app_version()
    resolved_signing_key = (
        signing_public_key_b64
        or os.environ.get("UNOLOCK_SIGNING_PUBLIC_KEY")
        or load_signing_key()
    )

    if not resolved_app_version:
        raise ValueError(
            "Missing UnoLock app version. Run inside the UnoLock repo or set UNOLOCK_APP_VERSION."
        )
    if not resolved_signing_key:
        raise ValueError(
            "Missing UnoLock signing public key. Run inside the UnoLock repo or set UNOLOCK_SIGNING_PUBLIC_KEY."
        )

    return UnoLockConfig(
        base_url=resolved_base_url,
        app_version=resolved_app_version,
        signing_public_key_b64=resolved_signing_key,
    )
