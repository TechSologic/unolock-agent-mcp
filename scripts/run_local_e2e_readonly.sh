#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

ARTIFACT_FILE=${E2E_AGENT_BOOTSTRAP_OUTPUT_FILE:-/tmp/unolock-agent-bootstrap.json}
PIN=${E2E_AGENT_PIN:-0123}
MINIMUM_RECORDS=${E2E_AGENT_MINIMUM_RECORDS:-1}

echo "[agent-mcp] generating fresh local agent bootstrap artifact at $ARTIFACT_FILE"
E2E_AGENT_BOOTSTRAP_OUTPUT_FILE="$ARTIFACT_FILE" \
  npm --prefix "$REPO_ROOT/client/e2e-playwright" run test:create-safe

echo "[agent-mcp] running local agent read-only integration check"
PYTHONPATH="$REPO_ROOT/agent-mcp/src" \
  python3 "$REPO_ROOT/agent-mcp/tests/integration/live_local_readonly_flow.py" \
    --artifact-file "$ARTIFACT_FILE" \
    --pin "$PIN" \
    --minimum-records "$MINIMUM_RECORDS"
