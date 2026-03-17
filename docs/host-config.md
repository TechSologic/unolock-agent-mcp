# MCP Host Config

This document shows the current easiest way to run the UnoLock agent MCP in real MCP hosts.

For the public agent-first onboarding flow, see:

* `https://unolock.ai/index.html`
* `https://unolock.ai/install-mcp.html`

If you need the underlying UnoLock product concepts first, see:

* UnoLock Knowledge Base: `https://docs.unolock.com/index.html`
* Agentic Safe Access: `https://docs.unolock.com/features/agentic-safe-access.html`
* Spaces: `https://docs.unolock.com/features/spaces.html`

## Security Requirement

For normal customer use, UnoLock Agent MCP works best with a production-ready:

* TPM
* vTPM
* Secure Enclave
* or equivalent platform-backed non-exportable key store

If the current host does not provide one, the MCP can still fall back to the software provider. When that happens, it reports reduced assurance clearly, requires an explicit acknowledgment before use, and makes that reduced-assurance tradeoff visible.

That is the point of the product: keep AI agent access as device-bound as the host allows, without hiding when the host could not meet UnoLock's strongest storage requirements.

Checked against the official host docs on 2026-03-08:

* Anthropic Claude Code / Claude Desktop MCP docs:
  * https://docs.anthropic.com/en/docs/claude-code/mcp
* Cursor MCP docs:
  * https://docs.cursor.com/advanced/model-context-protocol

## Recommended install mode

The preferred mode is:

* use `mcporter` or another keep-alive runner when it is available
* launch the MCP through `npx @techsologic/unolock-agent-mcp@latest`
* keep the MCP alive so the user PIN can remain in MCP process memory instead of being persisted by the agent

For customer use, prefer a standalone GitHub Release binary:

* `https://github.com/TechSologic/unolock-agent-mcp/releases`

If you are integrating with a Node/npm-oriented host, you can also use:

```bash
npx @techsologic/unolock-agent-mcp@latest --version
```

This npm package is an OpenClaw-friendly wrapper around the standalone UnoLock MCP binary.

It is **not** an OpenClaw plugin for `openclaw plugins install ...`.

With no arguments, the wrapper starts the MCP server by default.

Project home:

* `https://github.com/TechSologic/unolock-agent-mcp`

If you want the preferred keep-alive path instead of relaunching the MCP repeatedly, see:

* [mcporter keep-alive setup](mcporter.md)

This is especially useful for UnoLock because the user PIN is kept only in MCP process memory. A keep-alive runner lets the agent continue working without repeatedly asking the user for the PIN while that MCP process stays alive, and reduces pressure to store that PIN persistently.

For updates, the preferred pattern is:

* check status with `unolock_get_update_status` or `unolock-agent-mcp check-update`
* let the current task finish
* restart the runner
* let the npm wrapper or replacement binary apply the update between tasks

Do not expect the live MCP process to replace itself in place.

You can print a ready-to-paste `mcporter` config with:

```bash
python3 -m unolock_mcp mcporter-config
```

If you need the source-install fallback instead, install the MCP as a standalone package:

```bash
pipx install git+https://github.com/TechSologic/unolock-agent-mcp.git
```

If you are running outside a UnoLock monorepo checkout, the MCP can normally derive the UnoLock server origin and PQ validation key from the UnoLock Agent Key URL itself. In most cases, the only host-level setting you should need is:

* optionally `UNOLOCK_TPM_PROVIDER`

Use explicit config only when you need overrides or you are connecting to a custom deployment that does not publish the normal deployment metadata.

You can also place them in:

```text
~/.config/unolock-agent-mcp/config.json
```

and verify the resolved values with:

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

* the MCP now requires an explicit reduced-assurance acknowledgment before it will register or authenticate with the software provider
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
      "command": "/home/you/.local/bin/unolock-agent-mcp",
      "args": ["mcp"],
      "env": {
        "UNOLOCK_TPM_PROVIDER": "auto"
      }
    }
  }
}
```

Notes:

* If `unolock-agent-mcp` is already on your `PATH`, you can use `"command": "unolock-agent-mcp"`.
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
      "command": "unolock-agent-mcp",
      "args": ["mcp"],
      "env": {
        "UNOLOCK_TPM_PROVIDER": "auto"
      }
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
      "command": "${env:HOME}/.local/bin/unolock-agent-mcp",
      "args": ["mcp"],
      "env": {
        "UNOLOCK_TPM_PROVIDER": "auto"
      }
    }
  }
}
```

## First-use flow

Once the host can launch the MCP:

1. Ask the MCP for registration status.
2. If it says an Agent Key URL is needed, ask the user for the one-time UnoLock Agent Key URL and, if they configured one, the agent PIN at the same time.
   Treat that URL as enrollment-only, not as a reusable credential.
3. Submit them to the MCP with `unolock_submit_agent_bootstrap`.
4. If the PIN was not collected up front and the Safe later asks for it, set it in MCP memory.
5. Call the one-shot bootstrap/auth flow.
6. Start using read and write tools as permitted by the Agent Key.

After the MCP process restarts:

1. Ask the MCP for registration status again.
2. If it reports `authenticate_or_set_pin`, ask the user for the agent PIN.
3. Set the PIN in MCP memory.
4. Authenticate and continue using read or write tools as permitted by the Agent Key.

Relevant tools:

* `unolock_get_registration_status`
* `unolock_get_tpm_diagnostics`
* `unolock_submit_agent_bootstrap`
* `unolock_submit_connection_url`
* `unolock_set_agent_pin`
* `unolock_bootstrap_agent`
* `unolock_list_spaces`
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

Write guidance:

* Read the target Space or record first.
* Use `writable` and `allowed_operations` before attempting a write.
* Use `record_ref` and `version` when updating existing records.
* Use `archive_id` from `unolock_list_files` when downloading a Cloud file.
* Use `space_id` from `unolock_list_spaces` when uploading a Cloud file.
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
