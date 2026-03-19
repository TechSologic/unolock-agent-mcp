# Install Guide

This guide explains the recommended ways for customers to install UnoLock Agent.

UnoLock Agent is currently in alpha. The install flow is available for evaluation and early testing, but it is not ready for broad production rollout yet.

If you want the current public agent-first onboarding path, start with:

* `https://unolock.ai/index.html`
* `https://unolock.ai/install-mcp.html`

## Security Requirement

UnoLock Agent is intended for high-security AI access to Safe data.

For normal customer use, the preferred deployment uses a production-ready:

* TPM
* vTPM
* Secure Enclave
* or equivalent platform-backed non-exportable key store

If the MCP cannot find one, it can still fall back to the software provider. When that happens, the MCP reports that the host is operating at reduced assurance and makes that tradeoff visible instead of pretending it met UnoLock’s preferred key-storage requirements.

This is deliberate. The point of UnoLock Agent is to keep AI access as device-bound and resistant to secret export as the host allows, without hiding when it had to fall back.

On Windows and WSL, the MCP now prefers a TPM-backed key first and falls back to a non-exportable Windows CNG key when TPM-backed creation is unavailable.

Official GitHub repository:

* `https://github.com/TechSologic/unolock-agent-mcp`
* Releases: `https://github.com/TechSologic/unolock-agent-mcp/releases`

The quickest post-install readiness summary is:

```bash
unolock-agent-self-test
```

If you are new to UnoLock, these docs explain the product concepts behind the MCP:

* UnoLock Knowledge Base: `https://docs.unolock.com/index.html`
* Agentic Safe Access: `https://docs.unolock.com/features/agentic-safe-access.html`
* Access Keys & Safe Access: `https://docs.unolock.com/features/multi-device-access.html`
* Spaces: `https://docs.unolock.com/features/spaces.html`
* Connect an AI Agent to a Safe: `https://docs.unolock.com/howto/connecting-an-ai-agent.html`

## Recommended Customer Install

The preferred path is:

1. use a GitHub Release binary or `npx -y @techsologic/unolock-agent@latest`
2. prefer the CLI commands for normal agent use
3. use `unolock-agent mcp` only when the host specifically requires MCP
4. let UnoLock handle its local daemon internally so the user PIN can stay in process memory instead of being stored persistently

On a fresh host, the first start can take longer than later launches because local cryptographic code may need to be compiled or prepared. Agents should allow for that before treating the MCP as hung.

If you need the public-facing explanation of this path, see:

* `https://unolock.ai/install-mcp.html`

For most customers, prefer a standalone GitHub Release binary for your platform.

That avoids most local Python packaging and source-build overhead.

Download from:

* `https://github.com/TechSologic/unolock-agent-mcp/releases`

If your host environment is already Node/npm-oriented, you can also use the npm wrapper:

```bash
npx -y @techsologic/unolock-agent@latest --version
```

The wrapper downloads the matching GitHub Release binary for the current platform on first use and then reuses the cached copy.

On restart, the npm wrapper checks GitHub Releases for a newer stable binary and can update its cached binary between tasks.

The npm package is an OpenClaw-friendly install and launch path for the UnoLock executable.
It can also act as an OpenClaw plugin package that ships the UnoLock skill.

For normal direct use, prefer commands like:

```bash
npx -y @techsologic/unolock-agent@latest link-agent-key '<agent-key-url>' '<pin>'
npx -y @techsologic/unolock-agent@latest list-spaces
npx -y @techsologic/unolock-agent@latest list-notes
npx -y @techsologic/unolock-agent@latest list-files
```

Project home:

* `https://github.com/TechSologic/unolock-agent-mcp`

Use it as a command that OpenClaw can launch, for example:

```bash
npx -y @techsologic/unolock-agent@latest mcp
```

If you want OpenClaw to load the UnoLock skill as a plugin, the intended published install path is:

```bash
openclaw plugins install @techsologic/unolock-agent
```

For local testing before publishing that plugin install path, use `plugins.load.paths` to point OpenClaw at this repo and enable the `unolock-agent-access` plugin.

For a host-managed stdio launch, use:

```bash
npx -y @techsologic/unolock-agent@latest mcp
```

