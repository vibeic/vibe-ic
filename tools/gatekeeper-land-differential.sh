#!/usr/bin/env bash
# gatekeeper-land-differential.sh — THE LANDING GATE, ASKING THE RIGHT QUESTION.
#
# Reached as `tools/gatekeeper-land.sh --differential`, which is the intended
# entry point; this file is the machinery.
#
# WHY THIS FILE EXISTS
# ====================
# `tools/gatekeeper-land.sh` judges ABSOLUTELY: every stage is "did anything
# fail", with no reference to what the base tree already does. `tools/git-hooks/
# pre-push` refuses any push to `main` whose commit has no passing stamp, and
# only `gatekeeper-land.sh` writes that stamp. Put those two together with a
# `main` that is itself red and you get a DEADLOCK, not a gate:
#
#   MEASURED 2026-08-17 on 8HD-8, in a detached worktree AT origin/main
#   (f6b0e77dd), running the gate on the base's OWN tip:
#       FAIL  repo tools tests (31 file(s))     9 failed, 650 passed
#       FAIL  repo hygiene gates                1 of 80 decided gates FAILED
#       === FAILURES ABOVE — stamp removed; the pre-push hook will refuse ===
#   and then, fed the exact stdin git feeds a `git push origin main`:
#       pre-push: FAILED — the full suites have not been run for this commit
#
# `main`'s own tip cannot be re-pushed to `main`. Neither can a commit that
# FIXES those reds. A gate that refuses every landing is a ban, and a ban is
# what teaches an operator to reach for `gh pr merge` — the bypass this whole
# battery exists to close.
#
# THE RULE THIS IMPLEMENTS IS NOT NEW, AND DELIBERATELY SO
# ========================================================
# `tools/gatekeeper-verify-merge.sh` has answered the right question on the
# MERGE path since vibe-ic#1019: run the same gates on the UNTOUCHED BASE as
# well, and judge the candidate on WHAT IT BREAKS. This script is that same
# rule, with the same programs, on the DIRECT-PUSH path — where nothing has
# ever performed the differential at all (`gatekeeper-land.sh:536-538` says so
# in its own words: "the differential still has to decide whether they were
# pre-existing", and that differential lives in verify-merge, not in land).
#
# ONE RULE, ONE JUDGE. The verdict is computed by `landing_merge_verdict.py` —
# the SAME function, `decide()`, with the SAME decision table — and by nothing
# here. This script only MEASURES. If you find yourself about to add an `if` in
# this file that decides whether something is acceptable, it belongs in the
# verdict program instead, or it is a second dialect.
#
#   REGRESSION means: did THIS change break something that used to work.
#   It does not mean: the tree is entirely green.
#
# WHAT IS DIFFERENCED, WHAT STAYS ABSOLUTE, AND WHY — READ THIS BEFORE EDITING
# ===========================================================================
# The rule is stated once, in `gatekeeper-verify-merge.sh:845-852` and
# `gatekeeper-land.sh:202-208`, and it is about the SUBJECT of a check:
#
#   ABSOLUTE  <=> the subject is the RANGE `BASE..HEAD` — the commits and the
#                 diff this landing introduces. The base arm runs AT the base
#                 with `GATEKEEPER_BASE=<base sha>`, so its range is `X..X` =
#                 EMPTY and every range-scoped gate SKIPs there. A gate that can
#                 never appear in the base's failing set can never be excused,
#                 so any failure of it on the candidate is necessarily the
#                 candidate's. In `gatekeeper-land.sh` those are:
#                     NDA — commit messages                  (:127)
#                     NDA — added content/paths              (:128)
#                     version bumped monotonically           (:140)
#                     agent check-in scope                   (:142)
#                     benchmark evidence structure           (:152)
#                     benchmark run manifest                 (:157)
#                     git prohibition guard                  (:165)
#                     no collateral revert within the push   (:171)
#                     tree contains the base it claims as parent (:188)
#                     landing is one commit / valid batch    (:213/:216)
#                 INHERITING AN NDA VIOLATION IS NOT A LICENCE TO ADD ONE, and
#                 for these it never can be: they are absolute by construction,
#                 not by a list anyone has to maintain here.
#
#                 PRECONDITION, and it is the laundering hole if it is ever
#                 broken: each of those MUST SKIP — not FAIL — over an empty
#                 range. A range-scoped gate that fails VACUOUSLY on the base
#                 enters the base's failing set and is then excused on every
#                 candidate forever. `--assert-empty-range-skips` checks this on
#                 the real base arm log, every run, and refuses if any
#                 range-scoped label is FAIL there.
#
#   DIFFERENCED <=> the subject is the WHOLE TREE, which the base can
#                 legitimately be red on today. `repo tools tests`,
#                 `repo hygiene gates`, `unselectable tests`, `plugin full
#                 audit`, `marketplace <-> plugin version sync`, and the
#                 targeted test tier. These are the ones the deadlock is made
#                 of, and the only ones a base failure may excuse.
#
# Two more families are ABSOLUTE for a reason orthogonal to the range, and the
# verdict program owns both — they are named here only so a reader of this file
# knows they are not silently missing:
#
#   MEASUREMENT COMPLETENESS — "I could not look" must never reach a reader as
#       "I looked and it was fine". An aggregate session with no complete
#       record, a truncated run, a selected file that produced no test case, a
#       base arm that did not finish: all refusals, on BOTH arms, and
#       explicitly unwaivable by the base's gate log
#       (`landing_merge_verdict.py:955-973`). THE BASE SIDE IS ABSOLUTE
#       PRECISELY BECAUSE THE BASE IS THE PERMISSIVE ARM.
#   TREE IDENTITY / ARM ISOLATION — the tree measured must be the tree that
#       lands, and no arm may have written into its own subject. Attested after
#       the fact, per arm, by `attest_test_worktree` below.
#
# UNKNOWN NEVER BUYS LENIENCY. Every degradation in this design is toward
# STRICTER: an unreadable base junit makes the base failed-set EMPTY, so every
# candidate red is NEW; an absent base gate log makes every blocking FAIL count
# against the branch; a base hygiene record measured on ANOTHER HOST is refused
# by `hygiene_finding_delta` rather than subtracted, and this script then
# promotes the hygiene tier to ABSOLUTE instead of letting it fall back to the
# coarse per-label comparison (see `--base-evidence`).
#
# CONCURRENCY IS NOT AN OPTIMISATION HERE
# =======================================
# A full round is ~31 minutes of gate wall clock. Serialised, a differential
# costs an hour and turns into a gate people skip. The four arms therefore run
# AT THE SAME TIME, each in its OWN checkout — A1/A2 must not share one, because
# tests in this repository have been observed writing into their worktree and a
# shared checkout makes one arm grade the other's residue
# (`gatekeeper-verify-merge.sh:705-717`).
#
#   A1  targeted tests on the UNTOUCHED base      NO --maxfail, ever
#   A2  gatekeeper-land.sh on the UNTOUCHED base  range forced EMPTY
#   B1  targeted tests on the candidate           --stop-after-failures 0
#   B2  gatekeeper-land.sh on the candidate       targeted tier skipped
#
# TWO HOSTS: `--base-arm-only <dir>` runs A1+A2 and writes an evidence bundle;
# `--base-evidence <dir>` consumes one instead of running them.
#
# AND THE SECOND HOST IS A CROSS-CHECK, NOT A SHORTCUT. This was built to split
# the cost across two machines and the measurement says it cannot be used that
# way. Same base f6b0e77dd, same 90-file selection, same driver, 2026-08-18:
#
#     8HD-8   2176 test id(s)   6 red
#     8HD-4   2118 test id(s)   9 red   (+3 environment-dependent, 58 ids absent)
#
# Subtracting the second host's baseline from a candidate measured on the first
# would excuse three failures the first host calls NEW. A red baseline is not
# portable. So a bundle whose `host` is not this one is READ, PRINTED, and NEVER
# SUBTRACTED: the run degrades to DEMAND GREEN and the hygiene tier to ABSOLUTE.
# `hygiene_finding_delta` already refuses a cross-host pair for the same reason
# one dimension over (`hygiene_finding_delta.py:118-124, :372-392`).
#
# BOTH ARMS ON ONE HOST IS THE ONLY CONFIGURATION THAT CAN SUBTRACT ANYTHING,
# and it is the default. Concurrency is what makes that affordable, not a
# second machine.
#
# Usage:
#   tools/gatekeeper-land-differential.sh [--base <ref>] [--json <path>]
#       [--repo <path>] [--keep] [--no-stamp] [--verdict-from <repo>]
#       [--base-arm-only <dir>] [--base-evidence <dir>]
#
# Exit: 0 stamped / 1 refused / 2 could not measure (also refused).
set -uo pipefail

