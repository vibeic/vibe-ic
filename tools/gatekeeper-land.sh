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
# Usage:  tools/gatekeeper-land.sh [--cheap-only] [--prepare] [--serial]
#
# --serial (or GATEKEEPER_LANDING_SERIAL=1) runs the full tier's independent
# stages one after another instead of in four lanes. It is an OPT-OUT: there is
# no variable that opts IN, because a fast path nobody switches on is a fast
# path nobody has. See "THE FULL TIER'S INDEPENDENT STAGES RUN AT THE SAME
# TIME" below for what is and is not in the concurrent window.
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
# The subject and the gate instrument are deliberately separate in verified
# landings.  The BASE transition manifest chooses one immutable instrument
# tuple and the hermetic runner mounts it read-only at /runtime for BOTH arms;
# cwd/Git still identify the subject at /subject.  Ordinary direct use keeps
# the historical one-tree shape.
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${GATEKEEPER_RUNTIME_ROOT:-$SCRIPT_ROOT}"
if [ "${VIBEIC_REQUIRE_TRUSTED_PYTEST_ENTRY:-0}" = "1" ] \
   && [ "$RUNTIME_ROOT" != "/runtime" ]; then
  echo "gatekeeper-land: verified runtime must be mounted at /runtime" >&2
  exit 2
fi
PROGRAMS="$RUNTIME_ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs"
PLUGIN="$ROOT/vibe-ic-marketplace/plugins/vibe-ic"
PJSON="$PLUGIN/.claude-plugin/plugin.json"
BASE="${GATEKEEPER_BASE:-origin/main}"
RANGE="${BASE}..HEAD"
# ── THE TEST CADENCE THE TREE REQUIRES (policy 2026-06-17, wired 2026-08-27) ──
#
# The policy is old and the implementation is old; what did not exist was the
# WIRE. `gatekeeper_review.derive_cadence` has said this since 2026-06-17 —
# x.y.0 MILESTONE -> FULL, x.y.Z PATCH -> TARGETED — while THIS script, the one
# that actually runs the landing, had no cadence concept at all. Measured at
# v1.11.94: `grep -c -i cadence tools/gatekeeper-land.sh` was 0.
#
# THE GAP RAN IN THE UNSAFE DIRECTION, which is the opposite of how it reads.
# `run_pytest` called `ci_targeted_test_select.py` on EVERY bump, so a
# MILESTONE landed on the patch tier: 101 selected files against a tree of
# 2862. The half that was lost is nameable — `full-suite-milestone` in
# `.github/workflows-disabled/gatekeeper-ci.yml.disabled`, gated by
# `if: needs.cadence.outputs.level == 'milestone'`. GitHub disabled Actions at
# the ACCOUNT level so it never ran once, and 0d66c96161 (2026-07-30, v1.8.40)
# retired both workflows. This script inherited the TARGETED selector and
# nothing inherited the FULL arm.
#
# FROM THE TREE, NEVER FROM A FLAG. There is no `--cadence` option here and
# there must never be one: a caller-supplied cadence is a caller-supplied
# answer. The version pair is read out of the committed manifest at BASE and at
# HEAD, and the verdict is `derive_cadence`'s own — imported, not copied.
#
# EVERY FAILURE IS FULL. An empty answer here means the program could not run
# at all, and "I could not read the version" must never arrive as "the cheap
# tier is fine". The fallback below is therefore the STRICTER tier, so this
# wire can only ever make a landing do more than it needed, never less.
LANDING_CADENCE="$(python3 "$PROGRAMS/landing_cadence.py" \
    --repo "$ROOT" --base "$BASE" --head HEAD 2>/dev/null \
    | sed -n 's/^LANDING_CADENCE=//p' || true)"
[ -n "$LANDING_CADENCE" ] || LANDING_CADENCE=FULL
# THE CONSISTENCY TIER RIDES THE SAME VERDICT (owner, 2026-09-26). Tests marked
# `consistency` — pure bookkeeping: stated counts, inventories, registers, file
# order, README/website figures — are DESELECTED unless this variable is 1
# (`programs/consistency_tier.py`). They run at the x.y.0 milestone and on the
# owner's request, never on a patch. Exported here, once, so every lane below
# (targeted/full pytest, repo tools tests, unselectable) inherits one answer;
# cleared otherwise, so a caller's environment cannot turn a patch landing into
# a bookkeeping one. The same no-flag rule as the cadence itself.
if [ "$LANDING_CADENCE" = "FULL" ]; then
  export VIBEIC_RUN_CONSISTENCY=1
else
  unset VIBEIC_RUN_CONSISTENCY
fi
CHEAP_ONLY=0
PREPARE=0
# THE FULL TIER'S INDEPENDENT STAGES RUN AT THE SAME TIME, BY DEFAULT.
#
# `LANE_WIDTH` is the number of full-tier lanes allowed to be live at once.
# 1 is SERIAL and it is the SAME SCHEDULER, not a second implementation: at
# width 1 the launch/join loop below executes each lane body in declaration
# order on the main shell, through the same capture and the same emit, so the
# journal it produces is asserted equal to the concurrent one
# (`tools/test_gatekeeper_land_lanes.py`). There is deliberately NO variable
# that opts IN — a fast path nobody switches on is a fast path nobody has.
LANE_WIDTH=4
[ "${GATEKEEPER_LANDING_SERIAL:-0}" = "1" ] && LANE_WIDTH=1
# THIS GATE JUDGES ABSOLUTELY, AND THAT COSTS SOMETHING REAL
# ==========================================================
# Everything below this line judges ABSOLUTELY: "did anything fail", with no
# reference to what the base tree already does. The cost is not academic —
# measured 2026-08-17, `origin/main` (f6b0e77dd) FAILS ITS OWN GATES here
# (`repo tools tests` 9 red, `repo hygiene gates` 1 of 80), so no stamp is
# written for main's own tip and `pre-push` refuses it. A commit that FIXES
# those reds is refused by the same rule. Five rounds, ~2.5 hours of gate wall
# clock, zero landings.
#
# That fact is still true and this comment stays because of it. What changed is
# the ANSWER this file used to give.
#
# THE TWO-ARM DIFFERENTIAL WAS REMOVED 2026-08-28 (owner instruction)
# ==================================================================
# `tools/gatekeeper-land-differential.sh` ran this same script TWICE — once on
# the candidate, once on pristine main in a throwaway worktree — and diffed the
# two red sets to answer "is this regression mine". It is gone, and telling
# people not to run it was tried first and did not work: while the code existed,
# someone ran it again.
#
# WHY, measured, not asserted:
#   * ~3.5 hours per arm. Three landings on 2026-08-27 spent 6h, 4h and 2h in
#     it and not one of them landed anything.
#   * It reported the ENVIRONMENT as the diff. Arms placed on two hosts
#     returned 2 new / 89 cleared, and 82 of the 89 were one family that is red
#     where docker is unreachable and green where it is not.
#   * A "fast" variant compared a harness red set against a standalone probe
#     and invented a new red that existed under NEITHER mode.
#
# A wrong answer that takes seven hours is worse than no answer, because it is
# believed. So: this gate asks the ABSOLUTE question, it says so when it
# refuses, and the remedy is stated at the bottom of this file — fix the named
# red, or land it and record the pre-existing reds in the commit message.
#
# NOT the merge path. `tools/gatekeeper-verify-merge.sh` (#1019) has its own
# arms and its own judge and is untouched by this removal.
for _arg in "$@"; do
  case "$_arg" in
    --cheap-only) CHEAP_ONLY=1 ;;
    --prepare)    PREPARE=1 ;;
    --serial)     LANE_WIDTH=1 ;;
    --differential)
      # REFUSED BY NAME, WITH THE REASON. The generic "unknown argument" below
      # would be true and useless: a reader who typed this flag learned it from
      # a runbook, a commit message or a colleague, and needs to know it was
      # taken away deliberately and what to do instead. A removal that leaves
      # no trace teaches the next reader nothing.
      echo "gatekeeper-land: --differential was REMOVED 2026-08-28 (owner)." >&2
      echo "    The two-arm differential cost ~3.5h PER ARM and reported" >&2
      echo "    environment differences as regressions: arms on two hosts" >&2
      echo "    returned 2 new / 89 cleared, of which 82 were one family that" >&2
      echo "    is red where docker is unreachable and green where it is not." >&2
      echo "" >&2
      echo "    This gate judges ABSOLUTELY — any red refuses, pre-existing or" >&2
      echo "    not. Instead of re-measuring the base:" >&2
      echo "      * fix the red this run names, or" >&2
      echo "      * land it and record the pre-existing reds, by name, in the" >&2
      echo "        commit message and 'git notes --ref=landing'." >&2
      echo "" >&2
      echo "    The MERGE path is unaffected: tools/gatekeeper-verify-merge.sh" >&2
      exit 2
      ;;
    *) echo "gatekeeper-land: unknown argument '$_arg'" >&2; exit 2 ;;
  esac
done

FAILED=0
CENSUS_UNDETERMINED=0
LANDING_RECORD_ENABLED=0
LANDING_RECORD_TOOL="$RUNTIME_ROOT/tools/ci/landing_completion_record.py"
# Only the approved runtime supplies this declaration. No candidate event,
# environment path or receipt can replace the required execution population.
LANDING_PLAN_TOOL="$RUNTIME_ROOT/tools/ci/landing_execution_plan.py"
LANDING_PLAN_SHELL="$(python3 "$LANDING_PLAN_TOOL" shell)" \
  || { echo "[NORECORD] approved landing execution plan unavailable" >&2; exit 2; }
eval "$LANDING_PLAN_SHELL"
unset LANDING_PLAN_SHELL
LANDING_NEXT=0
landing_plan_dispatch() {           # phase [lane] [emit]
  local phase="$1" lane="${2:-}" mode="${3:-unit}" unit fn before
  for unit in "${LANDING_PLAN_UNITS[@]}"; do
    [ "${LANDING_PLAN_PHASE[$unit]}" = "$phase" ] || continue
    [ -z "$lane" ] || [ "${LANDING_PLAN_LANE[$unit]}" = "$lane" ] || continue
    fn="landing_${mode/validate/unit}_${unit//[:-]/_}"
    declare -F "$fn" >/dev/null \
      || { echo "[NORECORD] missing plan handler: $fn" >&2; exit 2; }
    [ "$mode" != validate ] || continue
    before="$LANDING_NEXT"
    "$fn" "$unit"
    if [ "$phase" != window ] || [ "$mode" = emit ]; then
      [ "$LANDING_NEXT" -eq "$((before + 1))" ] \
        || { echo "[NORECORD] plan unit did not record exactly once: $unit" >&2; exit 2; }
    fi
  done
}

LANDING_PROGRESS_TOOL="$RUNTIME_ROOT/tools/ci/hermetic_progress_emit.py"
LANDING_JOURNAL="${VIBEIC_LANDING_PROGRESS:-}"
LANDING_COMPLETION="${VIBEIC_LANDING_COMPLETION:-}"
if [ -n "$LANDING_JOURNAL" ] || [ -n "$LANDING_COMPLETION" ]; then
  if [ -z "$LANDING_JOURNAL" ] || [ -z "$LANDING_COMPLETION" ] \
     || { [ "${GATEKEEPER_VERIFY_ARM:-}" != "A2" ] \
          && [ "${GATEKEEPER_VERIFY_ARM:-}" != "B2" ]; } \
     || [ "$LANDING_JOURNAL" != "/evidence/landing-progress.jsonl" ] \
     || [ "$LANDING_COMPLETION" != "/evidence/landing-completion.json" ]; then
    echo "[NORECORD] landing completion environment is partial or unowned" >&2
    exit 2
  fi
  [ ! -e "$LANDING_JOURNAL" ] && [ ! -L "$LANDING_JOURNAL" ] \
    && [ ! -e "$LANDING_COMPLETION" ] && [ ! -L "$LANDING_COMPLETION" ] \
    || { echo "[NORECORD] landing evidence path already exists" >&2; exit 2; }
  python3 "$LANDING_PROGRESS_TOOL" start \
    || { echo "[NORECORD] landing progress could not start" >&2; exit 2; }
  LANDING_RECORD_ENABLED=1
fi

landing_output_sha() {
  printf '%s' "$1" | sha256sum | awk '{print $1}'
}

landing_record() {                  # landing_record <unit> <state> <rc> <output>
  local unit="$1" state="$2" rc="$3" output="$4" digest
  if [ "${LANDING_PLAN_UNITS[$LANDING_NEXT]:-}" != "$unit" ]; then
    echo "[NORECORD] missing, duplicate, unexpected or out-of-order plan unit: $unit" >&2
    exit 2
  fi
  LANDING_NEXT=$((LANDING_NEXT + 1))
  [ "$LANDING_RECORD_ENABLED" = "1" ] || return 0
  digest="$(landing_output_sha "$output")" \
    || { echo "[NORECORD] cannot digest landing stage $unit" >&2; exit 2; }
  python3 "$LANDING_RECORD_TOOL" append --journal "$LANDING_JOURNAL" \
    --label "$unit" --state "$state" --returncode "$rc" \
    --output-sha256 "$digest" \
    || { echo "[NORECORD] cannot attest landing stage $unit" >&2; exit 2; }
  python3 "$LANDING_PROGRESS_TOOL" checkpoint "$unit" \
    || { echo "[NORECORD] cannot relay landing stage $unit" >&2; exit 2; }
}

landing_skip() {                    # landing_skip <unit> <message>
  landing_record "$1" SKIP 0 "$2"
}

landing_manual_stage() {            # landing_manual_stage <unit> <failed-before>
  local unit="$1" before="$2"
  if [ "$FAILED" -gt "$before" ]; then
    landing_record "$unit" FAIL 1 "FAILED:$before->$FAILED"
  else
    landing_record "$unit" PASS 0 "FAILED:$before->$FAILED"
  fi
}
# REPORT, not a gate. Prints what a probe found and NEVER touches FAILED.
#
# It exists so that a measurement whose blast radius is not yet a landing bar
# still EXECUTES against every landing instead of being parked in a flag nobody
# passes. The distinction is written into the label, so a reader of this log
# can never mistake a REPORT line for a PASS.
report() {                           # report <unit> <label> <cmd…>
  local unit="$1" label="$2"; shift 2
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then
    printf '  REPORT  %s\n' "$label"
  else
    printf '  REPORT  %s (rc=%s — NOT blocking)\n' "$label" "$rc"
  fi
  printf '%s\n' "$out" | grep -aE 'REPORT|VIOLATION|\[FAIL\]|\[SKIP\]' \
    | head -8 | sed 's/^/            /'
  landing_record "$unit" REPORT "$rc" "$out"
}
# ── run(), SPLIT INTO "EXECUTE" AND "EMIT" — ONE CODE PATH, NOT TWO ────────
#
# `run` did four things in one function: execute, buffer, print under a label,
# and record. Only the first can move off the main shell; the last MUST NOT.
# `landing_completion_record.append` is an UNLOCKED read-modify-write and
# `:200` refuses any label that is not `LANDING_PROGRESS_UNITS[len(gates)]`, so
# a lane that recorded from its own subshell would both append out of order and
# lose the concurrent updates. Splitting the function is what lets the stages
# run at the same time while the JOURNAL is still written by one shell, in one
# order — the fixed-order refusal and the complete-population refusal at `:261`
# are then satisfied by construction rather than by luck.
#
# NOTHING ABOUT BUFFERING CHANGES. `out="$("$@" 2>&1)"` already buffered every
# stage's output before this split; the only difference is that the buffer now
# has a name on disk so a stage that ran somewhere else can be printed here.
#
# `run` keeps its name, its signature and its output shape: it is capture
# followed immediately by emit, so every serial stage outside the concurrent
# window is byte-identical to what this script has always printed.
LANE_DIR="$(mktemp -d -t gk_lanes.XXXXXX)"
FP=""
WG_BASE=""
LANE_LIVE_PIDS=""
# HOISTED — `gk_cleanup` below CALLS this, and bash only defines a function when
# its definition statement is EXECUTED. Defined at its old site (next to
# `gk_subject_prepare`, ~1800 lines down) it did not yet exist on any exit that
# happens between `trap gk_cleanup EXIT` and there — `--cheap-only` is the
# obvious one, and it is not the only one — so the EXIT trap answered
# `gk_subject_release: command not found` twice and the trap's cleanup was
# only as complete as the line the script happened to die on. Safe to hoist:
# it reads `$ROOT` and `${!var}` at CALL time, never at definition time. NOT a
# guard at the call site — `declare -F ... &&` would make the leak silent
# instead of noisy, which is worse. `tools/test_gatekeeper_land_lanes.py`
# asserts the general invariant, not this one instance.
gk_subject_release() {               # gk_subject_release <var>
  local var="$1" wt
  wt="${!var:-}"
  [ -n "$wt" ] || return 0
  git -C "$ROOT" worktree remove --force "$wt" >/dev/null 2>&1 || true
  # `worktree remove` can refuse a directory a gate is still holding open; the
  # directory is then swept by name, and ONLY under a lane dir this script
  # minted — the same `case` guard `gk_cleanup` applies before its own `rm -rf`.
  case "$wt" in
    */gk_lanes.??????/subject-*) rm -rf "$wt" ;;
  esac
  git -C "$ROOT" worktree prune >/dev/null 2>&1 || true
  printf -v "$var" '%s' ''
  return 0
}