UnoLock manages its own local daemon automatically after launch, so the agent does not need to manage daemon mode or any separate runner. The `mcp` subcommand uses that daemon-backed runtime. On a fresh host, that first start can also be slower because local cryptographic code may need to be compiled or prepared.

The same executable also supports explicit CLI commands such as:

```bash
unolock-agent link-agent-key 'https://safe.example/#/agent-register/...' 1
unolock-agent list-spaces
unolock-agent list-notes
unolock-agent create-note "Todo" "Buy milk"
unolock-agent list-files
```

Use the explicit `mcp` subcommand for daemon-backed stdio MCP mode. Explicit subcommands are daemon-backed CLI mode.

## Built-in local daemon

The UnoLock executable now includes its own local daemon. That is the preferred persistence model and it is normally internal to the executable rather than something the agent needs to manage directly.

Useful support commands:

```bash
unolock-agent start
unolock-agent status
unolock-agent tools
unolock-agent call unolock_list_spaces
unolock-agent stop
```

Notes:

* MCP hosts usually do not need these commands at all; they just launch `unolock-agent` and speak stdio JSON-RPC.
* `start` starts the local daemon only if it is not already running.
* `tools` and `call` auto-start the daemon if needed.
* the current Space, auth state, and PIN-in-memory behavior belong to the UnoLock daemon itself

## Updates

UnoLock Agent updates should normally be handled by the install channel, not by the live MCP process replacing itself mid-session.

Recommended update flow:

1. check update status
2. finish the current task or flow
3. restart the UnoLock MCP
4. let the wrapper, binary replacement, or package manager apply the update

Check update status locally:

```bash
unolock-agent check-update --json
```

Or through the MCP:

* `unolock_get_update_status`

Preferred behavior by channel:

* built-in local daemon + `npx -y @techsologic/unolock-agent@latest`
  * preferred path
  * daemon restart lets the npm wrapper check GitHub Releases and fetch a newer stable binary
* direct GitHub Release binary
  * download the latest binary, replace the current executable, restart the UnoLock MCP
* source/Python install
  * upgrade the Python package in the environment that launches the MCP, restart the UnoLock MCP

Do not update in the middle of:

* active registration/authentication
* a sensitive write flow
* a task that depends on the current in-memory PIN remaining available

Expected artifact names:

* `unolock-agent-macos-arm64`
* `unolock-agent-windows-amd64.exe`
* `unolock-agent-linux-x86_64`

Then configure your MCP host to run that binary directly.

## macOS Quick Start

macOS support is still alpha. The MCP now prefers Secure Enclave first and falls back to a non-exportable Keychain-backed provider for broader compatibility on real Macs.

If you are installing on a Secure Enclave-capable Mac, especially Apple Silicon:

1. Install Apple Xcode Command Line Tools:

```bash
xcode-select --install
```

2. Install `pipx` if you do not already have it:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

3. Preferred: download the latest macOS release binary from:

```text
https://github.com/TechSologic/unolock-agent-mcp/releases
```

If you need the source-install fallback instead, install the MCP with:

```bash
pipx install git+https://github.com/TechSologic/unolock-agent-mcp.git
```

4. Verify Secure Enclave readiness:

```bash
python3 -m unolock_mcp tpm-diagnose
```

Expected provider on macOS when the host is working:

* `mac-secure-enclave`
* or `mac-keychain`

Then configure your MCP host to launch:

```bash
unolock-agent
```

The agent should then ask the user for the UnoLock Agent Key URL and PIN together.

## Option 0: Install A Standalone Release Binary

Download the latest platform binary from:

* `https://github.com/TechSologic/unolock-agent-mcp/releases`

Expected artifact names:

* `unolock-agent-macos-arm64`
* `unolock-agent-windows-amd64.exe`
* `unolock-agent-linux-x86_64`

Then configure your MCP host to run that binary directly.

## Option 1: Install From GitHub With `pipx`

Use this when you need a source install rather than a release binary.

```bash
pipx install git+https://github.com/TechSologic/unolock-agent-mcp.git
```

After install, the MCP command is:

```bash
unolock-agent
```

Useful extra command:

```bash
unolock-agent-tpm-check
unolock-agent-self-test
python3 -m unolock_mcp tpm-diagnose
python3 -m unolock_mcp config-check
```

