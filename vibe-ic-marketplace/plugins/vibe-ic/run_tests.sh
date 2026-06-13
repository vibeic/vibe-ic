#!/bin/bash
# Full test suite for the vibe-ic-d plugin.
#
# Runs four test tiers:
#   1. tests/               - driver core, YAML parser, cross-checks, integration
#   2. programs/tests/      - the 6 deterministic programs (CRC, lint, etc.)
#   3. skills/*/tests/      - per-skill compliance regression (auto-generated)
#   4. Coverage audit       - every skill has compliance.yaml + tests
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
printf "  %-35s %d dir\n" "Plugin-level (driver/integration)" "$plugin_tests"
printf "  %-35s %d dir\n" "Deterministic programs" "$prog_tests"
printf "  %-35s %d dirs\n" "Per-skill compliance" "$skill_tests"
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