# THIS SCRIPT HAD NO EXIT TRAP FOR PROCESSES BECAUSE IT HAD NO BACKGROUND WORK.
# With lanes it must own them: a gate killed mid-tier would otherwise leave
# pytest and hygiene children writing into the tree AFTER
# `full:worktree-fingerprint-final` has already stamped it, which is precisely
# the "the tree moved under the gates" failure the closing pair exists to
# catch — except nobody would be left to catch it.
#
# Modelled on `tools/gatekeeper-verify-merge.sh:822-838`, including its
# measured lesson: WAIT for each child rather than guessing an outer timeout.
# Its comment records that a two-second guess killed the wrapper and left the
# actual gate alive. Each lane is launched under `set -m` so it leads its own
# process group and the negated PID reaches its whole descendant tree.
gk_cleanup() {
  local pid
  for pid in $LANE_LIVE_PIDS; do
    kill -TERM -- "-$pid" >/dev/null 2>&1 || kill -TERM "$pid" >/dev/null 2>&1 || true
  done
  for pid in $LANE_LIVE_PIDS; do
    wait "$pid" >/dev/null 2>&1 || true
  done
  for pid in $LANE_LIVE_PIDS; do
    kill -KILL -- "-$pid" >/dev/null 2>&1 || true
  done
  [ -z "$FP" ] || rm -f "$FP"
  [ -z "$WG_BASE" ] || rm -f "$WG_BASE"
  # The two hygiene subjects (vibe-ic#2008) are linked worktrees REGISTERED in
  # this checkout's `.git/worktrees/`; sweeping the lane dir alone would leave
  # registrations `git worktree list` keeps reporting. Guarded, because
  # `tools/test_gatekeeper_land_lanes.py` drives this REAL function with the
  # variables never set.
  gk_subject_release GK_HYG_SUBJECT
  gk_subject_release GK_REVIEW_SUBJECT
  # Same `case` safety pattern the verifier uses before every `rm -rf`: the
  # variable must still name a path this script minted.
  case "$LANE_DIR" in
    */gk_lanes.??????) rm -rf "$LANE_DIR" ;;
  esac
}
trap gk_cleanup EXIT
lane_write() {                       # lane_write <unit> <output> <rc>
  # THE RETURN CODE FILE IS WRITTEN ATOMICALLY AND LAST. A lane that is killed
  # must be distinguishable from one that finished; if `.rc` could be observed
  # half-written, or written before the output it summarises, "no verdict" and
  # "verdict 0" would be the same state on disk.
  local unit="$1" out="$2" rc="$3"
  printf '%s\n' "$out" > "$LANE_DIR/$unit.out"
  printf '%s' "$rc" > "$LANE_DIR/$unit.rc.tmp" \
    && mv -f "$LANE_DIR/$unit.rc.tmp" "$LANE_DIR/$unit.rc"
}
lane_reported() {                    # lane_reported <unit>
  # THE POSITIVE SIGNAL THAT A STAGE REACHED THE END OF ITS OWN REPORT.
  #
  # `.rc` alone cannot carry it. A capture subshell that is SIGKILLed exits
  # 128+signal, and 137 is as parsable an integer as 0 or 1 — so for the three
  # `fn_capture` stages, which report by PRINTING `  FAIL  <label>` rather than
  # by exiting, a parsable `.rc` is not evidence that anything was reported.
  # This file is written by the stage's own process AFTER that print, so its
  # presence means exactly one thing and its absence means the other.
  printf 'REPORTED' > "$LANE_DIR/$1.reported.tmp" \
    && mv -f "$LANE_DIR/$1.reported.tmp" "$LANE_DIR/$1.reported"
}
run_capture() {                      # run_capture <unit> <cmd…>
  # These stages report BY EXIT STATUS: `run_emit` prints their label from the
  # return code, so the capture returning at all IS the report, and the marker
  # belongs here in the lane shell.
  local unit="$1"; shift
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  lane_reported "$unit"
  lane_write "$unit" "$out" "$rc"
  return 0
}
fn_capture() {                       # fn_capture <unit> <fn…>
  # For the three stages that print their own PASS/FAIL lines and signal
  # through `FAILED` rather than through an exit status. `FAILED` is reset
  # inside the subshell so the stage's verdict is its OWN, and the function's
  # return code is folded in as well: a stage that returned non-zero without
  # setting FAILED must not be read as a pass.
  #
  # `lane_reported` is INSIDE the subshell, after the stage function has
  # returned and therefore after its own label was printed. A stage killed
  # before that point leaves no marker, and `lane_resolve` then refuses to read
  # its exit status as a verdict.
  local unit="$1"; shift
  local out rc
  out="$( FAILED=0; "$@" 2>&1; _frc=$?; [ "$_frc" -eq 0 ] || FAILED=1
          lane_reported "$unit"
          exit "$FAILED" )"; rc=$?
  lane_write "$unit" "$out" "$rc"
  return 0
}
# LANE_WAIT_RC / LANE_BROKEN are set by `lane_join` for the group of units
# being emitted next; `lane_resolve` reads them to decide what a missing
# verdict means. EMIT_RC / EMIT_OUT are its outputs.
LANE_WAIT_RC=0
LANE_BROKEN=0
EMIT_RC=0
EMIT_OUT=""
lane_resolve() {                     # lane_resolve <unit> [--last]
  # A KILLED LANE REACHES THE VERDICT AS FAILED, NEVER ABSENT AND NEVER A PASS.
  #
  # Absence is NOT the signal, and assuming it was is the defect this replaces:
  # a redirect creates the output file at fork time, so a killed lane leaves a
  # PARTIAL file, not no file. Worse, `landing_merge_verdict.py:958` accepts
  # rc=1 as an ordinary red and then subtracts BY PRINTED LABEL, so a lane that
  # died contributing no label at all is absorbed as "no new failure".
  #
  # So a record is MANDATORY for every unit: the main shell pre-creates `.rc`
  # holding the literal NORECORD, the lane overwrites it atomically with an
  # integer as its last action, and anything else — NORECORD, missing,
  # unparsable — is resolved HERE into a labelled FAIL. rc must be non-zero
  # because `landing_completion_record.py:190-196` refuses FAIL with rc 0; 199
  # is the value `pytest_per_file_junit` already uses for the same meaning.
  local unit="$1" last="${2:-}" raw reported=0
  EMIT_OUT="$(cat "$LANE_DIR/$unit.out" 2>/dev/null || true)"
  raw="$(cat "$LANE_DIR/$unit.rc" 2>/dev/null || true)"
  [ -f "$LANE_DIR/$unit.reported" ] && reported=1
  if [[ "$raw" =~ ^[0-9]+$ ]] && [ "$raw" -le 255 ] && [ "$reported" -eq 1 ] \
     && { [ "$LANE_BROKEN" -eq 0 ] || [ "$last" != "--last" ]; }; then
    EMIT_RC="$raw"
    return 0
  fi
  EMIT_RC="$LANE_WAIT_RC"
  [[ "$EMIT_RC" =~ ^[0-9]+$ ]] && [ "$EMIT_RC" -ne 0 ] && [ "$EMIT_RC" -le 255 ] \
    || EMIT_RC=199
  if [ "$reported" -eq 0 ] && [[ "$raw" =~ ^[0-9]+$ ]]; then
    # THE STAGE DIED INSIDE A LANE THAT STAYED ALIVE. Named separately because
    # the two events need different repairs from a reader: a dead lane loses
    # every unit after the one it was on, a dead STAGE loses only this one and
    # the lane's later units reported normally right underneath it.
    EMIT_OUT="$EMIT_OUT
NORECORD  stage $unit exited (rc $raw) but did not reach its own report — killed inside a lane that stayed alive. Its label was never printed, and an unprinted label is not a pass."
  else
    EMIT_OUT="$EMIT_OUT
NORECORD  lane $unit left no verdict — killed, or it did not finish. This is not a pass."
  fi
  return 1
}
run_emit() {                         # run_emit <unit> <label>
  local unit="$1" label="$2"
  local out rc state
  lane_resolve "$unit" "${3:-}" || true
  out="$EMIT_OUT"; rc="$EMIT_RC"
  if [ "$rc" -eq 0 ]; then
    printf '  PASS  %s\n' "$label"
    state=PASS
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
    # A VERDICT PREFIXED WITH ITS OWN PROGRAM NAME IS STILL A VERDICT (2026-09-10).
    # The `^[[:space:]]*` anchor meant a line like
    #     landing_hygiene_ratchet_check: FAIL — this landing INTRODUCES non-atomic report writes
    # matched NOTHING, so this branch printed nothing and only the `tail` below survived. That
    # program emits 127 lines, so the window held its last two ADVISORY coverage gaps while the
    # FAIL sat 122 lines above it — and the reader saw a refusal that named no finding.
    #
    # Measured cost, one night: nine landings refused with an unreadable reason. All nine named
    # a REAL introduced finding once the truncation was undone; zero false positives. One held a
    # PR for three and a half hours over a single line, and four were a personal username
    # entering this PUBLIC repository inside an added test file — on runs where the
    # `NDA — added content/paths` gate itself reported PASS.
    #
    # The second-order cost was worse than the first. A reader inferred from this DISPLAY that
    # the GATE was refusing on sub-checks it could not measure, and weakened the gate to match —
    # a fail-open hole in the one instrument that had just caught four NDA-shaped leaks. Measured
    # afterwards, the checker prints 121 unmeasurable sub-checks and still exits 0; its coverage
    # block is advisory by construction. The gate was never wrong. The display was.
    #
    # This is the SECOND repair of this class at this line — the 2026-07-30 note above records a
    # failing gate hidden by `tail` alone, fixed by printing failing lines first. That fix
    # assumed a failing line looks like `FAIL …`. This one drops the assumption, and errs toward
    # showing MORE: an extra rendered line costs a glance; a missing one cost an hour and a gate.
    printf '%s\n' "$out" \
      | grep -aE '(^|[[:space:]]|:[[:space:]])(FAIL|ERROR|REFUSE|REFUSED)\b|\[FAIL\]|\[ERROR\]|FAILED' \
      | head -12 | sed 's/^/          /'
    printf '%s\n' "$out" | tail -5 | sed 's/^/          /'
    FAILED=1
    state=FAIL
  fi
  landing_record "$unit" "$state" "$rc" "$out"
}
census_freshness_emit() {            # census_freshness_emit [--last]
  # THREE OUTCOMES, NOT TWO, AND rc 2 IS NOT ONE OF THE OTHER TWO.
  #
  # `run_emit` reads any non-zero as FAIL. `gen_flow_matrix_census --check`
  # returns 2 for "I could not look" — NORECORD (a non-cell test in one of the
  # nine dimension modules is red, so the census is not a record), a tree that
  # carries no matrix suite (ZERO_DENOMINATOR), or a declared corpus provenance
  # this host cannot arrange. These are not product findings (#1277), but a
  # run that could not decide cannot certify ALL GATES PASS either (#2203).
  # Keep REPORT separate from FAILED; the existing completion unit refuses
  # certification of an undetermined run without inventing a tree defect.
  #
  # rc 2 is therefore REPORT — the state this record already has for "ran,
  # decided nothing, never mistaken for a pass" — with the returncode printed.
  # It is not SKIP: `landing_completion_record` refuses SKIP with a non-zero rc,
  # and rightly, because a skip is something nobody attempted.
  #
  # rc 1 — the block is STALE — BLOCKS, and that is the whole point of the unit.
  # The generator names the figures that moved (`census_drift`, #2142), so the
  # lines quoted under the FAIL say which dimension and which column.
  #
  # AND A LANE THAT NEVER REPORTED IS NOT rc 2 EITHER. `lane_resolve` RETURNS
  # non-zero when it could not read a real verdict — a killed lane, a stage that
  # died before printing its label — and synthesises `EMIT_RC=199` for it. Read
  # blindly, 199 would fall into the `else` below and a killed lane would be
  # published as "the census could not be measured", which is the same sentence
  # an honest NORECORD prints and would make the two indistinguishable. So the
  # RESOLUTION is consulted first and an unresolved unit is a FAIL, exactly as
  # `run_emit` treats it.
  local unit="full:census-freshness" label="63x8 census freshness" resolved=0
  # The last emitted measurement owns this state, including a serial re-run.
  CENSUS_UNDETERMINED=0
  lane_resolve "$unit" "${1:-}" || resolved=1
  if [ "$resolved" -ne 0 ]; then
    printf '  FAIL  %s — no verdict was recorded for this unit\n' "$label"
    printf '%s\n' "$EMIT_OUT" | tail -5 | sed 's/^/          /'
    FAILED=1
    landing_record "$unit" FAIL "$EMIT_RC" "$EMIT_OUT"
  elif [ "$EMIT_RC" -eq 0 ]; then
    printf '  PASS  %s\n' "$label"
    landing_record "$unit" PASS 0 "$EMIT_OUT"
  elif [ "$EMIT_RC" -eq 1 ]; then
    printf '  FAIL  %s — the published census does not re-derive on this tree\n' "$label"
    printf '%s\n' "$EMIT_OUT" | grep -aE 'stale|committed .* -> live|no PUBLISHED FIGURE' \
      | head -12 | sed 's/^/          /'
    FAILED=1
    landing_record "$unit" FAIL "$EMIT_RC" "$EMIT_OUT"
  else
    CENSUS_UNDETERMINED=1
    printf '  REPORT  %s (rc=%s — the census could not be measured here; NOT a pass)\n' \
      "$label" "$EMIT_RC"
    printf '%s\n' "$EMIT_OUT" | grep -aE 'NORECORD|ZERO_DENOMINATOR|CROSS_TREE|NOT_MEASURED' \
      | head -8 | sed 's/^/            /'
    landing_record "$unit" REPORT "$EMIT_RC" "$EMIT_OUT"
  fi
}
fn_emit() {                          # fn_emit <unit> <label> [--last]
  # THE EMIT FOR A STAGE THAT PRINTS ITS OWN LABEL.
  #
  # `run_emit` prints `PASS`/`FAIL <label>` from the return code. The three
  # `fn_capture` stages print it themselves, so this one normally only replays
  # what they wrote — EXCEPT when they never got there. A stage killed inside a
  # live lane leaves a parsable `.rc` and no report marker, and
  # `landing_merge_verdict.py` subtracts the two arms' gate logs BY PRINTED
  # LABEL: a stage that contributed no label at all is absorbed as "no new
  # failure", which is the permissive direction and the one that lands.
  #
  # So the label is printed HERE when the stage could not print it. WITHOUT ITS
  # DISCOVERY COUNT, because the count was never measured: the base arm's line
  # carries one and this one does not, the two labels therefore do not match,
  # and the differential reads the gate as failing on the candidate alone —
  # which is exactly what an unmeasured stage is.
  local unit="$1" label="$2" resolved=0
  lane_resolve "$unit" "${3:-}" || resolved=1
  printf '%s\n' "$EMIT_OUT"
  [ "$resolved" -eq 0 ] || printf '  FAIL  %s\n' "$label"
  return 0
}
run() {                              # run <unit> <label> <cmd…>
  local unit="$1" label="$2"; shift 2
  run_capture "$unit" "$@"
  run_emit "$unit" "$label"
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
GK_RANGE_N="$(git rev-list --count "$RANGE" 2>/dev/null || echo 0)"
landing_unit_cheap_nda_messages() {
  if [ "$GK_RANGE_N" = "0" ]; then
    landing_skip "$1" "range is empty"
    return 0
  fi
  if [ -n "${VIBEIC_NDA_HOST_RESULT:-}" ]; then
    run "$1" "NDA — trusted host commit messages" python3 "$RUNTIME_ROOT/tools/ci/trusted_nda_host.py" \
      check-unit --repo "$ROOT" --base "$BASE" --guard commit_msg_nda_check.py
    return
  fi
  run "$1" "NDA — commit messages"   python3 "$PROGRAMS/commit_msg_nda_check.py" --repo "$ROOT" --rev-range "$RANGE"
}
landing_unit_cheap_nda_content() {
  if [ "$GK_RANGE_N" = "0" ]; then
    landing_skip "$1" "range is empty"
    return 0
  fi
  if [ -n "${VIBEIC_NDA_HOST_RESULT:-}" ]; then
    run "$1" "NDA — trusted host content and paths" python3 "$RUNTIME_ROOT/tools/ci/trusted_nda_host.py" \
      check-unit --repo "$ROOT" --base "$BASE" --guard nda_diff_scan_check.py
    return
  fi
  run "$1" "NDA — added content/paths" python3 "$PROGRAMS/nda_diff_scan_check.py" --rev-range "$RANGE"
}
landing_unit_cheap_version() {
  if [ "$GK_RANGE_N" = "0" ]; then
    landing_skip "$1" "range is empty"
    return 0
  fi
  # `GATEKEEPER_VERSION_BY_GATEKEEPER=1` — the VERSION-LESS authoring-PR path,
  # for `tools/gatekeeper-verify-merge.sh` (vibe-ic#1019). The version is
  # assigned AT MERGE by the gatekeeper, so a PR under verification legitimately
  # carries no bump and demanding one here would refuse every conformant PR —
  # the same deferral `tools/git-hooks/pre-push` already applies off-main, using
  # the same flag the program already ships. A BACKWARDS version is still
  # refused in both directions, so this defers the gate and does not disable it.
  # Unset (the push path) is unchanged: current == previous still FAILs.
  if [ "${GATEKEEPER_VERSION_BY_GATEKEEPER:-0}" = "1" ]; then
    run "$1" "version monotonic (assigned at merge — deferred)" python3 "$PROGRAMS/version_bump_monotonic_check.py" --plugin-json "$PJSON" --base "$BASE" --version-by-gatekeeper
  else
    run "$1" "version bumped monotonically" python3 "$PROGRAMS/version_bump_monotonic_check.py" --plugin-json "$PJSON" --base "$BASE"
  fi
}
landing_unit_cheap_agent_scope() {
  if [ "$GK_RANGE_N" = "0" ]; then
    landing_skip "$1" "range is empty"
    return 0
  fi
  run "$1" "agent check-in scope"    python3 "$PROGRAMS/agent_checkin_scope_guard.py" --role core-agent --base "$BASE"
}
landing_unit_cheap_benchmark_structure() {
  if [ "$GK_RANGE_N" = "0" ]; then
    landing_skip "$1" "range is empty"
    return 0
  fi
  # `--corpus-may-be-absent`: the published corpus lives in vibeic/benchmark-data,
  # so THIS repo legitimately has no `benchmark-data/`. Without the flag the gate
  # correctly reports UNDETERMINED and blocks every push — a gate that refuses
  # every landing is the ban this repo already learned to distrust.
  #
  # It is NOT a licence. With VIBE_IC_BENCHMARK_DATA pointing at a clone the gate
  # scans it and can still fail; with the pointer set and broken it is still
  # UNDETERMINED, flag or no flag. The flag only names the one case it was written
  # for: nothing configured, nothing local, nothing claimed.
  #
  # `BASE` is an object in THIS repository.  It cannot be resolved inside the
  # separately attested benchmark-data repository, so applying --changed-since
  # there turns a present corpus into a zero-denominator NORECORD.  The external
  # snapshot is immutable and SHA-bound by the verifier; grade its complete
  # population.  Preserve change-scoping only for the historical in-tree shape.
  BENCHMARK_STRUCTURE_SCOPE=()
  [ -n "${VIBE_IC_BENCHMARK_DATA:-}" ] \
    || BENCHMARK_STRUCTURE_SCOPE=(--changed-since "$BASE")
  run "$1" "benchmark evidence structure" python3 "$PROGRAMS/benchmark_evidence_structure_check.py" --tree benchmark-data --corpus-may-be-absent "${BENCHMARK_STRUCTURE_SCOPE[@]}"
}
landing_unit_cheap_benchmark_manifest() {
  if [ "$GK_RANGE_N" = "0" ]; then
    landing_skip "$1" "range is empty"
    return 0
  fi
  # vibe-ic#635 — a NEW published number must arrive with its composition.
  # Scoped `--changed-since` like the gate above: 20 of the 25 runs already
  # published carry no per-problem name set, and applying this retroactively
  # would fail every landing over work nobody is doing.
  run "$1" "benchmark run manifest" python3 "$PROGRAMS/benchmark_run_manifest.py" check --tree benchmark-data --changed-since "$BASE"
}
landing_unit_cheap_git_prohibition() {
  if [ "$GK_RANGE_N" = "0" ]; then
    landing_skip "$1" "range is empty"
    return 0
  fi
  # PER-RUN, not a fixed name. `tools/gatekeeper-verify-merge.sh` (vibe-ic#1019)
  # runs this script for the BASE and for the CANDIDATE at the same time — two
  # arms of one differential — and a shared `/tmp/gk_*.txt` would have had each
  # arm reading the other's range. A gate that silently answers about the wrong
  # tree is the defect this whole file exists to stop.
  MSGFILE="$(mktemp -t gk_commit_text.XXXXXX)"
  git log --format='%B' "$RANGE" > "$MSGFILE" 2>/dev/null
  run "$1" "git prohibition guard"   python3 "$PROGRAMS/git_prohibition_guard.py" "$MSGFILE"
  rm -f "$MSGFILE"
}
landing_unit_cheap_collateral_revert() {
  if [ "$GK_RANGE_N" = "0" ]; then
    landing_skip "$1" "range is empty"
    return 0
  fi
  # 2026-08-03 — the batch that landed five PRs from a 6.5-hour-stale base and
  # let three of its own commits erase the other two. `gatekeeper_stale_branch_check`
  # said STALE_OVERLAP on all five BEFORE the land; nothing looked at the
  # commits AFTER they existed, which is the artefact this script pushes.
  run "$1" "no collateral revert within the push" \
      python3 "$PROGRAMS/landing_collateral_revert_check.py" --repo "$ROOT" --rev-range "$RANGE"
}
landing_unit_cheap_base_ancestry() {
  if [ "$GK_RANGE_N" = "0" ]; then
    landing_skip "$1" "range is empty"
    return 0
  fi
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
  run "$1" "tree contains the base it claims as parent" \
      python3 "$PROGRAMS/gatekeeper_stale_branch_check.py" --repo "$ROOT" \
          --base "$BASE" --head HEAD
}
landing_unit_cheap_version_sync() {
  run "$1" "marketplace <-> plugin version sync" python3 "$PROGRAMS/marketplace_version_sync_check.py"
}
# vibe-ic#712 — NO LANDING MAY ADD A POLARITY-BLIND PROSE EXTRACTOR.
#
# Whole-tree, so it sits OUTSIDE the range block above with `version-sync`: the
# question is what the tree that ships contains, not what this push touched.
#
# `--ratchet` is a MEMBERSHIP verdict against `_OFFENDER_REGISTER`, not a count.
# MEASURED across v1.17.51..v1.17.83 the population went 212 -> 213 -> 214 ->
# 213 -> 214 -> 215 because entries both ENTER and LEAVE, so the number moved
# DOWN in a window where offenders were arriving; bisecting it names the wrong
# landing. It fails on an offender that is NOT registered — a landing adding one
# — and on a register entry that outlived its offender, so the register cannot
# rot into a list of things that used to be true.
#
# It is NOT the plain no-argument mode: that one compares against a baseline
# debt file and prints an errand naming a write flag. A landing gate must name
# the offender and its owning lane, never a flag that banks it.
landing_unit_cheap_prose_polarity() {
  run "$1" "prose polarity — no landing adds an unregistered offender" \
    python3 "$PROGRAMS/prose_polarity_consulted_check.py" --ratchet
}

# vibe-ic#2138 — A HAND-FED COUNT GUARDING A POPULATION THAT MOVES EVERY
# LANDING MUST GO STALE, SO THE LANDING IS WHERE IT IS CAUGHT.
#
# `tools/ci/trusted_test_selection.py::HERMETIC_TEST_PROGRESS` pins the exact
# collection denominator of four nested-progress test files. `f5474d758` added an item
# to one of them and did not move its pin, and nothing here refused: the guard
# that knows — `tools/ci/test_trusted_test_selection.py::
# test_nested_progress_schedule_matches_live_pytest_collection` — lives in
# `full:repo-tools-tests`, minutes away and skipped entirely by `--cheap-only`,
# which is the pre-push hook's path. So the stale pin reached main and the guard
# fired THERE, where nobody can fix it by pushing again.
#
# WHOLE-TREE, so it sits outside the range block with `version-sync` and
# `prose-polarity`: the question is what the tree that ships contains, not what
# this push touched.
#
# BOTH SIDES FROM THE SUBJECT ($ROOT/$PLUGIN), the program from the instrument
# ($PROGRAMS) — a landing that adds a test AND moves the pin must be green, and
# reading the pin from the BASE would refuse exactly that landing. The subject
# still cannot cheat with it: the merge verifier executes the BASE copy of the
# schedule, never the candidate's, so a moved schedule governs nothing until it
# has landed.
#
# CHEAP: one `pytest --collect-only` over four files. MEASURED on 8HD-9 in the
# pinned image (0.3.48), this lane's clone, three consecutive runs at load
# 12.3-12.7: 4.47 s / 4.27 s / 4.41 s.
landing_unit_cheap_nested_progress_pin() {
  run "$1" "nested-progress item pins match live collection" \
    python3 "$PROGRAMS/nested_progress_pin_check.py" \
        --schedule "$ROOT/tools/ci/trusted_test_selection.py" \
        --plugin-root "$PLUGIN"
}
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
landing_unit_cheap_landing_shape() {
  GK_RANGE_N="$(git rev-list --count "$RANGE" 2>/dev/null || echo 0)"
  if [ "$GK_RANGE_N" = "0" ]; then
    echo "  SKIP  landing shape — range is empty, so there is no landing to shape"
    landing_skip "$1" "range is empty"
  elif [ "$GK_RANGE_N" -gt 1 ]; then
    run "$1" "landing is a valid batch (version on tip)" \
        python3 "$PROGRAMS/landing_is_one_commit_check.py" --base "$BASE" --batch
  else
    run "$1" "landing is one commit" \
        python3 "$PROGRAMS/landing_is_one_commit_check.py" --base "$BASE"
  fi
}

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
landing_unit_cheap_competing_claims_report() {
  if [ "$GK_RANGE_N" = "0" ]; then
    echo "  SKIP  competing claims — range is empty, so there is nothing claimed"
    landing_skip "$1" "range is empty"
  else
    report "$1" "issues claimed by more than one commit in this landing" \
        python3 "$PROGRAMS/competing_pr_claim_groups.py" \
            --repo-root "$ROOT" --rev-range "$RANGE"
  fi
}

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
landing_unit_cheap_worktree_clean() {
  FP="$(mktemp -t gk_fingerprint.XXXXXX)"
  run "$1" "worktree carries no uncommitted change" \
      python3 "$PROGRAMS/landing_worktree_is_clean_check.py" "$ROOT" \
          --emit-fingerprint "$FP"
}


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
landing_unit_cheap_scratch_report() {
  report "$1" "untracked scratch paths in this checkout" \
      python3 "$PROGRAMS/gitignore_scratch_guard.py" --root "$ROOT" \
          --include-worktree
}

# vibe-ic#2176 — THE HYGIENE TIER DOES NOT RUN ON THE LANDING PATH, SO THE
# LANDING PATH MUST ASK ITS QUESTION ITSELF.
#
# The `--cheap-only` exit immediately below this block happens BEFORE
# `--- full tier ---` and therefore before `run_capture "full:repo-hygiene"`,
# the only caller of `tools/ci/repo_hygiene_gates.sh` in this repository. The
# direct-push landing path uses `--cheap-only`, so the 154-gate hygiene tier
# has never run at a landing and the gates it owns are measured only by a
# manual sweep hours later. MEASURED over origin/main across 140 landings on
# 2026-09-07: six of the seven reds on main were introduced that day by our own
# landings, and `shipped-path portability` — BLOCKING since 2026-07-20 — went
# 0 -> 4 (#2158) -> 9 (#2165) without being refused once.
#
# A DELTA, NOT THE GATE. Running the gates themselves here refuses every
# landing: main already carries 9 portability findings and 1 watchdog offender.
# What must be empty is the DIFFERENCE, which is the rule the test tier has had
# since #1019 and which `hygiene_finding_delta.py` was written to give the
# hygiene tier — supplied until now only by `tools/gatekeeper-verify-merge.sh`,
# the PR path, which the direct-push directive never traverses.
#
# RANGE-SCOPED, so it SKIPs over an empty range exactly as the block above
# does: `gatekeeper-verify-merge.sh` runs this script over `X..X` on the BASE
# to learn which gates already fail, and a gate that fails vacuously there
# would let a candidate's real violation be waived as pre-existing.
#
# CHEAP, AND MEASURED RATHER THAN FEARED. Two `git archive` extractions
# (0.54 s, 169 MB each) and two runs of each declared checker. On 8HD-8, this
# lane's clone, load 3.75-4.13: 23.4 / 23.4 / 23.9 s for one gate and 46.8 s
# for the two declared. The hygiene tier itself took 563 s on the same host in
# the same hour, so the whole delta is under 9% of it and the per-gate cost is
# linear and legible — add a gate, add ~23 s.
landing_unit_cheap_hygiene_ratchet() {
  if [ "$GK_RANGE_N" = "0" ]; then
    echo "  SKIP  hygiene ratchet — range is empty, so this landing introduces nothing"
    landing_skip "$1" "range is empty"
  else
    run "$1" "this landing introduces no hygiene finding" \
        python3 "$PROGRAMS/landing_hygiene_ratchet_check.py" \
            --repo "$ROOT" --plugin-root "$PLUGIN" --base "$BASE"
  fi
}

landing_plan_dispatch cheap

if [ "$CHEAP_ONLY" = "1" ]; then
  echo "--- full tier SKIPPED (--cheap-only) — no stamp will be written ---"
  exit "$FAILED"
fi

echo "--- full tier (minutes; stamps the tree on success) ---"

# ── NO CHILD OF THE FULL TIER WRITES BYTECODE (vibe-ic#2008) ───────────────
#
# Every pytest lane below already carries `PYTHONDONTWRITEBYTECODE=1` on its
# own command line and `-B` on its isolated entry (see the note above
# `run_pytest`), `repo_hygiene_gates.sh:52` exports it for the hygiene set and
# `gatekeeper_review.repo_hygiene_gate` sets it for the review's copy of that
# set. What none of those covered is the REST of this tier — the audit lane,
# the closing gates, and every `python3` this file itself spawns between them
# — so a child of one of those could still leave a `.pyc` in the checkout for
# `attestation preflight` to refuse. Exported once, here, at the start of the
# tier that the preflight judges; the per-lane tokens stay, because `python3
# -I` discards this variable and the lanes need the `-B` flag regardless.
export PYTHONDONTWRITEBYTECODE=1

# ── IS THIS CHECKOUT STILL GOING TO BE A REPOSITORY IN AN HOUR? ───────────
#
# A linked worktree's registration lives in a repository this run does not own,
# and `git worktree prune` there removes it MID-RUN. MEASURED: one tier run lost
# four gates to pure collateral that way — four verdicts about the accident
# instead of about the commit, and the run's third measurement lost to something
# outside the measurement.
#
# BEFORE the runtime preflight and before every arm, because it costs
# milliseconds and because a tier that cannot survive its own hour has nothing
# to say later. Deliberately AFTER the `--cheap-only` exit: the cheap tier is
# the pre-push hook's path, it runs in whatever checkout the developer is in,
# and it finishes in seconds — the failure mode this refuses needs an hour to
# happen.
#
# There is no environment escape hatch, on purpose: a flag that permits a
# worktree is a flag that gets exported once and forgotten. The refusal text and
# the remedy belong to the program, so this line and the cause cannot drift.
if ! python3 "$PROGRAMS/landing_tier_checkout_preflight.py" --root "$ROOT"; then
  echo "=== REFUSED — the full tier will not start in a checkout something"
  echo "    outside this run can remove. No arm was run and no stamp was"
  echo "    written. See the cause and remedy above."
  exit 2
fi

# ── CAN THIS HOST LOOK AT ALL? ASKED ONCE, BEFORE THE ARMS ────────────────
#
# The three test arms below run their child through the isolated trusted entry.
# Isolated mode suppresses the USER site directory, so on a host whose test
# runner is installed only there the child dies before emitting one lifecycle
# event and EVERY selected file in EVERY arm is reported NORECORD — UNKNOWN,
# not clean and not red — with no junit test case in existence anywhere.
#
# MEASURED on this host at 7c376e348, the repo-tools arm alone:
#
#     asked 40  recorded 0  NORECORD 40  aggregate INCOMPLETE rc=2 cases=0
#
# Across the three arms that is hundreds of UNKNOWN lines naming hundreds of
# innocent files and not one line naming the cause. The commit that introduced
# it ALREADY KNEW the cause: `tools/ci/test_repo_tools_tests_gate.py:65` skips
# three of its OWN tests with exactly this diagnosis. The knowledge was applied
# to that commit's CI tests and not to this gate, which :47-52 still documents
# as a supported host shape.
#
# A gate that cannot look must say so ONCE, attributably, and name the remedy.
# It must not answer a question it could not ask, hundreds of times, and leave
# the reader to infer why. The probe EXECUTES the real entry on a synthetic
# one-test subject rather than merely importing the runner, because a runtime
# that imports and then cannot report produces the identical every-file-UNKNOWN
# shape. It costs milliseconds against a tier that costs an hour and a half.
#
# The verdict text belongs to the program, not to this line: one owner for the
# cause, so it cannot drift apart. Any nonzero rc stops landing before an arm.
if ! python3 "$PROGRAMS/landing_pytest_runtime_preflight.py"; then
  echo "=== STOPPED — the runtime preflight did not pass; its verdict is above."
  echo "    no arm was run and no stamp was written."
  exit 2
fi

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
landing_unit_full_write_guard_baseline() {
  WG_BASE="$(mktemp -t gk_writeguard.XXXXXX)"
  run "$1" "write-guard baseline" \
      python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" --snapshot "$WG_BASE"
}
landing_plan_dispatch before_window


# ── THE FULL TIER'S INDEPENDENT STAGES RUN AT THE SAME TIME ────────────────
#
# The plan declares a contiguous window between serial producer/consumer
# brackets. Its labels and lane order come from landing_execution_plan.py:
# `cheap:worktree-clean` emits $FP which `full:worktree-fingerprint-final`
# re-checks, and `full:write-guard-baseline` writes $WG_BASE which
# `full:write-guard-final` compares. Four lanes:
#
#   L1  full:targeted-tests
#   L2  repo-tools -> unselectable -> unselectable-census
#       -> census-freshness
#   L3  full:repo-hygiene
#   L4  full:plugin-audit
#
# L2 IS ONE ORDERED LANE AND THAT IS NOT A CONVENIENCE. Its first two stages
# each wrap their own WHOLE-REPO `suite_write_guard` snapshot/compare bracket;
# two brackets spanning the same instant cannot separate a writer from a gate
# that merely overlapped it, which is exactly what `tools/ci/_gate_dispatch.sh`
# already measured ("JOBS=8 wrote_corpus 2 passed 0 — BOTH recorded
# WROTE_CORPUS"). The third stage audits the very corpus the second one ran.
# Ordering them costs nothing: 96.5 s of lane hides inside hygiene's 259 s.
#
# NO SHARED MUTABLE STATE, ASSERTED RATHER THAN ARGUED. The tier's own closing
# gates certify it on EVERY round — "the full tier wrote nothing into the tree"
# and "worktree unchanged since the gates started" — and both brackets are
# taken on the MAIN shell, before any lane starts and after every lane is
# joined, so the window they assert over is WIDER than before, not narrower.
# In a verified arm it is enforced by the kernel instead:
# `hermetic_candidate_runner.py:849-853` refuses unless the subject, runtime
# and corpus binds are read-only. Every lane writes only to `$TMPDIR`, its own
# `mktemp` files, and (L3 only) a git worktree registration under `.git` that
# `git status` never reports. No lane reads another lane's output.
#
# THE PROCESS BUDGET IS CONSTANT — the fan-out RE-ALLOCATES the tier's existing
# budget instead of adding to it. The one measured concurrency harm on record
# is `gates are host-independent` going from 168 s to a 600 s per-worker budget
# KILL, and an arm's 300 s aggregate progress lease turning a green session
# into AGGREGATE_NORECORD, which in `--aggregate-only` mode refuses the whole
# verification. Both are load-sensitive by construction, so the hygiene pool
# gives back exactly what the other lanes take:
#
#     hygiene pool width = budget - (number of OTHER live lanes)
#
# COMPUTED from the lane set actually launched, not configured. Direct-push
# (L1+L2+L4 live): 8-3 = 5. Arm shape, targeted skipped (L2+L4): 8-2 = 6.
# Serial: 8, unchanged. Peak concurrent process count in the tier is 8 in every
# shape, so a neighbouring B1/A1 arm sees the load it sees today.
LANE_LAUNCHED=""                     # names, in declaration order
HYGIENE_POOL=8

# ── THE STOPWATCH: EACH LANE STAMPS ITS OWN [start, end] ───────────────────
#
# WHY THIS EXISTS. This script ran a four-lane window for weeks and reported no
# elapsed time at all, so "which lane is the landing's critical path" could not
# be answered from a landing log — only guessed at from the order the labels
# came out in, which is the EMISSION order and has nothing to do with duration.
# A tier whose cost cannot be attributed is a tier nobody can shorten.
#
# THE STAMPS ARE TAKEN BY THE LANE, NOT AT THE JOIN, AND THAT IS THE WHOLE
# DESIGN. `lane_emit_window` joins in DECLARATION order — targeted, corpus,
# hygiene, audit — and `lane_join targeted` does not return until the longest
# lane the tier launched first has finished. Every later `lane_join` then
# returns immediately, because its lane finished while the main shell was
# blocked on the first one. So an end stamp taken at the join measures WHEN THE
# MAIN SHELL GOT ROUND TO ASKING, which is the barrier, not the work: every
# lane reads back the same number and the report says the tier has four equally
# expensive lanes however lopsided it really is. MEASURED: an earlier
# join-stamped version of this instrument reported all four lanes as 1117 s.
# Stamped by the lane itself the same tier reads targeted 1736 s, hygiene
# 1259 s, corpus 518 s, audit 26 s.
#
# INTEGER SECONDS, from `date +%s`. The quantity being reported is a
# multi-minute stage and the consumer is a human reading a log; sub-second
# resolution would be precision this cannot honestly claim, since the stamp
# brackets a `wait` and a fork.
#
# IT CANNOT MOVE A VERDICT, BY CONSTRUCTION. `lane_timed` returns its body's
# own status unchanged and the report is printed after the window is closed and
# every unit already emitted. A stopwatch that could fail a landing would be a
# second gate wearing an instrument's name.
lane_stamp() {                       # lane_stamp <name> <t0|t1>
  # Written atomically, for the same reason `.rc` is: a half-written stamp and
  # an absent stamp must not be the same state on disk. An absent one is
  # reported as absent below, never as zero.
  printf '%s' "$(date +%s)" > "$LANE_DIR/$1.$2.tmp" \
    && mv -f "$LANE_DIR/$1.$2.tmp" "$LANE_DIR/$1.$2"
}
lane_timed() {                       # lane_timed <name> <fn…>
  local name="$1"; shift
  local rc=0
  lane_stamp "$name" t0
  "$@" || rc=$?
  # NOT in a trap and NOT after an `exit`: this line is reached only when the
  # body RETURNED. A lane that was killed leaves `t0` and no `t1`, which is the
  # honest record of a lane that never finished — and `lane_report_window`
  # prints it as NO END STAMP rather than inventing a duration for it.
  lane_stamp "$name" t1
  return "$rc"
}
# THE REPORT. Printed after the window is joined and emitted, from the MAIN
# shell only. Three numbers, because one of them alone would mislead:
# the per-lane elapsed (what each lane cost), the WINDOW span (what the tier
# actually waited, = the critical path), and the SERIAL sum (what the same work
# would have cost one after another). The ratio is the concurrency actually
# obtained, which is the only honest answer to "was the window worth it".
#
# ONE ROUND PER CALL, BECAUSE A LANDING CAN HAVE TWO. When
# `lane_window_saw_a_write` fires, the whole window runs a second time at width
# 1 -- and `lane_window_reset` deliberately clears `.rc`/`.out`/`.reported` and
# NOT `.t0`/`.t1`, while `lane_stamp` truncates. So round 2's stamps landed on
# top of round 1's and the single report at the end described the SERIAL round
# and called it the tier. MEASURED by driving `lane_stamp` and this function
# with a lopsided tier (targeted 1736 / hygiene 1259 / corpus 518 / audit 26)
# and then a serial re-run of the same work:
#
#   what round 1 alone says   window 1736s wall vs 3539s serial -- 2.04x
#   what was actually printed window 3539s wall vs 3539s serial -- 1.00x
#
# On the one landing shape that costs the most wall clock, the log said the
# tier obtained NO concurrency. It obtained 2.04x and then paid for a full
# serial repeat on top, and neither number survived. The re-run is also the
# single largest wall-clock event this script can have, so it is the last
# reading that should be silently overwritten.
#
# THE STAMPS ARE ARCHIVED, NOT RE-READ FROM A SECOND CLOCK. Before the re-run
# starts, round 1's stamps are MOVED aside under a suffix and each round is
# then reported against its own. There is deliberately no fallback clock: the
# only other stamps in reach are the parent's, whose difference is the barrier
# -- the very number this instrument exists to stop printing.
#
# STILL CANNOT MOVE A VERDICT. Every function here returns 0 unconditionally,
# touches no `FAILED`, and writes no `.rc`.
lane_stamps_archive() {              # lane_stamps_archive <round-suffix>
  local name
  for name in $LANE_LAUNCHED; do
    # `mv` only what exists. A lane that left no stamp must stay unstamped in
    # the archive too, so the round-1 report says NO ELAPSED RECORD for it
    # rather than inheriting round 2's.
    [ -f "$LANE_DIR/$name.t0" ] && mv -f "$LANE_DIR/$name.t0" "$LANE_DIR/$name.$1.t0"
    [ -f "$LANE_DIR/$name.t1" ] && mv -f "$LANE_DIR/$name.t1" "$LANE_DIR/$name.$1.t1"
  done
  printf '%s' "$LANE_LAUNCHED" > "$LANE_DIR/lanes.$1"
  return 0
}
#: Set by `lane_report_round` so the caller can state the cost ACROSS rounds.
#: A round that measured nothing leaves them empty rather than 0 -- an
#: unmeasured round and a zero-length one are not the same state.
LANE_ROUND_WINDOW=""
LANE_ROUND_SUM=""
lane_report_round() {                # lane_report_round <suffix> <lane-list>
  local sfx="$1" lanes="$2"
  local name t0 t1 elapsed sum=0 first="" last="" measured=0 missing=""
  LANE_ROUND_WINDOW=""; LANE_ROUND_SUM=""
  for name in $lanes; do
    t0="$(cat "$LANE_DIR/$name$sfx.t0" 2>/dev/null || true)"
    t1="$(cat "$LANE_DIR/$name$sfx.t1" 2>/dev/null || true)"
    case "${t0:-x}${t1:-x}" in
      *[!0-9]*) missing="$missing $name"; continue ;;
    esac
    elapsed=$(( t1 - t0 ))
    sum=$(( sum + elapsed ))
    measured=$(( measured + 1 ))
    if [ -z "$first" ] || [ "$t0" -lt "$first" ]; then first="$t0"; fi
    if [ -z "$last" ]  || [ "$t1" -gt "$last" ];  then last="$t1";  fi
    printf '  REPORT  lane %-9s %6ss\n' "$name" "$elapsed"
  done
  # "I COULD NOT LOOK" IS SAID, NEVER ABSORBED. A lane with no end stamp did
  # not finish; leaving it out of the list silently would make the sum below
  # read as the whole tier's cost when it is not.
  for name in $missing; do
    printf '  REPORT  lane %-9s NO ELAPSED RECORD — it left no end stamp, so it did not finish\n' "$name"
  done
  # A span needs at least two stamps and a ratio needs a non-zero window; both
  # are refused rather than divided by zero or printed as 1.00x.
  if [ "$measured" -eq 0 ]; then
    echo "  REPORT  lane elapsed: NOT MEASURED — no lane left a complete stamp pair"
    return 0
  fi
  local window=$(( last - first ))
  if [ "$window" -le 0 ]; then
    printf '  REPORT  window %ss wall, %ss if serial (%s lane(s) measured%s); ratio NOT COMPUTED over a zero-length window\n' \
      "$window" "$sum" "$measured" "${missing:+, $(set -- $missing; echo $#) unmeasured}"
    return 0
  fi
  printf '  REPORT  window %ss wall vs %ss serial — %sx over %s lane(s)%s\n' \
    "$window" "$sum" \
    "$(awk -v s="$sum" -v w="$window" 'BEGIN{printf "%.2f", s/w}')" \
    "$measured" "${missing:+, $(set -- $missing; echo $#) lane(s) unmeasured}"
  LANE_ROUND_WINDOW="$window"; LANE_ROUND_SUM="$sum"
  return 0
}
lane_report_window() {
  # NO ARCHIVE = ONE ROUND = the output this script printed before rounds were
  # told apart, byte for byte. The two-round shape is entered only when the
  # re-run actually happened, so the ordinary landing's log does not change.
  if [ ! -f "$LANE_DIR/lanes.concurrent" ]; then
    lane_report_round "" "$LANE_LAUNCHED"
    return 0
  fi
  local w1 w2
  echo "  REPORT  round 1 of 2 — the CONCURRENT window:"
  lane_report_round ".concurrent" "$(cat "$LANE_DIR/lanes.concurrent")"
  w1="$LANE_ROUND_WINDOW"
  echo "  REPORT  round 2 of 2 — the SERIAL re-run forced by the write guard:"
  lane_report_round "" "$LANE_LAUNCHED"
  w2="$LANE_ROUND_WINDOW"
  # THE TIER PAID BOTH, and neither round alone says so. Stated only when both
  # rounds measured something; a round that could not be measured makes the
  # total unknowable and it is refused rather than reported as the other half.
  if [ -n "$w1" ] && [ -n "$w2" ]; then
    printf '  REPORT  this tier cost %ss wall in total — %ss concurrent THEN %ss serial; the re-run is not free and is not an overlap\n' \
      "$(( w1 + w2 ))" "$w1" "$w2"
  else
    echo "  REPORT  total across the two rounds: NOT MEASURED — one round left no complete stamp pair, and the other half is not the total"
  fi
  return 0
}
lane_launch() {                      # lane_launch <name> <fn…>
  local name="$1"; shift
  eval "LANE_JOINED_$name="; eval "LANE_RC_$name=0"
  eval "LANE_PID_$name=";    eval "LANE_BODY_$name="
  if [ "$LANE_WIDTH" -le 1 ]; then
    # WIDTH 1 IS THE SAME SCHEDULER, NOT A SECOND IMPLEMENTATION. The body is
    # DEFERRED to the join so the serial order is the DECLARATION order —
    # targeted, corpus, hygiene, audit — which is exactly the order this script
    # ran these stages in before lanes existed.
    eval "LANE_BODY_$name=\"lane_timed $name \$*\""
  else
    # THE PID COMES BACK IN A VARIABLE, NOT ON STDOUT. `PID="$(lane_launch …)"`
    # would start the job inside the command substitution's OWN subshell, so
    # `wait "$PID"` in the main shell fails with "not a child of this shell" —
    # the lane would be unwaited, unjoined, and its non-zero exit would never
    # reach FAILED. A gate that cannot fail is worse than no gate.
    #
    # `set -m` gives the lane its own PROCESS GROUP so the EXIT trap's
    # `kill -- -PID` reaches its whole descendant tree; without it, killing the
    # lane shell leaves pytest and hygiene children running against a tree the
    # closing gates have already stamped.
    #
    # stdin from /dev/null and BOTH output channels into a named lane log: the
    # labelled stream on stdout belongs to the main shell alone. Anything a
    # lane prints outside `lane_write` would otherwise land between two labels
    # and be read as belonging to one of them.
    set -m
    ( lane_timed "$name" "$@" ) </dev/null >"$LANE_DIR/$name.lane.log" 2>&1 &
    eval "LANE_PID_$name=\$!"
    set +m
    eval "LANE_LIVE_PIDS=\"\$LANE_LIVE_PIDS \$LANE_PID_$name\""
  fi
  LANE_LAUNCHED="$LANE_LAUNCHED $name"
}
lane_join() {                        # lane_join <name>   → LANE_WAIT_RC/LANE_BROKEN
  # IDEMPOTENT. The window is joined once as a whole (so the write-guard
  # attribution question can be asked with every lane terminal) and then again,
  # lane by lane, as the emits walk the units in order. A second `wait` on a
  # reaped PID reports failure, so the first join's verdict is REMEMBERED
  # rather than re-measured.
  local name="$1" pid body rc=0 joined
  eval "joined=\"\${LANE_JOINED_$name:-}\""
  if [ -z "$joined" ]; then
    eval "pid=\"\${LANE_PID_$name:-}\""
    if [ -z "$pid" ]; then
      eval "body=\"\${LANE_BODY_$name:-}\""
      [ -z "$body" ] || { $body </dev/null >"$LANE_DIR/$name.lane.log" 2>&1 || rc=$?; }
    else
      wait "$pid" || rc=$?
      # Drop it from the reaping set: the EXIT trap must not signal a PID the
      # kernel may already have recycled onto somebody else's process.
      LANE_LIVE_PIDS="$(printf '%s\n' ${LANE_LIVE_PIDS:-} \
        | grep -vx "$pid" | tr '\n' ' ')"
    fi
    eval "LANE_RC_$name=\$rc"
    eval "LANE_JOINED_$name=1"
  fi
  eval "LANE_WAIT_RC=\$LANE_RC_$name"
  LANE_BROKEN=0
  [ "$LANE_WAIT_RC" -eq 0 ] || LANE_BROKEN=1
}
# EVERY UNIT IN THE WINDOW GETS A RECORD SLOT BEFORE ANY LANE STARTS. The
# literal `NORECORD` is what `lane_resolve` turns into a labelled FAIL, so a
# unit whose lane never reached it is IMPOSSIBLE to read as a pass and
# impossible to read as absent.
# LANE_WINDOW_UNITS is derived from the approved execution plan at startup.
lane_window_reset() {
  local unit
  for unit in "${LANE_WINDOW_UNITS[@]}"; do
    printf 'NORECORD' > "$LANE_DIR/$unit.rc"
    : > "$LANE_DIR/$unit.out"
    # The report marker is EVIDENCE FROM THIS ROUND. A stale one from the
    # serial re-run's predecessor would vouch for a stage this round killed.
    rm -f "$LANE_DIR/$unit.reported" "$LANE_DIR/$unit.reported.tmp"
  done
  rm -f "$LANE_DIR/targeted.norecord"
}

