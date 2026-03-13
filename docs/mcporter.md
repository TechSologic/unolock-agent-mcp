# mcporter

`mcporter` is a good way to run UnoLock Agent MCP as a persistent external MCP server instead of spawning a fresh process for every interaction.

That matters for UnoLock because the MCP keeps useful state in memory while it is running:

* in-memory session state
* in-memory archive cache
* cached Safe record views used by the write path

## Why use mcporter

If your host launches a brand-new MCP process on every request, the MCP has to rebuild its in-memory state repeatedly.

Using a keep-alive runner such as `mcporter` gives you:

* fewer cold starts
* less repeated auth/setup work
* better cache reuse between interactions
* better performance for read/update flows

## Important distinction

The npm package:

```bash
npx @techsologic/unolock-agent-mcp
```

is an easy way to launch the external UnoLock MCP binary.

It is **not** an `mcporter` plugin and it is **not** an OpenClaw plugin package.

## Recommended mcporter setup

Define UnoLock as a named stdio server and use a keep-alive lifecycle.

Example:

```json
{
  "servers": {
    "unolock-agent": {
      "command": "npx",
      "args": ["@techsologic/unolock-agent-mcp"],
      "lifecycle": "keep-alive"
    }
  }
}
```

If you prefer a direct binary instead of `npx`, point `command` at the downloaded GitHub Release binary.

## Why keep-alive matters

With `lifecycle: "keep-alive"`:

* the MCP can remain running between interactions
* in-memory record/archive cache stays warm
* active local process state is not thrown away after every request

Without keep-alive:

* the MCP may be relaunched frequently
* cold-start overhead increases
* in-memory state is lost between requests

## Security note

Using `mcporter` keep-alive does **not** change the main UnoLock security model:

* Safe content still stays client-side decrypted only in MCP memory
* archive cache remains in memory only
* the connection URL is still one-time-use
* the user PIN is still not persisted

## Related docs

* [Install Guide](install.md)
* [MCP Host Config](host-config.md)
* [Tool Catalog](tool-catalog.md)
