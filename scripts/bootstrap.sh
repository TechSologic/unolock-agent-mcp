#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"
python3 -m pip install --user -e .

echo
echo "Installed unolock-agent in editable mode."
echo "Run ./scripts/run_local_probe.sh to probe the local UnoLock server."
