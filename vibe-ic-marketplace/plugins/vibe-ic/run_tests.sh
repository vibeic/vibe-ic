#!/bin/bash
# Full test suite for the vibe-ic-d plugin.
#
# THIS SCRIPT IS THE FULL SUITE. Bare `pytest` is NOT: `pytest.ini` declares a
# single testpath on purpose (`single_testpath_guard.py` pins it), so every
# tree below other than programs/tests/ is collected HERE and nowhere else.
# A tier named here but not discovered in the block below is a lie about
# coverage — that is the defect vibe-ic#1391 was filed for.
#   1. tests/                     - driver core/integration. DOES NOT EXIST in
#                                   this repo; the `[ -d tests ]` guard skips
#                                   it and the tier report prints `0 dir`.
#   2. programs/tests/            - the deterministic programs
#   3. tools/phase1_engine/tests/ - the Phase-1 gap/render engine (#1391)
#   4. mcp-eda/test/              - the MCP EDA server sub-project
#   5. skills/*/tests/            - per-skill compliance regression (generated)
#   6. Coverage audit             - every skill has compliance.yaml + tests
#
# Exit 0 = all pass. Non-zero = failures (see stdout).
set -e
cd "$(dirname "$0")"

PYTEST_ARGS="${@:-}"
echo "==========================================================="
echo "vibe-ic-d: full test suite"
echo "==========================================================="
echo ""

mapfile -t TEST_DIRS < <(
    # Plugin-level tests
    [ -d tests ] && echo tests

    # Program tests
    [ -d programs/tests ] && echo programs/tests

    # Phase-1 engine tests. Collected by NOTHING before #1391 — not by this
    # script, and not by pytest.ini, which declares ONE testpath by design.
    # It carried two failing tests on main that no suite reported. The
    # repo-root copy is unreachable from here (this script cds into the
    # plugin); `test_both_engine_copies_agree` keeps the copies together.
    [ -d tools/phase1_engine/tests ] && echo tools/phase1_engine/tests

    # MCP EDA server sub-project. Named by the PR template and CONTRIBUTING as
    # a SEPARATE `pytest -q mcp-eda/test`, and by no runner at all — prose in a
    # checklist is not automation, so its 201 tests ran only when a human
    # remembered. 193 pass / 8 tool-gated skips.
    [ -d mcp-eda/test ] && echo mcp-eda/test

    # Per-skill tests
    find skills -type d -name tests 2>/dev/null | while read -r d; do
        if compgen -G "$d/test_*.py" > /dev/null; then
            echo "$d"
        fi
    done
)

if [[ ${#TEST_DIRS[@]} -eq 0 ]]; then
    echo "No tests found."
    exit 1
fi

echo "Test tiers discovered (${#TEST_DIRS[@]} dirs):"
plugin_tests=$(printf '%s\n' "${TEST_DIRS[@]}" | grep -E '^tests$' | wc -l)
prog_tests=$(printf '%s\n' "${TEST_DIRS[@]}" | grep -E '^programs/tests$' | wc -l)
skill_tests=$(printf '%s\n' "${TEST_DIRS[@]}" | grep -c 'skills/' || true)
engine_tests=$(printf '%s\n' "${TEST_DIRS[@]}" | grep -cE '^tools/phase1_engine/tests$' || true)
mcp_tests=$(printf '%s\n' "${TEST_DIRS[@]}" | grep -cE '^mcp-eda/test$' || true)
printf "  %-35s %d dir\n" "Plugin-level (driver/integration)" "$plugin_tests"
printf "  %-35s %d dir\n" "Deterministic programs" "$prog_tests"
printf "  %-35s %d dirs\n" "Per-skill compliance" "$skill_tests"
printf "  %-35s %d dir\n" "Phase-1 engine" "$engine_tests"
printf "  %-35s %d dir\n" "MCP EDA server" "$mcp_tests"
echo ""

# Coverage audit - every skill must have compliance.yaml + tests
echo "Coverage audit:"
uncov=0
for skill_dir in skills/*/; do
    s=$(basename "$skill_dir")
    has_yaml=0; has_tests=0
    [ -f "$skill_dir/compliance.yaml" ] && has_yaml=1
    [ -f "$skill_dir/tests/test_compliance.py" ] && has_tests=1
    if [[ $has_yaml -eq 0 || $has_tests -eq 0 ]]; then
        printf "  [GAP]  %-25s yaml=%d tests=%d\n" "$s" "$has_yaml" "$has_tests"
        uncov=$((uncov + 1))
    fi
done
if [[ $uncov -eq 0 ]]; then
    echo "  (no gaps - every skill has compliance.yaml + test_compliance.py)"
fi
echo ""

echo "==========================================================="
echo "Running pytest..."
echo "==========================================================="
set +e
python3 -m pytest "${TEST_DIRS[@]}" $PYTEST_ARGS
RC=$?
set -e

echo ""
echo "==========================================================="
if [[ $RC -eq 0 ]]; then
    echo "All tests passed."
else
    echo "Some tests FAILED (exit $RC)."
fi
echo "==========================================================="
exit $RC
