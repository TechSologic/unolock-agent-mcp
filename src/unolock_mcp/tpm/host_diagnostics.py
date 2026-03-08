from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from .base import TpmDiagnostics


def detect_host_tpm_state(provider_name: str, *, production_ready: bool) -> TpmDiagnostics:
    system = platform.system().lower()
    machine = platform.machine().lower()
    release = platform.release().lower()
    details: dict[str, object] = {
        "os": system,
        "machine": machine,
        "release": release,
    }
    advice: list[str] = []
    available = False
    summary = "No working TPM/vTPM detected."

    if system == "linux":
        device_paths = ["/dev/tpmrm0", "/dev/tpm0"]
        existing_devices = [path for path in device_paths if Path(path).exists()]
        details["device_paths"] = device_paths
        details["existing_devices"] = existing_devices
        details["tpm2_tools_present"] = shutil.which("tpm2_getcap") is not None
        is_wsl = "microsoft" in release or "WSL_INTEROP" in os.environ
        details["is_wsl"] = is_wsl
        available = len(existing_devices) > 0
        if available:
            summary = f"Detected TPM device(s): {', '.join(existing_devices)}."
        elif is_wsl:
            summary = "Running under WSL without a Linux TPM device."
            advice.append("Use native Linux, Windows, or a VM with vTPM for production UnoLock agent keys.")
        else:
            advice.append("Enable a physical TPM or attach a vTPM to this host or VM.")
            advice.append("On Linux, UnoLock expects a working TPM device such as /dev/tpmrm0.")

    elif system == "windows":
        result = _run_powershell_tpm_query()
        details["powershell_query"] = result
        available = bool(result.get("tpm_present")) and bool(result.get("tpm_ready"))
        if available:
            summary = "Windows reports a working TPM."
        else:
            summary = "Windows did not report a ready TPM."
            advice.append("Check Windows Security > Device security > Security processor details.")
            advice.append("If you are in a VM, enable vTPM in the VM configuration.")

    elif system == "darwin":
        summary = "macOS does not expose TPM/vTPM in the same way as Linux/Windows."
        advice.append("Use Secure Enclave support once UnoLock adds a macOS production TPM DAO.")
        advice.append("For now, use the MCP test TPM provider only for development.")
    else:
        summary = f"Unsupported host OS for TPM diagnostics: {system}."
        advice.append("Use Linux or Windows with a physical TPM or vTPM for production agent keys.")

    if provider_name == "test":
        advice.insert(0, "The active MCP provider is the test TPM DAO. It is not production-grade.")
        if not available:
            advice.append("You can keep using the test TPM provider for development while enabling TPM/vTPM for production later.")

    return TpmDiagnostics(
        provider_name=provider_name,
        provider_type="test" if provider_name == "test" else "hardware",
        production_ready=production_ready and available,
        available=available,
        summary=summary,
        details=details,
        advice=advice,
    )


def _run_powershell_tpm_query() -> dict[str, object]:
    powershell = shutil.which("powershell") or shutil.which("powershell.exe")
    if not powershell:
        return {"available": False, "reason": "powershell_not_found"}
    try:
        proc = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-Command",
                "Get-Tpm | Select-Object TpmPresent,TpmReady,ManufacturerIdTxt | ConvertTo-Json -Compress",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return {"available": False, "reason": type(exc).__name__, "error": str(exc)}
    stdout = proc.stdout.strip()
    if proc.returncode != 0 or not stdout:
        return {
            "available": False,
            "reason": "powershell_query_failed",
            "returncode": proc.returncode,
            "stderr": proc.stderr.strip(),
        }
    normalized = stdout.lower()
    return {
        "available": True,
        "raw": stdout,
        "tpm_present": "\"tpmpresent\":true" in normalized,
        "tpm_ready": "\"tpmready\":true" in normalized,
    }