# See `gatekeeper-verify-merge.sh:159-170`: git exports GIT_DIR when a push or a
# hook originates in a worktree, and `git -C` does not override it.
unset GIT_DIR GIT_WORK_TREE
export GIT_NO_REPLACE_OBJECTS=1

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_REF="origin/main"; JSON_OUT=""; REPO=""; KEEP=0; NO_STAMP=0
VERDICT_FROM=""; BASE_ARM_ONLY=""; BASE_EVIDENCE=""

die() { printf 'gatekeeper-land-differential: %s\n' "$*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --base)           BASE_REF="${2:?}"; shift 2 ;;
    --repo)           REPO="${2:?}"; shift 2 ;;
    --json)           JSON_OUT="${2:?}"; shift 2 ;;
    --verdict-from)   VERDICT_FROM="${2:?}"; shift 2 ;;
    --base-arm-only)  BASE_ARM_ONLY="${2:?}"; shift 2 ;;
    --base-evidence)  BASE_EVIDENCE="${2:?}"; shift 2 ;;
    --keep)           KEEP=1; shift ;;
    --no-stamp)       NO_STAMP=1; shift ;;
    -h|--help)        sed -n '1,150p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)                die "unknown argument '$1'" ;;
  esac
done

[ -n "$BASE_ARM_ONLY" ] && [ -n "$BASE_EVIDENCE" ] \
  && die "--base-arm-only and --base-evidence are the two halves of one split; pass one"

[ -z "$REPO" ] && REPO="$(git -C "$SELF" rev-parse --show-toplevel 2>/dev/null)"
[ -n "$REPO" ] || die "no repository (pass --repo)"
REPO="$(cd "$REPO" && pwd)"
G=(git -C "$REPO")
PLUGIN_REL="vibe-ic-marketplace/plugins/vibe-ic"

BASE_SHA="$("${G[@]}" rev-parse --verify "${BASE_REF}^{commit}" 2>/dev/null)" \
  || die "cannot resolve base '$BASE_REF'"
HEAD_SHA="$("${G[@]}" rev-parse --verify 'HEAD^{commit}' 2>/dev/null)" \
  || die "cannot resolve HEAD"
HEAD_TREE="$("${G[@]}" rev-parse --verify 'HEAD^{tree}')"
BASE_TREE="$("${G[@]}" rev-parse --verify "${BASE_SHA}^{tree}")"
THIS_HOST="$(uname -n)"

