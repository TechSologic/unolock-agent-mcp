# Supported Environments

UnoLock Agent MCP is designed to work across a wide range of agent hosts, but some environments can satisfy UnoLock’s preferred key-storage requirements more easily than others.

## Best fit today

* Windows desktop/laptop with TPM or the non-exportable Windows CNG fallback
* WSL2 using the Windows TPM helper or the Windows CNG fallback
* Linux desktop, workstation, or VM with TPM/vTPM
* macOS desktop/laptop when either:
  * Secure Enclave works cleanly in the current launch context
  * or the Keychain-backed non-exportable fallback works

## Lower-Assurance Environments

* plain Docker containers
* Kubernetes pods without a host or VM trust path
* fully remote or unattended agent sandboxes
* environments where the user cannot provide an Agent Key URL and, if needed, a PIN

These environments are harder to support because UnoLock Agent MCP is designed around non-exportable host-bound keys, not reusable secrets. They may still work, but the MCP should report the reduced assurance clearly.

## Quick rule

Run:

```bash
unolock-agent-self-test
```

or:

```bash
python3 -m unolock_mcp self-test --json
```

If the MCP reports reduced assurance, review the environment-specific advice and decide whether that host is acceptable for your Safe data.
