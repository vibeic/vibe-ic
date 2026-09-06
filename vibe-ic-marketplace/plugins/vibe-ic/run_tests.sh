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
#   6. _shared/                   - the shared skill runner/compliance harness
#   7. Coverage audit             - every skill has compliance.yaml + tests
#
# THE ROSTER ABOVE IS A HAND LIST, AND IT WENT STALE. `_shared/` was absent
# through `ebccf100a0` (v1.13.77) while `gatekeeper-land.sh` already named it as a
# tree that carries files no landing stage reaches. RE-MEASURED on `ebccf100a0`,
# `run_tests.sh --list-tiers` piped into `pytest --collect-only`:
#
#     without this entry    73 dirs, 43668 nodes
#     with it               74 dirs, 44024 nodes   (+356, exactly _shared's)
#
# They PASS today, so nothing was hidden at that moment; what was hidden is the
# future — a red there could never reach this script's exit code. See the closing note at the bottom of this file: a
# hand roster is the wrong shape for an automatically-growing tree, and
# `test_bidirectional_controls_are_executed.py::test_no_test_file_collects_zero_tests`
# is the guard that now asks the population question from git instead.
#
# Exit 0 = all pass. Non-zero = failures (see stdout).
#
# `--list-tiers` prints the discovered tiers, one per line, and exits 0 without
# running anything. It exists so a GUARD can ask this script what the full suite
# is, instead of re-deriving the answer: a second copy of the discovery is a
# second definition of "the suite", and the direction that drift goes is a tree
# nothing checks. It is emitted from the SAME `TEST_DIRS` array the pytest
# invocation below consumes, so the two cannot disagree.
set -e
cd "$(dirname "$0")"

PYTEST_ARGS="${@:-}"
LIST_TIERS_ONLY=0
if [[ "${1:-}" == "--list-tiers" ]]; then
    LIST_TIERS_ONLY=1
    PYTEST_ARGS=""
fi
if [[ $LIST_TIERS_ONLY -eq 0 ]]; then
echo "==========================================================="
echo "vibe-ic-d: full test suite"
echo "==========================================================="
echo ""
fi

# A TIER IS A DIRECTORY THAT HOLDS TESTS, not one that merely exists.
#
# The `skills/*/tests` discovery below always asked the second question; the
# fixed entries above it asked only the first, and they drifted apart. MEASURED
# on e1814e28d: `<plugin>/tests` holds exactly one file,
# `tests/fixtures/real_benchmark/log2_width_helper.md`, and NO test file at all
# — so `--list-tiers` named a tier that collects zero tests, while the
# git-derived population correctly implied it was not one, and
# `test_full_suite_run_check.py::test_the_derived_tiers_are_the_tiers_the_runner
# _discovers` reported the disagreement ("only the runner lists ['tests']").
#
# Asking one question everywhere is the fix, rather than deleting the `tests`
# line by hand: a hand-deleted literal drifts back the next time the directory
# is repopulated, and this predicate simply starts answering yes again.
# The patterns are pytest's OWN `python_files` defaults, so a tier is a tier
# exactly when pytest would collect something from it.
_has_tests() {
    [ -d "$1" ] || return 1
    compgen -G "$1/test_*.py" > /dev/null && return 0
    compgen -G "$1/*_test.py" > /dev/null && return 0
    return 1
}

mapfile -t TEST_DIRS < <(
    # Plugin-level tests
    _has_tests tests && echo tests

    # Program tests
    _has_tests programs/tests && echo programs/tests

    # Phase-1 engine tests. Collected by NOTHING before #1391 — not by this
    # script, and not by pytest.ini, which declares ONE testpath by design.
    # It carried two failing tests on main that no suite reported. The
    # repo-root copy is unreachable from here (this script cds into the
    # plugin); `test_both_engine_copies_agree` keeps the copies together.
    _has_tests tools/phase1_engine/tests && echo tools/phase1_engine/tests

    # MCP EDA server sub-project. Named by the PR template and CONTRIBUTING as
    # a SEPARATE `pytest -q mcp-eda/test`, and by no runner at all — prose in a
    # checklist is not automation, so its 201 tests ran only when a human
    # remembered. 193 pass / 8 tool-gated skips.
    _has_tests mcp-eda/test && echo mcp-eda/test

    # Per-skill tests
    find skills -type d -name tests 2>/dev/null | while read -r d; do
        if compgen -G "$d/test_*.py" > /dev/null; then
            echo "$d"
        fi
    done

    # The shared skill-runner / compliance harness. Reached by NO tier above
    # (it is not `skills/*/tests`, not `programs/tests`, and bare `pytest` sees
    # one testpath by design) and by NO landing stage — `gatekeeper-land.sh`
    # lists it among the trees with no stage at all. 356 nodes on v1.13.77.
    [ -d _shared ] && compgen -G "_shared/test_*.py" > /dev/null && echo _shared
)

