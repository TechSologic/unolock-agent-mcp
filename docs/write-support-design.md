# Write Support Design

This document defines the planned write surface for the UnoLock Agent MCP.

The goal is to add useful write support without pretending the MCP can safely perform full-fidelity rich-text editing from day one.

## Goals

* support practical agent writes for notes and checklists
* preserve UnoLock permission enforcement and Space scoping
* avoid silent overwrite of newer human edits
* keep the v1 write contract simple for agents
* leave room for richer formats later without breaking the tool model

## Non-Goals For V1

* full rich-text editing parity with the UnoLock client
* full Markdown support
* exact Quill Delta round-tripping
* arbitrary HTML editing
* hidden lossy conversion of existing richly formatted notes

## Current Storage Reality

UnoLock stores:

* notes as Quill Delta JSON in `recordBody`
* checklists as structured checkbox items with `done`, `data`, and `id`

The MCP currently projects records into a simpler agent-friendly read model.

That means write support needs an adapter layer between:

* MCP-facing agent input
* UnoLock stored record format

## V1 Input Format

V1 writes will support raw text only.

Planned internal format field:

* `text/plain`

Future planned formats:

* `text/markdown`
* `application/vnd.quill.delta+json`

Even though only raw text is supported in v1, the design should keep format as an explicit concept so richer formats can be added later without redesigning the entire write API.

## V1 Write Scope

### Notes

Supported:

* create note from raw text
* create note title from raw text

Not supported yet:

* editing existing rich-text notes
* partial note patching
* format-preserving note rewrites
* inline media or embedded content

V1 note creation behavior:

* agent provides raw text
* MCP converts raw text to a minimal Quill Delta
* UnoLock stores the note in the normal client format

### Checklists

Supported:

* create checklist from raw text items
* rename checklist title
* set checklist item checked state
* add checklist item
* remove checklist item

Possible later support:

* reorder checklist items
* update checklist item text

Checklist write support is safer to add early because the underlying UnoLock format is already structured.

## Record Safety Model

The MCP should not treat all existing records as equally safe to rewrite.

### V1 Rule

* existing notes are read-only
* newly created MCP notes can be tagged or treated as MCP-safe for later raw-text replace support
* checklists can support structured updates earlier because the storage model is already close to the MCP model

This avoids accidental destruction of user-created rich formatting.

## Record Lock Metadata

UnoLock records can be locked / read-only.

The MCP read surface should expose that clearly in record metadata returned to the agent.

Required read/list behavior:

* record list results should include whether the record is locked/read-only
* single-record reads should include whether the record is locked/read-only

Recommended metadata fields:

* `read_only`
* `locked`

These can be aliases of the same underlying UnoLock `ro` record property if that keeps the MCP payload clearer for agents.

## Locked Record Write Rule

If a record is locked/read-only, the MCP should treat it as non-writable.

V1 rule:

* no note write operations
* no checklist item changes
* no rename
* no pin/unpin through the MCP unless the product later decides that lock should apply only to content

The write path should fail clearly with an error such as:

* `record_locked`

This should be checked before mutation and before upload.

## Locking Policy

Agent lock behavior should be intentionally one-way.

V1 rule:

* the agent may lock a record
* the agent may not unlock a record once it is locked

That means:

* add a lock operation later if needed
* do not expose an unlock operation to the agent
* if an agent attempts to change a locked record back to writable, the MCP must reject it

Recommended error:

* `record_unlock_not_allowed`

This keeps the MCP aligned with a conservative safety model:

* agents can make content more restrictive
* they cannot make content less restrictive

## Concurrency And Revision Control

Every write operation should include revision context.

Required design rule:

* no write should silently overwrite a record that changed after the MCP last read it

Planned model:

* each record returned by the MCP includes a revision token
* writes must include that token
* if the token is stale, the MCP rejects the write and tells the agent to re-read first

This should apply to both notes and checklists.

## Archive Upload And Concurrency Requirements

Write support cannot treat UnoLock record writes as a simple JSON API update.

The actual stored record content lives in a Records archive, and the UnoLock web client already applies important archive-level safety rules that the MCP must mirror.

### Required Behavior

The MCP write path must preserve:

* archive encryption format compatibility
* AWS Encryption SDK header behavior
* KEK support
* MD5 / ETag based optimistic concurrency checks for uploaded archive payloads
* the same upload mode rules the client uses for `post`, `put`, and `lput`

