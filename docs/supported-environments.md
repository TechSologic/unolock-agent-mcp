# Supported Environments

UnoLock Agent MCP is best suited to **user-adjacent desktop or VM hosts** where a strong device-bound or platform-bound key can be created without unusual setup.

## Best fit today

* Windows desktop/laptop with TPM
* WSL2 using the Windows TPM helper
* Linux desktop, workstation, or VM with TPM/vTPM
* macOS desktop/laptop when either:
  * Secure Enclave works cleanly in the current launch context
  * or the Keychain-backed non-exportable fallback works

## Weaker fit

* plain Docker containers
* Kubernetes pods without a host or VM trust path
* fully remote or unattended agent sandboxes
* environments where the user cannot provide a connection URL and, if needed, a PIN

These are weaker fits because UnoLock Agent MCP is designed around non-exportable host-bound keys, not reusable secrets.

## Quick rule

Run:

```bash
unolock-agent-self-test
```

or:

```bash
python3 -m unolock_mcp self-test --json
```

If the MCP says the host is not production-ready, follow the environment-specific advice before trying to register an agent key.
