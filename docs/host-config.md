# MCP Host Config

This document shows the current easiest way to run the UnoLock agent MCP in real MCP hosts.

Checked against the official host docs on 2026-03-08:

* Anthropic Claude Code / Claude Desktop MCP docs:
  * https://docs.anthropic.com/en/docs/claude-code/mcp
* Cursor MCP docs:
  * https://docs.cursor.com/advanced/model-context-protocol

## Recommended install mode

For the current prototype, install from the UnoLock repo checkout itself:

```bash
cd /path/to/Unolock/agent-mcp
python3 -m pip install --user -e .
```

That matters because the MCP can then auto-resolve:

* `UNOLOCK_APP_VERSION`
* `UNOLOCK_SIGNING_PUBLIC_KEY`

from the local UnoLock repo.

If you run the package outside the UnoLock repo, set these environment variables explicitly:

* `UNOLOCK_BASE_URL`
* `UNOLOCK_APP_VERSION`
* `UNOLOCK_SIGNING_PUBLIC_KEY`
* optionally `UNOLOCK_TPM_PROVIDER`

TPM provider modes:

* `auto`: prefer a real TPM-backed provider for the current host, otherwise fall back to the test TPM provider
* `test`: always use the test TPM provider
* `linux`: force the Linux TPM/vTPM provider
* `mac`: force the macOS Secure Enclave provider
* `windows`: force the Windows TPM helper provider

WSL2 note:

* WSL2 usually does not expose `/dev/tpmrm0` or `/dev/tpm0`
* on WSL2, `auto` now prefers the Windows TPM helper provider
* if the Windows helper cannot create TPM-backed keys, `auto` falls back to the test provider
* for production use, WSL2 should use the Windows TPM helper path, not the Linux TPM path

macOS note:

* on macOS, `auto` will prefer the Secure Enclave provider when the helper can create a Secure Enclave key
* the current implementation uses a small Swift helper that talks to Security.framework
* this path is implemented but still needs validation on a real Secure Enclave-capable Mac

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
        "UNOLOCK_BASE_URL": "http://127.0.0.1:3000",
        "UNOLOCK_TPM_PROVIDER": "auto"
      }
    }
  }
}
```

Notes:

* If `unolock-agent-mcp` is already on your `PATH`, you can use `"command": "unolock-agent-mcp"`.
* For local development, keep `UNOLOCK_BASE_URL` pointed at the local SAM server.
* If the install is not tied to the UnoLock repo checkout, also set:
  * `UNOLOCK_APP_VERSION`
  * `UNOLOCK_SIGNING_PUBLIC_KEY`

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
        "UNOLOCK_BASE_URL": "http://127.0.0.1:3000",
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
        "UNOLOCK_BASE_URL": "http://127.0.0.1:3000",
        "UNOLOCK_TPM_PROVIDER": "auto"
      }
    }
  }
}
```

## First-use flow

Once the host can launch the MCP:

1. Ask the MCP for registration status.
2. If it says a connection URL is needed, ask the user for the UnoLock agent key connection URL.
3. Submit the URL to the MCP.
4. If the Safe uses an agent PIN, ask the user for it and set it in MCP memory.
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
cd /path/to/Unolock/agent-mcp
python3 -m unolock_mcp tpm-diagnose
```

The diagnostic reports:

* active provider name
* whether the provider is production-ready
* whether the host appears to have a working TPM/vTPM
* concrete advice when the host does not
* whether a stored agent registration was created with a different TPM provider than the one currently selected

If the MCP reports a TPM provider mismatch after you change hosts or switch `UNOLOCK_TPM_PROVIDER`, either:

* re-run the MCP with the provider that originally registered the agent key
* or generate a fresh UnoLock agent key connection URL and register a new agent credential with the current provider
