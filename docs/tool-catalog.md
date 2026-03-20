# MCP Tool Catalog

This document describes the current normal UnoLock Agent surface.

## Normal agent model

The normal agent workflow is:

1. Launch the UnoLock executable as a local `stdio` MCP.
2. Allow extra time on the very first start on a fresh host, because local cryptographic code may need to be compiled or prepared.
3. Ask for the one-time UnoLock Agent Key URL and PIN together when the MCP asks for setup.
4. Follow the MCP's directions.
5. Use the current Space for normal read, write, and file work.

The MCP now keeps one current Space. If no current Space was selected yet, it auto-selects the first accessible Space and uses that as the default.

### `unolock_register`

Purpose:
Store the one-time Agent Key URL and PIN together.

Arguments:

* `connection_url: str`
* `pin: str`

Notes:

* The input is the one-time `#/agent-register/...` Agent Key URL.
* The user manages the Agent Key in the UnoLock Safe web app.
* The Agent Key URL is the one-time setup input for that Agent Key on this device.
* After that, ongoing access uses the registered local Agent Key, not the URL itself.
* The initial setup flow expects both values together.

### `unolock_set_agent_pin`

Purpose:
Store the Agent Key PIN in MCP process memory only.

Arguments:

* `pin: str`

Notes:

* PINs are strings, not numbers.
* Valid characters are `0-9` and `a-f`.
* Use this mainly after restart or re-authentication when the MCP asks for the PIN again.

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
* `title: str | null = None`
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
* `title: str | null = None`
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

These are support-only tools for diagnostics or cleanup:

* `unolock_get_update_status`
* `unolock_get_tpm_diagnostics`
* `unolock_clear_agent_pin`
* `unolock_clear_connection_url`
* `unolock_clear_current_space`
* `unolock_disconnect_agent`
