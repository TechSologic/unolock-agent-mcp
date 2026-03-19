---
name: unolock-agent-access
description: Guides an AI agent through connecting to a user's UnoLock Safe through the UnoLock agent-access skill, which uses the local UnoLock MCP and then works in the current Space with notes, checklists, and files.
---

# UnoLock Agent Access

Use this skill when a user wants to give their agent access to a UnoLock Safe.
This skill uses a local UnoLock `stdio` MCP that runs on the user's device. The MCP guides setup and then provides ongoing access to Spaces, notes, checklists, and Cloud files.

## Workflow

1. Load this skill if the host supports skills.
2. Use `npx -y @techsologic/unolock-agent-mcp@latest` as the MCP command.
3. Start the MCP normally over `stdio`.
4. On a fresh host, allow extra time for the first start.
5. Follow the MCP's directions.
6. Use the current Space for normal note, checklist, and file work.

## MCP Launch

- The host runs `npx -y @techsologic/unolock-agent-mcp@latest` as the MCP command.
- The host writes MCP JSON-RPC to `stdin` and reads MCP JSON-RPC from `stdout`.
- Launch it with no UnoLock-specific arguments.

## How To Use The MCP

1. Launch UnoLock as the local `stdio` MCP command.
2. Initialize it like any other MCP server.
3. Use normal MCP tool discovery and tool calls.
4. If setup is needed, call `unolock_link_agent_key` with the Agent Key URL and PIN.
5. If the MCP later needs the PIN again, call `unolock_set_agent_pin`.
6. Use Space tools to inspect or switch the current Space when needed.
7. Use note, checklist, and file tools for normal work.
8. Let the MCP tell you the next concrete step instead of inventing a side flow.

## Available MCP Calls

- `unolock_link_agent_key`: give the MCP the one-time Agent Key URL and the PIN for first setup on the current device
- `unolock_set_agent_pin`: give the MCP the PIN again after restart or re-authentication
- `unolock_list_spaces`, `unolock_get_current_space`, `unolock_set_current_space`: discover and switch the current Space
- `unolock_list_notes`, `unolock_create_note`, `unolock_update_note`, `unolock_append_note`: read and write notes
- `unolock_list_checklists`, `unolock_create_checklist`, `unolock_set_checklist_item_done`, `unolock_add_checklist_item`, `unolock_remove_checklist_item`: read and write checklists
- `unolock_list_files`, `unolock_get_file`, `unolock_download_file`, `unolock_upload_file`, `unolock_rename_file`, `unolock_replace_file`, `unolock_delete_file`: read and manage Cloud files
- `unolock_get_record` and `unolock_rename_record`: inspect or rename an existing note or checklist

Use those calls by purpose to work through setup and then normal Safe access.

## Key Rules

- Follow the MCP's directions.
- Give the MCP the Agent Key URL and PIN when it asks for setup.
- Give the MCP the PIN again only after restart or re-authentication when it asks for it.
- Keep the PIN in MCP process memory only.

## User-Facing Model

- The user manages the Agent Key in the UnoLock Safe web app.
- The user gives the agent a one-time Agent Key URL and the PIN.
- The local UnoLock MCP uses those to set up access on the current device.
- After that, ongoing access uses the registered local Agent Key.
