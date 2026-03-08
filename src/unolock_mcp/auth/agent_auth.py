from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from unolock_mcp.auth.flow_client import UnoLockFlowClient
from unolock_mcp.auth.registration_store import RegistrationStore
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.crypto.safe_keyring import SafeKeyringManager
from unolock_mcp.domain.models import CallbackAction, FlowSession, RegistrationState
from unolock_mcp.tpm.base import TpmDao
from unolock_mcp.tpm.factory import create_tpm_dao


class AgentAuthClient:
    def __init__(
        self,
        flow_client: UnoLockFlowClient,
        session_store: SessionStore,
        registration_store: RegistrationStore,
        tpm_dao: TpmDao | None = None,
    ) -> None:
        self._flow_client = flow_client
        self._session_store = session_store
        self._registration_store = registration_store
        self._tpm = tpm_dao or create_tpm_dao()
        self._keyrings: dict[str, SafeKeyringManager] = {}
        self._agent_pin: str | None = None

    def set_agent_pin(self, pin: str) -> dict[str, Any]:
        self._agent_pin = pin
        return self.runtime_status()

    def clear_agent_pin(self) -> dict[str, Any]:
        self._agent_pin = None
        return self.runtime_status()

    def runtime_status(self) -> dict[str, Any]:
        registration = self._load_registration()
        diagnostics = self._tpm.diagnose()
        provider_mismatch = self._get_provider_mismatch(registration)
        return {
            "has_agent_pin": self._agent_pin is not None,
            "pin_mode": "ephemeral_memory" if self._agent_pin is not None else "unset",
            "tpm_provider": self._tpm.provider_name(),
            "tpm_production_ready": diagnostics.production_ready,
            "tpm_available": diagnostics.available,
            "registered_tpm_provider": registration.tpm_provider,
            "tpm_provider_mismatch": provider_mismatch is not None,
            "tpm_provider_mismatch_detail": provider_mismatch,
        }

    def tpm_diagnostics(self) -> dict[str, Any]:
        return self._tpm.diagnose().to_dict()

    def get_keyring_for_session(self, session_id: str) -> SafeKeyringManager:
        session = self._session_store.get(session_id)
        registration = self._registration_store.load()
        access_id = self._resolve_access_id(registration, session.current_callback, session)
        keyring = self._get_bootstrap_keyring(registration, access_id)
        if keyring is None:
            raise ValueError("No UnoLock bootstrap keyring is available for this session")
        return keyring

    def start_registration_from_stored_url(self) -> dict[str, Any]:
        registration = self._load_registration()
        if registration.connection_url is None:
            return {
                "started": False,
                "reason": "missing_connection_url",
                "message": "Ask the user for a UnoLock connection URL, then call unolock_submit_connection_url.",
            }

        flow = registration.connection_url.flow or "agentRegister"
        args = registration.connection_url.args or self._build_registration_args(registration)
        session = self._flow_client.start(flow=flow, args=args)
        self._session_store.put(session)
        return self._advance_session(session.session_id)

    def authenticate_registered_agent(self) -> dict[str, Any]:
        registration = self._load_registration()
        provider_mismatch = self._get_provider_mismatch(registration)
        if provider_mismatch is not None:
            return provider_mismatch
        access_id = registration.access_id or (registration.connection_url.access_id if registration.connection_url else None)
        if not access_id:
            return {
                "started": False,
                "reason": "missing_access_id",
                "registration": registration.summary(),
            }

        session = self._flow_client.start(flow="agentAccess", args=json.dumps({"accessID": access_id}))
        self._session_store.put(session)
        return self._advance_session(session.session_id)

    def advance_session(self, session_id: str) -> dict[str, Any]:
        return self._advance_session(session_id)

    def _advance_session(self, session_id: str) -> dict[str, Any]:
        session = self._session_store.get(session_id)
        registration = self._load_registration()
        steps: list[dict[str, Any]] = []

        while True:
            callback = session.current_callback
            if callback.type == "SUCCESS":
                updated = self._registration_store.mark_registered(
                    session_id=session.session_id,
                    access_id=self._resolve_access_id(registration, callback, session),
                    key_id=self._resolve_key_id(registration),
                    tpm_provider=self._tpm.provider_name(),
                )
                self._session_store.put(session)
                return {
                    "ok": True,
                    "authorized": True,
                    "completed": True,
                    "steps": steps,
                    "session": session.summary(),
                    "registration": updated.summary(),
                }
            if callback.type in {"FAILED"}:
                return {
                    "ok": False,
                    "authorized": session.authorized,
                    "completed": False,
                    "steps": steps,
                    "session": session.summary(),
                    "registration": registration.summary(),
                }

            handled = self._build_auto_response(session, registration)
            if handled is None:
                self._session_store.put(session)
                return {
                    "ok": True,
                    "authorized": session.authorized,
                    "completed": False,
                    "reason": "manual_callback_required",
                    "steps": steps,
                    "session": session.summary(),
                    "registration": registration.summary(),
                }
            if handled.get("blocked"):
                self._session_store.put(session)
                return {
                    "ok": False,
                    "authorized": session.authorized,
                    "completed": False,
                    "steps": steps,
                    "session": session.summary(),
                    "registration": registration.summary(),
                    **handled,
                }

            steps.append(
                {
                    "callback_type": callback.type,
                    "submitted": handled["submitted"],
                }
            )
            session = self._flow_client.continue_flow(
                session,
                callback_type=callback.type,
                result=handled["result"],
            )
            self._session_store.put(session)
            registration = self._registration_store.load()

    def _build_auto_response(self, session: FlowSession, registration: RegistrationState) -> dict[str, Any] | None:
        callback = session.current_callback
        access_id = self._resolve_access_id(registration, callback, session)
        provider_mismatch = self._get_provider_mismatch(registration)

        if callback.type == "AgentRegistrationCode":
            registration_code = registration.connection_url.registration_code if registration.connection_url else None
            if not access_id or not registration_code:
                return {
                    "blocked": True,
                    "reason": "missing_registration_material",
                    "message": "The stored connection URL does not include both accessID and registration code.",
                }
            return {
                "result": {
                    "accessID": access_id,
                    "registrationCode": registration_code,
                    "connectionUrl": registration.connection_url.raw_url if registration.connection_url else "",
                },
                "submitted": {
                    "accessID": access_id,
                    "registrationCode": "<redacted>",
                },
            }

        if callback.type == "AgentKeyRegistration":
            if not access_id:
                return {
                    "blocked": True,
                    "reason": "missing_access_id",
                    "message": "No accessID is available for agent key registration.",
                }
            created = self._tpm.create_key(self._resolve_key_id(registration, access_id))
            self._registration_store.save(
                RegistrationState(
                    registered=registration.registered,
                    registration_mode=registration.registration_mode,
                    connection_url=registration.connection_url,
                    session_id=registration.session_id,
                    registered_at=registration.registered_at,
                    access_id=access_id,
                    key_id=created.key_id,
                    bootstrap_secret=registration.bootstrap_secret,
                    tpm_provider=self._tpm.provider_name(),
                )
            )
            return {
                "result": {
                    "publicKey": base64.b64encode(created.public_key).decode("ascii"),
                    "algorithm": "ecdsa-p256-sha256-spki",
                    "keyName": "UnoLock Agent Test TPM",
                    "protection": created.binding_info.protection,
                    "deviceBinding": created.binding_info.device_binding,
                    "exportable": created.binding_info.exportable,
                    "keyId": created.key_id,
                    "attestation": "",
                },
                "submitted": {
                    "algorithm": "ecdsa-p256-sha256-spki",
                    "keyId": created.key_id,
                    "protection": created.binding_info.protection,
                    "deviceBinding": created.binding_info.device_binding,
                },
            }

        if callback.type == "AgentChallenge":
            if provider_mismatch is not None:
                return provider_mismatch
            if not access_id:
                return {
                    "blocked": True,
                    "reason": "missing_access_id",
                    "message": "No accessID is available for agent authentication.",
                }
            key_id = self._resolve_key_id(registration, access_id)
            challenge = str(callback.request.get("challenge", ""))
            signature = self._tpm.sign(key_id, challenge.encode("utf8"))
            return {
                "result": {
                    "accessID": access_id,
                    "signature": base64.b64encode(signature).decode("ascii"),
                    "keyId": key_id,
                },
                "submitted": {
                    "accessID": access_id,
                    "signature": "<redacted>",
                    "keyId": key_id,
                },
            }

        if callback.type == "GetSafeAccessID":
            if not access_id:
                return {
                    "blocked": True,
                    "reason": "missing_access_id",
                    "message": "No accessID is available to answer GetSafeAccessID.",
                }
            return {
                "result": {"accessID": access_id},
                "submitted": {"accessID": access_id},
            }

        if callback.type == "GetPin":
            pin_challenge = str(callback.request.get("pinHashChallenge", ""))
            if not pin_challenge:
                return {
                    "blocked": True,
                    "reason": "missing_pin_hash_challenge",
                    "message": "The UnoLock server requested agent PIN auth but did not include a pin hash challenge.",
                }
            if self._agent_pin is None:
                return {
                    "blocked": True,
                    "reason": "missing_agent_pin",
                    "message": "Ask the user for the UnoLock agent PIN, call unolock_set_agent_pin, then continue the session.",
                }
            if not access_id:
                return {
                    "blocked": True,
                    "reason": "missing_access_id",
                    "message": "No accessID is available to answer GetPin.",
                }
            return {
                "result": {
                    "pinHash": self._build_agent_pin_hash(access_id, pin_challenge, self._agent_pin),
                },
                "submitted": {"pinHash": "<redacted>"},
            }

        if callback.type == "DecodeKey":
            keyring = self._get_bootstrap_keyring(registration, access_id)
            if keyring is None:
                return {
                    "blocked": True,
                    "reason": "missing_bootstrap_secret",
                    "message": (
                        "The current agent flow reached DecodeKey, but no bootstrap secret is stored. "
                        "For now the MCP needs bootstrap AIDK material to unwrap the Safe metadata key."
                    ),
                }
            wrapped_key = str(callback.request.get("wrappedKey", ""))
            decoded = keyring.decrypt_server_metadata_key(wrapped_key)
            return {
                "result": {"key": decoded},
                "submitted": {"key": "<redacted>"},
            }

        if callback.type == "ClientDataKey":
            keyring = self._get_bootstrap_keyring(registration, access_id)
            if keyring is None:
                return {
                    "blocked": True,
                    "reason": "missing_bootstrap_secret",
                    "message": (
                        "The current agent flow reached ClientDataKey, but no bootstrap secret is stored. "
                        "For now the MCP needs bootstrap AIDK material to unwrap the client data key."
                    ),
                }
            wrapped_client_key = callback.result if isinstance(callback.result, str) else ""
            keyring.unwrap_and_set_client_data_master_key(wrapped_client_key)
            return {
                "result": wrapped_client_key,
                "submitted": {"wrappedClientKey": "<redacted>"},
            }

        return None

    def _load_registration(self) -> RegistrationState:
        if self._registration_store is None:
            return RegistrationState()
        return self._registration_store.load()

    def _get_provider_mismatch(self, registration: RegistrationState) -> dict[str, Any] | None:
        stored_provider = registration.tpm_provider
        current_provider = self._tpm.provider_name()
        if not stored_provider or stored_provider == current_provider:
            return None
        return {
            "ok": False,
            "blocked": True,
            "reason": "tpm_provider_mismatch",
            "message": (
                f"This agent key was registered with TPM provider '{stored_provider}', but the MCP is "
                f"currently using '{current_provider}'. Re-run the MCP with UNOLOCK_TPM_PROVIDER={stored_provider} "
                "or register a new agent connection with the current provider."
            ),
            "stored_tpm_provider": stored_provider,
            "current_tpm_provider": current_provider,
        }

    def _build_registration_args(self, registration: RegistrationState) -> str | None:
        connection_url = registration.connection_url
        if connection_url is None:
            return None
        access_id = connection_url.access_id or registration.access_id
        registration_code = connection_url.registration_code
        if not access_id or not registration_code:
            return connection_url.args
        return json.dumps(
            {
                "accessID": access_id,
                "registrationCode": registration_code,
                "connectionUrl": connection_url.raw_url,
            }
        )

    def _resolve_access_id(self, registration: RegistrationState, callback: CallbackAction, session: FlowSession) -> str | None:
        if registration.access_id:
            return registration.access_id
        if registration.connection_url and registration.connection_url.access_id:
            return registration.connection_url.access_id
        result = callback.result if isinstance(callback.result, dict) else {}
        if "accessID" in result and isinstance(result["accessID"], str):
            return result["accessID"]
        request = callback.request if isinstance(callback.request, dict) else {}
        if "accessID" in request and isinstance(request["accessID"], str):
            return request["accessID"]
        try:
            state_obj = json.loads(session.state)
            if isinstance(state_obj, dict) and isinstance(state_obj.get("accessID"), str):
                return state_obj["accessID"]
        except Exception:
            pass
        return None

    def _resolve_key_id(self, registration: RegistrationState, access_id: str | None = None) -> str:
        if registration.key_id:
            return registration.key_id
        resolved_access_id = access_id or registration.access_id or (
            registration.connection_url.access_id if registration.connection_url else None
        )
        if not resolved_access_id:
            return "unolock-agent"
        return f"agent-{resolved_access_id}"

    def _get_bootstrap_keyring(self, registration: RegistrationState, access_id: str | None) -> SafeKeyringManager | None:
        if not access_id or not registration.bootstrap_secret:
            return None
        keyring = self._keyrings.get(access_id)
        if keyring is None:
            keyring = SafeKeyringManager()
            self._init_bootstrap_keyring(keyring, registration.bootstrap_secret, access_id)
            self._keyrings[access_id] = keyring
        return keyring

    def _init_bootstrap_keyring(self, keyring: SafeKeyringManager, bootstrap_secret: str, access_id: str) -> None:
        if bootstrap_secret.startswith("pp:"):
            keyring.init_with_passphrase(bootstrap_secret[3:], access_id)
            return
        if bootstrap_secret.startswith("smk:"):
            keyring.init_with_safe_access_master_key(base64.b64decode(bootstrap_secret[4:].encode("ascii")))
            return
        if self._try_init_safe_access_master_key(keyring, bootstrap_secret):
            return
        keyring.init_with_passphrase(bootstrap_secret, access_id)

    def _try_init_safe_access_master_key(self, keyring: SafeKeyringManager, bootstrap_secret: str) -> bool:
        try:
            decoded = base64.b64decode(bootstrap_secret.encode("ascii"), validate=True)
        except Exception:
            return False
        if len(decoded) != 32:
            return False
        keyring.init_with_safe_access_master_key(decoded)
        return True

    @staticmethod
    def _build_agent_pin_hash(access_id: str, pin_challenge: str, pin: str) -> str:
        material = f"UnoLock:GetPin:{access_id}:{pin_challenge}:{pin}".encode("utf8")
        return base64.b64encode(hashlib.sha256(material).digest()).decode("ascii")
