# UnoLock Agent

This repository is the dedicated home for UnoLock's local agent client.

UnoLock was built to protect you. Now it can protect both you and your agent.

UnoLock Agent is currently in alpha. It is available for evaluation and early testing, but it is not ready for broad production rollout yet.

## Start With The Skill

For skill-aware agents, the primary starting point is the UnoLock agent-access skill:

* [skills/unolock-agent-access/SKILL.md](skills/unolock-agent-access/SKILL.md)
* `https://github.com/TechSologic/unolock-agent/blob/main/skills/unolock-agent-access/SKILL.md`

That skill is the agent-facing onboarding layer.

For OpenClaw, this package can also be installed as a plugin so OpenClaw can load the same skill natively.

## Why Use UnoLock For An Agent

UnoLock Agent is not only about protecting secrets.

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

UnoLock Agent is built for customers who want the strongest practical protection for AI-accessed secrets.

For normal customer use, the strongest deployment uses a production-ready:

* TPM
* vTPM
* Secure Enclave
* or equivalent platform-backed non-exportable key store

If the host cannot provide one of those, UnoLock Agent can still fall back to a lower-assurance software provider. When that happens, UnoLock reports the reduced assurance clearly and makes the reduced-assurance tradeoff visible instead of pretending it met UnoLock's preferred key-storage requirements.

That tradeoff is intentional. Agentic Safe Access exists to keep AI access as close as possible to UnoLock's normal device-bound security model without pretending every host can satisfy the same storage guarantees.

## Intended Environment

UnoLock Agent is designed to work across a wide range of agent environments.

The strongest deployments are environments that can provide device-bound, non-exportable key storage in a normal user-controlled session. That includes:

* desktop AI assistants
* local AI hosts such as Claude Desktop or Cursor
* user-controlled workstations, laptops, and VMs with TPM/vTPM access
* macOS hosts that can use either Secure Enclave or a non-exportable Keychain-backed key
* Windows or WSL hosts that can use either TPM-backed keys or the non-exportable Windows CNG fallback

Other environments may still work, but they may only be able to provide lower assurance. That commonly includes:

* fully headless background agents
* remote sandboxes
* plain containers without hardware-backed key access

These environments are harder to support because they often cannot satisfy UnoLock's preferred requirement for device-bound, non-exportable key storage in a normal user-controlled session.

Official GitHub repository:

* `https://github.com/TechSologic/unolock-agent`
* Releases: `https://github.com/TechSologic/unolock-agent/releases`

Agent-first onboarding site:

* `https://unolock.ai/index.html`
* `https://unolock.ai/install-mcp.html`
* `https://unolock.ai/connect-agent.html`
* `https://unolock.ai/agent-explanation-kit.html`

Recommended customer install source:

* UnoLock's built-in local runtime/CLI with a GitHub Release binary when available
* `npx -y @techsologic/unolock-agent@latest` as the easiest Node/npm CLI path
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

The current agent runtime proves the hardest integration seam first:

* live local `/start` flow compatibility
* ML-DSA signature verification
* ML-KEM encapsulation
* AES-GCM callback decryption

The agent client does not create Safes.

Safe creation remains a human/browser responsibility, matching the product model:

* human admin creates a Safe
* human admin creates an agent access key for that Safe
* UnoLock Agent registers to the existing Safe
* UnoLock Agent later authenticates and uses the shared Safe API surface for agent memory, notes, checklists, and secrets

## Quick start

Run this from the repo root after the local server is up on `http://127.0.0.1:3000`:

```bash
./scripts/bootstrap.sh
./scripts/run_local_probe.sh
./scripts/run_stdio_mcp.sh
./scripts/run_local_e2e_readonly.sh
```

For host configuration and implementation details, see:

* [Install Guide](docs/install.md)
* [macOS Quick Start](docs/macos.md)
* [Supported Environments](docs/supported-environments.md)
* [MCP Host Config](docs/host-config.md)
* [Support Matrix](docs/support-matrix.md)
* [Tool Catalog](docs/tool-catalog.md)
* [Claude Desktop example](examples/claude-desktop-config.json)
* [Cursor example](examples/cursor-mcp.json)
* [OpenClaw MCP example](examples/openclaw-mcp.json)
* [OpenClaw plugin config example](examples/openclaw-plugin-config.json)

For skill-aware agents, start with the skill above.
For direct agent use, prefer the CLI. If `unolock-agent` is already installed, use it directly. Only use `npx -y @techsologic/unolock-agent@latest ...` when the executable is not installed yet. Run the command you need directly.

```bash
unolock-agent register 'https://safe.example/#/agent-register/...' 1
unolock-agent list-spaces
unolock-agent list-notes
unolock-agent list-files
```

Only if the executable is not installed yet, use the same commands through:

```bash
npx -y @techsologic/unolock-agent@latest register 'https://safe.example/#/agent-register/...' 1
```

