# Testing With A Local Safe

The agent/MCP must not create Safes.

That boundary is intentional:

* Safe creation is a human flow
* agent registration and authentication are separate flows
* local testing should mirror that production model

## Local test setup

Use the existing browser Playwright suite from a full UnoLock checkout in `client/e2e-playwright` to create and validate a local Safe.

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
npm --prefix /path/to/Unolock/client/e2e-playwright run test:create-safe
```

The JSON artifact contains the UnoLock Agent Key URL that can be handed to the MCP.

Local bootstrap behavior:

* preferred path: create a dedicated AI-marked access and emit its Agent Key URL
* fallback path: if the current Safe tier blocks creating another device access, emit an Agent Key URL for the current authenticated access instead

That fallback exists to keep local development moving on lower tiers. It should not be treated as the preferred production model.

## Division of responsibility

Use the browser test harness for:

* creating a Safe
* provisioning browser-side passkeys
* validating normal human Safe lifecycle behavior

Use `unolock-agent` for:

* probing live `/start` compatibility
* implementing agent registration
* implementing agent access
* later, calling the authenticated Safe API surface
* testing sync add, status, run, and restore against a real Safe with Cloud files

## Why this matters

If the MCP grows its own Safe-creation path, the architecture drifts away from the intended product model.

The intended model is:

1. Human creates Safe.
2. Human admin creates agent access.
3. MCP registers.
4. MCP authenticates and operates within delegated permissions.

## Sync-focused local testing

Once local registration and normal file access are working, a useful real-Safe sync test is:

1. create a small local file such as `SOUL.md`
2. run `unolock-agent sync-add ./SOUL.md`
3. run `unolock-agent sync-status`
4. edit the file locally and run `unolock-agent sync-run --all`
5. confirm the Cloud file was updated in the expected Space
6. remove the local file or restore to another path with `unolock-agent sync-restore ./SOUL.md`

Current sync scope for local E2E:

* one-way local-to-cloud backup only
* manual restore only
* no automatic remote-to-local sync yet
