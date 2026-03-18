# MCP Tool Catalog

This document describes the current normal UnoLock Agent MCP surface.

## Normal agent model

The normal agent workflow is:

1. Launch the UnoLock local daemon/CLI, or launch the local `stdio` MCP from an external host if one is already in use.
2. Ask for the one-time UnoLock Agent Key URL only if the MCP says registration is needed.
3. Ask for the PIN only if the MCP says the key uses one.
4. Let the MCP guide registration or authentication.
5. Use the current Space for normal read, write, and file work.

For direct local use, the preferred commands are:

```bash
unolock-agent-mcp start
unolock-agent-mcp call unolock_get_registration_status
```

The normal agent workflow should not require:

* `session_id`
* `space_id`
* base URLs
* signing keys
* app versions

The MCP now keeps one current Space. If no current Space was selected yet, it will auto-select the first accessible Space and use that as the default.

## Primary first-use tools

### `unolock_get_registration_status`

Purpose:
Return the MCP's current state and the next thing the agent should do.

Important fields:

* `registration_state`
* `registered`
* `recommended_next_action`
* `guidance`
* `has_agent_pin`
* `current_space_id`
* `current_space_name`
* `explanation_resources`

Typical next actions:

* `ask_for_agent_key_url`
* `start_registration`
* `ask_for_agent_pin`
* `authenticate_agent`
* `choose_current_space`
* `ready`

### `unolock_submit_agent_bootstrap`

Purpose:
Store the one-time Agent Key URL and an optional PIN together.

Arguments:

* `connection_url: str`
* `pin: str | null`

Notes:

* The input is the one-time `#/agent-register/...` Agent Key URL.
* The Agent Key URL is for local enrollment only, not ongoing access.
* If the key does not use a PIN, omit it.

### `unolock_bootstrap_agent`

Purpose:
Run the normal one-shot registration/authentication path.

Notes:

* If the MCP is unregistered and already has a stored Agent Key URL, this enrolls the local MCP.
* If the MCP is already registered, this authenticates it.
* If the MCP needs a PIN, it will return a concrete blocker instead of making the agent guess.

### `unolock_set_agent_pin`

Purpose:
Store the Agent Key PIN in MCP process memory only.

Arguments:

* `pin: str`

Notes:

* PINs are strings, not numbers.
* Valid characters are `0-9` and `a-f`.
* The MCP can resume pending auth or data work after the PIN is provided.

## Current Space tools

### `unolock_list_spaces`

Purpose:
List the Spaces visible to the current Agent Key.

Important response fields:

* `spaces`
* `current_space_id`

Notes:

* If no current Space exists yet, the MCP auto-selects the first accessible Space.
* Each Space entry indicates whether it is the current Space.
* If the Agent Key currently has access to zero Spaces, the MCP returns `no_accessible_spaces`.

### `unolock_get_current_space`

Purpose:
Return the current default Space used by normal operations.

Notes:

* If no Space was selected yet, the MCP auto-selects the first accessible Space.
* If the Agent Key currently has access to zero Spaces, the MCP returns `no_accessible_spaces`.

### `unolock_set_current_space`

Purpose:
Switch the MCP's current default Space.

Arguments:

* `space_id: int`

### `unolock_clear_current_space`

Purpose:
Clear the remembered current Space.

Notes:

* The next normal read or write operation will auto-select the first accessible Space again.

## Read tools

These tools use the current Space by default and include the `space_id` they actually used in their responses.

### `unolock_list_records`

Arguments:

* `kind: str = "all"`
* `pinned: bool | null = None`
* `label: str | null = None`

Notes:

* `kind` may be `all`, `note`, or `checklist`.

### `unolock_list_notes`

Arguments:

* `pinned: bool | null = None`
* `label: str | null = None`

### `unolock_list_checklists`

Arguments:

* `pinned: bool | null = None`
* `label: str | null = None`

### `unolock_get_record`

Arguments:

* `record_ref: str`

Notes:

* Use this before updates so the MCP has the latest version and archive state.

### `unolock_list_files`

Purpose:
List Cloud files in the current Space.

Notes:

* Only `Cloud` archives are exposed.
* `Local` and `Msg` archives are intentionally excluded.

### `unolock_get_file`

Arguments:

* `archive_id: str`

### `unolock_download_file`

Arguments:

* `archive_id: str`
* `output_path: str`
* `overwrite: bool = False`

Notes:

* The MCP reconstructs multipart Cloud archives before writing plaintext to the local filesystem.

## Write tools

These tools either use the current Space automatically or act on an already identified record or file.

### `unolock_create_note`

Arguments:

* `title: str`
* `text: str`

### `unolock_update_note`

Arguments:

* `record_ref: str`
* `expected_version: int`
* `title: str`
* `text: str`

### `unolock_append_note`

Arguments:

* `record_ref: str`
* `expected_version: int`
* `append_text: str`

### `unolock_rename_record`

Arguments:

* `record_ref: str`
* `expected_version: int`
* `title: str`

### `unolock_create_checklist`

Arguments:

* `title: str`
* `items: list[str] | null = None`

### `unolock_set_checklist_item_done`

Arguments:

* `record_ref: str`
* `expected_version: int`
* `item_id: int`
* `done: bool`

### `unolock_add_checklist_item`

Arguments:

* `record_ref: str`
* `expected_version: int`
* `text: str`

### `unolock_remove_checklist_item`

Arguments:

* `record_ref: str`
* `expected_version: int`
* `item_id: int`

### `unolock_upload_file`

Arguments:

* `local_path: str`
* `name: str | null = None`
* `mime_type: str | null = None`

Notes:

* Upload uses the current Space automatically.
* Only `Cloud` files are supported.

### `unolock_rename_file`

Arguments:

* `archive_id: str`
* `name: str`

### `unolock_replace_file`

Arguments:

* `archive_id: str`
* `local_path: str`
* `name: str | null = None`
* `mime_type: str | null = None`

### `unolock_delete_file`

Arguments:

* `archive_id: str`

## Explanatory resources

Use these when the user needs plain-language help instead of improvised agent wording:

* `unolock://usage/about`
* `unolock://usage/security-model`
* `unolock://usage/quickstart`
* `unolock://usage/updates`

## Update and diagnostics tools

### `unolock_get_update_status`

Purpose:
Return runner-friendly update guidance.

### `unolock_get_tpm_diagnostics`

Purpose:
Return the active host key-storage provider and assurance guidance.

## Advanced/debug tools

These are not the preferred normal workflow:

* `unolock_submit_connection_url`
* `unolock_clear_connection_url`
* `unolock_start_registration_from_connection_url`
* `unolock_continue_agent_session`
* `unolock_authenticate_agent`
* `unolock_disconnect_agent`

Agents should ignore these unless the normal guided workflow cannot complete the task.
