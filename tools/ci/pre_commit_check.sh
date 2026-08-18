#!/bin/bash
# ============================================================================
# Vibe-IC Pre-Commit Check
# ============================================================================
# Run unit tests and Python syntax checks before committing.
# Install with: tools/ci/install_hooks.sh
#
# Usage (manual):
#   bash tools/ci/pre_commit_check.sh
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "============================================"
echo "  Vibe-IC Pre-Commit Check"
echo "============================================"

ERRORS=0

# --------------------------------------------------------------------------
# 1. Python syntax check on all .py files in tools/
# --------------------------------------------------------------------------
echo ""
echo "--- Python Syntax Check ---"
PY_FILES=$(find "$PROJECT_ROOT/tools" -name "*.py" -type f 2>/dev/null)
PY_COUNT=0
PY_FAIL=0

for f in $PY_FILES; do
    PY_COUNT=$((PY_COUNT + 1))
    if ! python3 -m py_compile "$f" 2>/dev/null; then
        echo "  FAIL: $f"
        PY_FAIL=$((PY_FAIL + 1))
        ERRORS=$((ERRORS + 1))
    fi
done

if [ $PY_FAIL -eq 0 ]; then
    echo "  PASS: $PY_COUNT Python files checked, all OK"
else
    echo "  FAIL: $PY_FAIL/$PY_COUNT files have syntax errors"
fi

# --------------------------------------------------------------------------
# 2. Unit tests
# --------------------------------------------------------------------------
echo ""
echo "--- Unit Tests ---"

TEST_FILES=$(find "$PROJECT_ROOT/tools" -maxdepth 1 -name "test_*.py" -type f 2>/dev/null)

if [ -z "$TEST_FILES" ]; then
    echo "  SKIP: No test files found"
