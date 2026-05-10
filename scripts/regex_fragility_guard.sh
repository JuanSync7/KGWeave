#!/usr/bin/env bash
# Correctness guard for the regex-fragility auto-research loop.
#
# Must pass for any iteration to be kept:
#   1. pytest tests/knowledge_graph/ -x  (KG suite green)
#
# Exit codes:
#   0  = guard pass
#   1  = pytest failed
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[guard] running pytest tests/knowledge_graph/ ..."
if ! uv run pytest tests/knowledge_graph/ -x -q > /tmp/regex_guard_pytest.log 2>&1; then
  echo "[guard] FAIL pytest"
  tail -60 /tmp/regex_guard_pytest.log
  exit 1
fi
echo "[guard] pytest OK"
echo "[guard] PASS"
