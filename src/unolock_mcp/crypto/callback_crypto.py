from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

G2_PREFIX = "G2:"


class CallbackCrypto:
    @staticmethod
    def encrypt_g2_json(payload: dict[str, Any], raw_key: bytes) -> str:
        iv = os.urandom(12)
        ciphertext = AESGCM(raw_key).encrypt(iv, json.dumps(payload).encode("utf8"), None)
        return G2_PREFIX + base64.b64encode(iv + ciphertext).decode("ascii")

    @staticmethod
    def decrypt_g2_json(ciphertext: str, raw_key: bytes) -> dict[str, Any]:
        if not ciphertext.startswith(G2_PREFIX):
            raise ValueError("Expected G2-prefixed AES-GCM ciphertext")
        combined = base64.b64decode(ciphertext[len(G2_PREFIX):].encode("ascii"))
        iv = combined[:12]
        payload = combined[12:]
        plaintext = AESGCM(raw_key).decrypt(iv, payload, None)
        return json.loads(plaintext.decode("utf8"))