RUN="$(mktemp -d "${TMPDIR:-/tmp}/gk_land_diff.XXXXXX")"
WT_BASE_TESTS="$RUN/wt_base_tests"
WT_BASE_GATES="$RUN/wt_base_gates"
WT_CAND_TESTS="$RUN/wt_cand_tests"
WT_CAND_GATES="$RUN/wt_cand_gates"
cleanup() {
  local w
  [ "$KEEP" = "1" ] && return 0
  for w in "$WT_BASE_TESTS" "$WT_BASE_GATES" "$WT_CAND_TESTS" "$WT_CAND_GATES"; do
    [ -d "$w" ] && "${G[@]}" worktree remove --force "$w" >/dev/null 2>&1
  done
  "${G[@]}" worktree prune >/dev/null 2>&1
  rm -rf "$RUN"
}
trap cleanup EXIT

echo "=== gatekeeper landing gate — DIFFERENTIAL (direct-push path) ==="
echo "--- base ${BASE_SHA:0:12}  candidate ${HEAD_SHA:0:12}  host $THIS_HOST"
echo "--- run dir $RUN"

# ------------------------------------------------------------------ preflight
# ABSOLUTE, and it has no base-side analogue: the four arms run in THROWAWAY
# checkouts, so `gatekeeper-land.sh`'s own "worktree carries no uncommitted
# change" gate would answer about a tree the operator never touched. The
# question it exists for — "is the tree you are pushing the tree that was
# measured" — is asked HERE, about the operator's checkout, or it is not asked.
if ! PRE="$(python3 "$REPO/$PLUGIN_REL/programs/landing_worktree_is_clean_check.py" \
        "$REPO" 2>&1)"; then
  echo "  FAIL  the pushing worktree carries uncommitted change (ABSOLUTE — no"
  echo "        base failure can excuse it; the arms measure commits, and a"
  echo "        dirty tree is not the commit you would push)"
  printf '%s\n' "$PRE" | tail -8 | sed 's/^/          /'
  exit 1
fi
if [ "$BASE_SHA" = "$HEAD_SHA" ]; then
  die "HEAD is the base — there is nothing to land, and a differential over an empty range is not a landing"
fi
if ! "${G[@]}" merge-base --is-ancestor "$BASE_SHA" "$HEAD_SHA"; then
  die "HEAD does not descend from $BASE_REF — rebase first; a differential against a base you are not on measures nothing"
fi

# THE JUDGE. On the merge path it comes from the VERIFIER's repo and never the
# subject's (`gatekeeper-verify-merge.sh:99-110`). On the DIRECT-PUSH path
# there is no second repo by construction — the operator's checkout IS the tree
# under test — so the asymmetry cannot be had for free. Two things are done
# about it instead of pretending otherwise:
#   1. `--verdict-from <repo>` lets a gatekeeper point at a trusted checkout;
#   2. failing that, any candidate-side edit to the judge or to the differencing
#      helpers is DISCLOSED through the verdict's own `--gate-edited` seam,
#      which is disclosed-never-blocking on purpose (a change that improves the
#      gate has to be landable).
VERDICT_PROG="$REPO/$PLUGIN_REL/programs/landing_merge_verdict.py"
if [ -n "$VERDICT_FROM" ]; then
  VERDICT_PROG="$VERDICT_FROM/$PLUGIN_REL/programs/landing_merge_verdict.py"
  [ -f "$VERDICT_PROG" ] || die "no verdict program under --verdict-from $VERDICT_FROM"
fi
GATE_ARGS=()
while read -r p; do
  [ -n "$p" ] && GATE_ARGS+=(--gate-edited "$p")
done < <("${G[@]}" diff --name-only "$BASE_SHA" "$HEAD_SHA" -- \
            tools/gatekeeper-land.sh tools/gatekeeper-land-differential.sh \
            tools/gatekeeper-verify-merge.sh tools/ci/repo_hygiene_gates.sh \
            tools/git-hooks/pre-push \
            "$PLUGIN_REL/programs/landing_merge_verdict.py" \
            "$PLUGIN_REL/programs/hygiene_finding_delta.py" \
            "$PLUGIN_REL/programs/ci_targeted_test_select.py" \
            "$PLUGIN_REL/programs/pytest_per_file_junit.py" 2>/dev/null)