# The TARGETED TEST RUN, carried over verbatim from the retired ci.yml:130-132.
# Omitted from the first version of this script, which covered the governance
# gates and quietly dropped the tests — the gap surfaced when
# `ci_harness_timeout_ceiling_check` lost its input and reported CANNOT
# DETERMINE rather than passing.
#
# No fixed elapsed-time limit participates in this verdict.  The driver below
# observes pytest's validated collection/test lifecycle protocol, owns the
# complete descendant process tree, and has no total runtime ceiling.  A test
# that keeps completing finite semantic work may therefore take as long as it
# needs.  A session whose lifecycle stops produces NORECORD, never a fabricated
# test failure and never a partial green JUnit.
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
# ── WHAT A RED LANE MUST SAY, IN ONE PLACE FOR ALL THREE LANES ────────────
#
# The three pytest lanes drive the SAME driver and reported it three different
# ways: `run_pytest` grepped the driver's greppable prefixes and then tailed;
# `run_repo_tools_pytest` and `run_unselectable_pytest` only tailed. `tail -6`
# is EXACTLY the six lines of the driver's summary block, so in those two lanes
# a `NORECORD` line -- a file whose result is UNKNOWN, the one thing a reader
# cannot reconstruct from a tail -- was computed, printed into `$out`, and
# discarded. MEASURED on both 2026-08-31 full tiers: `repo tools tests` said
# `NORECORD 2` in each, and neither log names either file. Recovering them took
# re-running the lane with `GATEKEEPER_REPO_TOOLS_JUNIT` exported and
# differencing the 65-file discovery against the 63 per-file suites in the
# report; they are `tools/ci/test_dispatch_shell_harnesses.py` and
# `tools/test_gatekeeper_land_lanes.py`.
#
# `suite_write_guard:` rides along for a reason measured on 2026-08-31 while
# triaging this very run. `unselectable tests` FAILED in three separate landing
# tiers with `aggregate complete rc=1 cases=1341 red=0` -- a refusal with NOT ONE
# red test case behind it. `pytest_per_file_junit.py` returns RC_RED on a
# non-zero session status even when the XML is green, and its own comment names
# the expected author: "Session-level guards such as this repo's
# `suite_write_guard` legitimately set session.exitstatus = 1 after every
# testcase has passed". The guard PRINTS the offending paths. `tail -6` is the
# summary block, so that print never reached the log, and isolating the cause
# cost three container arms, a full instrumented tier and a 0.2 s `git status`
# watcher -- which found two transient blocking-class writes into the shared
# worktree (`programs/_i528_planted_unrouted_check.py`, planted by
# `programs/tests/test_gate_skip_routing_check.py`, ~6 s; and `programs/INDEX.md`
# MODIFIED for ~20 s) while four lanes shared it. The gate had the answer and
# threw it away.
#
# `^RED ` rides along with the same argument: the driver now prints every red
# case by name whether or not the session truncated, so a lane that does not
# grep for it throws the answer away for the second time.
#
# IT CHANGES NO VERDICT. `rc` still decides every one of these lines; this
# function only prints, and it prints what the driver already computed.
lane_report_out() {                  # lane_report_out <driver stdout>
  printf '%s\n' "$1" \
    | grep -a '^NORECORD\|^NOTRUN\|^AGGREGATE_NORECORD\|^AGGREGATE_TRUNCATED\|^FILE_TRUNCATED\|^TRUNCATED_RED\|^RED \|suite_write_guard:\|written by ' \
    | sed 's/^/          /'
  printf '%s\n' "$1" | tail -6 | sed 's/^/          /'
}
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
    FAILED=1; return 1
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
  # THE SELECTION IS THE CADENCE, EXPRESSED. A FULL milestone runs the whole
  # `programs/tests` tree (pytest.ini pins it as the single testpath, so that
  # tree IS the full suite); a TARGETED patch runs the diff-derived subset,
  # which is exactly what this line did for every bump before the wire existed.
  #
  # ONE INSTRUMENT, BOTH TIERS. FULL does not get a second code path: it gets a
  # longer selection file handed to the same per-file driver, the same aggregate
  # session, the same write guard and the same junit. A milestone that was
  # measured by a different instrument than a patch could not be compared with
  # one, and the asymmetry #1417 spent a version removing would be back.
  if [ "$LANDING_CADENCE" = "FULL" ]; then
    ( cd "$PLUGIN" && python3 programs/landing_cadence.py \
        --plugin-root "$PLUGIN" --emit-full-selection > "$sel" ) 2>/dev/null
  else
    ( cd "$PLUGIN" && python3 programs/ci_targeted_test_select.py --base "$BASE" > "$sel" ) 2>/dev/null
  fi
  if [ ! -s "$sel" ]; then
    echo "  FAIL  targeted test selection produced no files — not a clean result"
    FAILED=1; rm -f "$sel"; return
  fi
  # WHAT THIS RUN CAN HONESTLY CLAIM, DERIVED FROM THE SELECTION IT IS ABOUT TO
  # EXECUTE — never from `$LANDING_CADENCE`. Reporting the full-suite string
  # because the cadence SAYS full, while the selection is short, is precisely
  # the false green the cadence gate exists to refuse; `--describe` compares the
  # selection against the tree by MEMBERSHIP and only then emits the full-suite
  # command. At FULL cadence a short selection therefore describes itself as a
  # subset, and `full_suite_run_check` turns that into the red it should be.
  #
  # THROUGH A FILE, because run_pytest runs inside a lane subshell and a
  # variable set here never reaches the main shell that calls the review — the
  # same lesson `$LANE_DIR/targeted.norecord` records one screen down.
  ( cd "$PLUGIN" && python3 programs/landing_cadence.py \
      --plugin-root "$PLUGIN" --selection "$sel" --describe 2>/dev/null \
      | sed -n 's/^LANDING_PYTEST_CMD=//p' ) > "$LANE_DIR/pytest-cmd.txt" || true
  printf '  REPORT  cadence %s — %s file(s) selected\n' \
    "$LANDING_CADENCE" "$(wc -l < "$sel")"
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
  # no third-party entry-point plugin.  The progress plugin is loaded by the
  # trusted driver through its explicit module path; pytest-timeout is
  # deliberately absent because elapsed time is not a test verdict.
  #
  # `suite_write_guard` is UNAFFECTED and must stay that way: conftest.py loads it
  # through `pytest_plugins`, not through an entry point, so disabling autoload does
  # not disarm the write guard. That is the check that would have made this fix a
  # false green, so it is asserted rather than assumed — the guard's PASS/FAIL line
  # must still appear in `out`.
  #
  # ── ONE WHOLE-SELECTION SESSION ON THE LANDING CRITICAL PATH (#1654) ──
  #
  # A fixed pytest timeout cannot interrupt a blocking `waiter.acquire()` as a
  # test failure. It dumps every thread's stack and takes the PROCESS down, and
  # a process that dies never writes its `--junitxml`. So ONE hanging file used to cost the
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
  # THE PYTEST COMMAND IS PASSED IN VERBATIM, not built inside the driver.  It
  # intentionally carries no fixed timeout: only the driver's strict semantic
  # lifecycle lease may classify the run NORECORD.
  # `PYTHONDONTWRITEBYTECODE=1` FREEZES THE HOST-INDEPENDENCE GATE'S STIMULUS.
  # `gate_host_independence_check.py` takes the checkout's UNTRACKED + IGNORED
  # paths AS ITS SUBJECT (:209 says `tracked` invalidates the comparison,
  # `untracked` + `ignored` ARE the comparison; :407 collects them with
  # `git status --ignored=traditional`). Bytecode churn from a neighbouring
  # lane is written straight into that set, and losing the race does not fail
  # louder — `run_tolerating_uncheckable` downgrades it to NOT CHECKED (rc 2,
  # non-fatal), which is a check made WEAKER by parallelism and is forbidden.
  # `python3 -I` does not imply `-B` -- AND IT DOES NOT SEE THE VARIABLE
  # EITHER: `-I` implies `-E`, which discards every `PYTHON*` name from the
  # environment. So the variable below freezes the DRIVER (`pytest_per_file_
  # junit.py`, no `-I`) and the `-B` flag on the isolated entry freezes the
  # child that actually imports the tests. Both halves are required; supplying
  # only the variable is what shipped, and it wrote 500+ `.pyc` into $ROOT in
  # 7 minutes of one landing. It does not make the gate check less: it
  # makes the stimulus the checkout's PRE-EXISTING dirt, which is exactly what
  # that gate's own docstring says its subject is, and it makes that stimulus
  # IDENTICAL between the serial and the concurrent shape.
  if out="$( cd "$PLUGIN" && PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 programs/pytest_per_file_junit.py \
        --selection "$sel" --junit "$merged" \
        --stall-after "${GATEKEEPER_PYTEST_FILE_STALL_AFTER:-300}" \
        --aggregate-check \
        --aggregate-stall-after "${GATEKEEPER_PYTEST_AGGREGATE_STALL_AFTER:-300}" \
        --fallback-jobs "${GATEKEEPER_PYTEST_FALLBACK_JOBS:-8}" \
        --fallback-rescue-jobs "${GATEKEEPER_PYTEST_RESCUE_JOBS:-32}" \
        --stop-after-failures "${GATEKEEPER_PYTEST_MAXFAIL:-10}" \
        -- python3 -I -B "$PROGRAMS/trusted_pytest_entry.py" -q \
        -p no:cacheprovider \
        "${maxfail[@]+"${maxfail[@]}"}" 2>&1 )"; then
    rc=0
    printf '  PASS  targeted tests (%s file(s))\n' "$(wc -l < "$sel")"
    # PAIRED GUARD for the autoload pin above. A green bought by quietly removing
    # the write guard from the session would be a false green, and it would look
    # exactly like this one. The guard reports on every session it is loaded into,
    # so its absence from the output means it did not run.
    if ! grep -qa 'suite_write_guard:' <<<"$out"; then
      echo "  FAIL  suite_write_guard did not report — the session ran WITHOUT the"
      echo "        write guard, so 'the suite wrote nothing' was never checked."
      FAILED=1
    fi
  else
    rc=$?
    printf '  FAIL  targeted tests (%s file(s))\n' "$(wc -l < "$sel")"
    # THE FILES WITH NO RECORD, ALWAYS AND FIRST. They are the one thing a
    # reader cannot reconstruct from the tail of a 91-file run, and `tail -6`
    # would show whichever file happened to be last instead of the one that
    # cost the record.
    # `TRUNCATED` lines ride along: a session that stopped at its own declared
    # failure bound has ALREADY printed the red case names, and on the
    # 2026-08-31 full tier those names were computed inside $out and never
    # reached this log — the only copy died with the --rm container.
    lane_report_out "$out"
    FAILED=1
    # THROUGH A FILE, because this stage now runs in a lane and a variable set
    # in a subshell never reaches the main shell. The refusal below reads the
    # file; a variable would have read 0 forever and silently disarmed the
    # absolute NORECORD refusal.
    [ "$rc" -eq 2 ] && { TARGETED_NORECORD=1; : > "$LANE_DIR/targeted.norecord"; }
  fi
  # `grep -q … <<<"$out"`, NEVER `printf … | grep -q …`. THE PIPE FORM ANSWERS
  # THE WRONG QUESTION, AND IT ANSWERS IT IN THE PERMISSIVE DIRECTION.
  #
  # This file runs under `set -o pipefail`. `grep -q` exits the instant it
  # matches; if the buffer is bigger than a pipe can hold, `printf` is still
  # writing, takes SIGPIPE, and the PIPELINE's status becomes 141 — so a MATCH
  # is reported to the `if` as a NON-match. MEASURED, this shell, 1.75 MB
  # buffer, `^AGGREGATE_NORECORD`:
  #
  #     match on the FIRST line   → 141 141 141 141 141 141 141 141 141 141 141 141
  #     match on the LAST line    →   0   0   0   0   0   0
  #
  # The verdict therefore depended on WHERE in the driver's output the marker
  # landed and on how the two processes were scheduled — not on the subject.
  # Caught by exactly that: two rounds over one frozen tree whose targeted arms
  # were byte-identical (same 18 files, same AGGREGATE_NORECORD text, same 382
  # cases) printed DIFFERENT labels, `targeted aggregate session produced no
  # status` and `… produced no complete record`.
  #
  # THE DIRECTION IS WHAT MAKES IT A DEFECT AND NOT A WART. For the NORECORD /
  # NOTRUN / AGGREGATE_NORECORD probes a 141 MISSES A REAL REFUSAL — "I could
  # not look" reaching the reader as "I looked and it was fine", which is the
  # one direction this battery exists to make impossible. It also renames a
  # gate between two arms that `landing_merge_verdict` subtracts BY PRINTED
  # LABEL, so the differential reads one gate as two.
  #
  # A herestring has no pipe, no second process and no SIGPIPE, and asks the
  # identical question of the identical bytes.
  #
  # Human-facing diagnostics only. The merge verdict does NOT trust this mixed
  # driver/subject stdout channel: pytest can print marker-looking text. It
  # derives completeness from exact process suites in the merged JUnit.
  if grep -qa '^=== pytest junit summary' <<<"$out"; then
    printf '  REPORT  targeted test process verdicts embedded in junit\n'
  else
    printf '  FAIL  targeted test instrument produced no junit summary\n'
    FAILED=1
  fi
  if grep -qa '^NORECORD' <<<"$out"; then
    printf '  FAIL  targeted per-file session produced no complete record\n'
    FAILED=1
  fi
  if grep -qa '^NOTRUN' <<<"$out"; then
    printf '  FAIL  targeted per-file session was not run\n'
    FAILED=1
  fi
  if grep -qa '^AGGREGATE_NORECORD' <<<"$out"; then
    printf '  FAIL  targeted aggregate session produced no complete record\n'
    FAILED=1
  elif grep -qa '^AGGREGATE_COMPLETE' <<<"$out"; then
    printf '  REPORT  targeted aggregate session completed\n'
  else
    printf '  FAIL  targeted aggregate session produced no status\n'
    FAILED=1
  fi
  rm -f "$sel"
  if [ -n "$merged_tmp" ]; then rm -f "$merged_tmp"; fi
}
landing_unit_full_targeted_tests() {
  fn_capture "$1" run_pytest
}
lane_targeted() {
  landing_plan_dispatch window targeted
}

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
#
# ONE PRUNE, AND IT IS NOT A ROSTER. `tools/harvest/` holds RESCUE SNAPSHOTS —
# files another workspace left untracked, copied in verbatim so the work was not
# lost. They are not this repository's tests: they import fixtures that live
# beside them in the workspace they came from, so `find` selects them and every
# one dies in setup. Measured on e265f228be, serial: 30 of the 30 ERRORs in this
# stage were exactly those three files, and there were no others.
#
# This stays a PRUNE of one directory, never a list of files: a file list would
# go stale in the safe-looking direction the moment a snapshot gained a file,
# which is the disease the comment above is about. And the prune is checked in
# both directions by `tools/test_repo_tools_discovery_prunes_harvest.py` — an
# exclusion that cannot go red is an exclusion that hides the thing it excluded.
run_repo_tools_pytest() {
  local files out rc wg wrc snap list merged
  mapfile -t files < <(cd "$ROOT" && find tools \
      -path 'tools/harvest' -prune -o \
      \( -name 'test_*.py' -o -name '*_test.py' \) -type f -print | sort)
  # An empty corpus is a VACUOUS pass, not a pass. A gate that reports success
  # over zero items is indistinguishable from one that works, and is worse.
  if [ "${#files[@]}" -eq 0 ]; then
    echo "  FAIL  repo tools tests: discovery matched NO files under tools/ —"
    echo "        an empty corpus is not evidence that anything passed."
    FAILED=1; return 1
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
    FAILED=1; rm -f "$snap"; return 1
  }
  list="$(mktemp -t gk_tools_sel.XXXXXX)"
  # `GATEKEEPER_REPO_TOOLS_JUNIT=<path>` keeps this lane's report instead of
  # deleting it, and it is the MIRROR of `GATEKEEPER_PYTEST_JUNIT` in
  # `run_pytest` — same shape, same discipline, same non-participation in the
  # verdict. Read that block for the reasoning; only what is specific to this
  # lane is repeated here.
  #
  # WHY IT WAS MISSING IS WHY IT IS NEEDED. This lane already merged a full
  # per-file JUnit — every case name, every failure message — and then
  # `rm -f`'d it three lines later, unconditionally. Inside a `--rm` container
  # nothing outlives the process, so the report existed for the length of one
  # function and was destroyed with the only copy. What survived to the operator
  # was the count in the FAIL line below and nothing else.
  #
  # MEASURED, on this repository, 2026-08-29: a full tier reported "28 red
  # cases" here and "8 red cases" in `run_unselectable_pytest`, and the names
  # were already gone. Recovering what this lane had ALREADY COMPUTED took a
  # re-measurement of 810 files across five machines. A 46-minute gate that
  # cannot say WHICH case is red has produced a number, not a result.
  #
  # IT CHANGES NO VERDICT. `rc` below is still the only thing that decides this
  # line, and with the variable unset the command issued is byte-for-byte the
  # one this file has always issued: the merge target is still a `mktemp`, it is
  # still removed, and `--junit` is passed either way. This can only ADD a
  # readable record.
  local merged_tmp=""
  merged="${GATEKEEPER_REPO_TOOLS_JUNIT:-}"
  if [ -z "$merged" ]; then
    merged_tmp="$(mktemp -t gk_tools_junit.XXXXXX)"
    merged="$merged_tmp"
  else
    # REMOVE THE TARGET FIRST — see the same removal in `run_pytest`. A lane
    # that dies without writing must leave NO report, because a leftover from
    # an earlier run parses, looks complete, and describes a different session.
    # Absence is honest; a stale green report is not.
    rm -f "$merged" 2>/dev/null || true
  fi
  printf '%s\n' "${files[@]}" > "$list"
  # `PYTHONDONTWRITEBYTECODE=1` — see the note in `run_pytest`. This stage is
  # the one that MEASURABLY writes bytecode into $ROOT on main today: it never
  # set the token, and setting the token alone would not have been enough
  # because `python3 -I` implies `-E` and discards it. The `-B` on the
  # isolated entry is the half that reaches the writer. That churn lands in
  # `gate_host_independence_check`'s untracked+ignored stimulus set, which is
  # the one ordering hazard concurrency here would otherwise create.
  out="$( cd "$ROOT" && PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
        python3 "$PROGRAMS/pytest_per_file_junit.py" \
        --selection "$list" --junit "$merged" --cwd "$ROOT" \
        --stall-after "${GATEKEEPER_PYTEST_FILE_STALL_AFTER:-300}" \
        --aggregate-check \
        --aggregate-stall-after "${GATEKEEPER_PYTEST_AGGREGATE_STALL_AFTER:-300}" \
        --fallback-jobs "${GATEKEEPER_PYTEST_FALLBACK_JOBS:-8}" \
        --fallback-rescue-jobs "${GATEKEEPER_PYTEST_RESCUE_JOBS:-32}" \
        --stop-after-failures 0 \
        -- python3 -I -B "$PROGRAMS/trusted_pytest_entry.py" -q \
        -p no:cacheprovider 2>&1 )"
  rc=$?
  wg="$(python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" \
        --compare "$snap" 2>&1)"; wrc=$?
  # Only the temporary target is removed. When the operator named a path, the
  # report is theirs and this lane must not destroy it — that deletion is the
  # entire defect being fixed.
  rm -f "$snap" "$list" ${merged_tmp:+"$merged_tmp"}
  if [ "$rc" -ne 0 ]; then
    printf '  FAIL  repo tools tests (%s file(s))\n' "${#files[@]}"
    lane_report_out "$out"
    FAILED=1; return 1
  fi
  # rc 0 clean / 1 wrote / 2 NOT_CHECKED. 2 is NOT a pass: "I could not look"
  # must never reach a reader as "I looked and it was fine".
  if [ "$wrc" -ne 0 ]; then
    printf '  FAIL  repo tools tests wrote to the tree (write-guard rc=%s)\n' "$wrc"
    printf '%s\n' "$wg" | tail -8 | sed 's/^/          /'
    FAILED=1; return 1
  fi
  printf '  PASS  repo tools tests (%s file(s))\n' "${#files[@]}"
  return 0
}

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
  local files out rc wg wrc snap list lrc merged
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
    FAILED=1; rm -f "$list"; return 1
  fi
  mapfile -t files < "$list"
  if [ "${#files[@]}" -eq 0 ]; then
    echo "  FAIL  unselectable tests: the complement is EMPTY — either every"
    echo "        tree is genuinely covered (say so by declaring it) or the"
    echo "        census broke. A gate over zero items is not a pass."
    FAILED=1; rm -f "$list"; return 1
  fi
  # As in `run_repo_tools_pytest`: the in-process `suite_write_guard` is loaded
  # by the PLUGIN conftest, and this session's rootdir is not guaranteed to be
  # it, so the same property is asserted from the outside via the same program
  # rather than quietly dropped.
  snap="$(mktemp -t gk_unsel_wg.XXXXXX)"
  python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" \
      --snapshot "$snap" >/dev/null 2>&1 || {
    echo "  FAIL  unselectable tests: could not baseline the tree — not a pass"
    FAILED=1; rm -f "$snap" "$list"; return 1
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
  # `GATEKEEPER_UNSELECTABLE_JUNIT=<path>` keeps this lane's report instead of
  # deleting it — the same mirror of `GATEKEEPER_PYTEST_JUNIT` that
  # `run_repo_tools_pytest` above carries, for the same measured reason, and it
  # matters MORE here. This corpus is by construction the tests that NO diff can
  # select: when one of them is red, no targeted run will ever name it again, so
  # this lane's report is the only place the name is ever written down.
  #
  # IT CHANGES NO VERDICT. `rc` below still decides this line; with the variable
  # unset the command is byte-for-byte the one this file has always issued.
  local merged_tmp=""
  merged="${GATEKEEPER_UNSELECTABLE_JUNIT:-}"
  if [ -z "$merged" ]; then
    merged_tmp="$(mktemp -t gk_unsel_junit.XXXXXX)"
    merged="$merged_tmp"
  else
    rm -f "$merged" 2>/dev/null || true
  fi
  out="$( cd "$ROOT" && PYTHONDONTWRITEBYTECODE=1 \
        PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
        python3 "$PROGRAMS/pytest_per_file_junit.py" \
        --selection "$list" --junit "$merged" --cwd "$ROOT" \
        --stall-after "${GATEKEEPER_PYTEST_FILE_STALL_AFTER:-300}" \
        --aggregate-check \
        --aggregate-stall-after "${GATEKEEPER_PYTEST_AGGREGATE_STALL_AFTER:-300}" \
        --fallback-jobs "${GATEKEEPER_PYTEST_FALLBACK_JOBS:-8}" \
        --fallback-rescue-jobs "${GATEKEEPER_PYTEST_RESCUE_JOBS:-32}" \
        --stop-after-failures 0 \
        -- python3 -I -B "$PROGRAMS/trusted_pytest_entry.py" -q \
        -p no:cacheprovider 2>&1 )"
  rc=$?
  wg="$(python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" \
        --compare "$snap" 2>&1)"; wrc=$?
  # Only the temporary target is removed; a named report belongs to the operator.
  rm -f "$snap" "$list" ${merged_tmp:+"$merged_tmp"}
  # THE COUNT IS NOT IN THE LABEL, and that is deliberate. #1431: the two arms
  # of `gatekeeper-verify-merge.sh` subtract gate logs BY PRINTED LABEL, so a
  # label carrying a discovery count renames its own gate whenever a branch adds
  # a test file — and the verdict then reads a repaired gate as a silenced one.
  # This corpus grows with every new tree, which is exactly the branch shape
  # that would trip it, so the count is REPORTED on its own line instead.
  printf '        unselectable corpus: %s file(s)\n' "${#files[@]}"
  if [ "$rc" -ne 0 ]; then
    echo "  FAIL  unselectable tests"
    lane_report_out "$out"
    FAILED=1; return 1
  fi
  if [ "$wrc" -ne 0 ]; then
    printf '  FAIL  unselectable tests wrote to the tree (write-guard rc=%s)\n' "$wrc"
    printf '%s\n' "$wg" | tail -8 | sed 's/^/          /'
    FAILED=1; return 1
  fi
  echo "  PASS  unselectable tests"
  return 0
}
# ── L2: ONE ORDERED LANE ───────────────────────────────────────────────────
# The two pytest stages must not overlap EACH OTHER — each wraps its own
# whole-repo `suite_write_guard` snapshot/compare bracket, and two brackets
# spanning one instant cannot tell a writer from a gate that merely overlapped
# it. The census then audits the very corpus the second stage just ran. One
# lane, in order, preserves both properties for free.
landing_unit_full_repo_tools_tests() {
    fn_capture "$1"   run_repo_tools_pytest
}
landing_unit_full_unselectable_tests() {
    fn_capture "$1" run_unselectable_pytest
}
landing_unit_full_unselectable_census() {
    # The census that decides the stage above must itself be trustworthy: a
    # subtrahend whose stage no longer exists, or an exclusion whose reason no
    # longer describes anything, both shrink the corpus in the direction that
    # still prints PASS. rc=1 on either.
    run_capture "$1" \
        python3 "$PROGRAMS/landing_unselectable_pytest_corpus.py" --repo "$ROOT" --audit
}
landing_unit_full_census_freshness() {
    # vibe-ic#2142 — THE 63x8 CENSUS, RE-DERIVED ON THE CANDIDATE TREE.
    #
    # `flow_matrix/README.md` publishes a 621-cell census that EVERY landing can
    # move: a cell changes state whenever a gate is wired, waived, or goes red. So
    # the published table is a register that must be hand-fed, and a register like
    # that goes stale — the only question is who finds out. On 2026-09-07 at
    # d644d7fb1 the finder was MAIN: the block published `undeclared 405,
    # contradicted 0` while the tree derived `404, 1`, and it had been red on main
    # for at least two days.
    #
    # NOT IN `repo_hygiene_gates.sh`, and the reason is that dispatcher's own
    # contract rather than a preference: every gate declared there must arrive with
    # a can-pass AND a can-fail fixture (`tools/ci/gate_fixture_debt.json`), a
    # fixture drives the gate against a SYNTHETIC subject tree, and this program
    # refuses any subject that is not its own checkout by construction (#972 —
    # ZERO_DENOMINATOR / CROSS_TREE). Neither direction can be authored there, and
    # the only way in would be a new debt entry, i.e. an exemption.
    #
    # NOT IN THE CHEAP TIER either: `test_issue1382_census_derives_at_land.py::
    # test_the_expensive_check_is_not_moved_into_the_push_hook` asserts it is not
    # in `pre-push`, and #1382 chose that with measurements on both sides.
    #
    # HERE, AND LAST IN THIS LANE, BECAUSE IT COSTS NO WALL CLOCK HERE. The
    # lane elapsed figures this script's own stopwatch published are targeted
    # 1736 s, hygiene 1259 s, corpus 518 s, audit 26 s. This check MEASURED 699 s
    # (11m39s) on 8HD-4, so `corpus` becomes ~1217 s and is still not the critical
    # path. Anywhere serial it would be twelve minutes on every landing.
    #
    # THE FIGURE IS THIS PROGRAM'S, NOT ITS TEST FILE'S. The first draft of this
    # comment said 559 s, which is what `programs/tests/
    # test_flow_matrix_census_freshness.py` takes -- a different subject that runs
    # the same derivation among six other things. 699 s is the one measurement of
    # THIS program on the tree that ships (the two other runs, 555 s and 531 s,
    # were over deliberately mutated trees and are not this number).
    run_capture "$1" \
        python3 "$ROOT/tools/gen_flow_matrix_census.py" "$ROOT" --check
}
lane_corpus() {
  landing_plan_dispatch window corpus
}

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
# THE RECORD IS NO LONGER OPTIONAL (owner ruling, 2026-08-21).
#
# It used to be written only when `GATEKEEPER_HYGIENE_REPORT` named a path, and
# the paragraph above says that with the variable unset the command was
# byte-for-byte the one this file had always issued. That is no longer true and
# this is why: `full:gatekeeper-review` below adjudicates THIS run's record
# against `tools/ci/gate_red_since.json`, and with no record it can only report
# `skipped — 0 gate state(s) examined`, which is a deadline that never comes
# due. Measured on an unbound corpus: the whole review returns in 45 s having
# adjudicated nothing at all.
#
# It still changes no verdict here. `run_capture` below decides this line from
# the script's exit status exactly as before; the extra flag only makes the
# record land somewhere the next stage can read it, and when the caller named a
# path that path is still the one used.
GK_HYG_RECORD="${GATEKEEPER_HYGIENE_REPORT:-$LANE_DIR/repo-hygiene-summary.json}"
# THE CALLER'S PATH IS PASSED VERBATIM, and that branch is not collapsible into
# the expansion above. The two are different contracts: a path the VERIFIER
# named is read outside this process — `hygiene_finding_delta` differences it
# against the base's record — while the lane-local default is scratch nobody
# else has been told about. v1.11.67 collapsed them and the record went on
# landing in the right place, so nothing observable broke; what broke is that
# the one line saying "the variable the verifier sets is the path used" stopped
# existing, and that line is the whole of the guarantee.
if [ -n "${GATEKEEPER_HYGIENE_REPORT:-}" ]; then
  GK_HYG=(--summary-json "$GATEKEEPER_HYGIENE_REPORT")
