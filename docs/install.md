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

* [host-config.md](/home/mike/Unolock/agent-mcp/docs/host-config.md)
* [tool-catalog.md](/home/mike/Unolock/agent-mcp/docs/tool-catalog.md)

## Environment Variables

Common environment variables:

* `UNOLOCK_BASE_URL`
* `UNOLOCK_TPM_PROVIDER`
* `UNOLOCK_APP_VERSION`
* `UNOLOCK_SIGNING_PUBLIC_KEY`

For most customers:

* `UNOLOCK_BASE_URL` should point at the UnoLock server they are using
* `UNOLOCK_TPM_PROVIDER=auto` should remain the default

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