# ----------------------------------------------------- arm-isolation attestation
# Lifted verbatim in behaviour from `gatekeeper-verify-merge.sh:250-325` — a
# fresh index built from the EXPECTED TREE, so assume-unchanged / skip-worktree
# cannot hide edited bytes from this decision. One rule, one implementation of
# it; if this ever needs changing, change it there too.
attest_test_worktree() {
  local wt="$1" expected_commit="$2" expected_tree="$3" label="$4"
  local report="$RUN/${label}.worktree_status"
  local index="$RUN/.${label}.attestation-index"
  local tracked="$RUN/.${label}.tracked-diff"
  local untracked="$RUN/.${label}.untracked"
  local head rc flags
  if ! head="$(git -C "$wt" rev-parse HEAD 2>/dev/null)"; then
    printf 'inspection failed: cannot read HEAD\n' > "$report"; printf 'unknown\n'; return
  fi
  if [ "$head" != "$expected_commit" ]; then
    printf 'expected=%s\nactual=%s\n' "$expected_commit" "$head" > "$report"
    printf 'wrong-head\n'; return
  fi
  if ! flags="$(git -C "$wt" ls-files -v 2>/dev/null)"; then
    printf 'inspection failed: cannot read subject index flags\n' > "$report"
    printf 'unknown\n'; return
  fi
  if printf '%s\n' "$flags" | grep -Eq '^(S|[a-z]) '; then
    printf 'subject index contains assume-unchanged/skip-worktree entries\n' > "$report"
    printf '%s\n' "$flags" | grep -E '^(S|[a-z]) ' >> "$report"
    printf 'dirty\n'; return
  fi
  if ! GIT_INDEX_FILE="$index" git -C "$wt" read-tree "$expected_tree" >/dev/null 2>&1; then
    printf 'inspection failed: cannot materialize expected tree index\n' > "$report"
    printf 'unknown\n'; return
  fi
  GIT_INDEX_FILE="$index" git -C "$wt" update-index --really-refresh >/dev/null 2>&1 || true
  GIT_INDEX_FILE="$index" git -C "$wt" diff-files --name-status \
      --no-ext-diff --no-textconv --ignore-submodules=none > "$tracked" 2>/dev/null
  rc=$?
  if [ "$rc" -gt 1 ]; then
    printf 'inspection failed: cannot compare tracked worktree bytes\n' > "$report"
    printf 'unknown\n'; return
  fi
  if ! GIT_INDEX_FILE="$index" git -C "$wt" ls-files --others --exclude-standard \
       > "$untracked" 2>/dev/null; then
    printf 'inspection failed: cannot enumerate untracked files\n' > "$report"
    printf 'unknown\n'; return
  fi
  if [ -s "$tracked" ] || [ -s "$untracked" ]; then
    {
      [ ! -s "$tracked" ] || { printf 'tracked differences:\n'; cat "$tracked"; }
      [ ! -s "$untracked" ] || { printf 'untracked files:\n'; cat "$untracked"; }
    } > "$report"
    printf 'dirty\n'; return
  fi
  printf 'clean\n'
}

# ------------------------------------------------------------- the two subjects
BASE_JUNIT="$RUN/base.xml"
CAND_JUNIT="$RUN/candidate.xml"
BASE_LAND_LOG="$RUN/base_land.log"
CAND_LAND_LOG="$RUN/land.log"
BASE_HYG="$RUN/base_hygiene.json"
CAND_HYG="$RUN/candidate_hygiene.json"
: > "$RUN/selection.txt"
: > "$RUN/selection_base.txt"
A1_STATUS=unknown
# NO `B1_RC`. The candidate test arm's process status is not an input to the
# verdict and must not look like one: the driver's own
# `whole_selection::process_exit` case carries the attested rc inside the
# junit, and that is what `landing_merge_verdict` reads. A second, unread copy
# of it here would read as a backstop that is not wired to anything.
A1_RC=0; A2_RC=2; B2_RC=2
BASE_HYG_HOST="$THIS_HOST"
RUN_BASE_ARMS=1
[ -n "$BASE_EVIDENCE" ] && RUN_BASE_ARMS=0

# THE SELECTION IS COMPUTED ONCE, FROM THE CANDIDATE, and the base list is that
# same list filtered to files that EXIST at the base — a test the change ADDS
# cannot have an opinion there, and its absence is a real outcome the verdict
# reads as ABSENT (`gatekeeper-verify-merge.sh:719-724`).
"${G[@]}" worktree add -q --detach "$WT_CAND_TESTS" "$HEAD_SHA" || die "cannot create the candidate-test worktree"
"${G[@]}" worktree add -q --detach "$WT_CAND_GATES" "$HEAD_SHA" || die "cannot create the candidate-gate worktree"
CAND_PLUGIN="$WT_CAND_TESTS/$PLUGIN_REL"
( cd "$CAND_PLUGIN" && python3 programs/ci_targeted_test_select.py --base "$BASE_SHA" ) \
    > "$RUN/selection.txt" 2>"$RUN/selection.err"
if [ ! -s "$RUN/selection.txt" ]; then
  echo "--- the targeted selection produced no file; that is not a clean result:"
  tail -5 "$RUN/selection.err" | sed 's/^/      /'
fi

if [ "$RUN_BASE_ARMS" = "1" ]; then
  "${G[@]}" worktree add -q --detach "$WT_BASE_TESTS" "$BASE_SHA" || die "cannot create the base-test worktree"
  "${G[@]}" worktree add -q --detach "$WT_BASE_GATES" "$BASE_SHA" || die "cannot create the base-gate worktree"
  BASE_TEST_PLUGIN="$WT_BASE_TESTS/$PLUGIN_REL"
  while read -r f; do
    [ -n "$f" ] && [ -f "$BASE_TEST_PLUGIN/$f" ] && printf '%s\n' "$f" >> "$RUN/selection_base.txt"
  done < "$RUN/selection.txt"
fi

# THE SAME INSTRUMENT ON BOTH SIDES (vibe-ic#1417). The DRIVER is taken from the
# CANDIDATE tree for both arms, exactly as verify-merge does it (:764, :1001):
# a differential is only a differential if the two arms were measured the same
# way, and source-text guessing cannot select a mismatched runner.
DRIVER="$CAND_PLUGIN/programs/pytest_per_file_junit.py"

