from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Dict

import aws_encryption_sdk
from aws_encryption_sdk import CommitmentPolicy
from aws_encryption_sdk.identifiers import EncryptionKeyType, WrappingAlgorithm
from aws_encryption_sdk.internal.crypto import WrappingKey
from aws_encryption_sdk.key_providers.raw import RawMasterKeyProvider
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class _RawAesMasterKeyProvider(RawMasterKeyProvider):
    def __init__(self) -> None:
        super().__init__()
        self._provider_id = "aes-namespace"
        self._wrapping_key = b""

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def configure(self, wrapping_key: bytes, key_name: str) -> None:
        self._wrapping_key = wrapping_key
        self.add_master_key(key_name.encode("utf8"))

    def _get_raw_key(self, key_id):
        return WrappingKey(
            wrapping_algorithm=WrappingAlgorithm.AES_256_GCM_IV12_TAG16_NO_PADDING,
            wrapping_key=self._wrapping_key,
            wrapping_key_type=EncryptionKeyType.SYMMETRIC,
        )


class SafeKeyringManager:
    def __init__(self) -> None:
        self._master_key: bytes | None = None
        self._key_provider: _RawAesMasterKeyProvider | None = None
        self._space_key_providers: Dict[int, _RawAesMasterKeyProvider] = {}
        self._client = aws_encryption_sdk.EncryptionSDKClient(
            commitment_policy=CommitmentPolicy.REQUIRE_ENCRYPT_REQUIRE_DECRYPT
        )

    @property
    def initialized(self) -> bool:
        return self._master_key is not None and self._key_provider is not None

    def init_with_passphrase(self, passphrase: str, access_id_hash: str) -> bytes:
        digest = hashlib.sha256((passphrase + access_id_hash).encode("utf8")).digest()
        master_key = digest[:32]
        self.init_with_safe_access_master_key(master_key, key_name="passphrase")
        return master_key

    def init_with_safe_access_master_key(self, master_key: bytes, *, key_name: str = "passphrase") -> None:
        self._master_key = bytes(master_key)
        provider = _RawAesMasterKeyProvider()
        provider.configure(self._master_key, key_name)
        self._key_provider = provider
        self._space_key_providers = {}

    def init_space_keyring(self, sid: int, keying_data: bytes, key_name: str = "sharedSpaceKey") -> None:
        if sid <= 0:
            raise ValueError("Invalid sid")
        provider = _RawAesMasterKeyProvider()
        provider.configure(bytes(keying_data), f"{key_name}:{sid}")
        self._space_key_providers[int(sid)] = provider

    def remove_space_keyring(self, sid: int) -> None:
        self._space_key_providers.pop(int(sid), None)

    def clear_space_keyrings(self) -> None:
        self._space_key_providers = {}

    def encrypt_client_data_master_key(self, client_data_key: bytes) -> str:
        key_provider = self._require_key_provider()
        ciphertext, _ = self._client.encrypt(
            source=client_data_key,
            key_provider=key_provider,
            encryption_context={"safeID": "UnoLock", "type": "clientDataKey"},
        )
        return base64.b64encode(ciphertext).decode("ascii")

    def generate_new_client_data_key(self) -> str:
        client_data_key = secrets.token_bytes(32)
        wrapped = self.encrypt_client_data_master_key(client_data_key)
        self.init_with_safe_access_master_key(client_data_key)
        return wrapped

    def decrypt_client_data_master_key(self, wrapped_client_key: str) -> bytes:
        key_provider = self._require_key_provider()
        plaintext, header = self._client.decrypt(
            source=base64.b64decode(wrapped_client_key.encode("ascii")),
            key_provider=key_provider,
        )
        expected = {"safeID": "UnoLock", "type": "clientDataKey"}
        for key, value in expected.items():
            if header.encryption_context.get(key) != value:
                raise ValueError("Encryption context does not match expected values")
        return bytes(plaintext)

    def unwrap_and_set_client_data_master_key(self, wrapped_client_key: str) -> bytes:
        client_data_key = self.decrypt_client_data_master_key(wrapped_client_key)
        self.init_with_safe_access_master_key(client_data_key, key_name="clientDataKey")
        return client_data_key

    def encrypt_server_metadata_key(self, safe_key: str) -> str:
        master_key = self._require_master_key()
        counter = secrets.token_bytes(16)
        cipher = Cipher(algorithms.AES(master_key), modes.CTR(counter))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(safe_key.encode("utf8")) + encryptor.finalize()
        return base64.b64encode(counter + ciphertext).decode("ascii")

    def decrypt_server_metadata_key(self, wrapped_safe_key: str) -> str:
        master_key = self._require_master_key()
        combined = base64.b64decode(wrapped_safe_key.encode("ascii"))
        counter = combined[:16]
        ciphertext = combined[16:]
        cipher = Cipher(algorithms.AES(master_key), modes.CTR(counter))
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        return plaintext.decode("utf8")

    def encrypt_string(self, text: str, sid: int | None = None) -> str:
        key_provider = self._get_key_provider_for_sid(sid)
        ciphertext, _ = self._client.encrypt(
            source=text.encode("utf8"),
            key_provider=key_provider,
            encryption_context={"safeID": "UnoLock"},
        )
        return base64.b64encode(ciphertext).decode("ascii")

    def decrypt_string(self, encrypted: str, sid: int | None = None) -> str:
        key_provider = self._get_key_provider_for_sid(sid)
        plaintext, header = self._client.decrypt(
            source=base64.b64decode(encrypted.encode("ascii")),
            key_provider=key_provider,
        )
        if header.encryption_context.get("safeID") != "UnoLock":
            raise ValueError("Encryption context does not match expected values")
        return plaintext.decode("utf8")

    def xor_encrypted_data_keys_in_header_string(self, encrypted: str, kek: str | None) -> str:
        encrypted_data = bytearray(base64.b64decode(encrypted.encode("ascii")))
        self.xor_encrypted_data_keys_in_header(encrypted_data, kek)
        return base64.b64encode(encrypted_data).decode("ascii")

    def xor_encrypted_data_keys_in_header(self, encrypted_data: bytearray, kek: str | None) -> str:
        raw_kek = base64.b64decode(kek.encode("ascii")) if kek else None
        version_length = 1
        algorithm_id_length = 2
        message_id_length = 32
        aad_length_field_size = 2
        edk_count_field_size = 2

        offset = version_length + algorithm_id_length + message_id_length
        if offset + aad_length_field_size > len(encrypted_data):
            raise ValueError("Invalid encryptedData: insufficient length for AAD length field")
        version = encrypted_data[0]
        if version != 2:
            raise ValueError(f"Unsupported AWS Encryption SDK version: {version}")
        aad_length = (encrypted_data[offset] << 8) | encrypted_data[offset + 1]
        offset += aad_length_field_size + aad_length + edk_count_field_size
        edk_count = (encrypted_data[offset - 2] << 8) | encrypted_data[offset - 1]

        for _ in range(edk_count):
            provider_id_length = (encrypted_data[offset] << 8) | encrypted_data[offset + 1]
            offset += 2 + provider_id_length
            provider_key_length = (encrypted_data[offset] << 8) | encrypted_data[offset + 1]
            offset += 2 + provider_key_length
            edk_length = (encrypted_data[offset] << 8) | encrypted_data[offset + 1]
            if raw_kek is None:
                raw_kek = secrets.token_bytes(edk_length)
            offset += 2
            for idx in range(edk_length):
                encrypted_data[offset + idx] ^= raw_kek[idx % len(raw_kek)]
            offset += edk_length

        if raw_kek is None:
            raise ValueError("KEK generation failed")
        return base64.b64encode(raw_kek).decode("ascii")

    def _require_master_key(self) -> bytes:
        if self._master_key is None:
            raise ValueError("Safe keyring is not initialized")
        return self._master_key

    def _require_key_provider(self) -> _RawAesMasterKeyProvider:
        if self._key_provider is None:
            raise ValueError("Safe keyring is not initialized")
        return self._key_provider

    def _get_key_provider_for_sid(self, sid: int | None) -> _RawAesMasterKeyProvider:
        if sid is not None:
            provider = self._space_key_providers.get(int(sid))
            if provider is not None:
                return provider
        return self._require_key_provider()