else
  GK_HYG=(--summary-json "$GK_HYG_RECORD")
fi
GK_HYG_ENV=()
[ -n "${GATEKEEPER_HYGIENE_PROGRESS:-}" ] \
  && GK_HYG_ENV=(env "GATE_DISPATCH_ATTESTATION_FILE=$GATEKEEPER_HYGIENE_PROGRESS")
landing_unit_full_repo_hygiene() {
    # `VIBEIC_CHECKOUT_CONCURRENT_LANES` DECLARES THE SHARED CHECKOUT. The lanes
    # above run in THIS tree at the same time as this one, so a per-gate
    # before/after snapshot taken inside the hygiene tier sees their writes and
    # cannot tell them from its own. `gate_host_independence_check` reads this to
    # decide whether it may attribute such a write to a gate; without it, it named
    # whichever gate it was driving. Said out loud rather than inferred from
    # `HYGIENE_POOL`: a number that means one thing and is read as another is how
    # this went wrong the first time.
    #
    # THE SUBJECT IS THE FRESH WORKTREE WHEN THERE IS ONE (vibe-ic#2008), AND
    # THIS CHECKOUT WHEN THERE IS NOT. `gk_hygiene_subject_prepare` decided
    # which, from the main shell and immediately before the window, and said so
    # in a REPORT line; this lane only reads the decision. `${GK_HYG_SUBJECT:-}`,
    # not `$GK_HYG_SUBJECT`: `tools/test_gatekeeper_land_lanes.py` drives this
    # REAL function under `set -u` with the variable never set, and an unset
    # subject IS the fallback, not an error.
    #
    # ONE, NOT `$LANE_WIDTH`, FOR THE FRESH SUBJECT — the same declaration, told
    # truthfully. The variable counts the stages WRITING INTO THE CHECKOUT THE
    # HYGIENE SET MEASURES. The other lanes write into `$ROOT`; nothing but this
    # lane can reach the subject worktree, so a write the probe sees there is
    # nobody else's and attribution is sound — which is the standalone shape the
    # hygiene shard runs in ("ABSENT MEANS ONE", `gate_host_independence_check.
    # declared_concurrent_lanes`). The shared fallback keeps the full width.
    #
    # THE SUBJECT'S OWN COPY OF THE SCRIPT RUNS AGAINST THE SUBJECT, when this
    # checkout IS the runtime. MEASURED on the parked first attempt (8hd-3
    # `_ktier_run`, tree 89ae23da8): the runtime copy driven at a subject
    # elsewhere failed `gates are host-independent` with 114 of 141 gates at
    # CHECKOUT_ATTESTATION_WRONG_COMMAND, because `gate_host_independence_check.
    # _expand` rebuilds every declared argv with `$PG` under the SUBJECT while
    # the attestation the dispatcher wrote carried `$PG` under the RUNTIME — two
    # different paths to byte-identical programs. In the direct-push shape
    # `RUNTIME_ROOT` is `$ROOT`, the subject is a worktree of `$ROOT`'s HEAD, and
    # `cheap:worktree-clean` has already refused a tree whose tracked files
    # differ from HEAD, so the subject's copy IS the runtime's copy, byte for
    # byte, at a path the probe's expansion agrees with. When a SEPARATE runtime
    # was named (`GATEKEEPER_RUNTIME_ROOT`, the verified-arm shape) the trusted
    # copy keeps running, exactly as before: that shape's whole point is that
    # the subject does not get to supply the instrument.
    local subject="$ROOT" lanes="$LANE_WIDTH"
    local script="$RUNTIME_ROOT/tools/ci/repo_hygiene_gates.sh"
    if [ -n "${GK_HYG_SUBJECT:-}" ]; then
      subject="$GK_HYG_SUBJECT"
      lanes=1
      if [ "$RUNTIME_ROOT" -ef "$ROOT" ]; then
        script="$GK_HYG_SUBJECT/tools/ci/repo_hygiene_gates.sh"
      fi
    fi
    run_capture "$1" "${GK_HYG_ENV[@]}" \
        env "VIBEIC_SUBJECT_ROOT=$subject" \
        "VIBEIC_CHECKOUT_CONCURRENT_LANES=$lanes" \
        "GATEKEEPER_HYGIENE_JOBS=$HYGIENE_POOL" \
        bash "$script" \
        "${GK_HYG[@]+"${GK_HYG[@]}"}"
}
lane_hygiene() {
  landing_plan_dispatch window hygiene
}
# `full:plugin-audit` IS KEPT, AND SO IS THE HYGIENE TIER'S OWN COPY.
#
# On the DIRECT-PUSH path these two are the same program over the same tree —
# `plugin_full_audit.main` defaults `plugin_root` to the directory this call
# site names explicitly, and `repo_hygiene_gates.sh:180` resolves the same
# script — so it is tempting to call one a duplicate and delete it. Do not.
#
#   * The LABEL is `LANDING_PROGRESS_UNITS[23]`. Removing it refuses every
#     landing driven with `VIBEIC_LANDING_PROGRESS` set, which is exactly how
#     the B2/A2 arms are driven: `landing_completion_record.finish` refuses
#     unless the emitted labels equal the complete 28-entry tuple.
#     BOTH NUMBERS WERE ALREADY ONE BEHIND AT 425c6402841d, before this
#     landing touched anything: the tuple was 26 entries and `full:plugin-audit`
#     sat at index 21, because the vibe-ic#712 insertion at index 10 shifted
#     every later index and re-stated only the window line above. vibe-ic#2138
#     inserts `cheap:nested-progress-pin` at index 11 and shifts them again, so
#     these are re-derived from the tuple rather than incremented -- an index
#     nothing asserts is exactly the kind of number that rots in silence
#     (`test_the_window_is_exactly_the_declared_contiguous_units` locates it
#     by `order.index`, never by an ordinal, which is why nothing went red).
#   * In an ARM they are not the same subject at all. This one runs the
#     TRUSTED `/runtime` copy of the program; the hygiene tier runs the copy
#     resolved against the candidate-controlled `/subject`. Two different
#     instruments asking the same question of the same tree is the point.
#
# Both are read-only readers, 20.2 s and 21 s, so they cost nothing beside a
# 259 s hygiene lane.
landing_unit_full_plugin_audit() {
    run_capture "$1" python3 "$PROGRAMS/plugin_full_audit.py" "$PLUGIN"
}
lane_audit() {
  landing_plan_dispatch window audit
}

