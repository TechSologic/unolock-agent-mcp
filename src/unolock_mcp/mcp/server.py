from __future__ import annotations

import os
from typing import Any

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
        "missing_connection_url": "Ask the user for the one-time UnoLock Agent Key URL, then call unolock_submit_agent_bootstrap.",
        "wrong_connection_url_type": "Ask the user for a UnoLock Agent Key URL in the #/agent-register/... format.",
        "session_not_found": "Authenticate again or restart the UnoLock bootstrap flow, then retry the request.",
        "runtime_metadata_missing": "Submit a UnoLock Agent Key URL from the target Safe first. If this is a non-standard deployment, confirm that deployment metadata is published correctly.",
    }
    return {
        "ok": False,
        "reason": reason,
        "message": message,
        "suggested_action": suggested_action_map.get(reason, "Review the error and retry with corrected input or fresher data."),
    }


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
    guidance = "Agent registration is configured. Authenticate and start using the UnoLock tools allowed by this Agent Key."
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
            guidance = "Agent registration is configured. Authenticate and start using the UnoLock tools allowed by this Agent Key."
    elif not registration.get("has_connection_url"):
        next_action = "ask_for_connection_url"
        guidance = (
            "Ask the user for the one-time UnoLock Agent Key URL in the #/agent-register/... format. If they do not "
            "have one yet, ask them to open the Safe web app at https://safe.unolock.com/, create a dedicated Agent "
            "Key, and paste the generated URL here. Ask for the agent PIN only if that key uses one."
        )
    else:
        next_action = "start_registration"
        guidance = (
            "The Agent Key URL is already stored. Continue registration now with "
            "unolock_start_registration_from_connection_url or unolock_bootstrap_agent. Do not speculate about menu "
            "labels, URL expiry, or deployment internals unless the MCP reports a concrete blocker."
        )

    if security_warning:
        guidance = f"{guidance} Warning: {security_warning.get('message')}"

    primary_tools = [
        "unolock_get_registration_status",
        "unolock_submit_agent_bootstrap",
        "unolock_bootstrap_agent",
        "unolock_list_spaces",
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
        if key != "registration_mode"
    }
    public_registration["registration_state"] = (
        "registered"
        if registration.get("registered")
        else "waiting_for_connection_url"
        if not registration.get("has_connection_url")
        else "ready_to_register"
    )

    return {
        **public_registration,
        **runtime,
        "tpm_diagnostics": tpm,
        "security_warning": security_warning,
        "pending_session": pending_session,
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
            "Check registration status first.",
            "If needed, ask the user for the one-time Agent Key URL and optional PIN together.",
            "Authenticate or finish registration before using data tools.",
            "Read a space or record before writing so you have current version and allowed_operations metadata.",
            "If a write reports conflict, reread the target record and retry with the latest version.",
        ],
        "agent_behavior_rules": [
            "Do not narrate raw internal MCP state names to the user.",
            "Do not guess UnoLock UI menu labels or screen paths.",
            "Do not guess that a URL expired unless the MCP reports a concrete enrollment failure.",
            "If progress stops, report one concrete blocker and ask for one concrete next input.",
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
                "runtime_metadata_missing: UnoLock runtime metadata is not resolved yet. Submit a UnoLock agent key "
                "Agent Key URL from the target Safe first."
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
            "unolock_list_spaces, unolock_list_records, unolock_list_files, and unolock_get_record. Read records before "
            "writing so you have current version and allowed_operations metadata. If registration is not configured, "
            "ask the user for the one-time UnoLock Agent Key URL and the optional agent PIN together when possible, "
            "then submit them with unolock_submit_agent_bootstrap. The Agent Key URL is for enrollment only. "
            "If the user needs an explanation of what UnoLock is, why the MCP asks for an Agent Key URL or PIN, "
            "or why host assurance matters, use the explanatory UnoLock resources instead of improvising."
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
                "unolock_list_files",
                "unolock_get_record",
            ],
            "normal_flow_note": (
                "After the local stdio MCP is running, it should guide the agent through whatever registration or "
                "authentication step is actually required. Start with unolock_get_registration_status and follow "
                "its recommended_next_action instead of inventing a manual bootstrap sequence."
            ),
            "agent_behavior_note": (
                "Ask only for the Agent Key URL and, if needed, the PIN. Do not invent menu paths, expiry behavior, "
                "or deployment internals unless the MCP reports a concrete blocker."
            ),
            "write_rule": "Read the target record first, then use record_ref, version, writable, and allowed_operations before writing.",
        }

    @server.resource(
        "unolock://usage/about",
        name="About UnoLock Agent MCP",
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
                "The one-time Agent Key URL is only used to enroll the local UnoLock MCP on this machine.",
                "After enrollment, ongoing access uses the registered agent key plus normal UnoLock authentication, not the URL itself.",
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
                "The Agent Key URL is a one-time enrollment URL created by the Safe admin.",
                "It tells the MCP how to register the local host for that Agent Key.",
                "It is not the ongoing access credential and should be treated as enrollment-only.",
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
        name="UnoLock MCP Updates",
        description="Agent-safe guidance for how UnoLock Agent MCP updates should be checked and applied.",
        mime_type="application/json",
    )
    def updates_resource() -> dict[str, Any]:
        return {
            "summary": (
                "UnoLock Agent MCP should normally be updated by its wrapper or runner, not by the live MCP "
                "server replacing itself mid-session."
            ),
            "preferred_path": [
                "Prefer mcporter keep-alive plus `npx @techsologic/unolock-agent-mcp@latest` when available.",
                "Use `unolock_get_update_status` or `unolock-agent-mcp check-update` to see whether a newer release exists.",
                "If an update is available, restart the runner between tasks so the wrapper or binary can be replaced cleanly.",
            ],
            "rules": [
                "Do not attempt in-place self-replacement while an active UnoLock session or write flow is in progress.",
                "Avoid updating in the middle of a sensitive workflow that depends on an in-memory PIN.",
                "Prefer explicit user awareness before applying an update.",
            ],
            "channels": {
                "npm-wrapper": "Restart and relaunch with `npx @techsologic/unolock-agent-mcp@latest`.",
                "release-binary": "Download the latest GitHub Release binary, replace the executable, then restart the runner.",
                "python-package": "Upgrade the Python package in the environment that launches the MCP and restart the runner.",
            },
            "release_url": "https://github.com/TechSologic/unolock-agent-mcp/releases",
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
                    "Agent Key URL for AI/agent registration and, if they configured one, the UnoLock "
                    "agent PIN at the same time. The Agent Key URL is one-time-use and only registers the local "
                    "UnoLock MCP on this machine. Once registration succeeds, ongoing access uses the registered "
                    "agent key and normal authentication, not the URL itself. Once "
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
                    "If registration is needed, ask the user for the one-time UnoLock Agent Key URL "
                    "and optional PIN together, then call unolock_submit_agent_bootstrap and unolock_bootstrap_agent. "
                    "Treat the Agent Key URL only as the one-time enrollment input for the local MCP on this machine, "
                    "not as the ongoing access credential. "
                    "After authentication, prefer unolock_list_spaces, unolock_list_records, unolock_list_files, and "
                    "unolock_get_record. Before writing, read the target record and use its writable, "
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
                    "When a user asks why UnoLock Agent MCP needs an Agent Key URL, PIN, or a stronger host key store, "
                    "explain it plainly: UnoLock uses an Agent Key instead of a reusable API key. The one-time "
                    "Agent Key URL is only for enrolling the local MCP on this machine. After registration, the agent "
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
        name="unolock_get_registration_status",
        description=(
            "Return whether this MCP is already registered. If not registered, the response will say "
            "that the agent should ask the user for the one-time UnoLock Agent Key URL."
        ),
    )
    def get_registration_status() -> dict[str, Any]:
        return _registration_status_payload(registration_store, session_store, agent_auth)

    @server.tool(
        name="unolock_get_update_status",
        description=(
            "Check the installed UnoLock Agent MCP version against the latest GitHub Release and return "
            "runner-specific update guidance. Prefer checking between tasks, not during an active flow."
        ),
    )
    def get_update_status_tool() -> dict[str, Any]:
        try:
            return get_update_status()
        except Exception as exc:
            return _tool_error_response(exc)

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
            return agent_auth.set_agent_pin(pin)
        except ValueError as exc:
            return _tool_error_response(exc)

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
            "Accept a one-time UnoLock Agent Key URL from the user and store it locally for MCP-guided enrollment."
        ),
    )
    def submit_connection_url(connection_url: str) -> dict[str, Any]:
        try:
            return agent_auth.submit_connection_url(connection_url)
        except ValueError as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_submit_agent_bootstrap",
        description=(
            "Accept the one-time UnoLock Agent Key URL and an optional agent PIN together. "
            "This is the preferred cold-start bootstrap tool. If a PIN is provided, pass it as a string "
            "using only characters 0-9 and a-f."
        ),
    )
    def submit_agent_bootstrap(connection_url: str, pin: str | None = None) -> dict[str, Any]:
        status = agent_auth.submit_connection_url(connection_url)
        if status.get("ok") is False or status.get("blocked"):
            return status
        if pin:
            try:
                status = agent_auth.set_agent_pin(pin)
            except ValueError as exc:
                return _tool_error_response(exc)
        return {
            "ok": True,
            "registration": registration_store.load().summary(),
            "runtime": agent_auth.runtime_status(),
            "message": (
                "UnoLock Agent Key URL was accepted. Continue with MCP-guided registration next."
            ),
        }

    @server.tool(
        name="unolock_clear_connection_url",
        description="Clear the locally stored UnoLock Agent Key URL.",
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
            "Start UnoLock registration from the stored one-time Agent Key URL."
        ),
    )
    def start_registration_from_connection_url() -> dict[str, Any]:
        try:
            ensure_flow_client()
            return agent_auth.start_registration_from_stored_url()
        except ValueError as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_continue_agent_session",
        description=(
            "Automatically continue a stored UnoLock agent session through known agent callbacks such as "
            "AgentRegistrationCode, AgentKeyRegistration, AgentChallenge, GetSafeAccessID, DecodeKey, and ClientDataKey."
        ),
    )
    def continue_agent_session(session_id: str) -> dict[str, Any]:
        try:
            ensure_flow_client()
            return agent_auth.advance_session(session_id)
        except (ValueError, KeyError) as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_authenticate_agent",
        description=(
            "Start UnoLock agentAccess and automatically progress the agent flow with the locally stored "
            "agent credential and bootstrap material."
        ),
    )
    def authenticate_agent() -> dict[str, Any]:
        try:
            ensure_flow_client()
            return agent_auth.authenticate_registered_agent()
        except ValueError as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_bootstrap_agent",
        description=(
            "One-shot UnoLock bootstrap helper. If not registered, it starts registration from the "
            "stored Agent Key URL. If already registered, it authenticates the agent."
        ),
    )
    def bootstrap_agent() -> dict[str, Any]:
        try:
            status = _registration_status_payload(registration_store, session_store, agent_auth)
            ensure_flow_client()
            if not status.get("has_connection_url"):
                return {
                    "ok": False,
                    "reason": "missing_connection_url",
                    "status": status,
                    "suggested_action": "Ask the user for the one-time UnoLock Agent Key URL, then call unolock_submit_agent_bootstrap.",
                }
            if not status.get("registered"):
                return {
                    "ok": True,
                    "status": status,
                    "result": agent_auth.start_registration_from_stored_url(),
                }
            return {
                "ok": True,
                "status": status,
                "result": agent_auth.authenticate_registered_agent(),
            }
        except ValueError as exc:
            return _tool_error_response(exc)

    if _advanced_tools_enabled():
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
            "List UnoLock spaces with record counts, Cloud file counts, and write capability metadata for an authenticated session. "
            "Use writable and allowed_operations to decide whether note/checklist or file actions are allowed."
        ),
    )
    def list_spaces(session_id: str) -> dict[str, Any]:
        try:
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return readonly_records.list_spaces(session_id)
        except (ValueError, KeyError) as exc:
            return _tool_error_response(exc)

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
        try:
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
        except (ValueError, KeyError) as exc:
            return _tool_error_response(exc)

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
        try:
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
        except (ValueError, KeyError) as exc:
            return _tool_error_response(exc)

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
        try:
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
        except (ValueError, KeyError) as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_list_files",
        description=(
            "List UnoLock Cloud files for an authenticated session. "
            "Only Cloud archives are exposed by the MCP; Local and Msg archives are intentionally excluded."
        ),
    )
    def list_files(session_id: str, space_id: int | None = None) -> dict[str, Any]:
        try:
            readonly_files = UnoLockReadonlyFilesClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return readonly_files.list_files(session_id, space_id=space_id)
        except (ValueError, KeyError) as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_get_file",
        description=(
            "Get metadata for one UnoLock Cloud file by archive_id. "
            "Use unolock_list_files first to discover archive_id values."
        ),
    )
    def get_file(session_id: str, archive_id: str) -> dict[str, Any]:
        try:
            readonly_files = UnoLockReadonlyFilesClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return readonly_files.get_file(session_id, archive_id)
        except (ValueError, KeyError) as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_download_file",
        description=(
            "Download one UnoLock Cloud file to a local filesystem path. "
            "Only Cloud files are supported; Local and Msg archives are excluded."
        ),
    )
    def download_file(session_id: str, archive_id: str, output_path: str, overwrite: bool = False) -> dict[str, Any]:
        try:
            readonly_files = UnoLockReadonlyFilesClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return readonly_files.download_file(
                session_id,
                archive_id=archive_id,
                output_path=output_path,
                overwrite=overwrite,
            )
        except (ValueError, KeyError) as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_upload_file",
        description=(
            "Upload a local filesystem file into a UnoLock Cloud archive in the requested space. "
            "Only Cloud files are supported; Local and Msg archives are excluded."
        ),
    )
    def upload_file(
        session_id: str,
        space_id: int,
        local_path: str,
        name: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        writable_files = UnoLockWritableFilesClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        try:
            return writable_files.upload_file(
                session_id,
                space_id=space_id,
                local_path=local_path,
                name=name,
                mime_type=mime_type,
            )
        except ValueError as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_rename_file",
        description=(
            "Rename one UnoLock Cloud file by archive_id. "
            "Use unolock_get_file first to confirm writable=true and the current file metadata."
        ),
    )
    def rename_file(session_id: str, archive_id: str, name: str) -> dict[str, Any]:
        writable_files = UnoLockWritableFilesClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        try:
            return writable_files.rename_file(
                session_id,
                archive_id=archive_id,
                name=name,
            )
        except ValueError as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_replace_file",
        description=(
            "Replace the content of one existing UnoLock Cloud file from a local filesystem path. "
            "Use unolock_get_file first to confirm writable=true and the target archive_id."
        ),
    )
    def replace_file(
        session_id: str,
        archive_id: str,
        local_path: str,
        name: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        writable_files = UnoLockWritableFilesClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        try:
            return writable_files.replace_file(
                session_id,
                archive_id=archive_id,
                local_path=local_path,
                name=name,
                mime_type=mime_type,
            )
        except ValueError as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_delete_file",
        description=(
            "Delete one UnoLock Cloud file by archive_id. "
            "Use unolock_get_file first to confirm writable=true and the target archive_id."
        ),
    )
    def delete_file(session_id: str, archive_id: str) -> dict[str, Any]:
        writable_files = UnoLockWritableFilesClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        try:
            return writable_files.delete_file(
                session_id,
                archive_id=archive_id,
            )
        except ValueError as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_get_record",
        description=(
            "Get one read-only UnoLock note or checklist by record_ref. "
            "Use unolock_list_records first to discover record_ref values and current version metadata before writing."
        ),
    )
    def get_record(session_id: str, record_ref: str) -> dict[str, Any]:
        try:
            readonly_records = UnoLockReadonlyRecordsClient(
                UnoLockApiClient(ensure_flow_client(), session_store),
                agent_auth,
                session_store,
            )
            return readonly_records.get_record(session_id, record_ref)
        except (ValueError, KeyError) as exc:
            return _tool_error_response(exc)

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
        try:
            return writable_records.create_note(
                session_id,
                space_id=space_id,
                title=title,
                text=text,
            )
        except ValueError as exc:
            return _tool_error_response(exc)

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
        try:
            return writable_records.create_checklist(
                session_id,
                space_id=space_id,
                title=title,
                items=items,
            )
        except ValueError as exc:
            return _tool_error_response(exc)

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
        try:
            return writable_records.update_note(
                session_id,
                record_ref=record_ref,
                expected_version=expected_version,
                title=title,
                text=text,
            )
        except ValueError as exc:
            return _tool_error_response(exc)

    @server.tool(
        name="unolock_append_note",
        description=(
            "Append new line(s) of raw text to the end of an existing UnoLock note without resending the entire note body. "
            "Read the note first, then use the returned record_ref, version, and allowed_operations metadata. "
            "The MCP still enforces note locks and version conflicts before appending."
        ),
    )
    def append_note(session_id: str, record_ref: str, expected_version: int, append_text: str) -> dict[str, Any]:
        writable_records = UnoLockWritableRecordsClient(
            UnoLockApiClient(ensure_flow_client(), session_store),
            agent_auth,
            session_store,
        )
        try:
            return writable_records.append_note(
                session_id,
                record_ref=record_ref,
                expected_version=expected_version,
                append_text=append_text,
            )
        except ValueError as exc:
            return _tool_error_response(exc)

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
        try:
            return writable_records.rename_record(
                session_id,
                record_ref=record_ref,
                expected_version=expected_version,
                title=title,
            )
        except ValueError as exc:
            return _tool_error_response(exc)

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
        try:
            return writable_records.set_checklist_item_done(
                session_id,
                record_ref=record_ref,
                expected_version=expected_version,
                item_id=item_id,
                done=done,
            )
        except ValueError as exc:
            return _tool_error_response(exc)

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
        try:
            return writable_records.add_checklist_item(
                session_id,
                record_ref=record_ref,
                expected_version=expected_version,
                text=text,
            )
        except ValueError as exc:
            return _tool_error_response(exc)

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
        try:
            return writable_records.remove_checklist_item(
                session_id,
                record_ref=record_ref,
                expected_version=expected_version,
                item_id=item_id,
            )
        except ValueError as exc:
            return _tool_error_response(exc)

    return server
