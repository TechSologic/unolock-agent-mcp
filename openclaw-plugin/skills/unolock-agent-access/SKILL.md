---
name: unolock-agent-access
description: Guides an AI agent through connecting to a user's UnoLock Safe with the UnoLock agent tool, then working in the current Space with notes, checklists, and files.
---

# UnoLock Agent Access

Use this skill when a user wants to give their agent access to a UnoLock Safe.
This skill uses the local `unolock-agent` executable on the user's device.

## Preferred Workflow

1. If `unolock-agent` is not already installed, use `npx -y @techsologic/unolock-agent@latest`.
2. On a fresh host, allow extra time for the first start.
3. Ask the user for the one-time Agent Key URL and the PIN together.
4. Link the key on this device:
   `unolock-agent link-agent-key '<agent-key-url>' '<pin>'`
5. List spaces and select the working space when needed:
   `unolock-agent list-spaces`
   `unolock-agent set-current-space <space_id>`
6. Use the normal note, checklist, and file commands for day-to-day work.

## Main CLI Commands

- `unolock-agent link-agent-key '<agent-key-url>' '<pin>'`: first setup on this device
- `unolock-agent set-agent-pin '<pin>'`: provide the PIN again after restart or re-authentication
- `unolock-agent list-spaces`, `unolock-agent get-current-space`, `unolock-agent set-current-space <space_id>`: inspect and switch the current Space
- `unolock-agent list-notes`, `unolock-agent create-note <title> <text>`, `unolock-agent update-note ...`, `unolock-agent append-note ...`: read and write notes
- `unolock-agent list-checklists`, `unolock-agent create-checklist ...`, `unolock-agent set-checklist-item-done ...`, `unolock-agent add-checklist-item ...`, `unolock-agent remove-checklist-item ...`: read and write checklists
- `unolock-agent list-files`, `unolock-agent get-file <archive_id>`, `unolock-agent download-file ...`, `unolock-agent upload-file ...`, `unolock-agent rename-file ...`, `unolock-agent replace-file ...`, `unolock-agent delete-file ...`: read and manage Cloud files
- `unolock-agent get-record <record_ref>` and `unolock-agent rename-record ...`: inspect or rename an existing note or checklist

## Key Rules

- give the agent the Agent Key URL and PIN together for first setup
- if a command reports that the PIN is needed, run `unolock-agent set-agent-pin '<pin>'` and retry the original command
- keep the PIN in UnoLock process memory only
- if a host explicitly requires the host-command form, use `npx -y @techsologic/unolock-agent@latest mcp`

## User-Facing Model

- The user manages the Agent Key in the UnoLock Safe web app.
- The user gives the agent a one-time Agent Key URL and the PIN.
- The local UnoLock agent uses those to set up access on the current device.
- After that, ongoing access uses the registered local Agent Key.
