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
# Usage:  tools/gatekeeper-land.sh [--cheap-only] [--prepare]
#
# --prepare (vibe-ic#1129) — do the MECHANICAL things this script would
# otherwise refuse a batch for, before the cheap tier runs, and let the gates
# refuse only what is left:
#
#     version_bump_monotonic_check    the version was not bumped
#     landing_is_one_commit          no [vX.Y.Z]-tagged commit on the tip
#     test_programs_index_freshness  programs/INDEX.md is stale
#     63x8 census freshness          the derived figures are stale (#1382)
#
# None of those is a judgement, each already has a program that owns it, and a
# refusal for one of them costs an hour of gate wall-clock while saying nothing
# about the code under test. OFF BY DEFAULT: it rewrites the tip commit, which
# is the operator's call, not a side effect of asking for a verdict.
#
# The census line is the LAND-TIME DERIVATION POINT (vibe-ic#1382). That gate
# blocked eleven of thirteen finished batches on 2026-08-13 and not one of those
# was a defect in a PR it stopped — every figure was off by exactly one, one gate
# added by one PR with the derived figures never re-derived. Re-deriving here
# does not silence it: `repo_hygiene_gates.sh` still runs the generator's own
# `--check` afterwards, on the tree this step produced. Alone among the steps
# above it is BEST EFFORT — its generator can fail on a loaded host for reasons
# no re-derivation reaches (#1277), and a fatal step would refuse every landing.
#
# The preparation is delegated to `gatekeeper_prepare_landing.py`, which REFUSES
# if anything outside the set its writers declared is dirty — the gate must not
# become a path for editing its own subject (#1029, #1089). If preparation
# refuses, this script stops: a landing whose preparation could not be
# attributed is not a landing worth an hour.
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel)"
PROGRAMS="$ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs"
PLUGIN="$ROOT/vibe-ic-marketplace/plugins/vibe-ic"
PJSON="$PLUGIN/.claude-plugin/plugin.json"
BASE="${GATEKEEPER_BASE:-origin/main}"
RANGE="${BASE}..HEAD"
CHEAP_ONLY=0
PREPARE=0
for _arg in "$@"; do
  case "$_arg" in
    --cheap-only) CHEAP_ONLY=1 ;;
    --prepare)    PREPARE=1 ;;
    *) echo "gatekeeper-land: unknown argument '$_arg'" >&2; exit 2 ;;
  esac
done

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

# vibe-ic#1129 — the mechanical repairs, BEFORE anything measures them. A gate
# that refuses for a reason a program can fix spends an hour saying so.
if [ "$PREPARE" = "1" ]; then
  echo "--- prepare (vibe-ic#1129: the mechanical three, then get out of the way) ---"
  if python3 "$PROGRAMS/gatekeeper_prepare_landing.py" --repo "$ROOT" --commit; then
    :
  else
    echo "  FAIL  preparation REFUSED — see above. Not proceeding: a landing whose"
    echo "        preparation could not be attributed is not one worth an hour."
    exit 1
  fi
fi

echo "--- cheap tier (also enforced by the pre-push hook) ---"

# An empty range means nothing new is being landed; the NDA checkers correctly
# refuse an empty scan, so the no-op is skipped rather than reported as a pass.
if [ "$(git rev-list --count "$RANGE" 2>/dev/null || echo 0)" != "0" ]; then
  run "NDA — commit messages"   python3 "$PROGRAMS/commit_msg_nda_check.py" --repo "$ROOT" --rev-range "$RANGE"
  run "NDA — added content/paths" python3 "$PROGRAMS/nda_diff_scan_check.py" --rev-range "$RANGE"
  # `GATEKEEPER_VERSION_BY_GATEKEEPER=1` — the VERSION-LESS authoring-PR path,
  # for `tools/gatekeeper-verify-merge.sh` (vibe-ic#1019). The version is
  # assigned AT MERGE by the gatekeeper, so a PR under verification legitimately
  # carries no bump and demanding one here would refuse every conformant PR —
  # the same deferral `tools/git-hooks/pre-push` already applies off-main, using
  # the same flag the program already ships. A BACKWARDS version is still
  # refused in both directions, so this defers the gate and does not disable it.
  # Unset (the push path) is unchanged: current == previous still FAILs.
  if [ "${GATEKEEPER_VERSION_BY_GATEKEEPER:-0}" = "1" ]; then
    run "version monotonic (assigned at merge — deferred)" python3 "$PROGRAMS/version_bump_monotonic_check.py" --plugin-json "$PJSON" --base "$BASE" --version-by-gatekeeper
  else
    run "version bumped monotonically" python3 "$PROGRAMS/version_bump_monotonic_check.py" --plugin-json "$PJSON" --base "$BASE"
  fi
  run "agent check-in scope"    python3 "$PROGRAMS/agent_checkin_scope_guard.py" --role core-agent --base "$BASE"
  # `--corpus-may-be-absent`: the published corpus lives in vibeic/benchmark-data,
  # so THIS repo legitimately has no `benchmark-data/`. Without the flag the gate
  # correctly reports UNDETERMINED and blocks every push — a gate that refuses
  # every landing is the ban this repo already learned to distrust.
  #
  # It is NOT a licence. With VIBE_IC_BENCHMARK_DATA pointing at a clone the gate
  # scans it and can still fail; with the pointer set and broken it is still
  # UNDETERMINED, flag or no flag. The flag only names the one case it was written
  # for: nothing configured, nothing local, nothing claimed.
  run "benchmark evidence structure" python3 "$PROGRAMS/benchmark_evidence_structure_check.py" --tree benchmark-data --corpus-may-be-absent --changed-since "$BASE"
  # vibe-ic#635 — a NEW published number must arrive with its composition.
  # Scoped `--changed-since` like the gate above: 20 of the 25 runs already
  # published carry no per-problem name set, and applying this retroactively
  # would fail every landing over work nobody is doing.
  run "benchmark run manifest" python3 "$PROGRAMS/benchmark_run_manifest.py" check --tree benchmark-data --changed-since "$BASE"
  # PER-RUN, not a fixed name. `tools/gatekeeper-verify-merge.sh` (vibe-ic#1019)
  # runs this script for the BASE and for the CANDIDATE at the same time — two
  # arms of one differential — and a shared `/tmp/gk_*.txt` would have had each
  # arm reading the other's range. A gate that silently answers about the wrong
  # tree is the defect this whole file exists to stop.
  MSGFILE="$(mktemp -t gk_commit_text.XXXXXX)"
  git log --format='%B' "$RANGE" > "$MSGFILE" 2>/dev/null
  run "git prohibition guard"   python3 "$PROGRAMS/git_prohibition_guard.py" "$MSGFILE"
  rm -f "$MSGFILE"
  # 2026-08-03 — the batch that landed five PRs from a 6.5-hour-stale base and
  # let three of its own commits erase the other two. `gatekeeper_stale_branch_check`
  # said STALE_OVERLAP on all five BEFORE the land; nothing looked at the
  # commits AFTER they existed, which is the artefact this script pushes.
  run "no collateral revert within the push" \
      python3 "$PROGRAMS/landing_collateral_revert_check.py" --repo "$ROOT" --rev-range "$RANGE"
  # 2026-08-05 — THE OTHER HALF OF THE SAME QUESTION, and the half nothing here
  # was asking. The gate above reads the commits INSIDE this push; this reads
  # whether the tree being pushed actually contains the base it names as its
  # parent.
  #
  # `1766746f6` named origin/main (v1.9.78) as its parent and carried v1.9.77's
  # tree: 81 files, 9258 deletions, 13 commits reverted, 15 files deleted. It
  # passed every shape check here — one commit ahead of the base, no in-range
  # predecessor to revert, and `gatekeeper_stale_branch_check` itself said FRESH,
  # because the head really does descend from the tip. Only a human read caught
  # it, an hour before it would have landed.
  #
  # The checker was already blocking in `gatekeeper_review`; it had never been
  # wired HERE, which is the script that writes the stamp the pre-push hook
  # demands — so the landing path had no opinion on the landing method at all.
  run "tree contains the base it claims as parent" \
      python3 "$PROGRAMS/gatekeeper_stale_branch_check.py" --repo "$ROOT" \
          --base "$BASE" --head HEAD
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
#
# AN EMPTY RANGE IS NOT A LANDING, so it is not a landing of one commit either.
# Asked over `X..X` the checker sees ZERO commits and answers FAIL — a vacuous
# refusal, and one with teeth beyond this line: `gatekeeper-verify-merge.sh`
# (vibe-ic#1019) runs this script over an empty range on the BASE to learn which
# gates are ALREADY failing, and a gate that fails vacuously there would let a
# candidate's REAL one-commit violation be waived as pre-existing. Range-scoped
# gates must SKIP over an empty range, exactly as the block above already does.
GK_RANGE_N="$(git rev-list --count "$RANGE" 2>/dev/null || echo 0)"
if [ "$GK_RANGE_N" = "0" ]; then
  echo "  SKIP  landing shape — range is empty, so there is no landing to shape"
