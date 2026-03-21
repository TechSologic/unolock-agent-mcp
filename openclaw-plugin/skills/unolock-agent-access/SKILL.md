---
name: unolock-agent-access
description: Guides an AI agent through connecting to a user's UnoLock Safe with the UnoLock agent tool, then working in the current Space with notes, checklists, and files.
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

## Core Concepts

- `Safe`: the user's protected storage area in UnoLock
- `Space`: a working area inside the Safe for one project, customer, or task context
- `note`: durable freeform text for summaries, plans, research, decisions, and reusable context
- `checklist`: durable structured task tracking with item completion state
- `file`: durable document or binary storage for attachments, exports, references, and other non-text artifacts

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

## Preferred Workflow

1. Install the UnoLock Agent CLI with `npm install -g @techsologic/unolock-agent`, then run `unolock-agent` directly.
1.5. Run `unolock-agent` without arguments to get a usage statement when needed.
2. Run the `unolock-agent` command you need directly.
3. On a fresh host, allow extra time for the first start.
4. Ask the user for the one-time Agent Key URL and the PIN together.
5. Register this device to the Safe:
   `unolock-agent register '<agent-key-url>' '<pin>'`
6. List spaces and select the working space when needed:
   `unolock-agent list-spaces`
   `unolock-agent set-current-space <space_id>`
7. Use the normal note, checklist, and file commands for day-to-day work.

## Registration And PIN Model

- registration normally happens once on a device for a given Agent Key
- after registration, use normal UnoLock commands directly
- the one-time Agent Key URL is for registration, not for everyday use
- the CLI may ask for the PIN later when the local UnoLock process restarts or needs to authenticate again
- if that happens, run `unolock-agent set-pin '<pin>'` and retry the original command

## Main CLI Commands

- `unolock-agent register '<agent-key-url>' '<pin>'`: first setup on this device
- `unolock-agent set-pin '<pin>'`: provide the PIN again after restart or re-authentication
- `unolock-agent list-spaces`, `unolock-agent get-current-space`, `unolock-agent set-current-space <space_id>`: inspect and switch the current Space
- `unolock-agent list-notes`, `unolock-agent create-note <title> <text>`, `unolock-agent update-note <record_ref> [--title <title>] [--text <text>]`, `unolock-agent append-note ...`: read and write notes
- `unolock-agent list-checklists`, `unolock-agent create-checklist ...`, `unolock-agent set-checklist-item-done ...`, `unolock-agent add-checklist-item ...`, `unolock-agent remove-checklist-item ...`: read and write checklists
- `unolock-agent list-files`, `unolock-agent get-file <archive_id>`, `unolock-agent download-file ...`, `unolock-agent upload-file ...`, `unolock-agent rename-file ...`, `unolock-agent replace-file ...`, `unolock-agent delete-file ...`: read and manage Cloud files
- `unolock-agent get-record <record_ref>` and `unolock-agent rename-record ...`: inspect or rename an existing note or checklist

## Key Rules

- give the agent the Agent Key URL and PIN together for first setup
- if `unolock-agent` is installed, use `unolock-agent ...` directly for CLI commands
- run the `unolock-agent` command you need directly
- if a command reports that the PIN is needed, run `unolock-agent set-pin '<pin>'` and retry the original command
- if unsure which command to use next, run `unolock-agent --help`
- keep the PIN in UnoLock process memory only
- install the UnoLock Agent CLI with `npm install -g @techsologic/unolock-agent`

## User-Facing Model

- The user manages the Agent Key in the UnoLock Safe web app.
- The user gives the agent a one-time Agent Key URL and the PIN.
- The local UnoLock agent uses those to set up access on the current device.
- After that, ongoing access uses the registered local Agent Key.