### Why This Matters

The web client currently:

* encrypts or compresses+encrypts record archive payloads before upload
* updates `archive.m.kek` by calling the KEK/header rewrite flow
* calculates MD5 for uploaded archive blobs
* uses the returned/current ETag to detect conflicts
* sends `Content-MD5`
* uses conditional upload semantics so two writers do not silently clobber each other

If the MCP skips this and simply uploads a new encrypted blob, it risks:

* losing conflict detection
* corrupting KEK/header expectations
* producing files that the normal UnoLock client cannot read consistently

## Required MCP Write Pipeline

For record-archive writes, the MCP should follow the same high-level pipeline as the web client:

1. Read the current archive metadata and current encrypted archive object
2. Decrypt the current archive body with the normal client data keyring
3. Apply the structured record mutation in memory
4. Re-serialize the archive body
5. Compress/encrypt or encrypt using the same archive mode rules as the web client
6. Apply KEK/header processing exactly as the web client does
7. Compute MD5 of the final upload blob
8. Use the current ETag and the new MD5 when requesting the upload URL
9. Upload with the same conditional semantics as the web client
10. Treat ETag mismatch / `412` / `409` as a conflict and fail safely

## Upload Mode Rules

The MCP should not invent its own upload policy.

It should respect the same archive transfer mode the UnoLock client uses:

* `post`
* `put`
* `lput`

For Records archives, the design should assume:

* the existing archive mode controls how the rewritten blob is uploaded
* KEK handling is required for encrypted string payload upload modes
* `put` / `lput` style uploads need MD5 and ETag handling to stay safe

## Revision Token Design

The MCP-facing `revision` token should be derived from the archive reality, not just the projected record body.

A good v1 revision token should include enough information to detect:

* archive ID
* record ID
* archive ETag or equivalent current-object identity
* maybe a stable body hash for the current record projection

That way the MCP can reject stale writes before or during upload instead of silently replacing a newer archive version.

## Proposed V1 MCP Tools

### Notes

* `unolock_create_note`
  * inputs:
    * `space_id`
    * `title`
    * `text`
    * `format` default `text/plain`

### Checklists

* `unolock_create_checklist`
  * inputs:
    * `space_id`
    * `title`
    * `items`
    * `format` default `text/plain`

* `unolock_set_checklist_item_done`
  * inputs:
    * `record_ref`
    * `item_id`
    * `done`
    * `revision`

* `unolock_add_checklist_item`
  * inputs:
    * `record_ref`
    * `text`
    * `revision`

* `unolock_remove_checklist_item`
  * inputs:
    * `record_ref`
    * `item_id`
    * `revision`

### Shared Record Operations

* `unolock_rename_record`
  * inputs:
    * `record_ref`
    * `title`
    * `revision`

* `unolock_set_record_pinned`
  * inputs:
    * `record_ref`
    * `pinned`
    * `revision`

## Planned Future Expansion

The tool model should leave space for richer note support later.

### Planned Future Note Formats

* `text/markdown`
  * agent-friendly
  * constrained subset only

* `application/vnd.quill.delta+json`
  * advanced/raw mode
  * intended for exact-format clients, not normal agents

### Planned Future Write Modes

* `safe_structured`
  * default mode for v1
  * raw text and structured checklist operations only

* `advanced_raw`
  * future mode for explicit rich-format writes
  * should require the caller to opt in knowingly

## Permission Model

Write support must continue to rely on UnoLock server-side enforcement.

The MCP must not duplicate or weaken:

* Space-scoped access restrictions
* `ro` versus `rw`
* archive ownership rules

If the server rejects a write due to permissions, the MCP should return that clearly to the agent.

## Recommended Implementation Order

1. Create checklist
2. Toggle checklist item checked state
3. Add/remove checklist item
4. Rename/pin shared record operations
5. Create note from raw text
6. Revisit existing-note update support later

## Why This Design

This approach is intentionally conservative.

It gives agents useful write capabilities quickly while avoiding the most likely causes of data loss:

* rewriting rich notes with lossy conversions
* silent concurrency clobbering
* pretending raw text is a safe universal edit format for all existing UnoLock notes

It also keeps the API shape extensible, so future Markdown or Quill Delta support can be added without redesigning the write surface.