elif [ "$GK_RANGE_N" -gt 1 ]; then
  run "landing is a valid batch (version on tip)" \
      python3 "$PROGRAMS/landing_is_one_commit_check.py" --base "$BASE" --batch
else
  run "landing is one commit" \
      python3 "$PROGRAMS/landing_is_one_commit_check.py" --base "$BASE"
fi

# The gate above asks whether the batch has a legal SHAPE. This asks what it
# CONTAINS: does more than one member of this landing claim the same issue?
#
# vibe-ic#1411 — the only mechanism this repo has for noticing two changes doing
# one job is a MERGE CONFLICT, and of the 22 issues carrying more than one open
# PR, 16 had members sharing no file, so nothing reported them. #1080 is the
# confirmed instance: two PRs shipped two metric schemas for one issue, each
# with its own passing tests, and the pair was found by accident.
#
# `competing_pr_claim_groups.py` (#1413) computes that. Until this line it was
# reachable from nowhere — measured on its own branch, the only references to it
# outside itself were `INDEX.md`, which is a generated catalog and not a caller,
# and its own test. A report nothing runs produces no report.
#
# THE `--rev-range` MODE, not the API mode: this script must work offline —
# `gatekeeper-verify-merge.sh` runs it twice, for the base and for the
# candidate, as one differential — and a report that can only ask GitHub is a
# report the landing path cannot use.
#
# REPORT, not a gate, and the reason is measured rather than cautious: several
# of those 16 are legitimate splits verified by hand (#1241 has nineteen rows,
# #1097 names three distinct mechanisms, #1115's pair repairs different
# channels). A bar that refuses all of them is red every day, and a bar that is
# red every day is the one people learn to bypass. What this asserts is only
# that nobody has looked yet.
if [ "$GK_RANGE_N" = "0" ]; then
  echo "  SKIP  competing claims — range is empty, so there is nothing claimed"
else
  report "issues claimed by more than one commit in this landing" \
      python3 "$PROGRAMS/competing_pr_claim_groups.py" \
          --repo-root "$ROOT" --rev-range "$RANGE"
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

# vibe-ic#1029 — the full tier is the window in which the gates read the tree,
# and it is the window in which they have three times been caught WRITING to
# it. `landing_worktree_is_clean_check --expect-fingerprint` at the end of this
# tier already refuses the stamp when a TRACKED file moved; what it does not do
# is name what moved, or see the untracked (`??`) half that `git add -A` would
# sweep just the same.
#
# This baseline pairs with the compare below to answer, by name, "did the full
# tier write into the tree". It is deliberately taken around the WHOLE tier
# rather than around pytest alone: `repo_hygiene_gates.sh` and
# `plugin_full_audit.py` run INSIDE this window but OUTSIDE the pytest command,
# so the in-process pytest guard (programs/suite_write_guard.py, loaded by the
# plugin's rootdir conftest) cannot see them. That gap is exactly the stage
# whose family this repo already caught rewriting 77 tracked files.
WG_BASE="$(mktemp -t gk_writeguard.XXXXXX)"
trap 'rm -f "$FP" "$WG_BASE"' EXIT
run "write-guard baseline" \
    python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" --snapshot "$WG_BASE"

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
#
# `GATEKEEPER_PYTEST_JUNIT=<path>` additionally writes a junit report for this
# run. It changes NO verdict here — the `if out=…` below still decides — and
# exists because `gatekeeper-verify-merge.sh` (vibe-ic#1019) compares the
# candidate's failed SET against the base's. Without a report it would have to
# run the same suite a second time, and a landing gate slow enough to be
# bypassed is a bypassed gate. `xunit1` is asked for because it is the family
# that carries the `file` attribute, so a selected file that produced no test
# case at all can be told from a clean one.
#
# `GATEKEEPER_PYTEST_MAXFAIL=<n>` overrides `--maxfail`; `0` removes the bound.
# `10` stays the default and the push path is unchanged — stopping early is right
# when the answer is "this is red, go fix it". It is WRONG for a differential:
# `gatekeeper-verify-merge.sh` compares the candidate's failed SET against the
# base's, and a truncated run has no failed set, only a prefix of one. Measured
# on PR #1028 (137 selected files, 3242 tests at the base): `--maxfail=10`
# stopped the candidate at 1437 tests, which the verdict correctly refused as
# unmeasurable. A landing gate that cannot answer for a wide PR is a landing gate
# nobody uses.
# `-m "not audit_63x9"` — THE LANDING GATE ANSWERS ONE QUESTION AND IT IS NOT THIS
# ONE. A landing asks "did this change break something that used to work". The
# 63x9 audit asks "is the published audit of our 63 flow steps x 9 dimensions
# still honest" — it grades a PUBLISHED ARTEFACT against a corpus, and a landing
# tree carries no corpus (benchmark-data left this repo in v1.10.56). So here
# those tests cannot audit anything; they are VOID, not slow, and their permanent
# red refused landings that broke nothing.
#
# MEASURED in a corpus-less tree, both directions, because either half alone
# proves nothing (mark everything and the first passes; mark nothing and the
# second does):
#     -m audit_63x9        -> 12 failed, 35 deselected   (exactly the corpus-dependent set)
#     -m "not audit_63x9"  ->  0 failed, 35 passed, rc=0 (the same three files, green)
# 12 + 35 = 47 = every test in those files, so the partition is exact.
#
# THIS SAVES NO TIME AND IS NOT MEANT TO. The 12 assertions cost 0.13 s together;
# the 247 s their arm takes is collection and import, which the landing pays
# anyway for the 35 that stay. What it buys is that the landing stops being
# refused by a question a landing tree cannot answer.
# The audit still runs, where the corpus is: tools/ci/audit_63x9.sh
# ── WHY THIS ARM IS NOT xdist, MEASURED RATHER THAN ASSUMED ─────────────────
# 31 of 32 cores are idle during a round (load 3.3, exactly ONE process above 20%%
# CPU, for 2083 cases), and pytest-xdist 3.8.0 is installed. So it was tried, at
# `-n 12 --dist loadfile`, on both arms. The round came back
# `RED TOTAL: 0` and `produced no complete record` -- every selected file NORECORD
# with `pytest progress protocol incomplete: schema/nonce/pid mismatch`.
#
# THE PROTOCOL IS SINGLE-PROCESS BY CONSTRUCTION, and two of its clauses say so:
#   pytest_per_file_junit.py:330  record["pid"] != pid   -> xdist workers are
#                                 children, so every event carries the wrong pid
#   pytest_per_file_junit.py:335  seq != self.seq + 1    -> a strictly monotonic
#                                 sequence, which N concurrent workers interleave
# That triple (schema, nonce, pid, seq) is what stops a stale or foreign event
# being counted as progress. It is not a flag to relax; relaxing it wrongly would
# let a dead run's events look alive. So the gate REFUSED, correctly, and the
# refusal is the finding: xdist is incompatible with this driver as written.
#
# THE PARALLELISM THIS REPO ALREADY OWNS IS THE ANSWER, and it is protocol-correct
# by design: `--fallback-jobs` runs N independent supervisor processes, each with
# its OWN progress protocol instance. It is wired only as post-NORECORD recovery
# (`--aggregate-check` runs one process first), so it fires in zero healthy rounds.
# Making it the primary path is a change to the driver, not a flag on this line,
# and it is not folded in here as if it were one.