# ── LAUNCH THE WINDOW, JOIN IT, THEN EMIT IN DECLARATION ORDER ─────────────
#
# `run_emit` is called ONLY from the MAIN shell and ONLY in
# LANDING_PROGRESS_UNITS order. That one rule satisfies two requirements at
# once: the labelled stream appears in declaration order, so a finding can
# never be printed under the wrong label (the measured reason
# `tools/ci/_gate_dispatch.sh` buffers and replays one level down), and
# `landing_completion_record.py:200`'s fixed-order refusal and `:261`'s
# complete-population refusal are met by construction.
# ── WHICH TREE DID THE TWO COUNTS MEASURE? ────────────────────────────────
#
# MEASURED 2026-08-28. The `batch96-landing-v1-11-96` gate reported 225 targeted
# and 133 unselectable; an independent reproduction on the same declared base
# got 221 and 132, and no base in that history yields 225. It cost a night to
# find out why, and the reason is that NEITHER COUNT MEASURES A COMMIT:
#
#   landing_unselectable_pytest_corpus.tracked_test_files   `git ls-files`
#       -> the INDEX. A staged file counts; a commit is never consulted.
#   ci_targeted_test_select._git_changed_files              `git diff <base>`
#       -> the UNION of `<base>..HEAD` and base-vs-WORKING-TREE. The second has
#          no commit on its right-hand side, and it is there deliberately: the
#          merge queue stages a squash, so `<base>..HEAD` is empty and without
#          the union the answer was the smoke floor.
#
# Both are right for their own job and both describe THIS TREE, which on a
# landing is precisely the tree where "index" and "commit" differ most. What
# was missing is one sentence saying so, and the numbers were read for weeks as
# properties of the candidate. Reproduced with the commit tree held byte-
# identical to main's: uncommitted work in one directory moved the census
# 132 -> 133 and the targeted selection 221 -> 225. See
# docs/research/2026-08-28-both-landing-counts-read-the-index-not-the-commit.md
#
# `gate_host_independence_check` already refuses this exact state for its own
# question (`DIRTY_CHECKOUT: ... N TRACKED path(s) modified/staged`). This is
# the same disclosure for the two counts, and it is a DISCLOSURE and not a
# refusal: a landing legitimately runs on a staged squash, so refusing here
# would refuse the normal case. It states the denominator; it decides nothing.
#
# TRACKED PATHS ONLY, which is what `--porcelain -uno` means. An untracked
# scratch file changes neither count -- `ls-files` does not list it and
# `git diff` does not report it -- so counting it here would raise an alarm
# about a state that moves no number.
landing_measured_tree_disclosure() {
  local out rc dirty
  # THE EXIT STATUS IS CAPTURED, NOT INFERRED FROM THE OUTPUT. Written first as
  # `git status … | grep -c ''`, which maps a FAILED git to an empty stream and
  # so to a count of 0 — "I could not look" arriving as "the tree is clean",
  # which is the substitution this whole disclosure exists against. Caught by
  # the not-a-repository arm of `tools/test_landing_measured_tree_disclosure.py`
  # on its first run.
  out="$(git -C "$ROOT" status --porcelain -uno 2>/dev/null)"; rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "  REPORT  measured tree: UNDETERMINED — \`git status\` did not answer"
    echo "          under $ROOT, so the two counts below cannot be attributed"
    echo "          to any commit. This is NOT a clean tree."
    return 0
  fi
  if [ -z "$out" ]; then dirty=0
  else dirty="$(printf '%s\n' "$out" | grep -c '' || true)"; fi
  case "$dirty" in
    ''|*[!0-9]*)
      echo "  REPORT  measured tree: UNDETERMINED — the modified-path count did"
      echo "          not come back as a number, so the two counts below cannot"
      echo "          be attributed to any commit. This is NOT a clean tree."
      return 0 ;;
    0)
      printf '  REPORT  measured tree: clean at %s — the targeted selection and the\n' \
        "$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo UNREADABLE)"
      echo "          unselectable census below describe that commit."
      return 0 ;;
  esac
  printf '  REPORT  measured tree: %s TRACKED path(s) differ from HEAD (staged or\n' "$dirty"
  echo "          modified). The targeted selection reads the working tree and the"
  echo "          unselectable census reads the index, so the two counts below"
  echo "          describe THIS TREE and not any commit. Landing on a staged"
  echo "          squash is normal and this is a disclosure, not a refusal."
}

