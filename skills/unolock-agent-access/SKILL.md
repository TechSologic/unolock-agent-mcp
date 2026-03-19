---
name: unolock-agent-access
description: Guides an AI agent through connecting to a user's UnoLock Safe through the UnoLock agent-access skill, which uses the local UnoLock MCP and then works in the current Space with notes, checklists, and files.
---

# UnoLock Agent Access

Use this skill when a user wants to give their agent access to a UnoLock Safe.
This skill uses a local UnoLock `stdio` MCP that runs on the user's device. The MCP guides setup and then provides ongoing access to the current Space's notes, checklists, and Cloud files.

## Workflow

1. Load this skill if the host supports skills.
2. Use `npx -y @techsologic/unolock-agent-mcp@latest` as the MCP command.
3. On a fresh host, allow extra time for the first start.
4. Follow the MCP's directions.
5. Use the current Space for normal note, checklist, and file work.

## MCP Launch

- The host runs `npx -y @techsologic/unolock-agent-mcp@latest` as the MCP command.
- The host writes MCP JSON-RPC to `stdin` and reads MCP JSON-RPC from `stdout`.
- Launch it with no UnoLock-specific arguments.

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