run_pytest() {
  local sel out rc
  TARGETED_NORECORD=0
  # PREFLIGHT (vibe-ic#1446): the scratch root this pytest will use is part of
  # its verdict. A root inside a git work tree makes 46 tests report failures
  # that are the ROOT, not the tree — and each names its own subject rather
  # than the cause, so a landing can spend an hour producing a red that says
  # nothing true about the branch. The in-process guard (conftest.py loads
  # programs/scratch_root_guard.py through pytest_plugins, exactly as it loads
  # suite_write_guard) refuses too, but only once pytest is already starting —
  # after the selection below has been built. Asked here it costs milliseconds
  # and is answered before anything else runs.
  if ! out="$( cd "$PLUGIN" && python3 programs/scratch_root_guard.py 2>&1 )"; then
    echo "  FAIL  the scratch root would falsify this run"
    printf '%s\n' "$out" | sed 's/^/          /'
    FAILED=1; return
  fi
  # PER-RUN: see the MSGFILE note above. Two concurrent arms sharing one
  # selection file would each run the other's test list.
  sel="$(mktemp -t gk_sel.XXXXXX)"
  local maxfail=(--maxfail="${GATEKEEPER_PYTEST_MAXFAIL:-10}")
  [ "${GATEKEEPER_PYTEST_MAXFAIL:-10}" = "0" ] && maxfail=()
  # THE MERGED REPORT IS ALWAYS PRODUCED, even when nobody asked for it
  # (vibe-ic#1654). The per-file driver below needs somewhere to merge to, and
  # the run that does NOT export a junit is the same run in every other
  # respect — measuring it differently is the asymmetry #1417 spent a version
  # removing. A temporary target costs nothing and keeps ONE instrument.
  local merged="${GATEKEEPER_PYTEST_JUNIT:-}"
  local merged_tmp=""
  if [ -z "$merged" ]; then
    merged_tmp="$(mktemp -t gk_junit.XXXXXX)"
    merged="$merged_tmp"
  fi
  if [ -n "${GATEKEEPER_PYTEST_JUNIT:-}" ]; then
    # REMOVE THE TARGET FIRST, so a leftover can never be read as THIS run's record.
    #
    # A pytest that TIMES OUT writes no junit at all. Meanwhile
    # programs/tests/test_landing_merge_verdict.py builds a stub gatekeeper-land.sh that
    # honours this same variable and runs it with the inherited environment; its stub
    # selector emits one synthetic file, so it leaves a 1-test report at this exact path.
    #
    # MEASURED twice today. MEGA4: the targeted-tests gate timed out, and the junit left
    # behind was 374 bytes, tests="1", carrying `test_thing::test_value_is_one` — a
    # fixture name, not a real test — for a session of 1368. MEGA was the same shape.
    #
    # The file therefore EXISTED, PARSED, and described a different run. That is worse
    # than a missing file: absence is honest, and this is not. Removing it up front means
    # a timed-out run leaves NO junit, which is the truthful state, and the judge's
    # "refuse when the complete record is absent" rule then applies correctly.
    rm -f "$GATEKEEPER_PYTEST_JUNIT" 2>/dev/null || true
  fi
  ( cd "$PLUGIN" && python3 programs/ci_targeted_test_select.py --base "$BASE" > "$sel" ) 2>/dev/null
  if [ ! -s "$sel" ]; then
    echo "  FAIL  targeted test selection produced no files — not a clean result"
    FAILED=1; rm -f "$sel"; return
  fi
  # THIS SESSION'S ENVIRONMENT IS PART OF THE GATE (vibe-ic#1047, one level up).
  #
  # #1047 fixed the environment of a pytest this suite SPAWNS. The same defect was
  # sitting on the suite the LANDING GATE ITSELF runs, and it was worse, because
  # this is the session whose exit code decides whether a change may be pushed.
  #
  # Bare `python3 -m pytest` autoloads every `pytest11` entry point installed on
  # the host. Measured on the landing host 2026-08-12: of 8 installed entry points
  # exactly one — `web3`'s `pytest_ethereum` — raises at import
  # (`ImportError: cannot import name 'ContractName' from 'eth_typing'`), and it
  # takes the session down AT COLLECTION. Not one test runs. A package this repo
  # does not use, has never imported, and does not ship made the landing gate
  # unrunnable, which is precisely why merges were going around it via
  # `gh pr merge` — the bypass vibe-ic#1019/#1036 is about.
  #
  # So the session declares what it loads instead of inheriting it. The suite needs
  # exactly ONE third-party plugin — `pytest-timeout`, for the `--timeout` flags on
  # this very line — verified by grepping the whole suite for the fixtures and marks
  # of every other installed plugin: requests_mock 0 files, typeguard 0, anyio 0,
  # hydra 0, xdist mentioned only in a README.
  #
  # `suite_write_guard` is UNAFFECTED and must stay that way: conftest.py loads it
  # through `pytest_plugins`, not through an entry point, so disabling autoload does
  # not disarm the write guard. That is the check that would have made this fix a
  # false green, so it is asserted rather than assumed — the guard's PASS/FAIL line
  # must still appear in `out`.
  #
  # ── ONE WHOLE-SELECTION SESSION ON THE LANDING CRITICAL PATH (#1654) ──
  #
  # `--timeout-method=thread` cannot interrupt a blocking `waiter.acquire()`. It
  # dumps every thread's stack and takes the PROCESS down, and a process that
  # dies never writes its `--junitxml`. So ONE hanging file used to cost the
  # WHOLE run's machine-readable record — measured at the #1650 tree with a
  # 91-file selection, where the hang was 1 file and the blast radius was the
  # other 90, on BOTH arms:
  #
  #     ARM_cand_RC=123   ls: cannot access '/tmp/junit_full_cand.xml'
  #     ARM_base_RC=143   ls: cannot access '/tmp/junit_full_base.xml'
  #
  # Reproduced on this tree at 1adbf3444 with three files, one of them hanging
  # in the exact `Future.result -> Condition.wait -> waiter.acquire` shape: the
  # green file that had ALREADY PASSED lost its record too.
  #
  # The first #1654 repair ran N isolated sessions and then repeated the whole
  # selection as an aggregate semantics canary.  That preserved neighbouring
  # records after a hang, but made every successful landing pay for BOTH
  # questions and erased cross-file/order semantics from the first copy.
  #
  # Landing now asks the authoritative question exactly once: the original
  # whole-selection session, supervised by validated pytest lifecycle progress.
  # A complete aggregate JUnit plus its exact OS process verdict is sufficient
  # evidence.  AGGREGATE_NORECORD is an absolute refusal. Only after that
  # refusal does the driver run per-file recovery, preserving every neighbouring
  # record it can and naming the file(s) it cannot measure. Recovery cannot make
  # UNKNOWN land and adds no work to the successful critical path.
  #
  # THE PYTEST COMMAND IS PASSED IN VERBATIM, not built inside the driver, so
  # `--timeout=180` stays declared HERE — `ci_harness_timeout_ceiling_check`
  # resolves the binding harness bound from this file (EXTRA_HARNESS_RELS) and a
  # bound moved into Python would vanish from its view.
  # ── THE BASE ARM STARTS NOW, ALONGSIDE THE CANDIDATE, NOT AFTER IT ──────────
  # The two arms are independent by construction: same selection, two different
  # trees, neither reads the other's output. Running them in sequence made a RED
  # round cost the SUM of two ~31-minute arms; running them together makes it cost
  # the MAX. MEASURED on this host while a round was in flight: load 3.3 on 32
  # cores, exactly ONE process above 20% CPU. Thirty-one cores were idle while the
  # gate took an hour.
  #
  # It is started unconditionally and its result thrown away when the candidate is
  # green. That trade is deliberate and it is cheap in the only currency that
  # matters here -- WALL CLOCK on an idle box -- because a green round no longer
  # waits for it at all.
  _base_sha="$(git -C "$ROOT" merge-base HEAD "${GATEKEEPER_BASE:-origin/main}" 2>/dev/null)"
  _bwt=""; _bjunit=""; _bpid=""
  if [ "${GATEKEEPER_TARGETED_DIFFERENTIAL:-1}" = "1" ] && [ -n "$_base_sha" ]; then
    _bwt="$(mktemp -d -t gk_base.XXXXXX)"; rmdir "$_bwt"
    _bjunit="$(mktemp -t gk_basejunit.XXXXXX)"
    if git -C "$ROOT" worktree add -q --detach "$_bwt" "$_base_sha" 2>/dev/null; then
      # THE SAME SELECTION FILE, not one re-derived at the base: re-deriving would
      # compare two different populations and call the difference a regression.
      # And the SAME `-m` exclusion, or a base that ran the 63x9 audit against a
      # candidate that did not would report every audit test as FIXED.
      ( cd "$_bwt/vibe-ic-marketplace/plugins/vibe-ic" \
        && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 programs/pytest_per_file_junit.py \
             --selection "$sel" --junit "$_bjunit" \
             --stall-after "${GATEKEEPER_PYTEST_FILE_STALL_AFTER:-300}" \
             --parallel-first \
             --fallback-jobs "${GATEKEEPER_PYTEST_FALLBACK_JOBS:-8}" \
             --fallback-rescue-jobs "${GATEKEEPER_PYTEST_RESCUE_JOBS:-32}" \
             -- python3 -m pytest -q -p pytest_timeout -p no:cacheprovider \
             -m "not audit_63x9" \
             --timeout=180 --timeout-method=thread ) >/dev/null 2>&1 &
      _bpid=$!
      printf '        base arm started in parallel at %s (pid %s)\n' \
        "$(echo "$_base_sha" | cut -c1-12)" "$_bpid"
    else
      _bwt=""; rm -f "$_bjunit"; _bjunit=""
    fi
  fi
  if out="$( cd "$PLUGIN" && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 programs/pytest_per_file_junit.py \
        --selection "$sel" --junit "$merged" \
        --stall-after "${GATEKEEPER_PYTEST_FILE_STALL_AFTER:-300}" \
        --parallel-first \
        --fallback-jobs "${GATEKEEPER_PYTEST_FALLBACK_JOBS:-8}" \
        --fallback-rescue-jobs "${GATEKEEPER_PYTEST_RESCUE_JOBS:-32}" \
        --stop-after-failures "${GATEKEEPER_PYTEST_MAXFAIL:-10}" \
        -- python3 -m pytest -q -p pytest_timeout -p no:cacheprovider \
        -m "not audit_63x9" \
        "${maxfail[@]+"${maxfail[@]}"}" --timeout=180 --timeout-method=thread 2>&1 )"; then
    rc=0
    printf '  PASS  targeted tests (%s file(s))\n' "$(wc -l < "$sel")"
    # THE CANDIDATE IS GREEN, SO THE BASE ARM HAS NOTHING TO EXPLAIN. Stop it and
    # take its worktree back. Left running it would burn a core for another half
    # hour and leave a worktree behind that the NEXT round's
    # `landing_worktree_is_clean_check` would blame on that round instead of this
    # one. Killed by the PID we recorded, never by pattern.
    if [ -n "$_bpid" ]; then
      kill -- -"$_bpid" 2>/dev/null || kill "$_bpid" 2>/dev/null
      wait "$_bpid" 2>/dev/null
    fi
    if [ -n "$_bwt" ] && [ -d "$_bwt" ]; then
      git -C "$ROOT" worktree remove --force "$_bwt" 2>/dev/null || rm -rf "$_bwt"
    fi
    [ -n "$_bjunit" ] && rm -f "$_bjunit"
    # PAIRED GUARD for the autoload pin above. A green bought by quietly removing
    # the write guard from the session would be a false green, and it would look
    # exactly like this one. The guard reports on every session it is loaded into,
    # so its absence from the output means it did not run.
    if ! printf '%s\n' "$out" | grep -qa 'suite_write_guard:'; then
      echo "  FAIL  suite_write_guard did not report — the session ran WITHOUT the"
      echo "        write guard, so 'the suite wrote nothing' was never checked."
      FAILED=1
    fi
  else
    rc=$?
    printf '  RED   targeted tests (%s file(s)) — deciding whether it is a REGRESSION\n' "$(wc -l < "$sel")"
    # THE FILES WITH NO RECORD, ALWAYS AND FIRST. They are the one thing a
    # reader cannot reconstruct from the tail of a 91-file run, and `tail -6`
    # would show whichever file happened to be last instead of the one that
    # cost the record.
    printf '%s\n' "$out" | grep -a '^NORECORD\|^NOTRUN\|^AGGREGATE_NORECORD' | sed 's/^/          /'
    # THE RED CASES BY NAME. `tail -6` below CANNOT reach them and never could:
    # the driver's summary block is nine lines, so the tail always lands inside
    # the arithmetic and the failure list scrolls past above it. Measured on a
    # 3-red selection: the reader got `aggregate complete rc=1 cases=93 red=3`
    # and not one of the three names, while the names sat 8 lines further up.
    # No tail depth fixes that — the red count is unbounded — so the names are
    # selected by NAME here, exactly like the NORECORD lines above.
    # THE RED CASES BY NAME. The driver's summary is nine lines, so the
    # `tail -6` below can never reach pytest's failure list -- and MEASURED,
    # the driver emits no `RED` line of its own either, so an earlier grep for
    # one printed nothing and merely moved the reason the names were
    # unreadable. They live in the JUNIT, so the junit is what gets read.
    if [ -s "$merged" ]; then
      python3 "$ROOT/tools/ci/print_junit_reds.py" "$merged" 2>&1 \
        | sed 's/^/          /'
    fi

    # ── THE DIFFERENTIAL: A LANDING IS JUDGED ON WHAT IT BREAKS ──────────────
    # The base arm has been running in parallel since before the candidate started
    # (see the block above run_pytest's own invocation). Here we only WAIT for it.
    #
    # WHY THE RULE (measured 2026-08-18): pre-push refuses any push to main whose
    # commit lacks this gate's stamp, this arm judged ABSOLUTELY, and clean
    # origin/main ITSELF carried red tests -- so nothing could reach main, not even
    # a commit fixing those reds. Five rounds, ~2.5 h of gate wall clock, zero
    # landings. Meanwhile changes DID land through the PR path, which GitHub merges
    # server-side where no local hook runs: the only path that honoured the gate
    # was unusable and the usable path never ran it.
    #
    # NO --maxfail ON THE BASE ARM: a truncated base has no failure SET, only a
    # prefix, so a new failure past the cut would read as pre-existing.
    #
    # WHOLE-TREE GATES ARE UNTOUCHED -- NDA tokens, version monotonicity,
    # collateral revert, corpus writes stay ABSOLUTE.
    if [ -n "$_bpid" ] && [ -s "$merged" ] && [ "$rc" -ne 2 ]; then
      printf '        waiting for the parallel base arm (pid %s)\n' "$_bpid"
      wait "$_bpid" 2>/dev/null
      _dout="$(python3 "$ROOT/tools/ci/targeted_regression_verdict.py" \
                 --candidate "$merged" --base "$_bjunit" 2>&1)"
      _drc=$?
      printf '%s\n' "$_dout" | sed 's/^/        /'
      case "$_drc" in
        0) printf '  PASS  targeted tests — no NEW failure (judged as a regression)\n'
           rc=0 ;;
        1) printf '  FAIL  targeted tests — this change breaks something that worked\n' ;;
        *) printf '  FAIL  targeted tests — differential NOT DETERMINED; refusing\n' ;;
      esac
    elif [ -z "$_bpid" ]; then
      echo "        DIFFERENTIAL NOT RUN: no base arm — refusing on the absolute"
      echo "        verdict, because unknown must not be cheaper than red."
    fi

    # ALWAYS CLEAN UP THE BASE WORKTREE, including the paths that never reached the
    # comparison. A rewrite of this block dropped the cleanup once and it would have
    # leaked one worktree per round -- and `landing_worktree_is_clean_check` would
    # then have blamed the NEXT round for a tree this one left behind.
    if [ -n "$_bwt" ] && [ -d "$_bwt" ]; then
      git -C "$ROOT" worktree remove --force "$_bwt" 2>/dev/null || rm -rf "$_bwt"
    fi
    [ -n "$_bjunit" ] && rm -f "$_bjunit"

    # CONDITIONAL ON rc, because the differential above may have cleared it.
    # This line was unconditional, which would have made the whole regression
    # verdict decorative: it could print PASS and the round would still fail.
    # A verdict nothing acts on is not a verdict.
    if [ "$rc" -ne 0 ]; then
      FAILED=1
      [ "$rc" -eq 2 ] && TARGETED_NORECORD=1
    fi
  fi
  # Human-facing diagnostics only. The merge verdict does NOT trust this mixed
  # driver/subject stdout channel: pytest can print marker-looking text. It
  # derives completeness from exact process suites in the merged JUnit.
  # SEAM: tools/ci/test_landing_parallel_evidence.py executes the block between
  # these sentinels VERBATIM against synthetic evidence, so the planted-defect
  # proof exercises the shipped text and not a copy of it. Keep each sentinel the
  # LAST thing on its line — everything after it is extracted as shell.
  # >>> LANDING_EVIDENCE_CHECK_1 >>>
  # ── CHECK 1: DID THE INSTRUMENT PRODUCE A COMPLETE RECORD OF THE SELECTION? ──
  #
  # WHAT IT READ BEFORE: the `=== pytest junit summary` header. On the
  # aggregate path that header was sufficient, because ONE process answered for
  # the WHOLE selection: if it got far enough to print its summary, the thing it
  # summarised was the entire population by construction.
  #
  # WHY THAT IS NO LONGER EQUIVALENT: on the parallel path the population is
  # measured by N independent supervisors plus one isolated checkout per
  # tree-exclusive file. The header can therefore be printed over a selection
  # that was only PARTLY measured -- the header proves the reporter ran, not that
  # the run covered anything. Keeping the old test would have downgraded this
  # check from "the whole selection was measured" to "the program reached its
  # last print statement".
  #
  # WHAT IT READS NOW, and why this is the same question: the summary's own
  # COMPLETION CENSUS. The driver states `asked`, `recorded`, `NORECORD` and
  # `NOTRUN`; this check requires that the census exists, that `asked` equals the
  # selection this gate actually handed it, and that the three outcome buckets
  # add back up to `asked`. That is the per-file equivalent of "one process
  # answered for the whole selection": every selected file is accounted for in
  # exactly one bucket, so no file can go missing between the selector and the
  # report. The merged junit must also exist and be non-empty, because the census
  # is a claim and the junit is the artefact backing it.
  #
  # ABSENCE IS A REFUSAL. A driver that dies before the census -- which is
  # exactly what the `--parallel-first` NameError did, after a full parallel wave
  # and before any reporting -- prints no census, and a missing census fails
  # here rather than passing quietly.
  _sel_n="$(wc -l < "$sel" | tr -d ' ')"
  _census="$(printf '%s\n' "$out" | grep -a -A 8 '^=== pytest junit summary' || true)"
  _c_asked="$(printf '%s\n' "$_census" | awk '$1=="asked"{print $2; exit}')"
  _c_rec="$(printf '%s\n' "$_census"  | awk '$1=="recorded"{print $2; exit}')"
  _c_nor="$(printf '%s\n' "$_census"  | awk '$1=="NORECORD"{print $2; exit}')"
  _c_not="$(printf '%s\n' "$_census"  | awk '$1=="NOTRUN"{print $2; exit}')"
  if [ -z "$_c_asked" ] || [ -z "$_c_rec" ] || [ -z "$_c_nor" ] || [ -z "$_c_not" ]; then
    printf '  FAIL  targeted test instrument produced no completion census\n'
    printf '        (no `=== pytest junit summary` block with asked/recorded/NORECORD/NOTRUN;\n'
    printf '         the instrument did not report, so the selection is UNMEASURED, not clean)\n'
    FAILED=1
  elif [ "$_c_asked" != "$_sel_n" ]; then
    printf '  FAIL  targeted test census covers %s file(s), the selection had %s\n' \
      "$_c_asked" "$_sel_n"
    FAILED=1
  elif [ "$(( _c_rec + _c_nor + _c_not ))" -ne "$_c_asked" ]; then
    printf '  FAIL  targeted test census does not add up: recorded=%s + NORECORD=%s + NOTRUN=%s != asked=%s\n' \
      "$_c_rec" "$_c_nor" "$_c_not" "$_c_asked"
    printf '        a file that is in no bucket was never accounted for either way\n'
    FAILED=1
  elif [ ! -s "$merged" ]; then
    printf '  FAIL  targeted test census claims %s recorded file(s) but the merged junit is absent/empty\n' \
      "$_c_rec"
    FAILED=1
  else
    printf '  REPORT  targeted test census complete: asked=%s recorded=%s NORECORD=%s NOTRUN=%s\n' \
      "$_c_asked" "$_c_rec" "$_c_nor" "$_c_not"
  fi
  # <<< LANDING_EVIDENCE_CHECK_1 <<<
  if printf '%s\n' "$out" | grep -qa '^NORECORD'; then
    printf '  FAIL  targeted per-file session produced no complete record\n'
    FAILED=1
  fi
  if printf '%s\n' "$out" | grep -qa '^NOTRUN'; then
    printf '  FAIL  targeted per-file session was not run\n'
    FAILED=1
  fi
  # >>> LANDING_EVIDENCE_CHECK_2 >>>
  # ── CHECK 2: DID THE WHOLE-SELECTION SESSION DECLARE A STATUS AT ALL? ────────
  #
  # WHAT IT READ BEFORE: `AGGREGATE_NORECORD` (refuse) / `AGGREGATE_COMPLETE`
  # (report) / neither (refuse). The third branch is the load-bearing one and it
  # is the whole reason this check exists: a session that declared NOTHING must
  # not be cheaper than one that declared failure.
  #
  # WHY IT CANNOT KEEP READING AGGREGATE_*: with `--parallel-first` there is no
  # aggregate session, so those two lines can never be printed. The check would
  # be demanding evidence that by construction cannot exist -- it would refuse
  # every round forever, which is not strictness, it is just a broken gate. The
  # opposite mistake is worse and is the one the doctrine forbids: deleting the
  # check would mean a parallel round that measured nothing reads exactly like
  # one that measured everything.
  #
  # WHAT IT READS NOW, and why it is the same question: the driver emits
  # `PARALLEL_COMPLETE` / `PARALLEL_NORECORD` on the parallel path, printed
  # unconditionally at the same point in the run and carrying the same meaning --
  # COMPLETE means every selected file produced a record AND every tree-exclusive
  # file got the isolated checkout it was planned, NORECORD means the
  # whole-selection result is UNKNOWN. The three branches below are therefore
  # branch-for-branch what they were, over the marker family the path can
  # actually produce.
  #
  # `PARALLEL_SPLIT` is additionally required and its `asked=` cross-checked
  # against this gate's own selection. The status line alone attests to the
  # population the DRIVER believed it had; the split line is where that belief is
  # stated as a number, and a driver that silently measured a different
  # population would otherwise satisfy a green status line.
  _sel_n="$(wc -l < "$sel" | tr -d ' ')"
  _psplit="$(printf '%s\n' "$out" | grep -a '^PARALLEL_SPLIT' | head -1)"
  _p_asked="$(printf '%s\n' "$_psplit" | sed -n 's/.*asked=\([0-9]*\).*/\1/p')"
  if printf '%s\n' "$out" | grep -qa '^PARALLEL_NORECORD'; then
    printf '  FAIL  targeted parallel session produced no complete record\n'
    FAILED=1
  elif [ -z "$_psplit" ]; then
    printf '  FAIL  targeted parallel session declared no population (no PARALLEL_SPLIT)\n'
    printf '        the split into parallel-safe and tree-exclusive files is what the\n'
    printf '        status line is a status OF; without it there is nothing to have completed\n'
    FAILED=1
  elif [ "$_p_asked" != "$_sel_n" ]; then
    printf '  FAIL  targeted parallel session split %s file(s), the selection had %s\n' \
      "$_p_asked" "$_sel_n"
    FAILED=1
  elif printf '%s\n' "$out" | grep -qa '^PARALLEL_COMPLETE'; then
    printf '  REPORT  targeted parallel session completed (%s)\n' \
      "$(printf '%s\n' "$out" | grep -a '^PARALLEL_COMPLETE' | head -1 | sed 's/^PARALLEL_COMPLETE  *//')"
  else
    printf '  FAIL  targeted parallel session produced no status\n'
    printf '        neither PARALLEL_COMPLETE nor PARALLEL_NORECORD was printed: the\n'
    printf '        session did not say what happened, and silence is not a pass\n'
    FAILED=1
  fi
  # <<< LANDING_EVIDENCE_CHECK_2 <<<
  rm -f "$sel"
  # THE EVIDENCE OUTLIVES THE RUN THAT FAILED. A green run's report is
  # reconstructible by re-running; a RED one's is the only copy of what broke,
  # and deleting it unconditionally is why every round could report `red=3` and
  # leave nothing to read. Kept ONLY on failure and ONLY when the caller did not
  # name its own target, so the successful critical path is byte-for-byte
  # unchanged and no green run accumulates files.
  if [ -n "$merged_tmp" ]; then
    if [ "$rc" -ne 0 ]; then
      printf '  REPORT  targeted test junit kept for reading: %s\n' "$merged_tmp"
    else
      rm -f "$merged_tmp"
    fi
  fi
}
if [ "${GATEKEEPER_SKIP_TARGETED_TESTS:-0}" = "1" ]; then
  echo "  SKIP  targeted tests — measured by the independent aggregate test arm"
