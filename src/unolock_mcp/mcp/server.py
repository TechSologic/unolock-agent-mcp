from __future__ import annotations

import os
from typing import Any, Callable
from urllib.error import HTTPError

from mcp.server.fastmcp import FastMCP

from unolock_mcp.api.client import UnoLockApiClient
from unolock_mcp.api.files import UnoLockReadonlyFilesClient, UnoLockWritableFilesClient
from unolock_mcp.api.records import UnoLockReadonlyRecordsClient, UnoLockWritableRecordsClient
from unolock_mcp.auth.agent_auth import AgentAuthClient
from unolock_mcp.auth.flow_client import UnoLockFlowClient
from unolock_mcp.auth.local_probe import LocalServerProbe
from unolock_mcp.auth.registration_store import RegistrationStore
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.config import resolve_unolock_config
from unolock_mcp.domain.models import UnoLockConfig
from unolock_mcp.update import get_update_status
from unolock_mcp.sync.runtime_store import SyncRuntimeStore
from unolock_mcp.sync.service import SyncService
from unolock_mcp.sync.config_note import DEFAULT_SYNC_DEBOUNCE_SECONDS, DEFAULT_SYNC_POLL_SECONDS


def _advanced_tools_enabled() -> bool:
    return os.environ.get("UNOLOCK_MCP_ENABLE_ADVANCED_TOOLS", "").strip().lower() in {"1", "true", "yes", "on"}


def _tool_error_response(exc: Exception) -> dict[str, Any]:
    raw_message = str(exc).strip() or "Unknown write failure"
    reason = "operation_failed"
    message = raw_message
    if ": " in raw_message:
        prefix, remainder = raw_message.split(": ", 1)
        if prefix and prefix.replace("_", "").isalnum() and prefix == prefix.lower():
            reason = prefix
            message = remainder

    suggested_action_map = {
        "space_read_only": "Read spaces or records again and respect writable=false and allowed_operations before writing.",
        "record_locked": "Do not modify this record. Read it again and inspect locked/read_only metadata.",
        "write_conflict_requires_reread": "Reread the target record or space, then retry with the latest version.",
        "read_first_before_write": "Read the target record first so the MCP has current cache and version metadata.",
        "operation_not_allowed": "Inspect allowed_operations on the space or record and choose a supported action.",
        "record_not_found": "Reread the target space or record and verify the current record_ref or item id.",
        "item_not_found": "Reread the checklist and use the current checklist item ids before retrying.",
        "invalid_input": "Correct the input payload and retry the write operation.",
        "invalid_sync_config_note": "Inspect or repair the reserved UnoLock sync config note in the affected Space, then retry.",
        "no_accessible_spaces": "Ask the user to share or create a UnoLock Space for this Agent Key, or issue a different Agent Key with Space access.",
        "missing_current_space": "List spaces or get the current UnoLock space so the MCP can select an accessible default space.",
        "missing_connection_url": "Ask the user for the one-time UnoLock Agent Key URL and PIN, then call unolock_register.",
        "wrong_connection_url_type": "Ask the user for a UnoLock Agent Key URL in the #/agent-register/... format.",
        "session_not_found": "Authenticate again or restart the UnoLock bootstrap flow, then retry the request.",
        "runtime_metadata_missing": "Submit a UnoLock Agent Key URL from the target Safe first. If this is a non-standard deployment, confirm that the Safe deployment is published correctly.",
    }
    return {
        "ok": False,
        "reason": reason,
        "message": message,
        "suggested_action": suggested_action_map.get(reason, "Review the error and retry with corrected input or fresher data."),
    }


def _strip_session_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_session_ids(item)
            for key, item in value.items()
            if key != "session_id"
        }
    if isinstance(value, list):
        return [_strip_session_ids(item) for item in value]
    return value


def _registration_status_payload(
    registration_store: RegistrationStore,
    session_store: SessionStore,
    agent_auth: AgentAuthClient,
) -> dict[str, Any]:
    registration = registration_store.load().summary()
    runtime = agent_auth.runtime_status()
    tpm = agent_auth.tpm_diagnostics()
    security_warning = runtime.get("security_warning")
    provider_mismatch = runtime.get("tpm_provider_mismatch_detail")
    next_action = "authenticate_agent"
    guidance = (
        "Agent registration is configured. The normal UnoLock data tools can authenticate automatically when needed "
        "and will stop only for one concrete missing input such as the PIN."
    )
    pending_flow = None
    if session_store.has_active_flow(incomplete_only=True):
        try:
            pending_flow = _strip_session_ids(session_store.get().summary())
        except KeyError:
            pending_flow = None

    if pending_flow and pending_flow.get("current_callback_type") in {"SUCCESS", "FAILED"}:
        pending_flow = None

    if provider_mismatch:
        next_action = "resolve_tpm_provider_mismatch"
        guidance = str(provider_mismatch.get("message"))
    elif pending_flow is not None:
        callback_type = pending_flow.get("current_callback_type")
        if callback_type == "GetPin" and not runtime.get("has_agent_pin"):
            next_action = "ask_for_agent_pin_then_continue"
            guidance = (
                "A UnoLock flow is waiting at GetPin. Ask the user for the agent PIN, call "
                "unolock_set_agent_pin, then retry the original UnoLock request."
            )
        else:
            next_action = "continue_pending_flow"
            guidance = (
                "A UnoLock flow is already in progress. Retry the original UnoLock request."
            )
    elif registration.get("registered"):
        if not runtime.get("has_agent_pin"):
            next_action = "authenticate_or_set_pin"
            guidance = (
                "Registration is configured. Ask the user for the agent PIN and call unolock_set_agent_pin before authenticating."
            )
        else:
            next_action = "authenticate_agent"
            guidance = (
                "Agent registration is configured. The normal UnoLock data tools can authenticate automatically when "
                "needed and will stop only for one concrete missing input such as the PIN."
            )
    elif not registration.get("has_connection_url"):
        next_action = "ask_for_connection_url"
        guidance = (
            "Ask the user for the one-time UnoLock Agent Key URL in the #/agent-register/... format. If they need "
            "to create one, ask them to open the Safe web app at https://safe.unolock.com/, create a dedicated Agent "
            "Key, and paste the generated URL here along with the PIN."
        )
    else:
        next_action = "start_registration"
        guidance = (
            "The Agent Key URL is already stored. Continue the normal UnoLock flow. Do not speculate about menu "
            "labels, URL expiry, or deployment internals unless the MCP reports a concrete blocker."
        )

    if security_warning:
        guidance = f"{guidance} Warning: {security_warning.get('message')}"
    guidance = (
        f"{guidance} On a fresh host, the first MCP start can take longer because local cryptographic code may need "
        "to be compiled or prepared."
    )

    primary_tools = [
        "unolock_register",
        "unolock_list_spaces",
        "unolock_set_current_space",
        "unolock_list_records",
        "unolock_list_files",
        "unolock_get_record",
    ]
    write_tools = [
        "unolock_create_note",
        "unolock_update_note",
        "unolock_append_note",
        "unolock_upload_file",
        "unolock_download_file",
        "unolock_rename_record",
        "unolock_create_checklist",
        "unolock_set_checklist_item_done",
        "unolock_add_checklist_item",
        "unolock_remove_checklist_item",
    ]
    advanced_tools = []
    if _advanced_tools_enabled():
        advanced_tools = [
            "unolock_probe_local_server",
            "unolock_get_update_status",
            "unolock_start_flow",
            "unolock_continue_flow",
            "unolock_get_session",
            "unolock_list_sessions",
            "unolock_delete_session",
            "unolock_call_api",
            "unolock_get_spaces",
            "unolock_get_archives",
        ]

    public_registration = {
        key: value
        for key, value in registration.items()
        if key not in {"registration_mode", "session_id"}
    }
    public_registration["registration_state"] = (
        "registered"
        if registration.get("registered")
        else "waiting_for_connection_url"
        if not registration.get("has_connection_url")
        else "ready_to_register"
    )

    return _strip_session_ids({
        **public_registration,
        **runtime,
        "tpm_diagnostics": tpm,
        "security_warning": security_warning,
        "pending_flow": pending_flow,
        "recommended_next_action": next_action,
        "guidance": guidance,
        "primary_tools": primary_tools,
        "write_tools": write_tools,
        "advanced_tools": advanced_tools,
        "explanation_resources": [
            "unolock://usage/quickstart",
            "unolock://usage/about",
            "unolock://usage/security-model",
            "unolock://usage/updates",
        ],
        "workflow_summary": [
            "Allow extra time on the first start on a fresh host, because local cryptographic code may need to be compiled or prepared.",
            "Ask the user for the one-time Agent Key URL and PIN together.",
            "Call the normal data tools directly and let the MCP authenticate automatically when needed.",
            "After authentication, set the current space once and let normal record/file tools use it by default.",
            "Read a space or record before writing so you have current version and allowed_operations metadata.",
            "If a write reports conflict, reread the target record and retry with the latest version.",
        ],
        "agent_behavior_rules": [
            "Use plain user-facing wording.",
            "Report one concrete next step.",
            "Ask for one concrete missing input at a time.",
        ],
    })