if [[ ${#TEST_DIRS[@]} -eq 0 ]]; then
    echo "No tests found."
    exit 1
fi

# The guard's hook. Printed from TEST_DIRS itself — see the header.
if [[ $LIST_TIERS_ONLY -eq 1 ]]; then
    printf '%s\n' "${TEST_DIRS[@]}"
    exit 0
fi

echo "Test tiers discovered (${#TEST_DIRS[@]} dirs):"
plugin_tests=$(printf '%s\n' "${TEST_DIRS[@]}" | grep -E '^tests$' | wc -l)
prog_tests=$(printf '%s\n' "${TEST_DIRS[@]}" | grep -E '^programs/tests$' | wc -l)
skill_tests=$(printf '%s\n' "${TEST_DIRS[@]}" | grep -c 'skills/' || true)
engine_tests=$(printf '%s\n' "${TEST_DIRS[@]}" | grep -cE '^tools/phase1_engine/tests$' || true)
mcp_tests=$(printf '%s\n' "${TEST_DIRS[@]}" | grep -cE '^mcp-eda/test$' || true)
shared_tests=$(printf '%s\n' "${TEST_DIRS[@]}" | grep -cE '^_shared$' || true)
printf "  %-35s %d dir\n" "Plugin-level (driver/integration)" "$plugin_tests"
printf "  %-35s %d dir\n" "Deterministic programs" "$prog_tests"
printf "  %-35s %d dirs\n" "Per-skill compliance" "$skill_tests"
printf "  %-35s %d dir\n" "Phase-1 engine" "$engine_tests"
printf "  %-35s %d dir\n" "MCP EDA server" "$mcp_tests"
printf "  %-35s %d dir\n" "Shared skill harness" "$shared_tests"
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

# ── IS A HAND ROSTER THE RIGHT SHAPE HERE? NO. ───────────────────────────────
#
# Plainly: it is not, and this file should stop being one. The block above is
# five hand-written entries plus one `find`, over a tree that grows by itself,
# and line 3 calls the result THE FULL SUITE. That claim can only ever be as
# true as the last person who remembered to edit it — `_shared/` was added to
# the repo, ran green in nobody's suite, and was named as an uncovered tree in
# `tools/gatekeeper-land.sh:1379-1386` while line 3 here still said "full".
# Nothing detected the disagreement, because a roster cannot notice what is not
# on it. `landing_unselectable_pytest_corpus.py` states the same rule for the
# landing corpus — "THE CORPUS IS A COMPLEMENT, NEVER A ROSTER" — and gives the
# reason: a list of trees goes stale the first time one is added, silently, and
# in the direction that still prints PASS.
#
# The shape that does not rot is the one that program already uses: derive the
# population from `git ls-files`, subtract what is DECLARED out with its reason,
# and run the remainder. Two things now stand between this roster and a silent
# hole, and both are complements rather than lists:
#
#   test_bidirectional_controls_are_executed.py::test_no_test_file_collects_zero_tests
#       every tracked (and untracked-not-ignored) pytest module in this plugin,
#       from git, must yield at least one collected node.
#   landing_unselectable_pytest_corpus.py
#       every tracked test file no landing stage reaches, enumerated.
#
# Neither yet FAILS on "a tree exists that this script does not discover", which
# is the missing third check and the one that would have caught `_shared/` on
# the day it landed rather than eight versions later. Converting the block above
# to a git-derived complement is the fix; it is not made here because it changes
# what the suite RUNS, and that belongs in its own change with its own
# before/after node count, not bundled with the roster repair that proves it is
# needed.