lane_run_window() {
  landing_plan_dispatch window "" validate
  local skipped="${GATEKEEPER_SKIP_TARGETED_TESTS:-0}"
  local others=0
  lane_window_reset
  LANE_LAUNCHED=""
  if [ "$LANE_WIDTH" -gt 1 ]; then
    others=2                                    # L2 corpus + L4 audit
    [ "$skipped" = "1" ] || others=3            # + L1 targeted
  fi
  local budget="${GATEKEEPER_HYGIENE_JOBS:-8}"
  [[ "$budget" =~ ^[0-9]+$ ]] || budget=8
  HYGIENE_POOL=$(( budget - others ))
  [ "$HYGIENE_POOL" -ge 1 ] || HYGIENE_POOL=1
  local lane
  for lane in "${LANDING_PLAN_LANES[@]}"; do
    [ "$lane" != targeted ] || [ "$skipped" != "1" ] || continue
    lane_launch "$lane" "lane_$lane"
  done
}
landing_emit_full_targeted_tests() {
  local skipped="${GATEKEEPER_SKIP_TARGETED_TESTS:-0}"
  if [ "$skipped" = "1" ]; then
    echo "  SKIP  targeted tests — measured by the independent aggregate test arm"
    landing_skip "$1" "measured by the aggregate test arm"
  else
    lane_join targeted
    _landing_before="$FAILED"
    fn_emit "$1" "targeted tests" --last
    [ "$EMIT_RC" -eq 0 ] || FAILED=1
    landing_manual_stage "$1" "$_landing_before"
  fi
}
landing_emit_full_repo_tools_tests() {
  lane_join corpus
  fn_emit "$1" "repo tools tests"
  if [ "$EMIT_RC" -eq 0 ]; then
    landing_record "$1" PASS 0 "repo tools tests complete"
  else
    FAILED=1
    landing_record "$1" FAIL "$EMIT_RC" "repo tools tests failed"
  fi
}
landing_emit_full_unselectable_tests() {
  fn_emit "$1" "unselectable tests"
  if [ "$EMIT_RC" -eq 0 ]; then
    landing_record "$1" PASS 0 "unselectable tests complete"
  else
    FAILED=1
    landing_record "$1" FAIL "$EMIT_RC" "unselectable tests failed"
  fi
}
landing_emit_full_unselectable_census() {
  run_emit "$1" "unselectable-test census is not stale"
}
landing_emit_full_census_freshness() {
  census_freshness_emit --last
}
landing_emit_full_repo_hygiene() {
  lane_join hygiene
  run_emit "$1" "repo hygiene gates" --last


  if [ -n "${GK_HYG_RECORD:-}" ]; then
    printf '  REPORT  hygiene debt (advisory display; parent comparator owns admission)\n'
    python3 "$PROGRAMS/gate_red_since_check.py" --repo "$ROOT" \
      --record "$GK_HYG_RECORD" --head-ref "$BASE" --ledger-ref "$BASE" \
      || printf '  REPORT  debt checker reported findings or incomplete evidence\n'
  fi
}
landing_emit_full_plugin_audit() {
  lane_join audit
  run_emit "$1" "plugin full audit" --last
}
lane_emit_window() {
  landing_plan_dispatch window "" emit
}