For normal installs, do not drive the CLI `bootstrap` command directly. Prefer the normal MCP flow:

```text
run the MCP
provide the Agent Key URL and PIN together
let the MCP continue
```

If you are doing manual CLI recovery or local debugging and the MCP falls back to the software provider, the CLI bootstrap path is still:

```bash
python3 -m unolock_mcp bootstrap --connection-url '<unoLock connection url>' --pin 0123
```

## Option 2: Install From GitHub With `pip`

```bash
python3 -m pip install git+https://github.com/TechSologic/unolock-agent-mcp.git
```

This is acceptable, but `pipx` is preferred for desktop MCP hosts because it avoids mixing MCP dependencies into a user’s main Python environment.

## Option 3: Install From a Local Checkout

This is mainly for development and local testing:

```bash
git clone https://github.com/TechSologic/unolock-agent-mcp.git
cd unolock-agent
python3 -m pip install --user -e .
```

## Verify The Install

Check that the command is available:

```bash
unolock-agent --help
python3 -m unolock_mcp --help
```

Check TPM/vTPM readiness:

```bash
unolock-agent-tpm-check
python3 -m unolock_mcp tpm-diagnose
```

If you want to confirm that the PQ dependency is importable before first live use:

```bash
python3 -c "import oqs; print('liboqs-python ok')"
```

## Host Configuration

Once installed, configure your MCP host to run:

```bash
unolock-agent
```

See:

* [host-config.md](host-config.md)
* [tool-catalog.md](tool-catalog.md)

## Environment Variables

These are advanced overrides, not part of the normal setup flow. In the normal flow, the agent should only need to run the bridge, receive the one-time UnoLock Agent Key URL, and ask for the PIN.

Common advanced environment variables:

* `UNOLOCK_TPM_PROVIDER`
* `UNOLOCK_BASE_URL` override
* `UNOLOCK_TRANSPARENCY_ORIGIN` override
* `UNOLOCK_SIGNING_PUBLIC_KEY`
* `UNOLOCK_CONFIG_FILE`

Instead of environment variables, you can also use the local UnoLock config file if you are dealing with an advanced override case.

Advanced override example:

```json
{
  "base_url": "https://api.unolock.example",
  "transparency_origin": "https://safe.unolock.example",
  "signing_public_key_b64": "BASE64_SERVER_PQ_SIGNING_PUBLIC_KEY"
}
```

For most customers:

* `UNOLOCK_TPM_PROVIDER=auto` should remain the default
* for normal UnoLock cloud-service use, the MCP can derive the Safe site origin, API base URL, and PQ validation key from the UnoLock Agent Key URL
* UnoLock is a cloud service, but Safe data remains client-side encrypted, no identity is linked to a Safe, and the system is designed to minimize unnecessary metadata and correlation exposure
* for custom deployments, only set overrides when automatic discovery is unavailable or you intentionally want to force different values
* if no production-ready TPM, vTPM, or platform-backed provider is available, `auto` falls back to the software provider and reports reduced assurance loudly
* force `UNOLOCK_TPM_PROVIDER=software` when you intentionally want the software provider; `test` remains a legacy alias

## Upgrade

If installed with `pipx`:

```bash
pipx upgrade unolock-agent
```

If installed directly from GitHub with `pip`:

```bash
python3 -m pip install --upgrade git+https://github.com/TechSologic/unolock-agent-mcp.git
```

## Uninstall

If installed with `pipx`:

```bash
pipx uninstall unolock-agent
```

If installed with `pip`:

```bash
python3 -m pip uninstall unolock-agent
```

If you also want to remove the local UnoLock registration from the host before uninstalling, run:

```bash
python3 -m unolock_mcp disconnect
```

## Troubleshooting `liboqs-python`

UnoLock Agent currently depends on `liboqs-python` `0.14.x`.

If your environment already has a working local `liboqs` installation, you can point Python at it with:

```bash
export OQS_INSTALL_PATH=/path/to/liboqs-install
```

This should be treated as an advanced override or temporary workaround, not a normal customer setup step.

If you want to avoid local `liboqs` setup friction entirely, prefer the standalone GitHub Release binary for your platform when one is available.
