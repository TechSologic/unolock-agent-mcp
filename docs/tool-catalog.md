# MCP Tool Catalog

This document describes the current UnoLock Agent MCP tool surface for the current read and write MVP.

The recommended lifecycle is:

1. Check registration and TPM readiness.
2. Ask the user for a one-time-use UnoLock agent key connection URL and, if configured, the agent PIN if needed.
3. Register or authenticate the agent.
4. Use the primary space and record tools.
5. Read a target record before updating it so the MCP has cached archive state and the current record version.

If the user asks what UnoLock is, why the MCP needs a connection URL, why it may ask for a PIN, or why host assurance matters, use the explanatory resources:

* `unolock://usage/about`
* `unolock://usage/security-model`
* `unolock://usage/updates`

Primary tools for first-time agent use:

* `unolock_get_registration_status`
* `unolock_submit_agent_bootstrap`
* `unolock_bootstrap_agent`
* `unolock_list_spaces`
* `unolock_list_records`
* `unolock_get_record`

Advanced/debug tools exist too, but agents should ignore them unless the primary workflow cannot complete the task.

## Registration And Runtime

### `unolock_get_registration_status`

Purpose:
Return whether this MCP host is already registered, whether it has a stored agent key connection URL, and what the agent should do next.

Notes:

* When registration is needed, the MCP should tell the agent that the agent key connection URL is one-time-use and for enrollment only.

Arguments:
None.

Important response fields:

* `registered`
* `needs_connection_url`
* `recommended_next_action`
* `guidance`
* `has_agent_pin`
* `tpm_provider`
* `tpm_diagnostics`
* `explanation_resources`

Typical `recommended_next_action` values:

* `ask_for_connection_url`
* `start_registration`
* `authenticate_or_set_pin`
* `authenticate_agent`
* `ask_for_agent_pin_then_continue`
* `continue_pending_session`
* `review_tpm_diagnostics`
* `resolve_tpm_provider_mismatch`

The `explanation_resources` field points to MCP resources the agent can read when it needs authoritative user-facing language about UnoLock, Agent Keys, enrollment URLs, PINs, and assurance tradeoffs.

### `unolock_get_update_status`

Purpose:
Check the installed UnoLock Agent MCP version against the latest GitHub Release and return runner-specific update guidance.

Arguments:
None.

Notes:

* UnoLock Agent MCP should normally be updated by its wrapper or runner, not by the live MCP process replacing itself mid-session.
* Prefer checking between tasks, not during an active registration, authentication, or sensitive write flow.
* The preferred low-friction path is `mcporter` keep-alive plus `npx @techsologic/unolock-agent-mcp@latest`.

## Explanatory Resources

### `unolock://usage/about`

Purpose:
Return a concise explanation of what UnoLock is, what an Agent Key is, and why customers might use UnoLock with AI agents.

Typical use:

* user asks what UnoLock is
* user asks why an Agent Key is needed
* agent needs authoritative wording instead of improvising

### `unolock://usage/security-model`

Purpose:
Return a concise explanation of why the MCP asks for a one-time-use connection URL, why a PIN may be needed, and why stronger host key storage is preferred.

Typical use:

* user asks why the connection URL is required
* user asks why the URL is one-time-use
* user asks why the agent may need a PIN
* user asks why TPM, Secure Enclave, or platform-backed keys matter

### `unolock://usage/quickstart`

Purpose:
Return the preferred short MCP happy path for first-time agent use.

### `unolock://usage/updates`

Purpose:
Return concise guidance for how UnoLock Agent MCP updates should be checked and applied without pushing the agent toward unsafe in-place self-replacement.

### `unolock_get_tpm_diagnostics`

Purpose:
Describe the active TPM/vTPM provider and whether the host is production-ready.

Arguments:
None.

Important response fields:

* `provider_name`
* `provider_type`
* `production_ready`
* `available`
* `summary`
* `advice`

### `unolock_submit_connection_url`

Purpose:
Store and parse a one-time-use UnoLock agent key connection URL from the user.

Arguments:

* `connection_url: str`

Expected input:

* one-time-use agent URL format: `#/agent-register/...`

Common failure response:

* `reason: wrong_connection_url_type`
  Used when the user provides a normal `#/register/...` key URL instead of an agent key URL.

### `unolock_submit_agent_bootstrap`

Purpose:
Store the one-time-use UnoLock agent key connection URL and an optional agent PIN together in one step.

Arguments:

