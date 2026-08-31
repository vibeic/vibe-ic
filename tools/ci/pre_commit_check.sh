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
# 4.6. Package invariants (W7 — the rule lives next to the code it binds)
# --------------------------------------------------------------------------
# Two things happen here, and they are deliberately different.
#
# ENFORCE: every enrolled package must still carry a non-empty INVARIANTS.json,
# every declared rule must hold over that package's own files, and every rule
# must still reject its own counterexample. Deleting the file is a FAIL, not a
# silence -- an absent invariant file must never read as "no constraints".
#
# READ: the invariants binding the packages this commit TOUCHES are printed
# back to the author. That is the whole point of moving the rules out of the
# centre: the rule is visible at the moment the code it binds is being changed,
# without anyone having to go and look for it.
echo ""
echo "--- Package invariants ---"
PKG_INV="$PROJECT_ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs/package_invariants_check.py"
if [ -f "$PKG_INV" ]; then
    if python3 "$PKG_INV" --repo-root "$PROJECT_ROOT"; then
        STAGED_FOR_INV=$(git -C "$PROJECT_ROOT" diff --cached --name-only 2>/dev/null || true)
        if [ -n "$STAGED_FOR_INV" ]; then
            # shellcheck disable=SC2086
            python3 "$PKG_INV" --repo-root "$PROJECT_ROOT" --touched $STAGED_FOR_INV
        fi
    else
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "  SKIP: package_invariants_check.py not present"
fi

# --------------------------------------------------------------------------
# The manifest a commit carries must describe the tree that commit ships.
#
# A landing carries tools/ci/protected_landing_transition.json and, before this,
# NOTHING verified it was rendered against the tree it travels with -- the
# lander references the transition validator zero times and the hygiene set's
# one reference is a comment. Batch 72 shipped a manifest rendered two mains
# earlier and no gate said a word.
#
# Wired HERE, and not into repo_hygiene_gates.sh or gatekeeper-land.sh, because
# both are PROTECTED paths and editing one to add a protected-path check is the
# circularity this whole class comes from. This runner is the honest home: the
# rule is visible at the moment the tree it binds is being changed.
#
# rc 2 is "could not look" and must not fail a commit -- a working tree with no
# manifest, or one not in a git checkout, is not a finding about the tree.
# --------------------------------------------------------------------------
echo ""
echo "--- Protected manifest describes its tree ---"
MAN_TREE="$PROJECT_ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs/transition_manifest_describes_its_tree_check.py"
MAN_PROT_LIST="$PROJECT_ROOT/tools/ci/protected_landing_transition.json"
if [ -f "$MAN_TREE" ]; then
    # `set -e` is in force at the top of this file, so the checker is called
    # inside an `if` -- a bare call returning 1 would exit the runner here and
    # every check BELOW would silently never run. That is worse than the defect
    # this block exists for, and it is how the block was first written.
    MAN_TREE_RC=0
    python3 "$MAN_TREE" --repo "$PROJECT_ROOT" --ref HEAD || MAN_TREE_RC=$?
    if [ "$MAN_TREE_RC" -eq 1 ]; then
        # SCOPED TO WHAT THE COMMITTER CAN ACT ON. MEASURED on `30dca502ed`
        # (v1.14.26): main is drifted from `current` on 4 of its 52 protected
        # paths and from `next` on 1. Failing every commit for that would
        # block people who touched nothing protected and can do nothing about
        # it -- a gate nobody can satisfy gets disabled, and then it protects
        # nothing. It is an ERROR only when this commit touches a protected
        # path or the manifest; otherwise the drift is REPORTED and the commit
        # proceeds. Scoping, not softening: the blocking case is exactly the one
        # where landing would ship a manifest that lies about its tree.
        MAN_TREE_HITS=""
        if [ -f "$MAN_PROT_LIST" ]; then
            MAN_TREE_HITS=$(git -C "$PROJECT_ROOT" diff --cached --name-only 2>/dev/null \
                | python3 -c 'import json,sys
prot=set()
try:
    prot={f["path"] for f in json.load(open(sys.argv[1]))["current"]["files"]}
except Exception:
    pass
prot.add("tools/ci/protected_landing_transition.json")
for ln in sys.stdin.read().split():
    if ln in prot:
        print(ln)' "$MAN_PROT_LIST" || true)
        fi
        if [ -n "$MAN_TREE_HITS" ]; then
            echo "  BLOCKING: this commit touches a protected path, so it would"
            echo "  ship a manifest that does not describe its own tree:"
            printf '    %s\n' $MAN_TREE_HITS
            ERRORS=$((ERRORS + 1))
        else
            echo "  REPORTED, not blocking: this commit touches no protected path"
            echo "  and no manifest, so it cannot repair the drift above."
        fi
    elif [ "$MAN_TREE_RC" -eq 2 ]; then
        echo "  NOT CHECKED (rc 2): see the reason above. Not a finding."
    fi
else
    echo "  SKIP: transition_manifest_describes_its_tree_check.py not present"
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