Only if a host needs the explicit host-command form, use:

* `npx -y @techsologic/unolock-agent@latest mcp`
* The host writes JSON-RPC to `stdin` and reads JSON-RPC from `stdout`.
* The `mcp` subcommand starts and uses UnoLock automatically.
* On a fresh host, the first start can take longer because local cryptographic code may need to be compiled or prepared.

That keeps the user PIN in process memory and keeps the current Space selected.

The same executable also supports explicit CLI commands, for example:

```bash
unolock-agent register 'https://safe.example/#/agent-register/...' 1
unolock-agent list-spaces
unolock-agent list-notes
unolock-agent create-note "Todo" "Buy milk"
unolock-agent list-files
```

Use the explicit `mcp` subcommand only for hosts that require that command shape. Running `unolock-agent` with no arguments prints usage.

Once the local UnoLock Agent is running, the normal flow is:

* call normal UnoLock tools
* provide the one-time Agent Key URL and PIN together when UnoLock asks for setup
* let UnoLock keep and use the current Space by default for normal work

If you prefer manual install from source:

```bash
git clone https://github.com/TechSologic/unolock-agent.git
cd unolock-agent
python3 -m pip install --user -e .
unolock-agent-probe probe
unolock-agent --help
unolock-agent mcp
python3 -m unolock_mcp tpm-diagnose
unolock-agent-tpm-check
unolock-agent-self-test
python3 -m unolock_mcp config-check
```

For normal customer and agent onboarding, do not drive the CLI `bootstrap` command directly.
Let UnoLock guide the normal flow.

macOS support is still alpha. UnoLock Agent now prefers Secure Enclave when it works cleanly and otherwise falls back to a non-exportable macOS Keychain key for broader compatibility. If you are evaluating it on Apple Silicon, start with:

* [macOS Quick Start](docs/macos.md)

The first `liboqs-python` run may build or locate `liboqs` under your home directory. That can take a few minutes, so agents should not assume the first startup is hung just because it is slower than later launches.

For the best customer experience, prefer GitHub Release binaries over source installs. Source installs still depend on the local `liboqs-python` / `liboqs` environment.

## Preferred Customer Install

When available, prefer the built-in UnoLock local runtime plus the npm wrapper or release binary.

For an agent-first public onboarding flow, send users or agents to:

* `https://unolock.ai/index.html`

When available, prefer the standalone GitHub Release binaries instead of installing from Git.

That avoids most of the Python packaging and source-build overhead for customers.

If your host environment is already Node/npm-oriented, you can also use the npm wrapper:

```bash
npx -y @techsologic/unolock-agent@latest --version
```

The wrapper downloads the correct GitHub Release binary for the current platform on first use and then reuses the cached copy.

On restart, the npm wrapper now checks GitHub Releases for a newer stable binary and will update its cached binary between tasks when a newer release is available.

The npm package is both:

* the normal UnoLock executable package
* an OpenClaw plugin package that ships the UnoLock skill

Project home:

* `https://github.com/TechSologic/unolock-agent`

Use it as a command that OpenClaw can launch, for example:

```bash
npx -y @techsologic/unolock-agent@latest mcp
```

For hosts that require the command form, use the explicit `mcp` argument:

```bash
npx -y @techsologic/unolock-agent@latest mcp
```

That is the preferred host-facing launch shape.

## Update Policy

UnoLock Agent should not replace itself in the middle of an active session or write flow.

The intended update model is:

* the MCP reports update status
* the install channel applies updates
* the UnoLock process restarts between tasks so in-memory PINs and sessions can be re-established cleanly

Check update status with:

```bash
unolock-agent check-update --json
```

Or, through the MCP itself, call:

* `unolock_get_update_status`

Preferred channel behavior:

* built-in daemon + `npx -y @techsologic/unolock-agent@latest`
  * preferred low-friction path
  * on restart, the npm wrapper checks GitHub Releases and can fetch the latest stable binary
  * npm publishing is only needed when the wrapper itself changes
* direct GitHub Release binary
  * replace the binary manually, then restart the UnoLock MCP
* Python package install
  * upgrade the package in that environment, then restart the UnoLock MCP

For the best user experience, do updates between tasks, not while a setup flow, authentication flow, or sensitive write flow is active.

## Standalone config

Normal setup should not require this section. When the MCP runs outside the main UnoLock monorepo, it can usually derive its UnoLock runtime config from the UnoLock Agent Key URL. Environment variables and config files are advanced overrides for custom deployments or broken metadata, not part of the normal agent flow.

Advanced override example:

```json
{
  "base_url": "https://api.unolock.example",
  "transparency_origin": "https://safe.unolock.example",
  "signing_public_key_b64": "BASE64_SERVER_PQ_SIGNING_PUBLIC_KEY"
}
```

