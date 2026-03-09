# MCP Tool Catalog

This document describes the current UnoLock Agent MCP tool surface for the working read-only slice.

The recommended lifecycle is:

1. Check registration and TPM readiness.
2. Ask the user for an UnoLock agent key connection URL if needed.
3. Register or authenticate the agent.
4. Use read-only space and record tools.

## Registration And Runtime

### `unolock_get_registration_status`

Purpose:
Return whether this MCP host is already registered, whether it has a stored agent key connection URL, and what the agent should do next.

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

Typical `recommended_next_action` values:

* `ask_for_connection_url`
* `start_registration`
* `authenticate_or_set_pin`
* `authenticate_agent`
* `ask_for_agent_pin_then_continue`
* `continue_pending_session`
* `review_tpm_diagnostics`
* `resolve_tpm_provider_mismatch`

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
Store and parse a UnoLock agent key connection URL from the user.

Arguments:

* `connection_url: str`

Expected input:

* agent URL format: `#/agent-register/...`

Common failure response:

* `reason: wrong_connection_url_type`
  Used when the user provides a normal `#/register/...` key URL instead of an agent key URL.

### `unolock_clear_connection_url`

Purpose:
Remove the locally stored UnoLock agent key connection URL.

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
Start agent registration from the stored agent key connection URL.

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

Arguments:

* `session_id: str`
* `space_id: int | null`
* `pinned: bool | null`
* `label: str | null`

### `unolock_get_record`

Purpose:
Return one note or checklist by `record_ref`.

Arguments:

* `session_id: str`
* `record_ref: str`

Typical use:

* call `unolock_list_records` first to discover `record_ref`

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
2. If needed, ask the user for the UnoLock agent key connection URL.
3. Call `unolock_submit_connection_url`.
4. If needed, call `unolock_start_registration_from_connection_url` or `unolock_bootstrap_agent`.
5. If the MCP says it needs the agent PIN, ask the user for it and call `unolock_set_agent_pin`.
6. Continue with `unolock_bootstrap_agent` or `unolock_continue_agent_session`.
7. After authentication, call `unolock_list_spaces` or `unolock_list_records`.