* `connection_url: str`
* `pin: str | null`

Typical use:

* cold start
* reduce one round trip by asking the user for the connection URL and PIN together

Notes:

* the connection URL is one-time-use and for enrollment only
* the PIN remains in process memory only
* if no PIN was configured for the agent key, omit it

### `unolock_clear_connection_url`

Purpose:
Remove the locally stored one-time-use UnoLock agent key connection URL.

Arguments:
None.

### `unolock_set_agent_pin`

Purpose:
Store the optional agent PIN in process memory only.

Arguments:

* `pin: str`

Notes:

* The PIN is not persisted across MCP process restarts.
* The MCP hashes it with the server challenge when `GetPin` is encountered.

### `unolock_clear_agent_pin`

Purpose:
Clear the in-memory agent PIN.

Arguments:
None.

### `unolock_disconnect_agent`

Purpose:
Permanently disconnect the local MCP host from the current UnoLock agent registration.

Arguments:
None.

What it removes locally:

* TPM/provider key for the local agent
* provider-protected bootstrap secret
* provider-protected AIDK secret
* local registration state
* in-memory auth sessions
* in-memory PIN

What it does not remove:

* the server-side access record

## Agent Flow Tools

### `unolock_start_registration_from_connection_url`

Purpose:
Start agent registration from the stored one-time-use agent key connection URL.

Arguments:
None.

Typical use:

* after `unolock_submit_connection_url`
* or after a restart when a stored URL exists and registration was not completed

### `unolock_continue_agent_session`

Purpose:
Continue an in-memory agent flow session through known callbacks.

Arguments:

* `session_id: str`

Typical use:

* continue a paused `GetPin` session after calling `unolock_set_agent_pin`

### `unolock_authenticate_agent`

Purpose:
Authenticate an already registered agent.

Arguments:
None.

Typical use:

* after the MCP process restarts
* after setting the agent PIN in memory

### `unolock_bootstrap_agent`

Purpose:
One-shot helper that chooses registration or authentication based on the current local state.

Arguments:
None.

Behavior:

* if not registered and a stored agent key connection URL exists:
  starts registration
* if already registered:
  authenticates the agent

## Read-Only Data Tools

These tools require an authenticated `session_id`.

### `unolock_list_spaces`

Purpose:
Return the visible UnoLock spaces plus record counts.

Arguments:

* `session_id: str`

Response shape:

* `count`
* `spaces[]`

Each `spaces[]` item includes:

* `space_id`
* `type`
* `owner`
* `space_name`
* `record_archive_id`
* `record_count`
* `note_count`
* `checklist_count`
* `writable`
* `allowed_operations`

### `unolock_list_records`

Purpose:
Return read-only notes and checklists projected into agent-friendly DTOs.

Arguments:

* `session_id: str`
* `kind: "all" | "note" | "checklist"` default `all`
* `space_id: int | null`
* `pinned: bool | null`
* `label: str | null`

Response shape:

* `count`
* `records[]`

Each `records[]` item includes:

* `record_ref`
* `id`
* `version`
* `archive_id`
* `space_id`
* `space_name`
* `kind`
* `title`
* `plain_text`
* `pinned`
* `labels`
* `message_meta`
* `checklist_items`
* `raw_delta`
* `raw_checkboxes`
* `read_only`
* `locked`
* `writable`
* `allowed_operations`

For checklist records, each `checklist_items[]` item includes:

* `id`
* `text`
* `done`
* `checked`
* `state`
* `order`

### `unolock_list_notes`

Purpose:
Convenience wrapper for `unolock_list_records(kind="note")`.

Arguments:

* `session_id: str`
* `space_id: int | null`
* `pinned: bool | null`
* `label: str | null`

### `unolock_list_checklists`

Purpose:
Convenience wrapper for `unolock_list_records(kind="checklist")`.

### `unolock_get_record`

Purpose:
Return one note or checklist by `record_ref`.

Arguments:

* `session_id: str`
* `record_ref: str`

Typical use:

* call `unolock_list_records` first to discover `record_ref`

Notes:

* This is the recommended way to refresh one record before a write.
* Existing-record writes depend on cached archive state from a prior `get` or `list` call.
* Use `writable` and `allowed_operations` to decide whether a write is allowed before calling a write tool.

## Write Tools

These tools require an authenticated `session_id`.

General rules:

* Read the target record first with `unolock_get_record` or `unolock_list_records`.
* Check `writable` and `allowed_operations` before attempting a write.
* Use the returned `record_ref` and `version` when updating existing records.
* Read-only agents fail early with `space_read_only`.
* Locked/read-only records fail with `record_locked`.
* If the record changed since the last read, the MCP fails with `write_conflict_requires_reread` and the agent should reread before retrying.

Stable write failure reasons:

* `space_read_only`
* `record_locked`
* `write_conflict_requires_reread`
* `read_first_before_write`
* `operation_not_allowed`
* `record_not_found`
* `item_not_found`
* `invalid_input`

Each write failure response includes:

* `ok: false`
* `reason`
* `message`
* `suggested_action`

### `unolock_create_note`

Purpose:
Create a new note from raw text.

Arguments:

* `session_id: str`
* `space_id: int`
* `title: str`
* `text: str`

Notes:

* New notes start at `version: 1`.
* Raw text is converted to the minimal Quill JSON form UnoLock stores internally.
* If the space is not writable for this agent, the MCP fails early with `space_read_only`.

### `unolock_update_note`

Purpose:
Update an existing note's title and body from raw text.

Arguments:

* `session_id: str`
* `record_ref: str`
* `expected_version: int`
* `title: str`
* `text: str`

Notes:

* Requires cached archive state from a prior read.
* Uses a cache-first optimistic write path.
* On archive conflict, the MCP rereads from UnoLock and retries only if the note version is unchanged.
* If the note is locked or the agent only has read-only access, the MCP fails before upload.

### `unolock_rename_record`

Purpose:
Change the title of an existing note or checklist.

Arguments:

* `session_id: str`
* `record_ref: str`
* `expected_version: int`
* `title: str`

Notes:

* This changes the title only.
* It does not change note text or checklist items.
* Requires cached archive state from a prior read.
* If the record is locked or the agent only has read-only access, the MCP fails before upload.

### `unolock_create_checklist`

Purpose:
Create a new checklist in a writable Records archive.

Arguments:

* `session_id: str`
* `space_id: int`
* `title: str`
* `items: list[object]`

Each `items[]` object must include:

* `text: str`

Supported optional item state fields:

* `checked`
* `done`
* `state`

State rules:

* `checked: true` creates a checked item
* `done: true` creates a checked item
* `state: "checked"` creates a checked item
* If the space is not writable for this agent, the MCP fails early with `space_read_only`.

### `unolock_set_checklist_item_done`

Purpose:
Set one checklist item's checked state.

Arguments:

* `session_id: str`
* `record_ref: str`
* `expected_version: int`
* `item_id: int`
* `done: bool`

Notes:

* Requires cached archive state from a prior read.
* If the checklist is locked or the agent only has read-only access, the MCP fails before upload.

### `unolock_add_checklist_item`

Purpose:
Append a new unchecked checklist item.

Arguments:

* `session_id: str`
* `record_ref: str`
* `expected_version: int`
* `text: str`

Notes:

* Requires cached archive state from a prior read.
* If the checklist is locked or the agent only has read-only access, the MCP fails before upload.

### `unolock_remove_checklist_item`

Purpose:
Remove one checklist item by `item_id`.

Arguments:

* `session_id: str`
* `record_ref: str`
* `expected_version: int`
* `item_id: int`

Notes:

* Requires cached archive state from a prior read.
* If the checklist is locked or the agent only has read-only access, the MCP fails before upload.

## Low-Level Utility Tools

These are useful for debugging or deeper integration work, but they are not the preferred surface for the normal agent workflow.

* `unolock_probe_local_server`
* `unolock_start_flow`
* `unolock_continue_flow`
* `unolock_get_session`
* `unolock_list_sessions`
* `unolock_delete_session`
* `unolock_call_api`
* `unolock_get_spaces`
* `unolock_get_archives`

## Recommended Happy Path

1. Call `unolock_get_registration_status`.
2. If needed, ask the user for the one-time-use UnoLock agent key connection URL and optional PIN together.
3. Call `unolock_submit_agent_bootstrap`.
4. If needed, call `unolock_bootstrap_agent`.
5. If the MCP still says it needs the agent PIN, ask the user for it and call `unolock_set_agent_pin`.
6. Continue with `unolock_bootstrap_agent` or `unolock_continue_agent_session`.
7. After authentication, call `unolock_list_spaces` or `unolock_list_records`.
8. Before writing, read the target record and use its `writable`, `allowed_operations`, `record_ref`, and `version` fields.
