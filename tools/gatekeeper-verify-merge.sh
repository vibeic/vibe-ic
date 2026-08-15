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
#   5. run the targeted suite on the BASE (arm A) and `gatekeeper-land.sh` on the
#      squash commit (arm B), each with its own junit report — AND hand the
#      verdict the list arm A was ASKED to run (`--base-selection`), so a base
#      arm that did not finish is caught instead of being subtracted as though
#      it had (vibe-ic#1443: a partial base arm hides `silenced`, which is the
#      permissive direction);
#   6. hand every fact to `landing_merge_verdict.py`, which owns the refusal
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
#   the VERDICT        THIS repo's copy of `landing_merge_verdict.py`, never the
#                      candidate's. The judge may not be supplied by the subject
#                      — the same rule §4.05 states for an oracle. A PR can
#                      change what its gates check; it cannot change what
#                      counts as a refusal.
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
# The verdict is about a BASE. If `origin/main` moves before the merge, the
# verdict is stale — `--reassert` says so rather than letting a stale pass land.
#
# Usage:
#   gatekeeper-verify-merge.sh <pr-number> [options]
#   gatekeeper-verify-merge.sh --ref <ref> [options]
#   gatekeeper-verify-merge.sh --reassert <verdict.json>
#
# Options:
#   --base <ref>        base the PR would land on          (default origin/main)
#   --repo <path>       repository to operate on   (default: this script's repo)
#   --json <path>       write the verdict JSON
#   --no-fetch          do not touch the network (local refs must already exist)
#   --require-version-bump
#                       demand the version bump in the PR itself. OFF by
#                       default because authoring PRs are VERSION-LESS by
#                       doctrine — the gatekeeper assigns the version AT MERGE —
#                       so demanding it here would refuse every conformant PR.
#                       A BACKWARDS version is refused either way.
#   --keep              keep the run directory and the worktrees for inspection
#   --base-gate-cache <dir>
#                       reuse arm A2's gate log for a base already measured.
#                       CONTENT-ADDRESSED by the base commit: the file is named
#                       after the base SHA, so the same tree yields the same
#                       gates and a cache hit cannot be stale. In a serialized
#                       merge queue the base only moves once per landing, so
#                       every verification after the first on a given base skips
#                       one whole gate run. Measured on this host: one hygiene
#                       pass is 19 min uncontended.
set -uo pipefail

PR=""; REF=""; BASE="origin/main"; JSON_OUT=""; REASSERT=""
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

die() { printf 'gatekeeper-verify-merge: %s\n' "$*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --ref)      REF="${2:?}"; shift 2 ;;
    --base)     BASE="${2:?}"; shift 2 ;;
    --repo)     REPO="${2:?}"; shift 2 ;;
    --json)     JSON_OUT="${2:?}"; shift 2 ;;
    --reassert) REASSERT="${2:?}"; shift 2 ;;
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

SELF_REPO="$(git -C "$SELF" rev-parse --show-toplevel 2>/dev/null)"
[ -z "$REPO" ] && REPO="$SELF_REPO"
[ -n "$REPO" ] || die "no repository (pass --repo)"
REPO="$(cd "$REPO" && pwd)"
G=(git -C "$REPO")

