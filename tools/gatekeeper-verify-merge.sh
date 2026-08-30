#!/usr/bin/env bash
# gatekeeper-verify-merge.sh — put the landing gates ON THE PATH THAT LANDS CODE.
#
# WHY THIS FILE EXISTS (vibe-ic#1019)
# ==================================
# `tools/gatekeeper-land.sh` runs the tests and the hygiene gates and stamps
# `.git/gatekeeper-stamp`; `tools/git-hooks/pre-push` refuses a push whose commit
# has no matching stamp. That is the whole enforcement, and it is attached to
# `git push`.
#
#     `gh pr merge --squash` creates the commit SERVER-SIDE. Nothing is pushed
#     from a local clone, so `pre-push` never fires and `gatekeeper-land.sh`
#     never runs.
#
# Merging is not pushing. Measured on 2026-08-12: Actions is disabled at the
# ACCOUNT level (`actions/permissions` -> `{"enabled": false}`), `main` returns
# `404 Branch not protected`, and there are no required status checks. So there
# is no server-side check to fall back on and none can be created — this script
# is the merge-path gate or there is not one.
#
# WHAT IT VERIFIES: THE SQUASH COMMIT, NOT A LOCAL REBASE OF THE BRANCH
# ====================================================================
# `gh pr merge --squash` creates ONE commit whose parent is the base tip and
# whose tree is the forge's merge tree. So that is what gets built and gated:
#
#   1. fetch the PR head (and the forge's own `refs/pull/<n>/merge`, when it has
#      one);
#   2. REBASE that head onto the base in a THROWAWAY WORKTREE — this is the
#      independent second opinion, and a conflict here is a refusal;
#   3. compute the merge tree with `git merge-tree --write-tree` and REFUSE
#      unless the rebase agrees with it AND the forge agrees with both. Replaying
#      the branch's patches and 3-way-merging its text are different questions,
#      and the phantom-revert shape is exactly where they diverge.
#      `--write-tree` NEEDS GIT >= 2.38 and four of six hosts in this fleet run
#      2.34.1, the landing host among them, so the capability is PROBED and the
#      run declares a TIER — see "TWO TIERS" below;
#   4. build the SQUASH commit — `commit-tree <merge tree> -p <base>` with the
#      forge's own default squash message (the PR's commit messages concatenated,
#      so the NDA and prohibition scans read the text that will actually land) —
#      and check it out. The commit-SHAPE gates (`landing_is_one_commit_check`,
#      `landing_collateral_revert_check`, `gatekeeper_stale_branch_check`) then
#      judge the shape that lands instead of an N-commit local branch that does
#      not;
#   5. BEFORE starting either expensive arm, run the BASE-owned cheap gates on
#      the exact commit population that would be pushed. A measured refusal
#      stops here; it is never discovered after the CPU work has finished;
#   6. run the targeted suite on the BASE (arm A) and `gatekeeper-land.sh` on the
#      squash commit (arm B), each with its own junit report — AND hand the
#      verdict the list arm A was ASKED to run (`--base-selection`), so a base
#      arm that did not finish is caught instead of being subtracted as though
#      it had (vibe-ic#1443: a partial base arm hides `silenced`, which is the
#      permissive direction);
#   7. hand every fact to `landing_merge_verdict.py`, which owns the refusal
#      decision, and exit non-zero on REFUSE.
#
# The verified SHA is a local stand-in: the forge will pick its own committer and
# date, so its commit hashes differently. The TREE is the identity that matters
# and it is reported alongside.
#
# TWO TIERS, BECAUSE THE LANDING HOST CANNOT RUN THE STRONG ONE
# ============================================================
# `git merge-tree --write-tree` requires git >= 2.38. Measured across this fleet
# on 2026-08-12: `.112` 2.43.0 and `.114` 2.54.0 have it; `.102` (the
# orchestrator, where every `gh pr merge` is run), `.105`, `.120` and `.121` are
# all 2.34.1 and do not. On those four the tree came back empty and the verdict
# refused every landing with THE MERGE TREE COULD NOT BE COMPUTED — fail-closed
# and correct, and a BAN rather than a check.
#
#   TIER `merge-tree`     git >= 2.38. Unchanged. The tree under test is the
#                         3-way merge; the rebase replay cross-checks it and a
#                         disagreement is a refusal.
#   TIER `rebase-replay`  the fallback. The tree under test is the REBASE
#                         REPLAY. THE SQUASH-VS-REBASE CROSS-CHECK IS NOT
#                         PERFORMED — there is only one answer, so nothing can
#                         disagree with it. The forge's `refs/pull/<n>/merge`
#                         still cross-checks it whenever the forge merged this
#                         same base.
#
# Everything else is identical in both tiers: the same squash commit is built
# from the tree under test, the same `gatekeeper-land.sh` runs on it, the same
# test and gate differentials decide. The fallback is a WEAKER CHECK, NEVER A
# PASS — the paired negative control (an innocuous diff that leaves a test red)
# is asserted UNDER THE FALLBACK, because a fallback that passes everything
# would be worse than a gate that refuses everything.
#
# The loss is disclosed twice, and the machine-readable half is the load-bearing
# one — a downstream reader must be able to tell the tiers apart without parsing
# prose:
#
#   printed   `  DISCLOSE  SQUASH_VS_REBASE_CROSS_CHECK_NOT_PERFORMED`
#   JSON      "verification_tier": "rebase-replay", "tier_degraded": true,
#             "squash_vs_rebase_cross_check": "NOT_PERFORMED",
#             "disclosures": [...], "git_version", "git_version_required_for_merge_tree"
#
# `GATEKEEPER_FORCE_REBASE_REPLAY=1` forces the fallback on a host that has the
# capability. It exists so the fallback branch is TESTED on every host rather
# than only on the hosts that need it, and it can only ever select the weaker,
# disclosed tier — no value of it turns a refusal into a pass.
#
# WHERE EACH HALF COMES FROM, AND WHY
# ===================================
#   the GATES          the CANDIDATE's tree. `gatekeeper-land.sh` resolves every
#                      program from its own repo root, so a tree's gates ship
#                      with it; a PR that adds one is covered by it from the next
#                      landing onward. `--gate-edited` DISCLOSES when the branch
#                      touches the battery judging it, because that is worth
#                      reading and must not be blocking (a PR that improves the
#                      gate has to be landable).
#   the VERDICT        the exact BASE commit's raw-attested copy of
#                      `landing_merge_verdict.py`, rematerialized after the
#                      candidate census is zero; never the candidate's or a
#                      mutable caller worktree's copy. The judge may not be
#                      supplied by the subject — the same rule §4.05 states for
#                      an oracle. A PR can change what its gates check; it
#                      cannot change what counts as a refusal.
#
# WHY ARM A EXISTS: `main` is RED independently of anything in flight
# (`test_ci_harness_timeout_ceiling_check` 3/40, measured at two different tips).
# A gate that demanded a green tree would refuse EVERY landing today, and a gate
# that refuses every landing is a ban that teaches the operator to bypass it. The
# candidate is judged on WHAT IT BREAKS — with `failed -> skipped` counted as a
# refusal, never an improvement. See the program's docstring for the table.
#
# USE IT BEFORE `gh pr merge`, AND LAND ONLY ON A PASS:
#
#     tools/gatekeeper-verify-merge.sh 1021 --json /tmp/v.json   # must exit 0
#     gh pr merge 1021 --squash
#     tools/gatekeeper-verify-merge.sh --reassert /tmp/v.json     # if time passed
#
# If ONLY the commit packaging changed after a complete verdict (same base,
# final tree and canonical path/mode/blob delta), rebind that evidence instead
# of re-running all expensive arms. The actual push population still has to
# pass every cheap BASE-owned gate first:
#
#     tools/gatekeeper-verify-merge.sh --rebind /tmp/old.json \
#       --ref <one-commit-ref> --json /tmp/rebound.json
#
# The verdict is about a BASE. If `origin/main` moves before the merge, the
# verdict is stale — `--reassert` says so rather than letting a stale pass land.
#
# Usage:
#   gatekeeper-verify-merge.sh <pr-number> [options]
#   gatekeeper-verify-merge.sh --ref <ref> [options]
#   gatekeeper-verify-merge.sh --reassert <verdict.json>
#   gatekeeper-verify-merge.sh --rebind <verdict.json> --ref <ref> --json <out>
#
# Options:
#   --base <ref>        base the PR would land on          (default origin/main)
#   --repo <path>       repository to operate on   (default: this script's repo)
#   --json <path>       write the verdict JSON
#   --rebind <path>     identity-only rebind of a complete prior LAND_OK;
#                       requires an exact one-commit BASE parent, unchanged
#                       final tree/delta, fresh protected tuple receipt, and
#                       PASS from every cheap gate on the actual push range
#   --no-fetch          do not touch the network (local refs must already exist)
#   --require-version-bump
#                       demand the version bump in the PR itself. OFF by
#                       default because authoring PRs are VERSION-LESS by
#                       doctrine — the gatekeeper assigns the version AT MERGE —
#                       so demanding it here would refuse every conformant PR.
#                       A BACKWARDS version is refused either way.
#   --keep              keep the run directory and the worktrees for inspection
#   --base-gate-cache <dir>
#                       reuse only NON-PERMISSIVE GREEN A1/A2 evidence, bound to
#                       base, selection, candidate instrument, host/runtime and
#                       execution contract. Red baseline evidence is always
#                       remeasured in this run and can never become a stale
#                       exemption. Busy/unsupported locks are cache misses, not
#                       critical-path waits. Every bundle is terminal-validated.
set -uo pipefail

PR=""; REF=""; BASE="origin/main"; JSON_OUT=""; REASSERT=""; REBIND=""
NO_FETCH=0; KEEP=0; REQUIRE_VERSION_BUMP=0; BASE_GATE_CACHE=""
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO=""

# GIT EXPORTS `GIT_DIR` WHEN A PUSH OR A HOOK ORIGINATES IN A WORKTREE, and
# `git -C <dir>` does NOT override an explicitly-set `GIT_DIR` (vibe-ic#636 —
# the lesson `tools/git-hooks/pre-push` learned by mis-gating every push from a
# worktree). Every git call here is `git -C`, and this script may be handed a
# `--repo` that is not the one the caller's environment names, so the inherited
# value can only ever point at the wrong repository. An EMPTY value is worse
# than a wrong one: git takes it literally and every `rev-parse` fails.
unset GIT_DIR GIT_WORK_TREE
# Replacement objects are mutable repository metadata, not part of the commit
# being verified.  Never let a subject-created refs/replace entry change what
# any parent-side object lookup means.
export GIT_NO_REPLACE_OBJECTS=1

die() { printf 'gatekeeper-verify-merge: %s\n' "$*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --ref)      REF="${2:?}"; shift 2 ;;
    --base)     BASE="${2:?}"; shift 2 ;;
    --repo)     REPO="${2:?}"; shift 2 ;;
    --json)     JSON_OUT="${2:?}"; shift 2 ;;
    --reassert) REASSERT="${2:?}"; shift 2 ;;
    --rebind)   REBIND="${2:?}"; shift 2 ;;
    --no-fetch) NO_FETCH=1; shift ;;
    --keep)     KEEP=1; shift ;;
    --base-gate-cache) BASE_GATE_CACHE="${2:?}"; shift 2 ;;
    --require-version-bump) REQUIRE_VERSION_BUMP=1; shift ;;
    -h|--help)  sed -n '1,149p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*)         die "unknown option $1" ;;
    *)          [ -n "$PR" ] && die "more than one PR number given"
                PR="$1"; shift ;;
  esac
done

# A candidate shares this uid and receives paths under RUN.  Until cache
# bundles are parent-authenticated, reading or writing a mutable baseline cache
# concurrently with that candidate would let it turn introduced failures into
# "pre-existing" ones.  Measure the base after candidate zero-census instead.
if [ -n "$BASE_GATE_CACHE" ]; then
  echo "--- base-gate cache disabled for adversarial differential ownership; base will be remeasured"
  BASE_GATE_CACHE=""
fi

SELF_REPO="$(git -C "$SELF" rev-parse --show-toplevel 2>/dev/null)"
[ -z "$REPO" ] && REPO="$SELF_REPO"
[ -n "$REPO" ] || die "no repository (pass --repo)"
REPO="$(cd "$REPO" && pwd)"
G=(git -C "$REPO")
[ -z "$REASSERT" ] || [ -z "$REBIND" ] \
  || die "--reassert and --rebind are mutually exclusive"

