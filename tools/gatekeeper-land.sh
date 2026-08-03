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
# REPORT, not a gate. Prints what a probe found and NEVER touches FAILED.
#
# It exists so that a measurement whose blast radius is not yet a landing bar
# still EXECUTES against every landing instead of being parked in a flag nobody
# passes. The distinction is written into the label, so a reader of this log
# can never mistake a REPORT line for a PASS.
report() {                           # report <label> <cmd…>
  local label="$1"; shift
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then
    printf '  REPORT  %s\n' "$label"
  else
    printf '  REPORT  %s (rc=%s — NOT blocking)\n' "$label" "$rc"
  fi
  printf '%s\n' "$out" | grep -aE 'REPORT|VIOLATION|\[FAIL\]|\[SKIP\]' \
    | head -8 | sed 's/^/            /'
}
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
  # vibe-ic#635 — a NEW published number must arrive with its composition.
  # Scoped `--changed-since` like the gate above: 20 of the 25 runs already
  # published carry no per-problem name set, and applying this retroactively
  # would fail every landing over work nobody is doing.
  run "benchmark run manifest" python3 "$PROGRAMS/benchmark_run_manifest.py" check --tree benchmark-data --changed-since "$BASE"
  git log --format='%B' "$RANGE" > /tmp/gk_commit_text.txt 2>/dev/null
  run "git prohibition guard"   python3 "$PROGRAMS/git_prohibition_guard.py" /tmp/gk_commit_text.txt
  # 2026-08-03 — the batch that landed five PRs from a 6.5-hour-stale base and
  # let three of its own commits erase the other two. `gatekeeper_stale_branch_check`
  # said STALE_OVERLAP on all five BEFORE the land; nothing looked at the
  # commits AFTER they existed, which is the artefact this script pushes.
  run "no collateral revert within the push" \
      python3 "$PROGRAMS/landing_collateral_revert_check.py" --repo "$ROOT" --rev-range "$RANGE"
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

# Everything above reasons about COMMITS. A tracked file still modified in the
# worktree means the tree they verified is not the tree the author has.
#
# v1.9.12 landed HALF of #591 this way: `git stash pop` does not restore
# staged-ness, and the explicit `git add` that followed named two of the four
# files. The commit message asserted "undecided silence is a hard error" and the
# hard error was in one of the two left behind. Every gate here passed, because
# the test file was left behind WITH the code it tests — the landed repository
# was self-consistent, which is exactly what a suite measures.
#
# Cheap tier: it is one `git status`, and it is the last thing that can tell a
# complete landing from a coherent fragment of one.
#
# ...and the tree must still be THAT tree when the stamp is written. The full
# tier below runs for minutes and reads the WORKTREE, while the stamp names a
# COMMIT. On the v1.9.16 run the gate started at 10:28 on a clean tree, an
# unrelated file was edited at 10:35, and the targeted tests ran at 10:41 and
# stamped 9fd81bb45 — a tree that never existed. FP is per-run, so two gates in
# one checkout do not read each other's.
FP="$(mktemp -t gk_fingerprint.XXXXXX)"
trap 'rm -f "$FP"' EXIT
run "worktree carries no uncommitted change" \
    python3 "$PROGRAMS/landing_worktree_is_clean_check.py" "$ROOT" \
        --emit-fingerprint "$FP"

# The gate above deliberately EXCLUDES untracked paths (`??`) — see its module
# docstring. That exclusion is right for its question and leaves a gap for a
# different one: an untracked, un-ignored `*scratch*` path is one `git add -A`
# from being committed, which is why this repo forbids `-A`. ORGANIC #720 found
# four of them sitting in the tree for three to nine days.
#
# REPORT, not a gate, and the reason is measured rather than cautious: all four
# of those paths are ignored at origin/main (`.gitignore` 139-143), so across
# 250 checkouts on one host the ONLY thing this half still finds is
# `vibe-ic-marketplace/scratch_geom_signoff_tests/` in 61 checkouts that are
# BEHIND origin/main. A bar whose one instance is already closed is a bar that
# only ever fires on somebody's scratch notes. `--worktree-blocking` promotes
# it when that changes.
report "untracked scratch paths in this checkout" \
    python3 "$PROGRAMS/gitignore_scratch_guard.py" --root "$ROOT" \
        --include-worktree

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

# LAST, and after every suite has read the tree. Everything above answers
# "do the gates pass"; this answers "did they all read the same tree", which is
# the question the stamp actually asserts.
run "worktree unchanged since the gates started" \
    python3 "$PROGRAMS/landing_worktree_is_clean_check.py" "$ROOT" \
        --expect-fingerprint "$FP"

if [ "$FAILED" -eq 0 ]; then
  # Stamp the exact commit these suites were verified against. The hook compares
  # this to what is being pushed, so a later commit invalidates it automatically.
  #
  # `--absolute-git-dir`, not "$ROOT/.git". In a WORKTREE `.git` is a FILE (a
  # `gitdir:` pointer), so the redirect died with "Not a directory" and no stamp
  # was ever written — while the hook, computing the same path the same way,
  # found no stamp and refused the push. Landing from a worktree was therefore
  # impossible, and the failure named neither cause. `--absolute-git-dir` gives
  # the PER-WORKTREE dir (…/.git/worktrees/<name>), which is what this stamp
  # must be: two worktrees sitting at different commits must not share one, or a
  # gate run in one would authorise a push from the other.
  git rev-parse HEAD > "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"
  echo "=== ALL GATES PASS — stamped $(git rev-parse --short HEAD) ==="
else
  rm -f "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"
  echo "=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ==="
fi
exit "$FAILED"
