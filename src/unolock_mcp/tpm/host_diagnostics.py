from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from .base import TpmDiagnostics

AGENTIC_SAFE_ACCESS_DOC = "https://safe.unolock.com/docs/features/agentic-safe-access/"
CONNECTING_AGENT_DOC = "https://safe.unolock.com/docs/howto/connecting-an-ai-agent/"


def detect_host_tpm_state(provider_name: str, *, production_ready: bool) -> TpmDiagnostics:
    normalized_provider = _normalize_provider_name(provider_name)
    system = platform.system().lower()
    machine = platform.machine().lower()
    release = platform.release().lower()
    environment = detect_host_environment(system=system, release=release)
    details: dict[str, object] = {
        "os": system,
        "machine": machine,
        "release": release,
        "environment": environment,
        "docs": {
            "agentic_safe_access": AGENTIC_SAFE_ACCESS_DOC,
            "connecting_an_ai_agent": CONNECTING_AGENT_DOC,
        },
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
        elif bool(environment.get("is_container")):
            runtime = str(environment.get("container_runtime") or "container")
            summary = f"Running inside {runtime} without a visible TPM/vTPM device."
            advice.append(
                f"This host looks like a {runtime} environment. Plain containers usually do not expose TPM/vTPM "
                "or a strong platform key store by default."
            )
            advice.append(
                "Use a host or VM with TPM/vTPM, or arrange a host-backed signer path instead of relying on the "
                "container alone."
            )
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
        advice.append("If needed, the MCP can fall back to the software provider with reduced assurance.")
    else:
        summary = f"Unsupported host OS for TPM diagnostics: {system}."
        advice.append("Use Linux or Windows with a physical TPM or vTPM for production agent keys.")

    if normalized_provider == "software":
        advice.insert(0, "The active MCP provider is using software-backed local key protection, not a device-bound or platform-backed key store.")
        if system == "darwin":
            summary = "macOS could not use Secure Enclave or a non-exportable Keychain-backed key, so the MCP is using the software provider."
            advice.insert(1, "On macOS, the MCP prefers Secure Enclave first and then a non-exportable Keychain-backed key before using the software fallback.")
        if not available:
            advice.append("You can keep using the software provider if needed, but the MCP should treat it as reduced assurance until stronger host protection is available.")

    if not available:
        advice.append(
            f"For current setup guidance, see {CONNECTING_AGENT_DOC} and {AGENTIC_SAFE_ACCESS_DOC}"
        )

    return TpmDiagnostics(
        provider_name=normalized_provider,
        provider_type="software" if normalized_provider == "software" else "hardware",
        production_ready=production_ready and available,
        available=available,
        summary=summary,
        details=details,
        advice=advice,
    )


def _normalize_provider_name(provider_name: str) -> str:
    if provider_name == "test":
        return "software"
    return provider_name


def detect_host_environment(*, system: str | None = None, release: str | None = None) -> dict[str, object]:
    host_system = system or platform.system().lower()
    host_release = release or platform.release().lower()
    environment: dict[str, object] = {
        "is_container": False,
        "container_runtime": "",
        "is_wsl": False,
    }

    if host_system == "linux":
        environment["is_wsl"] = "microsoft" in host_release or "WSL_INTEROP" in os.environ
        container_runtime = _detect_linux_container_runtime()
        if container_runtime:
            environment["is_container"] = True
            environment["container_runtime"] = container_runtime

    return environment


def _detect_linux_container_runtime() -> str:
    if Path("/.dockerenv").exists():
        return "docker"
    if Path("/run/.containerenv").exists():
        return "podman"

    cgroup_candidates = [Path("/proc/1/cgroup"), Path("/proc/self/cgroup")]
    for cgroup_path in cgroup_candidates:
        if not cgroup_path.exists():
            continue
        try:
            text = cgroup_path.read_text(encoding="utf8", errors="ignore").lower()
        except OSError:
            continue
        if "docker" in text:
            return "docker"
        if "containerd" in text:
            return "containerd"
        if "kubepods" in text or "kube" in text:
            return "kubernetes"
        if "podman" in text:
            return "podman"
        if "lxc" in text:
            return "lxc"
    return ""


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
