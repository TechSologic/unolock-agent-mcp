from __future__ import annotations

from contextlib import ExitStack
import os
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from unolock_mcp.auth.registration_store import RegistrationStore
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.domain.models import CallbackAction, FlowSession, RegistrationState, UnoLockResolvedConfig

from unolock_mcp.mcp.server import _registration_status_payload, _tool_error_response, create_mcp_server


class _FakeAgentAuth:
    def __init__(self, *, has_agent_pin: bool) -> None:
        self._has_agent_pin = has_agent_pin

    def runtime_status(self) -> dict[str, object]:
        return {
            "has_agent_pin": self._has_agent_pin,
            "pin_mode": "unset" if not self._has_agent_pin else "ephemeral_memory",
            "tpm_provider": "windows-tpm",
            "tpm_production_ready": True,
            "tpm_available": True,
            "registered_tpm_provider": "windows-tpm",
            "bootstrap_secret_available": False,
            "tpm_provider_mismatch": False,
            "tpm_provider_mismatch_detail": None,
        }

    def tpm_diagnostics(self) -> dict[str, object]:
        return {
            "provider_name": "windows-tpm",
            "provider_type": "hardware",
            "production_ready": True,
            "available": True,
            "summary": "Windows Platform Crypto Provider created a TPM-backed P-256 key.",
            "details": {},
            "advice": [],
        }


class RegistrationStatusPayloadTest(unittest.TestCase):
    def test_registered_agent_without_pin_requests_auth_or_pin_not_connection_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registration_store = RegistrationStore(Path(tmpdir) / "registration.json")
            registration_store.save(
                RegistrationState(
                    registered=True,
                    registration_mode="registered",
                    access_id="access-123",
                    key_id="agent-access-123",
                    tpm_provider="windows-tpm",
                )
            )

            payload = _registration_status_payload(
                registration_store,
                SessionStore(),
                _FakeAgentAuth(has_agent_pin=False),
            )

            self.assertEqual(payload["recommended_next_action"], "authenticate_or_set_pin")
            self.assertIn("PIN", payload["guidance"])
            self.assertFalse(payload["needs_connection_url"])
            self.assertEqual(payload["registration_state"], "registered")
            self.assertNotIn("registration_mode", payload)
            self.assertIn("unolock_register", payload["primary_tools"])
            self.assertIn("unolock_list_records", payload["primary_tools"])
            self.assertIn("unolock_list_files", payload["primary_tools"])
            self.assertEqual(payload["advanced_tools"], [])
            self.assertIn("unolock_append_note", payload["write_tools"])
            self.assertIn("unolock_upload_file", payload["write_tools"])
            self.assertIn("unolock://usage/about", payload["explanation_resources"])
            self.assertIn("unolock://usage/security-model", payload["explanation_resources"])
            self.assertIn("unolock://usage/updates", payload["explanation_resources"])

    def test_unregistered_agent_without_connection_url_requests_agent_key_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = _registration_status_payload(
                RegistrationStore(Path(tmpdir) / "registration.json"),
                SessionStore(),
                _FakeAgentAuth(has_agent_pin=False),
            )

            self.assertEqual(payload["recommended_next_action"], "ask_for_connection_url")
            self.assertIn("Agent Key URL", payload["guidance"])
            self.assertIn("safe.unolock.com", payload["guidance"])
            self.assertIn("PIN", payload["guidance"])
            self.assertEqual(payload["registration_state"], "waiting_for_connection_url")
            self.assertNotIn("registration_mode", payload)
            self.assertIn("Call the normal data tools directly and let the MCP authenticate automatically when needed.", payload["workflow_summary"])
            self.assertIn("unolock://usage/quickstart", payload["explanation_resources"])
            self.assertIn("Use plain user-facing wording.", payload["agent_behavior_rules"])

    def test_reduced_assurance_warning_does_not_change_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth = _FakeAgentAuth(has_agent_pin=False)
            auth.runtime_status = lambda: {
                "has_agent_pin": False,
                "pin_mode": "unset",
                "tpm_provider": "software",
                "tpm_production_ready": False,
                "tpm_available": False,
                "registered_tpm_provider": None,
                "bootstrap_secret_available": False,
                "tpm_provider_mismatch": False,
                "tpm_provider_mismatch_detail": None,
                "security_warning": {"message": "reduced assurance"},
            }
            auth.tpm_diagnostics = lambda: {
                "provider_name": "software",
                "provider_type": "software",
                "production_ready": False,
                "available": False,
                "summary": "software fallback",
                "details": {},
                "advice": [],
            }

            payload = _registration_status_payload(
                RegistrationStore(Path(tmpdir) / "registration.json"),
                SessionStore(),
                auth,
            )

            self.assertEqual(payload["recommended_next_action"], "ask_for_connection_url")
            self.assertIn("Warning: reduced assurance", payload["guidance"])
            self.assertIn("unolock_register", payload["primary_tools"])

    def test_pending_getpin_guidance_prefers_retrying_original_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registration_store = RegistrationStore(Path(tmpdir) / "registration.json")
            registration_store.save(
                RegistrationState(
                    registered=True,
                    registration_mode="registered",
                    access_id="access-123",
                    key_id="agent-access-123",
                    tpm_provider="windows-tpm",
                )
            )
            session_store = SessionStore()
            session_store.put(
                FlowSession(
                    session_id="pending-1",
                    flow="agentAccess",
                    state="state",
                    shared_secret=b"secret",
                    current_callback=CallbackAction(type="GetPin", result={}),
                    authorized=False,
                )
            )

            payload = _registration_status_payload(
                registration_store,
                session_store,
                _FakeAgentAuth(has_agent_pin=False),
            )

            self.assertEqual(payload["recommended_next_action"], "ask_for_agent_pin_then_continue")
            self.assertIn("retry the original UnoLock request", payload["guidance"])
            self.assertNotIn("unolock_continue_agent_session", payload["guidance"])


