#!/usr/bin/env bash
# gatekeeper-land.sh — everything `gatekeeper-ci.yml` and `ci.yml` would have run,
# run locally, because Actions is disabled at the account level (vibe-ic#550) and
# the appeal was rejected. This is not a stopgap: it is the enforcement path.
#
# Split by cost, because a slow check is a bypassed check:
#
#   CHEAP  — also run by the pre-push hook on EVERY push (see tools/git-hooks/).
#   FULL   — the multi-minute suites. Too slow for a hook, so on success this
#            script stamps `.git/gatekeeper-stamp` with the tree SHA it verified,
#            and the pre-push hook REFUSES a push whose commit has no matching
#            stamp. That makes the expensive tier enforced rather than optional.
#
# Usage:  tools/gatekeeper-land.sh [--cheap-only]
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel)"
PROGRAMS="$ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs"
PLUGIN="$ROOT/vibe-ic-marketplace/plugins/vibe-ic"
PJSON="$PLUGIN/.claude-plugin/plugin.json"
BASE="${GATEKEEPER_BASE:-origin/main}"
RANGE="${BASE}..HEAD"
CHEAP_ONLY=0
[ "${1:-}" = "--cheap-only" ] && CHEAP_ONLY=1

FAILED=0
run() {                              # run <label> <cmd…>
  local label="$1"; shift
  local out
  if out="$("$@" 2>&1)"; then
    printf '  PASS  %s\n' "$label"
  else
    printf '  FAIL  %s\n' "$label"
    # The FAILING lines first, then the tail — not the tail alone.
    #
    # A gate that aggregates others puts its failure in the middle and its
    # summary at the end, so `tail` shows the wrong thing by construction. On
    # 2026-07-30 this reported `FAIL repo hygiene gates` (37 sub-gates) with
    # five lines of a DIFFERENT sub-gate's PASS output underneath it. The
    # failure was real, it was named nowhere, and the whole 17-minute run had
    # to be repeated just to find out which gate it was.
    #
    # The tail is kept because the summary line usually lives there and is
    # worth having; it is no longer the ONLY thing kept.
    printf '%s\n' "$out" \
      | grep -aE '^[[:space:]]*(FAIL|ERROR)|\[FAIL\]|\[ERROR\]|FAILED' \
      | head -12 | sed 's/^/          /'
    printf '%s\n' "$out" | tail -5 | sed 's/^/          /'
    FAILED=1
  fi
}

echo "=== gatekeeper landing gates — base=$BASE ==="
echo "--- cheap tier (also enforced by the pre-push hook) ---"

# An empty range means nothing new is being landed; the NDA checkers correctly
# refuse an empty scan, so the no-op is skipped rather than reported as a pass.
if [ "$(git rev-list --count "$RANGE" 2>/dev/null || echo 0)" != "0" ]; then
  run "NDA — commit messages"   python3 "$PROGRAMS/commit_msg_nda_check.py" --repo "$ROOT" --rev-range "$RANGE"
  run "NDA — added content/paths" python3 "$PROGRAMS/nda_diff_scan_check.py" --rev-range "$RANGE"
  run "version bumped monotonically" python3 "$PROGRAMS/version_bump_monotonic_check.py" --plugin-json "$PJSON" --base "$BASE"
  run "agent check-in scope"    python3 "$PROGRAMS/agent_checkin_scope_guard.py" --role core-agent --base "$BASE"
  run "benchmark evidence structure" python3 "$PROGRAMS/benchmark_evidence_structure_check.py" --tree benchmark-data --changed-since "$BASE"
  git log --format='%B' "$RANGE" > /tmp/gk_commit_text.txt 2>/dev/null
  run "git prohibition guard"   python3 "$PROGRAMS/git_prohibition_guard.py" /tmp/gk_commit_text.txt
else
  echo "  SKIP  range is empty — nothing new to land"
fi
run "marketplace <-> plugin version sync" python3 "$PROGRAMS/marketplace_version_sync_check.py"
# A landing is normally ONE commit. A batch is legitimate when several
# independent changes land together — NO-MIX forces a benchmark-data fix and a
# plugin change into separate commits, for instance — and the gate accepts that
# via --batch, which additionally requires the version bump to sit on the TIP.
# Auto-detected rather than configured, so a batch is never silently waved
# through as if it were a single landing.
if [ "$(git rev-list --count "$RANGE" 2>/dev/null || echo 0)" -gt 1 ]; then
  run "landing is a valid batch (version on tip)" \
      python3 "$PROGRAMS/landing_is_one_commit_check.py" --base "$BASE" --batch
else
  run "landing is one commit" \
      python3 "$PROGRAMS/landing_is_one_commit_check.py" --base "$BASE"
fi

if [ "$CHEAP_ONLY" = "1" ]; then
  echo "--- full tier SKIPPED (--cheap-only) — no stamp will be written ---"
  exit "$FAILED"
fi

echo "--- full tier (minutes; stamps the tree on success) ---"

# The TARGETED TEST RUN, carried over verbatim from the retired ci.yml:130-132.
# Omitted from the first version of this script, which covered the governance
# gates and quietly dropped the tests — the gap surfaced when
# `ci_harness_timeout_ceiling_check` lost its input and reported CANNOT
# DETERMINE rather than passing.
#
# `--timeout=180` is load-bearing beyond this run: that check resolves the
# harness bound from this line and fails any inner subprocess timeout above it,
# because an inner bound larger than the harness does not fail a test — it
# outlives the harness and takes the session down.
run_pytest() {
  local sel=/tmp/gk_sel.txt out
  ( cd "$PLUGIN" && python3 programs/ci_targeted_test_select.py --base "$BASE" > "$sel" ) 2>/dev/null
  if [ ! -s "$sel" ]; then
    echo "  FAIL  targeted test selection produced no files — not a clean result"
    FAILED=1; return
  fi
  if out="$( cd "$PLUGIN" && xargs -a "$sel" pytest -q --maxfail=10 --timeout=180 --timeout-method=thread 2>&1 )"; then
    printf '  PASS  targeted tests (%s file(s))\n' "$(wc -l < "$sel")"
  else
    printf '  FAIL  targeted tests (%s file(s))\n' "$(wc -l < "$sel")"
    printf '%s\n' "$out" | tail -6 | sed 's/^/          /'
    FAILED=1
  fi
}
run_pytest

run "repo hygiene gates"      bash "$ROOT/tools/ci/repo_hygiene_gates.sh"
run "plugin full audit"       python3 "$PROGRAMS/plugin_full_audit.py" "$PLUGIN"

if [ "$FAILED" -eq 0 ]; then
  # Stamp the exact commit these suites were verified against. The hook compares
  # this to what is being pushed, so a later commit invalidates it automatically.
  git rev-parse HEAD > "$ROOT/.git/gatekeeper-stamp"
  echo "=== ALL GATES PASS — stamped $(git rev-parse --short HEAD) ==="
else
  rm -f "$ROOT/.git/gatekeeper-stamp"
  echo "=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ==="
fi
exit "$FAILED"