launch_targeted() {                # launch_targeted <plugin> <sel> <junit> <arm>
  setsid bash -c '
    cd "$1" || exit 2
    exec env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
      GATEKEEPER_VERIFY_ARM="$5" \
      python3 "$4" --selection "$2" --junit "$3" \
      --stall-after "${GATEKEEPER_PYTEST_FILE_STALL_AFTER:-300}" \
      --aggregate-check \
      --aggregate-stall-after "${GATEKEEPER_PYTEST_AGGREGATE_STALL_AFTER:-300}" \
      --fallback-jobs "${GATEKEEPER_PYTEST_FALLBACK_JOBS:-8}" \
      --fallback-rescue-jobs "${GATEKEEPER_PYTEST_RESCUE_JOBS:-32}" \
      --stop-after-failures 0 \
      -- python3 -m pytest -q -p pytest_timeout -p no:cacheprovider \
      --timeout=180 --timeout-method=thread
  ' "gkdiff-$4" "$1" "$2" "$3" "$DRIVER" "$4"
}

# ---------------------------------------------------------------- launch arms
# ALL AT ONCE. Anything that serialises these turns a 35-minute gate into a
# 70-minute one, and a gate that costs an hour is a gate that gets bypassed.
if [ "$RUN_BASE_ARMS" = "1" ] && [ -s "$RUN/selection_base.txt" ]; then
  # `--stop-after-failures 0` and NO `--maxfail`, on purpose and on BOTH arms.
  # `gatekeeper-verify-merge.sh:737-738`: "arm A must produce the COMPLETE
  # pre-existing failed set, and a truncated base makes a new failure look
  # pre-existing." The mirror is the fatal one — `silenced` and `weakened` are
  # read off what was RED on the base, so a base failure that was never
  # measured is a base failure the branch may delete for free.
  launch_targeted "$WT_BASE_TESTS/$PLUGIN_REL" "$RUN/selection_base.txt" \
      "$BASE_JUNIT" A1 > "$RUN/base_tests.log" 2>&1 &
  A1_PID=$!
else
  A1_PID=""
fi

if [ "$RUN_BASE_ARMS" = "1" ]; then
  # `GATEKEEPER_BASE=$BASE_SHA` in a worktree AT `$BASE_SHA` makes the range
  # EMPTY on purpose: the range-scoped gates then SKIP — a failure there is
  # always the candidate's, never pre-existing — and the WHOLE-TREE gates, the
  # ones that CAN be pre-existing red, still run.
  setsid bash -c '
    cd "$1" || exit 2
    exec env GATEKEEPER_VERIFY_ARM=A2 GATEKEEPER_BASE="$2" \
      GATEKEEPER_VERSION_BY_GATEKEEPER=1 \
      GATEKEEPER_SKIP_TARGETED_TESTS=1 \
      GATEKEEPER_NO_STAMP=1 \
      GATEKEEPER_HYGIENE_REPORT="$3" \
      bash tools/gatekeeper-land.sh
  ' gkdiff-a2 "$WT_BASE_GATES" "$BASE_SHA" "$BASE_HYG" \
      > "$BASE_LAND_LOG" 2>&1 &
  A2_PID=$!
else
  A2_PID=""
fi

# NOT IN `--base-arm-only`. That mode exists to measure the BASE on a second
# machine while this one measures the candidate; running the candidate arms
# there too would double the fleet's bill for evidence nobody reads.
B1_PID=""; B2_PID=""; B1_STATUS=clean
if [ -z "$BASE_ARM_ONLY" ]; then
  launch_targeted "$CAND_PLUGIN" "$RUN/selection.txt" "$CAND_JUNIT" B1 \
      > "$RUN/candidate_tests.log" 2>&1 &
  B1_PID=$!
  # NO `GATEKEEPER_VERSION_BY_GATEKEEPER` on the candidate arm. That flag is the
  # authoring-PR deferral — the gatekeeper assigns the version AT MERGE — and
  # this is the PUSH path, where the bump is the pusher's and the gate is
  # unchanged. Leaving it out is what keeps version monotonicity ABSOLUTE here.
  setsid bash -c '
    cd "$1" || exit 2
    exec env GATEKEEPER_VERIFY_ARM=B2 GATEKEEPER_BASE="$2" \
      GATEKEEPER_SKIP_TARGETED_TESTS=1 \
      GATEKEEPER_NO_STAMP=1 \
      GATEKEEPER_HYGIENE_REPORT="$3" \
      bash tools/gatekeeper-land.sh
  ' gkdiff-b2 "$WT_CAND_GATES" "$BASE_SHA" "$CAND_HYG" \
      > "$CAND_LAND_LOG" 2>&1 &
  B2_PID=$!
fi

echo "--- arms launched concurrently: A1=${A1_PID:-none} A2=${A2_PID:-none} B1=${B1_PID:-none} B2=${B2_PID:-none}"

if [ -n "$B1_PID" ]; then
  wait "$B1_PID" || true
  B1_STATUS="$(attest_test_worktree "$WT_CAND_TESTS" "$HEAD_SHA" "$HEAD_TREE" candidate_tests)"
fi
if [ -n "$B2_PID" ]; then wait "$B2_PID"; B2_RC=$?; fi
if [ -n "$A1_PID" ]; then wait "$A1_PID"; A1_RC=$?; fi
if [ -n "$A2_PID" ]; then wait "$A2_PID"; A2_RC=$?; fi
if [ "$RUN_BASE_ARMS" = "1" ] && [ -s "$RUN/selection_base.txt" ]; then
  A1_STATUS="$(attest_test_worktree "$WT_BASE_TESTS" "$BASE_SHA" "$BASE_TREE" base_tests)"
elif [ "$RUN_BASE_ARMS" = "1" ]; then
  A1_STATUS=clean
fi
# A subject-created replacement ref changes what every later object lookup
# means, so it invalidates both attestations at once.
if [ -n "$("${G[@]}" for-each-ref --format='%(refname)' refs/replace 2>/dev/null)" ]; then
  B1_STATUS=dirty
  [ "$A1_STATUS" = "unknown" ] || A1_STATUS=dirty