class ToolErrorResponseTest(unittest.TestCase):
    def test_structured_space_read_only_error(self) -> None:
        payload = _tool_error_response(ValueError("space_read_only: This agent has read-only access."))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "space_read_only")
        self.assertIn("read-only access", payload["message"])
        self.assertIn("allowed_operations", payload["suggested_action"])

    def test_structured_conflict_error(self) -> None:
        payload = _tool_error_response(
            ValueError("write_conflict_requires_reread: Read the target record again and retry.")
        )
        self.assertEqual(payload["reason"], "write_conflict_requires_reread")
        self.assertIn("Reread", payload["suggested_action"])

    def test_generic_error_falls_back_to_operation_failed(self) -> None:
        payload = _tool_error_response(ValueError("unexpected failure"))
        self.assertEqual(payload["reason"], "operation_failed")
        self.assertEqual(payload["message"], "unexpected failure")

    def test_structured_no_accessible_spaces_error(self) -> None:
        payload = _tool_error_response(
            ValueError("no_accessible_spaces: This Agent Key does not currently have access to any UnoLock Spaces.")
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "no_accessible_spaces")
        self.assertIn("does not currently have access to any UnoLock Spaces", payload["message"])
        self.assertIn("share or create a UnoLock Space", payload["suggested_action"])


class _FakeFlowClient:
    def __init__(self, config) -> None:
        self.config = config


class _FakeReadonlyRecordsClient:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def list_spaces(self, session_id: str) -> dict[str, object]:
        return {
            "ok": True,
            "internal_session_id": session_id,
            "spaces": [
                {"space_id": 1773, "name": "Agent Space", "writable": True, "allowed_operations": ["create_note"]},
                {"space_id": 1888, "name": "Second Space", "writable": True, "allowed_operations": ["create_note"]},
            ],
        }

    def list_records(
        self,
        session_id: str,
        kind: str = "all",
        *,
        space_id: int | None = None,
        pinned: bool | None = None,
        label: str | None = None,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "internal_session_id": session_id,
            "kind_filter": kind,
            "space_id_filter": space_id,
            "pinned_filter": pinned,
            "label_filter": label,
            "records": [],
        }


