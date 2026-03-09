from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from unolock_mcp.api.client import UnoLockApiClient
from unolock_mcp.api.records import UnoLockReadonlyRecordsClient
from unolock_mcp.auth.agent_auth import AgentAuthClient
from unolock_mcp.auth.flow_client import UnoLockFlowClient
from unolock_mcp.auth.registration_store import RegistrationStore
from unolock_mcp.auth.session_store import SessionStore
from unolock_mcp.config import load_unolock_config
from unolock_mcp.mcp.server import _registration_status_payload


def _load_connection_url(artifact_path: Path) -> str:
    payload = json.loads(artifact_path.read_text(encoding="utf8"))
    registration = payload.get("registration")
    if isinstance(registration, dict):
        connection_url = registration.get("connectionUrl")
        if isinstance(connection_url, str) and connection_url:
            return connection_url
    connection_url = payload.get("connectionUrl")
    if isinstance(connection_url, str) and connection_url:
        return connection_url
    raise ValueError(f"Could not find connectionUrl in artifact: {artifact_path}")


def _build_runtime():
    config = load_unolock_config()
    flow_client = UnoLockFlowClient(config)
    session_store = SessionStore()
    registration_store = RegistrationStore()
    agent_auth = AgentAuthClient(flow_client, session_store, registration_store)
    api_client = UnoLockApiClient(flow_client, session_store)
    records_client = UnoLockReadonlyRecordsClient(api_client, agent_auth)
    return session_store, registration_store, agent_auth, records_client


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_live_local_readonly_flow(artifact_path: Path, pin: str, minimum_records: int) -> dict[str, Any]:
    connection_url = _load_connection_url(artifact_path)

    _, registration_store, agent_auth, records_client = _build_runtime()
    disconnect_result = agent_auth.disconnect()
    _assert(disconnect_result.get("ok") is True, "Failed to disconnect local MCP state before E2E run")

    submit_result = agent_auth.submit_connection_url(connection_url)
    _assert(submit_result.get("access_id"), "Submitted connection URL did not yield an access_id")

    agent_auth.set_agent_pin(pin)
    registration_result = agent_auth.start_registration_from_stored_url()
    _assert(registration_result.get("ok") is True, "Registration flow did not complete successfully")
    _assert(registration_result.get("completed") is True, "Registration flow did not complete")

    auth_result = agent_auth.authenticate_registered_agent()
    _assert(auth_result.get("ok") is True, "Initial post-registration authentication failed")
    _assert(auth_result.get("authorized") is True, "Initial post-registration auth did not authorize")
    session_id = auth_result.get("session", {}).get("session_id")
    _assert(isinstance(session_id, str) and session_id, "Missing authenticated session_id after registration")

    spaces = records_client.list_spaces(session_id)
    records = records_client.list_records(session_id)
    _assert(spaces.get("count", 0) >= 1, "Expected at least one visible space")
    _assert(records.get("count", 0) >= minimum_records, f"Expected at least {minimum_records} visible records")

    restart_session_store, restart_registration_store, restart_agent_auth, restart_records_client = _build_runtime()
    restart_status = _registration_status_payload(restart_registration_store, restart_session_store, restart_agent_auth)
    _assert(restart_status.get("registered") is True, "Agent registration did not persist across restart simulation")
    _assert(
        restart_status.get("recommended_next_action") == "authenticate_or_set_pin",
        "Restart status did not require PIN re-authentication",
    )

    restart_agent_auth.set_agent_pin(pin)
    restart_auth_result = restart_agent_auth.authenticate_registered_agent()
    _assert(restart_auth_result.get("ok") is True, "Restarted authentication failed")
    _assert(restart_auth_result.get("authorized") is True, "Restarted authentication did not authorize")
    restart_session_id = restart_auth_result.get("session", {}).get("session_id")
    _assert(isinstance(restart_session_id, str) and restart_session_id, "Missing restarted authenticated session_id")

    restart_spaces = restart_records_client.list_spaces(restart_session_id)
    restart_records = restart_records_client.list_records(restart_session_id)
    _assert(restart_spaces.get("count") == spaces.get("count"), "Visible space count changed after restart")
    _assert(restart_records.get("count") == records.get("count"), "Visible record count changed after restart")

    return {
        "ok": True,
        "artifact_file": str(artifact_path),
        "access_id": submit_result.get("access_id"),
        "initial_spaces": spaces,
        "initial_records": {
            "count": records.get("count"),
            "titles": [record.get("title") for record in records.get("records", [])],
        },
        "restart_status": {
            "recommended_next_action": restart_status.get("recommended_next_action"),
            "guidance": restart_status.get("guidance"),
        },
        "restart_records": {
            "count": restart_records.get("count"),
            "titles": [record.get("title") for record in restart_records.get("records", [])],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local UnoLock agent read-only end-to-end regression.")
    parser.add_argument("--artifact-file", required=True, help="Path to the Playwright-generated agent bootstrap artifact JSON.")
    parser.add_argument("--pin", default="0123", help="Agent PIN for the generated local test Safe.")
    parser.add_argument("--minimum-records", type=int, default=1, help="Minimum number of visible records expected.")
    args = parser.parse_args()

    result = run_live_local_readonly_flow(
        artifact_path=Path(args.artifact_file),
        pin=args.pin,
        minimum_records=args.minimum_records,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