# ---------------------------------------------------------------- --reassert
# A verdict is about a BASE and a HEAD. Between the verify and the merge, other
# agents land PRs; if either moved, the pass describes a tree nobody is about to
# create. This is the time dimension of "verified the wrong tree", and it is the
# cheap half — no worktree, no tests, just two `rev-parse`s.
if [ -n "$REASSERT" ]; then
  [ -f "$REASSERT" ] || die "--reassert: no such file: $REASSERT"
  read -r WAS_BASE WAS_HEAD WAS_VERDICT < <(python3 - "$REASSERT" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
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
  echo "REASSERT: OK — $BASE is still ${WAS_BASE:0:12}, head still ${WAS_HEAD:0:12}"
  exit 0
fi

[ -n "$PR" ] || [ -n "$REF" ] || die "give a PR number or --ref <ref>"
[ -n "$PR" ] && [ -n "$REF" ] && die "give a PR number OR --ref, not both"

LAND="$REPO/tools/gatekeeper-land.sh"
[ -x "$LAND" ] || [ -f "$LAND" ] || die "no landing script at $LAND"

RUN="$(mktemp -d -t gkverify.XXXXXX)"
WT_CAND="$RUN/candidate"
WT_BASE="$RUN/base"
# PER-RUN ref names. Two verifications of two different PRs may legitimately be
# in flight at once (the merge queue is serialized; a gatekeeper reading ahead is
# not), and a fixed `refs/gk-verify/head` would have had each run fetching over
# the other's head. The run directory's basename is already unique.
RUN_ID="$(basename "$RUN")"
HEAD_REF="refs/gk-verify/$RUN_ID/head"
MERGE_REF="refs/gk-verify/$RUN_ID/merge"

cleanup() {
  if [ "$KEEP" = "1" ]; then
    echo "--- kept: $RUN (worktrees included)"
    return
  fi
  "${G[@]}" worktree remove --force "$WT_CAND" >/dev/null 2>&1
  "${G[@]}" worktree remove --force "$WT_BASE" >/dev/null 2>&1
  "${G[@]}" update-ref -d "$HEAD_REF"  >/dev/null 2>&1
  "${G[@]}" update-ref -d "$MERGE_REF" >/dev/null 2>&1
  rm -rf "$RUN"
}
trap cleanup EXIT

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

# ------------------------- 2. CAN THIS HOST COMPUTE THE MERGE TREE AT ALL?
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

# ------------------------------------------- 3. rebase in a throwaway worktree
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

# ------------------------------- 4. THE SQUASH COMMIT — what actually lands
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
# THE JUDGE COMES FROM THIS REPO, NOT FROM THE SUBJECT (see the header). The
# candidate's copy is the fallback only when this script was handed a `--repo`
# that is not its own tree.
VERDICT_PROG="$SELF_REPO/$PLUGIN_REL/programs/landing_merge_verdict.py"
[ -f "$VERDICT_PROG" ] || VERDICT_PROG="$CAND_PLUGIN/programs/landing_merge_verdict.py"
: > "$RUN/selection.txt"
# Created HERE, not only inside the `SHORT_CIRCUIT=0` branch, so the verdict is
# always handed a file it can read. An absent file and an empty one both mean
# "the base arm was asked for nothing", which the verdict reports as a
# not-checked disclosure rather than as a clean base arm (vibe-ic#1443).
: > "$RUN/selection_base.txt"
: > "$RUN/land.log"
CAND_JUNIT="$RUN/candidate.xml"
BASE_JUNIT="$RUN/base.xml"
BASE_LAND_ARG=()
# vibe-ic#1498 — the two arms' hygiene RECORDS, so the gate differential can ask
# the hygiene tier which findings this branch INTRODUCED rather than only
# whether its one label failed. Both arms already run `gatekeeper-land.sh`; all
# that is added is that each writes its `--summary-json` record where the
# verdict can read it. Left EMPTY when either arm did not produce one, which the
# verdict discloses and treats as the coarse per-label comparison it does today.
BASE_HYG="$RUN/base_hygiene.json"
CAND_HYG="$RUN/candidate_hygiene.json"
HYG_ARGS=()
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
            tools/ci/repo_hygiene_gates.sh tools/git-hooks/pre-push \
            "$PLUGIN_REL/programs/landing_merge_verdict.py" \
            "$PLUGIN_REL/programs/ci_targeted_test_select.py" 2>/dev/null)

