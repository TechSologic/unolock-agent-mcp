from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption

from .base import CreatedKey, KeyBindingInfo, TpmDao, TpmDiagnostics
from .host_diagnostics import detect_host_tpm_state


@dataclass
class _StoredKey:
    public_key: bytes
    private_key: ec.EllipticCurvePrivateKey
    binding_info: KeyBindingInfo


class TestTpmDao(TpmDao):
    """
    Software fallback TPM DAO.

    This provides a lower-assurance local software key path when the host
    cannot provide device-bound or platform-backed key protection.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._keys: dict[str, _StoredKey] = {}
        self._path = path or (Path.home() / ".config" / "unolock-agent-mcp" / "test-tpm")
        self._path.mkdir(parents=True, exist_ok=True)

    def provider_name(self) -> str:
        return "software"

    def create_key(self, key_id: str) -> CreatedKey:
        existing = self._load_key(key_id)
        if existing is not None:
            self._keys[key_id] = existing
            return CreatedKey(key_id=key_id, public_key=existing.public_key, binding_info=existing.binding_info)

        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key().public_bytes(
            encoding=Encoding.DER,
            format=PublicFormat.SubjectPublicKeyInfo,
        )
        binding = KeyBindingInfo(
            protection="software",
            exportable=False,
            attestation_supported=False,
            device_binding="software",
        )
        self._keys[key_id] = _StoredKey(
            public_key=public_key,
            private_key=private_key,
            binding_info=binding,
        )
        self._save_key(key_id, private_key)
        return CreatedKey(key_id=key_id, public_key=public_key, binding_info=binding)

    def get_public_key(self, key_id: str) -> bytes:
        return self._get_or_load(key_id).public_key

    def sign(self, key_id: str, challenge: bytes) -> bytes:
        der_signature = self._get_or_load(key_id).private_key.sign(challenge, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der_signature)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    def get_binding_info(self, key_id: str) -> KeyBindingInfo:
        return self._get_or_load(key_id).binding_info

    def delete_key(self, key_id: str) -> None:
        self._keys.pop(key_id, None)
        self._key_path(key_id).unlink(missing_ok=True)

    def store_secret(self, secret_id: str, secret: bytes) -> None:
        self._secret_path(secret_id).write_bytes(secret)

    def load_secret(self, secret_id: str) -> bytes | None:
        path = self._secret_path(secret_id)
        if not path.exists():
            return None
        return path.read_bytes()

    def delete_secret(self, secret_id: str) -> None:
        self._secret_path(secret_id).unlink(missing_ok=True)

    def diagnose(self) -> TpmDiagnostics:
        diagnostics = detect_host_tpm_state(self.provider_name(), production_ready=False)
        details = dict(diagnostics.details)
        details["key_store_path"] = str(self._path)
        details["persisted_key_count"] = len(list(self._path.glob("*.pem")))
        return TpmDiagnostics(
            provider_name=diagnostics.provider_name,
            provider_type=diagnostics.provider_type,
            production_ready=diagnostics.production_ready,
            available=diagnostics.available,
            summary=diagnostics.summary,
            details=details,
            advice=diagnostics.advice,
        )

    def _get_or_load(self, key_id: str) -> _StoredKey:
        existing = self._keys.get(key_id)
        if existing is not None:
            return existing
        loaded = self._load_key(key_id)
        if loaded is None:
            raise KeyError(key_id)
        self._keys[key_id] = loaded
        return loaded

    def _load_key(self, key_id: str) -> _StoredKey | None:
        key_path = self._key_path(key_id)
        if not key_path.exists():
            return None
        private_key = serialization.load_pem_private_key(
            key_path.read_bytes(),
            password=None,
        )
        if not isinstance(private_key, ec.EllipticCurvePrivateKey):
            raise TypeError("Stored test TPM key is not an EC private key")
        public_key = private_key.public_key().public_bytes(
            encoding=Encoding.DER,
            format=PublicFormat.SubjectPublicKeyInfo,
        )
        binding = KeyBindingInfo(
            protection="software",
            exportable=False,
            attestation_supported=False,
            device_binding="software",
        )
        return _StoredKey(public_key=public_key, private_key=private_key, binding_info=binding)

    def _save_key(self, key_id: str, private_key: ec.EllipticCurvePrivateKey) -> None:
        pem = private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )
        self._key_path(key_id).write_bytes(pem)

    def _key_path(self, key_id: str) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in key_id)
        return self._path / f"{safe_name}.pem"

    def _secret_path(self, secret_id: str) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in secret_id)
        return self._path / f"{safe_name}.secret"