For normal UnoLock cloud-service use, the MCP can derive the API origin and PQ validation key from the user-provided Agent Key URL automatically. UnoLock remains client-side encrypted, no identity is linked to a Safe, and the design tries to minimize unnecessary metadata and correlation exposure. If you want to force the same normal cloud deployment without waiting for an Agent Key URL, this also works:

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

* single active UnoLock auth-flow state machine
* generic `/start` flow bootstrap after PQ negotiation
* generic flow continuation
* generic authenticated `/api` action calls
* convenience wrappers for `GetSpaces` and `GetArchives`
* note and checklist projection from UnoLock `Records` archives
* write-support MVP for notes and checklists with version-aware conflict handling

Installed commands:

* `unolock-agent-probe`
  * run the packaged local probe
* `unolock-agent`
  * run the CLI and print usage with no arguments
  * use `unolock-agent mcp` for stdio MCP mode
* `unolock-agent-tpm-check`
  * run the fail-fast production-readiness TPM check

Current MCP tools:

* `unolock_set_agent_pin`
* `unolock_register`
* `unolock_list_spaces`
* `unolock_get_current_space`
* `unolock_set_current_space`
* `unolock_list_records`
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

Low-level flow and raw API debug tools are hidden by default. Enable them only for debugging with `UNOLOCK_MCP_ENABLE_ADVANCED_TOOLS=1`.
* the software provider is the final fallback when the host cannot provide a production-grade provider, and the MCP surfaces that reduced assurance clearly
* once authenticated, the MCP can read UnoLock notes/checklists and project them into plain-text agent-friendly DTOs while keeping the stored Quill/checklist formats unchanged
* the MCP can now create notes and checklists and perform version-aware note/checklist updates, note appends, and checklist updates within the agent's allowed Spaces
* the MCP now keeps one current Space and uses it as the default for normal read, write, and Cloud file operations
* registration status now reports a `recommended_next_action` and `guidance` field so an agent can tell whether it should ask for an agent key URL, ask for a PIN, start registration, or authenticate
* after the MCP process restarts, the agent stays registered but must ask the user for the PIN again before re-authenticating
* registration state now remembers which TPM provider created the agent key and will tell the host to re-register or force the old provider if there is a provider mismatch
* the MCP can diagnose the active TPM/vTPM provider and give host advice when no working TPM/vTPM is detected

Read and write support:

* `unolock_list_records` accepts `kind`, `pinned`, and `label`
* `unolock_list_notes` and `unolock_list_checklists` are convenience wrappers
* `unolock_list_spaces` marks the current Space, and `unolock_get_current_space` / `unolock_set_current_space` manage that default
* `unolock_list_files` exposes only `Cloud` archives; `Local` and `Msg` archives are intentionally excluded
* `unolock_list_spaces` returns space metadata plus record counts and Cloud file counts
* normal read and write tools use the current Space automatically and include the `space_id` they actually used in their responses
* read/list/get responses include `writable`, `allowed_operations`, `version`, `read_only`, and `locked`
* write tools use cache-first optimistic writes with 5-minute in-memory archive TTLs
* archive rereads happen only on cache miss, cache expiry, or upload conflict
* write conflicts return stable structured reasons such as `write_conflict_requires_reread`
* `unolock_upload_file` creates a `Cloud` archive and uploads encrypted multipart chunks like the web client path
* `unolock_download_file` reconstructs multipart Cloud archives part by part before writing plaintext to the local filesystem
* `unolock_rename_file` updates only Cloud file metadata and keeps the archive in place
* `unolock_replace_file` reuses the existing Cloud archive ID while replacing file contents
* `unolock_delete_file` removes the Cloud archive when the Agent Key is writable

Current bootstrap limitation:

* to finish `DecodeKey` and `ClientDataKey`, the MCP still needs the bootstrap AIDK material for the access
* if the Agent Key URL does not include that bootstrap secret, the MCP will stop with a clear blocker instead of faking progress
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

* the generated UnoLock Agent Key URL
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
unolock-agent/
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
  * single-flow auth state and local registration state
* `src/unolock_mcp/api/`
  * authenticated Safe API client
* `src/unolock_mcp/domain/`
  * domain objects and DTOs
* `src/unolock_mcp/mcp/`
  * MCP tool surface only

## Notes

* Server-side interop probes can still live under `server/safe-server/scripts/` when they are validating server behavior directly.
* Production agent auth is intended to use TPM/vTPM or equivalent device-backed storage. The software provider is the lower-assurance fallback when stronger host key protection is not available.
If you want OpenClaw to load the UnoLock skill as a plugin, the intended published install path is:

```bash
openclaw plugins install @techsologic/unolock-agent
```

For local testing before publishing that plugin path, point OpenClaw at this repo through `plugins.load.paths` and enable the `unolock-agent-access` plugin. See [examples/openclaw-plugin-config.json](examples/openclaw-plugin-config.json).
