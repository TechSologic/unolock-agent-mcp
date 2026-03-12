from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from unolock_mcp.api.client import UnoLockApiClient
from unolock_mcp.api.records import UnoLockReadonlyRecordsClient, UnoLockWritableRecordsClient
from unolock_mcp.auth.agent_auth import AgentAuthClient
from unolock_mcp.auth.flow_client import UnoLockFlowClient
from unolock_mcp.auth.local_probe import LocalServerProbe
from unolock_mcp.auth.registration_store import RegistrationStore
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.config import resolve_unolock_config
from unolock_mcp.domain.models import UnoLockConfig


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
    guidance = "Agent registration is configured. Authenticate and start using read-only tools."
    pending_session = None
    session_id = registration.get("session_id")
    if session_id:
        try:
            pending_session = session_store.get(str(session_id)).summary()
        except KeyError:
            pending_session = None

    if pending_session and pending_session.get("current_callback_type") in {"SUCCESS", "FAILED"}:
        pending_session = None

    if provider_mismatch:
        next_action = "resolve_tpm_provider_mismatch"
        guidance = str(provider_mismatch.get("message"))
    elif security_warning and not runtime.get("reduced_assurance_acknowledged"):
        next_action = "acknowledge_reduced_assurance"
        guidance = (
            "This host is using the lower-assurance software provider. Ask the user whether they want to continue "
            "in reduced-assurance mode, then call unolock_acknowledge_reduced_assurance before registering or authenticating."
        )
    elif pending_session is not None:
        callback_type = pending_session.get("current_callback_type")
        if callback_type == "GetPin" and not runtime.get("has_agent_pin"):
            next_action = "ask_for_agent_pin_then_continue"
            guidance = (
                "A UnoLock flow is waiting at GetPin. Ask the user for the agent PIN, call "
                "unolock_set_agent_pin, then call unolock_bootstrap_agent or unolock_continue_agent_session."
            )
        else:
            next_action = "continue_pending_session"
            guidance = (
                "A UnoLock flow is already in progress. Continue it with unolock_bootstrap_agent or "
                "unolock_continue_agent_session instead of starting over."
            )
    elif registration.get("registered"):
        if not runtime.get("has_agent_pin"):
            next_action = "authenticate_or_set_pin"
            guidance = (
                "Registration is configured. If the Safe requires an agent PIN, ask the user for it and "
                "call unolock_set_agent_pin before authenticating."
            )
        else:
            next_action = "authenticate_agent"
            guidance = "Agent registration is configured. Authenticate and start using read-only tools."
    elif not registration.get("has_connection_url"):
        next_action = "ask_for_connection_url"
        guidance = (
            "Ask the user for the one-time-use UnoLock agent key connection URL and, if they configured one, the "
            "UnoLock agent PIN at the same time. The connection URL is for enrollment only and should not be reused "
            "or treated like a persistent secret. Then call unolock_submit_agent_bootstrap or submit the connection "
            "URL and PIN separately."
        )
    else:
        next_action = "start_registration"
        guidance = (
            "A one-time-use UnoLock agent key connection URL is stored. Call "
            "unolock_start_registration_from_connection_url to register this MCP."
        )

    if security_warning:
        guidance = f"{guidance} Warning: {security_warning.get('message')}"

    primary_tools = [
        "unolock_get_registration_status",
        "unolock_submit_agent_bootstrap",
        "unolock_bootstrap_agent",
        "unolock_list_spaces",
        "unolock_list_records",
        "unolock_get_record",
    ]
    write_tools = [
        "unolock_create_note",
        "unolock_update_note",
        "unolock_rename_record",
        "unolock_create_checklist",
        "unolock_set_checklist_item_done",
        "unolock_add_checklist_item",
        "unolock_remove_checklist_item",
    ]
    advanced_tools = [
        "unolock_probe_local_server",
        "unolock_start_flow",
        "unolock_continue_flow",
        "unolock_get_session",
        "unolock_list_sessions",
        "unolock_delete_session",
        "unolock_call_api",
        "unolock_get_spaces",
        "unolock_get_archives",
    ]

    return {
        **registration,
        **runtime,
        "tpm_diagnostics": tpm,
        "security_warning": security_warning,
        "pending_session": pending_session,
        "recommended_next_action": next_action,
        "guidance": guidance,
        "primary_tools": primary_tools,
        "write_tools": write_tools,
        "advanced_tools": advanced_tools,
        "workflow_summary": [
            "Check registration status first.",
            "If needed, ask the user for the one-time-use agent key connection URL and optional PIN together.",
            "Authenticate or finish registration before using data tools.",
            "Read a space or record before writing so you have current version and allowed_operations metadata.",
            "If a write reports conflict, reread the target record and retry with the latest version.",
        ],
    }


