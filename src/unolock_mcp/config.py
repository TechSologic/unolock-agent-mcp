from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

from unolock_mcp.domain.models import UnoLockConfig, UnoLockResolvedConfig


# Bundled client/runtime compatibility version used when the deployment host does
# not publish appVersion metadata. The signing/PQ key remains host-specific.
BUNDLED_UNOLOCK_APP_VERSION = "0.20.21"
APP_NAME = "unolock-agent"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_state_dir() -> Path:
    override = os.environ.get("UNOLOCK_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return _platform_state_dir(APP_NAME)


def _platform_state_dir(app_name: str) -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / app_name
        return Path.home() / "AppData" / "Local" / app_name
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / app_name
    return Path.home() / ".config" / app_name


def default_config_path() -> Path:
    override = os.environ.get("UNOLOCK_CONFIG_FILE")
    if override:
        return Path(override).expanduser()
    return default_state_dir() / "config.json"


def repo_auto_discovery_enabled() -> bool:
    return os.environ.get("UNOLOCK_DISABLE_REPO_AUTO_DISCOVERY", "").strip().lower() not in {"1", "true", "yes"}


def load_config_file(config_path: Path | None = None) -> dict[str, str]:
    path = config_path or default_config_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf8"))
    if not isinstance(data, dict):
        raise ValueError(f"UnoLock config file must contain a JSON object: {path}")
    normalized: dict[str, str] = {}
    for key in ("base_url", "transparency_origin", "app_version", "signing_public_key_b64"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            normalized[key] = value.strip()
    return normalized


def is_local_base_url(base_url: str | None) -> bool:
    if not base_url:
        return True
    hostname = (urlparse(base_url).hostname or "").lower()
    return hostname in {"", "localhost", "127.0.0.1", "0.0.0.0"} or hostname.endswith(".local")


def derive_transparency_origin(base_url: str | None) -> str | None:
    if is_local_base_url(base_url):
        return None
    parsed = urlparse(base_url or "")
    if not parsed.scheme or not parsed.hostname:
        return None
    hostname = parsed.hostname
    if hostname.startswith("api."):
        hostname = hostname[4:]
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{hostname}{port}"


def derive_api_base_url(site_origin: str | None) -> str | None:
    if not site_origin:
        return None
    parsed = urlparse(site_origin)
    if not parsed.scheme or not parsed.hostname:
        return None
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "127.0.0.1", "0.0.0.0"} or hostname.endswith(".local"):
        return "http://127.0.0.1:3000"
    if hostname.startswith("safe."):
        api_host = f"api.{hostname}"
    elif hostname.startswith("api."):
        api_host = hostname
    else:
        api_host = f"api.{hostname}"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{api_host}{port}"


def should_fetch_transparency_metadata(
    *,
    transparency_origin: str | None,
    transparency_source: str | None,
    needs_app_version: bool,
    needs_signing_key: bool,
) -> bool:
    if not transparency_origin or (not needs_app_version and not needs_signing_key):
        return False
    return not is_local_base_url(transparency_origin)


def fetch_transparency_metadata(transparency_origin: str, timeout: float = 10.0) -> dict[str, str]:
    latest_url = urljoin(transparency_origin.rstrip("/") + "/", "transparency/latest.json")
    with urlopen(latest_url, timeout=timeout) as response:
        latest = json.load(response)
    build_info_path = latest.get("buildInfo")
    if not isinstance(build_info_path, str) or not build_info_path.strip():
        raise ValueError(f"Hosted transparency metadata is missing buildInfo: {latest_url}")
    build_info_url = urljoin(transparency_origin.rstrip("/") + "/", build_info_path)
    with urlopen(build_info_url, timeout=timeout) as response:
        build_info = json.load(response)
    environment_snapshot = build_info.get("environmentSnapshot") or {}
    signing_key = environment_snapshot.get("serverPQSigningValidationKey")
    release = build_info.get("release") or latest.get("release")
    metadata: dict[str, str] = {}
    if isinstance(release, str) and release.strip():
        metadata["app_version"] = release.strip()
    if isinstance(signing_key, str) and signing_key.strip():
        metadata["signing_public_key_b64"] = signing_key.strip()
    return metadata


def fetch_hosted_client_metadata(asset_origin: str, timeout: float = 10.0) -> dict[str, str]:
    client_metadata_url = urljoin(asset_origin.rstrip("/") + "/", "unolock-client.json")
    with urlopen(client_metadata_url, timeout=timeout) as response:
        client_metadata = json.load(response)
    app_version = client_metadata.get("appVersion")
    signing_key = client_metadata.get("serverPQValidationKey") or client_metadata.get("serverPQSigningValidationKey")
    metadata: dict[str, str] = {}
    if isinstance(app_version, str) and app_version.strip():
        metadata["app_version"] = app_version.strip()
    if isinstance(signing_key, str) and signing_key.strip():
        metadata["signing_public_key_b64"] = signing_key.strip()
    return metadata


def fetch_local_bundle_metadata(site_origin: str, timeout: float = 10.0) -> dict[str, str]:
    root_url = site_origin.rstrip("/") + "/"
    with urlopen(root_url, timeout=timeout) as response:
        html = response.read().decode("utf8", errors="ignore")

    main_match = re.search(r'src="([^"]*main[^"]*\.js)"', html)
    if not main_match:
        raise ValueError(f"Could not locate main.js in local UnoLock app: {root_url}")

    main_js_url = urljoin(root_url, main_match.group(1))
    with urlopen(main_js_url, timeout=timeout) as response:
        bundle = response.read().decode("utf8", errors="ignore")

    version_match = re.search(r"const version = ['\"]([^'\"]+)['\"]", bundle)
    signing_key_match = re.search(r'serverPQSigningValidationKey[:=]\s*"([^"]+)"', bundle)

    metadata: dict[str, str] = {}
    if version_match and version_match.group(1).strip():
        metadata["app_version"] = version_match.group(1).strip()
    if signing_key_match and signing_key_match.group(1).strip():
        metadata["signing_public_key_b64"] = signing_key_match.group(1).strip()
    return metadata


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


def resolve_unolock_config(
    *,
    base_url: str | None = None,
    transparency_origin: str | None = None,
    app_version: str | None = None,
    signing_public_key_b64: str | None = None,
) -> UnoLockResolvedConfig:
    config_file = load_config_file()
    sources: dict[str, str] = {}

    resolved_base_url = base_url
    if resolved_base_url:
        sources["base_url"] = "argument"
    elif os.environ.get("UNOLOCK_BASE_URL"):
        resolved_base_url = os.environ["UNOLOCK_BASE_URL"]
        sources["base_url"] = "env:UNOLOCK_BASE_URL"
    elif config_file.get("base_url"):
        resolved_base_url = config_file["base_url"]
        sources["base_url"] = f"file:{default_config_path()}"
    else:
        resolved_base_url = "http://127.0.0.1:3000"
        sources["base_url"] = "default"

    resolved_transparency_origin = transparency_origin
    if resolved_transparency_origin:
        sources["transparency_origin"] = "argument"
    elif os.environ.get("UNOLOCK_TRANSPARENCY_ORIGIN"):
        resolved_transparency_origin = os.environ["UNOLOCK_TRANSPARENCY_ORIGIN"]
        sources["transparency_origin"] = "env:UNOLOCK_TRANSPARENCY_ORIGIN"
    elif config_file.get("transparency_origin"):
        resolved_transparency_origin = config_file["transparency_origin"]
        sources["transparency_origin"] = f"file:{default_config_path()}"
    else:
        derived_origin = derive_transparency_origin(resolved_base_url)
        if derived_origin:
            resolved_transparency_origin = derived_origin
            sources["transparency_origin"] = "derived-from-base-url"

    hosted_metadata: dict[str, str] = {}
    hosted_metadata_source: str | None = None
    if should_fetch_transparency_metadata(
        transparency_origin=resolved_transparency_origin,
        transparency_source=sources.get("transparency_origin"),
        needs_app_version=not bool(app_version or os.environ.get("UNOLOCK_APP_VERSION") or config_file.get("app_version")),
        needs_signing_key=not bool(
            signing_public_key_b64
            or os.environ.get("UNOLOCK_SIGNING_PUBLIC_KEY")
            or config_file.get("signing_public_key_b64")
        ),
    ):
        try:
            hosted_metadata = fetch_hosted_client_metadata(resolved_transparency_origin)
            hosted_metadata_source = "hosted-client-metadata"
        except Exception:
            try:
                hosted_metadata = fetch_transparency_metadata(resolved_transparency_origin)
                hosted_metadata_source = "hosted-transparency"
            except Exception:
                hosted_metadata = {}
                hosted_metadata_source = None

    local_bundle_metadata: dict[str, str] = {}
    local_bundle_metadata_source: str | None = None
    if (
        resolved_transparency_origin
        and is_local_base_url(resolved_transparency_origin)
        and (
            not bool(app_version or os.environ.get("UNOLOCK_APP_VERSION") or config_file.get("app_version"))
            or not bool(
                signing_public_key_b64
                or os.environ.get("UNOLOCK_SIGNING_PUBLIC_KEY")
                or config_file.get("signing_public_key_b64")
            )
        )
    ):
        try:
            local_bundle_metadata = fetch_local_bundle_metadata(resolved_transparency_origin)
            local_bundle_metadata_source = "local-dev-bundle"
        except Exception:
            local_bundle_metadata = {}
            local_bundle_metadata_source = None

    resolved_app_version = app_version
    if resolved_app_version:
        sources["app_version"] = "argument"
    elif os.environ.get("UNOLOCK_APP_VERSION"):
        resolved_app_version = os.environ["UNOLOCK_APP_VERSION"]
        sources["app_version"] = "env:UNOLOCK_APP_VERSION"
    elif config_file.get("app_version"):
        resolved_app_version = config_file["app_version"]
        sources["app_version"] = f"file:{default_config_path()}"
    elif hosted_metadata.get("app_version"):
        resolved_app_version = hosted_metadata["app_version"]
        sources["app_version"] = f"{hosted_metadata_source}:{resolved_transparency_origin}"
    elif local_bundle_metadata.get("app_version"):
        resolved_app_version = local_bundle_metadata["app_version"]
        sources["app_version"] = f"{local_bundle_metadata_source}:{resolved_transparency_origin}"
    elif BUNDLED_UNOLOCK_APP_VERSION:
        resolved_app_version = BUNDLED_UNOLOCK_APP_VERSION
        sources["app_version"] = "bundled-default"
    elif repo_auto_discovery_enabled():
        loaded = load_app_version()
        if loaded:
            resolved_app_version = loaded
            sources["app_version"] = "repo-auto-discovery"

    resolved_signing_key = signing_public_key_b64
    if resolved_signing_key:
        sources["signing_public_key_b64"] = "argument"
    elif os.environ.get("UNOLOCK_SIGNING_PUBLIC_KEY"):
        resolved_signing_key = os.environ["UNOLOCK_SIGNING_PUBLIC_KEY"]
        sources["signing_public_key_b64"] = "env:UNOLOCK_SIGNING_PUBLIC_KEY"
    elif config_file.get("signing_public_key_b64"):
        resolved_signing_key = config_file["signing_public_key_b64"]
        sources["signing_public_key_b64"] = f"file:{default_config_path()}"
    elif hosted_metadata.get("signing_public_key_b64"):
        resolved_signing_key = hosted_metadata["signing_public_key_b64"]
        sources["signing_public_key_b64"] = f"{hosted_metadata_source}:{resolved_transparency_origin}"
    elif local_bundle_metadata.get("signing_public_key_b64"):
        resolved_signing_key = local_bundle_metadata["signing_public_key_b64"]
        sources["signing_public_key_b64"] = f"{local_bundle_metadata_source}:{resolved_transparency_origin}"
    elif repo_auto_discovery_enabled():
        loaded = load_signing_key()
        if loaded:
            resolved_signing_key = loaded
            sources["signing_public_key_b64"] = "repo-auto-discovery"

    return UnoLockResolvedConfig(
        base_url=resolved_base_url,
        transparency_origin=resolved_transparency_origin,
        app_version=resolved_app_version,
        signing_public_key_b64=resolved_signing_key,
        sources=sources,
    )


def load_unolock_config(
    *,
    base_url: str | None = None,
    transparency_origin: str | None = None,
    app_version: str | None = None,
    signing_public_key_b64: str | None = None,
) -> UnoLockConfig:
    resolved = resolve_unolock_config(
        base_url=base_url,
        transparency_origin=transparency_origin,
        app_version=app_version,
        signing_public_key_b64=signing_public_key_b64,
    )

    if not resolved.app_version:
        raise ValueError(
            "UnoLock does not know which Safe deployment to use yet. Submit a UnoLock Agent Key URL from the "
            "target Safe first, or configure a custom deployment override."
        )
    if not resolved.signing_public_key_b64:
        raise ValueError(
            "UnoLock does not know which Safe deployment to use yet. Submit a UnoLock Agent Key URL from the "
            "target Safe first, or configure a custom deployment override."
        )

    return UnoLockConfig(
        base_url=resolved.base_url or "http://127.0.0.1:3000",
        app_version=resolved.app_version,
        signing_public_key_b64=resolved.signing_public_key_b64,
    )