if [ "$SHORT_CIRCUIT" = "0" ]; then
  # ------------------------------------------------ 5a. the selection, ONCE
  ( cd "$CAND_PLUGIN" && python3 programs/ci_targeted_test_select.py \
      --base "$BASE_SHA" ) > "$RUN/selection.txt" 2>"$RUN/selection.err"
  if [ ! -s "$RUN/selection.txt" ]; then
    echo "--- the targeted selection produced no file; that is not a clean result:"
    tail -5 "$RUN/selection.err" | sed 's/^/      /'
  fi

  # ------------------------- 5b. ARM A — the same tests on the UNTOUCHED base
  # Only files that EXIST at the base: a test the PR adds cannot have an opinion
  # there, and its absence is a real outcome the verdict reads as ABSENT.
  "${G[@]}" worktree add -q --detach "$WT_BASE" "$BASE_SHA" \
    || die "cannot create the base worktree"
  BASE_PLUGIN="$WT_BASE/$PLUGIN_REL"
  : > "$RUN/selection_base.txt"
  while read -r f; do
    [ -n "$f" ] && [ -f "$BASE_PLUGIN/$f" ] && printf '%s\n' "$f" >> "$RUN/selection_base.txt"
  done < "$RUN/selection.txt"
  if [ -s "$RUN/selection_base.txt" ]; then
    # NO `--maxfail` here on purpose: arm A must produce the COMPLETE pre-existing
    # failed set, and a truncated base makes a new failure look pre-existing.
    #
    ( cd "$BASE_PLUGIN" && xargs -a "$RUN/selection_base.txt" \
        python3 -m pytest -q --timeout=180 --timeout-method=thread \
        -p no:cacheprovider -o junit_family=xunit1 "--junitxml=$BASE_JUNIT" ) \
        > "$RUN/base_tests.log" 2>&1
    echo "--- arm A1 (base ${BASE_SHA:0:12}): $(tail -1 "$RUN/base_tests.log")"
  else
    echo "--- arm A1: no selected file exists at the base — the differential will demand green"
  fi
  # A MEASUREMENT'S SIDE EFFECTS MUST NOT BECOME THE NEXT MEASUREMENT'S INPUT.
  # Arm A1 is a pytest run over the shipped tree, and at least one test in this
  # repo's own suite has been observed writing into it; leaving that behind would
  # make arm A2 report a dirty base worktree that arm A1 dirtied.
  git -C "$WT_BASE" checkout -q -- . 2>/dev/null

  # ------------- 5c. ARM A2 — the SAME landing gates on the UNTOUCHED base
  # Two of the repo-hygiene gates are red on `main` as measured 2026-08-12, so
  # "any gate FAIL refuses" would be a ban. The gate tier gets the same
  # differential the test tier gets, which needs the base's own verdicts.
  # `GATEKEEPER_BASE=$BASE_SHA` in a worktree AT `$BASE_SHA` makes the range
  # EMPTY on purpose: the range-scoped gates then SKIP (a failure there is always
  # the PR's, never pre-existing) and the WHOLE-TREE gates — the ones that can be
  # pre-existing red — still run.
  A2_PID=""
  CACHED=""
  CACHED_HYG=""
  CACHED_HYG_HOST=""
  if [ -n "$BASE_GATE_CACHE" ]; then
    mkdir -p "$BASE_GATE_CACHE"
    CACHED="$BASE_GATE_CACHE/$BASE_SHA.land.log"
    # vibe-ic#1498 — cached ALONGSIDE the log and keyed the same way, because a
    # hit skips arm A2 entirely and the finding differential would otherwise
    # have no base record exactly in the mode the merge queue runs in. The host
    # travels WITH the record: findings are host-dependent, and a cache
    # directory on shared storage could otherwise hand one host's baseline to
    # another's candidate.
    CACHED_HYG="$BASE_GATE_CACHE/$BASE_SHA.hygiene.json"
    CACHED_HYG_HOST="$BASE_GATE_CACHE/$BASE_SHA.hygiene.host"
  fi
  # A CACHE HIT MUST BE THE SAME QUESTION, not a similar one. The key is the base
  # COMMIT, so a hit is by construction about the identical tree; a base that
  # moved has a different name and misses.
  if [ -n "$CACHED" ] && [ -s "$CACHED" ]; then
    cp "$CACHED" "$RUN/base_land.log"
    echo "--- arm A2: reused the gate log measured for base ${BASE_SHA:0:12}"
    # The two halves are cached independently, so a cache written before this
    # change has the log and not the record. That is a MISSING baseline, which
    # the verdict discloses and degrades from — never a silently empty one.
    if [ -s "$CACHED_HYG" ] && [ -s "$CACHED_HYG_HOST" ]; then
      cp "$CACHED_HYG" "$BASE_HYG"
      BASE_HYG_HOST="$(cat "$CACHED_HYG_HOST")"
    else
      echo "--- arm A2: the cache carries no hygiene record for this base, so the"
      echo "            hygiene tier falls back to the per-LABEL comparison"
    fi
  else
    ( cd "$WT_BASE" && \
        GATEKEEPER_BASE="$BASE_SHA" \
        GATEKEEPER_VERSION_BY_GATEKEEPER=1 \
        GATEKEEPER_HYGIENE_REPORT="$BASE_HYG" \
        bash tools/gatekeeper-land.sh ) > "$RUN/base_land.log" 2>&1 &
    A2_PID=$!
  fi

  # -------------------- 5c. ARM B — the real landing gates on the real tree
  # `gatekeeper-land.sh` is INVOKED, not re-listed, so a gate added to it is
  # covered here with no edit to this file. `GATEKEEPER_PYTEST_JUNIT` makes its
  # targeted run emit a report; it changes no verdict of its own.
  #
  # `GATEKEEPER_VERSION_BY_GATEKEEPER` is the documented VERSION-LESS PR path
  # (the same deferral `pre-push` already applies off-main): the gatekeeper
  # assigns the version AT MERGE, so demanding it in the PR would refuse every
  # conformant PR. A BACKWARDS version is still refused.
  VBG=1
  [ "$REQUIRE_VERSION_BUMP" = "1" ] && VBG=0
  if ! grep -q GATEKEEPER_PYTEST_JUNIT "$WT_CAND/tools/gatekeeper-land.sh" 2>/dev/null; then
    echo "--- note: this tree's gatekeeper-land.sh predates GATEKEEPER_PYTEST_JUNIT, so"
    echo "          it cannot report per-test outcomes and the differential will refuse."
    echo "          Rebase the branch onto a base that carries the merge-path gate."
  fi
  ( cd "$WT_CAND" && \
      GATEKEEPER_BASE="$BASE_SHA" \
      GATEKEEPER_PYTEST_JUNIT="$CAND_JUNIT" \
      GATEKEEPER_PYTEST_MAXFAIL=0 \
      GATEKEEPER_VERSION_BY_GATEKEEPER="$VBG" \
      bash tools/gatekeeper-land.sh ) > "$RUN/land.log" 2>&1
  echo "--- arm B (squash ${VERIFIED_SHA:0:12}): gatekeeper-land.sh rc=$?"
  sed -n 's/^  \(PASS\|FAIL\|SKIP\|REPORT\)  /      \1  /p' "$RUN/land.log"
  [ -n "${A2_PID:-}" ] && wait "$A2_PID" 2>/dev/null
  # Written only after a REAL measurement, and only if it named some gate — an
  # empty or truncated log cached would answer every later verification with
  # "the base fails nothing", which is the permissive direction.
  if [ -n "$CACHED" ] && [ ! -s "$CACHED" ] \
     && grep -q '^=== gatekeeper landing gates' "$RUN/base_land.log"; then
    cp "$RUN/base_land.log" "$CACHED"
  fi
  echo "--- arm A2 (base ${BASE_SHA:0:12}): $(grep -c '^  FAIL  ' "$RUN/base_land.log" || true) gate(s) already failing on the base"
  sed -n 's/^  FAIL  /      base-FAIL  /p' "$RUN/base_land.log"
  BASE_LAND_ARG=(--base-land-log "$RUN/base_land.log")
else
  echo "--- the tree under test is not the tree that would be merged; the suites were NOT run"
fi

# --------------------------------------------------------------- 6. the verdict
[ -f "$VERDICT_PROG" ] || die "no verdict program at $VERDICT_PROG"
python3 "$VERDICT_PROG" \
  --base-sha "$BASE_SHA" --head-sha "$HEAD_SHA" \
  --verified-sha "$VERIFIED_SHA" --rebase-status "$REBASE_STATUS" \
  --expected-tree "$EXPECTED_TREE" --verified-tree "$VERIFIED_TREE" \
  --replayed-tree "$REBASED_TREE" --github-tree "$GITHUB_TREE" \
  --land-log "$RUN/land.log" --selection "$RUN/selection.txt" \
  --base-selection "$RUN/selection_base.txt" \
  "${BASE_LAND_ARG[@]+"${BASE_LAND_ARG[@]}"}" \
  --base-junit "$BASE_JUNIT" --candidate-junit "$CAND_JUNIT" \
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