fi

# ----------------------------------------------- --base-arm-only: publish and stop
if [ -n "$BASE_ARM_ONLY" ]; then
  mkdir -p "$BASE_ARM_ONLY"
  cp "$BASE_JUNIT" "$BASE_ARM_ONLY/base.xml" 2>/dev/null
  cp "$BASE_LAND_LOG" "$BASE_ARM_ONLY/base_land.log" 2>/dev/null
  cp "$BASE_HYG" "$BASE_ARM_ONLY/base_hygiene.json" 2>/dev/null
  cp "$RUN/selection_base.txt" "$BASE_ARM_ONLY/selection_base.txt"
  cp "$RUN/base_tests.log" "$BASE_ARM_ONLY/base_tests.log" 2>/dev/null
  # THE HOST TRAVELS WITH THE RECORD and is never inferred by the consumer:
  # hygiene findings are host-dependent, and a bundle that does not say where it
  # was measured cannot be subtracted from anything.
  printf '%s\n' "$THIS_HOST" > "$BASE_ARM_ONLY/host"
  printf '%s\n' "$BASE_SHA"  > "$BASE_ARM_ONLY/base_sha"
  printf 'a1_rc=%s\na2_rc=%s\na1_worktree=%s\n' "$A1_RC" "$A2_RC" "$A1_STATUS" \
      > "$BASE_ARM_ONLY/manifest"
  echo "=== BASE ARM ONLY — evidence bundle written to $BASE_ARM_ONLY"
  echo "    base ${BASE_SHA:0:12}  host $THIS_HOST  A1 rc=$A1_RC  A2 rc=$A2_RC"
  exit 0
fi

# -------------------------------------------------- --base-evidence: consume one
#
# A FOREIGN BASE ARM IS A CROSS-CHECK, NEVER AN EXCUSE — and that is MEASURED,
# not cautious. Same base commit (f6b0e77dd), same 90-file selection, same
# driver, two fleet hosts, 2026-08-18:
#
#     8HD-8   2176 test id(s)   6 red
#     8HD-4   2118 test id(s)   9 red
#
# The three extra reds on the second host are an environment-dependent family
# (an external simulator's availability), and 58 test ids did not even exist
# there. Subtracting THAT base from a candidate measured here would excuse
# three failures this host would have called NEW — which is precisely the
# laundering direction this whole file exists to close. Nothing about a red
# baseline is portable, so a bundle from another host is READ and REPORTED and
# never subtracted, and the run degrades to DEMAND GREEN.
HYGIENE_TIER_ABSOLUTE=0
if [ -n "$BASE_EVIDENCE" ]; then
  [ -f "$BASE_EVIDENCE/base_sha" ] || die "--base-evidence $BASE_EVIDENCE has no base_sha"
  EV_BASE="$(cat "$BASE_EVIDENCE/base_sha")"
  [ "$EV_BASE" = "$BASE_SHA" ] || die "the base evidence is for ${EV_BASE:0:12}, this landing is against ${BASE_SHA:0:12}"
  EV_HOST="$(cat "$BASE_EVIDENCE/host" 2>/dev/null || echo '')"
  if [ -n "$EV_HOST" ] && [ "$EV_HOST" = "$THIS_HOST" ]; then
    cp "$BASE_EVIDENCE/base.xml" "$BASE_JUNIT" 2>/dev/null
    cp "$BASE_EVIDENCE/base_land.log" "$BASE_LAND_LOG" 2>/dev/null
    cp "$BASE_EVIDENCE/base_hygiene.json" "$BASE_HYG" 2>/dev/null
    cp "$BASE_EVIDENCE/selection_base.txt" "$RUN/selection_base.txt" 2>/dev/null
    BASE_HYG_HOST="$EV_HOST"
    A1_STATUS="$(sed -n 's/^a1_worktree=//p' "$BASE_EVIDENCE/manifest" | tail -1)"
    [ -n "$A1_STATUS" ] || A1_STATUS=unknown
    echo "--- base evidence: ${BASE_SHA:0:12} measured on $EV_HOST — this host, so it is subtracted"
  else
    BASE_HYG_HOST=""
    A1_STATUS=clean
    echo "--- base evidence: measured on ${EV_HOST:-UNKNOWN}, this run is on $THIS_HOST."
    echo "    A RED BASELINE IS NOT PORTABLE — measured 2026-08-18, two hosts gave 6"
    echo "    and 9 reds over the SAME base and the SAME selection, and 58 test ids"
    echo "    existed on only one of them. Subtracting a foreign baseline would"
    echo "    excuse failures this host calls NEW. It is therefore NOT subtracted:"
    echo "    the differential degrades to DEMAND GREEN and the hygiene tier to"
    echo "    ABSOLUTE. The bundle below is a cross-check for a reader, not an"
    echo "    input to the verdict:"
    if [ -s "$BASE_EVIDENCE/base_land.log" ]; then
      sed -n 's/^  FAIL  /      foreign-base-FAIL  /p' "$BASE_EVIDENCE/base_land.log"
    fi
  fi
fi

# ---------------------------------- the hygiene pair, and what a host split costs
HYG_ARGS=()
if [ -s "$BASE_HYG" ] && [ -n "$BASE_HYG_HOST" ] && [ "$BASE_HYG_HOST" = "$THIS_HOST" ]; then
  HYG_ARGS=(--base-hygiene "$BASE_HYG" --candidate-hygiene "$CAND_HYG"
            --base-hygiene-host "$BASE_HYG_HOST" --candidate-hygiene-host "$THIS_HOST")
  echo "--- hygiene finding delta: both arms on $THIS_HOST — the ~80-gate suite is"
  echo "                           differenced FINDING BY FINDING"
