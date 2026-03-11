# Install Guide

This guide explains the recommended ways for customers to install the UnoLock Agent MCP.

UnoLock Agent MCP is currently in alpha. The install flow is available for evaluation and early testing, but it is not ready for broad production rollout yet.

## Security Requirement

UnoLock Agent MCP is intended for high-security AI access to Safe data.

For normal customer use, the preferred deployment uses a production-ready:

* TPM
* vTPM
* Secure Enclave
* or equivalent platform-backed non-exportable key store

If the MCP cannot find one, it can still fall back to the software provider. When that happens, the MCP reports that the host is operating at reduced assurance instead of pretending it met UnoLock’s preferred key-storage requirements.

This is deliberate. The point of the Agent MCP is to keep AI access as device-bound and resistant to secret export as the host allows, without hiding when it had to fall back.

On Windows and WSL, the MCP now prefers a TPM-backed key first and falls back to a non-exportable Windows CNG key when TPM-backed creation is unavailable.

Official GitHub repository:

* `https://github.com/TechSologic/unolock-agent-mcp`

The quickest post-install readiness summary is:

```bash
unolock-agent-self-test
```

If you are new to UnoLock, these docs explain the product concepts behind the MCP:

* UnoLock Knowledge Base: `https://safe.unolock.com/docs/`
* Agentic Safe Access: `https://safe.unolock.com/docs/features/agentic-safe-access/`
* Access Keys & Safe Access: `https://safe.unolock.com/docs/features/multi-device-access/`
* Spaces: `https://safe.unolock.com/docs/features/spaces/`
* Connect an AI Agent to a Safe: `https://safe.unolock.com/docs/howto/connecting-an-ai-agent/`

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

3. Install the MCP:

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
unolock-agent-mcp mcp
```

The agent should then ask the user for the UnoLock Agent Key connection URL and optional PIN.

## Recommended Install Method

For most customers, prefer a standalone GitHub Release binary when one is available for your platform.

That avoids most local Python packaging and source-build overhead.

If you are installing from source, use `pipx` so the MCP is installed into an isolated environment but still exposes a normal command on `PATH`.

## Option 0: Install A Standalone Release Binary

If the GitHub Releases page includes a binary for your platform, download that first.

Expected artifact names:

* `unolock-agent-mcp-macos-arm64`
* `unolock-agent-mcp-windows-amd64.exe`
* `unolock-agent-mcp-linux-x86_64`

Then configure your MCP host to run that binary directly.

## Option 1: Install From GitHub With `pipx`

```bash
pipx install git+https://github.com/TechSologic/unolock-agent-mcp.git
```

After install, the MCP command is:

```bash
unolock-agent-mcp mcp
```

Useful extra command:

```bash
unolock-agent-tpm-check
unolock-agent-self-test
python3 -m unolock_mcp tpm-diagnose
python3 -m unolock_mcp config-check
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
cd unolock-agent-mcp
python3 -m pip install --user -e .
```

## Verify The Install

Check that the command is available:

```bash
unolock-agent-mcp --help
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
unolock-agent-mcp mcp
```

See:

* [host-config.md](host-config.md)
* [tool-catalog.md](tool-catalog.md)

## Environment Variables

Common environment variables:

* `UNOLOCK_TPM_PROVIDER`
* `UNOLOCK_BASE_URL` override
* `UNOLOCK_TRANSPARENCY_ORIGIN` override
* `UNOLOCK_APP_VERSION`
* `UNOLOCK_SIGNING_PUBLIC_KEY`
* `UNOLOCK_CONFIG_FILE`

Instead of environment variables, you can also create a config file at:

```text
~/.config/unolock-agent-mcp/config.json
```

Override example:

```json
{
  "base_url": "https://api.unolock.example",
  "transparency_origin": "https://safe.unolock.example",
  "app_version": "1.2.3",
  "signing_public_key_b64": "BASE64_SERVER_PQ_SIGNING_PUBLIC_KEY"
}
```

For most customers:

* `UNOLOCK_TPM_PROVIDER=auto` should remain the default
* for the standard hosted UnoLock deployment, the MCP can derive the Safe site origin, API base URL, app version, and PQ validation key from the UnoLock agent key connection URL
* for custom deployments, only set overrides when automatic discovery is unavailable or you intentionally want to force different values
* if no production-ready TPM, vTPM, or platform-backed provider is available, `auto` falls back to the software provider and reports reduced assurance loudly
* force `UNOLOCK_TPM_PROVIDER=software` when you intentionally want the software provider; `test` remains a legacy alias

## Upgrade

If installed with `pipx`:

```bash
pipx upgrade unolock-agent-mcp
```

If installed directly from GitHub with `pip`:

```bash
python3 -m pip install --upgrade git+https://github.com/TechSologic/unolock-agent-mcp.git
```

## Uninstall

If installed with `pipx`:

```bash
pipx uninstall unolock-agent-mcp
```

If installed with `pip`:

```bash
python3 -m pip uninstall unolock-agent-mcp
```

If you also want to remove the local UnoLock registration from the host before uninstalling, run:

```bash
python3 -m unolock_mcp disconnect
```

## Troubleshooting `liboqs-python`

The UnoLock Agent MCP currently depends on `liboqs-python` `0.14.x`.

If your environment already has a working local `liboqs` installation, you can point Python at it with:

```bash
export OQS_INSTALL_PATH=/path/to/liboqs-install
```

This should be treated as an advanced override or temporary workaround, not a normal customer setup step.

If you want to avoid local `liboqs` setup friction entirely, prefer the standalone GitHub Release binary for your platform when one is available.
