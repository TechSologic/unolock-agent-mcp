from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class KeyBindingInfo:
    protection: str
    exportable: bool
    attestation_supported: bool
    device_binding: str


@dataclass(frozen=True)
class CreatedKey:
    key_id: str
    public_key: bytes
    binding_info: KeyBindingInfo


@dataclass(frozen=True)
class TpmDiagnostics:
    provider_name: str
    provider_type: str
    production_ready: bool
    available: bool
    summary: str
    details: dict[str, Any]
    advice: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TpmDao(ABC):
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def create_key(self, key_id: str) -> CreatedKey:
        raise NotImplementedError

    @abstractmethod
    def get_public_key(self, key_id: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def sign(self, key_id: str, challenge: bytes) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def get_binding_info(self, key_id: str) -> KeyBindingInfo:
        raise NotImplementedError

    @abstractmethod
    def delete_key(self, key_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def diagnose(self) -> TpmDiagnostics:
        raise NotImplementedError
