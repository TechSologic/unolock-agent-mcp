from __future__ import annotations

import argparse
import json
import sys
from typing import Any

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
    DEFAULT_DAEMON_CALL_TIMEOUT,
    DEFAULT_DAEMON_START_TIMEOUT,
    DEFAULT_DAEMON_STOP_TIMEOUT,
    LocalHostError,
    call_tool as call_daemon_tool,
    ensure_daemon_running,
    list_tools as list_daemon_tools,
    proxy_stdio_to_daemon,
    serve_local_daemon_forever,
    stop_daemon,
    get_daemon_status,
)
from unolock_mcp.update import get_update_status


def _parse_bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected a boolean value like true or false")


CLI_TOOL_COMMANDS: dict[str, dict[str, Any]] = {
    "link-agent-key": {
        "tool": "unolock_link_agent_key",
        "help": "Link a one-time UnoLock Agent Key URL and PIN to this device.",
        "description": "Set up UnoLock access on this device from the one-time Agent Key URL and PIN.",
        "arguments": [
            (("connection_url",), {"help": "One-time UnoLock Agent Key URL."}),
            (("pin",), {"help": "Agent PIN as a string using only 0-9 and a-f."}),
        ],
    },
    "set-agent-pin": {
        "tool": "unolock_set_agent_pin",
        "help": "Set the in-memory UnoLock agent PIN.",
        "description": "Store the UnoLock agent PIN in MCP process memory for authentication.",
        "arguments": [
            (("pin",), {"help": "Agent PIN as a string using only 0-9 and a-f."}),
        ],
    },
    "list-spaces": {
        "tool": "unolock_list_spaces",
        "help": "List accessible UnoLock spaces.",
        "description": "List accessible UnoLock spaces and current-space metadata.",
        "arguments": [],
    },
    "get-current-space": {
        "tool": "unolock_get_current_space",
        "help": "Show the current UnoLock space.",
        "description": "Show the current UnoLock space used for normal operations.",
        "arguments": [],
    },
    "set-current-space": {
        "tool": "unolock_set_current_space",
        "help": "Set the current UnoLock space.",
        "description": "Select the UnoLock space used by default for normal operations.",
        "arguments": [
            (("space_id",), {"type": int, "help": "Space ID to select."}),
        ],
    },
    "list-records": {
        "tool": "unolock_list_records",
        "help": "List notes and checklists in the current space.",
        "description": "List notes and checklists in the current UnoLock space.",
        "arguments": [
            (("--kind",), {"choices": ["all", "note", "checklist"], "default": "all"}),
            (("--pinned",), {"action": "store_true"}),
            (("--label",), {"default": None}),
        ],
    },
    "list-notes": {
        "tool": "unolock_list_notes",
        "help": "List notes in the current space.",
        "description": "List notes in the current UnoLock space.",
        "arguments": [
            (("--pinned",), {"action": "store_true"}),
            (("--label",), {"default": None}),
        ],
    },
    "list-checklists": {
        "tool": "unolock_list_checklists",
        "help": "List checklists in the current space.",
        "description": "List checklists in the current UnoLock space.",
        "arguments": [
            (("--pinned",), {"action": "store_true"}),
            (("--label",), {"default": None}),
        ],
    },
    "get-record": {
        "tool": "unolock_get_record",
        "help": "Get one note or checklist by record_ref.",
        "description": "Fetch one UnoLock note or checklist by record_ref.",
        "arguments": [
            (("record_ref",), {"help": "record_ref from list-records output."}),
        ],
    },
    "create-note": {
        "tool": "unolock_create_note",
        "help": "Create a note in the current space.",
        "description": "Create a note in the current UnoLock space.",
        "arguments": [
            (("title",), {"help": "Note title."}),
            (("text",), {"help": "Note body text."}),
        ],
    },
    "update-note": {
        "tool": "unolock_update_note",
        "help": "Update an existing note.",
        "description": "Update an existing UnoLock note by record_ref and expected version.",
        "arguments": [
            (("record_ref",), {"help": "record_ref from get-record/list-notes output."}),
            (("expected_version",), {"type": int, "help": "Expected current note version."}),
            (("title",), {"help": "Updated note title."}),
            (("text",), {"help": "Updated note body text."}),
        ],
    },
    "append-note": {
        "tool": "unolock_append_note",
        "help": "Append text to an existing note.",
        "description": "Append text to an existing UnoLock note by record_ref and expected version.",
        "arguments": [
            (("record_ref",), {"help": "record_ref from get-record/list-notes output."}),
            (("expected_version",), {"type": int, "help": "Expected current note version."}),
            (("append_text",), {"help": "Text to append."}),
        ],
    },
    "rename-record": {
        "tool": "unolock_rename_record",
        "help": "Rename a note or checklist.",
        "description": "Rename an existing UnoLock note or checklist.",
        "arguments": [
            (("record_ref",), {"help": "record_ref from get-record/list-records output."}),
            (("expected_version",), {"type": int, "help": "Expected current record version."}),
            (("title",), {"help": "New title."}),
        ],
    },
    "create-checklist": {
        "tool": "unolock_create_checklist",
        "help": "Create a checklist in the current space.",
        "description": "Create a checklist in the current UnoLock space.",
        "arguments": [
            (("title",), {"help": "Checklist title."}),
            (("--items",), {"default": "[]", "help": "JSON array of checklist items."}),
        ],
    },
    "set-checklist-item-done": {
        "tool": "unolock_set_checklist_item_done",
        "help": "Set one checklist item's done state.",
        "description": "Set one checklist item's done state.",
        "arguments": [
            (("record_ref",), {"help": "record_ref from get-record/list-checklists output."}),
            (("expected_version",), {"type": int, "help": "Expected current checklist version."}),
            (("item_id",), {"type": int, "help": "Checklist item ID."}),
            (("done",), {"type": _parse_bool, "help": "true or false"}),
        ],
    },
    "add-checklist-item": {
        "tool": "unolock_add_checklist_item",
        "help": "Add an item to a checklist.",
        "description": "Add an item to an existing checklist.",
        "arguments": [
            (("record_ref",), {"help": "record_ref from get-record/list-checklists output."}),
            (("expected_version",), {"type": int, "help": "Expected current checklist version."}),
            (("text",), {"help": "Checklist item text."}),
        ],
    },
    "remove-checklist-item": {
        "tool": "unolock_remove_checklist_item",
        "help": "Remove an item from a checklist.",
        "description": "Remove an item from an existing checklist.",
        "arguments": [
            (("record_ref",), {"help": "record_ref from get-record/list-checklists output."}),
            (("expected_version",), {"type": int, "help": "Expected current checklist version."}),
            (("item_id",), {"type": int, "help": "Checklist item ID."}),
        ],
    },
    "list-files": {
        "tool": "unolock_list_files",
        "help": "List Cloud files in the current space.",
        "description": "List UnoLock Cloud files in the current space.",
        "arguments": [],
    },
    "get-file": {
        "tool": "unolock_get_file",
        "help": "Get metadata for one Cloud file.",
        "description": "Get metadata for one UnoLock Cloud file by archive_id.",
        "arguments": [
            (("archive_id",), {"help": "archive_id from list-files output."}),
        ],
    },
    "download-file": {
        "tool": "unolock_download_file",
        "help": "Download a Cloud file to the local filesystem.",
        "description": "Download one UnoLock Cloud file to a local path.",
        "arguments": [
            (("archive_id",), {"help": "archive_id from list-files output."}),
            (("output_path",), {"help": "Target file path or target directory."}),
            (("--overwrite",), {"action": "store_true"}),
        ],
    },
    "upload-file": {
        "tool": "unolock_upload_file",
        "help": "Upload a local file into the current space.",
        "description": "Upload a local file into the current UnoLock space.",
        "arguments": [
            (("local_path",), {"help": "Local file path to upload."}),
            (("--title",), {"default": None, "help": "Uploaded file name override."}),
            (("--mime-type",), {"dest": "mime_type", "default": None}),
        ],
    },
    "rename-file": {
        "tool": "unolock_rename_file",
        "help": "Rename a Cloud file.",
        "description": "Rename one UnoLock Cloud file.",
        "arguments": [
            (("archive_id",), {"help": "archive_id from get-file/list-files output."}),
            (("name",), {"help": "New file name."}),
        ],
    },
    "replace-file": {
        "tool": "unolock_replace_file",
        "help": "Replace a Cloud file with local content.",
        "description": "Replace an existing UnoLock Cloud file from a local path.",
        "arguments": [
            (("archive_id",), {"help": "archive_id from get-file/list-files output."}),
            (("local_path",), {"help": "Local file path with replacement content."}),
            (("--title",), {"default": None, "help": "Replacement file name override."}),
            (("--mime-type",), {"dest": "mime_type", "default": None}),
        ],
    },
    "delete-file": {
        "tool": "unolock_delete_file",
        "help": "Delete a Cloud file.",
        "description": "Delete one UnoLock Cloud file by archive_id.",
        "arguments": [
            (("archive_id",), {"help": "archive_id from get-file/list-files output."}),
        ],
    },
}


