from __future__ import annotations

import base64
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from .base import CreatedKey, KeyBindingInfo, TpmDao, TpmDiagnostics


WINDOWS_TPM_HELPER = r"""
param(
  [Parameter(Mandatory=$true)][string]$Action,
  [string]$KeyName,
  [string]$ChallengeB64
)
$ErrorActionPreference = 'Stop'

function To-JsonOut($obj) {
  $obj | ConvertTo-Json -Compress -Depth 10
}

function New-PlatformProvider() {
  return New-Object System.Security.Cryptography.CngProvider 'Microsoft Platform Crypto Provider'
}

function New-BindingInfo() {
  return [ordered]@{
    protection = 'windows-tpm'
    exportable = $false
    attestation_supported = $false
    device_binding = 'hardware:windows-tpm'
  }
}

function Open-Key([string]$name) {
  return [System.Security.Cryptography.CngKey]::Open($name, (New-PlatformProvider))
}

function Create-Key([string]$name) {
  $p = New-Object System.Security.Cryptography.CngKeyCreationParameters
  $p.Provider = New-PlatformProvider
  $p.KeyUsage = [System.Security.Cryptography.CngKeyUsages]::Signing
  $p.ExportPolicy = [System.Security.Cryptography.CngExportPolicies]::None
  return [System.Security.Cryptography.CngKey]::Create([System.Security.Cryptography.CngAlgorithm]::ECDsaP256, $name, $p)
}

function Key-Exists([string]$name) {
  return [System.Security.Cryptography.CngKey]::Exists($name, (New-PlatformProvider))
}

function Export-PublicBlobB64($key) {
  $blob = $key.Export([System.Security.Cryptography.CngKeyBlobFormat]::EccPublicBlob)
  return [Convert]::ToBase64String($blob)
}

function Protect-Secret([string]$secretB64) {
  $secure = ConvertTo-SecureString -String $secretB64 -AsPlainText -Force
  return ConvertFrom-SecureString -SecureString $secure
}

function Unprotect-Secret([string]$secretB64) {
  $secure = ConvertTo-SecureString -String $secretB64
  $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  } finally {
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}

try {
  switch ($Action) {
    'diagnose' {
      $testName = 'UnoLockDiag-' + [guid]::NewGuid().ToString('N')
      $key = Create-Key $testName
      $publicBlobB64 = Export-PublicBlobB64 $key
      $key.Delete()
      To-JsonOut([ordered]@{
        ok = $true
        available = $true
        provider_name = 'windows-tpm'
        summary = 'Windows Platform Crypto Provider created a TPM-backed P-256 key.'
        binding_info = (New-BindingInfo)
        public_blob_b64 = $publicBlobB64
      })
      exit 0
    }
    'create-key' {
      if (Key-Exists $KeyName) {
        $key = Open-Key $KeyName
      } else {
        $key = Create-Key $KeyName
      }
      To-JsonOut([ordered]@{
        ok = $true
        key_id = $KeyName
        public_blob_b64 = (Export-PublicBlobB64 $key)
        binding_info = (New-BindingInfo)
      })
      exit 0
    }
    'get-public-key' {
      $key = Open-Key $KeyName
      To-JsonOut([ordered]@{
        ok = $true
        public_blob_b64 = (Export-PublicBlobB64 $key)
      })
      exit 0
    }
    'sign' {
      $key = Open-Key $KeyName
      $ecdsa = [System.Security.Cryptography.ECDsaCng]::new($key)
      $bytes = [Convert]::FromBase64String($ChallengeB64)
      $signature = $ecdsa.SignData($bytes, [System.Security.Cryptography.HashAlgorithmName]::SHA256)
      To-JsonOut([ordered]@{
        ok = $true
        signature_b64 = ([Convert]::ToBase64String($signature))
      })
      exit 0
    }
    'delete-key' {
      if (Key-Exists $KeyName) {
        $key = Open-Key $KeyName
        $key.Delete()
      }
      To-JsonOut([ordered]@{
        ok = $true
        deleted = $KeyName
      })
      exit 0
    }
    'protect-secret' {
      To-JsonOut([ordered]@{
        ok = $true
        protected_secret_b64 = (Protect-Secret $ChallengeB64)
      })
      exit 0
    }
    'unprotect-secret' {
      To-JsonOut([ordered]@{
        ok = $true
        secret_b64 = (Unprotect-Secret $ChallengeB64)
      })
      exit 0
    }
    default {
      throw "Unknown action: $Action"
    }
  }
} catch {
  To-JsonOut([ordered]@{
    ok = $false
    error = $_.Exception.Message
    action = $Action
  })
  exit 1
}
"""


