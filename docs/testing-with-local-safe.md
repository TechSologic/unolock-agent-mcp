# Testing With A Local Safe

The agent/MCP prototype must not create Safes.

That boundary is intentional:

* Safe creation is a human flow
* agent registration and authentication are separate flows
* local testing should mirror that production model

## Local test setup

Use the existing browser Playwright suite in
[client/e2e-playwright](/home/mike/Unolock/client/e2e-playwright/README.md)
to create and validate a local Safe.

Relevant entrypoints:

* `npm run e2e:install`
* `npm run e2e:create-safe`
* `npm run e2e:lifecycle`

Those tests already support:

* local Angular app at `http://localhost:4200`
* virtual WebAuthn in Chromium
* PIN automation
* repeatable Safe open/delete flows

The create-safe harness can also emit an agent registration artifact:

```bash
E2E_AGENT_BOOTSTRAP_OUTPUT_FILE=/tmp/unolock-agent-bootstrap.json \
npm --prefix client/e2e-playwright run test:create-safe
```

The JSON artifact contains the UnoLock connection URL that can be handed to the MCP.

Local bootstrap behavior:

* preferred path: create a dedicated AI-marked access and emit its connection URL
* fallback path: if the current Safe tier blocks creating another device access, emit a connection URL for the current authenticated access instead

That fallback exists to keep local development moving on lower tiers. It should not be treated as the preferred production model.

## Division of responsibility

Use the browser test harness for:

* creating a Safe
* provisioning browser-side passkeys
* validating normal human Safe lifecycle behavior

Use `agent-mcp` for:

* probing live `/start` compatibility
* implementing agent registration
* implementing agent access
* later, calling the authenticated Safe API surface

## Why this matters

If the MCP grows its own Safe-creation path, the architecture drifts away from the intended product model.

The intended model is:

1. Human creates Safe.
2. Human admin creates agent access.
3. MCP registers.
4. MCP authenticates and operates within delegated permissions.