else
  run_pytest
fi

# Merge verification already has enough evidence to refuse once the aggregate
# session produced NO complete record.  Continuing through every remaining gate
# cannot turn UNKNOWN into PASS; it only burns the critical path.  Ordinary red
# tests do NOT take this branch because the differential still has to decide
# whether they were pre-existing.
if [ "${GATEKEEPER_FAIL_FAST_NORECORD:-0}" = "1" ] \
   && [ "${TARGETED_NORECORD:-0}" = "1" ]; then
  echo "=== FAILURES ABOVE — aggregate NORECORD is an absolute refusal; remaining gates were not run"
  exit 2
fi

# ── REPO-LEVEL tests (tools/) ──────────────────────────────────────────────
# `run_pytest` above cannot reach them, and not by accident: the targeted
# selector is PLUGIN-scoped by construction —
#     _SOURCE_DIRS = ("programs", "benchmark");  _TESTS_REL = "programs/tests"
# — and it is invoked with cwd=$PLUGIN, so `tools/` at the repo root is not
# even addressable from there. No change to any file under `tools/` can select
# a test, and no test under `tools/` can be selected by any change. Measured on
# a38902d16: 28 files / 552 tests that gate NOTHING. They were all green, which
# is exactly why it stayed invisible — a blind spot announces itself only when
# something behind it breaks, and by then it has been blind for a while.
#
# DISCOVERY, never a roster. A hardcoded list is the recorded-register defect
# (census / tranche baseline / skip-routing ratchet) that goes stale the moment
# a file is added, and it would go stale silently and in the safe-looking
# direction: fewer files still reports PASS.
run_repo_tools_pytest() {
  local files out rc wg wrc snap
  mapfile -t files < <(cd "$ROOT" && find tools \
      \( -name 'test_*.py' -o -name '*_test.py' \) -type f | sort)
  # An empty corpus is a VACUOUS pass, not a pass. A gate that reports success
  # over zero items is indistinguishable from one that works, and is worse.
  if [ "${#files[@]}" -eq 0 ]; then
    echo "  FAIL  repo tools tests: discovery matched NO files under tools/ —"
    echo "        an empty corpus is not evidence that anything passed."
    FAILED=1; return
  fi
  # The in-process `programs/suite_write_guard.py` is loaded by the PLUGIN
  # conftest and is NOT present in this session, so the property it asserts —
  # the suite writes nothing `git status --porcelain` would show — is asserted
  # here from the outside rather than quietly dropped.
  #
  # DELEGATED to that same program via its --snapshot/--compare CLI instead of
  # diffing `git status` by hand. A hand-rolled comparison is a SECOND
  # definition of "wrote to the tree" that can drift from the first, and the
  # first one already knows that `__pycache__`/`.pytest_cache`/`*.pyc` are
  # regenerable and not a violation. (Written by hand first; the test below
  # caught it flagging pytest's own bytecode cache as a write.)
  snap="$(mktemp -t gk_tools_wg.XXXXXX)"
  python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" \
      --snapshot "$snap" >/dev/null 2>&1 || {
    echo "  FAIL  repo tools tests: could not baseline the tree — not a pass"
    FAILED=1; rm -f "$snap"; return
  }
  out="$( cd "$ROOT" && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
        -m "not audit_63x9" \
        -q -p pytest_timeout --timeout=180 --timeout-method=thread \
        "${files[@]}" 2>&1 )"
  rc=$?
  wg="$(python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" \
        --compare "$snap" 2>&1)"; wrc=$?
  rm -f "$snap"
  if [ "$rc" -ne 0 ]; then
    printf '  FAIL  repo tools tests (%s file(s))\n' "${#files[@]}"
    printf '%s\n' "$out" | tail -6 | sed 's/^/          /'
    FAILED=1; return
  fi
  # rc 0 clean / 1 wrote / 2 NOT_CHECKED. 2 is NOT a pass: "I could not look"
  # must never reach a reader as "I looked and it was fine".
  if [ "$wrc" -ne 0 ]; then
    printf '  FAIL  repo tools tests wrote to the tree (write-guard rc=%s)\n' "$wrc"
    printf '%s\n' "$wg" | tail -8 | sed 's/^/          /'
    FAILED=1; return
  fi
  printf '  PASS  repo tools tests (%s file(s))\n' "${#files[@]}"
}
run_repo_tools_pytest

