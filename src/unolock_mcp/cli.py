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
from unolock_mcp.mcp.server import create_mcp_server


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
    mcp_parser.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Register or authenticate the UnoLock agent using the local registration store.",
        description="Use the stored UnoLock connection URL and optional PIN to register/authenticate the agent.",
    )
    bootstrap_parser.add_argument("--connection-url", default=None)
    bootstrap_parser.add_argument("--pin", default=None)
    bootstrap_parser.add_argument("--list-records", action="store_true")

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

    subparsers.add_parser(
        "config-check",
        help="Show the resolved UnoLock runtime configuration and missing values.",
        description="Inspect UnoLock MCP configuration sources from arguments, environment, config file, and repo auto-discovery.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "probe"

    if command == "mcp":
        server = create_mcp_server()
        server.run(args.transport)
        return 0

    if command == "config-check":
        registration = RegistrationStore().load()
        resolved = resolve_unolock_config(
            base_url=args.base_url or registration.api_base_url,
            transparency_origin=args.transparency_origin or registration.transparency_origin,
            app_version=args.app_version,
            signing_public_key_b64=args.signing_public_key,
        )
        payload = {
            "ok": resolved.is_complete(),
            "mcp_version": MCP_VERSION,
            "config_file": str(default_config_path()),
            "resolved": {
                "base_url": resolved.base_url,
                "transparency_origin": resolved.transparency_origin,
                "app_version": resolved.app_version,
                "signing_public_key_b64": "<redacted>" if resolved.signing_public_key_b64 else None,
            },
            "sources": resolved.sources,
            "missing": [
                key for key, value in {
                    "app_version": resolved.app_version,
                    "signing_public_key_b64": resolved.signing_public_key_b64,
                }.items() if not value
            ],
            "guidance": (
                "In the normal flow, submit a UnoLock agent key connection URL and let the MCP derive the server "
                "origin, app version, and PQ validation key automatically. Use environment variables or the config "
                "file only for overrides and custom deployments."
            ),
        }
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1

    def resolve_runtime_config(registration_store: RegistrationStore) -> UnoLockConfig:
        registration = registration_store.load()
        return load_unolock_config(
            base_url=args.base_url or registration.api_base_url,
            transparency_origin=args.transparency_origin or registration.transparency_origin,
            app_version=args.app_version,
            signing_public_key_b64=args.signing_public_key,
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
            and result.get("session", {}).get("session_id")
        ):
            api_client = UnoLockApiClient(flow_client, session_store)
            records_client = UnoLockReadonlyRecordsClient(api_client, agent_auth)
            result["records"] = records_client.list_records(result["session"]["session_id"])
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") and result.get("authorized") else 1

    if command == "disconnect":
        session_store = SessionStore()
        registration_store = RegistrationStore()
        agent_auth = AgentAuthClient(None, session_store, registration_store)
        result = agent_auth.disconnect()
        print(json.dumps(result, indent=2))
        return 0

    if command == "tpm-diagnose":
        session_store = SessionStore()
        registration_store = RegistrationStore()
        agent_auth = AgentAuthClient(None, session_store, registration_store)
        diagnostics = agent_auth.tpm_diagnostics()
        print(json.dumps(diagnostics, indent=2))
        return 0 if diagnostics.get("production_ready") else 1

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
    return main(["mcp", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
