#!/usr/bin/env bash
# Correctness guard for the genericness auto-research loop.
#
# Must pass for any iteration to be kept:
#   1. pytest tests/knowledge_graph/ -x  (KG suite green)
#   2. AES demo bit-stability: 67 / 41 / 229 / 216 / 109
#
# Exit codes:
#   0  = guard pass
#   1  = pytest failed
#   2  = AES demo numbers drifted
#   3  = AES demo crashed
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[guard] running pytest tests/knowledge_graph/ ..."
if ! uv run pytest tests/knowledge_graph/ -x -q > /tmp/guard_pytest.log 2>&1; then
  echo "[guard] FAIL pytest"
  tail -40 /tmp/guard_pytest.log
  exit 1
fi
echo "[guard] pytest OK"

echo "[guard] running AES demo ..."
if ! uv run python scripts/demo_opentitan_aes.py > /tmp/guard_aes.log 2>&1; then
  echo "[guard] FAIL aes demo crashed"
  tail -40 /tmp/guard_aes.log
  exit 3
fi

# Extract the five canonical numbers; demo prints them in a known order.
# We grep loosely and check the expected integers are all present.
expected=(67 41 229 216 109)
missing=()
for n in "${expected[@]}"; do
  if ! grep -qE "(^|[^0-9])${n}([^0-9]|$)" /tmp/guard_aes.log; then
    missing+=("$n")
  fi
done

if [ "${#missing[@]}" -gt 0 ]; then
  echo "[guard] FAIL aes demo numbers drifted; missing: ${missing[*]}"
  tail -40 /tmp/guard_aes.log
  exit 2
fi

echo "[guard] AES demo OK (67/41/229/216/109 present)"
echo "[guard] PASS"
