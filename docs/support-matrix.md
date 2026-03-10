# MCP Support Matrix

This document defines which agent-host environments UnoLock should support first and which TPM DAO should be used in each environment.

Checked against current host/platform docs on 2026-03-08:

* Anthropic Claude Code setup: https://code.claude.com/docs/en/setup
* Anthropic MCP docs: https://docs.anthropic.com/en/docs/claude-code/mcp
* Cursor MCP docs: https://docs.cursor.com/advanced/model-context-protocol
* Cursor background agents: https://docs.cursor.com/background-agents
* GitHub-hosted runners: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
* GitHub Actions Runner Controller: https://docs.github.com/en/actions/concepts/runners/actions-runner-controller
* Anthropic computer-use sandbox docs: https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool
* Docker Desktop for Windows: https://docs.docker.com/desktop/setup/install/windows-install/
* WSL Windows/Linux interop: https://learn.microsoft.com/en-us/windows/wsl/filesystems

## Design rule

Use the strongest non-exportable key provider available on the current host.

## Product Fit

UnoLock Agent MCP is primarily designed for **user-adjacent desktop agents**:

* local AI assistants
* desktop MCP hosts
* environments where the user can provide a connection URL and, if needed, a PIN

It is **not** designed first for every possible headless or background-agent environment.

That is an intentional tradeoff. Strong device-bound security is easier to preserve in a normal user session than in remote, sandboxed, or unattended environments.

Selection policy:

* default to `UNOLOCK_TPM_PROVIDER=auto`
* choose the strongest production-ready provider detected at startup
* store the provider used during registration
* if the host later resolves to a different provider, report a provider mismatch and require either:
  * forcing the original provider
  * or re-registering the agent key

## Priority environments

### Tier 1

These should be treated as first-class production targets.

| Environment | Why it matters | Preferred DAO | Current status | Assurance |
| --- | --- | --- | --- | --- |
| Windows desktop/laptop | Common local agent host for Claude Desktop and Cursor | `WindowsTpmDao` | Implemented | Hardware-backed |
| WSL2 on Windows | Common developer and agent host shape | `WindowsTpmDao` via Windows helper | Implemented and live-validated | Hardware-backed |
| Native Linux | Common server, workstation, and self-hosted agent environment | `LinuxTpmDao` | Implemented, needs more live host coverage | Hardware-backed or vTPM |
| Linux VM with vTPM | Strong production shape for hosted agents | `LinuxTpmDao` | Expected to work if TPM device is exposed | Virtual hardware-backed |

### Tier 2

These are important, but either need another provider or stronger operational guidance.

| Environment | Why it matters | Preferred DAO | Current status | Assurance |
| --- | --- | --- | --- | --- |
| macOS desktop/laptop | Major local developer and Claude/Desktop host | `MacSecureEnclaveDao` | Experimental, not production-ready yet | Hardware-backed |
| Windows VM with vTPM | Enterprise desktop and remote dev shape | `WindowsTpmDao` | Expected once Windows TPM is available in guest | Virtual hardware-backed |
| Kubernetes nodes with vTPM-backed VMs | Growing home for background agents | `LinuxTpmDao` | Depends on node/VM design | Virtual hardware-backed |
| Self-hosted CI runners | Common automation target when secrets matter | OS-specific production DAO | Supported if host exposes secure hardware | Host-dependent |

### Tier 3

These should work for development where possible, but are not preferred production targets.

| Environment | Why it matters | Preferred DAO | Current status | Assurance |
| --- | --- | --- | --- | --- |
| Plain Docker container with no TPM/vTPM | Common local packaging shape | none, fall back to `TestTpmDao` | Supported for development only | Test-only |
| Hosted CI runner with no secure device binding | Easy to adopt but weak binding | none, fall back to `TestTpmDao` | Development only | Test-only |
| Ephemeral remote sandboxes without TPM/vTPM | Likely for some agent products | none yet | Not a production target | Unsupported for production |

## Runtime mapping

The startup factory should think in terms of runtime shape, not just OS name.

### Windows native

Use:

* `WindowsTpmDao`

Detect with:

* `platform.system() == "Windows"`
* ability to create a non-exportable key through the Windows platform crypto provider

### WSL2

Use:

* `WindowsTpmDao`

Detect with:

* Linux kernel release showing `microsoft` / `wsl`
* `powershell.exe` available from WSL
* Windows TPM helper able to create and sign with a key

Do not prefer:

* `LinuxTpmDao` inside WSL2 unless WSL eventually exposes a real TPM device and that path is intentionally chosen

### Native Linux and Linux VMs

Use:

* `LinuxTpmDao`

Detect with:

* `/dev/tpmrm0` or `/dev/tpm0`
* working `tpm2-tools` path or equivalent implementation backend

### macOS

Use:

* `MacSecureEnclaveDao`

Target behavior:

* non-exportable key in Secure Enclave when available
* Keychain-backed fallback only if it preserves UnoLock’s device-bound intent

## Production guidance by environment

### Best current production path

* Windows native with TPM
* WSL2 using the Windows TPM helper
* native Linux with TPM
* Linux VM with vTPM
* user-adjacent desktop agents running in a normal logged-in session

### Acceptable with more validation

* Windows VM with vTPM
* Kubernetes on vTPM-backed worker VMs
* self-hosted CI runners with explicit TPM/vTPM support
* macOS desktop agents once Secure Enclave launch-context reliability is solved and validated

### Development-only path

* `TestTpmDao`

Use it for:

* local interoperability work
* unit and integration tests
* environments with no secure hardware path yet

Do not treat it as:

* password-equivalent production auth
* acceptable long-term agent registration storage

### Not a first-class production target

These environments are likely to be difficult or unreliable for strong device-bound security:

* fully headless background agents with no normal user session
* remote agent sandboxes with limited keychain or TPM access
* plain containers without TPM/vTPM passthrough
* hosted agent environments where the operator does not control hardware-backed key access

## Rollout plan

1. Keep `WindowsTpmDao` as the default production path for Windows and WSL2.
2. Validate `LinuxTpmDao` on native Linux and Linux VMs with vTPM.
3. Validate `MacSecureEnclaveDao` on real Secure Enclave-capable Macs.
4. Add clearer runtime detection for containers, CI, and Kubernetes.
5. Keep `TestTpmDao` only as an explicit development fallback.

## Factory expectations

The TPM factory should stay responsible only for provider selection.

It should not:

* mutate existing registrations
* silently switch a registered key to a different provider
* hide provider mismatch during auth

It should:

* pick the best available provider on fresh startup
* expose diagnostics explaining why that provider was chosen
* let the user override selection with `UNOLOCK_TPM_PROVIDER`
* work with persisted registration metadata so auth can fail clearly when the host changes
