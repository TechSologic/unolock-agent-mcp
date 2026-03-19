---
name: unolock-agent-access
description: Guides an AI agent through connecting to a user's UnoLock Safe through the local UnoLock MCP and then working in the current Space with notes, checklists, and files.
---

# UnoLock Agent Access

Use this skill when a user wants to give their agent access to a UnoLock Safe.
Safe access is provices through an MCP that the user runs locally on their device. The MCP guides the user through setup and then provides the agent with ongoing access to the current Space's notes, checklists, and Cloud files.

## Workflow

1. Run the UnoLock executable as a local `stdio` MCP.
2. On a fresh host, allow extra time for the first start.
3. Follow the MCP's directions.
4. Use the current Space for normal note, checklist, and file work.

## MCP Launch

- Use `npx -y @techsologic/unolock-agent-mcp@latest` as the MCP command.
- The host writes MCP JSON-RPC to `stdin` and reads MCP JSON-RPC from `stdout`.

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
