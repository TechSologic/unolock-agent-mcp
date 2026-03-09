from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from unolock_mcp.api.client import UnoLockApiClient
from unolock_mcp.api.records import UnoLockReadonlyRecordsClient
from unolock_mcp.auth.agent_auth import AgentAuthClient
from unolock_mcp.auth.flow_client import UnoLockFlowClient
from unolock_mcp.auth.local_probe import LocalServerProbe
from unolock_mcp.auth.registration_store import RegistrationStore
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.config import load_unolock_config


def _registration_status_payload(
    registration_store: RegistrationStore,
    session_store: SessionStore,
    agent_auth: AgentAuthClient,
) -> dict[str, Any]:
    registration = registration_store.load().summary()
    runtime = agent_auth.runtime_status()
    tpm = agent_auth.tpm_diagnostics()
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
    elif not tpm.get("production_ready"):
        next_action = "review_tpm_diagnostics"
        guidance = (
            "The current TPM/vTPM provider is not production-ready. Call unolock_get_tpm_diagnostics "
            "and follow the advice before relying on this MCP for production access."
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
            "Ask the user for the UnoLock agent key connection URL generated for an AI/agent key, "
            "then call unolock_submit_connection_url."
        )
    else:
        next_action = "start_registration"
        guidance = (
            "An UnoLock agent key connection URL is stored. Call "
            "unolock_start_registration_from_connection_url to register this MCP."
        )

    return {
        **registration,
        **runtime,
        "tpm_diagnostics": tpm,
        "pending_session": pending_session,
        "recommended_next_action": next_action,
        "guidance": guidance,
    }


def create_mcp_server() -> FastMCP:
    config = load_unolock_config()
    flow_client = UnoLockFlowClient(config)
    session_store = SessionStore()
    api_client = UnoLockApiClient(flow_client, session_store)
    registration_store = RegistrationStore()
    agent_auth = AgentAuthClient(flow_client, session_store, registration_store)
    readonly_records = UnoLockReadonlyRecordsClient(api_client, agent_auth)

    server = FastMCP(
        name="UnoLock Agent MCP",
        instructions=(
            "Use this server to probe UnoLock callback compatibility, start UnoLock auth flows, "
            "continue flow callbacks, and call a small set of authenticated UnoLock API actions. "
            "If registration is not configured, ask the user for the UnoLock agent key connection URL and "
            "submit it with unolock_submit_connection_url."
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
                    "agent key connection URL for AI/agent registration. Once the user gives you that URL, call "
                    "unolock_submit_connection_url with it."
                ),
            }
        ]

    @server.tool(
        name="unolock_probe_local_server",
        description="Run the UnoLock local /start probe and return the next callback after PQ negotiation.",
    )
    def probe_local_server(
        base_url: str = config.base_url,
        flow: str = "access",
        app_version: str = config.app_version,
        signing_public_key: str = config.signing_public_key_b64,
    ) -> dict[str, Any]:
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
            "that the agent should ask the user for the UnoLock agent key connection URL."
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
            "Accept a UnoLock agent key connection URL from the user, persist it locally, and parse any "
            "flow/args or registration code embedded in it."
        ),
    )
    def submit_connection_url(connection_url: str) -> dict[str, Any]:
        return agent_auth.submit_connection_url(connection_url)

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
            "Attempt to start UnoLock registration from the stored connection URL. If the server-side "
            "agent registration flow is not implemented yet, this returns a clear pending/unsupported result."
        ),
    )
    def start_registration_from_connection_url() -> dict[str, Any]:
        return agent_auth.start_registration_from_stored_url()

    @server.tool(
        name="unolock_continue_agent_session",
        description=(
            "Automatically continue a stored UnoLock agent session through known agent callbacks such as "
            "AgentRegistrationCode, AgentKeyRegistration, AgentChallenge, GetSafeAccessID, DecodeKey, and ClientDataKey."
        ),
    )
    def continue_agent_session(session_id: str) -> dict[str, Any]:
        return agent_auth.advance_session(session_id)

    @server.tool(
        name="unolock_authenticate_agent",
        description=(
            "Start UnoLock agentAccess and automatically progress the agent flow with the locally stored "
            "agent credential and bootstrap material."
        ),
    )
    def authenticate_agent() -> dict[str, Any]:
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
            "Start a UnoLock auth flow, automatically complete PQ negotiation, and return a session_id "
            "plus the next callback that requires client handling."
        ),
    )
    def start_flow(flow: str = "access", args: str | None = None) -> dict[str, Any]:
        session = flow_client.start(flow=flow, args=args)
        session_store.put(session)
        return session.summary()

    @server.tool(
        name="unolock_continue_flow",
        description=(
            "Reply to the current UnoLock auth-flow callback for a session. "
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
        description="Inspect the current in-memory UnoLock auth-flow session state.",
    )
    def get_session(session_id: str) -> dict[str, Any]:
        return session_store.get(session_id).summary()

    @server.tool(
        name="unolock_list_sessions",
        description="List the current in-memory UnoLock auth-flow sessions.",
    )
    def list_sessions() -> list[dict[str, Any]]:
        return session_store.list()

    @server.tool(
        name="unolock_delete_session",
        description="Delete an in-memory UnoLock auth-flow session.",
    )
    def delete_session(session_id: str) -> dict[str, Any]:
        session_store.delete(session_id)
        return {"deleted": session_id}

    @server.tool(
        name="unolock_call_api",
        description="Call a generic authenticated UnoLock /api action for an existing session.",
    )
    def call_api(
        session_id: str,
        action: str,
        request: Any | None = None,
        result: Any | None = None,
        reason: str | None = None,
        message: list[str] | None = None,
    ) -> dict[str, Any]:
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
        description="Call UnoLock GetSpaces for an authenticated session.",
    )
    def get_spaces(session_id: str) -> dict[str, Any]:
        return api_client.get_spaces(session_id)

    @server.tool(
        name="unolock_get_archives",
        description="Call UnoLock GetArchives for an authenticated session.",
    )
    def get_archives(session_id: str) -> dict[str, Any]:
        return api_client.get_archives(session_id)

    @server.tool(
        name="unolock_list_spaces",
        description="List UnoLock spaces with record counts for an authenticated session.",
    )
    def list_spaces(session_id: str) -> dict[str, Any]:
        return readonly_records.list_spaces(session_id)

    @server.tool(
        name="unolock_list_records",
        description=(
            "List read-only UnoLock notes and checklists for an authenticated session. "
            "Records are projected into agent-friendly plain text and checklist items."
        ),
    )
    def list_records(
        session_id: str,
        kind: str = "all",
        space_id: int | None = None,
        pinned: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        return readonly_records.list_records(
            session_id,
            kind=kind,
            space_id=space_id,
            pinned=pinned,
            label=label,
        )

    @server.tool(
        name="unolock_list_notes",
        description="List read-only UnoLock notes for an authenticated session.",
    )
    def list_notes(
        session_id: str,
        space_id: int | None = None,
        pinned: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        return readonly_records.list_records(
            session_id,
            kind="note",
            space_id=space_id,
            pinned=pinned,
            label=label,
        )

    @server.tool(
        name="unolock_list_checklists",
        description="List read-only UnoLock checklists for an authenticated session.",
    )
    def list_checklists(
        session_id: str,
        space_id: int | None = None,
        pinned: bool | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
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
            "Use unolock_list_records first to discover record_ref values."
        ),
    )
    def get_record(session_id: str, record_ref: str) -> dict[str, Any]:
        return readonly_records.get_record(session_id, record_ref)

    return server
