from __future__ import annotations

import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from unolock_mcp import __version__ as MCP_VERSION

GITHUB_REPO = "TechSologic/unolock-agent-mcp"
LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"


@dataclass(frozen=True)
class RuntimeVersionInfo:
    install_channel: str
    package_version: str
    wrapper_version: str | None
    binary_release_version: str | None
    current_version: str


def detect_runtime_version_info(env: dict[str, str] | None = None) -> RuntimeVersionInfo:
    current_env = env or os.environ
    wrapper_version = _normalize_version(current_env.get("UNOLOCK_AGENT_MCP_WRAPPER_VERSION"))
    binary_release_version = _normalize_version(current_env.get("UNOLOCK_AGENT_MCP_BINARY_VERSION"))
    install_channel = current_env.get("UNOLOCK_AGENT_MCP_INSTALL_CHANNEL") or _default_install_channel()
    current_version = binary_release_version or wrapper_version or _normalize_version(MCP_VERSION) or MCP_VERSION
    return RuntimeVersionInfo(
        install_channel=install_channel,
        package_version=_normalize_version(MCP_VERSION) or MCP_VERSION,
        wrapper_version=wrapper_version,
        binary_release_version=binary_release_version,
        current_version=current_version,
    )


def fetch_latest_release_version(
    *,
    api_url: str = LATEST_RELEASE_API_URL,
    timeout: float = 3.5,
) -> tuple[str, str]:
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "unolock-agent-mcp-update-check",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf8"))
    tag_name = payload.get("tag_name")
    if not isinstance(tag_name, str) or not tag_name.strip():
        raise ValueError("GitHub latest release payload did not include tag_name")
    html_url = payload.get("html_url")
    latest_version = _normalize_version(tag_name) or tag_name.strip()
    release_url = html_url.strip() if isinstance(html_url, str) and html_url.strip() else f"{RELEASES_URL}/tag/v{latest_version}"
    return latest_version, release_url


def get_update_status(
    *,
    env: dict[str, str] | None = None,
    api_url: str = LATEST_RELEASE_API_URL,
    timeout: float = 3.5,
) -> dict[str, Any]:
    runtime = detect_runtime_version_info(env)
    payload: dict[str, Any] = {
        "ok": True,
        "update_policy": "runner_managed",
        "supports_in_place_self_update": False,
        "install_channel": runtime.install_channel,
        "current_version": runtime.current_version,
        "package_version": runtime.package_version,
        "wrapper_version": runtime.wrapper_version,
        "binary_release_version": runtime.binary_release_version,
        "release_url": RELEASES_URL,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        latest_version, release_url = fetch_latest_release_version(api_url=api_url, timeout=timeout)
    except Exception as exc:
        payload.update(
            {
                "ok": False,
                "reason": "update_check_failed",
                "message": f"Could not check the latest UnoLock Agent MCP release: {exc}",
                "recommended_action": _recommended_action(runtime, update_available=None),
            }
        )
        return payload

    update_available = _is_version_newer(latest_version, runtime.current_version)
    payload.update(
        {
            "latest_version": latest_version,
            "update_available": update_available,
            "release_url": release_url,
            "recommended_action": _recommended_action(runtime, update_available=update_available, latest_version=latest_version),
        }
    )
    return payload


def _recommended_action(
    runtime: RuntimeVersionInfo,
    *,
    update_available: bool | None,
    latest_version: str | None = None,
) -> str:
    latest_suffix = f" to {latest_version}" if latest_version else ""
    if runtime.install_channel == "npm-wrapper":
        if update_available is False:
            return (
                "No update action is needed. Restart the MCP runner when convenient; the npm wrapper will keep "
                "checking GitHub Releases for newer stable binaries."
            )
        return (
            "Restart the MCP runner and relaunch with `npx -y @techsologic/unolock-agent-mcp@latest` so the npm wrapper "
            f"can fetch the latest stable binary{latest_suffix}. Prefer doing this between tasks, not during an active flow."
        )
    if runtime.install_channel == "release-binary":
        if update_available is False:
            return "No update action is needed. Keep using the current release binary."
        return (
            "Download the latest GitHub Release binary, replace the current executable, and restart the MCP runner. "
            "Do this between tasks so in-memory PINs and sessions can be re-established cleanly."
        )
    if runtime.install_channel == "python-package":
        if update_available is False:
            return "No update action is needed. Keep using the current Python package installation."
        return (
            "Upgrade the Python package in the environment that launches the MCP, for example "
            "`pipx upgrade unolock-agent-mcp`, then restart the MCP runner."
        )
    return (
        "The MCP should not replace itself while running. Update it through the wrapper, package manager, or release "
        "binary path that installed it, then restart the runner."
    )


def _default_install_channel() -> str:
    if getattr(sys, "frozen", False):
        return "release-binary"
    return "python-package"


def _normalize_version(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[1:] if normalized.startswith("v") else normalized


def _version_key(value: str) -> tuple[int, ...] | None:
    normalized = _normalize_version(value)
    if not normalized:
        return None
    parts = normalized.split(".")
    numbers: list[int] = []
    for part in parts:
        digits = ""
        for char in part:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            return None
        numbers.append(int(digits))
    return tuple(numbers)


def _is_version_newer(candidate: str, current: str) -> bool:
    candidate_key = _version_key(candidate)
    current_key = _version_key(current)
    if candidate_key is None or current_key is None:
        return _normalize_version(candidate) != _normalize_version(current)
    max_len = max(len(candidate_key), len(current_key))
    padded_candidate = candidate_key + (0,) * (max_len - len(candidate_key))
    padded_current = current_key + (0,) * (max_len - len(current_key))
    return padded_candidate > padded_current
