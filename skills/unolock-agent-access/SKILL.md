---
name: unolock-agent-access
description: Use when an AI agent needs the exact happy path for connecting to a user's UnoLock Safe through the local UnoLock MCP and then working with Spaces, notes, checklists, and files without wandering into support/debug flows.
---

# UnoLock Agent Access

Use this skill when a user wants to give their agent access to a UnoLock Safe.

## Happy Path

1. Run the UnoLock executable as a local `stdio` MCP.
2. On a fresh host, allow extra time for the first start.
3. Ask the user for the one-time UnoLock Agent Key URL and PIN together.
4. Call `unolock_link_agent_key`.
5. Call `unolock_list_spaces`.
6. If needed, call `unolock_set_current_space`.
7. Use the normal note, checklist, and file tools.

## Key Rules

- Follow the MCP's directions.
- Use the current Space by default.
- Use `unolock_set_agent_pin` only after restart or re-authentication when the MCP asks for the PIN again.
- Keep the PIN in MCP process memory only.
- Use `unolock_link_agent_key`, not support/debug tools, for the normal setup flow.

## User-Facing Model

- The user manages the Agent Key in the UnoLock Safe web app.
- The user gives the agent a one-time Agent Key URL and the PIN.
- The local UnoLock MCP uses those to set up access on the current device.
- After that, ongoing access uses the registered local Agent Key.

## Preferred Tools

- `unolock_link_agent_key`
- `unolock_list_spaces`
- `unolock_get_current_space`
- `unolock_set_current_space`
- `unolock_list_records`
- `unolock_list_notes`
- `unolock_list_checklists`
- `unolock_list_files`
- `unolock_get_record`
- `unolock_get_file`
- `unolock_download_file`
- `unolock_upload_file`
- `unolock_create_note`
- `unolock_create_checklist`
- `unolock_update_note`
- `unolock_append_note`
- `unolock_set_checklist_item_done`