# ── EVERY OTHER TREE THE SELECTOR CANNOT REACH ─────────────────────────────
# vibe-ic#1424. `run_pytest` runs the SELECTOR'S list and the selector is rooted
# at `programs/tests` (`_TESTS_REL`, and an explicit filter at :698), so it can
# emit nothing else — MEASURED on 3d13e2c59 against a real base: 29 files
# selected, 0 of them outside that tree. `run_repo_tools_pytest` above closed
# the same hole for repo-root `tools/` and only for that. What was still left
# with NO landing stage at all, tracked files only:
#
#     skills/*/tests/               67 files    222 tests
#     mcp-eda/                      31          201
#     tools/phase1_engine/tests/     8          121
#     _shared/                       3          283
#                                  ---         ----
#                                  109 files    827 pytest nodes
#
# #1391 and #1420 wired two of those trees into `run_tests.sh`, which is the
# DEVELOPER-facing full suite. Neither extended landing coverage, and the
# natural reading of "wired into the runners" is that it does. It did not: a
# developer running the full suite saw those failures; a landing never could.
#
# THE CORPUS IS A COMPLEMENT, NEVER A ROSTER — "every tracked test file MINUS
# what a stage already runs MINUS what is DECLARED out". A list of trees would
# go stale the first time one is added, silently and in the direction that
# still prints PASS. `benchmark-data/`'s 121 `test_*.py` are the one declared
# exclusion (CVDP corpus artefacts, not this repo's tests), stated in the
# program with its reason rather than implied by a constant.
#
# COST, measured as this line runs it: 761 passed, 58 skipped, 5 xfailed,
# 3 xpassed, 0 failed in 21 s. Zero INHERITED reds — not zero cost: the point
# of adopting a tree is that its FUTURE reds block a landing.
#
# cwd is $ROOT, as for `run_repo_tools_pytest`, and that is where this code
# says it lives: `tools/phase1_engine/gap_detect.py:43` resolves its defaults
# dir as a bare repo-root-relative path. From $PLUGIN two of these tests fail —
# vibe-ic#1390, open, a defect in that resolution and not silenced here.
run_unselectable_pytest() {
  local files out rc wg wrc snap list lrc
  list="$(mktemp -t gk_unsel.XXXXXX)"
  ( cd "$ROOT" && python3 "$PROGRAMS/landing_unselectable_pytest_corpus.py" \
        --repo "$ROOT" > "$list" ) ; lrc=$?
  # rc 2 is NOT DETERMINED. It is not an empty corpus, and it must not be
  # allowed to look like one — the whole defect this stage exists for is a
  # set of tests nobody could tell from a set that passed.
  if [ "$lrc" -ne 0 ]; then
    echo "  FAIL  unselectable tests: the corpus could not be enumerated"
    echo "        (landing_unselectable_pytest_corpus.py rc=$lrc) — that is"
    echo "        'I could not look', which is never a pass."
    FAILED=1; rm -f "$list"; return
  fi
  mapfile -t files < "$list"; rm -f "$list"
  if [ "${#files[@]}" -eq 0 ]; then
    echo "  FAIL  unselectable tests: the complement is EMPTY — either every"
    echo "        tree is genuinely covered (say so by declaring it) or the"
    echo "        census broke. A gate over zero items is not a pass."
    FAILED=1; return
  fi
  # As in `run_repo_tools_pytest`: the in-process `suite_write_guard` is loaded
  # by the PLUGIN conftest, and this session's rootdir is not guaranteed to be
  # it, so the same property is asserted from the outside via the same program
  # rather than quietly dropped.
  snap="$(mktemp -t gk_unsel_wg.XXXXXX)"
  python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" \
      --snapshot "$snap" >/dev/null 2>&1 || {
    echo "  FAIL  unselectable tests: could not baseline the tree — not a pass"
    FAILED=1; rm -f "$snap"; return
  }
  # `PYTHONDONTWRITEBYTECODE=1` IS LOAD-BEARING HERE, and it is the one hazard
  # this stage adds that no existing guard can catch.
  #
  # 67 of the 109 files are `skills/*/tests/`, and they import shipped
  # `skills/**/programs/*.py`. The IMPORT writes the bytecode — into the SHIPPED
  # tree. MEASURED on a fresh worktree, digesting `skills/` by relative path +
  # size:
  #
  #   clean, corpus never run          214 files   0 .pyc    b7a2de20…
  #   corpus run WITHOUT this token    283 files  69 .pyc    f6ad615c…  (+64 __pycache__ dirs)
  #   corpus run WITH this token       214 files   0 .pyc    b7a2de20…  identical to clean
  #
  # NOTHING ELSE SEES IT. `.pyc` is gitignored, so `git status`, `git add -A`,
  # `gitignore_scratch_guard --include-worktree` and this stage's OWN
  # `suite_write_guard` bracket all report clean with the 69 present: the guard
  # skips regenerable artefacts by design, which is correct for the guard and is
  # not a reason to leave the writes in.
  #
  # The collision it would make reachable is already named in the tree.
  # `test_tools_and_integration.py::test_shipped_skills_tree_is_untouched_by_this_session`
  # digests `skills/` at COLLECTION and compares at the end, and its own message
  # predicts this exact case: the writer is an import of a shipped
  # `skills/**/programs/*.py`, "invisible to git, `git add -A` and
  # suite_write_guard, so this digest is the only thing that sees it — which is
  # why it presents with no obvious author". Put those 67 files and that test in
  # ONE session and it fails. This stage would have been the author, in the
  # landing gate, on every batch — and :213 fails the WHOLE landing when the
  # tree moves under the gates, so the price is the batch.
  out="$( cd "$ROOT" && PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest \
        -m "not audit_63x9" \
        -q -p pytest_timeout --timeout=180 --timeout-method=thread \
        "${files[@]}" 2>&1 )"
  rc=$?
  wg="$(python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" \
        --compare "$snap" 2>&1)"; wrc=$?
  rm -f "$snap"
  # THE COUNT IS NOT IN THE LABEL, and that is deliberate. #1431: the two arms
  # of `gatekeeper-verify-merge.sh` subtract gate logs BY PRINTED LABEL, so a
  # label carrying a discovery count renames its own gate whenever a branch adds
  # a test file — and the verdict then reads a repaired gate as a silenced one.
  # This corpus grows with every new tree, which is exactly the branch shape
  # that would trip it, so the count is REPORTED on its own line instead.
  printf '        unselectable corpus: %s file(s)\n' "${#files[@]}"
  if [ "$rc" -ne 0 ]; then
    echo "  FAIL  unselectable tests"
    printf '%s\n' "$out" | tail -6 | sed 's/^/          /'
    FAILED=1; return
  fi
  if [ "$wrc" -ne 0 ]; then
    printf '  FAIL  unselectable tests wrote to the tree (write-guard rc=%s)\n' "$wrc"
    printf '%s\n' "$wg" | tail -8 | sed 's/^/          /'
    FAILED=1; return
  fi
  echo "  PASS  unselectable tests"
}
run_unselectable_pytest