def _add_cli_tool_subcommands(subparsers) -> None:
    for command_name, spec in CLI_TOOL_COMMANDS.items():
        subparser = subparsers.add_parser(
            command_name,
            help=spec["help"],
            description=spec["description"],
        )
        for names, kwargs in spec["arguments"]:
            subparser.add_argument(*names, **kwargs)
        subparser.set_defaults(cli_tool_command=command_name)


def _cli_tool_request_from_args(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    command = getattr(args, "cli_tool_command", None)
    if command is None:
        raise ValueError("missing cli tool command")
    if command == "link-agent-key":
        return "unolock_link_agent_key", {"connection_url": args.connection_url, "pin": args.pin}
    if command == "set-agent-pin":
        return "unolock_set_agent_pin", {"pin": args.pin}
    if command == "list-spaces":
        return "unolock_list_spaces", {}
    if command == "get-current-space":
        return "unolock_get_current_space", {}
    if command == "set-current-space":
        return "unolock_set_current_space", {"space_id": args.space_id}
    if command == "list-records":
        return "unolock_list_records", {"kind": args.kind, "pinned": args.pinned or None, "label": args.label}
    if command == "list-notes":
        return "unolock_list_notes", {"pinned": args.pinned or None, "label": args.label}
    if command == "list-checklists":
        return "unolock_list_checklists", {"pinned": args.pinned or None, "label": args.label}
    if command == "get-record":
        return "unolock_get_record", {"record_ref": args.record_ref}
    if command == "create-note":
        return "unolock_create_note", {"title": args.title, "text": args.text}
    if command == "update-note":
        return "unolock_update_note", {
            "record_ref": args.record_ref,
            "expected_version": args.expected_version,
            "title": args.title,
            "text": args.text,
        }
    if command == "append-note":
        return "unolock_append_note", {
            "record_ref": args.record_ref,
            "expected_version": args.expected_version,
            "append_text": args.append_text,
        }
    if command == "rename-record":
        return "unolock_rename_record", {
            "record_ref": args.record_ref,
            "expected_version": args.expected_version,
            "title": args.title,
        }
    if command == "create-checklist":
        try:
            items = json.loads(args.items)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON for --items: {exc}") from exc
        if not isinstance(items, list):
            raise ValueError("--items must decode to a JSON array.")
        return "unolock_create_checklist", {"title": args.title, "items": items}
    if command == "set-checklist-item-done":
        return "unolock_set_checklist_item_done", {
            "record_ref": args.record_ref,
            "expected_version": args.expected_version,
            "item_id": args.item_id,
            "done": args.done,
        }
    if command == "add-checklist-item":
        return "unolock_add_checklist_item", {
            "record_ref": args.record_ref,
            "expected_version": args.expected_version,
            "text": args.text,
        }
    if command == "remove-checklist-item":
        return "unolock_remove_checklist_item", {
            "record_ref": args.record_ref,
            "expected_version": args.expected_version,
            "item_id": args.item_id,
        }
    if command == "list-files":
        return "unolock_list_files", {}
    if command == "get-file":
        return "unolock_get_file", {"archive_id": args.archive_id}
    if command == "download-file":
        return "unolock_download_file", {
            "archive_id": args.archive_id,
            "output_path": args.output_path,
            "overwrite": args.overwrite,
        }
    if command == "upload-file":
        return "unolock_upload_file", {
            "local_path": args.local_path,
            "title": args.title,
            "mime_type": args.mime_type,
        }
    if command == "rename-file":
        return "unolock_rename_file", {"archive_id": args.archive_id, "name": args.name}
    if command == "replace-file":
        return "unolock_replace_file", {
            "archive_id": args.archive_id,
            "local_path": args.local_path,
            "title": args.title,
            "mime_type": args.mime_type,
        }
    if command == "delete-file":
        return "unolock_delete_file", {"archive_id": args.archive_id}
    raise ValueError(f"Unknown CLI tool command: {command}")


def _print_cli_payload(payload: dict[str, Any]) -> int:
    if payload.get("ok", True) and "result" in payload:
        result = payload["result"]
        print(json.dumps(result, indent=2))
        if isinstance(result, dict):
            if result.get("blocked"):
                return 1
            if result.get("ok") is False:
                return 1
        return 0
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok", True) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UnoLock Agent commands.")
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
    host_start_parser.set_defaults(timeout=DEFAULT_DAEMON_START_TIMEOUT)

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
    host_stop_parser.set_defaults(timeout=DEFAULT_DAEMON_STOP_TIMEOUT)

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
    host_call_parser.set_defaults(timeout=DEFAULT_DAEMON_CALL_TIMEOUT)

    _add_cli_tool_subcommands(subparsers)

    subparsers.add_parser(
        "_daemon",
        help=argparse.SUPPRESS,
        description=argparse.SUPPRESS,
    )

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Advanced/manual: register or authenticate the UnoLock agent using the local registration store.",
        description=(
            "Advanced/manual path. Use the stored UnoLock connection URL and PIN to "
            "register/authenticate the agent. For the normal customer or agent flow, prefer an "
            "MCP host and the MCP tools instead of calling this CLI command directly."
        ),
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
        help="Run a one-shot UnoLock Agent readiness check.",
        description=(
            "Check whether this host is suitable for UnoLock Agent bootstrap, summarize the detected "
            "environment, and report the next recommended action."
        ),
    )
    self_test_parser.add_argument("--json", action="store_true", help="Print the self-test result as JSON.")

    update_parser = subparsers.add_parser(
        "check-update",
        help="Check whether a newer UnoLock Agent release is available.",
        description=(
            "Check the installed UnoLock Agent version against the latest GitHub Release and print "
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
        try:
            return proxy_stdio_to_daemon(auto_start=True, timeout=None)
        except LocalHostError as exc:
            print(json.dumps({"ok": False, "reason": "daemon_proxy_failed", "message": str(exc)}, indent=2))
            return 1

    if command == "_daemon":
        return serve_local_daemon_forever()

    if command == "start":
        try:
            payload = ensure_daemon_running(timeout=getattr(args, "timeout", DEFAULT_DAEMON_START_TIMEOUT))
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
            payload = stop_daemon(timeout=getattr(args, "timeout", DEFAULT_DAEMON_STOP_TIMEOUT))
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
                timeout=getattr(args, "timeout", DEFAULT_DAEMON_CALL_TIMEOUT),
            )
        except LocalHostError as exc:
            print(json.dumps({"ok": False, "reason": "daemon_call_failed", "message": str(exc)}, indent=2))
            return 1
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("ok", True) else 1

    if getattr(args, "cli_tool_command", None):
        try:
            tool_name, tool_args = _cli_tool_request_from_args(args)
        except ValueError as exc:
            print(json.dumps({"ok": False, "reason": "invalid_input", "message": str(exc)}, indent=2))
            return 1
        try:
            payload = call_daemon_tool(
                tool_name,
                tool_args,
                auto_start=True,
                timeout=DEFAULT_DAEMON_CALL_TIMEOUT,
            )
        except LocalHostError as exc:
            print(json.dumps({"ok": False, "reason": "daemon_call_failed", "message": str(exc)}, indent=2))
            return 1
        return _print_cli_payload(payload)

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
            "and PIN, then start registration."
        )

    ok = bool(diagnostics.get("production_ready"))
    if not ok:
        next_action = "review_tpm_diagnostics_and_decide"
        guidance = (
            "This host could not satisfy UnoLock's preferred device-bound key-storage requirements. Review the "
            "TPM/environment diagnostics and decide whether reduced-assurance operation on this host is acceptable "
            "for your Safe data before continuing."
        )

    summary = str(diagnostics.get("summary") or "UnoLock Agent self-test completed.")
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
