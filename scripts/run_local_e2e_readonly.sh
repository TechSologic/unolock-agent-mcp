#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
UNOLOCK_REPO_ROOT=${UNOLOCK_REPO_ROOT:-$(cd "$REPO_ROOT/.." && pwd)}
CLIENT_E2E_DIR=${UNOLOCK_E2E_CLIENT_DIR:-$UNOLOCK_REPO_ROOT/client/e2e-playwright}

ARTIFACT_FILE=${E2E_AGENT_BOOTSTRAP_OUTPUT_FILE:-/tmp/unolock-agent-bootstrap.json}
PIN=${E2E_AGENT_PIN:-0123}
MINIMUM_RECORDS=${E2E_AGENT_MINIMUM_RECORDS:-1}

if [[ ! -d "$CLIENT_E2E_DIR" ]]; then
  echo "[unolock-agent-mcp] missing client e2e directory: $CLIENT_E2E_DIR" >&2
  echo "[unolock-agent-mcp] set UNOLOCK_E2E_CLIENT_DIR to a UnoLock client/e2e-playwright checkout to run this script." >&2
  exit 1
fi

echo "[agent-mcp] generating fresh local agent bootstrap artifact at $ARTIFACT_FILE"
E2E_AGENT_BOOTSTRAP_OUTPUT_FILE="$ARTIFACT_FILE" \
  npm --prefix "$CLIENT_E2E_DIR" run test:create-safe

echo "[agent-mcp] running local agent read-only integration check"
PYTHONPATH="$REPO_ROOT/src" \
  python3 "$REPO_ROOT/tests/integration/live_local_readonly_flow.py" \
    --artifact-file "$ARTIFACT_FILE" \
    --pin "$PIN" \
    --minimum-records "$MINIMUM_RECORDS"