# ── WRITE-GUARD ATTRIBUTION: FAIL-SAFE, WITH A FAILURE-PATH RETRY ──────────
#
# L1's session-scoped guard and L2's two whole-repo brackets now span the other
# lanes, so a write by any lane is charged to whichever bracket is open. The
# direction is fail-safe and cache churn cannot trip it: `suite_write_guard.py`
# classifies IGNORED (`!!`) as advisory and never blocking (:36) and counts
# `__pycache__`/`.pytest_cache`/`*.pyc` as regenerable noise (:117-128), so
# only an UNTRACKED non-ignored write could be misattributed — and the tier's
# own closing gate asserts on every round that no such write happens.
#
# When it DOES happen, do not guess the author: re-run the whole window at
# width 1 and report THAT run's attribution. Costs 0 s on a green round and one
# window on a round that is already failing — the same principle as the
# fallback pool, recovery adds nothing to the successful critical path.
lane_window_saw_a_write() {
  local unit
  for unit in "${LANE_WINDOW_UNITS[@]}"; do
    grep -qa 'wrote to the tree (write-guard rc=' "$LANE_DIR/$unit.out" \
      2>/dev/null && return 0
  done
  python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" --compare "$WG_BASE" \
    >/dev/null 2>&1 || return 0
  return 1
}
# ── THE HYGIENE SUBJECTS: ONE FRESH WORKTREE OF HEAD PER READER ────────────
#
# vibe-ic#2008. Every official full-tier run in the week of 2026-09-01 failed
# `attestation preflight` — "this checkout would make the attestation measure
# itself [15707 file(s) under 1 declared root(s)]" — while the hygiene shard,
# the same set on a clean clone of the SAME sha with no pytest before it,
# passed. The tier's three pytest lanes and its hygiene lane ran in ONE
# checkout. The pytest lanes leave `__pycache__`, `.pytest_cache` and `*.pyc`
# behind (`suite_write_guard` names them "regenerable cache artefact(s)" and
# is right not to count them as a write), and `attestation_preflight_check`
# refuses exactly that residue under its declared root, first and blocking,
# because a later attestation would otherwise measure it. Both are right. The
# tier's own lanes produced what the tier's own gate refuses, so the tier is
# what changes — not the gate, not the policy, and not the lanes' cache flags:
# `-p no:cacheprovider` and `PYTHONDONTWRITEBYTECODE=1` are on every lane
# command and the residue still appears, because a test that spawns
# `python3 -I` or a nested pytest writes it anyway (measured: "+3 regenerable
# cache artefact(s)" on 14 per-file sessions of one run).
#
# SO EACH READER OF THE HYGIENE SET MEASURES ITS OWN FRESH `git worktree` OF
# HEAD, made from the main shell immediately before that reader starts and
# released as soon as it has returned. There are TWO readers and therefore TWO
# subjects, never one shared: `lane_hygiene` inside the window, and
# `full:gatekeeper-review` after it, which RUNS the set a second time rather
# than being handed a record of it (owner ruling, 2026-08-21, above). The
# parked first attempt at this issue made ONE subject before the window and
# pointed both readers at it — and the review's run still failed `attestation
# preflight`, on the residue the LANE's hygiene run had by then left in the
# very worktree that was supposed to be clean (8hd-3 `_ktier_run/run.log`,
# tree 89ae23da8: the lane's set passed the preflight, the review's did not).
# A subject is fresh for exactly one reader; the second reader gets a second
# one. The serial re-run the write guard can force gets a fresh one too, for
# the same reason: the first hygiene run has already been in the old one.
#
# HEAD's tree, not a copy of the checkout, ON PURPOSE: the stamp names a
# COMMIT, `cheap:worktree-clean` has already refused a checkout whose tracked
# files differ from HEAD, and `full:worktree-fingerprint-final` refuses again
# at the end, so HEAD's tree IS the tree under test in every run that can
# stamp. The one case where it is not — tracked drift — is the case this
# function refuses to build a subject for, out loud.
#
# THE FALLBACK IS THE OLD BEHAVIOUR, SAID OUT LOUD, AND IT CANNOT PASS FALSELY.
# When a worktree cannot be made — a read-only `.git` in a verified arm, a
# dirty tracked tree, a `git` that did not answer — that reader measures this
# checkout exactly as it did before this block existed, a REPORT line says
# which and why, and `attestation preflight` still refuses any residue it
# finds there. The fallback can only ever cost a landing, never buy one. There
# is deliberately no environment flag that forces either shape.
#
# NOT A UNIT, NOT A GATE. `landing_completion_record` refuses any label outside
# the fixed 28-entry tuple, so this prints plain REPORT lines the way
# `landing_measured_tree_disclosure` does, and it returns 0 on every path: a
# subject that could not be prepared is a fact about the run, and the only
# verdict it can move is its reader's own, in the direction that refuses.
#
# UNDER `$LANE_DIR`, so the worktrees are outside the tree the closing gates
# judge and are swept with the lane files. Their REGISTRATIONS live in this
# checkout's `.git/worktrees/`, which `git status` never reports; each is
# removed by `gk_subject_release` before the closing gates and, if this script
# dies first, by `gk_cleanup`.
GK_HYG_SUBJECT=""
GK_REVIEW_SUBJECT=""
gk_subject_prepare() {               # gk_subject_prepare <var> <name> <reader>
  local var="$1" name="$2" reader="$3" wt dirty out
  wt="$LANE_DIR/subject-$name"
  printf -v "$var" '%s' ''
  # THE EXIT STATUS IS CAPTURED, NOT INFERRED FROM THE OUTPUT — the same rule
  # `landing_measured_tree_disclosure` was corrected to: a `git` that failed
  # must not arrive as "the tree is clean".
  if ! dirty="$(git -C "$ROOT" status --porcelain -uno 2>/dev/null)"; then
    echo "  REPORT  $reader subject: THIS checkout — \`git status\` did not answer, so"
    echo "          whether HEAD's tree is this tree could not be established; $reader"
    echo "          measures the checkout, and attestation preflight will refuse any"
    echo "          residue the test lanes left there (#2008)"
    return 0
  fi
  if [ -n "$dirty" ]; then
    echo "  REPORT  $reader subject: THIS checkout — tracked path(s) differ from HEAD, so"
    echo "          a worktree of HEAD would not be the tree under test; $reader"
    echo "          measures the checkout, and attestation preflight will refuse any"
    echo "          residue the test lanes left there (#2008)"
    return 0
  fi
  if out="$(git -C "$ROOT" worktree add -q --detach "$wt" HEAD 2>&1)"; then
    printf -v "$var" '%s' "$wt"
    echo "  REPORT  $reader subject: a fresh worktree of HEAD ($(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo UNREADABLE))"
    echo "          under the lane dir, made just now and read by nothing else — the"
    echo "          cache residue the test lanes leave in this checkout cannot reach"
    echo "          its attestation preflight (#2008)"
    return 0
  fi
  echo "  REPORT  $reader subject: THIS checkout — a fresh worktree of HEAD could not be"
  echo "          made (${out:-git gave no reason}); $reader measures the checkout, and"
  echo "          attestation preflight will refuse any residue the test lanes left"
  echo "          there (#2008)"
  return 0
}
# `gk_subject_release()` was MOVED UP to just above `gk_cleanup`/`trap ... EXIT`:
# `gk_cleanup` calls it, and defined here it did not exist yet on an early exit.
gk_hygiene_subject_prepare() {
  gk_subject_prepare GK_HYG_SUBJECT hygiene "the hygiene lane"
}
gk_hygiene_subject_release() {
  gk_subject_release GK_HYG_SUBJECT
}
gk_review_subject_prepare() {
  gk_subject_prepare GK_REVIEW_SUBJECT review "the review"
}
gk_review_subject_release() {
  gk_subject_release GK_REVIEW_SUBJECT
}

