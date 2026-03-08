from __future__ import annotations

import argparse
import json
import sys

from unolock_mcp.api.client import UnoLockApiClient
from unolock_mcp.api.records import UnoLockReadonlyRecordsClient
from unolock_mcp.auth.agent_auth import AgentAuthClient
from unolock_mcp.auth.flow_client import UnoLockFlowClient
from unolock_mcp.auth.local_probe import LocalServerProbe
from unolock_mcp.auth.registration_store import RegistrationStore
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.config import load_unolock_config
from unolock_mcp.mcp.server import create_mcp_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UnoLock agent prototype commands.")
    subparsers = parser.add_subparsers(dest="command", required=False)

    probe_parser = subparsers.add_parser(
        "probe",
        help="Run the UnoLock local-server PQ probe.",
        description="Run the UnoLock agent prototype probe against a live local server.",
    )
    probe_parser.add_argument("--base-url", default=None)
    probe_parser.add_argument("--flow", default="access")
    probe_parser.add_argument("--app-version", default=None)
    probe_parser.add_argument("--signing-public-key", default=None)

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

    diagnose_parser = subparsers.add_parser(
        "tpm-diagnose",
        help="Diagnose TPM/vTPM readiness for the UnoLock agent MCP.",
        description="Inspect the active TPM DAO and host TPM/vTPM signals and print advice.",
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

    config = load_unolock_config(
        base_url=getattr(args, "base_url", None),
        app_version=getattr(args, "app_version", None),
        signing_public_key_b64=getattr(args, "signing_public_key", None),
    )

    probe = LocalServerProbe(
        base_url=config.base_url,
        app_version=config.app_version,
        signing_public_key_b64=config.signing_public_key_b64,
    )
    if command == "bootstrap":
        flow_client = UnoLockFlowClient(config)
        session_store = SessionStore()
        registration_store = RegistrationStore()
        if args.connection_url:
            registration_store.set_connection_url(args.connection_url)
        agent_auth = AgentAuthClient(flow_client, session_store, registration_store)
        if args.pin:
            agent_auth.set_agent_pin(args.pin)

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

    if command == "tpm-diagnose":
        flow_client = UnoLockFlowClient(config)
        session_store = SessionStore()
        registration_store = RegistrationStore()
        agent_auth = AgentAuthClient(flow_client, session_store, registration_store)
        diagnostics = agent_auth.tpm_diagnostics()
        print(json.dumps(diagnostics, indent=2))
        return 0 if diagnostics.get("production_ready") else 1

    result = probe.run(flow=getattr(args, "flow", "access"))
    print(LocalServerProbe.to_json(result))
    return 0


def probe_main() -> int:
    return main(["probe", *sys.argv[1:]])


def mcp_main() -> int:
    return main(["mcp", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