class _FakeReadonlyRecordsNoSpacesClient(_FakeReadonlyRecordsClient):
    def list_spaces(self, session_id: str) -> dict[str, object]:
        return {
            "ok": True,
            "internal_session_id": session_id,
            "spaces": [],
        }


class _FakeReadonlyRecordsStaleSessionClient(_FakeReadonlyRecordsClient):
    calls = 0

    def list_spaces(self, session_id: str) -> dict[str, object]:
        self.__class__.calls += 1
        if self.__class__.calls == 1:
            raise HTTPError(
                url="https://api.safe.test.1two.be/access",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=None,
            )
        return super().list_spaces(session_id)


class _FakeWritableFilesClient:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def upload_file(
        self,
        session_id: str,
        *,
        space_id: int,
        local_path: str,
        name: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "file": {
                "archive_id": "archive-1",
                "space_id": space_id,
                "name": name,
                "local_path": local_path,
                "mime_type": mime_type or "application/octet-stream",
            },
            "internal_session_id": session_id,
        }


class _FakeReadonlyFilesClient:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def get_file(self, session_id: str, archive_id: str) -> dict[str, object]:
        return {
            "archive_id": archive_id,
            "space_id": 1773,
            "name": "cloud.txt",
            "mime_type": "text/plain",
        }


class _FakeWritableRecordsClient:
    last_update_note: dict[str, object] | None = None

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def update_note(
        self,
        session_id: str,
        *,
        record_ref: str,
        expected_version: int,
        title: str,
        text: str,
    ) -> dict[str, object]:
        self.__class__.last_update_note = {
            "session_id": session_id,
            "record_ref": record_ref,
            "expected_version": expected_version,
            "title": title,
            "text": text,
        }
        return {
            "ok": True,
            "record": {
                "record_ref": record_ref,
                "version": expected_version + 1,
                "title": title,
                "plain_text": text,
            },
        }


class _FakeAgentAuthForAutoSession:
    instances: list["_FakeAgentAuthForAutoSession"] = []

    def __init__(self, _flow_client, session_store: SessionStore, _registration_store: RegistrationStore, *_args, **_kwargs) -> None:
        self._session_store = session_store
        self._agent_pin: str | None = None
        self.auth_calls = 0
        self.registration_calls = 0
        self.flow_client_sets = 0
        self.__class__.instances.append(self)

    def set_flow_client(self, _flow_client) -> None:
        self.flow_client_sets += 1
        return None

    def runtime_status(self) -> dict[str, object]:
        return {
            "has_agent_pin": self._agent_pin is not None,
            "pin_mode": "ephemeral_memory" if self._agent_pin is not None else "unset",
            "tpm_provider": "software",
            "tpm_production_ready": False,
            "tpm_available": False,
            "registered_tpm_provider": "software",
            "bootstrap_secret_available": True,
            "tpm_provider_mismatch": False,
            "tpm_provider_mismatch_detail": None,
        }

    def tpm_diagnostics(self) -> dict[str, object]:
        return {
            "provider_name": "software",
            "provider_type": "software",
            "production_ready": False,
            "available": False,
            "summary": "software fallback",
            "details": {},
            "advice": [],
        }

    def set_agent_pin(self, pin: str) -> dict[str, object]:
        self._agent_pin = pin
        return self.runtime_status()

    def clear_agent_pin(self) -> dict[str, object]:
        self._agent_pin = None
        return self.runtime_status()

    def submit_connection_url(self, connection_url: str) -> dict[str, object]:
        return {"ok": True, "connection_url": connection_url}

    def start_registration_from_stored_url(self) -> dict[str, object]:
        self.registration_calls += 1
        return {
            "ok": True,
            "authorized": True,
            "completed": True,
            "session": {"session_id": "sess-reg", "flow": "agentRegister"},
            "registration": {"registered": True},
        }

    def authenticate_registered_agent(self) -> dict[str, object]:
        self.auth_calls += 1
        if self._agent_pin is None:
            return {
                "ok": False,
                "authorized": False,
                "completed": False,
                "reason": "missing_agent_pin",
                "message": "Ask the user for the UnoLock agent PIN, call unolock_set_agent_pin, then continue the session.",
            }
        session = FlowSession(
            session_id="sess-auth",
            flow="agentAccess",
            state="SUCCESS",
            shared_secret=b"",
            current_callback=CallbackAction(type="SUCCESS", result={"spaceIds": [1773]}),
            authorized=True,
        )
        self._session_store.put(session)
        return {
            "ok": True,
            "authorized": True,
            "completed": True,
            "session": session.summary(),
        }

    def advance_active_flow(self) -> dict[str, object]:
        return {
            "ok": False,
            "authorized": False,
            "completed": False,
            "reason": "manual_callback_required",
            "message": "Unexpected pending session in test.",
        }


class AutoSessionToolFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeAgentAuthForAutoSession.instances.clear()
        _FakeWritableRecordsClient.last_update_note = None
        _FakeReadonlyRecordsStaleSessionClient.calls = 0

    def _seed_registered_state(self, tmpdir: str) -> None:
        with patch.dict(os.environ, {"HOME": tmpdir}, clear=False):
            store = RegistrationStore()
            store.save(
                RegistrationState(
                    registered=True,
                    registration_mode="registered",
                    key_id="agent-test",
                    tpm_provider="software",
                    api_base_url="https://api.safe.test.1two.be",
                    transparency_origin="https://safe.test.1two.be",
                    app_version="0.20.21",
                    signing_public_key_b64="ZmFrZQ==",
                )
            )

    def _create_server(self, tmpdir: str, stack: ExitStack):
        self._seed_registered_state(tmpdir)
        stack.enter_context(patch.dict(os.environ, {"HOME": tmpdir}, clear=False))
        stack.enter_context(patch("unolock_mcp.mcp.server.AgentAuthClient", _FakeAgentAuthForAutoSession))
        stack.enter_context(
            patch(
                "unolock_mcp.mcp.server.UnoLockReadonlyRecordsClient",
                _FakeReadonlyRecordsClient,
            )
        )
        stack.enter_context(
            patch(
                "unolock_mcp.mcp.server.UnoLockWritableFilesClient",
                _FakeWritableFilesClient,
            )
        )
        stack.enter_context(
            patch(
                "unolock_mcp.mcp.server.UnoLockWritableRecordsClient",
                _FakeWritableRecordsClient,
            )
        )
        stack.enter_context(patch("unolock_mcp.mcp.server.UnoLockFlowClient", _FakeFlowClient))
        stack.enter_context(
            patch(
                "unolock_mcp.mcp.server.resolve_unolock_config",
                return_value=UnoLockResolvedConfig(
                    base_url="https://api.safe.test.1two.be",
                    transparency_origin="https://safe.test.1two.be",
                    app_version="0.20.21",
                    signing_public_key_b64="ZmFrZQ==",
                    sources={},
                ),
            )
        )
        return create_mcp_server()

    def test_list_spaces_auto_authenticates_without_explicit_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                server = self._create_server(tmpdir, stack)
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                result = server._tool_manager._tools["unolock_list_spaces"].fn()

            self.assertTrue(result["ok"])
            self.assertNotIn("session_id", result)
            self.assertEqual(result["internal_session_id"], "active")
            self.assertEqual(auth.auth_calls, 1)

    def test_set_agent_pin_resumes_pending_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                server = self._create_server(tmpdir, stack)
                auth = _FakeAgentAuthForAutoSession.instances[0]
                blocked = server._tool_manager._tools["unolock_list_spaces"].fn()
                self.assertFalse(blocked["ok"])
                self.assertEqual(blocked["reason"], "missing_agent_pin")
                self.assertEqual(blocked["pending_operation"]["tool"], "unolock_list_spaces")
                self.assertEqual(auth.auth_calls, 1)
                resumed = server._tool_manager._tools["unolock_set_agent_pin"].fn("1")

            self.assertTrue(resumed["has_agent_pin"])
            self.assertEqual(resumed["resumed_operation"]["tool"], "unolock_list_spaces")
            self.assertTrue(resumed["resumed_operation"]["result"]["ok"])
            self.assertNotIn("session_id", resumed["resumed_operation"]["result"])
            self.assertEqual(resumed["resumed_operation"]["result"]["internal_session_id"], "active")
            self.assertEqual(auth.auth_calls, 2)

    def test_link_agent_key_starts_registration_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                server = self._create_server(tmpdir, stack)
                auth = _FakeAgentAuthForAutoSession.instances[0]
                result = server._tool_manager._tools["unolock_register"].fn(
                    "https://safe.test/#/agent-register/x/y/z",
                    "1",
                )

            self.assertTrue(result["ok"])
            self.assertTrue(result["completed"])
            self.assertEqual(auth.registration_calls, 1)
            self.assertEqual(auth.flow_client_sets, 1)
            self.assertTrue(result["pin"]["has_agent_pin"])

    def test_list_spaces_reuses_latest_authorized_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                server = self._create_server(tmpdir, stack)
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                first = server._tool_manager._tools["unolock_list_spaces"].fn()
                second = server._tool_manager._tools["unolock_list_spaces"].fn()

            self.assertEqual(first["internal_session_id"], "active")
            self.assertEqual(second["internal_session_id"], "active")
            self.assertEqual(auth.auth_calls, 1)

    def test_list_spaces_recovers_from_stale_authorized_session_http_400(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                self._seed_registered_state(tmpdir)
                stack.enter_context(patch.dict(os.environ, {"HOME": tmpdir}, clear=False))
                stack.enter_context(patch("unolock_mcp.mcp.server.AgentAuthClient", _FakeAgentAuthForAutoSession))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockReadonlyRecordsClient",
                        _FakeReadonlyRecordsStaleSessionClient,
                    )
                )
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockWritableFilesClient",
                        _FakeWritableFilesClient,
                    )
                )
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockWritableRecordsClient",
                        _FakeWritableRecordsClient,
                    )
                )
                stack.enter_context(patch("unolock_mcp.mcp.server.UnoLockFlowClient", _FakeFlowClient))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.resolve_unolock_config",
                        return_value=UnoLockResolvedConfig(
                            base_url="https://api.safe.test.1two.be",
                            transparency_origin="https://safe.test.1two.be",
                            app_version="0.20.21",
                            signing_public_key_b64="ZmFrZQ==",
                            sources={},
                        ),
                    )
                )
                server = create_mcp_server()
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                result = server._tool_manager._tools["unolock_list_spaces"].fn()

            self.assertTrue(result["ok"])
            self.assertEqual(result["internal_session_id"], "active")
            self.assertEqual(auth.auth_calls, 2)
            self.assertEqual(_FakeReadonlyRecordsStaleSessionClient.calls, 2)

    def test_set_and_get_current_space(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                server = self._create_server(tmpdir, stack)
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                selected = server._tool_manager._tools["unolock_set_current_space"].fn(1773)
                current = server._tool_manager._tools["unolock_get_current_space"].fn()

            self.assertTrue(selected["ok"])
            self.assertEqual(selected["current_space_id"], 1773)
            self.assertTrue(selected["space"]["current"])
            self.assertTrue(current["selected"])
            self.assertEqual(current["current_space_id"], 1773)

    def test_list_spaces_selects_first_space_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                server = self._create_server(tmpdir, stack)
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                result = server._tool_manager._tools["unolock_list_spaces"].fn()
                current = server._tool_manager._tools["unolock_get_current_space"].fn()

            self.assertTrue(result["ok"])
            self.assertEqual(result["current_space_id"], 1773)
            self.assertTrue(result["spaces"][0]["current"])
            self.assertFalse(result["spaces"][1]["current"])
            self.assertTrue(current["selected"])
            self.assertEqual(current["current_space_id"], 1773)

    def test_list_records_defaults_to_current_space(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                server = self._create_server(tmpdir, stack)
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                server._tool_manager._tools["unolock_set_current_space"].fn(1773)
                result = server._tool_manager._tools["unolock_list_records"].fn()

            self.assertTrue(result["ok"])
            self.assertEqual(result["space_id"], 1773)
            self.assertEqual(result["space_id_filter"], 1773)

    def test_update_note_uses_latest_version_when_expected_version_is_omitted(self) -> None:
        class _FakeReadonlyRecordsWithVersion(_FakeReadonlyRecordsClient):
            def get_record(self, session_id: str, record_ref: str) -> dict[str, object]:
                return {
                    "record_ref": record_ref,
                    "version": 9,
                    "title": "existing title",
                    "plain_text": "existing",
                    "space_id": 1773,
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                self._seed_registered_state(tmpdir)
                stack.enter_context(patch.dict(os.environ, {"HOME": tmpdir}, clear=False))
                stack.enter_context(patch("unolock_mcp.mcp.server.AgentAuthClient", _FakeAgentAuthForAutoSession))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockReadonlyRecordsClient",
                        _FakeReadonlyRecordsWithVersion,
                    )
                )
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockWritableFilesClient",
                        _FakeWritableFilesClient,
                    )
                )
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockWritableRecordsClient",
                        _FakeWritableRecordsClient,
                    )
                )
                stack.enter_context(patch("unolock_mcp.mcp.server.UnoLockFlowClient", _FakeFlowClient))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.resolve_unolock_config",
                        return_value=UnoLockResolvedConfig(
                            base_url="https://api.safe.test.1two.be",
                            transparency_origin="https://safe.test.1two.be",
                            app_version="0.20.21",
                            signing_public_key_b64="ZmFrZQ==",
                            sources={},
                        ),
                    )
                )
                server = create_mcp_server()
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                result = server._tool_manager._tools["unolock_update_note"].fn("archive:1", 0, None, "body")

        self.assertTrue(result["ok"])
        self.assertEqual(_FakeWritableRecordsClient.last_update_note["expected_version"], 9)
        self.assertEqual(_FakeWritableRecordsClient.last_update_note["title"], "existing title")
        self.assertEqual(_FakeWritableRecordsClient.last_update_note["text"], "body")

    def test_update_note_reuses_existing_text_when_omitted(self) -> None:
        class _FakeReadonlyRecordsWithContent(_FakeReadonlyRecordsClient):
            def get_record(self, session_id: str, record_ref: str) -> dict[str, object]:
                return {
                    "record_ref": record_ref,
                    "version": 4,
                    "title": "existing title",
                    "plain_text": "existing body",
                    "space_id": 1773,
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                self._seed_registered_state(tmpdir)
                stack.enter_context(patch.dict(os.environ, {"HOME": tmpdir}, clear=False))
                stack.enter_context(patch("unolock_mcp.mcp.server.AgentAuthClient", _FakeAgentAuthForAutoSession))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockReadonlyRecordsClient",
                        _FakeReadonlyRecordsWithContent,
                    )
                )
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockWritableFilesClient",
                        _FakeWritableFilesClient,
                    )
                )
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockWritableRecordsClient",
                        _FakeWritableRecordsClient,
                    )
                )
                stack.enter_context(patch("unolock_mcp.mcp.server.UnoLockFlowClient", _FakeFlowClient))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.resolve_unolock_config",
                        return_value=UnoLockResolvedConfig(
                            base_url="https://api.safe.test.1two.be",
                            transparency_origin="https://safe.test.1two.be",
                            app_version="0.20.21",
                            signing_public_key_b64="ZmFrZQ==",
                            sources={},
                        ),
                    )
                )
                server = create_mcp_server()
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                result = server._tool_manager._tools["unolock_update_note"].fn("archive:1", 0, "new title", None)

        self.assertTrue(result["ok"])
        self.assertEqual(_FakeWritableRecordsClient.last_update_note["expected_version"], 4)
        self.assertEqual(_FakeWritableRecordsClient.last_update_note["title"], "new title")
        self.assertEqual(_FakeWritableRecordsClient.last_update_note["text"], "existing body")

    def test_get_record_wraps_record_payload(self) -> None:
        class _FakeReadonlyRecordClient(_FakeReadonlyRecordsClient):
            def get_record(self, session_id: str, record_ref: str) -> dict[str, object]:
                return {
                    "record_ref": record_ref,
                    "version": 2,
                    "title": "title",
                    "plain_text": "body",
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                self._seed_registered_state(tmpdir)
                stack.enter_context(patch.dict(os.environ, {"HOME": tmpdir}, clear=False))
                stack.enter_context(patch("unolock_mcp.mcp.server.AgentAuthClient", _FakeAgentAuthForAutoSession))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockReadonlyRecordsClient",
                        _FakeReadonlyRecordClient,
                    )
                )
                stack.enter_context(patch("unolock_mcp.mcp.server.UnoLockFlowClient", _FakeFlowClient))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.resolve_unolock_config",
                        return_value=UnoLockResolvedConfig(
                            base_url="https://api.safe.test.1two.be",
                            transparency_origin="https://safe.test.1two.be",
                            app_version="0.20.21",
                            signing_public_key_b64="ZmFrZQ==",
                            sources={},
                        ),
                    )
                )
                server = create_mcp_server()
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                result = server._tool_manager._tools["unolock_get_record"].fn("archive:1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["record_ref"], "archive:1")

    def test_get_file_wraps_file_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                self._seed_registered_state(tmpdir)
                stack.enter_context(patch.dict(os.environ, {"HOME": tmpdir}, clear=False))
                stack.enter_context(patch("unolock_mcp.mcp.server.AgentAuthClient", _FakeAgentAuthForAutoSession))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockReadonlyFilesClient",
                        _FakeReadonlyFilesClient,
                    )
                )
                stack.enter_context(patch("unolock_mcp.mcp.server.UnoLockFlowClient", _FakeFlowClient))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.resolve_unolock_config",
                        return_value=UnoLockResolvedConfig(
                            base_url="https://api.safe.test.1two.be",
                            transparency_origin="https://safe.test.1two.be",
                            app_version="0.20.21",
                            signing_public_key_b64="ZmFrZQ==",
                            sources={},
                        ),
                    )
                )
                server = create_mcp_server()
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                result = server._tool_manager._tools["unolock_get_file"].fn("archive-1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["file"]["archive_id"], "archive-1")

    def test_list_records_auto_selects_first_space_when_none_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                server = self._create_server(tmpdir, stack)
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                result = server._tool_manager._tools["unolock_list_records"].fn()
                current = server._tool_manager._tools["unolock_get_current_space"].fn()

            self.assertTrue(result["ok"])
            self.assertEqual(result["space_id"], 1773)
            self.assertEqual(result["space_id_filter"], 1773)
            self.assertEqual(current["current_space_id"], 1773)

    def test_upload_file_uses_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                server = self._create_server(tmpdir, stack)
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                server._tool_manager._tools["unolock_set_current_space"].fn(1773)
                result = server._tool_manager._tools["unolock_upload_file"].fn(
                    "/tmp/example.txt",
                    "agent-upload.txt",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["space_id"], 1773)
            self.assertEqual(result["file"]["name"], "agent-upload.txt")

    def test_replace_file_uses_title(self) -> None:
        class _FakeReplaceFilesClient(_FakeWritableFilesClient):
            def replace_file(
                self,
                session_id: str,
                *,
                archive_id: str,
                local_path: str,
                name: str | None = None,
                mime_type: str | None = None,
            ) -> dict[str, object]:
                return {
                    "ok": True,
                    "file": {
                        "archive_id": archive_id,
                        "space_id": 1773,
                        "name": name,
                        "local_path": local_path,
                        "mime_type": mime_type or "application/octet-stream",
                    },
                    "internal_session_id": session_id,
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                self._seed_registered_state(tmpdir)
                stack.enter_context(patch.dict(os.environ, {"HOME": tmpdir}, clear=False))
                stack.enter_context(patch("unolock_mcp.mcp.server.AgentAuthClient", _FakeAgentAuthForAutoSession))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockReadonlyRecordsClient",
                        _FakeReadonlyRecordsClient,
                    )
                )
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockWritableFilesClient",
                        _FakeReplaceFilesClient,
                    )
                )
                stack.enter_context(patch("unolock_mcp.mcp.server.UnoLockFlowClient", _FakeFlowClient))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.resolve_unolock_config",
                        return_value=UnoLockResolvedConfig(
                            base_url="https://api.safe.test.1two.be",
                            transparency_origin="https://safe.test.1two.be",
                            app_version="0.20.21",
                            signing_public_key_b64="ZmFrZQ==",
                            sources={},
                        ),
                    )
                )
                server = create_mcp_server()
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                result = server._tool_manager._tools["unolock_replace_file"].fn(
                    "archive-1",
                    "/tmp/example.txt",
                    "agent-replace.txt",
                    None,
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["file"]["name"], "agent-replace.txt")

    def test_list_spaces_returns_clear_error_when_agent_has_no_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                self._seed_registered_state(tmpdir)
                stack.enter_context(patch.dict(os.environ, {"HOME": tmpdir}, clear=False))
                stack.enter_context(patch.object(_FakeAgentAuthForAutoSession, "instances", []))
                stack.enter_context(patch("unolock_mcp.mcp.server.AgentAuthClient", _FakeAgentAuthForAutoSession))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockReadonlyRecordsClient",
                        _FakeReadonlyRecordsNoSpacesClient,
                    )
                )
                stack.enter_context(patch("unolock_mcp.mcp.server.UnoLockFlowClient", _FakeFlowClient))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.resolve_unolock_config",
                        return_value=UnoLockResolvedConfig(
                            base_url="https://api.safe.test.1two.be",
                            transparency_origin="https://safe.test.1two.be",
                            app_version="0.20.21",
                            signing_public_key_b64="ZmFrZQ==",
                            sources={},
                        ),
                    )
                )
                server = create_mcp_server()
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                result = server._tool_manager._tools["unolock_list_spaces"].fn()
                current = server._tool_manager._tools["unolock_get_current_space"].fn()

            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "no_accessible_spaces")
            self.assertIn("does not currently have access to any UnoLock Spaces", result["message"])
            self.assertFalse(current["ok"])
            self.assertEqual(current["reason"], "no_accessible_spaces")

    def test_list_records_returns_clear_error_when_agent_has_no_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with ExitStack() as stack:
                self._seed_registered_state(tmpdir)
                stack.enter_context(patch.dict(os.environ, {"HOME": tmpdir}, clear=False))
                stack.enter_context(patch.object(_FakeAgentAuthForAutoSession, "instances", []))
                stack.enter_context(patch("unolock_mcp.mcp.server.AgentAuthClient", _FakeAgentAuthForAutoSession))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.UnoLockReadonlyRecordsClient",
                        _FakeReadonlyRecordsNoSpacesClient,
                    )
                )
                stack.enter_context(patch("unolock_mcp.mcp.server.UnoLockFlowClient", _FakeFlowClient))
                stack.enter_context(
                    patch(
                        "unolock_mcp.mcp.server.resolve_unolock_config",
                        return_value=UnoLockResolvedConfig(
                            base_url="https://api.safe.test.1two.be",
                            transparency_origin="https://safe.test.1two.be",
                            app_version="0.20.21",
                            signing_public_key_b64="ZmFrZQ==",
                            sources={},
                        ),
                    )
                )
                server = create_mcp_server()
                auth = _FakeAgentAuthForAutoSession.instances[0]
                auth.set_agent_pin("1")
                result = server._tool_manager._tools["unolock_list_records"].fn()

            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "no_accessible_spaces")
            self.assertIn("share or create a UnoLock Space", result["suggested_action"])


if __name__ == "__main__":
    unittest.main()
