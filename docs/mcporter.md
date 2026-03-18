# mcporter

`mcporter` is a good way to run UnoLock Agent MCP as a persistent external MCP server instead of spawning a fresh process for every interaction.

It is also the preferred path when it is available.

When you choose `mcporter`, use it as the normal control surface:

* start and restart the UnoLock MCP through `mcporter`
* call UnoLock tools through `mcporter`
* do not bypass it with a parallel direct CLI workflow unless you are debugging

For the public agent-first explanation of this choice, see:

* `https://unolock.ai/install-mcp.html`

That matters for UnoLock because the MCP keeps useful state in memory while it is running:

* in-memory authentication state
* in-memory archive cache
* the agent PIN held only in MCP memory after the user provides it
* cached Safe record views used by the write path

## Why use mcporter

If your host launches a brand-new MCP process on every request, the MCP has to rebuild its in-memory state repeatedly.

Using a keep-alive runner such as `mcporter` gives you:

* the agent does not need to keep re-asking the user for the PIN while the MCP stays alive
* fewer cold starts
* less repeated auth/setup work
* better cache reuse between interactions
* better performance for read/update flows

## Important distinction

The npm package:

```bash
npx @techsologic/unolock-agent-mcp@latest
```

is an easy way to launch the external UnoLock MCP binary.

It is **not** an `mcporter` plugin and it is **not** an OpenClaw plugin package.

## Recommended mcporter setup

Define UnoLock as a named stdio server and use a keep-alive lifecycle.

The easiest way to get a ready-to-paste config is:

```bash
python3 -m unolock_mcp mcporter-config
```

or, for a direct binary path:

```bash
python3 -m unolock_mcp mcporter-config --mode binary --binary-path /path/to/unolock-agent-mcp
```

Example:

```json
{
  "mcpServers": {
    "unolock-agent": {
      "type": "stdio",
      "command": "npx",
      "args": ["@techsologic/unolock-agent-mcp@latest"],
      "lifecycle": "keep-alive"
    }
  }
}
```

If you prefer a direct binary instead of `npx`, point `command` at the downloaded GitHub Release binary.

## Why keep-alive matters

With `lifecycle: "keep-alive"`:

* the MCP can remain running between interactions
* the user-provided PIN can stay in MCP memory for that running process
* in-memory record/archive cache stays warm
* active local process state is not thrown away after every request

Without keep-alive:

* the MCP may be relaunched frequently
* the agent may need to ask the user for the PIN again after each restart or short-lived invocation
* cold-start overhead increases
* in-memory state is lost between requests

## Important operating rule

If UnoLock is running under `mcporter`, all normal communication and control should go through `mcporter`:

* use `mcporter` to launch the server
* use `mcporter` to call UnoLock MCP tools
* use `mcporter` to restart the MCP between tasks or updates

Do not mix that with a separate direct `unolock-agent-mcp ...` CLI workflow during normal agent use, because that creates avoidable confusion about which process owns the active registration state, in-memory PIN, and live session state.

## Updates with mcporter

`mcporter` is also the preferred update path when you launch UnoLock through:

```bash
npx @techsologic/unolock-agent-mcp@latest
```

Why:

* the MCP stays warm between interactions
* on restart, the npm wrapper can check GitHub Releases for a newer stable binary
* the user PIN can stay in MCP memory during normal use, without pushing the agent toward persistent PIN storage

Recommended pattern:

1. call `unolock_get_update_status` or run `unolock-agent-mcp check-update`
2. wait until the current task is finished
3. restart the `mcporter` server
4. let the wrapper fetch the latest stable binary if one is available

Do not try to update the running MCP process in place.

## Security note

Using `mcporter` keep-alive does **not** change the main UnoLock security model:

* Safe content still stays client-side decrypted only in MCP memory
* archive cache remains in memory only
* the Agent Key URL is still one-time-use
* the user PIN is still not persisted

## Related docs

* [Install Guide](install.md)
* [MCP Host Config](host-config.md)
* [Tool Catalog](tool-catalog.md)
