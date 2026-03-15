# UnoLock Agent MCP

This repository is the dedicated home for UnoLock's Python agent/MCP client.

UnoLock was built to protect you. Now it can protect both you and your agent.

UnoLock Agent MCP is currently in alpha. It is available for evaluation and early testing, but it is not ready for broad production rollout yet.

## Why Use UnoLock For An Agent

UnoLock Agent MCP is not only about protecting secrets.

It gives an agent a safer place to keep and use:

* secrets
* durable memory
* structured notes
* checklists
* space-scoped working data

Compared to local memory files or plaintext secret storage, UnoLock gives the agent:

* encrypted storage
* controlled access to only the Spaces it should use
* persistence beyond a single local machine or process
* safer recovery from host loss, reset, or replacement
* a stronger access model than reusable API keys or plaintext config secrets

## Security Requirement

UnoLock Agent MCP is built for customers who want the strongest practical protection for AI-accessed secrets.

For normal customer use, the strongest deployment uses a production-ready:

* TPM
* vTPM
* Secure Enclave
* or equivalent platform-backed non-exportable key store

If the host cannot provide one of those, the MCP can still fall back to a lower-assurance software provider. When that happens, the MCP reports the reduced assurance clearly, requires an explicit acknowledgment before use, and makes the reduced-assurance tradeoff visible instead of pretending it met UnoLock's preferred key-storage requirements.

That tradeoff is intentional. Agentic Safe Access exists to keep AI access as close as possible to UnoLock's normal device-bound security model without pretending every host can satisfy the same storage guarantees.

## Intended Environment

UnoLock Agent MCP is designed to work across a wide range of agent environments.

The strongest deployments are environments that can provide device-bound, non-exportable key storage in a normal user-controlled session. That includes:

* desktop AI assistants
* local MCP hosts such as Claude Desktop or Cursor
* user-controlled workstations, laptops, and VMs with TPM/vTPM access
* macOS hosts that can use either Secure Enclave or a non-exportable Keychain-backed key
* Windows or WSL hosts that can use either TPM-backed keys or the non-exportable Windows CNG fallback

Other environments may still work, but they may only be able to provide lower assurance. That commonly includes:

* fully headless background agents
* remote sandboxes
* plain containers without hardware-backed key access

These environments are harder to support because they often cannot satisfy UnoLock's preferred requirement for device-bound, non-exportable key storage in a normal user-controlled session.

Official GitHub repository:

* `https://github.com/TechSologic/unolock-agent-mcp`
* Releases: `https://github.com/TechSologic/unolock-agent-mcp/releases`

Agent-first onboarding site:

* `https://unolock.ai/index.html`
* `https://unolock.ai/install-mcp.html`
* `https://unolock.ai/connect-agent.html`
* `https://unolock.ai/agent-explanation-kit.html`

Recommended customer install source:

* `mcporter` keep-alive plus `npx @techsologic/unolock-agent-mcp@latest` when available
* GitHub Releases binaries
* `npx @techsologic/unolock-agent-mcp@latest` as the Node/npm wrapper path
* `pipx install` as the fallback source install path when no release binary is available yet

If you are new to UnoLock itself, start with these docs first:

* UnoLock Knowledge Base: `https://docs.unolock.com/index.html`
* Agentic Safe Access: `https://docs.unolock.com/features/agentic-safe-access.html`
* Access Keys & Safe Access: `https://docs.unolock.com/features/multi-device-access.html`
* Spaces: `https://docs.unolock.com/features/spaces.html`
* Connect an AI Agent to a Safe: `https://docs.unolock.com/howto/connecting-an-ai-agent.html`

Prerequisite:

* Free and Inheritance can share their single included Safe space with one extra Agent Key.
* Sovereign and HighRisk are still the right tiers for broader multi-Space and collaboration-heavy agent workflows.

The current MCP proves the hardest integration seam first:

* live local `/start` flow compatibility
* ML-DSA signature verification
* ML-KEM encapsulation
* AES-GCM callback decryption

The agent client does not create Safes.

Safe creation remains a human/browser responsibility, matching the product model:

* human admin creates a Safe
* human admin creates an agent access key for that Safe
* MCP registers to the existing Safe
* MCP later authenticates and uses the shared Safe API surface for agent memory, notes, checklists, and secrets

## Quick start

Run this from the repo root after the local server is up on `http://127.0.0.1:3000`:

```bash
./scripts/bootstrap.sh
./scripts/run_local_probe.sh
./scripts/run_stdio_mcp.sh
./scripts/run_local_e2e_readonly.sh
```

For real MCP hosts, see:

* [Install Guide](docs/install.md)
* [macOS Quick Start](docs/macos.md)
* [Supported Environments](docs/supported-environments.md)
* [MCP Host Config](docs/host-config.md)
* [mcporter keep-alive setup](docs/mcporter.md)
* [Support Matrix](docs/support-matrix.md)
* [Tool Catalog](docs/tool-catalog.md)
* [Claude Desktop example](examples/claude-desktop-config.json)
* [Cursor example](examples/cursor-mcp.json)
* [mcporter example](examples/mcporter.json)
* [Config file example](examples/unolock-agent-config.json)