else
  # UNKNOWN NEVER BUYS LENIENCY. Without a same-host base record the finding
  # differential cannot answer, and the verdict's own fallback is the COARSE
  # per-label comparison — under which a base-red `repo hygiene gates` excuses
  # the candidate's whole hygiene tier, findings this push INTRODUCED included.
  # That is the permissive direction, so the tier is promoted to ABSOLUTE here
  # instead: a candidate hygiene FAILURE refuses, base or no base.
  HYGIENE_TIER_ABSOLUTE=1
  echo "--- hygiene finding delta: NOT AVAILABLE (base record ${BASE_HYG_HOST:-absent}," \
       "candidate on $THIS_HOST). The hygiene tier is therefore judged ABSOLUTELY"
  echo "                           for this run — stricter, never more lenient."
fi

# ------------------------------------- the protected-source transition receipt
#
# `landing_merge_verdict.read_protected_transition_receipt` REFUSES with
# "PROTECTED LANDING SOURCE TRANSITION IS UNMEASURED" when no receipt is
# supplied, and that refusal is UNMEASURABLE, not a red — so omitting it does
# not make this path lenient, it makes it unable to answer at all, which is the
# ban this whole script exists to end. The receipt is built exactly as
# `gatekeeper-verify-merge.sh:356-365` builds it, from the SAME validator, over
# the candidate worktrees this script already created; only `--candidate`
# differs, because on the direct-push path the pushed commit IS what lands.
#
# FAIL-CLOSED: if the build refuses, nothing is passed and the verdict refuses
# for the reason above. A protected tuple that could not be verified must never
# reach the stamp as one that was. A landing that MOVES a protected path is
# refused here on purpose — `protected_landing_transition.build_receipt:527`
# ("PREPARE changed live protected bytes with the manifest") requires the
# two-commit PREPARE-then-ACTIVATE shape, and this script does not get to
# invent a third.
PROTECTED_RECEIPT="$RUN/protected-landing-transition.json"
PROTECTED_ARGS=()
if python3 "$REPO/tools/ci/protected_landing_transition.py" verify \
     --object-repo "$REPO" --base "$BASE_SHA" --candidate "$HEAD_SHA" \
     --candidate-gates "$WT_CAND_GATES" --candidate-tests "$WT_CAND_TESTS" \
     --receipt "$PROTECTED_RECEIPT" \
   && [ -s "$PROTECTED_RECEIPT" ]; then
  PROTECTED_ARGS=(--protected-transition-receipt "$PROTECTED_RECEIPT")
fi

# -------------------------------------------------------------- the verdict
[ -f "$VERDICT_PROG" ] || die "no verdict program at $VERDICT_PROG"
BASE_LAND_ARG=()
[ -s "$BASE_LAND_LOG" ] && BASE_LAND_ARG=(--base-land-log "$BASE_LAND_LOG")
VERDICT_JSON="${JSON_OUT:-$RUN/verdict.json}"

# `--verified-sha`/`--expected-tree`/`--verified-tree` are the PUSHED commit and
# its tree, because on this path they are the same object: nothing is squashed,
# so the tree measured IS the tree that lands. `--replayed-tree` and
# `--github-tree` stay EMPTY — there is no second computation to cross-check —
# and the tier code says NOT_APPLICABLE rather than NOT_PERFORMED so a reader
# can tell "there was never a second tree" from "we did not look".
python3 "$VERDICT_PROG" \
  --base-sha "$BASE_SHA" --base-tree "$BASE_TREE" --head-sha "$HEAD_SHA" \
  --verified-sha "$HEAD_SHA" --rebase-status ok \
  --expected-tree "$HEAD_TREE" --verified-tree "$HEAD_TREE" \
  --land-log "$CAND_LAND_LOG" --selection "$RUN/selection.txt" \
  --base-selection "$RUN/selection_base.txt" \
  "${BASE_LAND_ARG[@]+"${BASE_LAND_ARG[@]}"}" \
  --base-junit "$BASE_JUNIT" --candidate-junit "$CAND_JUNIT" \
  "${HYG_ARGS[@]+"${HYG_ARGS[@]}"}" \
  "${PROTECTED_ARGS[@]+"${PROTECTED_ARGS[@]}"}" \
  --candidate-gate-rc "$B2_RC" --require-composite-gate-record \
  --candidate-test-worktree-status "$B1_STATUS" \
  --base-test-worktree-status "$A1_STATUS" \
  --verification-tier direct-push \
  --git-version "$(git --version 2>/dev/null | awk '{print $3}')" \
  --json "$VERDICT_JSON" \
  "${GATE_ARGS[@]+"${GATE_ARGS[@]}"}"
RC=$?

# ------------------------------------------- INHERITED, BY NAME, NEVER SILENTLY
# The verdict already NOTES pre-existing failures, truncated to five. Five is
# right for a merge summary and wrong here: on the direct-push path this log is
# the only place a permanent red on `main` is ever printed, and silence is
# exactly how a permanent red becomes invisible. Every inherited failure is
# named, in full, on a line a grep can find — PASSING WITH INHERITED REDS IS NOT
# THE SAME EVENT AS PASSING CLEAN, and the log must not read as though it were.
python3 - "$VERDICT_JSON" "$BASE_LAND_LOG" <<'PY'
import json, pathlib, sys
try:
    v = json.loads(pathlib.Path(sys.argv[1]).read_text())
