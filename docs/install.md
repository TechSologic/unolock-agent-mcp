# Install Guide

This guide explains the recommended ways for customers to install the UnoLock Agent MCP.

Official GitHub repository:

* `https://github.com/TechSologic/unolock-agent-mcp`

## Recommended Install Method

For most customers, use `pipx` so the MCP is installed into an isolated environment but still exposes a normal command on `PATH`.

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
python3 -m unolock_mcp tpm-diagnose
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
* `UNOLOCK_ALLOW_INSECURE_PROVIDER` development-only override
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
* if no production-ready TPM, vTPM, or platform-backed provider is available, the MCP now fails closed by default
* `UNOLOCK_ALLOW_INSECURE_PROVIDER=1` is for development only

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
