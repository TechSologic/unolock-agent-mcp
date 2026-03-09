# Agent MCP Scripts

This directory contains MCP-side utility scripts only.

Current scripts:

* `bootstrap.sh`
  * installs the package in editable mode for the current user
* `run_local_probe.sh`
  * runs the packaged local `/start` flow probe against the local server
* `run_stdio_mcp.sh`
  * runs the packaged stdio MCP server
* `run_local_e2e_readonly.sh`
  * creates a fresh local Safe/bootstrap artifact with Playwright, then verifies agent registration, restart, re-auth, and read-only access
* `probe_local_server.py`
  * Python entrypoint that mirrors the packaged CLI

Server-side probes should remain under:

* `/home/mike/Unolock/server/safe-server/scripts/`
