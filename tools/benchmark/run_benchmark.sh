#!/usr/bin/env bash
# tools/benchmark/run_benchmark.sh — BACKLOG-v10 P2.2 + v11 P2.2.
#
# Run flow_compliance_check.py against every benchmark project under
# tools/benchmark/<project>_golden/ and assert the verdict matches the
# expected.txt file pinned alongside.
#
# Use as a CI regression gate on every plugin commit. A passing run
# proves the plugin behaviour on frozen benchmark projects has not
# drifted; a failing run forces the contributor to either fix the
# regression or update the pinned expected.txt with rationale.
#
# Layout:
#   tools/benchmark/
#     <project>_golden/
#       project/                <-- frozen project tree
#       expected.txt            <-- one line: PASS | PASS_WITH_WAIVERS | FAIL
#       (optional) NOTES.md     <-- why this golden state
#     run_benchmark.sh
#
# Exit codes:
#   0 — every golden project's verdict matched its expected.txt
#   1 — at least one verdict diverged
#   2 — no benchmark projects found / setup error
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FCC="$REPO_ROOT/vibe-ic-marketplace/plugins/vibe-ic-d/programs/flow_compliance_check.py"

if [[ ! -x "$FCC" ]] && [[ ! -f "$FCC" ]]; then
  echo "[error] flow_compliance_check.py not found at $FCC" >&2
  exit 2
fi

shopt -s nullglob
GOLDENS=("$SCRIPT_DIR"/*_golden)
if [[ ${#GOLDENS[@]} -eq 0 ]]; then
  echo "[skip] no benchmark projects under $SCRIPT_DIR/*_golden/" >&2
  exit 2
fi

PASS_COUNT=0
FAIL_COUNT=0
DIVERGED=()

for golden in "${GOLDENS[@]}"; do
  name="$(basename "$golden")"
  proj="$golden/project"
  expected_file="$golden/expected.txt"

  if [[ ! -d "$proj" ]]; then
    echo "[$name] [skip] $proj/ missing" >&2
    continue
  fi
  if [[ ! -f "$expected_file" ]]; then
    echo "[$name] [skip] $expected_file missing" >&2
    continue
  fi

  expected="$(grep -v '^[[:space:]]*#' "$expected_file" \
                | head -1 | tr -d '[:space:]')"
  if [[ -z "$expected" ]]; then
    echo "[$name] [skip] expected.txt empty" >&2
    continue
  fi

  echo "=== Running $name (expected: $expected) ==="
  out="$(python3 "$FCC" "$proj" 2>&1 || true)"
  # flow_compliance_check.py prints `Overall: <verdict>` on the last line
  actual="$(printf '%s' "$out" \
              | grep -E '^Overall:' | tail -1 \
              | sed -E 's/Overall:[[:space:]]+//' | tr -d '[:space:]')"
  if [[ -z "$actual" ]]; then
    echo "[$name] [FAIL] no Overall: line in flow_compliance output"
    DIVERGED+=("$name (no verdict)")
    FAIL_COUNT=$((FAIL_COUNT + 1))
    continue
  fi

  if [[ "$actual" == "$expected" ]]; then
    echo "[$name] [PASS] verdict=$actual matches expected"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "[$name] [FAIL] verdict=$actual diverges from expected=$expected"
    DIVERGED+=("$name (got $actual, want $expected)")
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
done

echo
echo "============================================"
echo "Benchmark summary: $PASS_COUNT pass, $FAIL_COUNT fail"
if [[ $FAIL_COUNT -gt 0 ]]; then
  echo "Diverged:"
  for d in "${DIVERGED[@]}"; do
    echo "  - $d"
  done
  exit 1
fi
echo "============================================"
exit 0
