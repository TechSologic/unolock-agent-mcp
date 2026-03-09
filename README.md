# Agent MCP

This directory is the dedicated home for UnoLock's Python agent/MCP client.

Official GitHub repository:

* `https://github.com/TechSologic/unolock-agent-mcp`

The current prototype proves the hardest integration seam first:

* live local `/start` flow compatibility
* ML-DSA signature verification
* ML-KEM encapsulation
* AES-GCM callback decryption

The agent client does not create Safes.

Safe creation remains a human/browser responsibility, matching the product model:

* human admin creates a Safe
* human admin creates an agent access key for that Safe
* MCP registers to the existing Safe
* MCP later authenticates and uses the shared Safe API surface

## Quick start

Run this from the repo root after the local server is up on `http://127.0.0.1:3000`:

```bash
./agent-mcp/scripts/bootstrap.sh
./agent-mcp/scripts/run_local_probe.sh
./agent-mcp/scripts/run_stdio_mcp.sh
./agent-mcp/scripts/run_local_e2e_readonly.sh
```

For real MCP hosts, see:

* [host-config.md](/home/mike/Unolock/agent-mcp/docs/host-config.md)
* [support-matrix.md](/home/mike/Unolock/agent-mcp/docs/support-matrix.md)
* [tool-catalog.md](/home/mike/Unolock/agent-mcp/docs/tool-catalog.md)
* [claude-desktop-config.json](/home/mike/Unolock/agent-mcp/examples/claude-desktop-config.json)
* [cursor-mcp.json](/home/mike/Unolock/agent-mcp/examples/cursor-mcp.json)

If you prefer manual install:

```bash
cd agent-mcp
python3 -m pip install --user -e .
unolock-agent-probe probe
unolock-agent-mcp mcp
python3 -m unolock_mcp bootstrap --connection-url '<unoLock connection url>' --pin 0123 --list-records
python3 -m unolock_mcp tpm-diagnose
```

The first `liboqs-python` run may build `liboqs` under your home directory. That can take a few minutes.

TPM provider selection:

* default: `UNOLOCK_TPM_PROVIDER=auto`
* force test provider: `UNOLOCK_TPM_PROVIDER=test`
* force Linux TPM/vTPM provider: `UNOLOCK_TPM_PROVIDER=linux`
* force macOS Secure Enclave provider: `UNOLOCK_TPM_PROVIDER=mac`
* force Windows TPM helper provider: `UNOLOCK_TPM_PROVIDER=windows`

On WSL2, `auto` now prefers the Windows TPM helper provider when `powershell.exe` can create TPM-backed keys on the Windows host. This has been validated on this local WSL2 setup with live key creation and challenge signing. If that path fails, it falls back to the test TPM provider.

On macOS, `auto` now prefers the Secure Enclave provider when the Swift/Xcode command-line toolchain is available and the helper can create a non-exportable key. This path is implemented, but still needs validation on real macOS hardware.

## Current prototype

The working path today is the local probe:

* GET `/start?type=access`
* verify `PQ_KEY_EXCHANGE`
* verify the server ML-DSA signature
* encapsulate to the server ML-KEM public key
* POST the PQ callback response
* decrypt the next encrypted callback

On the current local stack this is already returning the next callback successfully.

The package now also exposes a real stdio MCP server with:

* in-memory UnoLock auth-flow session store
* generic `/start` flow bootstrap after PQ negotiation
* generic flow continuation
* generic authenticated `/api` action calls
* convenience wrappers for `GetSpaces` and `GetArchives`
* read-only note and checklist projection from UnoLock `Records` archives

Installed commands:

* `unolock-agent-probe`
  * run the packaged local probe
* `unolock-agent-mcp`
  * run the stdio MCP server

Current MCP tools:

* `unolock_probe_local_server`
* `unolock_get_registration_status`
* `unolock_get_tpm_diagnostics`
* `unolock_set_agent_pin`
* `unolock_clear_agent_pin`
* `unolock_submit_connection_url`
* `unolock_clear_connection_url`
* `unolock_start_registration_from_connection_url`
* `unolock_continue_agent_session`
* `unolock_authenticate_agent`
* `unolock_bootstrap_agent`
* `unolock_start_flow`
* `unolock_continue_flow`
* `unolock_get_session`
* `unolock_list_sessions`
* `unolock_delete_session`
* `unolock_call_api`
* `unolock_get_spaces`
* `unolock_get_archives`
* `unolock_list_spaces`
* `unolock_list_records`
* `unolock_list_notes`
* `unolock_list_checklists`
* `unolock_get_record`

Registration discovery support:

* the MCP can report whether it is registered
* if not registered, it tells the agent to ask the user for the UnoLock agent key connection URL
* the agent key connection URL can be submitted and stored locally
* the optional agent PIN is held only in MCP process memory and cleared on restart or via `unolock_clear_agent_pin`
* the MCP can now auto-drive `agentRegister` and `agentAccess` through known callbacks using the active TPM DAO
* the Windows TPM helper provider is now usable from WSL2 when `powershell.exe` can reach the Windows Platform Crypto Provider
* the test TPM provider still persists a local ECDSA P-256 key so development registration/auth survive MCP restarts
* once authenticated, the MCP can read UnoLock notes/checklists and project them into plain-text agent-friendly DTOs while keeping the stored Quill/checklist formats unchanged
* registration status now reports a `recommended_next_action` and `guidance` field so an agent can tell whether it should ask for an agent key URL, ask for a PIN, start registration, or authenticate
* after the MCP process restarts, the agent stays registered but must ask the user for the PIN again before re-authenticating
* registration state now remembers which TPM provider created the agent key and will tell the host to re-register or force the old provider if there is a provider mismatch
* the MCP can diagnose the active TPM/vTPM provider and give host advice when no working TPM/vTPM is detected

Read-only filtering support:

* `unolock_list_records` accepts `kind`, `space_id`, `pinned`, and `label`
* `unolock_list_notes` and `unolock_list_checklists` are convenience wrappers
* `unolock_list_spaces` returns space metadata plus record counts

Current bootstrap limitation:

* to finish `DecodeKey` and `ClientDataKey`, the MCP still needs the bootstrap AIDK material for the access
* if the connection URL does not include that bootstrap secret, the MCP will stop with a clear blocker instead of faking progress
* that keeps the implementation aligned with UnoLock's current AIDK/CDMK hierarchy instead of bypassing it

## Testing with a local Safe

When you need a real Safe for local testing, use the browser Playwright harness under
[`client/e2e-playwright`]( /home/mike/Unolock/client/e2e-playwright/README.md ).

That harness already covers:

* Safe creation
* virtual WebAuthn registration in Chromium
* Safe open/lifecycle flows

This keeps the boundary clean:

* browser tests create and manage test Safes
* `agent-mcp` only probes or authenticates against an existing Safe

For local agent bootstrap, the create-safe harness can now emit a registration artifact:

```bash
E2E_AGENT_BOOTSTRAP_OUTPUT_FILE=/tmp/unolock-agent-bootstrap.json \
npm --prefix client/e2e-playwright run test:create-safe
cat /tmp/unolock-agent-bootstrap.json
```

That artifact includes:

* the generated UnoLock agent key connection URL
* the access ID used for the agent registration
* the bootstrap secret encoding needed by the MCP
* whether the browser had to fall back to the current access because the Safe tier could not create another device access
* with the default Playwright settings, the local test PIN is `0123`

Current local fallback behavior:

* if the Safe tier permits another device access, the harness creates a dedicated AI-marked access
* if the tier blocks new device accesses, the harness issues an agent registration URL for the current authenticated access instead
* the current-access fallback exists for local/dev testing and is not the preferred long-term product shape

For a full local read-only regression run:

```bash
./agent-mcp/scripts/run_local_e2e_readonly.sh
```

That script:

* creates a fresh local Safe and agent bootstrap artifact with Playwright
* registers the MCP against that new agent key
* authenticates and reads spaces/records
* simulates an MCP restart
* re-authenticates with the PIN and verifies read-only access again

## Package layout

```text
agent-mcp/
  docs/
  scripts/
  src/
    unolock_mcp/
      api/
      auth/
      crypto/
      domain/
      mcp/
      tpm/
      transport/
  tests/
```

## Separation of concerns

* `src/unolock_mcp/tpm/`
  * TPM DAO and provider implementations
* `src/unolock_mcp/crypto/`
  * PQ session negotiation
  * callback AES-GCM helpers
  * AWS Encryption SDK helpers
  * Safe keyring management
* `src/unolock_mcp/transport/`
  * `/start` and `/api` HTTP transport
  * callback DTO handling
* `src/unolock_mcp/auth/`
  * agent registration and access clients
  * local compatibility probe
  * generic flow session store
* `src/unolock_mcp/api/`
  * authenticated Safe API client
* `src/unolock_mcp/domain/`
  * domain objects and DTOs
* `src/unolock_mcp/mcp/`
  * MCP tool surface only

## Notes

* Server-side interop probes can still live under `server/safe-server/scripts/` when they are validating server behavior directly.
* Production agent auth is intended to use TPM/vTPM or equivalent device-backed storage. `TestTpmDao` is for development and interop only.