def create_mcp_server() -> FastMCP:
    session_store = SessionStore()
    registration_store = RegistrationStore()
    agent_auth = AgentAuthClient(None, session_store, registration_store)
    sync_runtime_store = SyncRuntimeStore()
    pending_operation: dict[str, Any] | None = None

    def resolve_runtime_config() -> UnoLockConfig:
        registration = registration_store.load()
        resolved = resolve_unolock_config(
            base_url=registration.api_base_url,
            transparency_origin=registration.transparency_origin,
            app_version=registration.app_version,
            signing_public_key_b64=registration.signing_public_key_b64,
        )
        registration_store.update_runtime_config(
            base_url=resolved.base_url,
            transparency_origin=resolved.transparency_origin,
            app_version=resolved.app_version,
            signing_public_key_b64=resolved.signing_public_key_b64,
        )
        if not resolved.is_complete():
            raise ValueError(
                "runtime_metadata_missing: UnoLock does not know which Safe deployment to use yet. Submit a "
                "UnoLock Agent Key URL from the target Safe first."
            )
        return UnoLockConfig(
            base_url=resolved.base_url or "http://127.0.0.1:3000",
            app_version=resolved.app_version or "",
            signing_public_key_b64=resolved.signing_public_key_b64 or "",
        )

    def ensure_flow_client() -> UnoLockFlowClient:
        flow_client = UnoLockFlowClient(resolve_runtime_config())
        agent_auth.set_flow_client(flow_client)
        return flow_client

    def daemon_keepalive() -> dict[str, Any] | None:
        try:
            ensure_flow_client()
        except ValueError:
            return None
        keepalive_result = agent_auth.keep_authorized_session_alive()
        try:
            active_session = session_store.get()
        except KeyError:
            return keepalive_result
        if not active_session.authorized:
            return keepalive_result
        key_id = registration_store.load().key_id
        if not key_id:
            return keepalive_result
        try:
            create_sync_service().refresh_from_remote(SessionStore.ACTIVE_SESSION_ID, key_id=key_id)
        except Exception:
            return keepalive_result
        return keepalive_result

    def daemon_sync_poll() -> dict[str, Any] | None:
        try:
            ensure_flow_client()
            active_session = session_store.get()
        except (ValueError, KeyError):
            return None
        if not active_session.authorized:
            return None
        key_id = registration_store.load().key_id
        if not key_id:
            return None
        try:
            return create_sync_service().run_syncs(
                SessionStore.ACTIVE_SESSION_ID,
                key_id=key_id,
                run_all=True,
                force=False,
            )
        except ValueError:
            return None

    def _normalize_tool_args(tool_args: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in tool_args.items() if value is not None}

    def create_sync_service() -> SyncService:
        return SyncService(
            UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            ),
            UnoLockWritableRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            ),
            UnoLockReadonlyFilesClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            ),
            UnoLockWritableFilesClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            ),
            sync_runtime_store,
        )

    def _pending_operation_payload() -> dict[str, Any] | None:
        if pending_operation is None:
            return None
        return {
            "tool": pending_operation["tool"],
            "arguments": dict(pending_operation["arguments"]),
        }

    def _remember_pending_operation(
        tool_name: str,
        tool_args: dict[str, Any],
        resume: Callable[[], dict[str, Any]],
    ) -> None:
        nonlocal pending_operation
        pending_operation = {
            "tool": tool_name,
            "arguments": _normalize_tool_args(tool_args),
            "resume": resume,
        }

    def _clear_pending_operation() -> None:
        nonlocal pending_operation
        pending_operation = None

    def _current_space_id() -> int | None:
        current = registration_store.load().current_space_id
        return current if isinstance(current, int) and current > 0 else None

    def _resolve_space_id(
        space_id: int | None,
        *,
        required: bool,
        available_spaces: Callable[[], dict[str, Any]] | None = None,
    ) -> int | None:
        if isinstance(space_id, int) and space_id > 0:
            return space_id
        current = _current_space_id()
        if current is not None:
            return current
        if available_spaces is not None:
            current = _decorate_spaces_payload(available_spaces()).get("current_space_id")
            if isinstance(current, int) and current > 0:
                return current
        if required:
            raise ValueError(
                "missing_current_space: No current UnoLock space is selected or accessible yet. Call unolock_list_spaces or unolock_get_current_space so the MCP can select an accessible default space."
            )
        return None

    def _current_space_payload() -> dict[str, Any]:
        return {
            "selected": _current_space_id() is not None,
            "current_space_id": _current_space_id(),
        }

    def _attach_space_id(payload: dict[str, Any], space_id: int | None) -> dict[str, Any]:
        if isinstance(space_id, int) and space_id > 0:
            payload["space_id"] = space_id
        return payload

    def _resolve_record_version(resolved_session_id: str, record_ref: str, expected_version: int) -> int:
        if isinstance(expected_version, int) and expected_version > 0:
            return expected_version
        readonly_records = UnoLockReadonlyRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        record = readonly_records.get_record(resolved_session_id, record_ref)
        version = int(record.get("version") or 0)
        if version <= 0:
            raise ValueError("record_not_found: Could not determine the current record version.")
        return version

    def _get_record_projection(resolved_session_id: str, record_ref: str) -> dict[str, Any]:
        readonly_records = UnoLockReadonlyRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return readonly_records.get_record(resolved_session_id, record_ref)

    def _resolve_note_update_fields(
        resolved_session_id: str,
        record_ref: str,
        *,
        title: str | None,
        text: str | None,
    ) -> tuple[str, str]:
        if title is not None and text is not None:
            return title, text
        record = _get_record_projection(resolved_session_id, record_ref)
        resolved_title = title if title is not None else str(record.get("title", ""))
        resolved_text = text if text is not None else str(record.get("plain_text", ""))
        return resolved_title, resolved_text

    def _decorate_spaces_payload(payload: dict[str, Any]) -> dict[str, Any]:
        current_space_id = _current_space_id()
        spaces = payload.get("spaces")
        if isinstance(spaces, list) and len(spaces) == 0:
            raise ValueError(
                "no_accessible_spaces: This Agent Key does not currently have access to any UnoLock Spaces."
            )
        if current_space_id is None and isinstance(spaces, list):
            for space in spaces:
                if isinstance(space, dict):
                    candidate = space.get("space_id")
                    if isinstance(candidate, int) and candidate > 0:
                        registration_store.set_current_space(candidate)
                        current_space_id = candidate
                        break
        if isinstance(spaces, list):
            for space in spaces:
                if isinstance(space, dict):
                    space["current"] = space.get("space_id") == current_space_id
        payload["current_space_id"] = current_space_id
        return payload

    def _build_blocked_operation_response(
        tool_name: str,
        tool_args: dict[str, Any],
        auth_result: dict[str, Any],
        resume: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        _remember_pending_operation(tool_name, tool_args, resume)
        reason = str(auth_result.get("reason") or "operation_blocked")
        message = str(auth_result.get("message") or "UnoLock needs an additional step before it can complete this request.")
        suggested_action = auth_result.get("suggested_action")
        if reason == "missing_agent_pin":
            suggested_action = (
                "Ask the user for the UnoLock agent PIN, call unolock_set_agent_pin, and the MCP will retry "
                "the original request automatically."
            )
        elif reason == "missing_connection_url":
            suggested_action = (
                "Ask the user for the one-time UnoLock Agent Key URL, submit it with "
                "unolock_register, and retry the original request."
            )
        elif reason == "agent_key_invalid_or_consumed":
            suggested_action = "Ask the user for a fresh UnoLock Agent Key URL, then retry the original request."
        elif reason == "manual_callback_required":
            suggested_action = "Retry the original UnoLock request."
        elif suggested_action is None:
            suggested_action = "Resolve the reported UnoLock blocker, then retry the original request."
        return {
            "ok": False,
            "reason": reason,
            "message": message,
            "suggested_action": suggested_action,
            "pending_operation": _pending_operation_payload(),
            "auth": _strip_session_ids(auth_result),
        }

    def _resume_pending_operation(trigger: str) -> dict[str, Any] | None:
        nonlocal pending_operation
        if pending_operation is None:
            return None
        operation = pending_operation
        pending_operation = None
        result = operation["resume"]()
        if isinstance(result, dict) and result.get("ok") is False and result.get("pending_operation"):
            pending_operation = operation
        return {
            "trigger": trigger,
            "tool": operation["tool"],
            "arguments": dict(operation["arguments"]),
            "result": _strip_session_ids(result),
        }

    def _ensure_authenticated_session(
        *,
        tool_name: str,
        tool_args: dict[str, Any],
        resume: Callable[[], dict[str, Any]],
    ) -> dict[str, Any] | None:
        if session_store.has_active_flow(authorized=True):
            try:
                session_store.get_auth_context()
                return None
            except KeyError:
                pass

        ensure_flow_client()

        while True:
            if session_store.has_active_flow(incomplete_only=True):
                pending_result = agent_auth.advance_active_flow()
                if pending_result.get("ok") and pending_result.get("authorized") and pending_result.get("completed"):
                    pending_flow = pending_result.get("session") or {}
                    if pending_flow.get("flow") == "agentAccess":
                        return None
                    continue
                return _build_blocked_operation_response(tool_name, tool_args, pending_result, resume)

            registration = registration_store.load()
            if not registration.registered:
                if registration.connection_url is None:
                    return _build_blocked_operation_response(
                        tool_name,
                        tool_args,
                        {
                            "ok": False,
                            "reason": "missing_connection_url",
                            "message": "UnoLock is not registered on this machine yet. The MCP needs the one-time Agent Key URL first.",
                        },
                        resume,
                    )
                registration_result = agent_auth.start_registration_from_stored_url()
                if registration_result.get("ok") and registration_result.get("authorized") and registration_result.get("completed"):
                    continue
                return _build_blocked_operation_response(tool_name, tool_args, registration_result, resume)

            auth_result = agent_auth.authenticate_registered_agent()
            if auth_result.get("ok") and auth_result.get("authorized") and auth_result.get("completed"):
                return None
            return _build_blocked_operation_response(tool_name, tool_args, auth_result, resume)

    def _run_with_auto_session(
        tool_name: str,
        tool_args: dict[str, Any],
        _requested_session_id: str | None,
        operation: Callable[[str], dict[str, Any]],
    ) -> dict[str, Any]:
        normalized_tool_args = _normalize_tool_args(tool_args)

        def resume() -> dict[str, Any]:
            return _run_with_auto_session(tool_name, normalized_tool_args, None, operation)

        retried_stale_authorized_session = False
        while True:
            try:
                blocker = _ensure_authenticated_session(
                    tool_name=tool_name,
                    tool_args=normalized_tool_args,
                    resume=resume,
                )
                if blocker is not None:
                    return blocker
                result = _strip_session_ids(operation(SessionStore.ACTIVE_SESSION_ID))
                _clear_pending_operation()
                return result
            except HTTPError as exc:
                stale_authorized_session = (
                    exc.code == 400
                    and not retried_stale_authorized_session
                    and session_store.has_active_flow(authorized=True)
                )
                if not stale_authorized_session:
                    return _tool_error_response(exc)
                session_store.clear()
                retried_stale_authorized_session = True
            except (ValueError, KeyError) as exc:
                return _tool_error_response(exc)

    server = FastMCP(
        name="UnoLock Agent",
        instructions=(
            "Call the normal UnoLock data tools directly. If the MCP needs the one-time Agent Key URL or the PIN, it "
            "will ask for that concrete input. Prefer unolock_register, unolock_list_spaces, "
            "unolock_set_current_space, unolock_list_records, unolock_list_files, and unolock_get_record. Read "
            "records before writing so you have current version and allowed_operations metadata. "
            "On a fresh host, the first MCP start can take longer because local cryptographic code may need to be "
            "compiled or prepared. "
            "If registration is not configured, ask the user for the one-time UnoLock Agent Key URL and "
            "the PIN, then submit them with unolock_register. The Agent Key URL is only for the one-time setup step. "
            "Normal data tools can authenticate automatically and resume after a PIN is supplied. After authentication, "
            "select a current space and let normal record/file tools use it by default. "
            "If the user needs an explanation of what UnoLock is, why the MCP asks for an Agent Key URL or PIN, "
            "or why host assurance matters, use the explanatory UnoLock resources instead of improvising. "
            "If the host is operating at reduced assurance, treat that as warning-only information; there is no separate acknowledgment step."
        ),
    )
    server.unolock_keepalive = daemon_keepalive
    server.unolock_sync_poll = daemon_sync_poll
    export_handoff_state = getattr(agent_auth, "export_local_handoff_state", None)
    if callable(export_handoff_state):
        server.unolock_export_handoff_state = export_handoff_state

    @server.resource(
        "unolock://registration/status",
        name="UnoLock Registration Status",
        description="Registration state and user guidance for the UnoLock agent MCP.",
        mime_type="application/json",
    )
    def registration_status_resource() -> dict[str, Any]:
        return _registration_status_payload(registration_store, session_store, agent_auth)

    @server.resource(
        "unolock://usage/quickstart",
        name="UnoLock Quickstart",
        description="Short, agent-oriented guidance for the preferred UnoLock MCP workflow.",
        mime_type="application/json",
    )
    def quickstart_resource() -> dict[str, Any]:
        return {
            "primary_tools": [
                "unolock_register",
                "unolock_list_spaces",
                "unolock_set_current_space",
                "unolock_list_records",
                "unolock_list_files",
                "unolock_get_record",
            ],
            "normal_flow_note": (
                "After the local stdio MCP is running, call the normal UnoLock tools directly and follow the MCP's "
                "directions. Do not invent a separate manual bootstrap sequence."
            ),
            "startup_note": (
                "On a fresh host, the first MCP start can take longer because local cryptographic code may need to "
                "be compiled or prepared."
            ),
            "space_rule": (
                "After authentication, list spaces and set the current space. Normal record and file tools operate "
                "in the current space automatically and report the space_id they used."
            ),
            "agent_behavior_note": (
                "Ask for the Agent Key URL and PIN, then follow the MCP's directions."
            ),
            "write_rule": "Read the target record first, then use record_ref, version, writable, and allowed_operations before writing.",
        }

    @server.resource(
        "unolock://usage/about",
        name="About UnoLock Agent",
        description="Agent-safe explanation of what UnoLock is and what an Agent Key does.",
        mime_type="application/json",
    )
    def about_resource() -> dict[str, Any]:
        return {
            "summary": (
                "UnoLock is a zero-knowledge Safe for sensitive data. An Agent Key lets an AI agent connect to an "
                "existing Safe with tightly scoped Space permissions instead of using a reusable API key."
            ),
            "what_to_tell_the_user": [
                "UnoLock keeps sensitive data inside a Safe controlled by the user.",
                "An Agent Key is a dedicated access key for an AI agent, not a full admin credential.",
                "The agent only gets the Spaces and permissions granted to that Agent Key.",
                "The user manages the Agent Key in the UnoLock Safe web app.",
                "The one-time Agent Key URL is used once to set up the Agent Key on this device.",
                "After that, ongoing access uses the registered local Agent Key plus normal UnoLock authentication, not the URL itself.",
            ],
            "how_to_ask": [
                "If the user does not already have an Agent Key URL, ask them to open the Safe web app at https://safe.unolock.com/ and create one.",
                "Do not guess where that action lives in the UI. Let the user navigate the Safe app themselves if needed.",
            ],
            "why_it_matters": [
                "This lets an AI agent work with Safe data without exposing a reusable plaintext API secret.",
                "The same Safe can grant different keys different Spaces and permissions.",
                "An Agent Key can be limited to view-only or limited edit access, but not full Safe control.",
            ],
            "docs": [
                "https://docs.unolock.com/index.html",
                "https://docs.unolock.com/features/agentic-safe-access.html",
                "https://docs.unolock.com/howto/connecting-an-ai-agent.html",
            ],
        }

    @server.resource(
        "unolock://usage/security-model",
        name="UnoLock Agent Security Model",
        description="Agent-safe explanation of why UnoLock asks for Agent Key URLs, PINs, and hardware/platform-backed keys.",
        mime_type="application/json",
    )
    def security_model_resource() -> dict[str, Any]:
        return {
            "summary": (
                "UnoLock tries to keep agent access as close as possible to a device-bound, least-privilege, "
                "zero-knowledge model."
            ),
            "why_the_agent_asks_for_an_agent_key_url": [
                "The Agent Key URL is a one-time URL created by the Safe admin for that Agent Key.",
                "It lets the MCP set up that Agent Key on this device.",
                "It is not the ongoing access credential and should be treated as one-time setup input only.",
                "After registration, the MCP uses the registered local agent credential and short-lived authenticated sessions."
            ],
            "why_the_agent_may_ask_for_a_pin": [
                "Some Agent Keys require a PIN on authentication.",
                "The MCP keeps the PIN only in process memory and sends a challenge-bound hash instead of the raw PIN.",
                "After restart, the agent may need the PIN again to re-authenticate."
            ],
            "why_host_assurance_matters": [
                "UnoLock prefers TPM, vTPM, Secure Enclave, or another platform-backed non-exportable key store.",
                "Those hosts make it harder to export the agent credential or copy it to another machine.",
                "If the MCP must fall back to software mode, it reports the reduced assurance clearly so the user can decide whether to continue."
            ],
            "least_privilege_rules": [
                "Agent Keys can be restricted to selected Spaces.",
                "Read-only keys cannot write.",
                "Locked records cannot be modified.",
                "An Agent Key can be limited to view-only or limited edit access, but not full Safe control."
            ],
        }

    @server.resource(
        "unolock://usage/updates",
        name="UnoLock Agent Updates",
        description="Agent-safe guidance for how UnoLock Agent updates should be checked and applied.",
        mime_type="application/json",
    )
    def updates_resource() -> dict[str, Any]:
        return {
            "summary": (
                "UnoLock Agent should normally be updated between tasks, not by replacing itself mid-session."
            ),
            "preferred_path": [
                "Prefer an installed `unolock-agent` executable or a GitHub Release binary.",
                "Use `unolock_get_update_status` or `unolock-agent check-update` to see whether a newer release exists.",
                "If an update is available, restart UnoLock between tasks so the global install or binary can be replaced cleanly.",
            ],
            "rules": [
                "Do not attempt in-place self-replacement while an active UnoLock session or write flow is in progress.",
                "Avoid updating in the middle of a sensitive workflow that depends on an in-memory PIN.",
                "Prefer explicit user awareness before applying an update.",
            ],
            "channels": {
                "npm-install": "Run `npm install -g @techsologic/unolock-agent@latest`, then restart UnoLock.",
                "release-binary": "Download the latest GitHub Release binary, replace the executable, then restart UnoLock.",
                "python-package": "Upgrade the Python package in the environment that launches UnoLock and restart it.",
            },
            "release_url": "https://github.com/TechSologic/unolock-agent/releases",
        }

    @server.prompt(
        name="unolock_request_connection_url",
        title="Request UnoLock Connection URL",
        description="Prompt content telling the agent how to ask the user for a UnoLock Agent Key URL.",
    )
    def request_connection_url_prompt() -> list[dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": (
                    "If UnoLock registration is not configured, ask the user to provide the UnoLock "
                    "Agent Key URL for AI/agent registration and the UnoLock agent PIN at the same time. "
                    "The Agent Key URL is one-time-use and is only for setting up the "
                    "Agent Key on this device. Once registration succeeds, ongoing access uses the registered "
                    "agent key and normal authentication, not the URL itself. Once "
                    "the user gives you those values, call "
                    "unolock_register."
                ),
            }
        ]

    @server.prompt(
        name="unolock_agent_happy_path",
        title="UnoLock Happy Path",
        description="Prompt content telling an agent how to use the primary UnoLock MCP workflow.",
    )
    def agent_happy_path_prompt() -> list[dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": (
                    "Use UnoLock in this order: call the normal data tools directly. If registration is needed, ask the "
                    "user for the one-time UnoLock Agent Key URL and PIN together, then call "
                    "unolock_register. Treat the Agent Key URL only as the one-time input used to set up "
                    "the Agent Key on this device, not as the ongoing access credential. After registration, prefer "
                    "unolock_list_spaces, unolock_list_records, unolock_list_files, and unolock_get_record. The MCP can "
                    "authenticate automatically and "
                    "resume the original request after the PIN is supplied. Before writing, read the target record and use its writable, "
                    "allowed_operations, record_ref, and version fields. Avoid low-level flow/api tools unless the "
                    "primary workflow cannot complete the task."
                ),
            }
        ]

    @server.prompt(
        name="unolock_explain_to_user",
        title="Explain UnoLock To The User",
        description="Prompt content telling an agent how to explain UnoLock, Agent Keys, PINs, and assurance tradeoffs to a user.",
    )
    def explain_to_user_prompt() -> list[dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": (
                    "When a user asks why UnoLock Agent needs an Agent Key URL, PIN, or a stronger host key store, "
                    "explain it plainly: UnoLock uses an Agent Key instead of a reusable API key. The one-time "
                    "Agent Key URL is used once to set up that Agent Key on this device. After registration, the agent "
                    "uses the registered local credential and normal authentication. The PIN may be required to "
                    "re-authenticate the agent. TPM, "
                    "Secure Enclave, or other platform-backed key storage is preferred because it helps keep the agent's "
                    "credential device-bound and harder to export. If you need authoritative wording, read the "
                    "unolock://usage/about and unolock://usage/security-model resources and summarize them for the user."
                ),
            }
        ]

    if _advanced_tools_enabled():
        @server.tool(
            name="unolock_probe_local_server",
            description="Advanced/debug: run the UnoLock local /start probe and return the next callback after PQ negotiation.",
        )
        def probe_local_server(
            base_url: str = "http://127.0.0.1:3000",
            flow: str = "access",
            app_version: str = "",
            signing_public_key: str = "",
        ) -> dict[str, Any]:
            if not app_version or not signing_public_key:
                resolved = resolve_unolock_config(base_url=base_url)
                app_version = app_version or resolved.app_version or ""
                signing_public_key = signing_public_key or resolved.signing_public_key_b64 or ""
            probe = LocalServerProbe(
                base_url=base_url,
                app_version=app_version,
                signing_public_key_b64=signing_public_key,
            )
            return probe.run(flow=flow)

    @server.tool(
        name="unolock_set_agent_pin",
        description=(
            "Store an optional UnoLock agent PIN in MCP process memory only. The MCP will hash it with the "
            "server challenge when a GetPin callback is encountered. Pass the PIN as a string using only "
            "characters 0-9 and a-f."
        ),
    )
    def set_agent_pin(pin: str) -> dict[str, Any]:
        try:
            status = agent_auth.set_agent_pin(pin)
        except ValueError as exc:
            return _tool_error_response(exc)
        resumed = _resume_pending_operation("unolock_set_agent_pin")
        if resumed is None:
            return status
        return {
            **status,
            "resumed_operation": resumed,
        }

    @server.tool(
        name="unolock_register",
        description=(
            "Register the one-time UnoLock Agent Key URL and the agent PIN together on this device. "
            "This is the preferred cold-start setup tool. Pass the PIN as a string using only characters 0-9 and a-f."
        ),
    )
    def register(connection_url: str, pin: str) -> dict[str, Any]:
        status = agent_auth.submit_connection_url(connection_url)
        if status.get("ok") is False or status.get("blocked"):
            return _strip_session_ids(status)
        try:
            pin_status = agent_auth.set_agent_pin(pin)
        except ValueError as exc:
            return _tool_error_response(exc)
        try:
            ensure_flow_client()
        except ValueError as exc:
            return {
                **_tool_error_response(exc),
                "pin": pin_status,
            }
        registration_status = agent_auth.start_registration_from_stored_url()
        registration_status = _strip_session_ids(registration_status)
        if registration_status.get("ok") is False or registration_status.get("blocked"):
            return {
                **registration_status,
                "pin": pin_status,
            }
        return {
            **registration_status,
            "pin": pin_status,
        }

    @server.tool(
        name="unolock_get_current_space",
        description=(
            "Return the currently selected UnoLock space used as the default for normal record and file operations. "
            "If no current space is selected yet, the MCP will pick the first accessible space automatically. "
            "If this Agent Key has access to no Spaces, the MCP returns a clear error."
        ),
    )
    def get_current_space() -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            _decorate_spaces_payload(readonly_records.list_spaces(resolved_session_id))
            return _current_space_payload()

        return _run_with_auto_session(
            "unolock_get_current_space",
            {},
            None,
            operation,
        )

    @server.tool(
        name="unolock_set_current_space",
        description=(
            "Select the current UnoLock space for subsequent list/create/upload operations. "
            "Normal record and file tools always use this current space and report the space_id they used."
        ),
    )
    def set_current_space(space_id: int = 0) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            if space_id <= 0:
                raise ValueError("invalid_input: space_id must be a positive integer.")
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            payload = readonly_records.list_spaces(resolved_session_id)
            selected_space = None
            spaces = payload.get("spaces")
            if isinstance(spaces, list):
                for space in spaces:
                    if isinstance(space, dict) and space.get("space_id") == space_id:
                        selected_space = dict(space)
                        break
            if selected_space is None:
                raise ValueError("record_not_found: The requested space_id is not available to this agent.")
            registration_store.set_current_space(space_id)
            selected_space["current"] = True
            return {
                "ok": True,
                "current_space_id": space_id,
                "space": selected_space,
            }

        return _run_with_auto_session(
            "unolock_set_current_space",
            {"space_id": space_id},
            None,
            operation,
        )

    if _advanced_tools_enabled():
        @server.tool(
            name="unolock_get_update_status",
            description=(
                "Support/debug: check the installed UnoLock Agent version against the latest GitHub Release "
                "and return update guidance."
            ),
        )
        def get_update_status_tool() -> dict[str, Any]:
            try:
                return get_update_status()
            except Exception as exc:
                return _tool_error_response(exc)

        @server.tool(
            name="unolock_clear_agent_pin",
            description="Support/debug: clear the in-memory UnoLock agent PIN from the running MCP process.",
        )
        def clear_agent_pin() -> dict[str, Any]:
            return agent_auth.clear_agent_pin()

        @server.tool(
            name="unolock_get_tpm_diagnostics",
            description=(
                "Support/debug: diagnose the active UnoLock TPM/vTPM provider and the host TPM/vTPM signals."
            ),
        )
        def get_tpm_diagnostics() -> dict[str, Any]:
            return agent_auth.tpm_diagnostics()

        @server.tool(
            name="unolock_clear_connection_url",
            description="Support/debug: clear the locally stored UnoLock Agent Key URL.",
        )
        def clear_connection_url() -> dict[str, Any]:
            return registration_store.clear_connection_url().summary()

        @server.tool(
            name="unolock_clear_current_space",
            description="Support/debug: clear the current UnoLock space selection.",
        )
        def clear_current_space() -> dict[str, Any]:
            registration_store.set_current_space(None)
            return _current_space_payload()

        @server.tool(
            name="unolock_disconnect_agent",
            description=(
                "Support/debug: permanently disconnect this local MCP host from its current UnoLock agent registration."
            ),
        )
        def disconnect_agent() -> dict[str, Any]:
            return agent_auth.disconnect()

        @server.tool(
            name="unolock_start_flow",
            description=(
                "Advanced/debug: start a UnoLock auth flow, automatically complete PQ negotiation, and return a "
                "summary of the active flow plus the next callback that requires client handling."
            ),
        )
        def start_flow(flow: str = "access", args: str | None = None) -> dict[str, Any]:
            flow_client = ensure_flow_client()
            session = flow_client.start(flow=flow, args=args)
            session_store.put(session)
            return session.summary()

        @server.tool(
            name="unolock_continue_flow",
            description=(
                "Advanced/debug: reply to the current UnoLock auth-flow callback. "
                "If callback_type is omitted, the current callback type is reused."
            ),
        )
        def continue_flow(
            callback_type: str | None = None,
            request: Any | None = None,
            result: Any | None = None,
            reason: str | None = None,
            message: list[str] | None = None,
        ) -> dict[str, Any]:
            session = session_store.get()
            flow_client = ensure_flow_client()
            updated = flow_client.continue_flow(
                session,
                callback_type=callback_type,
                request=request,
                result=result,
                reason=reason,
                message=message,
            )
            session_store.put(updated)
            if updated.authorized and updated.flow == "agentRegister":
                registration_store.mark_registered()
            return updated.summary()

        @server.tool(
            name="unolock_get_session",
            description="Advanced/debug: inspect the current in-memory UnoLock auth-flow state.",
        )
        def get_session() -> dict[str, Any]:
            return session_store.get().summary()

        @server.tool(
            name="unolock_list_sessions",
            description="Advanced/debug: list the current in-memory UnoLock auth-flow sessions.",
        )
        def list_sessions() -> list[dict[str, Any]]:
            return session_store.list()

        @server.tool(
            name="unolock_delete_session",
            description="Advanced/debug: clear the current in-memory UnoLock auth-flow state.",
        )
        def delete_session() -> dict[str, Any]:
            session_store.delete()
            return {"deleted": "active"}

        @server.tool(
            name="unolock_call_api",
            description="Advanced/debug: call a generic authenticated UnoLock /api action for the current active auth state.",
        )
        def call_api(
            action: str,
            request: Any | None = None,
            result: Any | None = None,
            reason: str | None = None,
            message: list[str] | None = None,
        ) -> dict[str, Any]:
            api_client = UnoLockApiClient(ensure_flow_client(), session_store)
            return api_client.call_action(
                action=action,
                request=request,
                result=result,
                reason=reason,
                message=message,
            )

        @server.tool(
            name="unolock_get_spaces",
            description="Advanced/debug: call UnoLock GetSpaces for the current authenticated state.",
        )
        def get_spaces() -> dict[str, Any]:
            api_client = UnoLockApiClient(ensure_flow_client(), session_store)
            return api_client.get_spaces()

        @server.tool(
            name="unolock_get_archives",
            description="Advanced/debug: call UnoLock GetArchives for the current authenticated state.",
        )
        def get_archives() -> dict[str, Any]:
            api_client = UnoLockApiClient(ensure_flow_client(), session_store)
            return api_client.get_archives()

    @server.tool(
        name="unolock_list_spaces",
        description=(
            "List UnoLock spaces with record counts, Cloud file counts, and write capability metadata. "
            "The MCP will authenticate automatically when needed and only stop for one concrete missing input such as the PIN. "
            "Use writable and allowed_operations to decide whether note/checklist or file actions are allowed. "
            "If this Agent Key has access to no Spaces, the MCP returns a clear error."
        ),
    )
    def list_spaces() -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return _decorate_spaces_payload(readonly_records.list_spaces(resolved_session_id))

        return _run_with_auto_session(
            "unolock_list_spaces",
            {},
            None,
            operation,
        )

    @server.tool(
        name="unolock_list_records",
        description=(
            "List read-only UnoLock notes and checklists. "
            "The MCP will authenticate automatically when needed and only stop for one concrete missing input such as the PIN. "
            "Records are projected into agent-friendly plain text and checklist items, and include version, "
            "writable, locked, and allowed_operations metadata. The response includes the current space_id used."
        ),
    )
    def list_records(
        kind: str = "all",
        pinned: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            effective_space_id = _resolve_space_id(
                None,
                required=False,
                available_spaces=lambda: readonly_records.list_spaces(resolved_session_id),
            )
            return _attach_space_id(
                readonly_records.list_records(
                    resolved_session_id,
                    kind=kind,
                    space_id=effective_space_id,
                    pinned=pinned,
                    label=label,
                ),
                effective_space_id,
            )

        return _run_with_auto_session(
            "unolock_list_records",
            {
                "kind": kind,
                "pinned": pinned,
                "label": label,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_list_notes",
        description=(
            "List read-only UnoLock notes with version and writable metadata. "
            "The MCP will authenticate automatically when needed. The response includes the current space_id used."
        ),
    )
    def list_notes(
        pinned: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            effective_space_id = _resolve_space_id(
                None,
                required=False,
                available_spaces=lambda: readonly_records.list_spaces(resolved_session_id),
            )
            return _attach_space_id(
                readonly_records.list_records(
                    resolved_session_id,
                    kind="note",
                    space_id=effective_space_id,
                    pinned=pinned,
                    label=label,
                ),
                effective_space_id,
            )

        return _run_with_auto_session(
            "unolock_list_notes",
            {
                "pinned": pinned,
                "label": label,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_list_checklists",
        description=(
            "List read-only UnoLock checklists with version and writable metadata. "
            "The MCP will authenticate automatically when needed. The response includes the current space_id used."
        ),
    )
    def list_checklists(
        pinned: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            effective_space_id = _resolve_space_id(
                None,
                required=False,
                available_spaces=lambda: readonly_records.list_spaces(resolved_session_id),
            )
            return _attach_space_id(
                readonly_records.list_records(
                    resolved_session_id,
                    kind="checklist",
                    space_id=effective_space_id,
                    pinned=pinned,
                    label=label,
                ),
                effective_space_id,
            )

        return _run_with_auto_session(
            "unolock_list_checklists",
            {
                "pinned": pinned,
                "label": label,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_list_files",
        description=(
            "List UnoLock Cloud files. "
            "The MCP will authenticate automatically when needed and only stop for one concrete missing input such as the PIN. "
            "Only Cloud archives are exposed by the MCP; Local and Msg archives are intentionally excluded. "
            "The response includes the current space_id used."
        ),
    )
    def list_files() -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            effective_space_id = _resolve_space_id(
                None,
                required=False,
                available_spaces=lambda: readonly_records.list_spaces(resolved_session_id),
            )
            readonly_files = UnoLockReadonlyFilesClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return _attach_space_id(
                readonly_files.list_files(resolved_session_id, space_id=effective_space_id),
                effective_space_id,
            )

        return _run_with_auto_session(
            "unolock_list_files",
            {},
            None,
            operation,
        )

    @server.tool(
        name="unolock_sync_list",
        description=(
            "List configured UnoLock sync jobs across all accessible Spaces by reading reserved sync-config notes. "
            "The MCP will authenticate automatically when needed."
        ),
    )
    def sync_list() -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            return create_sync_service().list_syncs(
                resolved_session_id,
                key_id=registration_store.load().key_id,
            )

        return _run_with_auto_session(
            "unolock_sync_list",
            {},
            None,
            operation,
        )

    @server.tool(
        name="unolock_sync_status",
        description=(
            "Show current UnoLock sync status across all configured sync jobs. "
            "This includes runtime status derived from reserved sync-config notes and local sync runtime state."
        ),
    )
    def sync_status() -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            return create_sync_service().sync_status(
                resolved_session_id,
                key_id=registration_store.load().key_id,
                monitoring=True,
            )

        return _run_with_auto_session(
            "unolock_sync_status",
            {},
            None,
            operation,
        )

    @server.tool(
        name="unolock_sync_add",
        description=(
            "Add one local file to UnoLock sync by writing a reserved sync-config note in the target Space. "
            "This creates configuration only; background upload behavior will be handled by the daemon."
        ),
    )
    def sync_add(
        local_path: str = "",
        space_id: int = 0,
        title: str | None = None,
        mime_type: str | None = None,
        archive_id: str | None = None,
        enabled: bool = True,
        poll_seconds: int = DEFAULT_SYNC_POLL_SECONDS,
        debounce_seconds: int = DEFAULT_SYNC_DEBOUNCE_SECONDS,
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            effective_space_id = _resolve_space_id(
                space_id if space_id > 0 else None,
                required=True,
                available_spaces=lambda: readonly_records.list_spaces(resolved_session_id),
            )
            payload = create_sync_service().add_sync(
                resolved_session_id,
                key_id=registration_store.load().key_id,
                space_id=effective_space_id,
                local_path=local_path,
                title=title,
                mime_type=mime_type,
                archive_id=archive_id,
                enabled=enabled,
                poll_seconds=poll_seconds,
                debounce_seconds=debounce_seconds,
            )
            return _attach_space_id(payload, effective_space_id)

        return _run_with_auto_session(
            "unolock_sync_add",
            {
                "local_path": local_path,
                "space_id": space_id,
                "title": title,
                "mime_type": mime_type,
                "archive_id": archive_id,
                "enabled": enabled,
                "poll_seconds": poll_seconds,
                "debounce_seconds": debounce_seconds,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_sync_run",
        description=(
            "Run UnoLock sync immediately for one sync job or for all configured sync jobs. "
            "This executes the current push-sync path without waiting for a background monitor."
        ),
    )
    def sync_run(sync_id: str = "", run_all: bool = False) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            return create_sync_service().run_syncs(
                resolved_session_id,
                key_id=registration_store.load().key_id,
                sync_id=sync_id,
                run_all=run_all,
            )

        return _run_with_auto_session(
            "unolock_sync_run",
            {
                "sync_id": sync_id,
                "run_all": run_all,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_sync_enable",
        description=(
            "Enable one configured UnoLock sync job. "
            "This preserves the reserved sync configuration and remote file binding."
        ),
    )
    def sync_enable(sync_id: str = "") -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            return create_sync_service().enable_sync(
                resolved_session_id,
                key_id=registration_store.load().key_id,
                sync_id=sync_id,
            )

        return _run_with_auto_session(
            "unolock_sync_enable",
            {
                "sync_id": sync_id,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_sync_disable",
        description=(
            "Disable one configured UnoLock sync job. "
            "This pauses background sync without removing the reserved sync configuration."
        ),
    )
    def sync_disable(sync_id: str = "") -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            return create_sync_service().disable_sync(
                resolved_session_id,
                key_id=registration_store.load().key_id,
                sync_id=sync_id,
            )

        return _run_with_auto_session(
            "unolock_sync_disable",
            {
                "sync_id": sync_id,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_sync_remove",
        description=(
            "Remove one configured UnoLock sync job. "
            "This accepts either the sync id or the watched local path. "
            "By default this removes only the sync configuration, not the remote Cloud file."
        ),
    )
    def sync_remove(sync_id: str = "", delete_remote: bool = False) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            return create_sync_service().remove_sync(
                resolved_session_id,
                key_id=registration_store.load().key_id,
                sync_id=sync_id,
                delete_remote=delete_remote,
            )

        return _run_with_auto_session(
            "unolock_sync_remove",
            {
                "sync_id": sync_id,
                "delete_remote": delete_remote,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_sync_restore",
        description=(
            "Restore one synced Cloud file back to the local filesystem. "
            "This accepts either the sync id or the watched local path. "
            "If output_path is omitted, the watched local path is used."
        ),
    )
    def sync_restore(sync_id: str = "", output_path: str | None = None, overwrite: bool = False) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            return create_sync_service().restore_sync(
                resolved_session_id,
                key_id=registration_store.load().key_id,
                sync_id=sync_id,
                output_path=output_path,
                overwrite=overwrite,
            )

        return _run_with_auto_session(
            "unolock_sync_restore",
            {
                "sync_id": sync_id,
                "output_path": output_path,
                "overwrite": overwrite,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_get_file",
        description=(
            "Get metadata for one UnoLock Cloud file by archive_id. "
            "Use unolock_list_files first to discover archive_id values."
        ),
    )
    def get_file(archive_id: str = "") -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            readonly_files = UnoLockReadonlyFilesClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return {
                "ok": True,
                "file": readonly_files.get_file(resolved_session_id, archive_id),
            }

        return _run_with_auto_session(
            "unolock_get_file",
            {"archive_id": archive_id},
            None,
            operation,
        )

    @server.tool(
        name="unolock_download_file",
        description=(
            "Download one UnoLock Cloud file to a local filesystem path. "
            "Only Cloud files are supported; Local and Msg archives are excluded."
        ),
    )
    def download_file(
        archive_id: str = "",
        output_path: str = "",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            readonly_files = UnoLockReadonlyFilesClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return readonly_files.download_file(
                resolved_session_id,
                archive_id=archive_id,
                output_path=output_path,
                overwrite=overwrite,
            )

        return _run_with_auto_session(
            "unolock_download_file",
            {
                "archive_id": archive_id,
                "output_path": output_path,
                "overwrite": overwrite,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_upload_file",
        description=(
            "Upload a local filesystem file into a UnoLock Cloud archive in the current space. "
            "Only Cloud files are supported; Local and Msg archives are excluded. "
            "The response includes the space_id used."
        ),
    )
    def upload_file(
        local_path: str = "",
        title: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            effective_space_id = _resolve_space_id(
                None,
                required=True,
                available_spaces=lambda: readonly_records.list_spaces(resolved_session_id),
            )
            writable_files = UnoLockWritableFilesClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return _attach_space_id(
                writable_files.upload_file(
                    resolved_session_id,
                    space_id=effective_space_id,
                    local_path=local_path,
                    name=title,
                    mime_type=mime_type,
                ),
                effective_space_id,
            )

        return _run_with_auto_session(
            "unolock_upload_file",
            {
                "local_path": local_path,
                "title": title,
                "mime_type": mime_type,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_rename_file",
        description=(
            "Rename one UnoLock Cloud file by archive_id. "
            "Use unolock_get_file first to confirm writable=true and the current file metadata."
        ),
    )
    def rename_file(archive_id: str = "", name: str = "") -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            writable_files = UnoLockWritableFilesClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return writable_files.rename_file(
                resolved_session_id,
                archive_id=archive_id,
                name=name,
            )

        return _run_with_auto_session(
            "unolock_rename_file",
            {"archive_id": archive_id, "name": name},
            None,
            operation,
        )

    @server.tool(
        name="unolock_replace_file",
        description=(
            "Replace the content of one existing UnoLock Cloud file from a local filesystem path. "
            "Use unolock_get_file first to confirm writable=true and the target archive_id."
        ),
    )
    def replace_file(
        archive_id: str = "",
        local_path: str = "",
        title: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            writable_files = UnoLockWritableFilesClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return writable_files.replace_file(
                resolved_session_id,
                archive_id=archive_id,
                local_path=local_path,
                name=title,
                mime_type=mime_type,
            )

        return _run_with_auto_session(
            "unolock_replace_file",
            {
                "archive_id": archive_id,
                "local_path": local_path,
                "title": title,
                "mime_type": mime_type,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_delete_file",
        description=(
            "Delete one UnoLock Cloud file by archive_id. "
            "Use unolock_get_file first to confirm writable=true and the target archive_id."
        ),
    )
    def delete_file(archive_id: str = "") -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            writable_files = UnoLockWritableFilesClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return writable_files.delete_file(
                resolved_session_id,
                archive_id=archive_id,
            )

        return _run_with_auto_session(
            "unolock_delete_file",
            {"archive_id": archive_id},
            None,
            operation,
        )

    @server.tool(
        name="unolock_get_record",
        description=(
            "Get one read-only UnoLock note or checklist by record_ref. "
            "The MCP will authenticate automatically when needed. "
            "Use unolock_list_records first to discover record_ref values and current version metadata before writing."
        ),
    )
    def get_record(record_ref: str = "") -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            return {
                "ok": True,
                "record": _get_record_projection(resolved_session_id, record_ref),
            }

        return _run_with_auto_session(
            "unolock_get_record",
            {"record_ref": record_ref},
            None,
            operation,
        )

    @server.tool(
        name="unolock_create_note",
        description=(
            "Create a new UnoLock note from raw text in an existing writable Records archive. "
            "The MCP will authenticate automatically when needed and resume after the PIN is supplied. "
            "Read the target space first and check writable/allowed_operations before creating notes. "
            "The returned record metadata includes the new record version, lock state, and space_id used."
        ),
    )
    def create_note(title: str = "", text: str = "") -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            effective_space_id = _resolve_space_id(
                None,
                required=True,
                available_spaces=lambda: readonly_records.list_spaces(resolved_session_id),
            )
            writable_records = UnoLockWritableRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return _attach_space_id(
                writable_records.create_note(
                    resolved_session_id,
                    space_id=effective_space_id,
                    title=title,
                    text=text,
                ),
                effective_space_id,
            )

        return _run_with_auto_session(
            "unolock_create_note",
            {"title": title, "text": text},
            None,
            operation,
        )

    @server.tool(
        name="unolock_create_checklist",
        description=(
            "Create a new UnoLock checklist in the current writable Records archive. "
            "Each item must be an object like {text: string, checked?: boolean}. "
            "Use checked, done, or state='checked' to create initially checked items. "
            "Read the target space first and check writable/allowed_operations before creating checklists. "
            "The response includes the space_id used."
        ),
    )
    def create_checklist(
        title: str = "",
        items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            effective_space_id = _resolve_space_id(
                None,
                required=True,
                available_spaces=lambda: readonly_records.list_spaces(resolved_session_id),
            )
            writable_records = UnoLockWritableRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return _attach_space_id(
                writable_records.create_checklist(
                    resolved_session_id,
                    space_id=effective_space_id,
                    title=title,
                    items=[] if items is None else items,
                ),
                effective_space_id,
            )

        return _run_with_auto_session(
            "unolock_create_checklist",
            {"title": title, "items": items},
            None,
            operation,
        )

    @server.tool(
        name="unolock_update_note",
        description=(
            "Update an existing UnoLock note from raw text. "
            "Read the note first, then use the returned record_ref, version, and allowed_operations metadata. "
            "If title or text is omitted, the MCP keeps the current value for that field. "
            "If the note is locked, read-only, or changed since the last read, the MCP will reject the update."
        ),
    )
    def update_note(
        record_ref: str = "",
        expected_version: int = 0,
        title: str | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            writable_records = UnoLockWritableRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            if title is None and text is None:
                raise ValueError("invalid_input: update_note requires title and/or text.")
            resolved_version = _resolve_record_version(resolved_session_id, record_ref, expected_version)
            resolved_title, resolved_text = _resolve_note_update_fields(
                resolved_session_id,
                record_ref,
                title=title,
                text=text,
            )
            return writable_records.update_note(
                resolved_session_id,
                record_ref=record_ref,
                expected_version=resolved_version,
                title=resolved_title,
                text=resolved_text,
            )

        return _run_with_auto_session(
            "unolock_update_note",
            {
                "record_ref": record_ref,
                "expected_version": expected_version,
                "title": title,
                "text": text,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_append_note",
        description=(
            "Append new line(s) of raw text to the end of an existing UnoLock note without resending the entire note body. "
            "Read the note first, then use the returned record_ref, version, and allowed_operations metadata. "
            "The MCP still enforces note locks and version conflicts before appending."
        ),
    )
    def append_note(
        record_ref: str = "",
        expected_version: int = 0,
        append_text: str = "",
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            writable_records = UnoLockWritableRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            resolved_version = _resolve_record_version(resolved_session_id, record_ref, expected_version)
            return writable_records.append_note(
                resolved_session_id,
                record_ref=record_ref,
                expected_version=resolved_version,
                append_text=append_text,
            )

        return _run_with_auto_session(
            "unolock_append_note",
            {
                "record_ref": record_ref,
                "expected_version": expected_version,
                "append_text": append_text,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_rename_record",
        description=(
            "Rename an existing UnoLock note or checklist by changing its title only. "
            "Read the record first, then use the returned record_ref, version, and allowed_operations metadata. "
            "If the record is locked, read-only, or changed since the last read, the MCP will reject the rename."
        ),
    )
    def rename_record(
        record_ref: str = "",
        expected_version: int = 0,
        title: str = "",
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            writable_records = UnoLockWritableRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            resolved_version = _resolve_record_version(resolved_session_id, record_ref, expected_version)
            return writable_records.rename_record(
                resolved_session_id,
                record_ref=record_ref,
                expected_version=resolved_version,
                title=title,
            )

        return _run_with_auto_session(
            "unolock_rename_record",
            {
                "record_ref": record_ref,
                "expected_version": expected_version,
                "title": title,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_set_checklist_item_done",
        description=(
            "Set one checklist item's checked state. "
            "Read the checklist first, then use the returned record_ref, version, and allowed_operations metadata. "
            "If the checklist is locked, read-only, or changed since the last read, the MCP will reject the update."
        ),
    )
    def set_checklist_item_done(
        record_ref: str = "",
        expected_version: int = 0,
        item_id: int = 0,
        done: bool = False,
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            writable_records = UnoLockWritableRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            resolved_version = _resolve_record_version(resolved_session_id, record_ref, expected_version)
            return writable_records.set_checklist_item_done(
                resolved_session_id,
                record_ref=record_ref,
                expected_version=resolved_version,
                item_id=item_id,
                done=done,
            )

        return _run_with_auto_session(
            "unolock_set_checklist_item_done",
            {
                "record_ref": record_ref,
                "expected_version": expected_version,
                "item_id": item_id,
                "done": done,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_add_checklist_item",
        description=(
            "Add a new unchecked item to an existing checklist. "
            "Read the checklist first, then use the returned record_ref, version, and allowed_operations metadata. "
            "If the checklist is locked, read-only, or changed since the last read, the MCP will reject the update."
        ),
    )
    def add_checklist_item(
        record_ref: str = "",
        expected_version: int = 0,
        text: str = "",
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            writable_records = UnoLockWritableRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            resolved_version = _resolve_record_version(resolved_session_id, record_ref, expected_version)
            return writable_records.add_checklist_item(
                resolved_session_id,
                record_ref=record_ref,
                expected_version=resolved_version,
                text=text,
            )

        return _run_with_auto_session(
            "unolock_add_checklist_item",
            {
                "record_ref": record_ref,
                "expected_version": expected_version,
                "text": text,
            },
            None,
            operation,
        )

    @server.tool(
        name="unolock_remove_checklist_item",
        description=(
            "Remove one checklist item by item_id. "
            "Read the checklist first, then use the returned record_ref, version, and allowed_operations metadata. "
            "If the checklist is locked, read-only, or changed since the last read, the MCP will reject the update."
        ),
    )
    def remove_checklist_item(
        record_ref: str = "",
        expected_version: int = 0,
        item_id: int = 0,
    ) -> dict[str, Any]:
        def operation(resolved_session_id: str) -> dict[str, Any]:
            writable_records = UnoLockWritableRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            resolved_version = _resolve_record_version(resolved_session_id, record_ref, expected_version)
            return writable_records.remove_checklist_item(
                resolved_session_id,
                record_ref=record_ref,
                expected_version=resolved_version,
                item_id=item_id,
            )

        return _run_with_auto_session(
            "unolock_remove_checklist_item",
            {
                "record_ref": record_ref,
                "expected_version": expected_version,
                "item_id": item_id,
            },
            None,
            operation,
        )

    return server