def create_mcp_server() -> FastMCP:
    session_store = SessionStore()
    registration_store = RegistrationStore()
    agent_auth = AgentAuthClient(None, session_store, registration_store)

    def resolve_runtime_config() -> UnoLockConfig:
        registration = registration_store.load()
        resolved = resolve_unolock_config(
            base_url=registration.api_base_url,
            transparency_origin=registration.transparency_origin,
        )
        if not resolved.is_complete():
            raise ValueError(
                "UnoLock runtime configuration is not resolved yet. Submit a UnoLock agent key connection URL first "
                "or provide UNOLOCK_BASE_URL / UNOLOCK_APP_VERSION / UNOLOCK_SIGNING_PUBLIC_KEY overrides."
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

    server = FastMCP(
        name="UnoLock Agent MCP",
        instructions=(
            "Start with unolock_get_registration_status and follow its recommended_next_action. "
            "Prefer the primary workflow tools first: unolock_submit_agent_bootstrap, unolock_bootstrap_agent, "
            "unolock_list_spaces, unolock_list_records, and unolock_get_record. Read records before writing so you "
            "have current version and allowed_operations metadata. Low-level flow and API tools are advanced/debug "
            "tools and should not be the normal first choice. If registration is not configured, ask the user for "
            "the one-time-use UnoLock agent key connection URL and the optional agent PIN together when possible, "
            "then submit them with unolock_submit_agent_bootstrap. The connection URL is for enrollment only."
        ),
    )

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
                "unolock_get_registration_status",
                "unolock_submit_agent_bootstrap",
                "unolock_bootstrap_agent",
                "unolock_list_spaces",
                "unolock_list_records",
                "unolock_get_record",
            ],
            "write_rule": "Read the target record first, then use record_ref, version, writable, and allowed_operations before writing.",
            "advanced_tools_note": "Ignore low-level flow/api tools unless the primary workflow cannot complete the task.",
        }

    @server.prompt(
        name="unolock_request_connection_url",
        title="Request UnoLock Connection URL",
        description="Prompt content telling the agent how to ask the user for an UnoLock agent key connection URL.",
    )
    def request_connection_url_prompt() -> list[dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": (
                "If UnoLock registration is not configured, ask the user to provide the UnoLock "
                    "agent key connection URL for AI/agent registration and, if they configured one, the UnoLock "
                    "agent PIN at the same time. The connection URL is one-time-use and for enrollment only. Once "
                    "the user gives you those values, call "
                    "unolock_submit_agent_bootstrap."
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
                    "Use UnoLock in this order: first call unolock_get_registration_status. "
                    "If registration is needed, ask the user for the one-time-use UnoLock agent key connection URL "
                    "and optional PIN together, then call unolock_submit_agent_bootstrap and unolock_bootstrap_agent. "
                    "After authentication, prefer unolock_list_spaces, unolock_list_records, and unolock_get_record. "
                    "Before writing, read the target record and use its writable, allowed_operations, record_ref, and "
                    "version fields. Avoid low-level flow/api tools unless the primary workflow cannot complete the task."
                ),
            }
        ]

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
        name="unolock_get_registration_status",
        description=(
            "Return whether this MCP is already registered. If not registered, the response will say "
            "that the agent should ask the user for the one-time-use UnoLock agent key connection URL."
        ),
    )
    def get_registration_status() -> dict[str, Any]:
        return _registration_status_payload(registration_store, session_store, agent_auth)

    @server.tool(
        name="unolock_set_agent_pin",
        description=(
            "Store an optional UnoLock agent PIN in MCP process memory only. The MCP will hash it with the "
            "server challenge when a GetPin callback is encountered."
        ),
    )
    def set_agent_pin(pin: str) -> dict[str, Any]:
        return agent_auth.set_agent_pin(pin)

    @server.tool(
        name="unolock_clear_agent_pin",
        description="Clear the in-memory UnoLock agent PIN from the running MCP process.",
    )
    def clear_agent_pin() -> dict[str, Any]:
        return agent_auth.clear_agent_pin()

    @server.tool(
        name="unolock_acknowledge_reduced_assurance",
        description=(
            "Record that the user understands this host is using the lower-assurance software provider and still "
            "wants to continue."
        ),
    )
    def acknowledge_reduced_assurance() -> dict[str, Any]:
        return agent_auth.acknowledge_reduced_assurance()

    @server.tool(
        name="unolock_get_tpm_diagnostics",
        description=(
            "Diagnose the active UnoLock TPM/vTPM provider and the host TPM/vTPM signals. "
            "Returns production-readiness and advice if the host does not have a working TPM/vTPM."
        ),
    )
    def get_tpm_diagnostics() -> dict[str, Any]:
        return agent_auth.tpm_diagnostics()

    @server.tool(
        name="unolock_submit_connection_url",
        description=(
            "Accept a one-time-use UnoLock agent key connection URL from the user, persist it locally for "
            "enrollment, and parse any flow/args or registration code embedded in it."
        ),
    )
    def submit_connection_url(connection_url: str) -> dict[str, Any]:
        return agent_auth.submit_connection_url(connection_url)

    @server.tool(
        name="unolock_submit_agent_bootstrap",
        description=(
            "Accept the one-time-use UnoLock agent key connection URL and an optional agent PIN together. "
            "This is the preferred cold-start bootstrap tool."
        ),
    )
    def submit_agent_bootstrap(connection_url: str, pin: str | None = None) -> dict[str, Any]:
        status = agent_auth.submit_connection_url(connection_url)
        if status.get("ok") is False or status.get("blocked"):
            return status
        if pin:
            status = agent_auth.set_agent_pin(pin)
        return {
            "ok": True,
            "registration": registration_store.load().summary(),
            "runtime": agent_auth.runtime_status(),
            "message": (
                "UnoLock agent bootstrap material was accepted. If registration is not complete yet, "
                "call unolock_bootstrap_agent."
            ),
        }

    @server.tool(
        name="unolock_clear_connection_url",
        description="Clear the locally stored UnoLock agent key connection URL.",
    )
    def clear_connection_url() -> dict[str, Any]:
        return registration_store.clear_connection_url().summary()

    @server.tool(
        name="unolock_disconnect_agent",
        description=(
            "Permanently disconnect this local MCP host from its current UnoLock agent registration by "
            "deleting local TPM keys, protected secrets, registration state, sessions, and in-memory PINs. "
            "This does not delete the server-side access record."
        ),
    )
    def disconnect_agent() -> dict[str, Any]:
        return agent_auth.disconnect()

    @server.tool(
        name="unolock_start_registration_from_connection_url",
        description=(
            "Attempt to start UnoLock registration from the stored one-time-use connection URL. If the server-side "
            "agent registration flow is not implemented yet, this returns a clear pending/unsupported result."
        ),
    )
    def start_registration_from_connection_url() -> dict[str, Any]:
        ensure_flow_client()
        return agent_auth.start_registration_from_stored_url()

    @server.tool(
        name="unolock_continue_agent_session",
        description=(
            "Automatically continue a stored UnoLock agent session through known agent callbacks such as "
            "AgentRegistrationCode, AgentKeyRegistration, AgentChallenge, GetSafeAccessID, DecodeKey, and ClientDataKey."
        ),
    )
    def continue_agent_session(session_id: str) -> dict[str, Any]:
        ensure_flow_client()
        return agent_auth.advance_session(session_id)

    @server.tool(
        name="unolock_authenticate_agent",
        description=(
            "Start UnoLock agentAccess and automatically progress the agent flow with the locally stored "
            "agent credential and bootstrap material."
        ),
    )
    def authenticate_agent() -> dict[str, Any]:
        ensure_flow_client()
        return agent_auth.authenticate_registered_agent()

    @server.tool(
        name="unolock_bootstrap_agent",
        description=(
            "One-shot UnoLock bootstrap helper. If not registered, it starts registration from the "
            "stored connection URL. If already registered, it authenticates the agent."
        ),
    )
    def bootstrap_agent() -> dict[str, Any]:
        status = _registration_status_payload(registration_store, session_store, agent_auth)
        ensure_flow_client()
        if not status.get("has_connection_url"):
            return {
                "ok": False,
                "reason": "missing_connection_url",
                "status": status,
            }
        if not status.get("registered"):
            return {
                "status": status,
                "result": agent_auth.start_registration_from_stored_url(),
            }
        return {
            "status": status,
            "result": agent_auth.authenticate_registered_agent(),
        }

    @server.tool(
        name="unolock_start_flow",
        description=(
            "Advanced/debug: start a UnoLock auth flow, automatically complete PQ negotiation, and return a "
            "session_id plus the next callback that requires client handling."
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
            "Advanced/debug: reply to the current UnoLock auth-flow callback for a session. "
            "If callback_type is omitted, the current callback type is reused."
        ),
    )
    def continue_flow(
        session_id: str,
        callback_type: str | None = None,
        request: Any | None = None,
        result: Any | None = None,
        reason: str | None = None,
        message: list[str] | None = None,
    ) -> dict[str, Any]:
        session = session_store.get(session_id)
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
            registration_store.mark_registered(session_id=updated.session_id)
        return updated.summary()

    @server.tool(
        name="unolock_get_session",
        description="Advanced/debug: inspect the current in-memory UnoLock auth-flow session state.",
    )
    def get_session(session_id: str) -> dict[str, Any]:
        return session_store.get(session_id).summary()

    @server.tool(
        name="unolock_list_sessions",
        description="Advanced/debug: list the current in-memory UnoLock auth-flow sessions.",
    )
    def list_sessions() -> list[dict[str, Any]]:
        return session_store.list()

    @server.tool(
        name="unolock_delete_session",
        description="Advanced/debug: delete an in-memory UnoLock auth-flow session.",
    )
    def delete_session(session_id: str) -> dict[str, Any]:
        session_store.delete(session_id)
        return {"deleted": session_id}

    @server.tool(
        name="unolock_call_api",
        description="Advanced/debug: call a generic authenticated UnoLock /api action for an existing session.",
    )
    def call_api(
        session_id: str,
        action: str,
        request: Any | None = None,
        result: Any | None = None,
        reason: str | None = None,
        message: list[str] | None = None,
    ) -> dict[str, Any]:
        api_client = UnoLockApiClient(ensure_flow_client(), session_store)
        return api_client.call_action(
            session_id,
            action=action,
            request=request,
            result=result,
            reason=reason,
            message=message,
        )

    @server.tool(
        name="unolock_get_spaces",
        description="Advanced/debug: call UnoLock GetSpaces for an authenticated session.",
    )
    def get_spaces(session_id: str) -> dict[str, Any]:
        api_client = UnoLockApiClient(ensure_flow_client(), session_store)
        return api_client.get_spaces(session_id)

    @server.tool(
        name="unolock_get_archives",
        description="Advanced/debug: call UnoLock GetArchives for an authenticated session.",
    )
    def get_archives(session_id: str) -> dict[str, Any]:
        api_client = UnoLockApiClient(ensure_flow_client(), session_store)
        return api_client.get_archives(session_id)

    @server.tool(
        name="unolock_list_spaces",
        description=(
            "List UnoLock spaces with record counts and write capability metadata for an authenticated session. "
            "Use writable and allowed_operations to decide whether note/checklist writes are allowed."
        ),
    )
    def list_spaces(session_id: str) -> dict[str, Any]:
        readonly_records = UnoLockReadonlyRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return readonly_records.list_spaces(session_id)

    @server.tool(
        name="unolock_list_records",
        description=(
            "List read-only UnoLock notes and checklists for an authenticated session. "
            "Records are projected into agent-friendly plain text and checklist items, and include version, "
            "writable, locked, and allowed_operations metadata."
        ),
    )
    def list_records(
        session_id: str,
        kind: str = "all",
        space_id: int | None = None,
        pinned: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        readonly_records = UnoLockReadonlyRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return readonly_records.list_records(
            session_id,
            kind=kind,
            space_id=space_id,
            pinned=pinned,
            label=label,
        )

    @server.tool(
        name="unolock_list_notes",
        description="List read-only UnoLock notes with version and writable metadata for an authenticated session.",
    )
    def list_notes(
        session_id: str,
        space_id: int | None = None,
        pinned: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        readonly_records = UnoLockReadonlyRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return readonly_records.list_records(
            session_id,
            kind="note",
            space_id=space_id,
            pinned=pinned,
            label=label,
        )

    @server.tool(
        name="unolock_list_checklists",
        description="List read-only UnoLock checklists with version and writable metadata for an authenticated session.",
    )
    def list_checklists(
        session_id: str,
        space_id: int | None = None,
        pinned: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        readonly_records = UnoLockReadonlyRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return readonly_records.list_records(
            session_id,
            kind="checklist",
            space_id=space_id,
            pinned=pinned,
            label=label,
        )

    @server.tool(
        name="unolock_get_record",
        description=(
            "Get one read-only UnoLock note or checklist by record_ref. "
            "Use unolock_list_records first to discover record_ref values and current version metadata before writing."
        ),
    )
    def get_record(session_id: str, record_ref: str) -> dict[str, Any]:
        readonly_records = UnoLockReadonlyRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return readonly_records.get_record(session_id, record_ref)

    @server.tool(
        name="unolock_create_note",
        description=(
            "Create a new UnoLock note from raw text in an existing writable Records archive. "
            "Read the target space first and check writable/allowed_operations before creating notes. "
            "The returned record metadata includes the new record version and lock state."
        ),
    )
    def create_note(session_id: str, space_id: int, title: str, text: str) -> dict[str, Any]:
        writable_records = UnoLockWritableRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return writable_records.create_note(
            session_id,
            space_id=space_id,
            title=title,
            text=text,
        )

    @server.tool(
        name="unolock_create_checklist",
        description=(
            "Create a new UnoLock checklist in an existing writable Records archive. "
            "Each item must be an object like {text: string, checked?: boolean}. "
            "Use checked, done, or state='checked' to create initially checked items. "
            "Read the target space first and check writable/allowed_operations before creating checklists."
        ),
    )
    def create_checklist(session_id: str, space_id: int, title: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        writable_records = UnoLockWritableRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return writable_records.create_checklist(
            session_id,
            space_id=space_id,
            title=title,
            items=items,
        )

    @server.tool(
        name="unolock_update_note",
        description=(
            "Update an existing UnoLock note from raw text. "
            "Read the note first, then use the returned record_ref, version, and allowed_operations metadata. "
            "If the note is locked, read-only, or changed since the last read, the MCP will reject the update."
        ),
    )
    def update_note(session_id: str, record_ref: str, expected_version: int, title: str, text: str) -> dict[str, Any]:
        writable_records = UnoLockWritableRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return writable_records.update_note(
            session_id,
            record_ref=record_ref,
            expected_version=expected_version,
            title=title,
            text=text,
        )

    @server.tool(
        name="unolock_rename_record",
        description=(
            "Rename an existing UnoLock note or checklist by changing its title only. "
            "Read the record first, then use the returned record_ref, version, and allowed_operations metadata. "
            "If the record is locked, read-only, or changed since the last read, the MCP will reject the rename."
        ),
    )
    def rename_record(session_id: str, record_ref: str, expected_version: int, title: str) -> dict[str, Any]:
        writable_records = UnoLockWritableRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return writable_records.rename_record(
            session_id,
            record_ref=record_ref,
            expected_version=expected_version,
            title=title,
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
        session_id: str,
        record_ref: str,
        expected_version: int,
        item_id: int,
        done: bool,
    ) -> dict[str, Any]:
        writable_records = UnoLockWritableRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return writable_records.set_checklist_item_done(
            session_id,
            record_ref=record_ref,
            expected_version=expected_version,
            item_id=item_id,
            done=done,
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
        session_id: str,
        record_ref: str,
        expected_version: int,
        text: str,
    ) -> dict[str, Any]:
        writable_records = UnoLockWritableRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return writable_records.add_checklist_item(
            session_id,
            record_ref=record_ref,
            expected_version=expected_version,
            text=text,
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
        session_id: str,
        record_ref: str,
        expected_version: int,
        item_id: int,
    ) -> dict[str, Any]:
        writable_records = UnoLockWritableRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        return writable_records.remove_checklist_item(
            session_id,
            record_ref=record_ref,
            expected_version=expected_version,
            item_id=item_id,
        )

    return server
