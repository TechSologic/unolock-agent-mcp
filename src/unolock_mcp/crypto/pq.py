from __future__ import annotations

import base64
import logging

from unolock_mcp.domain.models import PqExchangeRequest, PqExchangeResult


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


class PqSessionNegotiator:
    def __init__(self, signing_public_key_b64: str) -> None:
        self._signing_public_key_b64 = signing_public_key_b64

    def perform_exchange(self, request: PqExchangeRequest) -> PqExchangeResult:
        previous_disable = logging.root.manager.disable
        try:
            logging.disable(logging.CRITICAL)
            import oqs
        finally:
            logging.disable(previous_disable)

        logging.getLogger("oqs").setLevel(logging.WARNING)
        logging.getLogger("oqs.oqs").setLevel(logging.WARNING)

        signing_public_key = _b64decode(self._signing_public_key_b64)
        server_public_key = _b64decode(request.public_key_b64)
        signature = _b64decode(request.signature_b64)

        with oqs.Signature("ML-DSA-65") as verifier:
            valid = verifier.verify(server_public_key, signature, signing_public_key)
        if not valid:
            raise RuntimeError("ML-DSA verification failed")

        with oqs.KeyEncapsulation("ML-KEM-1024") as kem:
            first, second = kem.encap_secret(server_public_key)

        if len(first) == 32 and len(second) > 32:
            shared_secret = first
            cipher_text = second
        else:
            cipher_text = first
            shared_secret = second

        return PqExchangeResult(
            cipher_text_b64=_b64encode(cipher_text),
            shared_secret=shared_secret,
        )
