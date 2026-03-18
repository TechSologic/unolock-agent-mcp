from __future__ import annotations

import argparse
import json
import sys

from unolock_mcp import __version__ as MCP_VERSION
from unolock_mcp.api.client import UnoLockApiClient
from unolock_mcp.api.records import UnoLockReadonlyRecordsClient
from unolock_mcp.auth.agent_auth import AgentAuthClient
from unolock_mcp.auth.flow_client import UnoLockFlowClient
from unolock_mcp.auth.local_probe import LocalServerProbe
from unolock_mcp.auth.registration_store import RegistrationStore
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.config import default_config_path, load_unolock_config, resolve_unolock_config
from unolock_mcp.domain.models import UnoLockConfig
from unolock_mcp.host import (
    LocalHostError,
    call_tool as call_daemon_tool,
    ensure_daemon_running,
    list_tools as list_daemon_tools,
    serve_local_daemon_forever,
    stop_daemon,
    get_daemon_status,
)
from unolock_mcp.mcp.server import create_mcp_server
from unolock_mcp.update import get_update_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UnoLock Agent MCP commands.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {MCP_VERSION}")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--transparency-origin", default=None)
    parser.add_argument("--app-version", default=None)
    parser.add_argument("--signing-public-key", default=None)
    subparsers = parser.add_subparsers(dest="command", required=False)

    probe_parser = subparsers.add_parser(
        "probe",
        help="Run the UnoLock local-server PQ probe.",
        description="Run the UnoLock agent probe against a live local server.",
    )
    probe_parser.add_argument("--flow", default="access")

    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Run the UnoLock stdio MCP server.",
        description="Run the UnoLock agent stdio MCP server.",
    )

    host_start_parser = subparsers.add_parser(
        "start",
        help="Start the UnoLock local daemon if it is not already running.",
        description=(
            "Start the first-party UnoLock local daemon. If the daemon is already running, "
            "return its current status instead of launching another copy."
        ),
    )
    host_start_parser.add_argument("--timeout", type=float, default=15.0)

    subparsers.add_parser(
        "status",
        help="Show whether the UnoLock local daemon is running.",
        description="Inspect the first-party UnoLock local daemon state.",
    )

    host_stop_parser = subparsers.add_parser(
        "stop",
        help="Stop the UnoLock local daemon.",
        description="Ask the first-party UnoLock local daemon to stop.",
    )
    host_stop_parser.add_argument("--timeout", type=float, default=5.0)

    host_tools_parser = subparsers.add_parser(
        "tools",
        help="List UnoLock MCP tools through the local daemon.",
        description="List the MCP tool names exposed by the currently running UnoLock local daemon.",
    )
    host_tools_parser.add_argument("--no-auto-start", action="store_true")

    host_call_parser = subparsers.add_parser(
        "call",
        help="Call one UnoLock MCP tool through the local daemon.",
        description=(
            "Call one UnoLock MCP tool through the first-party local daemon. "
            "If the daemon is not running yet, this command starts it automatically."
        ),
    )
    host_call_parser.add_argument("tool")
    host_call_parser.add_argument(
        "--args",
        default="{}",
        help="JSON object of tool arguments. Example: --args '{\"pin\":\"1\"}'",
    )
    host_call_parser.add_argument("--no-auto-start", action="store_true")
    host_call_parser.add_argument("--timeout", type=float, default=30.0)

    subparsers.add_parser(
        "_daemon",
        help=argparse.SUPPRESS,
        description=argparse.SUPPRESS,
    )

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Advanced/manual: register or authenticate the UnoLock agent using the local registration store.",
        description=(
            "Advanced/manual path. Use the stored UnoLock connection URL and optional PIN to "
            "register/authenticate the agent. For the normal customer or agent flow, prefer an "
            "MCP host and the MCP tools instead of calling this CLI command directly."
        ),
    )
    bootstrap_parser.add_argument("--connection-url", default=None)
    bootstrap_parser.add_argument("--pin", default=None)
    bootstrap_parser.add_argument("--list-records", action="store_true")
    bootstrap_parser.add_argument("--allow-reduced-assurance", action="store_true")

    subparsers.add_parser(
        "disconnect",
        help="Permanently disconnect the local UnoLock agent registration from this host.",
        description=(
            "Delete the local UnoLock agent TPM key, protected secrets, registration state, in-memory PIN, "
            "and cached sessions. This does not delete the server-side access record."
        ),
    )

    diagnose_parser = subparsers.add_parser(
        "tpm-diagnose",
        help="Diagnose TPM/vTPM readiness for the UnoLock agent MCP.",
        description="Inspect the active TPM DAO and host TPM/vTPM signals and print advice.",
    )
    diagnose_parser.add_argument("--json", action="store_true", help="Print full JSON diagnostics.")

    tpm_check_parser = subparsers.add_parser(
        "tpm-check",
        help="Fail-fast check for production-ready TPM/vTPM/platform-backed key access.",
        description=(
            "Run a minimal UnoLock TPM readiness check and exit nonzero if a production-ready TPM, vTPM, "
            "Secure Enclave, or equivalent platform-backed provider is not available."
        ),
    )
    tpm_check_parser.add_argument("--json", action="store_true", help="Print the fail-fast result as JSON.")

    self_test_parser = subparsers.add_parser(
        "self-test",
        help="Run a one-shot UnoLock Agent MCP readiness check.",
        description=(
            "Check whether this host is suitable for UnoLock Agent MCP bootstrap, summarize the detected "
            "environment, and report the next recommended action."
        ),
    )
    self_test_parser.add_argument("--json", action="store_true", help="Print the self-test result as JSON.")

    mcporter_parser = subparsers.add_parser(
        "mcporter-config",
        help="Print a ready-to-paste mcporter keep-alive server config.",
        description=(
            "Print a named mcporter server entry for UnoLock Agent MCP. "
            "Use this when you want mcporter to keep the MCP alive between interactions."
        ),
    )
    mcporter_parser.add_argument(
        "--mode",
        choices=["npm", "binary"],
        default="npm",
        help="Choose whether mcporter should launch the npm wrapper or a direct binary path.",
    )
    mcporter_parser.add_argument(
        "--binary-path",
        default="unolock-agent-mcp",
        help="Binary path to use when --mode=binary.",
    )

    update_parser = subparsers.add_parser(
        "check-update",
        help="Check whether a newer UnoLock Agent MCP release is available.",
        description=(
            "Check the installed UnoLock Agent MCP version against the latest GitHub Release and print "
            "runner-specific update guidance."
        ),
    )
    update_parser.add_argument("--json", action="store_true", help="Print the update status as JSON.")

    subparsers.add_parser(
        "config-check",
        help="Show the resolved UnoLock runtime configuration and missing values.",
        description="Inspect UnoLock MCP configuration sources from arguments, environment, config file, and repo auto-discovery.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "mcp"

    if command == "mcp":
        server = create_mcp_server()
        server.run("stdio")
        return 0

    if command == "_daemon":
        return serve_local_daemon_forever()

    if command == "start":
        try:
            payload = ensure_daemon_running(timeout=getattr(args, "timeout", 15.0))
        except LocalHostError as exc:
            print(json.dumps({"ok": False, "reason": "daemon_start_failed", "message": str(exc)}, indent=2))
            return 1
        print(json.dumps(payload, indent=2))
        return 0

    if command == "status":
        payload = get_daemon_status()
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok", True) else 1

    if command == "stop":
        try:
            payload = stop_daemon(timeout=getattr(args, "timeout", 5.0))
        except LocalHostError as exc:
            print(json.dumps({"ok": False, "reason": "daemon_stop_failed", "message": str(exc)}, indent=2))
            return 1
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok", True) else 1

    if command == "tools":
        try:
            payload = list_daemon_tools(auto_start=not getattr(args, "no_auto_start", False))
        except LocalHostError as exc:
            print(json.dumps({"ok": False, "reason": "daemon_tools_failed", "message": str(exc)}, indent=2))
            return 1
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok", True) else 1

    if command == "call":
        try:
            tool_args = json.loads(args.args)
        except json.JSONDecodeError as exc:
            print(json.dumps({"ok": False, "reason": "invalid_input", "message": f"Invalid JSON for --args: {exc}"}, indent=2))
            return 1
        if not isinstance(tool_args, dict):
            print(json.dumps({"ok": False, "reason": "invalid_input", "message": "--args must decode to a JSON object."}, indent=2))
            return 1
        try:
            payload = call_daemon_tool(
                args.tool,
                tool_args,
                auto_start=not getattr(args, "no_auto_start", False),
                timeout=getattr(args, "timeout", 30.0),
            )
        except LocalHostError as exc:
            print(json.dumps({"ok": False, "reason": "daemon_call_failed", "message": str(exc)}, indent=2))
            return 1
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok", True) else 1

    if command == "config-check":
        registration = RegistrationStore().load()
        resolved = resolve_unolock_config(
            base_url=args.base_url or registration.api_base_url or (registration.connection_url.api_base_url if registration.connection_url else None),
            transparency_origin=args.transparency_origin or registration.transparency_origin or (registration.connection_url.site_origin if registration.connection_url else None),
            app_version=args.app_version,
            signing_public_key_b64=args.signing_public_key,
        )
        runtime_base_url = _display_runtime_base_url(resolved=resolved, registration=registration.summary())
        payload = {
            "ok": resolved.is_complete(),
            "mcp_version": MCP_VERSION,
            "config_file": str(default_config_path()),
            "resolved": {
                "base_url": runtime_base_url,
                "transparency_origin": resolved.transparency_origin,
                "signing_public_key_b64": "<redacted>" if resolved.signing_public_key_b64 else None,
            },
            "sources": resolved.sources,
            "missing": [
                key for key, value in {
                    "signing_public_key_b64": resolved.signing_public_key_b64,
                }.items() if not value
            ],
            "guidance": (
                "In the normal flow, submit a UnoLock agent key connection URL and let the MCP derive the server "
                "origin and PQ validation key automatically. Use environment variables or the config file only for "
                "overrides and custom deployments."
            ),
        }
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1

    if command == "self-test":
        session_store = SessionStore()
        registration_store = RegistrationStore()
        agent_auth = AgentAuthClient(None, session_store, registration_store)
        registration = registration_store.load().summary()
        diagnostics = agent_auth.tpm_diagnostics()
        resolved = resolve_unolock_config(
            base_url=args.base_url or registration.get("api_base_url") or (registration.get("connection_url") or {}).get("api_base_url"),
            transparency_origin=args.transparency_origin or registration.get("transparency_origin") or (registration.get("connection_url") or {}).get("site_origin"),
            app_version=args.app_version,
            signing_public_key_b64=args.signing_public_key,
        )
        payload = _build_self_test_payload(
            diagnostics=diagnostics,
            registration=registration,
            resolved=resolved,
        )
        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2))
        else:
            status = "OK" if payload["ok"] else "NOT_READY"
            print(f"{status}: {payload['summary']}")
        return 0 if payload["ok"] else 1

    if command == "mcporter-config":
        if args.mode == "binary":
            payload = {
                "mcpServers": {
                    "unolock-agent": {
                        "type": "stdio",
                        "command": args.binary_path,
                        "args": [],
                        "lifecycle": "keep-alive",
                    }
                }
            }
        else:
            payload = {
                "mcpServers": {
                    "unolock-agent": {
                        "type": "stdio",
                        "command": "npx",
                        "args": ["@techsologic/unolock-agent-mcp@latest"],
                        "lifecycle": "keep-alive",
                    }
                }
            }
        print(json.dumps(payload, indent=2))
        return 0

    if command == "check-update":
        payload = get_update_status()
        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2))
        else:
            status = "UPDATE_AVAILABLE" if payload.get("update_available") else "UP_TO_DATE"
            if payload.get("ok") is False:
                status = "UNKNOWN"
            print(f"{status}: {payload.get('recommended_action')}")
        return 0

    def resolve_runtime_config(registration_store: RegistrationStore) -> UnoLockConfig:
        registration = registration_store.load()
        return load_unolock_config(
            base_url=args.base_url or registration.api_base_url or (registration.connection_url.api_base_url if registration.connection_url else None),
            transparency_origin=args.transparency_origin or registration.transparency_origin or (registration.connection_url.site_origin if registration.connection_url else None),
            app_version=args.app_version or registration.app_version,
            signing_public_key_b64=args.signing_public_key or registration.signing_public_key_b64,
        )

    if command == "bootstrap":
        session_store = SessionStore()
        registration_store = RegistrationStore()
        agent_auth = AgentAuthClient(None, session_store, registration_store)
        if args.connection_url:
            status = agent_auth.submit_connection_url(args.connection_url)
            if status.get("ok") is False or status.get("blocked"):
                print(json.dumps(status, indent=2))
                return 1
        if args.pin:
            agent_auth.set_agent_pin(args.pin)
        if args.allow_reduced_assurance:
            agent_auth.acknowledge_reduced_assurance()

        registration = registration_store.load()
        resolved = resolve_unolock_config(
            base_url=args.base_url or registration.api_base_url or (registration.connection_url.api_base_url if registration.connection_url else None),
            transparency_origin=(
                args.transparency_origin
                or registration.transparency_origin
                or (registration.connection_url.site_origin if registration.connection_url else None)
            ),
            app_version=args.app_version or registration.app_version,
            signing_public_key_b64=args.signing_public_key or registration.signing_public_key_b64,
        )
        registration_store.update_runtime_config(
            base_url=resolved.base_url,
            transparency_origin=resolved.transparency_origin,
            app_version=resolved.app_version,
            signing_public_key_b64=resolved.signing_public_key_b64,
        )

        flow_client = UnoLockFlowClient(resolve_runtime_config(registration_store))
        agent_auth.set_flow_client(flow_client)

        registration = registration_store.load()
        if not registration.registered:
            result = agent_auth.start_registration_from_stored_url()
        else:
            result = agent_auth.authenticate_registered_agent()

        if (
            args.list_records
            and result.get("ok")
            and result.get("authorized")
        ):
            api_client = UnoLockApiClient(flow_client, session_store)
            records_client = UnoLockReadonlyRecordsClient(api_client, agent_auth, session_store)
            result["records"] = records_client.list_records(SessionStore.ACTIVE_SESSION_ID)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") and result.get("authorized") else 1

    if command == "disconnect":
        session_store = SessionStore()
        registration_store = RegistrationStore()
        agent_auth = AgentAuthClient(None, session_store, registration_store)
        result = agent_auth.disconnect()
        print(json.dumps(result, indent=2))
        return 0

    if command in {"tpm-diagnose", "tpm-check"}:
        session_store = SessionStore()
        registration_store = RegistrationStore()
        agent_auth = AgentAuthClient(None, session_store, registration_store)
        diagnostics = agent_auth.tpm_diagnostics()
        if command == "tpm-diagnose":
            print(json.dumps(diagnostics, indent=2))
            return 0 if diagnostics.get("production_ready") else 1

        payload = {
            "ok": bool(diagnostics.get("production_ready")),
            "provider_name": diagnostics.get("provider_name"),
            "provider_type": diagnostics.get("provider_type"),
            "production_ready": bool(diagnostics.get("production_ready")),
            "summary": diagnostics.get("summary"),
            "advice": diagnostics.get("advice", []),
        }
        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2))
        else:
            status = "OK" if payload["ok"] else "NOT_READY"
            print(f"{status}: {payload['summary']}")
        return 0 if payload["ok"] else 1

    config = load_unolock_config(
        base_url=args.base_url,
        transparency_origin=args.transparency_origin,
        app_version=args.app_version,
        signing_public_key_b64=args.signing_public_key,
    )
    probe = LocalServerProbe(
        base_url=config.base_url,
        app_version=config.app_version,
        signing_public_key_b64=config.signing_public_key_b64,
    )

    result = probe.run(flow=getattr(args, "flow", "access"))
    print(LocalServerProbe.to_json(result))
    return 0


