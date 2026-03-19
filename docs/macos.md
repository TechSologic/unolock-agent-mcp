# macOS Quick Start

macOS support is still alpha. This guide is for evaluation on a Secure Enclave-capable Mac, including Apple Silicon systems such as an M4 Mac.

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

Preferred:

* download the latest macOS binary from `https://github.com/TechSologic/unolock-agent-mcp/releases`

Source-install fallback:

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

Expected provider when the macOS host path works:

* `mac-secure-enclave`
* or `mac-keychain`

If the MCP does not find a production-ready provider, it falls back to the software provider and reports reduced assurance clearly. On macOS, the MCP now tries Secure Enclave first and then falls back to a non-exportable Keychain-backed provider before taking that lower-assurance fallback.

## Configure Your MCP Host

For normal UnoLock cloud-service use, no UnoLock-specific runtime configuration should be necessary.

Your MCP host should launch:

```bash
unolock-agent
```

See:

* [host-config.md](host-config.md)

## First-Use Flow

1. Start the MCP host.
2. Let the agent query registration status.
3. The agent should ask the user for:
   * the UnoLock Agent Key URL
   * the agent PIN
4. The MCP derives the UnoLock origins and runtime compatibility values from the Agent Key URL.
5. If the host path works, the MCP registers the agent with either a Secure Enclave-backed key or a non-exportable Keychain-backed key.
6. After restart, the agent remains registered but must ask the user for the PIN again before re-authenticating.

## Troubleshooting

If `tpm-diagnose` does not report either `mac-secure-enclave` or `mac-keychain`:

* make sure Xcode Command Line Tools are installed
* make sure you are running on a Secure Enclave-capable Mac
* check that the MCP host process can run the Swift helper locally
* retry `python3 -m unolock_mcp tpm-diagnose`

If diagnostics report `OSStatus -34018`:

* run the MCP from a normal logged-in macOS user session
* make sure the login keychain is unlocked and available
* try launching from Terminal.app first
* if a GUI MCP host is launching the MCP, make sure that host can access the user keychain

If the host still cannot use Secure Enclave, do not fall back to an insecure provider for customer use.

## Notes

The macOS Secure Enclave provider is implemented, but Secure Enclave launch-context reliability is still the main blocker on some Macs. The new Keychain-backed non-exportable provider is there to broaden support while keeping a platform-bound key model. Apple Silicon trials are still useful, but treat the overall macOS path as alpha, not broad production rollout.
