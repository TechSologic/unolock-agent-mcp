# macOS Quick Start

This guide is the shortest path for trying the UnoLock Agent MCP on a Secure Enclave-capable Mac, including Apple Silicon systems such as an M4 Mac.

## Prerequisites

Install Apple Xcode Command Line Tools:

```bash
xcode-select --install
```

You also need:

* Python `3.10+`
* `pipx` recommended for installation

Install `pipx` if needed:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

## Install

```bash
pipx install git+https://github.com/TechSologic/unolock-agent-mcp.git
```

If you prefer `pip`:

```bash
python3 -m pip install git+https://github.com/TechSologic/unolock-agent-mcp.git
```

## Verify Secure Enclave Access

Run:

```bash
python3 -m unolock_mcp tpm-diagnose
```

Expected production-ready provider:

* `mac-secure-enclave`

If the MCP does not find a production-ready provider, it now fails closed by default. That means the agent should not continue registration on that host until the Secure Enclave path is working.

## Configure Your MCP Host

For normal hosted UnoLock use, no UnoLock-specific runtime configuration should be necessary.

Your MCP host should launch:

```bash
unolock-agent-mcp mcp
```

See:

* [host-config.md](host-config.md)

## First-Use Flow

1. Start the MCP host.
2. Let the agent query registration status.
3. The agent should ask the user for:
   * the UnoLock Agent Key connection URL
   * the optional agent PIN, if one was configured
4. The MCP derives the UnoLock origins and runtime compatibility values from the connection URL.
5. The MCP registers the agent with a Secure Enclave-backed key.
6. After restart, the agent remains registered but must ask the user for the PIN again before re-authenticating.

## Troubleshooting

If `tpm-diagnose` does not report `mac-secure-enclave`:

* make sure Xcode Command Line Tools are installed
* make sure you are running on a Secure Enclave-capable Mac
* check that the MCP host process can run the Swift helper locally
* retry `python3 -m unolock_mcp tpm-diagnose`

If the host still cannot use Secure Enclave, do not fall back to an insecure provider for customer use.

## Notes

The macOS Secure Enclave provider is implemented and intended for production use, but it still needs broader real-hardware validation across more Macs. An Apple Silicon trial is exactly the right next step.