landing_measured_tree_disclosure
gk_hygiene_subject_prepare
lane_run_window
if [ "$LANE_WIDTH" -gt 1 ]; then
  for _lane in $LANE_LAUNCHED; do lane_join "$_lane"; done
  if lane_window_saw_a_write; then
    echo "  REPORT  a write-guard bracket reported a write inside the concurrent"
    echo "          window — re-running that window SERIALLY so the write is"
    echo "          attributed to a stage rather than to an overlap."
    # ARCHIVED BEFORE THE RE-RUN OVERWRITES THEM. `lane_stamp` truncates, so
    # without this the concurrent round's cost is destroyed by the round that
    # exists only because of it.
    lane_stamps_archive concurrent
    LANE_WIDTH=1
    # A fresh subject for the re-run: the concurrent hygiene run has already
    # been in the old one (vibe-ic#2008).
    gk_hygiene_subject_release
    gk_hygiene_subject_prepare
    lane_run_window
  fi
fi
lane_emit_window
# AFTER every unit is emitted, so no REPORT line can land between two
# labelled stage verdicts and be read as belonging to one of them.
lane_report_window
# The lane's subject has no reader left: `lane_emit_window` joined the lane
# (vibe-ic#2008). The review below gets its own.
gk_hygiene_subject_release

# Merge verification already has enough evidence to refuse once the aggregate
# session produced NO complete record.  Continuing through every remaining gate
# cannot turn UNKNOWN into PASS; it only burns the critical path.  Ordinary red
# tests do NOT take this branch because the differential still has to decide
# whether they were pre-existing.
#
# THE WINDOW ABOVE IS NOT "REMAINING GATES". Those lanes were launched beside
# the targeted arm, so by the time this line is reached their verdicts already
# exist and have already been printed; abandoning them here would discard
# evidence that has already been paid for. What is still refused is everything
# BELOW: the closing tree gates and the stamp.
if [ "${GATEKEEPER_FAIL_FAST_NORECORD:-0}" = "1" ] \
   && [ -e "$LANE_DIR/targeted.norecord" ]; then
  echo "=== FAILURES ABOVE — aggregate NORECORD is an absolute refusal; the closing tree gates were not run"
  exit 2
fi

# The parent plan owns hygiene. This unit runs every other review gate and
# returns SCOPED_REVIEW_OK only for that sub-scope. It accepts no record path
# and cannot authorize standalone admission. Timeouts remain incomplete.
GK_REVIEW_BUDGET_S="${GATEKEEPER_REVIEW_BUDGET_S:-1800}"
run_gatekeeper_review() {
  local out rc
  # THE REVIEW'S CADENCE GATE ONLY WORKS IF SOMEBODY TELLS IT WHAT RAN.
  # `test_cadence_gate` has always refused a FULL cadence whose --pytest-cmd is
  # a subset — but this call never passed one, so on a milestone the gate took
  # its OTHER branch and hard-failed with "FULL milestone requires a full-suite
  # pytest command (none supplied)". A milestone landing was therefore not
  # merely under-tested, it was IMPOSSIBLE through this script.
  #
  # The string comes from the file `run_pytest` wrote, which was derived from
  # the selection it executed. When the targeted lane is skipped entirely
  # (GATEKEEPER_SKIP_TARGETED_TESTS=1, the merge-verifier arm shape) no file
  # exists and no claim is made — an arm that did not run the tests must not
  # certify their cadence, and the review's own "no --pytest-cmd" branch is the
  # correct verdict for it.
  # `${LANE_DIR:-}`, not `$LANE_DIR`. This file runs under `set -u` and
  # `tools/test_gatekeeper_land_review_budget.py` drives this REAL function
  # against a stub, setting only the variables it needs; a bare dereference
  # made every case in that file die before the case statement it exists to
  # test. Tolerating an unset lane dir is also the honest reading: no lane dir
  # means no lane wrote a command, which is the same "no claim" branch.
  local cadence_arg=() cmd_file="${LANE_DIR:-}/pytest-cmd.txt"
  if [ -n "${LANE_DIR:-}" ] && [ -s "$cmd_file" ]; then
    cadence_arg=(--pytest-cmd "$(cat "$cmd_file")")
  fi
  # THE SHAPE OF THIS LANDING WAS ALREADY DECIDED, AND THE REVIEW WAS NOT TOLD.
  # `cheap:landing-shape` above counted the range into `GK_RANGE_N` and, when it
  # was greater than one, ran `landing_is_one_commit_check.py --batch` and
  # PASSED. The review below runs that SAME checker a second time, through
  # `gatekeeper_review.one_commit_gate`, and this call forwarded nothing — so one
  # caller called the tree a valid batch and the other called it an illegal
  # landing, inside a single gate run, about a single tree.
  #
  # That is not an edge case; it is every batch, and a batch is structurally
  # more than one commit. So the un-forwarded form has no passing case at all: it
  # can only ever refuse, and a gate that can only refuse is the one people learn
  # to push past with `--no-verify`, which is exactly what the last push did.
  #
  # THE FLAG DOES NOT RELAX THE CHECK, and that is why forwarding it is not the
  # `--hygiene-record-in` shape the owner ruled out above. That flag handed a
  # gate a SUBSTITUTE for running itself. This one hands the checker a stricter
  # question: batch mode additionally requires no manifest-only commit anywhere
  # in the range, exactly one version bump, and that bump on the TIP. It is
  # opt-in, and without it the single-landing rule is untouched.
  #
  # `${GK_RANGE_N:-0}`, not `$GK_RANGE_N`, for the reason given for `LANE_DIR`
  # directly above: `tools/test_gatekeeper_land_review_budget.py` drives this
  # REAL function against a stub and sets only the variables it needs, so a bare
  # dereference under `set -u` would kill every case in that file. Inside the
  # script the variable is always set, at top level, long before this function is
  # reached. Unset means no range was counted, which is the same "not a batch"
  # answer as a range of one.
  local batch_arg=()
  if [ "${GK_RANGE_N:-0}" -gt 1 ]; then
    batch_arg=(--batch)
  fi
  # The fresh review subject keeps structural readers clear of lane residue.
  # Hygiene runs only in the parent's required unit. No receipt is handed in.
  out="$(timeout -k 10 "$GK_REVIEW_BUDGET_S" \
         python3 "$PROGRAMS/gatekeeper_review.py" \
         --base "$BASE" --head HEAD --repo "${GK_REVIEW_SUBJECT:-$ROOT}" \
         "${cadence_arg[@]+"${cadence_arg[@]}"}" \
         "${batch_arg[@]+"${batch_arg[@]}"}" \
         --scope structural 2>&1)"; rc=$?
  case "$rc" in
    0|1) ;;
    124|137)
      out="$out
UNDETERMINED: the review did not decide within ${GK_REVIEW_BUDGET_S}s and was \
killed. A landing may not proceed on a review that did not finish."
      rc=2 ;;
    *)
      out="$out
UNDETERMINED: the review exited $rc, which is neither scoped success nor \
REQUEST_CHANGES. Treated as undecided."
      rc=2 ;;
  esac
  printf '%s\n' "$out"
  return "$rc"
}
landing_unit_full_gatekeeper_review() {
  gk_review_subject_prepare
  run "$1" "gatekeeper structural review (hygiene owned by parent)" \
      run_gatekeeper_review
  # Released BEFORE the two closing gates, so that everything this tier made
  # outside the tree is gone before the tree is judged; `gk_cleanup` repeats the
  # release for a run that dies before this line (vibe-ic#2008).
  gk_review_subject_release
}

# #1029 — the standing assertion, executed: everything above ran against this
# tree, so nothing above may have CHANGED it. Names every offending path rather
# than only failing, because a count is what made three writers cost three
# separate accidental discoveries. rc=2 (could not look) fails here too: `run`
# treats any non-zero as FAIL, which is the point — "I could not measure" must
# never reach the stamp as "I measured and it was clean".
landing_unit_full_write_guard_final() {
  run "$1" "the full tier wrote nothing into the tree" \
      python3 "$PROGRAMS/suite_write_guard.py" --repo "$ROOT" --compare "$WG_BASE"
}

# LAST, and after every suite has read the tree. Everything above answers
# "do the gates pass"; this answers "did they all read the same tree", which is
# the question the stamp actually asserts.
landing_unit_full_worktree_fingerprint_final() {
  run "$1" "worktree unchanged since the gates started" \
          python3 "$PROGRAMS/landing_worktree_is_clean_check.py" "$ROOT" \
          --expect-fingerprint "$FP"
}

landing_unit_full_completion_record() {
  # #2203: REPORT is not a product defect, but it cannot certify completion.
  # Keep the diagnostic journal and FAILED unchanged. Refuse before publishing
  # a completion receipt or reaching either standalone/composite success tail.
  if [ "${CENSUS_UNDETERMINED:-0}" -ne 0 ] && [ "$FAILED" -eq 0 ]; then
    rm -f "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"
    echo "[UNDETERMINED] census freshness was not measured; no completion receipt or stamp" >&2
    exit 2
  fi
  landing_record "$1" PASS 0 "completion record publication"
  if [ "$LANDING_RECORD_ENABLED" = "1" ]; then
    python3 "$LANDING_RECORD_TOOL" finish --journal "$LANDING_JOURNAL" \
      --record "$LANDING_COMPLETION" --failed "$FAILED" \
      || { echo "[NORECORD] landing completion record is incomplete" >&2; exit 2; }
    python3 "$LANDING_PROGRESS_TOOL" terminal \
      || { echo "[NORECORD] landing progress terminal is incomplete" >&2; exit 2; }
  fi
}

landing_plan_dispatch after_window

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
  # THE CADENCE IS PART OF WHAT THE STAMP CERTIFIES, or the asymmetry leaks.
  # Without this line every stamp is interchangeable, so a TARGETED stamp earned
  # on a patch would satisfy a later MILESTONE push exactly as well as a FULL
  # one — the milestone would be let off by a subset run, which is the single
  # thing the policy forbids. LINE 1 STAYS THE COMMIT AND ONLY THE COMMIT, so
  # both existing readers (this hook's `head -1`, and an older hook that reads
  # the whole file and fails closed) keep working, and the key=value tail is a
  # convention with a live READER and, since 2026-08-28, no writer in this repo:
  # `gatekeeper-land-differential.sh` wrote `base=`, `tier=`, `host=` and it was
  # removed. `pre-push` still parses `base=` ON PURPOSE — a stamp written before
  # the removal can still be sitting in somebody's `.git` dir, and the safe
  # direction is for the hook to keep applying the staleness rule to it rather
  # than to start ignoring a tail it no longer expects.
  # WRITTEN AS A REDIRECT AND THEN AN APPEND, not as a `{ ... } >` block.
  # `test_v1916_the_tree_must_not_move_under_the_gates` locates the stamp write
  # by searching the script for `git rev-parse HEAD > "<path>gatekeeper-stamp"`,
  # and uses that match's POSITION to assert the ordering rules — the
  # fingerprint comparison happens before it, the removal after it. A brace
  # group hides the redirect from that search, so the gate reports "nothing in
  # the landing script writes `git rev-parse HEAD` into a gatekeeper-stamp
  # file" and the ordering assertions lose their anchor. Writing line 1 first
  # and appending the tail also says the invariant out loud: the commit is
  # written alone, and everything else is a tail after it.
  git rev-parse HEAD > "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"
  printf 'cadence=%s\n' "$LANDING_CADENCE" \
    >> "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"
  echo "=== ALL GATES PASS — stamped $(git rev-parse --short HEAD) at cadence $LANDING_CADENCE ==="
  # AND PUBLISH THE VERDICT WHERE THE SERVER CAN READ IT (2026-08-29).
  #
  # The stamp above is in `.git/`, which is untracked, local, and invisible to
  # the remote. `--no-verify` skips the hook that reads it, and MEASURED on this
  # repository the same day: `branches/main/protection` -> 404, `rulesets` ->
  # [], `actions/permissions` -> {"enabled": false}. So the lane refused
  # correctly 49 times over and stopped nothing, because nothing on the server
  # was asking it.
  #
  # `required_status_checks` is the one rule that needs no GitHub Actions: the
  # context is fed by the Commit Statuses API. This line is the lane's half of
  # it. `main_ref_protection_check.py` is the other half's reader.
  #
  # NOT FATAL TO THE LANDING, and that is the safe direction rather than a
  # tolerance: a status that could not be published leaves the ruleset
  # unsatisfied, so the PUSH is refused by the server with a sentence naming the
  # missing context. Failing to publish can only ever make a push harder.
  python3 "$ROOT/tools/ci/landing_status_publish.py" --repo "$ROOT" \
      --failed "$FAILED" || true
else
  rm -f "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"
  echo "=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ==="
  # AND SAY SO ON THE SERVER TOO, for the same reason the stamp is removed: the
  # previous green must not still be standing against this commit's sha.
  python3 "$ROOT/tools/ci/landing_status_publish.py" --repo "$ROOT" \
      --failed "$FAILED" || true
  # AND SAY WHICH QUESTION WAS ASKED. This tier is ABSOLUTE: it refuses on any
  # red, including one the base tree already carries. On 2026-08-17 that made
  # main's own tip unpushable to main, so a reader of this line needs to know
  # that "did I break it" is a DIFFERENT question and that this repo can ask it.
  if [ "${GATEKEEPER_VERIFY_ARM:-}" = "" ]; then
    echo "    This run judged ABSOLUTELY — any red refuses, pre-existing or not."
    echo "    So a red above may be YOURS or may be one main already carries."
    echo "    There is no second arm to ask: the two-arm differential was"
    echo "    removed 2026-08-28 (it cost ~3.5h per arm and reported"
    echo "    environment differences as regressions). Do this instead:"
    echo "      * FIX the red named above — that is the answer whenever the"
    echo "        red is in a path this change touched; or"
    echo "      * establish it is pre-existing by running THAT ONE GATE alone"
    echo "        on an unmodified checkout of the base, which costs minutes"
    echo "        rather than hours because it measures one thing; then LAND"
    echo "        and record those reds BY NAME in the commit message and in"
    echo "        'git notes --ref=landing', so the next reader inherits the"
    echo "        list instead of re-deriving it."
    echo "    A green that hides a known red is the failure this repo pays for"
    echo "    most: say what was red, and say you landed anyway."
  fi
fi
exit "$FAILED"