# The census that decides the stage above must itself be trustworthy: a
# subtrahend whose stage no longer exists, or an exclusion whose reason no
# longer describes anything, both shrink the corpus in the direction that still
# prints PASS. rc=1 on either.
run "unselectable-test census is not stale" \
    python3 "$PROGRAMS/landing_unselectable_pytest_corpus.py" --repo "$ROOT" --audit

# THE HYGIENE TIER, AND THE RECORD THAT LETS IT BE DIFFERENCED (vibe-ic#1498).
#
# The label below is ONE line for a suite of ~70 gates, and
# `landing_merge_verdict` subtracts the two arms' gate logs BY LABEL. So the
# hygiene tier is judged at a granularity of one: while the base's suite is red
# — it has been, repeatedly, and `gate_red_since.json` exists because of it —
# the whole label is excused on the candidate too, and a finding this branch
# INTRODUCED under it is invisible. That is the permissive direction, and it is
# the direction nothing catches.
#
# `GATEKEEPER_HYGIENE_REPORT=<path>` makes this run write the suite's own
# `--summary-json` record there, which is what `hygiene_finding_delta.py` needs
# to answer the finer question — "which findings does the candidate have that
# the base does not" — instead of "is the count zero".
#
# IT CHANGES NO VERDICT HERE, exactly like `GATEKEEPER_PYTEST_JUNIT` above: the
# `run` below still decides this line, and with the variable unset the command
# is byte-for-byte the one this file has always issued. The differencing is
# done by `landing_merge_verdict`, which is the program that already owns the
# test tier's differential and is supplied by the VERIFIER rather than by the
# tree under test — a branch must not be able to change what counts as a
# refusal (see `gatekeeper-verify-merge.sh`, "WHERE EACH HALF COMES FROM").
#
# The record is written by `gate_dispatch_finish` BEFORE every one of its exit
# paths, so a FAILING run still yields one. A baseline that only existed when
# the base was green would be useless precisely when it is needed.
GK_HYG=()
[ -n "${GATEKEEPER_HYGIENE_REPORT:-}" ] \
  && GK_HYG=(--summary-json "$GATEKEEPER_HYGIENE_REPORT")
