from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import load_der_public_key

from .base import CreatedKey, KeyBindingInfo, TpmDao, TpmDiagnostics
from .host_diagnostics import detect_host_tpm_state


class LinuxTpmDao(TpmDao):
    """
    Linux TPM/vTPM provider backed by tpm2-tools.

    This implementation is intentionally conservative:
    - it only operates when Linux exposes a TPM device
    - it requires tpm2-tools on PATH
    - it recreates the primary parent as needed and reloads child blobs for use
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (Path.home() / ".config" / "unolock-agent-mcp" / "linux-tpm")
        self._path.mkdir(parents=True, exist_ok=True)

    def provider_name(self) -> str:
        return "linux-tpm"

    def create_key(self, key_id: str) -> CreatedKey:
        self._ensure_usable()
        existing_public = self._public_der_path(key_id)
        if existing_public.exists() and self._public_blob_path(key_id).exists() and self._private_blob_path(key_id).exists():
            return CreatedKey(
                key_id=key_id,
                public_key=existing_public.read_bytes(),
                binding_info=self.get_binding_info(key_id),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            primary_ctx = temp / "primary.ctx"
            pub_blob = temp / "key.pub"
            priv_blob = temp / "key.priv"
            pub_der = temp / "key.der"

            self._run(
                "tpm2_createprimary",
                "-Q",
                "-C",
                "o",
                "-G",
                "ecc",
                "-g",
                "sha256",
                "-c",
                str(primary_ctx),
            )
            self._run(
                "tpm2_create",
                "-Q",
                "-C",
                str(primary_ctx),
                "-G",
                "ecc:ecdsa-sha256",
                "-u",
                str(pub_blob),
                "-r",
                str(priv_blob),
                "-f",
                "der",
                "-o",
                str(pub_der),
            )

            self._public_blob_path(key_id).write_bytes(pub_blob.read_bytes())
            self._private_blob_path(key_id).write_bytes(priv_blob.read_bytes())
            self._public_der_path(key_id).write_bytes(pub_der.read_bytes())

        return CreatedKey(
            key_id=key_id,
            public_key=self._public_der_path(key_id).read_bytes(),
            binding_info=self.get_binding_info(key_id),
        )

    def get_public_key(self, key_id: str) -> bytes:
        public_path = self._public_der_path(key_id)
        if not public_path.exists():
            raise KeyError(key_id)
        return public_path.read_bytes()

    def sign(self, key_id: str, challenge: bytes) -> bytes:
        self._ensure_usable()
        if not self._public_blob_path(key_id).exists() or not self._private_blob_path(key_id).exists():
            raise KeyError(key_id)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            primary_ctx = temp / "primary.ctx"
            key_ctx = temp / "key.ctx"
            message = temp / "message.bin"
            sig = temp / "sig.bin"
            message.write_bytes(challenge)

            self._run(
                "tpm2_createprimary",
                "-Q",
                "-C",
                "o",
                "-G",
                "ecc",
                "-g",
                "sha256",
                "-c",
                str(primary_ctx),
            )
            self._run(
                "tpm2_load",
                "-Q",
                "-C",
                str(primary_ctx),
                "-u",
                str(self._public_blob_path(key_id)),
                "-r",
                str(self._private_blob_path(key_id)),
                "-c",
                str(key_ctx),
            )
            self._run(
                "tpm2_sign",
                "-Q",
                "-c",
                str(key_ctx),
                "-g",
                "sha256",
                "-s",
                "ecdsa",
                "-f",
                "plain",
                "-o",
                str(sig),
                str(message),
            )

            signature = sig.read_bytes()
            if len(signature) == 64:
                return signature
            r, s = decode_dss_signature(signature)
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    def get_binding_info(self, key_id: str) -> KeyBindingInfo:
        if not self._public_der_path(key_id).exists():
            raise KeyError(key_id)
        public = load_der_public_key(self._public_der_path(key_id).read_bytes())
        curve_name = getattr(getattr(public, "curve", None), "name", "unknown")
        return KeyBindingInfo(
            protection="tpm",
            exportable=False,
            attestation_supported=False,
            device_binding=f"hardware:{curve_name}",
        )

    def delete_key(self, key_id: str) -> None:
        self._public_blob_path(key_id).unlink(missing_ok=True)
        self._private_blob_path(key_id).unlink(missing_ok=True)
        self._public_der_path(key_id).unlink(missing_ok=True)

    def store_secret(self, secret_id: str, secret: bytes) -> None:
        self._ensure_usable()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            primary_ctx = temp / "primary.ctx"
            secret_input = temp / "secret.bin"
            pub_blob = temp / "secret.pub"
            priv_blob = temp / "secret.priv"
            secret_input.write_bytes(secret)

            self._run(
                "tpm2_createprimary",
                "-Q",
                "-C",
                "o",
                "-G",
                "ecc",
                "-g",
                "sha256",
                "-c",
                str(primary_ctx),
            )
            self._run(
                "tpm2_create",
                "-Q",
                "-C",
                str(primary_ctx),
                "-G",
                "keyedhash",
                "-i",
                str(secret_input),
                "-u",
                str(pub_blob),
                "-r",
                str(priv_blob),
            )
            self._secret_public_blob_path(secret_id).write_bytes(pub_blob.read_bytes())
            self._secret_private_blob_path(secret_id).write_bytes(priv_blob.read_bytes())

    def load_secret(self, secret_id: str) -> bytes | None:
        self._ensure_usable()
        pub_path = self._secret_public_blob_path(secret_id)
        priv_path = self._secret_private_blob_path(secret_id)
        if not pub_path.exists() or not priv_path.exists():
            return None

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            primary_ctx = temp / "primary.ctx"
            secret_ctx = temp / "secret.ctx"
            secret_output = temp / "secret.bin"

            self._run(
                "tpm2_createprimary",
                "-Q",
                "-C",
                "o",
                "-G",
                "ecc",
                "-g",
                "sha256",
                "-c",
                str(primary_ctx),
            )
            self._run(
                "tpm2_load",
                "-Q",
                "-C",
                str(primary_ctx),
                "-u",
                str(pub_path),
                "-r",
                str(priv_path),
                "-c",
                str(secret_ctx),
            )
            self._run(
                "tpm2_unseal",
                "-Q",
                "-c",
                str(secret_ctx),
                "-o",
                str(secret_output),
            )
            return secret_output.read_bytes()

    def delete_secret(self, secret_id: str) -> None:
        self._secret_public_blob_path(secret_id).unlink(missing_ok=True)
        self._secret_private_blob_path(secret_id).unlink(missing_ok=True)

    def diagnose(self) -> TpmDiagnostics:
        diagnostics = detect_host_tpm_state(self.provider_name(), production_ready=True)
        details = dict(diagnostics.details)
        details["key_store_path"] = str(self._path)
        details["persisted_key_count"] = len(list(self._path.glob("*.pubblob")))
        advice = list(diagnostics.advice)
        if not diagnostics.available:
            advice.append("Install tpm2-tools and expose a working TPM/vTPM device before forcing the linux-tpm provider.")
        return TpmDiagnostics(
            provider_name=diagnostics.provider_name,
            provider_type=diagnostics.provider_type,
            production_ready=diagnostics.production_ready,
            available=diagnostics.available,
            summary=diagnostics.summary,
            details=details,
            advice=advice,
        )

    def _ensure_usable(self) -> None:
        diagnostics = self.diagnose()
        if not diagnostics.available:
            raise RuntimeError(
                f"linux-tpm provider is not usable: {diagnostics.summary} Advice: {' '.join(diagnostics.advice)}"
            )

    def _run(self, *command: str) -> None:
        proc = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            stdout = proc.stdout.strip()
            combined = stderr or stdout or "unknown error"
            raise RuntimeError(f"{command[0]} failed: {combined}")

    def _public_blob_path(self, key_id: str) -> Path:
        return self._path / f"{self._safe_key_id(key_id)}.pubblob"

    def _private_blob_path(self, key_id: str) -> Path:
        return self._path / f"{self._safe_key_id(key_id)}.privblob"

    def _public_der_path(self, key_id: str) -> Path:
        return self._path / f"{self._safe_key_id(key_id)}.der"

    def _secret_public_blob_path(self, secret_id: str) -> Path:
        return self._path / f"{self._safe_key_id(secret_id)}.secret.pubblob"

    def _secret_private_blob_path(self, secret_id: str) -> Path:
        return self._path / f"{self._safe_key_id(secret_id)}.secret.privblob"

    def _safe_key_id(self, key_id: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in key_id)
