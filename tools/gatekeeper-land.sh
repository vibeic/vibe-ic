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
# --prepare (vibe-ic#1129) — do the three MECHANICAL things this script would
# otherwise refuse a batch for, before the cheap tier runs, and let the gates
# refuse only what is left:
#
#     version_bump_monotonic_check    the version was not bumped
#     landing_is_one_commit          no [vX.Y.Z]-tagged commit on the tip
#     test_programs_index_freshness  programs/INDEX.md is stale
#
# None of those is a judgement, each already has a program that owns it, and a
# refusal for one of them costs an hour of gate wall-clock while saying nothing
# about the code under test. OFF BY DEFAULT: it rewrites the tip commit, which
# is the operator's call, not a side effect of asking for a verdict.
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
  run "benchmark evidence structure" python3 "$PROGRAMS/benchmark_evidence_structure_check.py" --tree benchmark-data --changed-since "$BASE"
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
# PER-STAGE, and `--deep`. The bracket above is taken around the WHOLE tier,
# which answers "did the tier write" and cannot answer "which stage" — and
# "which stage" is the only form of the answer that is actionable, because the
# damage is not the dirty file, it is that every stage AFTER the writer
# measured what it left.
#
# Measured 2026-08-12: the tier ran three stages that write, and the failure it
# produced was reported against gates that ran LATER and were innocent. Three
# landing runs were re-done over it.
#
# `--deep` because two of the writers put the tree back. A restore closes the
# window; it does not mean the window was never open, and a stage killed inside
# one — `gatekeeper_review._run_hygiene` kills the hygiene child on timeout —
# leaves the mutation on disk for whatever runs next. #1090 measured that
# window at 23 s.
WG_STAGE="$(mktemp -t gk_stage.XXXXXX)"
trap 'rm -f "$FP" "$WG_BASE" "$WG_STAGE"' EXIT
run "write-guard baseline" \
    python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" --snapshot "$WG_BASE"
python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" \
    --snapshot "$WG_STAGE" --deep >/dev/null 2>&1 \
  || echo "  REPORT  per-stage write bracket NOT ACTIVE — a stage writing" \
          "into the tree would go unattributed in this run"

# `stage <label> <cmd…>` — `run`, plus "and what did it do to the tree".
#
# REPORT, not a gate, and deliberately so on this line: the blocking assertion
# for the tier as a whole is already made below by `--compare "$WG_BASE"`, and
# stating the same refusal twice would fail a landing twice for one cause. What
# was missing was never the refusal — it was the ATTRIBUTION.
stage() {                            # stage <label> <cmd…>
  local label="$1"; shift
  run "$label" "$@"
  stage_bracket "$label"
}

# The bracket alone, for a stage that is not a single `run` — `run_pytest`
# prints its own verdict and would be reported twice if it went through `run`.
stage_bracket() {                    # stage_bracket <label>
  local label="$1"
  local out rc=0
  out="$(python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" \
           --compare "$WG_STAGE" --snapshot "$WG_STAGE" 2>&1)" || rc=$?
  case "$rc" in
    0) [ -n "${out##*WRITTEN AND RESTORED*}" ] \
         || printf '  REPORT  ^ "%s" MUTATED THE TREE AND PUT IT BACK\n' "$label" ;;
    1) printf '  REPORT  ^ "%s" WROTE INTO THE TREE — every stage after it\n' \
              "$label"
       printf '          measures a tree this run wrote, not the tree the\n'
       printf '          stamp will name\n' ;;
    *) printf '  REPORT  ^ could not measure what "%s" did to the tree\n' \
              "$label" ;;
  esac
  [ "$rc" -eq 0 ] && [ -n "${out##*WRITTEN AND RESTORED*}" ] && return 0
  printf '%s\n' "$out" | grep -aE '^\s+(\?\?|~~|[ MARCD][ MARCD])\s' \
    | head -10 | sed 's/^/          /'
}

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
run_pytest() {
  local sel out
  # PER-RUN: see the MSGFILE note above. Two concurrent arms sharing one
  # selection file would each run the other's test list.
  sel="$(mktemp -t gk_sel.XXXXXX)"
  local maxfail=(--maxfail="${GATEKEEPER_PYTEST_MAXFAIL:-10}")
  [ "${GATEKEEPER_PYTEST_MAXFAIL:-10}" = "0" ] && maxfail=()
  local junit=()
  [ -n "${GATEKEEPER_PYTEST_JUNIT:-}" ] \
    && junit=(-o junit_family=xunit1 "--junitxml=$GATEKEEPER_PYTEST_JUNIT")
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
  if out="$( cd "$PLUGIN" && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 xargs -a "$sel" python3 -m pytest -q -p pytest_timeout "${maxfail[@]+"${maxfail[@]}"}" --timeout=180 --timeout-method=thread "${junit[@]+"${junit[@]}"}" 2>&1 )"; then
    printf '  PASS  targeted tests (%s file(s))\n' "$(wc -l < "$sel")"
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
    printf '  FAIL  targeted tests (%s file(s))\n' "$(wc -l < "$sel")"
    printf '%s\n' "$out" | tail -6 | sed 's/^/          /'
    FAILED=1
  fi
  rm -f "$sel"
}
run_pytest
# The targeted suite is the stage this repo has caught writing into the
# shipped tree three times (#1029). It is bracketed like the others.
stage_bracket "targeted tests"

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

# #1312 added this stage; #1096 added the per-stage bracket. The bracket
# must follow it for the SAME reason it follows `run_pytest`: the function
# prints its own verdict (so it cannot go through `stage`), and without a
# bracket here anything it writes is attributed to the stage that runs
# NEXT. It keeps its own blocking write check above -- that check FAILS the
# landing, where this bracket only REPORTS, so the two are not duplicates
# and removing either one loses something.
stage_bracket "repo tools tests"

stage "repo hygiene gates"    bash "$ROOT/tools/ci/repo_hygiene_gates.sh"
stage "plugin full audit"     python3 "$PROGRAMS/plugin_full_audit.py" "$PLUGIN"

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
