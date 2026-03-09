from __future__ import annotations

import os
import platform

from .base import TpmDao
from .linux_tpm import LinuxTpmDao
from .macos_secure_enclave import MacSecureEnclaveDao
from .test_tpm import TestTpmDao
from .windows_tpm import WindowsTpmDao


def create_tpm_dao(provider: str | None = None) -> TpmDao:
    selected = (provider or os.environ.get("UNOLOCK_TPM_PROVIDER") or "auto").strip().lower()
    allow_insecure = os.environ.get("UNOLOCK_ALLOW_INSECURE_PROVIDER", "").strip().lower() in {"1", "true", "yes"}
    if selected == "test":
        if not allow_insecure:
            raise ValueError(
                "UNOLOCK_TPM_PROVIDER=test requires UNOLOCK_ALLOW_INSECURE_PROVIDER=1. "
                "The test provider is for development only."
            )
        return TestTpmDao()
    if selected == "linux":
        return LinuxTpmDao()
    if selected == "mac":
        return MacSecureEnclaveDao()
    if selected == "windows":
        return WindowsTpmDao()
    if selected != "auto":
        raise ValueError("UNOLOCK_TPM_PROVIDER must be one of: auto, test, linux, mac, windows")

    system = platform.system().lower()
    if system == "windows":
        windows = WindowsTpmDao()
        if windows.diagnose().available:
            return windows
    if system == "linux" and _is_wsl():
        windows = WindowsTpmDao()
        if windows.diagnose().available:
            return windows
    if system == "linux":
        linux = LinuxTpmDao()
        if linux.diagnose().available:
            return linux
    if system == "darwin":
        mac = MacSecureEnclaveDao()
        if mac.diagnose().available:
            return mac
    if allow_insecure:
        return TestTpmDao()
    raise ValueError(
        "No production-ready UnoLock TPM/vTPM/platform provider is available on this host. "
        "For development only, set UNOLOCK_ALLOW_INSECURE_PROVIDER=1 to enable the test provider."
    )


def _is_wsl() -> bool:
    release = platform.release().lower()
    return "microsoft" in release or "wsl" in release
