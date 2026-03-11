# MCP Host Config

This document shows the current easiest way to run the UnoLock agent MCP in real MCP hosts.

If you need the underlying UnoLock product concepts first, see:

* UnoLock Knowledge Base: `https://safe.unolock.com/docs/`
* Agentic Safe Access: `https://safe.unolock.com/docs/features/agentic-safe-access/`
* Spaces: `https://safe.unolock.com/docs/features/spaces/`

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

For customer use, install the MCP as a standalone package:

```bash
pipx install git+https://github.com/TechSologic/unolock-agent-mcp.git
```

If you are running outside a UnoLock monorepo checkout, the MCP can normally derive the UnoLock server origin, app version, and PQ validation key from the UnoLock agent key connection URL itself. In most cases, the only host-level setting you should need is:

* optionally `UNOLOCK_TPM_PROVIDER`

Use explicit config only when you need overrides or you are connecting to a custom deployment that does not publish the standard hosted metadata.

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

For the standard hosted UnoLock deployment, no UnoLock runtime env vars are required at MCP startup. Once the user provides an UnoLock agent key connection URL, the MCP derives the Safe site origin, API base URL, and then fetches the published app version and PQ validation key automatically.

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
* For hosted UnoLock, the connection URL is enough for the MCP to resolve the published app version and PQ validation key automatically.
* For custom deployments, set `UNOLOCK_BASE_URL`, `UNOLOCK_TRANSPARENCY_ORIGIN`, `UNOLOCK_APP_VERSION`, or `UNOLOCK_SIGNING_PUBLIC_KEY` only when overrides are needed.

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
2. If it says a connection URL is needed, ask the user for the one-time-use UnoLock agent key connection URL and, if they configured one, the agent PIN at the same time.
   Treat that URL as enrollment-only, not as a reusable credential.
3. Submit them to the MCP with `unolock_submit_agent_bootstrap`.
4. If the PIN was not collected up front and the Safe later asks for it, set it in MCP memory.
5. Call the one-shot bootstrap/auth flow.
6. Start using read-only tools.

After the MCP process restarts:

1. Ask the MCP for registration status again.
2. If it reports `authenticate_or_set_pin`, ask the user for the agent PIN.
3. Set the PIN in MCP memory.
4. Authenticate and continue using read-only tools.

Relevant tools:

* `unolock_get_registration_status`
* `unolock_get_tpm_diagnostics`
* `unolock_submit_agent_bootstrap`
* `unolock_submit_connection_url`
* `unolock_set_agent_pin`
* `unolock_bootstrap_agent`
* `unolock_list_spaces`
* `unolock_list_notes`
* `unolock_list_checklists`
* `unolock_get_record`

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
* or generate a fresh UnoLock agent key connection URL and register a new agent credential with the current provider