except Exception as exc:                                   # noqa: BLE001
    print(f"  INHERITED  cannot be listed: {exc}")
    raise SystemExit(0)
import re
delta = v.get("delta") or {}
pre = delta.get("preexisting") or []
fixed = delta.get("fixed") or []
land = v.get("land") or {}
base_land = v.get("base_land") or {}
# THE SAME KEY THE JUDGE USES. `landing_merge_verdict.gate_key` strips ONLY a
# trailing ` (<n> file(s))`, because that count is a DISCOVERY number that
# renames the gate whenever a branch adds a file — and a renamed gate reads as
# a repaired one. Deliberately no wider than that: a normaliser that erased
# more would start merging gates that are genuinely different.
_COUNT = re.compile(r"\s*\(\d+\s+file\(s\)\)$")
def key(label):
    return _COUNT.sub("", label)
cand_fail = {key(l): l for l in (land.get("fail") or [])}
base_fail = {key(l): l for l in (base_land.get("blocking_failures") or [])}
inherited_gates = [base_fail[k] for k in base_fail if k in cand_fail]
fixed_gates = [base_fail[k] for k in base_fail if k not in cand_fail]
hyg = v.get("hygiene_finding_delta") or {}
carried = hyg.get("carried") or []
total = len(pre) + len(inherited_gates) + len(carried)
print(f"--- INHERITED FROM THE BASE: {total} item(s). Red on the base, still red "
      f"here, and therefore NOT this push's regression — and NOT FIXED either.")
for k in pre:
    print(f"  INHERITED  test   {k}")
for l in inherited_gates:
    print(f"  INHERITED  gate   {l}")
for f in carried:
    print(f"  INHERITED  hygiene {' / '.join(str(x) for x in f)}")
if total:
    print("  INHERITED  ^^ these are red on the BASE itself. This landing did not")
    print("             cause them and is not excused from them either: they are")
    print("             still red after it lands. A subset-clean pass is NOT a")
    print("             green tree, and this block is the only place that says so.")
if fixed or fixed_gates:
    print(f"--- FIXED BY THIS PUSH: {len(fixed)} test(s), "
          f"{len(fixed_gates)} gate(s) that were red on the base")
    for l in fixed_gates:
        print(f"  FIXED      gate   {l}")
PY

# ----------------------------------------- the hygiene tier when it was absolute
if [ "$HYGIENE_TIER_ABSOLUTE" = "1" ] \
   && grep -q '^  FAIL  repo hygiene gates' "$CAND_LAND_LOG"; then
  echo "  REFUSE  THE HYGIENE TIER FAILED AND COULD NOT BE DIFFERENCED — no"
  echo "          same-host base record exists, so 'the base fails it too' is a"
  echo "          claim nothing here can check. Unknown does not buy leniency."
  [ "$RC" -eq 0 ] && RC=1
fi

# -------------------------- the empty-range invariant, checked rather than assumed
# `gatekeeper-land.sh:202-208` states it: a range-scoped gate that FAILS
# vacuously over `X..X` enters the base's failing set and is excused on every
# candidate thereafter. That is the laundering hole, and it is checked HERE, on
# the real base arm log, every run — not asserted in a comment.
if [ -s "$BASE_LAND_LOG" ]; then
  BAD_RANGE_FAIL="$(grep -E '^  FAIL  (NDA — |version bumped|version monotonic|agent check-in scope|benchmark evidence structure|benchmark run manifest|git prohibition guard|no collateral revert|tree contains the base|landing is one commit|landing is a valid batch)' "$BASE_LAND_LOG" || true)"
  if [ -n "$BAD_RANGE_FAIL" ]; then
    echo "  REFUSE  A RANGE-SCOPED GATE FAILED ON THE EMPTY BASE RANGE. It would"
    echo "          therefore be excused on every candidate forever — including a"
    echo "          real NDA or collateral-revert violation. Fix the gate to SKIP"
    echo "          over X..X before this differential can be trusted:"
    printf '%s\n' "$BAD_RANGE_FAIL" | sed 's/^/          /'
    [ "$RC" -eq 0 ] && RC=1
  fi
fi

STAMP="$("${G[@]}" rev-parse --absolute-git-dir)/gatekeeper-stamp"
if [ "$RC" -eq 0 ] && [ "$NO_STAMP" = "0" ]; then
  # THE STAMP NAMES THE PAIR, NOT ONLY THE COMMIT. A differential verdict is
  # about a (base, candidate) pair: `main` moving between the gate and the push
  # makes the pass describe a tree nobody is about to create — the staleness
  # hole `gatekeeper-verify-merge.sh --reassert` already closes on the merge
  # path. Line 1 stays the commit SHA and nothing else, so an older `pre-push`
  # that reads the whole file still refuses (fail-closed); the reader that
  # understands the extra lines additionally re-checks the base.
  {
    printf '%s\n' "$HEAD_SHA"
    printf 'base=%s\n' "$BASE_SHA"
    printf 'tier=direct-push\n'
    printf 'host=%s\n' "$THIS_HOST"
  } > "$STAMP"
  echo "=== SUBSET-CLEAN AGAINST ${BASE_SHA:0:12} — stamped $("${G[@]}" rev-parse --short HEAD) ==="
  echo "    (subset-clean, NOT green: see the INHERITED lines above)"
else
  rm -f "$STAMP"
  echo "=== REFUSED (rc=$RC) — stamp removed; the pre-push hook will refuse ==="
fi
[ -n "$JSON_OUT" ] || echo "--- verdict record: $VERDICT_JSON (removed with the run dir unless --keep)"
exit "$RC"