GK_HYG_ENV=()
[ -n "${GATEKEEPER_HYGIENE_PROGRESS:-}" ] \
  && GK_HYG_ENV=(env "GATE_DISPATCH_ATTESTATION_FILE=$GATEKEEPER_HYGIENE_PROGRESS")
run "repo hygiene gates"      "${GK_HYG_ENV[@]}" \
    bash "$ROOT/tools/ci/repo_hygiene_gates.sh" \
    "${GK_HYG[@]+"${GK_HYG[@]}"}"
run "plugin full audit"       python3 "$PROGRAMS/plugin_full_audit.py" "$PLUGIN"

# #1029 — the standing assertion, executed: everything above ran against this
# tree, so nothing above may have CHANGED it. Names every offending path rather
# than only failing, because a count is what made three writers cost three
# separate accidental discoveries. rc=2 (could not look) fails here too: `run`
# treats any non-zero as FAIL, which is the point — "I could not measure" must
# never reach the stamp as "I measured and it was clean".
run "the full tier wrote nothing into the tree" \
    python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" --compare "$WG_BASE"

# LAST, and after every suite has read the tree. Everything above answers
# "do the gates pass"; this answers "did they all read the same tree", which is
# the question the stamp actually asserts.
run "worktree unchanged since the gates started" \
    python3 "$PROGRAMS/landing_worktree_is_clean_check.py" "$ROOT" \
        --expect-fingerprint "$FP"

if [ "$FAILED" -eq 0 ] && [ "${GATEKEEPER_NO_STAMP:-0}" = "1" ]; then
  # Merge verification runs the authoritative aggregate test session in its
  # own parallel arm.  This lane therefore proves ONLY the non-target gates and
  # must never mint a standalone push stamp before that evidence is joined.
  rm -f "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"
  echo "  REPORT  merge verifier owns the independent targeted-test evidence"
  echo "=== ALL NON-TARGET GATES COMPLETE — stamp withheld for composite verdict ==="
elif [ "$FAILED" -eq 0 ]; then
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