derive_push_range() {
  # Name the exact unpublished range when REF is a local branch.  If the head
  # is already published (or REF is an object id), re-run the cheap gates over
  # the one base->head delta; a packaging rebind is constrained to one commit
  # on BASE, so the two populations are then identical.
  local ref="$1" head="$2" base="$3" branch="" remote="" remote_sha=""
  case "$ref" in
    refs/heads/*) branch="${ref#refs/heads/}" ;;
    *) "${G[@]}" show-ref --verify --quiet "refs/heads/$ref" && branch="$ref" ;;
  esac
  if [ -n "$branch" ]; then
    remote="refs/remotes/origin/$branch"
    remote_sha="$("${G[@]}" rev-parse --verify "$remote" 2>/dev/null || true)"
    if [ -z "$remote_sha" ]; then
      PUSH_RANGE="$head --not --remotes"
      PUSH_RANGE_SOURCE="new remote branch"
    elif [ "$remote_sha" != "$head" ]; then
      PUSH_RANGE="$remote_sha..$head"
      PUSH_RANGE_SOURCE="unpublished commits after $remote"
    else
      PUSH_RANGE="$base..$head"
      PUSH_RANGE_SOURCE="already-published head; identity recheck"
    fi
  else
    PUSH_RANGE="$base..$head"
    PUSH_RANGE_SOURCE="object ref; base-to-head identity recheck"
  fi
}

# ---------------------------------------------------------------- --reassert
# A verdict is about a BASE and a HEAD. Between the verify and the merge, other
# agents land PRs; if either moved, the pass describes a tree nobody is about to
# create. This is the time dimension of "verified the wrong tree", and it is the
# cheap half — no worktree, no tests, just two `rev-parse`s.
if [ -n "$REASSERT" ]; then
  [ -f "$REASSERT" ] || die "--reassert: no such file: $REASSERT"
  read -r WAS_BASE WAS_HEAD WAS_VERDICT < <(python3 - "$REASSERT" <<'PY'
import json, sys
def pairs(rows):
    out = {}
    for key, value in rows:
        if key in out:
            raise ValueError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out
def constant(value):
    raise ValueError(f"non-finite JSON number {value!r}")
with open(sys.argv[1], encoding="utf-8") as fh:
    d = json.load(fh, object_pairs_hook=pairs, parse_constant=constant)
if not isinstance(d, dict):
    raise SystemExit(2)
print(d.get("base_sha", ""), d.get("head_sha", ""), d.get("verdict", ""))
PY
  ) || die "--reassert: $REASSERT is not a verdict JSON"
  [ "$WAS_VERDICT" = "LAND_OK" ] || {
    echo "REASSERT: REFUSE — the recorded verdict is $WAS_VERDICT, not LAND_OK" >&2
    exit 1; }
  [ "$NO_FETCH" = "1" ] || "${G[@]}" fetch -q origin main 2>/dev/null
  NOW_BASE="$("${G[@]}" rev-parse "$BASE" 2>/dev/null)" || die "cannot resolve $BASE"
  if [ "$NOW_BASE" != "$WAS_BASE" ]; then
    echo "REASSERT: REFUSE — the base moved under the verdict" >&2
    echo "    verified against ${WAS_BASE:0:12}   $BASE is now ${NOW_BASE:0:12}" >&2
    echo "    re-run the full verify; a pass about an older base is not a pass" >&2
    exit 1
  fi
  REASSERT_VERIFIER_BLOB="$(git -C "$SELF_REPO" hash-object --no-filters \
    "$SELF/gatekeeper-verify-merge.sh" 2>/dev/null)" \
    || die "--reassert: cannot hash the running verifier"
  REASSERT_BASE_VERIFIER_BLOB="$("${G[@]}" rev-parse \
    "$WAS_BASE:tools/gatekeeper-verify-merge.sh" 2>/dev/null)" \
    || die "--reassert: recorded base has no verifier"
  [ "$REASSERT_VERIFIER_BLOB" = "$REASSERT_BASE_VERIFIER_BLOB" ] \
    || die "--reassert: running verifier is not the recorded BASE authority"
  REASSERT_VALIDATOR="$SELF_REPO/tools/ci/protected_landing_transition.py"
  REASSERT_VALIDATOR_BLOB="$(git -C "$SELF_REPO" hash-object --no-filters \
    "$REASSERT_VALIDATOR" 2>/dev/null)" \
    || die "--reassert: cannot hash the protected transition validator"
  REASSERT_BASE_VALIDATOR_BLOB="$("${G[@]}" rev-parse \
    "$WAS_BASE:tools/ci/protected_landing_transition.py" 2>/dev/null)" \
    || die "--reassert: recorded base has no protected transition validator"
  [ "$REASSERT_VALIDATOR_BLOB" = "$REASSERT_BASE_VALIDATOR_BLOB" ] \
    || die "--reassert: transition validator is not the recorded BASE byte"
  PYTHONDONTWRITEBYTECODE=1 python3 -B "$REASSERT_VALIDATOR" \
      validate-verdict --verdict "$REASSERT" \
      --expected-base "$WAS_BASE" --expected-head "$WAS_HEAD" \
      --object-repo "$REPO" \
    || die "--reassert: protected transition receipt is missing or changed"
  echo "REASSERT: OK — $BASE is still ${WAS_BASE:0:12}, head still ${WAS_HEAD:0:12}"
  exit 0
fi

# --------------------------------------------------------------- --rebind
# A packaging rewrite changes commit ids, not functionality.  Re-running the
# full differential verifier is justified only if the BASE or final tree changed.
# This path proves they did not, re-runs the cheap BASE-owned push gates over
# the actual unpublished range, rebuilds the protected tuple receipt for the
# new one-commit head, and emits a self-contained REBOUND_FROM verdict.
if [ -n "$REBIND" ]; then
  [ -z "$PR" ] || die "--rebind accepts --ref, not a PR number"
  [ -n "$REF" ] || die "--rebind requires --ref <new-head>"
  [ -n "$JSON_OUT" ] || die "--rebind requires --json <rebound-verdict>"
  [ -f "$REBIND" ] || die "--rebind: no such old verdict: $REBIND"
  [ "$NO_FETCH" = "1" ] || "${G[@]}" fetch -q origin main 2>/dev/null
  REBIND_BASE="$("${G[@]}" rev-parse "$BASE" 2>/dev/null)" \
    || die "--rebind: cannot resolve $BASE"
  REBIND_HEAD="$("${G[@]}" rev-parse "$REF" 2>/dev/null)" \
    || die "--rebind: cannot resolve $REF"
  REBIND_VERIFIER_BLOB="$(git -C "$SELF_REPO" hash-object --no-filters \
    "$SELF/gatekeeper-verify-merge.sh" 2>/dev/null)" \
    || die "--rebind: cannot hash the running verifier"
  REBIND_BASE_VERIFIER_BLOB="$("${G[@]}" rev-parse \
    "$REBIND_BASE:tools/gatekeeper-verify-merge.sh" 2>/dev/null)" \
    || die "--rebind: base has no merge verifier"
  [ "$REBIND_VERIFIER_BLOB" = "$REBIND_BASE_VERIFIER_BLOB" ] \
    || die "--rebind: running verifier is not the exact BASE authority"
  REBIND_VALIDATOR="$SELF_REPO/tools/ci/protected_landing_transition.py"
  REBIND_VALIDATOR_BLOB="$(git -C "$SELF_REPO" hash-object --no-filters \
    "$REBIND_VALIDATOR" 2>/dev/null)" \
    || die "--rebind: cannot hash the transition validator"
  REBIND_BASE_VALIDATOR_BLOB="$("${G[@]}" rev-parse \
    "$REBIND_BASE:tools/ci/protected_landing_transition.py" 2>/dev/null)" \
    || die "--rebind: base has no transition validator"
  [ "$REBIND_VALIDATOR_BLOB" = "$REBIND_BASE_VALIDATOR_BLOB" ] \
    || die "--rebind: transition validator is not the exact BASE byte"

  REBIND_RUN="$(mktemp -d -t gkrebind.XXXXXX)"
  REBIND_GATES="$REBIND_RUN/candidate-gates"
  REBIND_TESTS="$REBIND_RUN/candidate-tests"
  REBIND_PREFLIGHT="$REBIND_RUN/push-preflight.json"
  REBIND_PROTECTED="$REBIND_RUN/protected-transition.json"
  rebind_cleanup() {
    "${G[@]}" worktree remove --force "$REBIND_GATES" >/dev/null 2>&1 || true
    "${G[@]}" worktree remove --force "$REBIND_TESTS" >/dev/null 2>&1 || true
    rm -rf "$REBIND_RUN"
  }
  rebind_signal_exit() {
    local rc="$1"
    trap - INT TERM
    exit "$rc"
  }
  trap rebind_cleanup EXIT
  trap 'rebind_signal_exit 130' INT
  trap 'rebind_signal_exit 143' TERM
  derive_push_range "$REF" "$REBIND_HEAD" "$REBIND_BASE"
  echo "=== landing verdict packaging rebind ==="
  echo "--- base=${REBIND_BASE:0:12} head=${REBIND_HEAD:0:12}"
  echo "--- push-range=$PUSH_RANGE ($PUSH_RANGE_SOURCE)"
  PYTHONDONTWRITEBYTECODE=1 python3 -B "$REBIND_VALIDATOR" push-preflight \
      --object-repo "$REPO" --base "$REBIND_BASE" \
      --candidate "$REBIND_HEAD" --push-range "$PUSH_RANGE" \
      --receipt "$REBIND_PREFLIGHT"
  REBIND_PREFLIGHT_RC=$?
  if [ "$REBIND_PREFLIGHT_RC" -ne 0 ]; then
    [ ! -f "$REBIND_PREFLIGHT" ] || cp "$REBIND_PREFLIGHT" "$JSON_OUT"
    exit "$REBIND_PREFLIGHT_RC"
  fi
  "${G[@]}" worktree add -q --detach "$REBIND_GATES" "$REBIND_HEAD" \
    || die "--rebind: cannot create candidate-gates worktree"
  "${G[@]}" worktree add -q --detach "$REBIND_TESTS" "$REBIND_HEAD" \
    || die "--rebind: cannot create candidate-tests worktree"
  PYTHONDONTWRITEBYTECODE=1 python3 -B "$REBIND_VALIDATOR" verify \
      --object-repo "$REPO" --base "$REBIND_BASE" \
      --candidate "$REBIND_HEAD" --candidate-gates "$REBIND_GATES" \
      --candidate-tests "$REBIND_TESTS" --receipt "$REBIND_PROTECTED" \
    || die "--rebind: protected tuple could not be re-attested"
  PYTHONDONTWRITEBYTECODE=1 python3 -B "$REBIND_VALIDATOR" rebind-verdict \
      --object-repo "$REPO" --base "$REBIND_BASE" \
      --candidate "$REBIND_HEAD" --old-verdict "$REBIND" \
      --push-preflight "$REBIND_PREFLIGHT" \
      --protected-transition "$REBIND_PROTECTED" --receipt "$JSON_OUT"
  exit $?
fi

[ -n "$PR" ] || [ -n "$REF" ] || die "give a PR number or --ref <ref>"
[ -n "$PR" ] && [ -n "$REF" ] && die "give a PR number OR --ref, not both"

LAND="$REPO/tools/gatekeeper-land.sh"
[ -x "$LAND" ] || [ -f "$LAND" ] || die "no landing script at $LAND"

RUN="$(mktemp -d -t gkverify.XXXXXX)"
WT_CAND="$RUN/candidate"
WT_CAND_TESTS="$RUN/candidate-tests"
WT_BASE="$RUN/base"
WT_BASE_TESTS="$RUN/base-tests"
WT_TRUSTED="$RUN/trusted-base-tools"
TRUSTED_REPO=""
BENCHMARK_MEASUREMENT="$RUN/benchmark-data-measurement.json"
BENCHMARK_MEASUREMENT_SHA256=""
BENCHMARK_SOURCE=""
BENCHMARK_SHA=""
BENCHMARK_A2="$RUN/benchmark-a2"
BENCHMARK_B2="$RUN/benchmark-b2"
BENCHMARK_A2_ADDED=0
BENCHMARK_B2_ADDED=0
BENCHMARK_POST_FAILURE=0
TRUSTED_TRANSITION_EVIDENCE="$RUN/trusted-routed-transition-evidence.json"
PROTECTED_PRE="$RUN/protected-landing-transition.pre.json"
PROTECTED_POST="$RUN/protected-landing-transition.post.json"
PROTECTED_PRE_SHA256=""
PROTECTED_ARGS=()
PROTECTED_OPERATION=""
RUNTIME_AUTHORITY_COMMIT=""
RUNTIME_SNAPSHOT="$RUN/protected-runtime"
RUNTIME_RECORD="$RUN/protected-runtime.json"
CAND_SUBJECT="$RUN/candidate-subject"
BASE_SUBJECT="$RUN/base-subject"
CAND_SUBJECT_RECORD="$RUN/candidate-subject.json"
BASE_SUBJECT_RECORD="$RUN/base-subject.json"
BENCHMARK_SUBJECT_RECORD="$RUN/benchmark-subject.json"
SELECTION_MANIFEST="$RUN/test-selection.json"
A1_PROGRESS_PLAN="$RUN/a1-progress-plan.json"
B1_PROGRESS_PLAN="$RUN/b1-progress-plan.json"
A2_PROGRESS_PLAN="$RUN/a2-progress-plan.json"
B2_PROGRESS_PLAN="$RUN/b2-progress-plan.json"
A1_OUTPUT="$RUN/a1-evidence"
B1_OUTPUT="$RUN/b1-evidence"
A2_OUTPUT="$RUN/a2-evidence"
B2_OUTPUT="$RUN/b2-evidence"
A1_RECEIPT="$RUN/a1-hermetic-receipt.json"
B1_RECEIPT="$RUN/b1-hermetic-receipt.json"
A2_RECEIPT="$RUN/a2-hermetic-receipt.json"
B2_RECEIPT="$RUN/b2-hermetic-receipt.json"
A1_VALIDATION="$RUN/a1-arm-validation.json"
B1_VALIDATION="$RUN/b1-arm-validation.json"
A2_VALIDATION="$RUN/a2-arm-validation.json"
B2_VALIDATION="$RUN/b2-arm-validation.json"
# BASE-owned, immutable semantic leases.  Exact 779-file collection completed
# healthily in 316.93 s, after the old 300 s lease, so pytest receives 600 s.
# The enclosing test-arm lease starts earlier and is deliberately 30 s longer:
# ordinary inner shutdown policy is 2 s TERM + 1 s KILL confirmation, followed
# by terminal publication.  A pathological uninterruptible child may still
# exhaust the outer lease and remains NORECORD.
# A2/B2 skip the duplicate targeted pytest, but they do NOT have a 300-second
# checkpoint contract.  The concurrent landing window deliberately joins every
# lane and performs write attribution before publishing its first unit, and the
# later gatekeeper review has its own 1800-second no-verdict budget.  PR #1920
# measured the old outer lease expiring at 15/25 while those inner instruments
# were still running normally.  Give the landing arm the longest inner semantic
# budget plus the same 30-second publication margin.  This is still a SILENCE
# lease, never a PASS inferred from elapsed time: expiry remains NORECORD.
TEST_ARM_SEMANTIC_STALL_GRACE=630
LANDING_ARM_SEMANTIC_STALL_GRACE=1830
# PER-RUN ref names. Two verifications of two different PRs may legitimately be
# in flight at once (the merge queue is serialized; a gatekeeper reading ahead is
# not), and a fixed `refs/gk-verify/head` would have had each run fetching over
# the other's head. The run directory's basename is already unique.
RUN_ID="$(basename "$RUN")"
HEAD_REF="refs/gk-verify/$RUN_ID/head"
MERGE_REF="refs/gk-verify/$RUN_ID/merge"

benchmark_origin_args() {
  BENCHMARK_ORIGIN_ARGS=()
  if [ "${VIBEIC_BENCHMARK_CHECKOUT_TEST_OVERRIDE:-0}" = "1" ] \
     && [ -n "${VIBEIC_BENCHMARK_CHECKOUT_TEST_ORIGIN:-}" ]; then
    BENCHMARK_ORIGIN_ARGS=(--test-expected-origin \
      "$VIBEIC_BENCHMARK_CHECKOUT_TEST_ORIGIN")
  fi
}

validate_benchmark_snapshot() {
  local checkout="$1"
  run_owned_operational "$TRUSTED_REPO" \
    python3 "$TRUSTED_REPO/tools/ci/benchmark_data_landing_checkout.py" validate \
    --checkout "$checkout" --expected-sha "$BENCHMARK_SHA" \
    "${BENCHMARK_ORIGIN_ARGS[@]}"
}

run_owned_operational() {
  local cwd="$1"; shift
  PYTHONDONTWRITEBYTECODE=1 python3 -B \
    "$TRUSTED_REPO/tools/ci/owned_command.py" \
    --repo "$TRUSTED_REPO" --cwd "$cwd" --stall-grace \
    "${GATEKEEPER_OPERATIONAL_STALL_GRACE:-300}" -- "$@"
}

validate_protected_landing_transition() {
  local receipt="$1"
  run_owned_operational "$TRUSTED_REPO" \
    python3 "$TRUSTED_REPO/tools/ci/protected_landing_transition.py" verify \
      --object-repo "$REPO" --base "$BASE_SHA" \
      --candidate "$VERIFIED_SHA" \
      --candidate-gates "$WT_CAND" \
      --candidate-tests "$WT_CAND_TESTS" \
      --receipt "$receipt"
}

materialize_protected_runtime() {
  local selected runtime_root runtime_state
  selected="$(PYTHONDONTWRITEBYTECODE=1 python3 -B \
    "$TRUSTED_REPO/tools/ci/protected_landing_transition.py" select-runtime \
      --receipt "$PROTECTED_PRE" \
      --expected-base "$BASE_SHA" --expected-candidate "$VERIFIED_SHA" \
      --expected-base-tree "$BASE_TREE" \
      --expected-candidate-tree "$VERIFIED_TREE" \
      --require-semantic-runtime)" \
    || die "BASE-predeclared semantic landing runtime is not active"
  IFS=$'\t' read -r runtime_root runtime_state <<< "$selected"
  case "$runtime_root" in
    candidate) RUNTIME_AUTHORITY_COMMIT="$VERIFIED_SHA" ;;
    base) RUNTIME_AUTHORITY_COMMIT="$BASE_SHA" ;;
    *) die "protected transition selected no executable runtime root" ;;
  esac
  echo "--- protected runtime=$runtime_root/$runtime_state"
  run_owned_operational "$TRUSTED_REPO" \
    python3 "$TRUSTED_REPO/tools/ci/protected_runtime_snapshot.py" \
      materialize --object-repo "$REPO" --receipt "$PROTECTED_PRE" \
      --base-snapshot "$TRUSTED_REPO" --snapshot "$RUNTIME_SNAPSHOT" \
      --record "$RUNTIME_RECORD" \
    || die "cannot materialize the one BASE-authorised landing runtime"
}

materialize_hermetic_git_subject() {
  local object_repo="$1" commit="$2" output="$3" record="$4"
  run_owned_operational "$RUNTIME_SNAPSHOT" \
    python3 -B "$RUNTIME_SNAPSHOT/tools/ci/hermetic_git_subject.py" \
      --object-repo "$object_repo" --commit "$commit" \
      --output "$output" --record "$record" \
    || die "cannot materialize object-exact hermetic Git subject ${commit:0:12}"
}

build_trusted_test_selection() {
  run_owned_operational "$RUNTIME_SNAPSHOT" \
    python3 "$RUNTIME_SNAPSHOT/tools/ci/trusted_test_selection.py" \
      --object-repo "$REPO" --base "$BASE_SHA" --candidate "$VERIFIED_SHA" \
      --selector-commit "$RUNTIME_AUTHORITY_COMMIT" \
      --selector-path "$RUNTIME_SNAPSHOT/$PLUGIN_REL/programs/ci_targeted_test_select.py" \
      --base-snapshot "$TRUSTED_REPO" \
      --candidate-snapshot "$WT_CAND" \
      --manifest "$SELECTION_MANIFEST" \
      --base-selection "$RUN/selection_base.txt" \
      --candidate-selection "$RUN/selection.txt" \
      --base-progress-plan "$A1_PROGRESS_PLAN" \
      --candidate-progress-plan "$B1_PROGRESS_PLAN" \
      --stall-grace-seconds "$TEST_ARM_SEMANTIC_STALL_GRACE" \
    || die "BASE-owned targeted selection/finite progress plan is NORECORD"
  python3 "$RUNTIME_SNAPSHOT/tools/ci/landing_completion_record.py" plan \
      --scope landing:A2 \
      --stall-grace-seconds "$LANDING_ARM_SEMANTIC_STALL_GRACE" \
      --output "$A2_PROGRESS_PLAN" \
    || die "cannot build the A2 parent-owned progress plan"
  python3 "$RUNTIME_SNAPSHOT/tools/ci/landing_completion_record.py" plan \
      --scope landing:B2 \
      --stall-grace-seconds "$LANDING_ARM_SEMANTIC_STALL_GRACE" \
      --output "$B2_PROGRESS_PLAN" \
    || die "cannot build the B2 parent-owned progress plan"
}

new_progress_nonce() {
  PYTHONDONTWRITEBYTECODE=1 python3 -I -B -c \
    'import secrets; print(secrets.token_hex(32))'
}

validated_arm_exit() {
  # `-B` IS LOAD-BEARING, and `PYTHONDONTWRITEBYTECODE=1` alone is not: `-I`
  # implies `-E`, so it IGNORES every PYTHON* variable including that one.  The
  # helper below imports the arm-receipt module OUT OF `$RUNTIME_SNAPSHOT`, so
  # without `-B` the first call byte-compiles it and leaves
  # `tools/ci/__pycache__/` inside the runtime tree.  The runtime tree digest is
  # exactly what every LATER arm's receipt is re-checked against, so the B1 call
  # made the very next validation refuse with "receipt runtime digest differs
  # from the current input" -> "B2 arm receipt is NORECORD", on every run, for
  # every branch.  Measured: runtime files 57 -> 58 across one B1 validation.
  PYTHONDONTWRITEBYTECODE=1 python3 -I -B - "$1" "$2" <<'PY'
import importlib.util, pathlib, sys
helper_path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("_trusted_arm_record_exit", helper_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
record = module.strict_load_record(pathlib.Path(sys.argv[2]))
print(record["payload"]["result_exit_code"])
PY
}

# WHY THE VALIDATOR'S OWN LOG IS NOT ENOUGH.
#
# When the arm never wrote a receipt, the validator can only report the SYMPTOM
# -- "cannot resolve runner receipt: [Errno 2] No such file or directory" -- and
# that one line is what a reader sees for every distinct cause. MEASURED, three
# different causes reduced to that same sentence in one evening:
#
#   * "subject would expose the host HOME to the candidate"  (TMPDIR under $HOME)
#   * "cannot start Docker CLI: ..."                          (no engine here)
#   * "candidate ended without the exact semantic terminal record"
#
# The runner writes its refusal to `$RUN/<arm>-runner.log` and then exits; that
# file is deleted with the run directory, so unless it is quoted HERE the cause
# is gone. "I could not run it" and "I ran it and it failed" must not read the
# same. The launchers above own that pathname, so it is derived from the arm id
# rather than threaded through this function's already-long parameter list.
arm_norecord_diagnosis() {
  local arm="$1" record_log="$2" runner_log
  runner_log="$RUN/$(printf '%s' "$arm" | tr 'A-Z' 'a-z')-runner.log"
  if [ -s "$runner_log" ]; then
    echo "      --- $arm runner said (this is the CAUSE; the lines below are the symptom):" >&2
    tail -n 20 -- "$runner_log" | sed 's/^/      /' >&2
  else
    echo "      --- $arm runner left no log at $runner_log — the arm did not even start" >&2
  fi
  sed 's/^/      /' "$record_log" >&2
}

validate_hermetic_arm_record() {
  local runner_rc="$1" receipt="$2" output="$3" arm="$4" subject="$5"
  local corpus="$6" selection="$7" plan="$8" command="$9" record="${10}"
  local completion="${11:-}" expected_head="${12:-}" receipt_rc
  local helper="$RUNTIME_SNAPSHOT/tools/ci/hermetic_landing_arm_receipt.py"
  local args=(validate --runner
    "$RUNTIME_SNAPSHOT/tools/ci/hermetic_candidate_runner.py"
    --receipt "$receipt" --output-dir "$output" --arm "$arm"
    --subject "$subject" --runtime "$RUNTIME_SNAPSHOT" --corpus "$corpus"
    --selection "$selection" --progress-plan "$plan"
    --benchmark-sha "$BENCHMARK_SHA" --command "$command" --record "$record")
  if [ -n "$completion" ]; then
    args+=(--completion "$completion" --base "$BASE_SHA"
           --head "$expected_head" --hygiene hygiene.json)
  fi
  python3 -B "$helper" "${args[@]}" >"$record.log" 2>&1 \
    || { arm_norecord_diagnosis "$arm" "$record.log"
         die "$arm arm receipt is NORECORD"; }
  receipt_rc="$(validated_arm_exit "$helper" "$record")" \
    || die "$arm validation record cannot be re-read"
  case "$runner_rc:$receipt_rc" in
    0:0|1:1) ;;
    *) die "$arm runner rc=$runner_rc disagrees with natural subject rc=$receipt_rc" ;;
  esac
  LAST_ARM_RC="$receipt_rc"
}

publish_validated_arm_artifact() {
  python3 -B "$RUNTIME_SNAPSHOT/tools/ci/hermetic_landing_arm_receipt.py" \
    publish --record "$1" --output-dir "$2" \
    --artifact "$3" --destination "$4"
}

launch_hermetic_test_arm() {
  local arm="$1" subject="$2" corpus="$3" selection="$4" plan="$5"
  local output="$6" receipt="$7" log="$8" nonce
  nonce="$(new_progress_nonce)" || die "cannot create $arm progress nonce"
  setsid python3 -B "$RUNTIME_SNAPSHOT/tools/ci/hermetic_candidate_runner.py" run \
    --subject "$subject" --runtime "$RUNTIME_SNAPSHOT" \
    --overlay tools/ci/hermetic_test_arm_entry.sh \
    --overlay vibe-ic-marketplace/plugins/vibe-ic/programs/matrix_mutation_ledger.py \
    --overlay vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_census_freshness.py \
    --overlay vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_coverage.py \
    --overlay vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_artefact_mutation_channel.py \
    --overlay vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_mutation_ledger.py \
    --env "GATEKEEPER_BENCHMARK_DATA_SHA=$BENCHMARK_SHA" \
    --env "GATEKEEPER_VERIFY_ARM=$arm" \
    --env VIBEIC_PYTEST_PROGRESS_FILE=/evidence/pytest-progress.jsonl \
    --env "VIBEIC_PYTEST_PROGRESS_NONCE=$nonce" \
    --corpus "$corpus" --selection "$selection" --progress-plan "$plan" \
    --output-dir "$output" --receipt "$receipt" -- \
    /subject/tools/ci/hermetic_test_arm_entry.sh >"$log" 2>&1 &
  LAST_ARM_PID=$!
}

launch_hermetic_land_arm() {
  local arm="$1" subject="$2" corpus="$3" selection="$4" plan="$5"
  local output="$6" receipt="$7" log="$8" version_by_gatekeeper="$9" nonce
  nonce="$(new_progress_nonce)" || die "cannot create $arm progress nonce"
  setsid python3 -B "$RUNTIME_SNAPSHOT/tools/ci/hermetic_candidate_runner.py" run \
    --subject "$subject" --runtime "$RUNTIME_SNAPSHOT" \
    --overlay tools/gatekeeper-land.sh \
    --env "GATEKEEPER_BASE=$BASE_SHA" \
    --env "GATEKEEPER_BENCHMARK_DATA_SHA=$BENCHMARK_SHA" \
    --env GATEKEEPER_HYGIENE_PROGRESS=/evidence/hygiene-progress.jsonl \
    --env GATEKEEPER_HYGIENE_REPORT=/evidence/hygiene.json \
    --env "GATEKEEPER_VERIFY_ARM=$arm" \
    --env "GATEKEEPER_VERSION_BY_GATEKEEPER=$version_by_gatekeeper" \
    --env "VIBEIC_LANDING_PROGRESS_NONCE=$nonce" \
    --corpus "$corpus" --selection "$selection" --progress-plan "$plan" \
    --output-dir "$output" --receipt "$receipt" -- \
    /subject/tools/gatekeeper-land.sh >"$log" 2>&1 &
  LAST_ARM_PID=$!
}

validate_hermetic_arm_result() {
  local runner_rc="$1" receipt="$2" output="$3" arm="$4" subject="$5"
  local corpus="$6" selection="$7" plan="$8" command="$9"
  local receipt_rc
  receipt_rc="$(hermetic_receipt_exit \
    "$receipt" "$output" "$arm" "$subject" "$corpus" "$selection" \
    "$plan" "$BENCHMARK_SHA" "$command")" \
    || die "$arm did not publish a complete, input-bound hermetic receipt"
  case "$runner_rc:$receipt_rc" in
    0:0|1:1) ;;
    *) die "$arm runner rc=$runner_rc disagrees with natural subject rc=$receipt_rc" ;;
  esac
  LAST_ARM_RC="$receipt_rc"
}

compare_hermetic_shared_inputs() {
  PYTHONDONTWRITEBYTECODE=1 python3 -B - \
      "$RUNTIME_SNAPSHOT" "$@" <<'PY'
import importlib.util, pathlib, sys
runtime = pathlib.Path(sys.argv[1])
path = runtime / "tools" / "ci" / "hermetic_candidate_runner.py"
spec = importlib.util.spec_from_file_location("_trusted_shared_inputs", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
records = [module.strict_load_receipt(pathlib.Path(value))
           for value in sys.argv[2:]]
for key in ("runtime", "corpus"):
    values = [record["inputs"][key] for record in records]
    if not values or any(value != values[0] for value in values[1:]):
        raise SystemExit(2)
images = [record["image"] for record in records]
if any(value != images[0] for value in images[1:]):
    raise SystemExit(2)
PY
}

refresh_and_attest_trusted_tools() {
  # Untrusted arms know RUN and share this uid.  Natural wrapper exit plus the
  # owned final census proves they have no surviving writer; only then discard
  # the old tool worktree, rematerialize BASE, and byte-attest every tracked
  # blob plus index/untracked/ignored/config state before parent evidence/judge.
  local bootstrap="$RUN/trusted-worktree-attest.py" bootstrap_part
  local expected_blob actual_blob
  bootstrap_part="$bootstrap.part.$$"
  expected_blob="$("${G[@]}" rev-parse \
    "$BASE_SHA:tools/ci/trusted_worktree_attest.py" 2>/dev/null)" \
    || die "base has no trusted snapshot attester"
  GIT_NO_REPLACE_OBJECTS=1 "${G[@]}" cat-file blob \
    "$BASE_SHA:tools/ci/trusted_worktree_attest.py" > "$bootstrap_part" \
    || die "cannot extract the exact base snapshot attester blob"
  actual_blob="$("${G[@]}" hash-object --no-filters "$bootstrap_part")" \
    || die "cannot hash the extracted snapshot attester"
  [ "$actual_blob" = "$expected_blob" ] \
    || die "extracted snapshot attester differs from its base blob"
  mv -f -- "$bootstrap_part" "$bootstrap"
  chmod 0500 "$bootstrap"
  case "$WT_TRUSTED" in "$RUN"/*) ;; *) die "unsafe trusted snapshot path" ;; esac
  rm -rf -- "$WT_TRUSTED"
  mkdir -m 0700 -- "$WT_TRUSTED"
  # git-archive cannot invoke checkout clean/smudge filters.  export-subst or
  # any other byte transformation is still caught by the raw blob census below
  # before one byte from this snapshot executes.
  GIT_NO_REPLACE_OBJECTS=1 "${G[@]}" archive --format=tar "$BASE_SHA" \
    | tar -xf - -C "$WT_TRUSTED" \
    || die "cannot materialize the exact trusted base snapshot"
  TRUSTED_REPO="$WT_TRUSTED"
  PYTHONDONTWRITEBYTECODE=1 python3 -B "$bootstrap" \
      --object-repo "$REPO" --snapshot "$TRUSTED_REPO" \
      --expected-sha "$BASE_SHA" \
    || die "trusted base snapshot failed raw-byte attestation"
}

hygiene_record_binds_benchmark() {
  PYTHONDONTWRITEBYTECODE=1 python3 -B - "$TRUSTED_REPO" "$1" "$2" <<'PY'
import pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]) / "vibe-ic-marketplace" /
                       "plugins" / "vibe-ic" / "programs"))
from gate_process_attestation import strict_loads
try:
    d = strict_loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
sha = (d.get("corpus_inputs") or {}).get("benchmark_data_sha")
if sha != sys.argv[3] or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha or ""):
    raise SystemExit(1)
PY
}

prepare_benchmark_snapshots() {
  local configured
  if [ -n "${VIBE_IC_BENCHMARK_DATA:-}" ]; then
    configured="$VIBE_IC_BENCHMARK_DATA"
  elif [ -n "${VIBEIC_BENCHMARK_DATA_CHECKOUT:-}" ]; then
    configured="$VIBEIC_BENCHMARK_DATA_CHECKOUT"
  elif [ -n "${HOME:-}" ]; then
    configured="$HOME/_matrix_benchmark_data"
  else
    die "benchmark-data: no explicit checkout and HOME is unset"
  fi
  benchmark_origin_args
  run_owned_operational "$TRUSTED_REPO" \
    python3 "$TRUSTED_REPO/tools/ci/benchmark_data_landing_checkout.py" measure \
    --checkout "$configured" --record "$BENCHMARK_MEASUREMENT" \
    "${BENCHMARK_ORIGIN_ARGS[@]}" \
    || die "benchmark-data canonical checkout produced NORECORD"
  BENCHMARK_SHA="$(PYTHONDONTWRITEBYTECODE=1 python3 -B - \
      "$TRUSTED_REPO" "$BENCHMARK_MEASUREMENT" "$configured" <<'PY'
import pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]) / "vibe-ic-marketplace" /
                       "plugins" / "vibe-ic" / "programs"))
from gate_process_attestation import strict_loads
d = strict_loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
if set(d) != {"schema", "complete", "sha", "origin", "path"}:
    raise SystemExit(2)
if d["schema"] != 1 or d["complete"] is not True:
    raise SystemExit(2)
if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", d.get("sha", "")):
    raise SystemExit(2)
if pathlib.Path(d["path"]).resolve() != pathlib.Path(sys.argv[3]).resolve():
    raise SystemExit(2)
print(d["sha"])
PY
  )" || die "benchmark-data measurement record is incomplete"
  BENCHMARK_SOURCE="$(PYTHONDONTWRITEBYTECODE=1 python3 -B - \
      "$TRUSTED_REPO" "$BENCHMARK_MEASUREMENT" <<'PY'
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]) / "vibe-ic-marketplace" /
                       "plugins" / "vibe-ic" / "programs"))
from gate_process_attestation import strict_loads
print(strict_loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))["path"])
PY
  )" || die "benchmark-data measurement path is unreadable"
  BENCHMARK_MEASUREMENT_SHA256="$(sha256sum "$BENCHMARK_MEASUREMENT" \
    | awk '{print $1}')" \
    || die "cannot bind the benchmark-data measurement record"

  echo "--- benchmark-data=${BENCHMARK_SHA:0:12} (one remote measurement; hermetic snapshot pending)"
}

prepare_base_wave() {
  run_owned_operational "$REPO" \
    git -C "$REPO" worktree add -q --detach "$WT_BASE_TESTS" "$BASE_SHA" \
    || die "cannot create the post-candidate base-test worktree"
  run_owned_operational "$REPO" \
    git -C "$REPO" worktree add -q --detach "$WT_BASE" "$BASE_SHA" \
    || die "cannot create the post-candidate base-gate worktree"
  raw_attest_base_worktree "$WT_BASE_TESTS" \
    || die "post-candidate base-test worktree failed raw-byte attestation"
  raw_attest_base_worktree "$WT_BASE" \
    || die "post-candidate base-gate worktree failed raw-byte attestation"
}

raw_attest_base_worktree() {
  local checkout="$1"
  PYTHONDONTWRITEBYTECODE=1 python3 -B \
    "$TRUSTED_REPO/tools/ci/trusted_worktree_attest.py" \
      --object-repo "$REPO" --snapshot "$checkout" \
      --expected-sha "$BASE_SHA" --allow-git-control-file
}

clear_base_wave_artifacts() {
  # These names are discoverable from the measurement-record path handed to
  # B2.  Once both candidate process groups have a terminal zero census, delete
  # every A-only artifact (including candidate-planted symlinks/directories)
  # before a base process or cache reader can treat it as carried evidence.
  local path
  for path in \
      "$BASE_JUNIT" "$BASE_HYG" "$RUN/base_land.log" \
      "$RUN/base_tests.log" "$RUN/base_hygiene_progress.jsonl" \
      "$RUN/selection_base.txt" "$RUN/selection_base.after"; do
    case "$path" in "$RUN"/*) ;; *) die "unsafe base artifact path: $path" ;; esac
    rm -rf -- "$path"
  done
}

seal_bound_file() {
  # Re-home bytes from a pre-candidate parent artifact onto a fresh private
  # inode.  A matching symlink/hardlink is not accepted merely because its
  # target happens to hash correctly at this instant.
  local path="$1" expected_sha="$2"
  PYTHONDONTWRITEBYTECODE=1 python3 -B - "$path" "$expected_sha" <<'PY'
import hashlib
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = sys.argv[2]
before = path.lstat()
if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
    raise SystemExit(2)
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
flags |= getattr(os, "O_NOFOLLOW", 0)
fd = os.open(path, flags)
try:
    chunks = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    after_fd = os.fstat(fd)
finally:
    os.close(fd)
identity = lambda st: (st.st_dev, st.st_ino, st.st_size,
                       st.st_mtime_ns, st.st_ctime_ns)
if identity(before) != identity(after_fd):
    raise SystemExit(2)
data = b"".join(chunks)
if hashlib.sha256(data).hexdigest() != expected:
    raise SystemExit(2)
tmp = path.with_name(f".{path.name}.sealed.{os.getpid()}")
wflags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
out = os.open(tmp, wflags, 0o600)
try:
    view = memoryview(data)
    while view:
        written = os.write(out, view)
        if written <= 0:
            raise OSError("short selection write")
        view = view[written:]
    os.fsync(out)
finally:
    os.close(out)
os.replace(tmp, path)
sealed = path.lstat()
if (not stat.S_ISREG(sealed.st_mode) or sealed.st_nlink != 1
        or stat.S_IMODE(sealed.st_mode) != 0o600):
    raise SystemExit(2)
PY
}

reattest_corpus_snapshot_against_arm_receipt() {
  # $BENCHMARK_B2 is not a benchmark-data CHECKOUT. It is built by
  # materialize_hermetic_git_subject -- `git init` over an object-exact tree --
  # so it has no `origin` remote and benchmark_data_landing_checkout.py can
  # only ever answer "origin must be exactly ...; observed ['<missing or
  # unreadable>']". Re-attest it as what it IS: its tree digest must still
  # equal the one the arm receipt already bound, which is the same digest
  # compare_hermetic_shared_inputs reads. Measured: a mutated byte and an added
  # file both change it; a perfect restore does not, which is also true of the
  # checkout validator this replaces.
  PYTHONDONTWRITEBYTECODE=1 python3 -B - "$RUNTIME_SNAPSHOT" "$1" "$2" <<'PY'
import importlib.util, pathlib, sys
runtime = pathlib.Path(sys.argv[1])
path = runtime / "tools" / "ci" / "hermetic_candidate_runner.py"
spec = importlib.util.spec_from_file_location("_trusted_corpus_reattest", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
record = module.strict_load_receipt(pathlib.Path(sys.argv[3]))
observed = module._tree_digest(pathlib.Path(sys.argv[2]), "corpus")
raise SystemExit(0 if observed == record["inputs"]["corpus"] else 2)
PY
}

build_trusted_transition_evidence() {
  rm -f "$TRUSTED_TRANSITION_EVIDENCE"
  run_owned_operational "$TRUSTED_REPO" \
    python3 "$TRUSTED_REPO/tools/ci/routed_def_corpus.py" \
      --repo "$TRUSTED_REPO" \
      --trusted-manifest "$TRUSTED_TRANSITION_EVIDENCE" \
      --checkout "$BENCHMARK_B2" --subject-repo "$WT_CAND" \
      --benchmark-sha "$BENCHMARK_SHA" \
    || die "trusted parent could not enumerate and execute the routed corpus"
  [ -s "$TRUSTED_TRANSITION_EVIDENCE" ] \
    || die "trusted routed transition evidence was not published"
  # The independent receipts read B2 after its pre-arm validation.  Re-attest
  # those exact bytes now so a mutation during parent execution cannot be
  # cleaned up and laundered into the evidence file.
  reattest_corpus_snapshot_against_arm_receipt "$BENCHMARK_B2" "$B2_RECEIPT" \
    || die "benchmark-data B2 changed during trusted parent evidence execution"
}

base_has_exact_legacy_routed_empty() {
  python3 - "$TRUSTED_REPO" "$1" "$BENCHMARK_SHA" <<'PY'
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]) / "vibe-ic-marketplace" /
                       "plugins" / "vibe-ic" / "programs"))
from gate_process_attestation import strict_loads

try:
    doc = strict_loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
except (OSError, ValueError, TypeError):
    raise SystemExit(1)
name = "published cells carrying a routed DEF"
label = f'corpus "{name}" is EMPTY — nothing was checked over it'
corpora = [c for c in doc.get("corpora", [])
           if isinstance(c, dict) and c.get("name") == name]
gates = [g for g in doc.get("gates", [])
         if isinstance(g, dict) and g.get("label") == label]
ok = (
    len(corpora) == len(gates) == 1
    and corpora[0] == {"name": name, "items": 0, "gates": 1,
                       "expansion": "EXPANDED"}
    and gates[0].get("state") == "NOT_CHECKED"
    and gates[0].get("corpus") == name
    and gates[0].get("corpus_item") == 0
    and gates[0].get("corpus_items") == 0
    and gates[0].get("exempt_until") is None
    and gates[0].get("exempt_reason") is None
    and gates[0].get("scope") is None
    and not any(a.get("label") == label for a in
                doc.get("process_attestations", []) if isinstance(a, dict))
    and (doc.get("corpus_inputs") or {}).get("benchmark_data_sha") == sys.argv[3]
)
raise SystemExit(0 if ok else 1)
PY
}

cleanup_event() {
  # Test/diagnostic-only semantic events.  The probe directory is outside the
  # run tree, so the final event survives worktree removal and lets a caller
  # wait for an observed cleanup phase instead of guessing how many seconds a
  # loaded host needs.  Ordinary production runs do not set this variable.
  [ -n "${GATEKEEPER_CONCURRENCY_PROBE_DIR:-}" ] || return 0
  mkdir -p -- "$GATEKEEPER_CONCURRENCY_PROBE_DIR" 2>/dev/null || return 0
  local event="$1" tmp
  tmp="$GATEKEEPER_CONCURRENCY_PROBE_DIR/.cleanup.$event.$$"
  printf '%s\n' "$$" > "$tmp" 2>/dev/null || return 0
  mv -f -- "$tmp" "$GATEKEEPER_CONCURRENCY_PROBE_DIR/cleanup.$event" \
    2>/dev/null || true
}

cleanup() {
  cleanup_event started
  # Every measured arm owns a process group.  Stop the entire group before its
  # worktree disappears; killing only the wrapper shell leaves pytest or a gate
  # subprocess running against a directory cleanup is about to remove.
  for pid in "${A1_PID:-}" "${A2_PID:-}" "${B1_PID:-}" "${B2_PID:-}"; do
    [ -n "$pid" ] || continue
    kill -TERM -- "-$pid" >/dev/null 2>&1 || true
  done
  # Every arm's trusted top-level supervisor owns TERM/KILL escalation and a
  # PID/starttime final-zero census.  Wait for that semantic terminal state;
  # replacing it with a two-second outer guess killed the wrapper before its
  # separately-sessioned reaper could finish and left the actual gate alive.
  for pid in "${A1_PID:-}" "${A2_PID:-}" "${B1_PID:-}" "${B2_PID:-}"; do
    [ -n "$pid" ] || continue
    wait "$pid" >/dev/null 2>&1 || true
  done
  cleanup_event reaped
  if [ "$KEEP" = "1" ]; then
    echo "--- kept: $RUN (worktrees included)"
    cleanup_event done
    return
  fi
  if [ "$BENCHMARK_B2_ADDED" = "1" ] && [ -n "$BENCHMARK_SOURCE" ]; then
    git -C "$BENCHMARK_SOURCE" worktree remove --force "$BENCHMARK_B2" \
      >/dev/null 2>&1 || true
  fi
  if [ "$BENCHMARK_A2_ADDED" = "1" ] && [ -n "$BENCHMARK_SOURCE" ]; then
    git -C "$BENCHMARK_SOURCE" worktree remove --force "$BENCHMARK_A2" \
      >/dev/null 2>&1 || true
  fi
  [ -z "$BENCHMARK_SOURCE" ] \
    || git -C "$BENCHMARK_SOURCE" worktree prune >/dev/null 2>&1 || true
  "${G[@]}" worktree remove --force "$WT_CAND" >/dev/null 2>&1
  "${G[@]}" worktree remove --force "$WT_CAND_TESTS" >/dev/null 2>&1
  "${G[@]}" worktree remove --force "$WT_BASE" >/dev/null 2>&1
  "${G[@]}" worktree remove --force "$WT_BASE_TESTS" >/dev/null 2>&1
  "${G[@]}" update-ref -d "$HEAD_REF"  >/dev/null 2>&1
  "${G[@]}" update-ref -d "$MERGE_REF" >/dev/null 2>&1
  rm -rf "$RUN"
  cleanup_event done
}

signal_exit() {
  # Bash defers a trapped signal while it waits for a foreground child.  Once
  # that child returns, EXIT immediately so the EXIT trap owns all four arms;
  # without this explicit bridge the script continued to its normal `wait A2`
  # and an A2 that ignored TERM kept the verifier alive forever.
  local rc="$1"
  trap - INT TERM
  exit "$rc"
}

trap cleanup EXIT
trap 'signal_exit 130' INT
trap 'signal_exit 143' TERM

echo "=== gatekeeper merge-path verification ==="
echo "--- repo=$REPO  base=$BASE  $( [ -n "$PR" ] && echo "pr=#$PR" || echo "ref=$REF" )"

# ------------------------------------------------------------------ 1. fetch
GITHUB_TREE=""
PR_TITLE=""
if [ -n "$PR" ]; then
  if [ "$NO_FETCH" = "0" ]; then
    "${G[@]}" fetch -q origin main "+refs/pull/$PR/head:$HEAD_REF" \
      || die "cannot fetch pull/$PR/head"
    # The forge's OWN merge result. Present only while the PR is mergeable, and
    # authoritative: `gh pr merge --squash` creates a commit with THIS tree.
    if "${G[@]}" fetch -q origin "+refs/pull/$PR/merge:$MERGE_REF" 2>/dev/null; then
      FORGE_TREE="$("${G[@]}" rev-parse "$MERGE_REF^{tree}")"
      FORGE_BASE="$("${G[@]}" rev-parse "$MERGE_REF^1" 2>/dev/null)"
    else
      echo "--- note: the forge publishes no refs/pull/$PR/merge (not mergeable, or not computed yet)"
    fi
    PR_TITLE="$(gh pr view "$PR" --repo "$("${G[@]}" remote get-url origin \
        | sed -E 's#.*github\.com[:/]##; s#\.git$##')" --json title \
        --jq .title 2>/dev/null)"
  fi
  HEAD_SHA="$("${G[@]}" rev-parse "$HEAD_REF" 2>/dev/null)" \
    || die "no local $HEAD_REF (drop --no-fetch)"
else
  [ "$NO_FETCH" = "0" ] && "${G[@]}" fetch -q origin main 2>/dev/null
  HEAD_SHA="$("${G[@]}" rev-parse "$REF" 2>/dev/null)" || die "cannot resolve $REF"
fi
BASE_SHA="$("${G[@]}" rev-parse "$BASE" 2>/dev/null)" || die "cannot resolve $BASE"
BASE_TREE="$("${G[@]}" rev-parse "$BASE_SHA^{tree}" 2>/dev/null)" \
  || die "cannot resolve the base tree"
# The orchestrator itself must be a byte owned by the base it is judging.  A
# candidate may contain the same path, but it cannot use its edited verifier as
# landing authority.  Phase 1 is therefore judged by the already-trusted old
# verifier; after phase 1 lands, phase 2's unchanged verifier matches BASE.
SELF_VERIFIER_BLOB="$(git -C "$SELF_REPO" hash-object --no-filters \
  "$SELF/gatekeeper-verify-merge.sh" 2>/dev/null)" \
  || die "cannot hash the running verifier bytes"
BASE_VERIFIER_BLOB="$("${G[@]}" rev-parse \
  "$BASE_SHA:tools/gatekeeper-verify-merge.sh" 2>/dev/null)" \
  || die "base does not carry the trusted merge verifier"
[ "$SELF_VERIFIER_BLOB" = "$BASE_VERIFIER_BLOB" ] \
  || die "running verifier is not the exact base-owned verifier; invoke the copy from current main"
if [ -n "$("${G[@]}" for-each-ref --format='%(refname)' refs/replace \
     2>/dev/null)" ]; then
  die "repository has active refs/replace; the verified object graph is not canonical"
fi
refresh_and_attest_trusted_tools
# THE FORGE'S ANSWER IS ABOUT THE FORGE'S BASE. `refs/pull/<n>/merge` is the merge
# of the PR head into the tip of the branch the PR TARGETS; asked about any other
# base it is not a second opinion, it is a different question. Comparing them
# anyway produced a confident refusal — "THE FORGE DISAGREES" — about a PR that
# was fine, which is a false refusal and therefore the same defect as a false
# pass. Used only when the two bases are the same commit; otherwise disclosed and
# dropped.
if [ -n "${FORGE_BASE:-}" ] && [ "$FORGE_BASE" = "$BASE_SHA" ]; then
  GITHUB_TREE="${FORGE_TREE:-}"
elif [ -n "${FORGE_TREE:-}" ]; then
  echo "--- note: the forge merged against ${FORGE_BASE:0:12}, this run is verifying"
  echo "          against ${BASE_SHA:0:12}; the forge tree answers a different question"
  echo "          and was NOT used as a cross-check."
fi
echo "--- base=${BASE_SHA:0:12}  head=${HEAD_SHA:0:12}${GITHUB_TREE:+  forge-merge-tree=${GITHUB_TREE:0:12}}"

# ------------------------- 2. CHEAP GATES ON THE ACTUAL PUSH POPULATION
# Run these BEFORE merge-tree synthesis, worktree construction, pytest, or the
# landing arms.  This closes the failure mode where hours of CPU verification
# succeeded and only the later pre-push hook revealed that the branch's actual
# commit sequence contained a forbidden collateral revert.  A PR head is
# already published, so BASE..HEAD is its complete PR population.  A local
# --ref may still be unpublished; derive_push_range names exactly those commits.
PUSH_PREFLIGHT_RECEIPT="$RUN/push-preflight.json"
if [ -n "$PR" ]; then
  PUSH_RANGE="$BASE_SHA..$HEAD_SHA"
  PUSH_RANGE_SOURCE="published PR population"
else
  derive_push_range "$REF" "$HEAD_SHA" "$BASE_SHA"
fi
echo "--- push-range=$PUSH_RANGE ($PUSH_RANGE_SOURCE)"
PUSH_PREFLIGHT_RC=0
PYTHONDONTWRITEBYTECODE=1 python3 -B \
    "$TRUSTED_REPO/tools/ci/protected_landing_transition.py" push-preflight \
    --object-repo "$REPO" --base "$BASE_SHA" \
    --candidate "$HEAD_SHA" --push-range "$PUSH_RANGE" \
    --receipt "$PUSH_PREFLIGHT_RECEIPT" \
  || PUSH_PREFLIGHT_RC=$?
if [ "$PUSH_PREFLIGHT_RC" -ne 0 ]; then
  [ -z "$JSON_OUT" ] || cp "$PUSH_PREFLIGHT_RECEIPT" "$JSON_OUT"
  exit "$PUSH_PREFLIGHT_RC"
fi

# ------------------------- 3. CAN THIS HOST COMPUTE THE MERGE TREE AT ALL?
# `git merge-tree --write-tree` landed in git 2.38. Measured 2026-08-12 across
# the fleet this repo is maintained on, FOUR OF SIX HOSTS RUN 2.34.1 — including
# the orchestrator, which is where every `gh pr merge` is actually run.
#
# On those hosts the strong path does not fail, it never starts: `--write-tree`
# is read as a REV, git answers `fatal: unknown rev --write-tree`, the tree comes
# back empty and the verdict refuses with THE MERGE TREE COULD NOT BE COMPUTED.
# That refusal is CORRECT — it fails closed and says so, and that property is
# kept below — but as a gate it was useless: it refused every landing on the only
# host that lands, which is the ban this whole program exists to avoid.
#
# So the capability is PROBED and the run picks a TIER:
#
#   merge-tree      the strong path, unchanged. The tree under test is the 3-way
#                   merge, and the rebase replay is an INDEPENDENT second opinion
#                   whose disagreement is a refusal.
#   rebase-replay   the fallback. The tree under test is the REBASE REPLAY, and
#                   THE SQUASH-VS-REBASE CROSS-CHECK IS NOT PERFORMED — there is
#                   only one answer, so there is nothing to disagree with it.
#
# The fallback is a WEAKER CHECK, NOT A PASS. Every other refusal reason — the
# test differential, the gate differential, silencing, truncation, the stamp, the
# forge cross-check when the forge merged this same base — is computed
# identically in both tiers, and the paired negative control is asserted UNDER
# THE FALLBACK specifically (`test_end_to_end_the_fallback_still_refuses_an_
# innocuous_diff_that_leaves_a_test_red`). A disclosed weaker check beats a
# universal refusal; a fallback that passes everything would be worse than both.
#
# The loss is DISCLOSED in the printed verdict AND machine-readably in the JSON
# (`verification_tier`, `tier_degraded`, `squash_vs_rebase_cross_check`, and the
# `disclosures` code list), because a downstream reader has to be able to tell
# the two tiers apart without parsing prose.
#
# THE PROBE IS FUNCTIONAL, NOT A VERSION COMPARISON. A version parse is what
# breaks on `2.39.3 (Apple Git-145)` and on vendor forks, and it would answer
# about the string rather than the capability. `git --version` is read only to
# NAME the version found alongside the version needed, which is what a refusal
# has to say to be actionable. Merging the base with ITSELF is the cheapest
# question whose answer is known in advance — the base's own tree — so the probe
# reports a property of the HOST and can never become an opinion about this PR.
MERGE_TREE_MIN_VERSION="2.38"
GIT_VERSION="$("${G[@]}" --version 2>/dev/null \
    | sed -n 's/^git version \([0-9][0-9A-Za-z.]*\).*/\1/p')"
[ -n "$GIT_VERSION" ] || GIT_VERSION="unknown"
TIER="merge-tree"
TIER_REASON=""
if [ "${GATEKEEPER_FORCE_REBASE_REPLAY:-0}" = "1" ]; then
  # THE TEST HOOK, and the only way the fallback branch can be exercised on a
  # host that HAS the capability. Without it the fallback would be untested
  # everywhere it is not needed and untestable everywhere it is — which is
  # moving the untested path rather than removing it. It can only ever move a
  # run to the WEAKER, DISCLOSED tier: there is no value of it that turns any
  # refusal into a pass, and a forced fallback discloses exactly as a natural
  # one does.
  TIER="rebase-replay"
  TIER_REASON="forced by GATEKEEPER_FORCE_REBASE_REPLAY (git $GIT_VERSION)"
else
  MT_PROBE="$("${G[@]}" merge-tree --write-tree "$BASE_SHA" "$BASE_SHA" 2>/dev/null)"
  MT_PROBE_RC=$?
  if [ "$MT_PROBE_RC" -ne 0 ] \
     || ! printf '%s\n' "$MT_PROBE" | head -1 | grep -Eq '^[0-9a-f]{40,64}$'; then
    TIER="rebase-replay"
    TIER_REASON="git $GIT_VERSION does not support \`merge-tree --write-tree\` (needs >= $MERGE_TREE_MIN_VERSION)"
  fi
fi

# --------------------------------------- 2b. the tree that WOULD be merged
# `--write-tree` reports the merge of base and head from their merge base — the
# same computation the forge does — and exits 1 when it conflicts.
EXPECTED_TREE=""
if [ "$TIER" = "merge-tree" ]; then
  MT_OUT="$("${G[@]}" merge-tree --write-tree "$BASE_SHA" "$HEAD_SHA" 2>&1)"; MT_RC=$?
  if [ "$MT_RC" -eq 0 ]; then
    EXPECTED_TREE="$(printf '%s\n' "$MT_OUT" | head -1)"
  else
    # THE CAPABILITY IS PRESENT AND THE MERGE STILL FAILED, so this is a fact
    # about the PR and not about the host. Unchanged: it stays a refusal.
    echo "--- the merge does not apply cleanly (merge-tree rc=$MT_RC):"
    printf '%s\n' "$MT_OUT" | head -12 | sed 's/^/      /'
  fi
else
  echo "--- merge-tree capability ABSENT — $TIER_REASON"
  echo "    TIER=rebase-replay: the tree under test is the REBASE REPLAY, and the"
  echo "    squash-vs-rebase cross-check is NOT performed. Disclosed in the verdict"
  echo "    and in the JSON record; every other refusal reason is unchanged."
fi

# ------------------------------------------- 4. rebase in a throwaway worktree
"${G[@]}" worktree add -q --detach "$WT_CAND" "$HEAD_SHA" \
  || die "cannot create the candidate worktree"
REBASE_STATUS=ok
# `-c user.*` so a clone with no identity can still replay commits; `rebase.
# autoStash=false` because there is nothing to stash in a fresh worktree and an
# autostash would hide it if there were.
if ! git -C "$WT_CAND" -c rebase.autoStash=false \
      -c user.name=gatekeeper-verify -c user.email=gatekeeper-verify@localhost \
      rebase "$BASE_SHA" > "$RUN/rebase.log" 2>&1; then
  REBASE_STATUS=conflict
  echo "--- REBASE CONFLICT:"
  tail -12 "$RUN/rebase.log" | sed 's/^/      /'
  git -C "$WT_CAND" rebase --abort >/dev/null 2>&1
fi
REBASED_SHA="$(git -C "$WT_CAND" rev-parse HEAD)"
REBASED_TREE="$(git -C "$WT_CAND" rev-parse 'HEAD^{tree}')"

# THE FALLBACK'S TREE UNDER TEST — adopted ONLY when the replay actually
# succeeded. A conflicted rebase leaves the HEAD's own tree checked out in the
# worktree, which is not a merge result at all; adopting that would verify a tree
# nobody will ever create, and it would do it silently, which is the one failure
# mode worse than the refusal this replaces. Left EMPTY on conflict so the
# verdict refuses as UNMEASURABLE, exactly as the strong tier does — the
# fail-closed property is preserved, not traded away.
if [ "$TIER" = "rebase-replay" ] && [ "$REBASE_STATUS" = "ok" ]; then
  EXPECTED_TREE="$REBASED_TREE"
fi
echo "--- rebase=$REBASE_STATUS  replayed=${REBASED_SHA:0:12}  tree=${REBASED_TREE:0:12}  tier=$TIER  tree-under-test=${EXPECTED_TREE:0:12}"

# A rebase conflict, a disagreement between the replay and the merge, or a forge
# that disagrees with both means nothing downstream measures the right tree. Run
# the verdict on what we have and stop — the suites would answer a question about
# a tree nobody will create.
#
# UNDER THE FALLBACK the replay-vs-merge comparison is vacuous by construction
# (they are the same object) — that IS the disclosed loss. The FORGE comparison
# below is not vacuous and is not dropped: when the forge merged this same base,
# `refs/pull/<n>/merge` is an independent second opinion computed by a git new
# enough to have the capability this host lacks, so the fallback still gets a
# real cross-check whenever the forge published one.
SHORT_CIRCUIT=0
[ "$REBASE_STATUS" != "ok" ] && SHORT_CIRCUIT=1
[ -z "$EXPECTED_TREE" ] && SHORT_CIRCUIT=1
[ -n "$EXPECTED_TREE" ] && [ "$EXPECTED_TREE" != "$REBASED_TREE" ] && SHORT_CIRCUIT=1
[ -n "$GITHUB_TREE" ] && [ -n "$EXPECTED_TREE" ] && [ "$GITHUB_TREE" != "$EXPECTED_TREE" ] && SHORT_CIRCUIT=1

# ------------------------------- 5. THE SQUASH COMMIT — what actually lands
VERIFIED_SHA="$REBASED_SHA"
VERIFIED_TREE="$REBASED_TREE"
if [ "$SHORT_CIRCUIT" = "0" ]; then
  # The forge's default squash message: the PR title, then every commit message
  # in the branch. Built here so `commit_msg_nda_check` and
  # `git_prohibition_guard` read the text that will actually reach `main` — a
  # squash of six commits publishes all six messages in its body.
  {
    if [ -n "$PR_TITLE" ]; then printf '%s (#%s)\n' "$PR_TITLE" "$PR"
    else git -C "$WT_CAND" log -1 --format='%s' "$REBASED_SHA"; fi
    printf '\n'
    git -C "$WT_CAND" log --reverse --format='* %B' "$BASE_SHA..$REBASED_SHA"
  } > "$RUN/squash_msg.txt"
  # Fixed identity and date so the same (base, tree) always yields the same SHA
  # and a verdict is reproducible. The forge picks its own, so this SHA is a
  # stand-in — the TREE is the identity that matters, and both are reported.
  VERIFIED_SHA="$(GIT_AUTHOR_NAME=gatekeeper-verify \
      GIT_AUTHOR_EMAIL=gatekeeper-verify@localhost \
      GIT_COMMITTER_NAME=gatekeeper-verify \
      GIT_COMMITTER_EMAIL=gatekeeper-verify@localhost \
      GIT_AUTHOR_DATE='@0 +0000' GIT_COMMITTER_DATE='@0 +0000' \
      "${G[@]}" commit-tree "$EXPECTED_TREE" -p "$BASE_SHA" \
          -F "$RUN/squash_msg.txt")" || die "cannot build the squash commit"
  git -C "$WT_CAND" checkout -q --detach "$VERIFIED_SHA" \
    || die "cannot check out the squash commit"
  VERIFIED_TREE="$(git -C "$WT_CAND" rev-parse 'HEAD^{tree}')"
  echo "--- squash=${VERIFIED_SHA:0:12}  tree=${VERIFIED_TREE:0:12}  ($(grep -c '' "$RUN/squash_msg.txt") message line(s) scanned)"
fi

PLUGIN_REL="vibe-ic-marketplace/plugins/vibe-ic"
CAND_PLUGIN="$WT_CAND/$PLUGIN_REL"
# ---------------------------------------------- 6. DIFFERENTIAL VERIFIER ARMS
# THE JUDGE COMES FROM THE RAW-ATTESTED BASE SNAPSHOT, NOT FROM THE SUBJECT
# (see the header).  A foreign `--repo` does not create a subject fallback.
VERDICT_PROG="$TRUSTED_REPO/$PLUGIN_REL/programs/landing_merge_verdict.py"
[ -f "$VERDICT_PROG" ] \
  || die "trusted base does not carry landing_merge_verdict.py"
: > "$RUN/selection.txt"
# Created HERE, not only inside the `SHORT_CIRCUIT=0` branch, so the verdict is
# always handed a file it can read. An absent file and an empty one both mean
# "the base arm was asked for nothing", which the verdict reports as a
# not-checked disclosure rather than as a clean base arm (vibe-ic#1443).
: > "$RUN/selection_base.txt"
: > "$RUN/land.log"
CAND_JUNIT="$RUN/candidate.xml"
BASE_JUNIT="$RUN/base.xml"
B2_RC=2
B1_WORKTREE_STATUS=unknown
A1_WORKTREE_STATUS=unknown
BASE_LAND_ARG=()
# vibe-ic#1498 — the two arms' hygiene RECORDS, so the gate differential can ask
# the hygiene tier which findings this branch INTRODUCED rather than only
# whether its one label failed. Both arms already run `gatekeeper-land.sh`; all
# that is added is that each writes its `--summary-json` record where the
# verdict can read it.
#
# The pair is handed to the verdict once the BASE arm produced a record; without
# one the verdict discloses the loss and falls back to the coarse per-label
# comparison, because the branch does not control whether arm A2 ran. A missing
# CANDIDATE record is NOT the same event and is NOT hidden here — that path is
# passed either way and the verdict refuses on it, since that is the tree under
# test failing to measure itself.
BASE_HYG="$RUN/base_hygiene.json"
CAND_HYG="$RUN/candidate_hygiene.json"
HYG_ARGS=()
TRANSITION_ARGS=()
# The host is REQUIRED by `hygiene_finding_delta` and never inferred: these
# findings are host-dependent (`gate_host_independence_check` is one of the
# gates). Both arms run HERE, so both hosts are this one — except on a
# `--base-gate-cache` hit, where the base arm did not run at all and the host
# is whatever measured the cached record. It is stored beside it for that
# reason rather than assumed.
THIS_HOST="$(uname -n)"
BASE_HYG_HOST="$THIS_HOST"

# The PR may change the very gate that judges it — this one does. Disclosed in
# the verdict, never blocking: a PR that improves the gate must be landable, and
# the reviewer needs to know the gate it passed was its own.
GATE_ARGS=()
while read -r p; do
  [ -n "$p" ] && GATE_ARGS+=(--gate-edited "$p")
done < <("${G[@]}" diff --name-only "$BASE_SHA" "$REBASED_SHA" -- \
            tools/gatekeeper-land.sh tools/gatekeeper-verify-merge.sh \
            tools/ci/repo_hygiene_gates.sh tools/ci/_gate_dispatch.sh \
            tools/ci/benchmark_data_landing_checkout.py \
            tools/ci/owned_command.py tools/ci/routed_def_corpus.py \
            tools/ci/hermetic_candidate_runner.py \
            tools/ci/hermetic_git_subject.py \
            tools/ci/hermetic_progress_emit.py \
            tools/ci/hermetic_test_arm_entry.sh \
            tools/ci/landing_completion_record.py \
            tools/ci/protected_landing_transition.py \
            tools/ci/protected_landing_transition.json \
            tools/ci/protected_runtime_snapshot.py \
            tools/ci/trusted_test_selection.py \
            tools/ci/trusted_worktree_attest.py tools/git-hooks/pre-push \
            "$PLUGIN_REL/programs/_owned_process_supervisor.py" \
            "$PLUGIN_REL/programs/gate_process_attestation.py" \
            "$PLUGIN_REL/programs/landing_merge_verdict.py" \
            "$PLUGIN_REL/programs/hygiene_finding_delta.py" \
            "$PLUGIN_REL/programs/ci_targeted_test_select.py" \
            "$PLUGIN_REL/programs/pytest_per_file_junit.py" \
            "$PLUGIN_REL/programs/repo_hygiene_parallel.py" 2>/dev/null)

if [ "$SHORT_CIRCUIT" = "0" ]; then
  # Phase-A's verifier executes both sides with one BASE-authorised runtime.
  # Candidate arms run first in a fixed, digest-pinned, least-privilege OCI
  # profile.  Only after both containers have naturally exited, published
  # strict receipts, and been removal-proved do we materialize either BASE arm.
  prepare_benchmark_snapshots
  "${G[@]}" worktree add -q --detach "$WT_CAND_TESTS" "$VERIFIED_SHA" \
    || die "cannot create the candidate-test worktree"
  validate_protected_landing_transition "$PROTECTED_PRE" \
    || die "protected landing source tuple is not BASE-authorised"
  PROTECTED_PRE_SHA256="$(sha256sum "$PROTECTED_PRE" | awk '{print $1}')" \
    || die "cannot bind the pre-arm protected landing receipt"
  materialize_protected_runtime
  build_trusted_test_selection

  # BETWEEN THE SELECTOR AND THE RUNNER, which is the position
  # `generated_test_list_min_guard` was written for and had never once been
  # called from: vibe-ic#381 counted it as a checker nothing but its own unit
  # test runs. It closes two measured failures that both read as green and fail
  # in OPPOSITE directions, so neither guards the other:
  #
  #   an EMPTY list runs EVERYTHING — `xargs -a <empty> python3 -m pytest`
  #     invokes pytest with no path arguments, so it falls back to `testpaths`
  #     and sweeps the whole suite. Measured: a selector timed out, wrote a
  #     zero-byte list, and two arms launched an unbounded sweep across two
  #     clones.
  #   a list naming a path that DOES NOT RESOLVE runs NOTHING, and reports it
  #     with a success code.
  #
  # MEASURED before wiring, over a real 1313-entry selection from this
  # selector: `[PASS] 1313 distinct entr(ies) >= minimum 1, all resolvable`.
  #
  # `--root` is the CANDIDATE plugin tree, because that is where the selector's
  # relative paths resolve and the arm about to consume the list runs there —
  # resolving them against the parent checkout would answer for a tree that is
  # not the one under test.
  #
  # `--min 1` IS THE FLOOR THE CALLER CAN HONESTLY STATE TODAY, and it is
  # deliberately not larger. The guard's own header argues that a real minimum
  # must come from outside the list, and this lane does not yet carry a
  # declared expected size; inventing one here would be a number nobody
  # measured, which is the shape this repository keeps finding in its own
  # baselines. At 1 it still closes both failures above — emptiness by the
  # count, the unresolvable path by the resolution — and raising it later is a
  # ratchet, not a rewrite.
  python3 -B "$RUNTIME_SNAPSHOT/$PLUGIN_REL/programs/generated_test_list_min_guard.py" \
      "$RUN/selection.txt" --min 1 --root "$WT_CAND/$PLUGIN_REL" \
    || die "the candidate test selection is not a usable list (empty, or naming a path that does not resolve): a bad list runs everything or nothing, and both report success"

  # THE LANDING IS A CLAIM ABOUT TWO TREES. `landing_noop_verdict_check` also
  # shipped with nothing but its own unit test running it. This repository
  # SQUASH-lands, so content reaches the trunk without ancestry and a merge
  # tool asked "is there anything to land?" answers for its own staging area
  # instead of for the trees — measured 2026-08-21, a batch logged NOTHING TO
  # LAND for a lane that differed from the trunk in FOUR files, three of them
  # not generated, one push from being dropped without a word.
  #
  # `--claim work` is the claim THIS lane makes: a verification arm is about to
  # spend an hour proving a candidate that asserts it changes something. Every
  # non-zero refuses, and the two non-zero codes are different facts worth
  # keeping apart in the message: rc 1 is "the trees do not support the claim",
  # rc 2 is "the branch touches no path at all relative to the merge base" —
  # which for `--claim work` is the no-op this gate exists to name.
  #
  # MEASURED before wiring, against a real lane (`origin/next/b73land` vs
  # `origin/main`): rc 1, naming all 4 paths that are not byte-identical. The
  # instrument works on real artefacts, not only on its author's fixture.
  python3 -B "$RUNTIME_SNAPSHOT/$PLUGIN_REL/programs/landing_noop_verdict_check.py" \
      --branch "$VERIFIED_SHA" --target "$BASE_SHA" --repo "$REPO" --claim work \
    || die "the candidate does not differ from the base it is being verified against: a landing verdict is a claim about the two TREES, and this pair does not support it"
  materialize_hermetic_git_subject \
    "$REPO" "$VERIFIED_SHA" "$CAND_SUBJECT" "$CAND_SUBJECT_RECORD"
  materialize_hermetic_git_subject \
    "$BENCHMARK_SOURCE" "$BENCHMARK_SHA" "$BENCHMARK_B2" \
    "$BENCHMARK_SUBJECT_RECORD"
  # The container runs as uid 65534; parent-owned inputs are immutable bind
  # mounts, but must be readable by that uid.
  chmod 0644 "$RUN/selection.txt" "$RUN/selection_base.txt" \
    "$A1_PROGRESS_PLAN" "$B1_PROGRESS_PLAN" \
    "$A2_PROGRESS_PLAN" "$B2_PROGRESS_PLAN" \
    || die "cannot publish read-only arm inputs"

  BASE_PLUGIN="$WT_BASE/$PLUGIN_REL"
  BASE_TEST_PLUGIN="$WT_BASE_TESTS/$PLUGIN_REL"
  CAND_TEST_PLUGIN="$WT_CAND_TESTS/$PLUGIN_REL"
  A1_ASKED=1
  A1_RC=2
  A2_RC=2
  B1_RC=2
  B2_RC=2
  VBG=1
  [ "$REQUIRE_VERSION_BUMP" = "1" ] && VBG=0

  launch_hermetic_test_arm B1 "$CAND_SUBJECT" "$BENCHMARK_B2" \
    "$RUN/selection.txt" "$B1_PROGRESS_PLAN" "$B1_OUTPUT" "$B1_RECEIPT" \
    "$RUN/b1-runner.log"
  B1_PID=$LAST_ARM_PID
  launch_hermetic_land_arm B2 "$CAND_SUBJECT" "$BENCHMARK_B2" \
    "$RUN/selection.txt" "$B2_PROGRESS_PLAN" "$B2_OUTPUT" "$B2_RECEIPT" \
    "$RUN/b2-runner.log" "$VBG"
  B2_PID=$LAST_ARM_PID
  wait "$B1_PID"; B1_RUNNER_RC=$?; B1_PID=""
  wait "$B2_PID"; B2_RUNNER_RC=$?; B2_PID=""
  validate_hermetic_arm_record "$B1_RUNNER_RC" "$B1_RECEIPT" "$B1_OUTPUT" \
    B1 "$CAND_SUBJECT" "$BENCHMARK_B2" "$RUN/selection.txt" \
    "$B1_PROGRESS_PLAN" /subject/tools/ci/hermetic_test_arm_entry.sh \
    "$B1_VALIDATION"
  B1_RC=$LAST_ARM_RC
  validate_hermetic_arm_record "$B2_RUNNER_RC" "$B2_RECEIPT" "$B2_OUTPUT" \
    B2 "$CAND_SUBJECT" "$BENCHMARK_B2" "$RUN/selection.txt" \
    "$B2_PROGRESS_PLAN" /subject/tools/gatekeeper-land.sh \
    "$B2_VALIDATION" landing-completion.json "$VERIFIED_SHA"
  B2_RC=$LAST_ARM_RC

  # No BASE pathname or result existed while candidate code ran.  Rebuild the
  # trusted authority and require the protected PRE receipt to reproduce byte
  # for byte before creating the base wave.
  refresh_and_attest_trusted_tools
  validate_protected_landing_transition "$PROTECTED_POST" \
    || die "protected landing tuple cannot be re-attested after candidate exit"
  [ "$(sha256sum "$PROTECTED_POST" | awk '{print $1}')" = \
      "$PROTECTED_PRE_SHA256" ] \
    || die "protected landing transition receipt changed across candidate arms"
  cmp -s -- "$PROTECTED_PRE" "$PROTECTED_POST" \
    || die "protected landing transition PRE/POST records differ"
  PROTECTED_ARGS=(--protected-transition-receipt "$PROTECTED_POST")

  clear_base_wave_artifacts
  prepare_base_wave
  materialize_hermetic_git_subject \
    "$REPO" "$BASE_SHA" "$BASE_SUBJECT" "$BASE_SUBJECT_RECORD"
  # clear_base_wave_artifacts intentionally removed the base selection path;
  # regenerate it from the already-bound selection manifest, not from a
  # candidate-controlled selector or worktree.
  run_owned_operational "$RUNTIME_SNAPSHOT" \
    python3 "$RUNTIME_SNAPSHOT/tools/ci/trusted_test_selection.py" \
      --object-repo "$REPO" --base "$BASE_SHA" --candidate "$VERIFIED_SHA" \
      --selector-commit "$RUNTIME_AUTHORITY_COMMIT" \
      --selector-path "$RUNTIME_SNAPSHOT/$PLUGIN_REL/programs/ci_targeted_test_select.py" \
      --base-snapshot "$TRUSTED_REPO" \
      --candidate-snapshot "$WT_CAND" \
      --manifest "$RUN/test-selection.after.json" \
      --base-selection "$RUN/selection_base.txt" \
      --candidate-selection "$RUN/selection.after.txt" \
      --base-progress-plan "$RUN/a1-progress-plan.after.json" \
      --candidate-progress-plan "$RUN/b1-progress-plan.after.json" \
      --stall-grace-seconds "$TEST_ARM_SEMANTIC_STALL_GRACE" \
    || die "cannot reproduce the BASE-owned selection after candidate exit"
  cmp -s -- "$SELECTION_MANIFEST" "$RUN/test-selection.after.json" \
    || die "BASE-owned selection manifest changed across candidate arms"
  cmp -s -- "$RUN/selection.txt" "$RUN/selection.after.txt" \
    || die "candidate selection changed across candidate arms"
  cmp -s -- "$A1_PROGRESS_PLAN" "$RUN/a1-progress-plan.after.json" \
    || die "base test progress plan changed across candidate arms"
  cmp -s -- "$B1_PROGRESS_PLAN" "$RUN/b1-progress-plan.after.json" \
    || die "candidate test progress plan changed across candidate arms"
  chmod 0644 "$RUN/selection_base.txt" \
    || die "cannot publish base selection to the hermetic arm"

  launch_hermetic_test_arm A1 "$BASE_SUBJECT" "$BENCHMARK_B2" \
    "$RUN/selection_base.txt" "$A1_PROGRESS_PLAN" "$A1_OUTPUT" "$A1_RECEIPT" \
    "$RUN/a1-runner.log"
  A1_PID=$LAST_ARM_PID
  launch_hermetic_land_arm A2 "$BASE_SUBJECT" "$BENCHMARK_B2" \
    "$RUN/selection_base.txt" "$A2_PROGRESS_PLAN" "$A2_OUTPUT" "$A2_RECEIPT" \
    "$RUN/a2-runner.log" 1
  A2_PID=$LAST_ARM_PID
  wait "$A1_PID"; A1_RUNNER_RC=$?; A1_PID=""
  wait "$A2_PID"; A2_RUNNER_RC=$?; A2_PID=""
  validate_hermetic_arm_record "$A1_RUNNER_RC" "$A1_RECEIPT" "$A1_OUTPUT" \
    A1 "$BASE_SUBJECT" "$BENCHMARK_B2" "$RUN/selection_base.txt" \
    "$A1_PROGRESS_PLAN" /subject/tools/ci/hermetic_test_arm_entry.sh \
    "$A1_VALIDATION"
  A1_RC=$LAST_ARM_RC
  validate_hermetic_arm_record "$A2_RUNNER_RC" "$A2_RECEIPT" "$A2_OUTPUT" \
    A2 "$BASE_SUBJECT" "$BENCHMARK_B2" "$RUN/selection_base.txt" \
    "$A2_PROGRESS_PLAN" /subject/tools/gatekeeper-land.sh \
    "$A2_VALIDATION" landing-completion.json "$BASE_SHA"
  A2_RC=$LAST_ARM_RC
  compare_hermetic_shared_inputs \
    "$A1_RECEIPT" "$B1_RECEIPT" "$A2_RECEIPT" "$B2_RECEIPT" \
    || die "A/B arms did not consume one identical runtime/corpus/image"

  # The final judge receives only fresh parent-owned copies of files named and
  # digested in the stopped-container receipts.
  rm -f -- "$RUN/land.log"
  publish_validated_arm_artifact "$B1_VALIDATION" "$B1_OUTPUT" pytest.xml "$CAND_JUNIT" \
    || die "cannot seal candidate JUnit evidence"
  publish_validated_arm_artifact "$A1_VALIDATION" "$A1_OUTPUT" pytest.xml "$BASE_JUNIT" \
    || die "cannot seal base JUnit evidence"
  publish_validated_arm_artifact "$B2_VALIDATION" "$B2_OUTPUT" hygiene.json "$CAND_HYG" \
    || die "cannot seal candidate hygiene evidence"
  publish_validated_arm_artifact "$A2_VALIDATION" "$A2_OUTPUT" hygiene.json "$BASE_HYG" \
    || die "cannot seal base hygiene evidence"
  publish_validated_arm_artifact "$B2_VALIDATION" "$B2_OUTPUT" runner-stdout.bin \
    "$RUN/land.log" || die "cannot seal candidate landing log"
  publish_validated_arm_artifact "$A2_VALIDATION" "$A2_OUTPUT" runner-stdout.bin \
    "$RUN/base_land.log" || die "cannot seal base landing log"
  publish_validated_arm_artifact "$B1_VALIDATION" "$B1_OUTPUT" runner-stdout.bin \
    "$RUN/candidate_tests.log" || die "cannot seal candidate test log"
  publish_validated_arm_artifact "$A1_VALIDATION" "$A1_OUTPUT" runner-stdout.bin \
    "$RUN/base_tests.log" || die "cannot seal base test log"

  B1_WORKTREE_STATUS=clean
  A1_WORKTREE_STATUS=clean
  hygiene_record_binds_benchmark "$CAND_HYG" "$BENCHMARK_SHA" \
    || die "candidate hygiene summary did not bind the measured corpus"
  hygiene_record_binds_benchmark "$BASE_HYG" "$BENCHMARK_SHA" \
    || die "base hygiene summary did not bind the measured corpus"
  HYG_ARGS=(--base-hygiene "$BASE_HYG" --candidate-hygiene "$CAND_HYG"
            --base-hygiene-host "$THIS_HOST"
            --candidate-hygiene-host "$THIS_HOST")
  BASE_LAND_ARG=(--base-land-log "$RUN/base_land.log")
  if base_has_exact_legacy_routed_empty "$BASE_HYG"; then
    build_trusted_transition_evidence
    TRANSITION_ARGS=(--trusted-transition-evidence \
                     "$TRUSTED_TRANSITION_EVIDENCE")
  fi
  echo "--- arm A1/B1: base rc=$A1_RC candidate rc=$B1_RC (hermetic aggregate)"
  echo "--- arm A2/B2: base rc=$A2_RC candidate rc=$B2_RC (hermetic gates)"

else
  echo "--- the tree under test is not the tree that would be merged; the suites were NOT run"
fi

# --------------------------------------------------------------- 7. the verdict
[ -f "$VERDICT_PROG" ] || die "no verdict program at $VERDICT_PROG"
python3 "$VERDICT_PROG" \
  --base-sha "$BASE_SHA" --base-tree "$BASE_TREE" --head-sha "$HEAD_SHA" \
  --verified-sha "$VERIFIED_SHA" --rebase-status "$REBASE_STATUS" \
  --expected-tree "$EXPECTED_TREE" --verified-tree "$VERIFIED_TREE" \
  --replayed-tree "$REBASED_TREE" --github-tree "$GITHUB_TREE" \
  --land-log "$RUN/land.log" --selection "$RUN/selection.txt" \
  --base-selection "$RUN/selection_base.txt" \
  "${BASE_LAND_ARG[@]+"${BASE_LAND_ARG[@]}"}" \
  --base-junit "$BASE_JUNIT" --candidate-junit "$CAND_JUNIT" \
  "${HYG_ARGS[@]+"${HYG_ARGS[@]}"}" \
  "${TRANSITION_ARGS[@]+"${TRANSITION_ARGS[@]}"}" \
  "${PROTECTED_ARGS[@]+"${PROTECTED_ARGS[@]}"}" \
  --candidate-gate-rc "$B2_RC" --require-composite-gate-record \
  --candidate-test-worktree-status "$B1_WORKTREE_STATUS" \
  --base-test-worktree-status "$A1_WORKTREE_STATUS" \
  --verification-tier "$TIER" --git-version "$GIT_VERSION" \
  --merge-tree-min-version "$MERGE_TREE_MIN_VERSION" \
  ${TIER_REASON:+--tier-reason "$TIER_REASON"} \
  ${JSON_OUT:+--json "$JSON_OUT"} \
  "${GATE_ARGS[@]+"${GATE_ARGS[@]}"}"
RC=$?

if [ "$RC" -eq 0 ]; then
  echo "=== LAND OK — verified the squash of ${HEAD_SHA:0:12} onto ${BASE_SHA:0:12}"
  echo "               commit ${VERIFIED_SHA:0:12} (local stand-in)  tree ${VERIFIED_TREE:0:12} (what lands)"
  echo "               tier ${TIER}$( [ "$TIER" = "merge-tree" ] || echo "  (DEGRADED — squash-vs-rebase cross-check NOT performed)" )"
else
  echo "=== REFUSED (rc=$RC) — do NOT run \`gh pr merge\`; the reasons are above"
fi
exit "$RC"
