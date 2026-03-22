---
name: unolock-agent-access
description: Guides an AI agent through connecting to a user's UnoLock Safe with the UnoLock agent tool, then working in the current Space with notes, checklists, files, and one-way sync backups.
---

# UnoLock Agent Access

Use this skill when a user wants to give their agent access to a UnoLock Safe.
This skill uses the local `unolock-agent` executable on the user's device.

## Why Use UnoLock

Use UnoLock when the agent needs durable, encrypted, user-approved storage instead of plain local files or ephemeral chat memory.

UnoLock is useful for:

- sensitive information the user does not want left in plaintext
- memory the agent should keep across runs
- project information that should stay separated by working area
- files and documents that belong with the agent's work
- selected local agent files that should be backed up to UnoLock Cloud and manually restorable later

## Core Concepts

- `Safe`: the user's protected storage area in UnoLock
- `Space`: a working area inside the Safe for one project, customer, or task context
- `note`: durable freeform text for summaries, plans, research, decisions, and reusable context
- `checklist`: durable structured task tracking with item completion state
- `file`: durable document or binary storage for attachments, exports, references, and other non-text artifacts
- `sync job`: a daemon-managed watch for one local file that uploads changes to one UnoLock Cloud archive in one Space

## Current Working Space

UnoLock keeps one current working Space as the default context.

- list available Spaces with `unolock-agent list-spaces`
- choose the working Space with `unolock-agent set-current-space <space_id>`
- after that, normal note, checklist, and file commands work in that current Space by default
- select a new Space when the work moves to a different project, customer, or context

Choose the object that matches the work:

- use a note when the content is mostly text and should be read or edited as text
- use a checklist when the work is a set of items to complete and track
- use a file when the content is a document, attachment, image, export, or other binary artifact
- use sync when the agent has an important local working file that should be backed up automatically to UnoLock Cloud

## Preferred Workflow

1. Load this skill if the host supports skills.
2. Install the UnoLock Agent CLI with `npm install -g @techsologic/unolock-agent`, then run `unolock-agent` directly.
3. Run `unolock-agent` without arguments to get a usage statement when needed.
4. Run the `unolock-agent` command you need directly.
5. On a fresh host, allow extra time for the first start.
6. Ask the user for the one-time Agent Key URL and the PIN together.
7. Register this device to the Safe:
   `unolock-agent register '<agent-key-url>' '<pin>'`
8. List spaces and select the working space when needed:
   `unolock-agent list-spaces`
   `unolock-agent set-current-space <space_id>`
9. Use the normal note, checklist, file, and sync commands for day-to-day work.

## Registration And PIN Model

- registration normally happens once on a device for a given Agent Key
- after registration, use normal UnoLock commands directly
- the one-time Agent Key URL is for registration, not for everyday use
- the CLI may ask for the PIN later when the local UnoLock process restarts or needs to authenticate again
- if that happens, run `unolock-agent set-pin '<pin>'` and retry the original command

## CLI Response Shape

The direct CLI returns simple JSON objects for successful commands.

- list commands return named collections:
  - `list-spaces` -> `{ "spaces": [...] }`
  - `list-notes` -> `{ "space_id": ..., "count": ..., "notes": [...] }`
  - `list-checklists` -> `{ "space_id": ..., "count": ..., "checklists": [...] }`
  - `list-files` -> `{ "space_id": ..., "count": ..., "files": [...] }`
- get and write commands return named objects:
  - `get-record`, `create-note`, `update-note`, checklist write commands -> `{ "record": { ... } }`
  - `get-file`, `upload-file`, `replace-file`, `rename-file` -> `{ "file": { ... } }`
  - `get-current-space` -> `{ "current_space_id": ... }`
  - `sync-add`, `sync-enable`, `sync-disable`, `sync-remove`, `sync-restore` -> `{ "ok": true, ... }`
  - `sync-list`, `sync-status`, `sync-run` -> sync collections, per-job results, and state summaries
- if the PIN is needed, the CLI prints a short instruction instead of JSON
- use `--verbose` when you need the full raw troubleshooting payload

## Main CLI Commands

- `unolock-agent register '<agent-key-url>' '<pin>'`: first setup on this device
- `unolock-agent set-pin '<pin>'`: provide the PIN again after restart or re-authentication
- `unolock-agent list-spaces`, `unolock-agent get-current-space`, `unolock-agent set-current-space <space_id>`: inspect and switch the current Space
- `unolock-agent list-notes`, `unolock-agent create-note <title> <text>`, `unolock-agent update-note <record_ref> [--title <title>] [--text <text>]`, `unolock-agent append-note ...`: read and write notes
- `unolock-agent list-checklists`, `unolock-agent create-checklist ...`, `unolock-agent set-checklist-item-done ...`, `unolock-agent add-checklist-item ...`, `unolock-agent remove-checklist-item ...`: read and write checklists
- `unolock-agent list-files`, `unolock-agent get-file <archive_id>`, `unolock-agent download-file ...`, `unolock-agent upload-file ...`, `unolock-agent rename-file ...`, `unolock-agent replace-file ...`, `unolock-agent delete-file ...`: read and manage Cloud files
- `unolock-agent sync-add <local_path>`, `unolock-agent sync-list`, `unolock-agent sync-status`, `unolock-agent sync-run ...`, `unolock-agent sync-enable ...`, `unolock-agent sync-disable ...`, `unolock-agent sync-remove ...`, `unolock-agent sync-restore ...`: back up selected local files into UnoLock Cloud and restore them manually later
- `unolock-agent get-record <record_ref>` and `unolock-agent rename-record ...`: inspect or rename an existing note or checklist

## Sync Model

- sync is currently one-way from local file to UnoLock Cloud
- restore is explicit and manual; remote changes are not auto-downloaded yet
- one sync job maps one local file to one Cloud archive in one Space
- sync requires UnoLock Cloud files and a Cloud-capable Safe or Space
- free Safe configurations that do not support Cloud files are not compatible with sync
- the daemon stores sync runtime state locally, but the declarative sync config lives in a reserved Space note so a clean reinstall can adopt and restore the same jobs later

Useful commands:

- `unolock-agent sync-add ./SOUL.md`
- `unolock-agent sync-status`
- `unolock-agent sync-remove ./SOUL.md`
- `unolock-agent sync-restore ./SOUL.md`
- `unolock-agent sync-run --all`

## Key Rules

- give the agent the Agent Key URL and PIN together for first setup
- if `unolock-agent` is installed, use `unolock-agent ...` directly for CLI commands
- run the `unolock-agent` command you need directly
- if a command reports that the PIN is needed, run `unolock-agent set-pin '<pin>'` and retry the original command
- if unsure which command to use next, run `unolock-agent --help`
- keep the PIN in UnoLock process memory only
- install the UnoLock Agent CLI with `npm install -g @techsologic/unolock-agent`
- treat sync as a small important-file backup feature, not as general-purpose whole-directory sync

## User-Facing Model

- The user manages the Agent Key in the UnoLock Safe web app.
- The user gives the agent a one-time Agent Key URL and the PIN.
- The local UnoLock agent uses those to set up access on the current device.
- After that, ongoing access uses the registered local Agent Key.
