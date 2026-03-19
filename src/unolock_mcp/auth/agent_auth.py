from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from unolock_mcp.auth.flow_client import UnoLockFlowClient
from unolock_mcp.auth.registration_store import RegistrationStore, parse_connection_url
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.crypto.safe_keyring import SafeKeyringManager
from unolock_mcp.domain.models import CallbackAction, FlowSession, RegistrationState
from unolock_mcp.tpm.base import TpmDao
from unolock_mcp.tpm.factory import create_tpm_dao


class AgentAuthClient:
    _AGENT_PIN_PATTERN = re.compile(r"^[0-9a-f]+$")

    def __init__(
        self,
        flow_client: UnoLockFlowClient | None,
        session_store: SessionStore,
        registration_store: RegistrationStore,
        tpm_dao: TpmDao | None = None,
    ) -> None:
        self._flow_client = flow_client
        self._session_store = session_store
        self._registration_store = registration_store
        self._tpm = tpm_dao
        self._data_keyrings: dict[str, SafeKeyringManager] = {}
        self._agent_pin: str | None = None
        self._pending_server_keys: dict[str, str] = {}
        self._pending_client_data_keys: dict[str, bytes] = {}

    def _get_tpm(self) -> TpmDao:
        if self._tpm is None:
            provider = None
            if self._registration_store is not None:
                try:
                    provider = self._registration_store.load().tpm_provider
                except Exception:
                    provider = None
            self._tpm = create_tpm_dao(provider)
        return self._tpm

    def set_flow_client(self, flow_client: UnoLockFlowClient) -> None:
        self._flow_client = flow_client

    def set_agent_pin(self, pin: str) -> dict[str, Any]:
        if not isinstance(pin, str):
            raise ValueError(
                "invalid_input: Agent PIN must be passed as a string containing only characters 0-9 and a-f."
            )
        if not pin:
            raise ValueError("invalid_input: Agent PIN must not be empty.")
        if self._AGENT_PIN_PATTERN.fullmatch(pin) is None:
            raise ValueError(
                "invalid_input: Agent PIN must contain only lowercase characters 0-9 and a-f."
            )
        self._agent_pin = pin
        return self.runtime_status()

    def clear_agent_pin(self) -> dict[str, Any]:
        self._agent_pin = None
        return self.runtime_status()

    def disconnect(self) -> dict[str, Any]:
        registration = self._load_registration()
        access_id = registration.access_id or (registration.connection_url.access_id if registration.connection_url else None)
        key_id = registration.key_id or self._resolve_key_id(registration, access_id)
        errors: list[str] = []
        deleted: dict[str, Any] = {
            "key_id": None,
            "bootstrap_secret_id": None,
            "aidk_secret_id": None,
        }

        if key_id and key_id != "unolock-agent":
            try:
                self._get_tpm().delete_key(key_id)
                deleted["key_id"] = key_id
            except Exception as exc:
                errors.append(f"Failed to delete local key '{key_id}': {exc}")

        if access_id:
            bootstrap_secret_id = self._bootstrap_secret_id(access_id)
            aidk_secret_id = self._aidk_secret_id(access_id)
            try:
                self._get_tpm().delete_secret(bootstrap_secret_id)
            except Exception as exc:
                errors.append(f"Failed to delete local secret '{bootstrap_secret_id}': {exc}")
            try:
                self._get_tpm().delete_secret(aidk_secret_id)
            except Exception as exc:
                errors.append(f"Failed to delete local secret '{aidk_secret_id}': {exc}")
            deleted["bootstrap_secret_id"] = bootstrap_secret_id
            deleted["aidk_secret_id"] = aidk_secret_id
            self._pending_server_keys.pop(access_id, None)
            self._pending_client_data_keys.pop(access_id, None)
            self._data_keyrings.pop(access_id, None)
        for secret_id in (self._registration_material_secret_id(), self._registered_access_id_secret_id()):
            try:
                self._get_tpm().delete_secret(secret_id)
            except Exception as exc:
                errors.append(f"Failed to delete local secret '{secret_id}': {exc}")

        self._agent_pin = None
        self._session_store.clear()
        self._registration_store.reset()

        return {
            "ok": len(errors) == 0,
            "disconnected": len(errors) == 0,
            "partial": len(errors) > 0,
            "local_only": True,
            "message": (
                "The local UnoLock agent registration was removed from this host. "
                "A Safe admin must still delete or rotate the server-side access record if revocation is needed."
            ),
            "deleted": deleted,
            "errors": errors,
        }

    def runtime_status(self) -> dict[str, Any]:
        registration = self._load_registration()
        diagnostics = self._get_tpm().diagnose()
        provider_mismatch = self._get_provider_mismatch(registration)
        access_id = registration.access_id or (registration.connection_url.access_id if registration.connection_url else None)
        security_warning = self._insecure_provider_warning()
        tpm_provider = self._normalize_provider_name(self._get_tpm().provider_name())
        registered_tpm_provider = self._normalize_provider_name(registration.tpm_provider)
        return {
            "has_agent_pin": self._agent_pin is not None,
            "pin_mode": "ephemeral_memory" if self._agent_pin is not None else "unset",
            "tpm_provider": tpm_provider,
            "tpm_production_ready": diagnostics.production_ready,
            "tpm_available": diagnostics.available,
            "assurance_level": "preferred" if diagnostics.production_ready else "reduced",
            "registered_tpm_provider": registered_tpm_provider,
            "bootstrap_secret_available": bool(registration.bootstrap_secret or self._load_protected_bootstrap_secret(access_id)),
            "tpm_provider_mismatch": provider_mismatch is not None,
            "tpm_provider_mismatch_detail": provider_mismatch,
            "security_warning": security_warning,
        }

    def tpm_diagnostics(self) -> dict[str, Any]:
        return self._get_tpm().diagnose().to_dict()

    def ensure_secure_provider(self) -> dict[str, Any] | None:
        return self._insecure_provider_warning()

    def submit_connection_url(self, connection_url: str) -> dict[str, Any]:
        parsed = parse_connection_url(connection_url)
        validation_error = self._validate_agent_connection_url(parsed)
        if validation_error is not None:
            return validation_error
        replacement = self._replace_local_registration_state_for_new_connection_url()
        if replacement is not None:
            return replacement
        if parsed.passphrase and parsed.access_id:
            self._store_protected_bootstrap_secret(parsed.access_id, parsed.passphrase)
        self._store_registration_material(parsed)
        state = self._registration_store.set_connection_url(connection_url)
        summary = state.summary()
        warning = self._insecure_provider_warning()
        if warning is not None:
            summary["security_warning"] = warning
        return summary

    def _replace_local_registration_state_for_new_connection_url(self) -> dict[str, Any] | None:
        registration = self._load_registration()
        access_ids: set[str] = set()
        key_ids: set[str] = set()

        if registration.access_id:
            access_ids.add(registration.access_id)
        if registration.connection_url and registration.connection_url.access_id:
            access_ids.add(registration.connection_url.access_id)

        material = self._load_registration_material()
        if material and material.get("access_id"):
            access_ids.add(material["access_id"])

        if registration.key_id:
            key_ids.add(registration.key_id)
        for access_id in access_ids:
            key_ids.add(self._resolve_key_id(registration, access_id))

        errors: list[str] = []
        for key_id in key_ids:
            if not key_id or key_id == "unolock-agent":
                continue
            try:
                self._get_tpm().delete_key(key_id)
            except Exception as exc:
                errors.append(f"Failed to delete local key '{key_id}': {exc}")

        for access_id in access_ids:
            for secret_id in (self._bootstrap_secret_id(access_id), self._aidk_secret_id(access_id)):
                try:
                    self._get_tpm().delete_secret(secret_id)
                except Exception as exc:
                    errors.append(f"Failed to delete local secret '{secret_id}': {exc}")
            self._pending_server_keys.pop(access_id, None)
            self._pending_client_data_keys.pop(access_id, None)
            self._data_keyrings.pop(access_id, None)

        for secret_id in (self._registration_material_secret_id(), self._registered_access_id_secret_id()):
            try:
                self._get_tpm().delete_secret(secret_id)
            except Exception as exc:
                errors.append(f"Failed to delete local secret '{secret_id}': {exc}")

        if errors:
            return {
                "ok": False,
                "blocked": True,
                "reason": "local_registration_reset_failed",
                "message": (
                    "The MCP could not fully clear the previous local UnoLock agent registration before "
                    "accepting the new Agent Key URL."
                ),
                "errors": errors,
            }

        self._agent_pin = None
        self._session_store.clear()
        self._registration_store.reset()
        return None

    def secure_registration_material(self) -> dict[str, Any]:
        registration = self._load_registration()
        self._protect_bootstrap_secret_if_needed(registration)
        summary = self._registration_store.load().summary()
        warning = self._insecure_provider_warning()
        if warning is not None:
            summary["security_warning"] = warning
        return summary

    def get_active_keyring(self) -> SafeKeyringManager:
        session = self._session_store.get()
        registration = self._load_registration()
        access_id = self._resolve_access_id(registration, session.current_callback, session)
        keyring = self._get_data_keyring(access_id)
        if keyring is None:
            raise ValueError("No UnoLock client data keyring is available for this session")
        return keyring

    def start_registration_from_stored_url(self) -> dict[str, Any]:
        registration = self._load_registration()
        flow_client = self.require_flow_client()
        self._protect_bootstrap_secret_if_needed(registration)
        registration = self._load_registration()
        if registration.connection_url is None:
            return {
                "started": False,
                "reason": "missing_connection_url",
                "message": "Ask the user for a UnoLock Agent Key URL and PIN, then call unolock_link_agent_key.",
            }

        flow = registration.connection_url.flow or "agentRegister"
        session = flow_client.start(flow=flow)
        self._session_store.put(session)
        result = self._advance_active_flow()
        warning = self._insecure_provider_warning()
        if warning is not None:
            result["security_warning"] = warning
        return result

    def authenticate_registered_agent(self) -> dict[str, Any]:
        registration = self._load_registration()
        flow_client = self.require_flow_client()
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

        session = flow_client.start(flow="agentAccess")
        self._session_store.put(session)
        result = self._advance_active_flow()
        warning = self._insecure_provider_warning()
        if warning is not None:
            result["security_warning"] = warning
        return result

    def advance_active_flow(self) -> dict[str, Any]:
        return self._advance_active_flow()

    def _advance_active_flow(self) -> dict[str, Any]:
        flow_client = self.require_flow_client()
        session = self._session_store.get()
        registration = self._load_registration()
        steps: list[dict[str, Any]] = []

        while True:
            callback = session.current_callback
            if callback.type == "SUCCESS":
                resolved_access_id = self._resolve_access_id(registration, callback, session)
                if session.flow == "agentRegister" and resolved_access_id:
                    self._delete_protected_bootstrap_secret(resolved_access_id)
                    self._delete_registration_material()
                updated = self._registration_store.mark_registered(
                    access_id=resolved_access_id,
                    key_id=self._resolve_key_id(registration),
                    bootstrap_secret="",
                    tpm_provider=self._get_tpm().provider_name(),
                )
                if resolved_access_id:
                    self._store_registered_access_id(resolved_access_id)
                if resolved_access_id:
                    self._pending_server_keys.pop(resolved_access_id, None)
                    self._pending_client_data_keys.pop(resolved_access_id, None)
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
                failure = self._classify_failed_callback(session, registration, steps)
                return {
                    "ok": False,
                    "authorized": session.authorized,
                    "completed": False,
                    "steps": steps,
                    "session": session.summary(),
                    "registration": registration.summary(),
                    **failure,
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
            session = flow_client.continue_flow(
                session,
                callback_type=callback.type,
                result=handled["result"],
            )
            self._session_store.put(session)
            registration = self._load_registration()

    def _classify_failed_callback(
        self,
        session: FlowSession,
        registration: RegistrationState,
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        callback = session.current_callback
        if (
            session.flow == "agentRegister"
            and steps
            and steps[-1].get("callback_type") == "AgentRegistrationCode"
            and callback.type == "FAILED"
        ):
            return {
                "reason": "agent_key_invalid_or_consumed",
                "message": (
                    "The submitted UnoLock Agent Key URL was accepted locally, but the Safe rejected it during "
                    "registration. The one-time Agent Key may already be used, expired, or no longer valid."
                ),
                "suggested_action": (
                    "Ask the user for a fresh UnoLock Agent Key URL from the Safe app and submit it again."
                ),
            }
        return {
            "reason": "flow_failed",
            "message": (
                "The UnoLock server ended the current flow without authorizing the agent."
            ),
        }

    def require_flow_client(self) -> UnoLockFlowClient:
        if self._flow_client is None:
            raise ValueError(
                "runtime_metadata_missing: UnoLock runtime metadata is not resolved yet. Submit a UnoLock Agent Key "
                "URL from the target Safe first."
            )
        return self._flow_client

    def _build_auto_response(self, session: FlowSession, registration: RegistrationState) -> dict[str, Any] | None:
        callback = session.current_callback
        access_id = self._resolve_access_id(registration, callback, session)
        provider_mismatch = self._get_provider_mismatch(registration)

        if callback.type == "AgentRegistrationCode":
            registration_code = registration.connection_url.registration_code if registration.connection_url else None
            material = self._load_registration_material()
            if material:
                access_id = access_id or material.get("access_id")
                registration_code = registration_code or material.get("registration_code")
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
            created = self._get_tpm().create_key(self._resolve_key_id(registration, access_id))
            self._registration_store.save(
                RegistrationState(
                    registered=registration.registered,
                    registration_mode=registration.registration_mode,
                    connection_url=registration.connection_url,
                    registered_at=registration.registered_at,
                    access_id=access_id,
                    key_id=created.key_id,
                    bootstrap_secret=None,
                    tpm_provider=self._get_tpm().provider_name(),
                    api_base_url=registration.api_base_url or (registration.connection_url.api_base_url if registration.connection_url else None),
                    transparency_origin=registration.transparency_origin or (registration.connection_url.site_origin if registration.connection_url else None),
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
            signature = self._get_tpm().sign(key_id, challenge.encode("utf8"))
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
            keyring = self._get_decode_key_keyring(session, registration, access_id)
            if keyring is None:
                return {
                    "blocked": True,
                    "reason": "missing_bootstrap_keyring",
                    "message": (
                        "The current UnoLock flow reached DecodeKey, but no keyring is available to unwrap "
                        "the Safe metadata key."
                    ),
                }
            wrapped_key = str(callback.request.get("wrappedKey", ""))
            decoded = keyring.decrypt_server_metadata_key(wrapped_key)
            if access_id:
                self._pending_server_keys[access_id] = decoded
            return {
                "result": {"key": decoded},
                "submitted": {"key": "<redacted>"},
            }

        if callback.type == "ClientDataKey":
            keyring = self._get_client_data_key_keyring(session, registration, access_id)
            if keyring is None:
                return {
                    "blocked": True,
                    "reason": "missing_client_data_keyring",
                    "message": (
                        "The current UnoLock flow reached ClientDataKey, but no keyring is available to unwrap "
                        "the client data key."
                    ),
                }
            wrapped_client_key = callback.result if isinstance(callback.result, str) else ""
            client_data_key = keyring.unwrap_and_set_client_data_master_key(wrapped_client_key)
            if access_id:
                self._pending_client_data_keys[access_id] = client_data_key
                self._data_keyrings[access_id] = keyring
            return {
                "result": wrapped_client_key,
                "submitted": {"wrappedClientKey": "<redacted>"},
            }

        if callback.type == "AgentWrappedKeys":
            if not access_id:
                return {
                    "blocked": True,
                    "reason": "missing_access_id",
                    "message": "No accessID is available to install the final agent-wrapped keys.",
                }
            server_key = self._pending_server_keys.get(access_id)
            client_data_key = self._pending_client_data_keys.get(access_id)
            if not server_key or client_data_key is None:
                return {
                    "blocked": True,
                    "reason": "missing_rewrap_material",
                    "message": "The MCP does not have both Safe keys needed to install the final agent AIDK-wrapped key material.",
                }
            aidk = self._load_or_create_agent_aidk(access_id)
            aidk_keyring = SafeKeyringManager()
            aidk_keyring.init_with_safe_access_master_key(aidk)
            wrapped_server_key = aidk_keyring.encrypt_server_metadata_key(server_key)
            wrapped_client_key = aidk_keyring.encrypt_client_data_master_key(client_data_key)
            data_keyring = self._get_data_keyring(access_id)
            if data_keyring is None:
                return {
                    "blocked": True,
                    "reason": "missing_data_keyring",
                    "message": (
                        "The MCP does not have the client data keyring needed to encrypt the agent assurance data."
                    ),
                }
            device_assurance_enc = data_keyring.encrypt_string(
                json.dumps(self._build_device_assurance_summary(key_id=self._resolve_key_id(registration, access_id)))
            )
            return {
                "result": {
                    "wrappedServerKey": wrapped_server_key,
                    "wrappedClientKey": wrapped_client_key,
                    "deviceAssuranceEnc": device_assurance_enc,
                },
                "submitted": {
                    "wrappedServerKey": "<redacted>",
                    "wrappedClientKey": "<redacted>",
                    "deviceAssuranceEnc": "<redacted>",
                },
            }

        return None

    def _load_registration(self) -> RegistrationState:
        if self._registration_store is None:
            return RegistrationState()
        registration = self._registration_store.load()
        protected_access_id = self._load_registered_access_id()
        if protected_access_id:
            registration.access_id = protected_access_id
        elif registration.key_id and registration.key_id.startswith("agent-"):
            registration.access_id = registration.key_id[6:]
        if registration.bootstrap_secret:
            return registration
        access_id = registration.access_id or (registration.connection_url.access_id if registration.connection_url else None)
        protected_secret = self._load_protected_bootstrap_secret(access_id)
        if not protected_secret:
            return registration
        registration.bootstrap_secret = protected_secret
        return registration

    def _get_provider_mismatch(self, registration: RegistrationState) -> dict[str, Any] | None:
        stored_provider = registration.tpm_provider
        current_provider = self._get_tpm().provider_name()
        normalized_stored_provider = self._normalize_provider_name(stored_provider)
        normalized_current_provider = self._normalize_provider_name(current_provider)
        if not stored_provider or normalized_stored_provider == normalized_current_provider:
            return None
        return {
            "ok": False,
            "blocked": True,
            "reason": "tpm_provider_mismatch",
            "message": (
                f"This agent key was registered with TPM provider '{normalized_stored_provider}', but the MCP is "
                f"currently using '{normalized_current_provider}'. Re-run the MCP with UNOLOCK_TPM_PROVIDER={normalized_stored_provider} "
                "or register a new agent connection with the current provider."
            ),
            "stored_tpm_provider": normalized_stored_provider,
            "current_tpm_provider": normalized_current_provider,
        }

    def _validate_agent_connection_url(self, parsed) -> dict[str, Any] | None:
        if parsed.action == "register":
            return {
                "ok": False,
                "blocked": True,
                "reason": "wrong_connection_url_type",
                "message": (
                    "This UnoLock URL is a regular key registration URL, not an agent connection URL. "
                    "Ask the user for the agent URL generated for an AI/agent key. It should use "
                    "the #/agent-register/... format."
                ),
                "expected_action": "agent-register",
                "received_action": parsed.action,
                "access_id": parsed.access_id,
            }
        if parsed.flow != "agentRegister":
            fragment_hint = (
                " If you passed the URL through a shell or host config, make sure the full "
                "#/agent-register/... fragment was preserved and quote the entire URL."
                if parsed.raw_url and "#/" not in parsed.raw_url
                else ""
            )
            return {
                "ok": False,
                "blocked": True,
                "reason": "unsupported_connection_url",
                "message": (
                    "The supplied UnoLock URL is not an agent registration URL. Ask the user for the "
                    "agent URL generated for an AI/agent key."
                    f"{fragment_hint}"
                ),
                "received_flow": parsed.flow,
                "received_action": parsed.action,
            }
        if not parsed.access_id or not parsed.registration_code or not parsed.passphrase:
            return {
                "ok": False,
                "blocked": True,
                "reason": "invalid_agent_connection_url",
                "message": (
                    "The supplied agent connection URL is incomplete. Ask the user to copy the full "
                    "UnoLock agent connection URL again."
                ),
                "has_access_id": bool(parsed.access_id),
                "has_registration_code": bool(parsed.registration_code),
                "has_bootstrap_secret": bool(parsed.passphrase),
            }
        return None

    def _resolve_access_id(self, registration: RegistrationState, callback: CallbackAction, session: FlowSession) -> str | None:
        if registration.access_id:
            return registration.access_id
        if registration.connection_url and registration.connection_url.access_id:
            return registration.connection_url.access_id
        material = self._load_registration_material()
        if material is not None:
            return material.get("access_id")
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
        del registration
        return self._build_aidk_keyring(access_id)

    def _get_registration_bootstrap_keyring(self, registration: RegistrationState, access_id: str | None) -> SafeKeyringManager | None:
        if not access_id:
            return None
        bootstrap_secret = registration.bootstrap_secret or self._load_protected_bootstrap_secret(access_id)
        if not bootstrap_secret:
            return None
        keyring = SafeKeyringManager()
        self._init_bootstrap_keyring(keyring, bootstrap_secret, access_id)
        return keyring

    def _build_aidk_keyring(self, access_id: str | None) -> SafeKeyringManager | None:
        if not access_id:
            return None
        aidk = self._load_agent_aidk(access_id)
        if aidk is None:
            return None
        keyring = SafeKeyringManager()
        keyring.init_with_safe_access_master_key(aidk)
        return keyring

    def _get_decode_key_keyring(
        self,
        session: FlowSession,
        registration: RegistrationState,
        access_id: str | None,
    ) -> SafeKeyringManager | None:
        if session.flow == "agentRegister":
            return self._get_registration_bootstrap_keyring(registration, access_id)
        return self._build_aidk_keyring(access_id)

    def _get_client_data_key_keyring(
        self,
        session: FlowSession,
        registration: RegistrationState,
        access_id: str | None,
    ) -> SafeKeyringManager | None:
        if session.flow == "agentRegister":
            return self._get_registration_bootstrap_keyring(registration, access_id)
        return self._build_aidk_keyring(access_id)

    def _get_data_keyring(self, access_id: str | None) -> SafeKeyringManager | None:
        if not access_id:
            return None
        return self._data_keyrings.get(access_id)

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

    def _store_protected_bootstrap_secret(self, access_id: str | None, bootstrap_secret: str) -> None:
        if not access_id or not bootstrap_secret:
            return
        self._get_tpm().store_secret(self._bootstrap_secret_id(access_id), bootstrap_secret.encode("utf8"))

    def _load_protected_bootstrap_secret(self, access_id: str | None) -> str | None:
        if not access_id:
            return None
        secret = self._get_tpm().load_secret(self._bootstrap_secret_id(access_id))
        if not secret:
            return None
        return secret.decode("utf8")

    def _delete_protected_bootstrap_secret(self, access_id: str | None) -> None:
        if not access_id:
            return
        self._get_tpm().delete_secret(self._bootstrap_secret_id(access_id))

    def _store_registration_material(self, parsed) -> None:
        if not parsed.access_id or not parsed.registration_code:
            return
        payload = json.dumps(
            {
                "access_id": parsed.access_id,
                "registration_code": parsed.registration_code,
            }
        ).encode("utf8")
        self._get_tpm().store_secret(self._registration_material_secret_id(), payload)

    def _load_registration_material(self) -> dict[str, str] | None:
        raw = self._get_tpm().load_secret(self._registration_material_secret_id())
        if not raw:
            return None
        try:
            payload = json.loads(raw.decode("utf8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        access_id = payload.get("access_id")
        registration_code = payload.get("registration_code")
        if not isinstance(access_id, str) or not isinstance(registration_code, str):
            return None
        return {
            "access_id": access_id,
            "registration_code": registration_code,
        }

    def _delete_registration_material(self) -> None:
        self._get_tpm().delete_secret(self._registration_material_secret_id())

    def _store_registered_access_id(self, access_id: str) -> None:
        self._get_tpm().store_secret(self._registered_access_id_secret_id(), access_id.encode("utf8"))

    def _load_registered_access_id(self) -> str | None:
        raw = self._get_tpm().load_secret(self._registered_access_id_secret_id())
        if not raw:
            return None
        try:
            return raw.decode("utf8")
        except Exception:
            return None

    def _load_agent_aidk(self, access_id: str) -> bytes | None:
        return self._get_tpm().load_secret(self._aidk_secret_id(access_id))

    def _load_or_create_agent_aidk(self, access_id: str) -> bytes:
        existing = self._load_agent_aidk(access_id)
        if existing is not None:
            return existing
        aidk = secrets.token_bytes(32)
        self._get_tpm().store_secret(self._aidk_secret_id(access_id), aidk)
        return aidk

    def _protect_bootstrap_secret_if_needed(self, registration: RegistrationState) -> None:
        access_id = registration.access_id or (registration.connection_url.access_id if registration.connection_url else None)
        if not access_id or not registration.bootstrap_secret:
            return
        self._store_protected_bootstrap_secret(access_id, registration.bootstrap_secret)
        registration.bootstrap_secret = ""
        self._registration_store.save(registration)

    def _insecure_provider_warning(self) -> dict[str, Any] | None:
        diagnostics = self._get_tpm().diagnose()
        if diagnostics.production_ready:
            return None
        provider_name = self._normalize_provider_name(self._get_tpm().provider_name())
        return {
            "ok": True,
            "blocked": False,
            "reason": "insecure_tpm_provider",
            "message": (
                f"The active TPM provider '{provider_name}' is not production-ready. "
                "UnoLock Agent will still work, but this host could not satisfy the preferred "
                "device-bound, non-exportable key-storage requirements and is operating at reduced assurance."
            ),
            "tpm_provider": provider_name,
            "tpm_diagnostics": diagnostics.to_dict(),
        }

    def _build_device_assurance_summary(self, key_id: str) -> dict[str, Any]:
        binding_info = self._get_tpm().get_binding_info(key_id)
        diagnostics = self._get_tpm().diagnose()
        return {
            "scheme": "agent-mcp",
            "provider": self._normalize_provider_name(self._get_tpm().provider_name()),
            "recordedAt": datetime.now(timezone.utc).isoformat(),
            "binding": {
                "protection": binding_info.protection,
                "deviceBinding": binding_info.device_binding,
                "exportable": binding_info.exportable,
                "attestationSupported": binding_info.attestation_supported,
            },
            "diagnostics": {
                "providerType": diagnostics.provider_type,
                "productionReady": diagnostics.production_ready,
                "available": diagnostics.available,
                "summary": diagnostics.summary,
            },
        }

    @staticmethod
    def _normalize_provider_name(provider_name: str | None) -> str:
        if provider_name == "test":
            return "software"
        return provider_name or ""

    @staticmethod
    def _bootstrap_secret_id(access_id: str) -> str:
        return f"bootstrap-{access_id}"

    @staticmethod
    def _aidk_secret_id(access_id: str) -> str:
        return f"aidk-{access_id}"

    @staticmethod
    def _registration_material_secret_id() -> str:
        return "registration-material"

    @staticmethod
    def _registered_access_id_secret_id() -> str:
        return "registered-access-id"