class WindowsTpmDao(TpmDao):
    def __init__(self, powershell_path: str | None = None) -> None:
        self._powershell = powershell_path or shutil.which("powershell.exe") or shutil.which("powershell")

    def provider_name(self) -> str:
        return "windows-tpm"

    def create_key(self, key_id: str) -> CreatedKey:
        payload = self._run_helper("create-key", key_id=key_id)
        return CreatedKey(
            key_id=str(payload["key_id"]),
            public_key=self._public_blob_to_spki_der(str(payload["public_blob_b64"])),
            binding_info=self._binding_info_from_payload(payload["binding_info"]),
        )

    def get_public_key(self, key_id: str) -> bytes:
        payload = self._run_helper("get-public-key", key_id=key_id)
        return self._public_blob_to_spki_der(str(payload["public_blob_b64"]))

    def sign(self, key_id: str, challenge: bytes) -> bytes:
        payload = self._run_helper(
            "sign",
            key_id=key_id,
            challenge_b64=base64.b64encode(challenge).decode("ascii"),
        )
        signature = base64.b64decode(str(payload["signature_b64"]).encode("ascii"))
        return self._normalize_signature(signature)

    def get_binding_info(self, key_id: str) -> KeyBindingInfo:
        created = self.create_key(key_id)
        return created.binding_info

    def delete_key(self, key_id: str) -> None:
        self._run_helper("delete-key", key_id=key_id)

    def store_secret(self, secret_id: str, secret: bytes) -> None:
        encrypted = self._run_helper(
            "protect-secret",
            challenge_b64=base64.b64encode(secret).decode("ascii"),
        )
        self._secret_path(secret_id).write_text(str(encrypted["protected_secret_b64"]), encoding="utf8")

    def load_secret(self, secret_id: str) -> bytes | None:
        path = self._secret_path(secret_id)
        if not path.exists():
            return None
        payload = self._run_helper(
            "unprotect-secret",
            challenge_b64=path.read_text(encoding="utf8").strip(),
        )
        return base64.b64decode(str(payload["secret_b64"]).encode("ascii"))

    def delete_secret(self, secret_id: str) -> None:
        self._secret_path(secret_id).unlink(missing_ok=True)

    def diagnose(self) -> TpmDiagnostics:
        details = {
            "os": platform.system().lower(),
            "release": platform.release().lower(),
            "powershell_path": self._powershell,
            "is_wsl": _is_wsl(),
        }
        advice: list[str] = []
        if not self._powershell:
            advice.append("Install or expose powershell.exe so WSL can call the Windows TPM helper.")
            return TpmDiagnostics(
                provider_name=self.provider_name(),
                provider_type="hardware",
                production_ready=False,
                available=False,
                summary="Windows PowerShell is not available from this environment.",
                details=details,
                advice=advice,
            )
        try:
            payload = self._run_helper("diagnose")
            details["binding_info"] = payload.get("binding_info")
            if _is_wsl():
                advice.append("WSL can use the Windows host TPM through the Windows TPM helper.")
            advice.append("Keep this provider selected for WSL production use when the helper is working.")
            return TpmDiagnostics(
                provider_name=self.provider_name(),
                provider_type="hardware",
                production_ready=True,
                available=True,
                summary=str(payload.get("summary", "Windows TPM provider is available.")),
                details=details,
                advice=advice,
            )
        except Exception as exc:
            advice.append("Make sure the Windows host has a working TPM or vTPM.")
            advice.append("If you are in WSL2, this provider is preferred over Linux TPM because WSL usually lacks /dev/tpmrm0.")
            advice.append("If the Windows helper still cannot create a key, use the test TPM provider only for development.")
            details["error"] = str(exc)
            return TpmDiagnostics(
                provider_name=self.provider_name(),
                provider_type="hardware",
                production_ready=False,
                available=False,
                summary="Windows TPM helper could not create a TPM-backed key.",
                details=details,
                advice=advice,
            )

    def _run_helper(
        self,
        action: str,
        *,
        key_id: str | None = None,
        challenge_b64: str | None = None,
    ) -> dict[str, object]:
        if not self._powershell:
            raise RuntimeError("powershell.exe is not available")
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf8") as handle:
            script_path = Path(handle.name)
            handle.write(WINDOWS_TPM_HELPER)
        try:
            command = [
                self._powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-Action",
                action,
            ]
            if key_id is not None:
                command.extend(["-KeyName", key_id])
            if challenge_b64 is not None:
                command.extend(["-ChallengeB64", challenge_b64])
            proc = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            if not stdout:
                raise RuntimeError(stderr or "Windows TPM helper returned no output")
            payload = json.loads(stdout)
            if proc.returncode != 0 or not payload.get("ok"):
                raise RuntimeError(str(payload.get("error") or stderr or "Windows TPM helper failed"))
            return payload
        finally:
            script_path.unlink(missing_ok=True)

    def _binding_info_from_payload(self, payload: object) -> KeyBindingInfo:
        if not isinstance(payload, dict):
            raise TypeError("Invalid binding info payload from Windows TPM helper")
        return KeyBindingInfo(
            protection=str(payload.get("protection", "windows-tpm")),
            exportable=bool(payload.get("exportable", False)),
            attestation_supported=bool(payload.get("attestation_supported", False)),
            device_binding=str(payload.get("device_binding", "hardware:windows-tpm")),
        )

    @staticmethod
    def _public_blob_to_spki_der(public_blob_b64: str) -> bytes:
        blob = base64.b64decode(public_blob_b64.encode("ascii"))
        if len(blob) < 8:
            raise ValueError("Invalid EccPublicBlob")
        cb_key = int.from_bytes(blob[4:8], "little")
        x = blob[8:8 + cb_key]
        y = blob[8 + cb_key:8 + (2 * cb_key)]
        if len(x) != cb_key or len(y) != cb_key:
            raise ValueError("Invalid EccPublicBlob coordinate lengths")
        numbers = ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, "big"),
            int.from_bytes(y, "big"),
            ec.SECP256R1(),
        )
        public_key = numbers.public_key()
        return public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    @staticmethod
    def _normalize_signature(signature: bytes) -> bytes:
        if len(signature) == 64:
            return signature
        r, s = decode_dss_signature(signature)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    @staticmethod
    def _secret_path(secret_id: str) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in secret_id)
        path = Path.home() / ".config" / "unolock-agent-mcp" / "windows-tpm"
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{safe_name}.secret"


def _is_wsl() -> bool:
    release = platform.release().lower()
    return "microsoft" in release or "WSL_INTEROP" in os.environ