def probe_main() -> int:
    return main(["probe", *sys.argv[1:]])


def mcp_main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"--help", "-h", "--version"}:
        return main(sys.argv[1:])
    return main(sys.argv[1:])


def tpm_check_main() -> int:
    return main(["tpm-check", *sys.argv[1:]])


def self_test_main() -> int:
    return main(["self-test", *sys.argv[1:]])


def _build_self_test_payload(*, diagnostics: dict, registration: dict, resolved) -> dict:
    environment = diagnostics.get("details", {}).get("environment", {})
    recommended_host_shape = _recommended_host_shape(environment)
    docs = diagnostics.get("details", {}).get("docs", {})
    runtime_base_url = _display_runtime_base_url(resolved=resolved, registration=registration)

    if registration.get("registered"):
        next_action = "authenticate_agent"
        guidance = "This host is ready. Ask the user for the agent PIN if needed, then authenticate."
    else:
        next_action = "ask_for_connection_url"
        guidance = (
            "This host is ready for bootstrap. Ask the user for the one-time-use UnoLock agent key connection URL "
            "and optional PIN, then start registration."
        )

    ok = bool(diagnostics.get("production_ready"))
    if not ok:
        next_action = "review_tpm_diagnostics_and_decide"
        guidance = (
            "This host could not satisfy UnoLock's preferred device-bound key-storage requirements. Review the "
            "TPM/environment diagnostics and decide whether reduced-assurance operation on this host is acceptable "
            "for your Safe data before continuing."
        )

    summary = str(diagnostics.get("summary") or "UnoLock Agent MCP self-test completed.")
    if ok and environment.get("is_container"):
        summary = f"{summary} Containerized environments still need a real host or VM trust path."

    return {
        "ok": ok,
        "mcp_version": MCP_VERSION,
        "provider_name": diagnostics.get("provider_name"),
        "provider_type": diagnostics.get("provider_type"),
        "production_ready": bool(diagnostics.get("production_ready")),
        "environment": environment,
        "recommended_host_shape": recommended_host_shape,
        "registration": {
            "registered": bool(registration.get("registered")),
            "access_id": registration.get("access_id"),
            "tpm_provider": registration.get("tpm_provider"),
        },
        "runtime_config": {
            "base_url": runtime_base_url,
            "transparency_origin": getattr(resolved, "transparency_origin", None),
            "pq_validation_key_available": bool(getattr(resolved, "signing_public_key_b64", None)),
        },
        "summary": summary,
        "recommended_next_action": next_action,
        "guidance": guidance,
        "docs": docs,
        "tpm_diagnostics": diagnostics,
    }


def _recommended_host_shape(environment: dict) -> str:
    if environment.get("is_wsl"):
        return "WSL using the Windows TPM helper"
    if environment.get("is_container"):
        runtime = environment.get("container_runtime") or "container"
        return f"{runtime} backed by a real host or VM TPM/vTPM path"
    return "normal logged-in desktop or VM session with TPM/vTPM/platform-backed key access"


def _display_runtime_base_url(*, resolved, registration: dict) -> str | None:
    if getattr(resolved, "base_url", None) is None:
        return None
    if getattr(resolved, "sources", {}).get("base_url") != "default":
        return resolved.base_url
    if registration.get("api_base_url") or (registration.get("connection_url") or {}).get("api_base_url"):
        return resolved.base_url
    return None


if __name__ == "__main__":
    raise SystemExit(main())