`mcporter` is the preferred path when it is available. The user PIN is kept only in MCP process memory, so keeping the MCP alive means lower latency, fewer repeat PIN prompts, and less pressure for the agent to store the PIN persistently.

If you prefer manual install from source:

```bash
git clone https://github.com/TechSologic/unolock-agent-mcp.git
cd unolock-agent-mcp
python3 -m pip install --user -e .
unolock-agent-probe probe
unolock-agent-mcp mcp
python3 -m unolock_mcp bootstrap --connection-url '<unoLock connection url>' --pin 0123 --list-records
python3 -m unolock_mcp tpm-diagnose
unolock-agent-tpm-check
unolock-agent-self-test
python3 -m unolock_mcp config-check
```

macOS support is still alpha. The MCP now prefers Secure Enclave when it works cleanly and otherwise falls back to a non-exportable macOS Keychain key for broader compatibility. If you are evaluating it on Apple Silicon, start with:

* [macOS Quick Start](docs/macos.md)

The first `liboqs-python` run may build or locate `liboqs` under your home directory. That can take a few minutes.

For the best customer experience, prefer GitHub Release binaries over source installs. Source installs still depend on the local `liboqs-python` / `liboqs` environment.

## Preferred Customer Install

When available, prefer `mcporter` keep-alive plus the npm wrapper or release binary instead of a cold-start bare MCP process.

For an agent-first public onboarding flow, send users or agents to:

* `https://unolock.ai/index.html`

When available, prefer the standalone GitHub Release binaries instead of installing from Git.

That avoids most of the Python packaging and source-build overhead for customers.

If your host environment is already Node/npm-oriented, you can also use the npm wrapper:

```bash
npx @techsologic/unolock-agent-mcp@latest --version
```

The wrapper downloads the correct GitHub Release binary for the current platform on first use and then reuses the cached copy.

On restart, the npm wrapper now checks GitHub Releases for a newer stable binary and will update its cached binary between tasks when a newer release is available.

The npm package is an OpenClaw-friendly install and launch path for the external UnoLock MCP binary.

It is **not** an OpenClaw plugin package for `openclaw plugins install ...`.

Project home:

* `https://github.com/TechSologic/unolock-agent-mcp`

Use it as a command that OpenClaw can launch, for example:

```bash
npx @techsologic/unolock-agent-mcp@latest mcp
```

With no arguments, the npm wrapper starts the MCP server by default:

```bash
npx @techsologic/unolock-agent-mcp@latest
```

Preferred keep-alive example with `mcporter`:

```json
{
  "servers": {
    "unolock-agent": {
      "command": "npx",
      "args": ["@techsologic/unolock-agent-mcp@latest"],
      "lifecycle": "keep-alive"
    }
  }
}
```

## Update Policy

UnoLock Agent MCP should not replace itself in the middle of an active session or write flow.

The intended update model is:

* the MCP reports update status
* the wrapper or runner applies updates
* the runner restarts between tasks so in-memory PINs and sessions can be re-established cleanly

Check update status with:

```bash
unolock-agent-mcp check-update --json
```

Or, through the MCP itself, call:

* `unolock_get_update_status`

Preferred channel behavior:

* `mcporter` + `npx @techsologic/unolock-agent-mcp@latest`
  * preferred low-friction path
  * on restart, the npm wrapper checks GitHub Releases and can fetch the latest stable binary
  * npm publishing is only needed when the wrapper itself changes
* direct GitHub Release binary
  * replace the binary manually, then restart the MCP runner
* Python package install
  * upgrade the package in that environment, then restart the runner

For the best user experience, do updates between tasks, not while an enrollment flow, authentication flow, or sensitive write flow is active.

## Standalone config

Normal setup should not require this section. When the MCP runs outside the main UnoLock monorepo, it can usually derive its UnoLock runtime config from the UnoLock agent key connection URL. Environment variables and config files are primarily for advanced overrides and custom deployments when the normal connection-URL-driven flow is not enough.

Default config file location:

```text
~/.config/unolock-agent-mcp/config.json
```

Advanced override example:

```json
{
  "base_url": "https://api.unolock.example",
  "transparency_origin": "https://safe.unolock.example",
  "signing_public_key_b64": "BASE64_SERVER_PQ_SIGNING_PUBLIC_KEY"
}
```

For normal UnoLock cloud-service use, the MCP can derive the API origin and PQ validation key from the user-provided agent key connection URL automatically. UnoLock remains client-side encrypted, and its design tries to minimize unnecessary identifying exposure. If you want to force the same normal cloud deployment without waiting for a connection URL, this also works:

```json
{
  "base_url": "https://api.safe.unolock.com"
}
```

the MCP will derive `https://safe.unolock.com`, fetch `/unolock-client.json`, and read the published `serverPQValidationKey`. If that deployment metadata file is unavailable, it falls back to the transparency bundle.

Use this command to verify what the MCP resolved:

```bash
python3 -m unolock_mcp config-check
```

TPM provider selection:

* default: `UNOLOCK_TPM_PROVIDER=auto`
* force software provider: `UNOLOCK_TPM_PROVIDER=software`
* force Linux TPM/vTPM provider: `UNOLOCK_TPM_PROVIDER=linux`
* force best macOS provider: `UNOLOCK_TPM_PROVIDER=mac`
* force best Windows provider: `UNOLOCK_TPM_PROVIDER=windows`

On WSL2, `auto` now prefers the Windows TPM helper provider when `powershell.exe` can create TPM-backed keys on the Windows host, and falls back to a non-exportable Windows CNG key when TPM-backed creation is unavailable. This has been validated locally with live registration and authentication. If neither Windows path works, `auto` falls back to the software provider with loud reduced-assurance warnings.

On macOS, `auto` now tries the Secure Enclave provider first and then falls back to a non-exportable Keychain-backed provider. Secure Enclave remains the higher-assurance path, but the Keychain path is there to reduce launch-context friction on real Macs.

## Current capabilities

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
* note and checklist projection from UnoLock `Records` archives
* write-support MVP for notes and checklists with version-aware conflict handling

Installed commands:

* `unolock-agent-probe`
  * run the packaged local probe
* `unolock-agent-mcp`
  * run the stdio MCP server
* `unolock-agent-tpm-check`
  * run the fail-fast production-readiness TPM check

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
* `unolock_create_note`
* `unolock_update_note`
* `unolock_rename_record`
* `unolock_create_checklist`
* `unolock_set_checklist_item_done`
* `unolock_add_checklist_item`
* `unolock_remove_checklist_item`

Registration discovery support:

* the MCP can report whether it is registered
* if not registered, it tells the agent to ask the user for the UnoLock agent key connection URL
* that URL is explicitly treated as one-time-use and enrollment-only
* in the cold-start path, the MCP now prefers that the agent ask for the connection URL and the optional PIN together
* the agent key connection URL can be submitted and stored locally
* `unolock_submit_agent_bootstrap` can submit the connection URL and optional PIN in one step
* the optional agent PIN is held only in MCP process memory and cleared on restart or via `unolock_clear_agent_pin`
* the MCP can now auto-drive `agentRegister` and `agentAccess` through known callbacks using the active TPM DAO
* the Windows TPM helper provider is now usable from WSL2 when `powershell.exe` can reach the Windows Platform Crypto Provider
* the Windows CNG non-exportable fallback provider is now also usable from Windows/WSL when TPM-backed creation is unavailable
* the software provider is the final fallback when the host cannot provide a production-grade provider, and the MCP surfaces that reduced assurance clearly
* once authenticated, the MCP can read UnoLock notes/checklists and project them into plain-text agent-friendly DTOs while keeping the stored Quill/checklist formats unchanged
* the MCP can now create notes and checklists and perform version-aware note/checklist updates within the agent's allowed Spaces
* registration status now reports a `recommended_next_action` and `guidance` field so an agent can tell whether it should ask for an agent key URL, ask for a PIN, start registration, or authenticate
* after the MCP process restarts, the agent stays registered but must ask the user for the PIN again before re-authenticating
* registration state now remembers which TPM provider created the agent key and will tell the host to re-register or force the old provider if there is a provider mismatch
* the MCP can diagnose the active TPM/vTPM provider and give host advice when no working TPM/vTPM is detected

Read and write support:

* `unolock_list_records` accepts `kind`, `space_id`, `pinned`, and `label`
* `unolock_list_notes` and `unolock_list_checklists` are convenience wrappers
* `unolock_list_spaces` returns space metadata plus record counts
* read/list/get responses include `writable`, `allowed_operations`, `version`, `read_only`, and `locked`
* write tools use cache-first optimistic writes with 5-minute in-memory archive TTLs
* archive rereads happen only on cache miss, cache expiry, or upload conflict
* write conflicts return stable structured reasons such as `write_conflict_requires_reread`

Current bootstrap limitation:

* to finish `DecodeKey` and `ClientDataKey`, the MCP still needs the bootstrap AIDK material for the access
* if the connection URL does not include that bootstrap secret, the MCP will stop with a clear blocker instead of faking progress
* that keeps the implementation aligned with UnoLock's current AIDK/CDMK hierarchy instead of bypassing it

## Testing with a local Safe

When you need a real Safe for local testing, use the UnoLock browser Playwright harness from a full UnoLock checkout under `client/e2e-playwright`.

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

For a full local regression run:

```bash
./scripts/run_local_e2e_readonly.sh
```

That script:

* creates a fresh local Safe and agent bootstrap artifact with Playwright
* registers the MCP against that new agent key
* authenticates and reads spaces/records
* simulates an MCP restart
* re-authenticates with the PIN and verifies access again

## Package layout

```text
unolock-agent-mcp/
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
* Production agent auth is intended to use TPM/vTPM or equivalent device-backed storage. The software provider is the lower-assurance fallback when stronger host key protection is not available.
