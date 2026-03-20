# MCP Host Config

This document shows the current easiest way to run UnoLock Agent in real MCP hosts.

For the public agent-first onboarding flow, see:

* `https://unolock.ai/index.html`
* `https://unolock.ai/install-mcp.html`

If you need the underlying UnoLock product concepts first, see:

* UnoLock Knowledge Base: `https://docs.unolock.com/index.html`
* Agentic Safe Access: `https://docs.unolock.com/features/agentic-safe-access.html`
* Spaces: `https://docs.unolock.com/features/spaces.html`

## Security Requirement

For normal customer use, UnoLock Agent works best with a production-ready:

* TPM
* vTPM
* Secure Enclave
* or equivalent platform-backed non-exportable key store

If the current host does not provide one, the MCP can still fall back to the software provider. When that happens, it reports reduced assurance clearly and makes that reduced-assurance tradeoff visible.

That is the point of the product: keep AI agent access as device-bound as the host allows, without hiding when the host could not meet UnoLock's strongest storage requirements.

Checked against the official host docs on 2026-03-08:

* Anthropic Claude Code / Claude Desktop MCP docs:
  * https://docs.anthropic.com/en/docs/claude-code/mcp
* Cursor MCP docs:
  * https://docs.cursor.com/advanced/model-context-protocol

## Recommended install mode

The preferred mode is:

* use `npx -y @techsologic/unolock-agent@latest` or a GitHub Release binary
* prefer the CLI commands for normal direct agent use
* use `unolock-agent mcp` only for hosts that specifically require MCP
* let UnoLock manage its own local daemon so the user PIN can remain in process memory instead of being persisted by the agent

For customer use, prefer a standalone GitHub Release binary:

* `https://github.com/TechSologic/unolock-agent/releases`

If you are integrating with a Node/npm-oriented host, you can also use:

```bash
npx -y @techsologic/unolock-agent@latest --version
```

This npm package is both:

* the normal UnoLock daemon-backed MCP command package
* an OpenClaw plugin package that ships the UnoLock skill

For a host-managed stdio launch, prefer:

```bash
npx -y @techsologic/unolock-agent@latest mcp
```

Project home:

* `https://github.com/TechSologic/unolock-agent`

For updates, the preferred pattern is:

* check status with `unolock_get_update_status` or `unolock-agent check-update`
* let the current task finish
* restart the UnoLock MCP
* let the npm wrapper or replacement binary apply the update between tasks

Do not expect the live MCP process to replace itself in place.

If you need the source-install fallback instead, install the MCP as a standalone package:

```bash
pipx install git+https://github.com/TechSologic/unolock-agent.git
```

If you are running outside a UnoLock monorepo checkout, the MCP can normally derive the UnoLock server origin and PQ validation key from the UnoLock Agent Key URL itself. In most cases, the only host-level setting you should need is:

* optionally `UNOLOCK_TPM_PROVIDER`

Use explicit config only when you need overrides or you are connecting to a custom deployment that does not publish the normal deployment metadata.

You can also place them in the local UnoLock config file and verify the resolved values with:

```bash
python3 -m unolock_mcp config-check
```

For a one-shot readiness summary after install, run:

```bash
unolock-agent-self-test
```

For normal UnoLock cloud-service use, no UnoLock runtime env vars are required at MCP startup. Once the user provides a UnoLock Agent Key URL, the MCP derives the Safe site origin, API base URL, and then fetches the published PQ validation key automatically. UnoLock is a cloud service, but Safe data remains client-side encrypted, no identity is linked to a Safe, and the system is designed to minimize unnecessary metadata and correlation exposure.

TPM provider modes:

* `auto`: choose the strongest available provider for the current host, then fall back to the software provider with reduced-assurance warnings if needed
* `software`: force the software provider
* `test`: legacy alias for the software provider
* `linux`: force the Linux TPM/vTPM provider
* `mac`: force the best available macOS provider
* `mac-se` / `mac-secure-enclave`: force the macOS Secure Enclave provider
* `mac-keychain` / `mac-platform`: force the macOS Keychain-backed provider
* `windows`: force the best available Windows provider
* `windows-tpm` / `win-tpm`: force the Windows TPM helper provider
* `windows-cng` / `windows-platform` / `win-cng`: force the Windows CNG fallback provider

WSL2 note:

* WSL2 usually does not expose `/dev/tpmrm0` or `/dev/tpm0`
* on WSL2, `auto` now prefers the Windows TPM helper provider and falls back to the Windows CNG provider
* if neither Windows provider works, `auto` falls back to the software provider and reports reduced assurance
* for production use, WSL2 should use the Windows provider path, not the Linux TPM path

Software fallback note:

* software mode is clearly reported as lower assurance and should be treated as a fallback, not equivalent to hardware-backed or platform-backed storage

macOS note:

* on macOS, `auto` now prefers Secure Enclave and falls back to a non-exportable Keychain-backed provider
* the current implementation uses a small Swift helper that talks to Security.framework
* install Apple Xcode Command Line Tools first with `xcode-select --install`
* for a first customer trial, start with [macos.md](macos.md)

## Claude Desktop

Add a server entry to your `claude_desktop_config.json` `mcpServers` object.

Example snippet:

```json
{
  "mcpServers": {
    "unolock-agent": {
      "command": "npx",
      "args": ["-y", "@techsologic/unolock-agent@latest", "mcp"]
    }
  }
}
```

Notes:

* If you already installed UnoLock locally, you can use `"command": "unolock-agent"` instead.
* For local development, you can still set `UNOLOCK_BASE_URL=http://127.0.0.1:3000` as an override, but it is no longer required for the normal connection-URL-driven flow.
* For normal UnoLock cloud-service use, the Agent Key URL is enough for the MCP to resolve what it needs automatically.
* Do not ask users for `UNOLOCK_BASE_URL`, `UNOLOCK_TRANSPARENCY_ORIGIN`, or `UNOLOCK_SIGNING_PUBLIC_KEY` in the normal flow. Use them only as advanced overrides when you are dealing with a custom deployment or debugging a broken one.

## Cursor

Cursor supports project-local and global MCP config:

* project: `.cursor/mcp.json`
* global: `~/.cursor/mcp.json`

Example snippet:

```json
{
  "mcpServers": {
    "unolock-agent": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@techsologic/unolock-agent@latest", "mcp"]
    }
  }
}
```

If needed, Cursor also supports variable interpolation in `command`, `args`, and `env`. For example:

```json
{
  "mcpServers": {
    "unolock-agent": {
      "type": "stdio",
      "command": "${env:HOME}/.local/bin/npx",
      "args": ["-y", "@techsologic/unolock-agent@latest", "mcp"]
    }
  }
}
```

## OpenClaw

For OpenClaw, prefer the UnoLock plugin and skill.

The intended published plugin install path is:

```bash
openclaw plugins install @techsologic/unolock-agent
```

For local repo testing before that plugin install path is published, point `plugins.load.paths` at this repo root and enable `unolock-agent-access`. A full example is in [examples/openclaw-plugin-config.json](../examples/openclaw-plugin-config.json).

If OpenClaw needs an MCP command in config, use the local stdio command below.

Example snippet:

```json
{
  "mcpServers": {
    "unolock-agent": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@techsologic/unolock-agent@latest", "mcp"]
    }
  }
}
```

If you already installed UnoLock locally, you can use `"command": "unolock-agent"` instead.

## First-use flow

Once the host can launch the MCP:

1. Launch the local stdio MCP.
2. Ask the user for the one-time UnoLock Agent Key URL and the agent PIN together when the MCP says setup is needed.
3. Submit them to the MCP with `unolock_link_agent_key`.
4. Let the MCP continue registration or authentication automatically.
5. Start using read and write tools as permitted by the Agent Key.

After the MCP process restarts:

1. Ask the MCP for registration status again.
2. If it reports `authenticate_or_set_pin`, ask the user for the agent PIN.
3. Set the PIN in MCP memory.
4. Authenticate and continue using read or write tools as permitted by the Agent Key.

Relevant tools:

* `unolock_link_agent_key`
* `unolock_set_agent_pin`
* `unolock_list_spaces`
* `unolock_get_current_space`
* `unolock_set_current_space`
* `unolock_list_files`
* `unolock_list_notes`
* `unolock_list_checklists`
* `unolock_get_file`
* `unolock_get_record`
* `unolock_download_file`
* `unolock_rename_file`
* `unolock_replace_file`
* `unolock_delete_file`
* `unolock_create_note`
* `unolock_update_note`
* `unolock_append_note`
* `unolock_upload_file`
* `unolock_rename_record`
* `unolock_create_checklist`
* `unolock_set_checklist_item_done`
* `unolock_add_checklist_item`
* `unolock_remove_checklist_item`

Important current-space behavior:

* the MCP now keeps one current Space locally
* if no current Space was selected yet, it auto-selects the first accessible Space
* normal read and write tools act in that current Space
* if the Agent Key has access to no Spaces, the MCP returns a clear `no_accessible_spaces` error

Write guidance:

* Let the MCP auto-select the first accessible Space if no current Space was chosen yet.
* Read the target Space or record first.
* Check `writable` and `allowed_operations` in the latest MCP response before attempting a write.
* Use `record_ref` and `version` when updating existing records.
* Use `archive_id` from `unolock_list_files` when downloading a Cloud file.
* Use `unolock_set_current_space` only when you want to switch away from the current default Space.
* Use `archive_id` from `unolock_list_files` or `unolock_get_file` when renaming, replacing, or deleting a Cloud file.
* The MCP keeps archive snapshots in memory only and uses a 5-minute default freshness TTL.
* On write conflict, the MCP rereads the archive, checks the record version, and tells the agent when a reread is required.

## Local development values

For the current local UnoLock stack:

* Angular client: `http://localhost:4200`
* local SAM server: `http://127.0.0.1:3000`

The Playwright create-safe flow can emit a fresh agent bootstrap artifact:

```bash
E2E_AGENT_BOOTSTRAP_OUTPUT_FILE=/tmp/unolock-agent-bootstrap.json \
npm --prefix /path/to/Unolock/client/e2e-playwright run test:create-safe
```

With the default Playwright PIN automation settings, the test PIN is:

```text
0123
```

## TPM/vTPM diagnosis

Before trusting the MCP in production, run:

```bash
python3 -m unolock_mcp tpm-diagnose
unolock-agent-self-test
```

The diagnostic reports:

* active provider name
* whether the provider is production-ready
* whether the host appears to have a working TPM/vTPM
* whether the host looks like Docker or another container environment
* concrete advice when the host does not
* whether a stored agent registration was created with a different TPM provider than the one currently selected

If the MCP detects that it is running in Docker or another plain container without TPM/vTPM access, the advice now says that explicitly and points to the UnoLock docs for current environment guidance.

If the MCP reports a TPM provider mismatch after you change hosts or switch `UNOLOCK_TPM_PROVIDER`, either:

* re-run the MCP with the provider that originally registered the agent key
* or generate a fresh UnoLock Agent Key URL and register a new agent credential with the current provider