else
    TOTAL=0; FAIL=0
    for tf in $TEST_FILES; do
        MOD=$(basename "$tf" .py)
        DIR=$(dirname "$tf")
        RESULT=$(cd "$DIR" && timeout 30 python3 -c "
import unittest, sys, io
sys.stdout=io.StringIO()
r=unittest.TextTestRunner(stream=io.StringIO(),verbosity=0).run(unittest.TestLoader().loadTestsFromName('$MOD'))
sys.stdout=sys.__stdout__
print(f'{r.testsRun},{len(r.failures)+len(r.errors)}')
" 2>/dev/null || echo "0,1")
        T=$(echo "$RESULT" | cut -d, -f1)
        F=$(echo "$RESULT" | cut -d, -f2)
        TOTAL=$((TOTAL + T))
        FAIL=$((FAIL + F))
    done
    if [ $FAIL -eq 0 ]; then
        echo "  PASS: $TOTAL tests across $(echo "$TEST_FILES" | wc -w) files"
    else
        echo "  FAIL: $FAIL failures in $TOTAL tests"
        ERRORS=$((ERRORS + 1))
    fi
fi

# --------------------------------------------------------------------------
# 3. Marketplace version sync (Wave 81 — prevents /plugin update no-op)
# --------------------------------------------------------------------------
echo ""
echo "--- Marketplace Version Sync ---"
SYNC_TOOL="$PROJECT_ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs/marketplace_version_sync_check.py"
SYNC_DIR="$PROJECT_ROOT/vibe-ic-marketplace"
if [ -f "$SYNC_TOOL" ] && [ -d "$SYNC_DIR/.claude-plugin" ]; then
    if python3 "$SYNC_TOOL" --marketplace-dir "$SYNC_DIR" >/dev/null 2>&1; then
        echo "  PASS: marketplace.json plugins[].version in sync with plugin.json"
    else
        # Re-run with output visible for the user to see what drifted.
        python3 "$SYNC_TOOL" --marketplace-dir "$SYNC_DIR" || true
        echo "  FAIL: marketplace.json plugins[].version drift detected."
        echo "        Re-run with --fix to auto-bump."
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "  SKIP: marketplace_version_sync_check tool or marketplace dir not present"
fi

# --------------------------------------------------------------------------
# 4. Commit-msg version-sync (Wave 93 / v1.6.17)
# --------------------------------------------------------------------------
# When the commit message advertises a vX.Y.Z, plugin.json + marketplace.json
# must already match. Closes the v1.6.10 / v1.6.13 / v1.6.16 repeating bug
# where the commit message claimed a new version but the JSON files still
# carried the previous one. Enforced at the commit-msg hook stage (git
# passes the active message file as $1 there); SKIP here because the
# pre-commit stage's .git/COMMIT_EDITMSG may still carry a stale residue
# from a prior commit. Manual CLI usage:
#   bash tools/ci/check_version_sync_with_commit.sh <msg-file>
echo ""
echo "--- Commit-msg version-sync ---"
echo "  SKIP: enforced at commit-msg hook stage (see tools/ci/install_hooks.sh)"

# --------------------------------------------------------------------------
# 4b. Staged-diff version-claim guard (v1.6.19 — closes Wave 93 mirror leak)
# --------------------------------------------------------------------------
# Wave 93 only catches the case where the commit SUBJECT advertises
# vX.Y.Z but plugin.json hasn't bumped. It misses the mirror-leak
# pattern observed in 9d4e984a where 5 in-code comments claim v1.6.19
# but the commit subject is silent → both Wave 81 (plugin↔marketplace
# drift) and Wave 93 (subject↔plugin) stay PASS while feature code
# lands at the wrong version.
#
# This guard scans the STAGED diff for newly added lines mentioning a
# vX.Y.Z that exceeds plugin.json. Historical references (`was`,
# `supersedes`, `since`, `pre-`, `from`, `before`, …) are skipped.
# CHANGELOG/RELEASE_NOTES paths are exempted (they legitimately list
# upcoming versions during release prep).
echo ""
echo "--- Staged-diff version-claim guard ---"
CLAIM_CHECK="$PROJECT_ROOT/tools/ci/staged_version_claim_check.py"
if [ -f "$CLAIM_CHECK" ]; then
    if python3 "$CLAIM_CHECK" --repo-root "$PROJECT_ROOT"; then
        :  # PASS message printed by the program itself
    else
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "  SKIP: staged_version_claim_check.py not present"
fi

# --------------------------------------------------------------------------
# 4.5. Picker fixture-thrash guard (issue #5 lesson learned)
# --------------------------------------------------------------------------
# Refuses any commit that flips an entry in the
# `tests/test_phase1_fixtures_regression.py::_EXPECTED` dict
# without an explicit `fixture-flip-acknowledged: <project>:<old>
# -> <new>` line in the commit message. Closes the
# v1.6.51→v1.6.58→v1.6.60 thrashing class structurally.
echo ""
echo "--- Picker fixture-thrash guard ---"
THRASH_GUARD="$PROJECT_ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs/picker_fixture_thrash_guard.py"
if [ -f "$THRASH_GUARD" ]; then
    MSG_FILE="${1:-}"
    if [ -n "$MSG_FILE" ] && [ -f "$MSG_FILE" ]; then
        if ! python3 "$THRASH_GUARD" --repo-root "$PROJECT_ROOT" \
                --commit-msg-file "$MSG_FILE"; then
            ERRORS=$((ERRORS + 1))
        fi
    else
        if ! python3 "$THRASH_GUARD" --repo-root "$PROJECT_ROOT"; then
            ERRORS=$((ERRORS + 1))
        fi
    fi
else
    echo "  SKIP: picker_fixture_thrash_guard.py not present"
fi

# --------------------------------------------------------------------------
# 4.6. Stated counts vs the generated inventories
# --------------------------------------------------------------------------
# A count typed into a README stops being true the moment the tree moves, and
# nothing noticed for a month: the READMEs said 917 deterministic programs while
# the glob they cited returned 1178. The three inventories
# (PROGRAM_INVENTORY.json / SKILL_INVENTORY.json / MCP_TOOL_INVENTORY.json) each
# had a drift guard proving the ARTEFACT matched the TREE; none proved the PROSE
# quoted the artefact.
#
# Read-only here on purpose. `--fix` re-types the numbers mechanically and runs
# at LAND (gatekeeper_prepare_landing.py), for the reason #1382 settled for the
# 63x8 census: tree-wide counters that every branch rewrites do not stack.
echo ""
echo "--- Stated counts vs generated inventories ---"
COUNT_GATE="$PROJECT_ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs/stated_count_drift_check.py"
if [ -f "$COUNT_GATE" ]; then
    if python3 "$COUNT_GATE" --root "$PROJECT_ROOT" >/dev/null 2>&1; then
        echo "  PASS: every registered stated count matches its generated inventory"
    else
        python3 "$COUNT_GATE" --root "$PROJECT_ROOT" || true
        echo "  FAIL: a stated count drifted."
        echo "        Re-derive: python3 vibe-ic-marketplace/plugins/vibe-ic/programs/gen_program_inventory.py"
        echo "        Re-type  : python3 vibe-ic-marketplace/plugins/vibe-ic/programs/stated_count_drift_check.py --fix"
        ERRORS=$((ERRORS + 1))
    fi
else
    # A gate that is not there has NOT passed.
    echo "  FAIL: stated_count_drift_check.py absent — NOT CHECKED"
    ERRORS=$((ERRORS + 1))
fi

# --------------------------------------------------------------------------
# 5. Check for accidental secret/credential files
# --------------------------------------------------------------------------
echo ""
echo "--- Secret File Check ---"

STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || true)
SECRET_PATTERNS=".env credentials.json .secret api_key token.json"
SECRET_FOUND=0

for pattern in $SECRET_PATTERNS; do
    for f in $STAGED_FILES; do
        if echo "$f" | grep -qi "$pattern"; then
            echo "  WARNING: Potential secret file staged: $f"
            SECRET_FOUND=$((SECRET_FOUND + 1))
        fi
    done
done

if [ $SECRET_FOUND -eq 0 ]; then
    echo "  PASS: No secret files detected in staged changes"
else
    echo "  WARNING: $SECRET_FOUND potential secret file(s) detected"
    echo "  Review staged files before committing!"
    # Don't block commit for warnings, but inform
fi

# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
echo ""
echo "============================================"
if [ $ERRORS -eq 0 ]; then
    echo "  All checks PASSED"
    echo "============================================"
    exit 0
else
    echo "  $ERRORS check(s) FAILED"
    echo "  Fix issues before committing."
    echo "============================================"
    exit 1
fi
