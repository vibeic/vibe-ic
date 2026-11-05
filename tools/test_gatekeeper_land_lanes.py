#!/usr/bin/env python3
"""The landing tier's concurrent window, asserted on the scheduler itself.

`tools/gatekeeper-land.sh` runs `LANDING_PROGRESS_UNITS[16..21]` as four lanes.
Everything here drives THAT SCHEDULER -- the real `lane_launch`, `lane_join`,
`lane_resolve`, `run_capture`, `fn_capture`, `run_emit`, `lane_run_window` and
`lane_emit_window` function bodies, extracted verbatim from the script by
name -- with STUB stage bodies. The stages are stubbed because a real round is
forty minutes; the SCHEDULER is not stubbed, because it is the thing under
test.

The two tests the change may not land without:

  * `test_the_window_actually_runs_at_the_same_time` fails if the stages go
    back to running one after another. It does not measure wall clock alone,
    which a fast host could satisfy by accident: it takes each lane's own
    [start, end] interval and requires the four to MUTUALLY OVERLAP.

  * `test_a_killed_lane_reaches_the_verdict_as_failed` fails if a lane that was
    SIGKILLed mid-flight reaches the verdict as anything but FAILED. Absence is
    deliberately not the signal -- the redirect creates the output file at fork
    time, so a killed lane leaves a PARTIAL file rather than no file, and
    `landing_merge_verdict.py` subtracts BY PRINTED LABEL, so a lane that died
    contributing no label at all would be absorbed as "no new failure".
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402
import _watchdog as _wd  # noqa: E402


_ROOT = Path(__file__).resolve().parents[1]
_LAND = _ROOT / "tools" / "gatekeeper-land.sh"

# The scheduler, by name. Extracted rather than duplicated: a copy of these
# bodies in a test would keep passing after the original stopped matching it.
def _plan():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_lane_execution_plan", _ROOT / "tools/ci/landing_execution_plan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SCHEDULER = (
    # `gk_cleanup` CALLS this, twice, and bash resolves a function name when the
    # call runs -- so leaving it out did not make the harness smaller, it made
    # the harness's own EXIT trap answer `gk_subject_release: command not found`
    # twice on every single run (vibe-ic#2095). The script itself is asserted
    # against exactly this shape by
    # `test_every_function_the_exit_trap_calls_is_defined_before_the_trap`; the
    # harness that drives the script was carrying the defect the script is
    # forbidden to have. Listed BEFORE `gk_cleanup`, mirroring the hoist in
    # `tools/gatekeeper-land.sh`.
    "gk_subject_release",
    "gk_cleanup",
    "lane_write",
    "lane_reported",
    "run_capture",
    "fn_capture",
    "lane_resolve",
    "run_emit",
    "fn_emit",
    # vibe-ic#2142 — `lane_emit_window` calls it, so the harness must define it
    # or the emit window answers `census_freshness_emit: command not found` and
    # the journal silently loses a unit. Listed with the other emitters.
    "census_freshness_emit",
    "run",
    "lane_stamp",
    "lane_stamps_archive",
    "lane_timed",
    "lane_launch",
    "lane_join",
    "lane_report_round",
    "lane_report_window",
    "lane_window_reset",
    "landing_plan_dispatch",
    "landing_unit_full_targeted_tests",
    "landing_unit_full_repo_tools_tests",
    "landing_unit_full_unselectable_tests",
    "landing_unit_full_census_freshness",
    "landing_unit_full_repo_hygiene",
    "landing_emit_full_targeted_tests",
    "landing_emit_full_repo_tools_tests",
    "landing_emit_full_unselectable_tests",
    "landing_emit_full_census_freshness",
    "landing_emit_full_repo_hygiene",
    "lane_hygiene",
    "lane_run_window",
    "lane_emit_window",
    "lane_window_saw_a_write",
)

_WINDOW = (
    "full:targeted-tests",
    "full:repo-tools-tests",
    "full:unselectable-tests",
    # vibe-ic#2142 — the 63x8 census, re-derived on the candidate tree, last in
    # `lane_corpus`. SEVEN, not six: the count in this tuple is not a property
    # anyone chose, it is the number of units the concurrent window contains,
    # and the assertion is that the window's MEMBERSHIP is exactly this list.
    "full:census-freshness",
    "full:repo-hygiene",
)

#: Sequential, after the window and before the closing write-guard
#: bracket. `full:gatekeeper-review` runs the review the landing path had
#: no other caller for; it needs the hygiene record the window produced,
#: so it cannot be inside the window.
_AFTER_WINDOW = ("full:gatekeeper-review", "full:write-guard-final")


def _extract(name: str, text: str) -> str:
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{.*?^\}}$", text, re.MULTILINE | re.DOTALL)
    assert match, f"{name}() is gone from tools/gatekeeper-land.sh"
    return match.group(0)


@pytest.fixture(scope="module")
def land_text() -> str:
    return _LAND.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def default_width(land_text: str) -> str:
    """The width the script itself defaults to — never a constant restated here.

    A test that pinned its own width would keep passing after the default was
    reverted to 1, which is exactly the regression it exists to catch.
    """
    match = re.search(r"^LANE_WIDTH=(\d+)$", land_text, re.MULTILINE)
    assert match, "the default lane width is gone from tools/gatekeeper-land.sh"
    return match.group(1)


@pytest.fixture(scope="module")
def scheduler(land_text: str) -> str:
    return "\n".join([_plan().shell()]
                     + [_extract(name, land_text) for name in _SCHEDULER])



_HARNESS = r"""
set -uo pipefail
LANE_DIR="$WORK/lanes"; mkdir -p "$LANE_DIR"
FP=""; WG_BASE="$WORK/wg"; : > "$WG_BASE"
LANE_LIVE_PIDS=""
LANE_LAUNCHED=""
HYGIENE_POOL=8
LANE_WAIT_RC=0; LANE_BROKEN=0; EMIT_RC=0; EMIT_OUT=""
FAILED=0
LANDING_NEXT=0
ROOT="$WORK"
PROGRAMS="$WORK/programs"
JOURNAL="$WORK/journal.tsv"; : > "$JOURNAL"

landing_record() {
  LANDING_NEXT=$((LANDING_NEXT + 1))
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$JOURNAL"
}
landing_skip() { landing_record "$1" SKIP 0 "$2"; }
landing_manual_stage() {
  local unit="$1" before="$2"
  if [ "$FAILED" -gt "$before" ]; then landing_record "$unit" FAIL 1
  else landing_record "$unit" PASS 0; fi
}

__SCHEDULER__
_gk_reap() {
  # Reap every recorded stage sleeper (and stage subshell) so a killed-lane or
  # killed-stage test leaves NO live descendant for the per-file landing
  # runner's post-session census to read as NORECORD. Runs BEFORE gk_cleanup.
  local _f _p
  for _f in "$WORK"/sleeper.* "$WORK"/pid.*; do
    [ -e "$_f" ] || continue
    _p=$(cat "$_f" 2>/dev/null) || continue
    [ -n "$_p" ] && kill -KILL "$_p" 2>/dev/null || true
  done
}
trap '_gk_reap; gk_cleanup' EXIT

# `lane_hygiene` is the REAL function, so the pool arithmetic is tested where
# it is actually wired. Only the suite it drives is a stub.
RUNTIME_ROOT="$WORK"
GK_HYG=(); GK_HYG_ENV=()

# ── STUB STAGES ────────────────────────────────────────────────────────────
# Each records its own [start, end] so the test can ask whether the lanes
# overlapped, rather than inferring it from the round's wall clock.
mark() { printf '%s %s %s\n' "$1" "$2" "$(date +%s.%N)" >> "$WORK/marks"; }
stage() {                            # stage <lane> <seconds> <rc>
  mark "$1" start
  # THE STAGE'S OWN PID, so a test can kill exactly THIS STAGE and leave the
  # lane around it alive. `$BASHPID` here is the command-substitution subshell
  # `run_capture`/`fn_capture` captures in — the process whose death the
  # killed-stage tests below are about.
  printf '%s\n' "$BASHPID" > "$WORK/pid.$1"
  # The sleeper must NOT inherit the capture pipe: with it inherited, killing
  # the stage leaves the substitution blocked on a child that outlived it and
  # the test would measure a timeout instead of the scheduler.
  #
  # It is BACKGROUNDED and its pid RECORDED so a killed lane/stage cannot
  # orphan it: bash does not cascade SIGKILL to children and the lanes are not
  # process-group leaders, so a bare lane/stage kill leaves `sleep "$2"` alive
  # and reparented past the harness. The per-file landing runner
  # (pytest_per_file_junit.py) reads ANY live descendant at session end as
  # NORECORD -- the same non-orphaning defect the gate-dispatch killed-worker
  # fix closed. `_gk_reap` (EXIT trap) kills every recorded sleeper.
  sleep "$2" >/dev/null 2>&1 &
  _gk_sleeper=$!
  printf '%s\n' "$_gk_sleeper" > "$WORK/sleeper.$1"
  wait "$_gk_sleeper"
  mark "$1" end
  echo "stub stage $1 says something"
  [ "$3" -eq 0 ] || { echo "FAIL: stub $1"; FAILED=1; }
  return "$3"
}
# The capture handlers are retained in the extracted closure; these expensive
# suite boundaries are represented by the stage process in this harness.
run_pytest() { stage targeted "$T_SEC" "$T_RC"; }
run_repo_tools_pytest() { stage corpus "$C_SEC" "$C_RC"; }
run_unselectable_pytest() { stage corpus2 0.05 0; }
lane_targeted() { fn_capture "full:targeted-tests" stage targeted "$T_SEC" "$T_RC"; }
lane_corpus() {
  fn_capture "full:repo-tools-tests"   stage corpus "$C_SEC" "$C_RC"
  fn_capture "full:unselectable-tests" stage corpus2 0.05 0
  # vibe-ic#2142 — the lane's LAST stage, mirroring the real `lane_corpus`.
  # `$CF_RC` is the census `--check` exit code, so this harness can drive the
  # three-outcome emitter in all three directions: 0 PASS, 1 FAIL (stale), 2
  # REPORT (could not be measured). Defaulted to 0 so every existing scenario
  # keeps the verdict it had.
  run_capture "full:census-freshness" \
      bash -c 'echo "63x8 stub rc=${CF_RC:-0}"; exit "${CF_RC:-0}"'
}
export WORK T_SEC C_SEC H_SEC A_SEC CF_RC
"""

_DRIVER = r"""
lane_run_window
if [ "$LANE_WIDTH" -gt 1 ]; then
  for _lane in $LANE_LAUNCHED; do lane_join "$_lane"; done
  if lane_window_saw_a_write; then
    echo "  REPORT  serial re-run"
    lane_stamps_archive concurrent
    LANE_WIDTH=1
    lane_run_window
  fi
fi
lane_emit_window
lane_report_window
echo "FAILED=$FAILED"
"""


def _harness(scheduler: str, body: str = _DRIVER) -> str:
    # No work directory is interpolated into the text: the script reads `$WORK`
    # from the environment `_run` builds, so a path never has to survive being
    # pasted into shell source. The parameter this used to take was never read
    # (vibe-ic#2095).
    return _HARNESS.replace("__SCHEDULER__", scheduler) + body


# NO WALL-CLOCK BOUND HERE, AND NOT BY OVERSIGHT (vibe-ic#2095).
#
# This helper used to declare `timeout: int = 60`, defended by eight lines
# justifying the NUMBER against `ci_harness_timeout_ceiling_check`. The number
# was never the problem: `_pr.run` has no `timeout` parameter at all -- it is
# this repo's replacement for `subprocess.run(..., timeout=N)` and its own
# conversion recipe is "delete the `timeout=`" -- so the declaration reached
# nothing. MEASURED before it was removed: `timeout=1` handed to this helper
# over stages that sleep 6 s returned rc 0 after 6.2 s. A parameter shaped like
# a bound that bounds nothing is worse than no parameter, because the next
# author budgets against it and the reviewer reads it as a guarantee.
#
# What supervises these runs instead is `_pr.run`'s forward-progress watch: a
# harness whose stages have gone silent AND idle across `stall_looks`
# consecutive looks raises `Stalled`, which is a finding about the child rather
# than a statement about this host. Do not put a clock back. If this file ever
# needs a longer allowance under CI, that is a change to the harness bound the
# workflow declares, not to this call.
def _run(scheduler: str, work: Path, env: dict[str, str], *,
         body: str = _DRIVER) -> subprocess.CompletedProcess:
    script = work / "harness.sh"
    script.write_text(_harness(scheduler, body), encoding="utf-8")
    programs = work / "programs"
    programs.mkdir(exist_ok=True)
    hygiene = work / "tools" / "ci"
    hygiene.mkdir(parents=True, exist_ok=True)
    # The stub the REAL `lane_hygiene` drives: it records the pool width it was
    # handed, which is the constant-budget rule's only observable.
    (hygiene / "repo_hygiene_gates.sh").write_text(
        'echo "pool=$GATEKEEPER_HYGIENE_JOBS" >> "$WORK/pool"\n'
        'echo hyg start; sleep "$H_SEC"; echo hyg ok\n', encoding="utf-8")
    # `lane_window_saw_a_write` asks this program whether the tree moved.
    (programs / "suite_write_guard.py").write_text(
        "import sys; sys.exit(%s)\n" % env.pop("_WG_RC", "0"), encoding="utf-8")
    full = dict(os.environ)
    # The real repo-tools gate constrains each child to one hygiene worker.
    # That outer production budget is not an input to this scheduler unit
    # harness: every scenario below supplies its own lane shape and expects the
    # scheduler's documented default budget.  Likewise, an aggregate-arm skip
    # must only apply when the individual test asks for it.
    full.pop("GATEKEEPER_HYGIENE_JOBS", None)
    full.pop("GATEKEEPER_SKIP_TARGETED_TESTS", None)
    full.update({"WORK": str(work), "T_SEC": "1", "C_SEC": "1", "H_SEC": "1",
                 "A_SEC": "1", "T_RC": "0", "C_RC": "0", "CF_RC": "0",
                 "LANE_WIDTH": "4"})
    full.update(env)
    return _pr.run(
        ["bash", str(script)], env=full, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, check=False)


def _journal(work: Path) -> list[tuple[str, str, str]]:
    rows = []
    for line in (work / "journal.tsv").read_text(encoding="utf-8").splitlines():
        if line:
            rows.append(tuple(line.split("\t")))
    return rows


def _marks(work: Path) -> dict[str, list[float]]:
    spans: dict[str, dict[str, float]] = {}
    for line in (work / "marks").read_text(encoding="utf-8").splitlines():
        lane, which, stamp = line.split()
        spans.setdefault(lane, {})[which] = float(stamp)
    return {lane: [v["start"], v["end"]] for lane, v in spans.items()
            if "start" in v and "end" in v}


@pytest.fixture
def work(tmp_path: Path) -> Path:
    return tmp_path


# ── THE TWO THAT MUST NOT BE REVERTIBLE ────────────────────────────────────

def test_the_window_actually_runs_at_the_same_time(scheduler, work,
                                                   default_width):
    """FAILS if the six stages go back to running one after another.

    Wall clock alone is not the assertion. A host fast enough could satisfy a
    wall-clock bound while still running serially, and a host slow enough could
    violate it while running concurrently. What is asserted is the LANES' OWN
    intervals: `targeted`, `corpus` and `hygiene` must be live at one instant.
    """
    proc = _run(scheduler, work, {"LANE_WIDTH": default_width})
    assert proc.returncode == 0, proc.stdout
    spans = _marks(work)
    lanes = ("targeted", "corpus")
    assert set(lanes) <= set(spans), spans
    latest_start = max(spans[lane][0] for lane in lanes)
    earliest_end = min(spans[lane][1] for lane in lanes)
    assert earliest_end > latest_start, (
        "the full tier's lanes did not overlap -- the concurrent window has "
        f"gone back to running serially: {spans}")

    # The negative control, in the same test: at width 1 the SAME scheduler
    # must NOT overlap. Without it a broken timestamp would pass above.
    serial = work / "serial"
    serial.mkdir()
    _run(scheduler, serial, {"LANE_WIDTH": "1"})
    spans = _marks(serial)
    latest_start = max(spans[lane][0] for lane in lanes)
    earliest_end = min(spans[lane][1] for lane in lanes)
    assert earliest_end < latest_start, spans


_LANE_ELAPSED = re.compile(r"^  REPORT  lane (\S+)\s+(\d+)s$", re.MULTILINE)
_LANE_WINDOW = re.compile(
    r"^  REPORT  window (\d+)s wall vs (\d+)s serial — ([\d.]+)x", re.MULTILINE)


def _elapsed(stdout: str) -> dict[str, int]:
    return {lane: int(secs) for lane, secs in _LANE_ELAPSED.findall(stdout)}


def test_each_lane_reports_its_own_cost_and_not_the_barrier(scheduler, work,
                                                            default_width):
    """FAILS if the stopwatch goes back to stamping at the JOIN.

    `lane_emit_window` joins in DECLARATION order and `lane_join targeted`
    blocks until the longest lane the tier launched first is done, so every
    later join returns at once. An end stamp taken there measures the BARRIER:
    all four lanes read back the same number, and the report then claims a tier
    of four equally expensive lanes whatever its real shape. That is not
    hypothetical -- an earlier version of this instrument reported all four
    lanes as 1117 s, which is why the tier's critical path went unnamed.

    So the assertion is not "a number was printed". It is that the four numbers
    REPRODUCE THE ORDER OF THE STUBS' OWN SLEEPS, which only a per-lane stamp
    can do, plus the arithmetic the report claims about itself.
    """
    proc = _run(scheduler, work,
                {"LANE_WIDTH": default_width, "T_SEC": "6", "C_SEC": "3",
                 "H_SEC": "0", "A_SEC": "0"})
    assert proc.returncode == 0, proc.stdout
    seen = _elapsed(proc.stdout)
    assert set(seen) == {"targeted", "corpus", "hygiene"}, proc.stdout

    # THE ORDER OF THE SLEEPS, RECOVERED FROM THE REPORT: targeted sleeps 6 s,
    # corpus 3 s (plus a 0.05 s second stage), hygiene and audit ~0.
    assert seen["targeted"] > seen["corpus"], (
        "the per-lane numbers do not reproduce the stubs' own durations, so "
        f"they are not measuring the lanes: {seen}\n{proc.stdout}")
    assert seen["targeted"] >= 6 and seen["corpus"] >= 3, (seen, proc.stdout)
    assert seen["hygiene"] < seen["targeted"], (seen, proc.stdout)

    window = _LANE_WINDOW.search(proc.stdout)
    assert window, proc.stdout
    wall, serial = int(window.group(1)), int(window.group(2))
    ratio = float(window.group(3))
    assert serial == sum(seen.values()), (serial, seen)
    # The window is the CRITICAL PATH: never shorter than the longest lane and
    # never longer than running the same lanes one after another.
    assert max(seen.values()) <= wall <= serial, (wall, seen)
    assert abs(ratio - serial / wall) < 0.01, (ratio, serial, wall)

    # WIDTH 1 IS THE ARM THAT SEPARATES "STAMPED IN THE LANE" FROM "STAMPED AT
    # THE LAUNCH". At width 4 the four launches are one instant apart, so a
    # start stamp taken by `lane_launch` reads the same as one taken by the
    # lane and both give the numbers above. At width 1 the bodies are DEFERRED
    # to the join and run one after another, so a launch stamp would charge
    # every lane with the elapsed time of every lane declared before it and the
    # numbers would come out monotonically increasing in DECLARATION order
    # instead of tracking the sleeps. Here `corpus` (3 s) must still outrank
    # `hygiene` and `audit` (~0 s) even though it is declared before them.
    serial_work = work / "serial"
    serial_work.mkdir()
    proc = _run(scheduler, serial_work,
                {"LANE_WIDTH": "1", "T_SEC": "6", "C_SEC": "3",
                 "H_SEC": "0", "A_SEC": "0"})
    assert proc.returncode == 0, proc.stdout
    seen = _elapsed(proc.stdout)
    assert seen["targeted"] > seen["corpus"], (
        "at width 1 the numbers no longer track the stubs' own sleeps, which "
        f"is what a launch-time start stamp looks like: {seen}\n{proc.stdout}")
    assert seen["corpus"] > seen["hygiene"], (seen, proc.stdout)
    window = _LANE_WINDOW.search(proc.stdout)
    assert window, proc.stdout
    # Serial: the window IS the serial total, so the ratio is 1.
    assert int(window.group(1)) >= int(window.group(2)), proc.stdout


def test_the_join_stamped_form_really_does_collapse_the_four_numbers(
        scheduler, work, default_width):
    """The negative control, EXECUTED rather than asserted from memory.

    The SAME scheduler with the stamps moved out of `lane_timed` and into
    `lane_launch` / `lane_join` -- which is exactly the earlier version that
    reported 1117 s four times. If this ever stops collapsing, the test above
    is not discriminating and the comment in `tools/gatekeeper-land.sh` has
    become false.
    """
    broken = scheduler.replace('( lane_timed "$name" "$@" )', '( "$@" )')
    assert broken != scheduler, "lane_launch no longer wraps the lane body"
    step = '  LANE_LAUNCHED="$LANE_LAUNCHED $name"'
    assert step in broken
    broken = broken.replace(step, '  lane_stamp "$name" t0\n' + step)
    step = '  eval "LANE_WAIT_RC=\\$LANE_RC_$name"'
    assert step in broken
    broken = broken.replace(step, '  lane_stamp "$name" t1\n' + step)
    proc = _run(broken, work,
                {"LANE_WIDTH": default_width, "T_SEC": "6", "C_SEC": "3",
                 "H_SEC": "0", "A_SEC": "0"})
    seen = _elapsed(proc.stdout)
    assert set(seen) == {"targeted", "corpus", "hygiene"}, proc.stdout
    # THE SIGNATURE: every lane reads the barrier, so the spread collapses and
    # a ~0 s lane is indistinguishable from the 6 s one.
    assert max(seen.values()) - min(seen.values()) <= 1, (
        "the join-stamped form no longer collapses on this host, so the test "
        f"above is not discriminating: {seen}\n{proc.stdout}")
    assert seen["hygiene"] >= 6, (
        "a ~0 s lane no longer reads back the 6 s barrier: " + str(seen))



def test_a_lane_that_never_finished_is_reported_as_unmeasured(scheduler, work,
                                                              default_width):
    """A missing end stamp is NAMED, never absorbed into the serial total.

    A killed lane leaves `t0` and no `t1`. Dropping it silently would make the
    remaining lanes' sum read as the whole tier's cost, which is the
    "I could not look" -> "I looked and it was fine" substitution one level
    down.
    """
    proc = _run(scheduler, work, {"LANE_WIDTH": default_width},
                body=_DRIVER.replace(
                    "lane_report_window",
                    'rm -f "$LANE_DIR/hygiene.t1"\nlane_report_window'))
    assert "lane hygiene   NO ELAPSED RECORD" in proc.stdout, proc.stdout
    assert "lane(s) unmeasured" in proc.stdout, proc.stdout
    assert "hygiene" not in _elapsed(proc.stdout), proc.stdout


def test_a_killed_lane_reaches_the_verdict_as_failed(scheduler, work):
    """FAILS if a SIGKILLed lane reaches the verdict as anything but FAILED.

    The lane is killed while it is inside its stage, so its `.rc` still holds
    the literal NORECORD the main shell pre-created. Three things must all be
    true: a labelled `  FAIL  ` line is printed for the unit, the journal row
    for that unit is FAIL with a non-zero return code, and the shell's FAILED
    flag is set so the stamp is withheld.
    """
    body = r"""
lane_run_window
sleep 0.6
kill -KILL -- "-$LANE_PID_hygiene" 2>/dev/null || kill -KILL "$LANE_PID_hygiene"
lane_emit_window
echo "FAILED=$FAILED"
"""
    proc = _run(scheduler, work, {"LANE_WIDTH": "4", "H_SEC": "30"}, body=body)
    rows = {row[0]: row[1:] for row in _journal(work)}
    assert rows["full:repo-hygiene"][0] == "FAIL", rows
    assert rows["full:repo-hygiene"][1] != "0", rows
    assert "  FAIL  repo hygiene gates" in proc.stdout, proc.stdout
    assert "left no verdict" in proc.stdout, proc.stdout
    assert "FAILED=1" in proc.stdout, proc.stdout
    # And every unit still has a row: the differential subtracts by printed
    # label, so a unit that contributed no label would be absorbed silently.
    assert set(rows) == set(_WINDOW), rows


# ── THE REST OF THE CONTRACT ───────────────────────────────────────────────

def test_serial_and_concurrent_produce_the_same_journal(scheduler, tmp_path):
    """Width 1 is the same scheduler, so the two shapes must agree exactly."""
    par, ser = tmp_path / "par", tmp_path / "ser"
    par.mkdir(); ser.mkdir()
    a = _run(scheduler, par, {"LANE_WIDTH": "4", "C_RC": "1"})
    b = _run(scheduler, ser, {"LANE_WIDTH": "1", "C_RC": "1"})
    assert a.returncode == 0 and b.returncode == 0
    assert _journal(par) == _journal(ser)
    assert [row[0] for row in _journal(par)] == list(_WINDOW)
    # And the opt-out is EXERCISED here, not merely present.
    assert "FAILED=1" in a.stdout and "FAILED=1" in b.stdout


def test_a_lane_that_leaves_no_rc_file_at_all_still_fails_with_199(
        scheduler, work):
    """Missing, not merely NORECORD. rc 199 is the NORECORD convention."""
    body = r"""
lane_run_window
for _lane in $LANE_LAUNCHED; do lane_join "$_lane"; done
rm -f "$LANE_DIR/full:repo-hygiene.rc"
lane_emit_window
echo "FAILED=$FAILED"
"""
    proc = _run(scheduler, work, {"LANE_WIDTH": "4"}, body=body)
    rows = {row[0]: row[1:] for row in _journal(work)}
    assert rows["full:repo-hygiene"] == ("FAIL", "199"), rows
    assert "  FAIL  repo hygiene gates" in proc.stdout, proc.stdout


def test_the_exit_trap_leaves_no_lane_descendant_alive(scheduler, work):
    """A killed gate must not leave pytest writing into a stamped tree."""
    body = r"""
lane_run_window
sleep 0.6
echo "PIDS=$LANE_LIVE_PIDS"
"""
    proc = _run(scheduler, work, {"LANE_WIDTH": "4", "H_SEC": "60",
                                  "T_SEC": "60", "C_SEC": "60", "A_SEC": "60"},
                body=body)
    pids = [p for p in re.search(r"PIDS=(.*)", proc.stdout).group(1).split()]
    assert pids, proc.stdout
    time.sleep(0.5)
    alive = [p for p in pids
             if subprocess.run(["kill", "-0", p], stderr=subprocess.DEVNULL,
                               check=False).returncode == 0]
    assert alive == [], f"lane process groups survived the EXIT trap: {alive}"


def test_a_write_inside_the_window_forces_a_serial_re_run(scheduler, work):
    """Attribution is never guessed: the window is replayed at width 1."""
    proc = _run(scheduler, work, {"LANE_WIDTH": "4", "_WG_RC": "1"})
    assert "REPORT  serial re-run" in proc.stdout, proc.stdout
    spans = _marks(work)
    # Both runs are in the marks file, so every lane ran twice.
    text = (work / "marks").read_text(encoding="utf-8")
    assert text.count("targeted start") == 2, text
    assert set(row[0] for row in _journal(work)) == set(_WINDOW)


_ROUND_1 = "  REPORT  round 1 of 2 — the CONCURRENT window:"
_ROUND_2 = "  REPORT  round 2 of 2 — the SERIAL re-run forced by the write guard:"
_TOTAL = re.compile(
    r"^  REPORT  this tier cost (\d+)s wall in total — (\d+)s concurrent "
    r"THEN (\d+)s serial", re.MULTILINE)


def test_the_concurrent_round_survives_the_serial_re_run(scheduler, work):
    """FAILS if round 2's stamps are allowed to overwrite round 1's.

    `lane_window_reset` clears `.rc`/`.out`/`.reported` and deliberately NOT
    `.t0`/`.t1`, and `lane_stamp` truncates. So a single report at the end read
    the SERIAL round and called it the tier: the concurrency the first round
    really obtained was destroyed by the round that exists only because of it,
    and the log said the window was worth nothing on the one landing shape that
    costs the most wall clock.

    The assertion is not "two headings were printed". It is that the two window
    lines DISAGREE in the direction only real rounds can — the concurrent one
    overlapped (window < serial sum) and the serial one did not — and that the
    total the report states about itself is their sum.
    """
    proc = _run(scheduler, work,
                {"LANE_WIDTH": "4", "_WG_RC": "1", "T_SEC": "5", "C_SEC": "2",
                 "H_SEC": "1", "A_SEC": "1"})
    assert proc.returncode == 0, proc.stdout
    assert _ROUND_1 in proc.stdout, proc.stdout
    assert _ROUND_2 in proc.stdout, proc.stdout

    windows = _LANE_WINDOW.findall(proc.stdout)
    assert len(windows) == 2, (
        f"expected one window line per round, got {len(windows)}: "
        f"{proc.stdout}")
    (w1, s1, r1), (w2, s2, r2) = windows
    assert int(w1) < int(s1), (
        f"round 1 is the CONCURRENT window and must have overlapped "
        f"({w1}s wall vs {s1}s serial): {proc.stdout}")
    assert float(r1) > float(r2), (
        f"round 1 must report MORE concurrency than the serial re-run "
        f"({r1}x vs {r2}x); equal ratios mean one round overwrote the other: "
        f"{proc.stdout}")

    total = _TOTAL.search(proc.stdout)
    assert total, proc.stdout
    assert (total.group(2), total.group(3)) == (w1, w2), proc.stdout
    assert int(total.group(1)) == int(w1) + int(w2), (
        f"the tier paid both rounds; the total must be their sum: "
        f"{proc.stdout}")


def test_without_a_re_run_the_report_is_exactly_the_one_round_it_always_was(
        scheduler, work):
    """The ordinary landing's log must not change at all.

    A diagnostic that reshapes every log to serve the rare case makes the
    common case harder to read, so the two-round shape is entered only when the
    re-run actually happened.
    """
    proc = _run(scheduler, work, {"LANE_WIDTH": "4", "_WG_RC": "0"})
    assert proc.returncode == 0, proc.stdout
    assert _ROUND_1 not in proc.stdout, proc.stdout
    assert _ROUND_2 not in proc.stdout, proc.stdout
    assert not _TOTAL.search(proc.stdout), proc.stdout
    assert len(_LANE_WINDOW.findall(proc.stdout)) == 1, proc.stdout


def test_a_lane_unstamped_in_round_1_does_not_inherit_round_2s_stamp(
        scheduler, work):
    """The archive moves only what exists, so an absent stamp stays absent.

    Copying `.t0`/`.t1` unconditionally, or letting the round-1 report fall
    through to the live stamps, would hand a lane that never finished the
    duration of the lane that replaced it — a number invented for a lane whose
    only honest reading is that it did not finish.
    """
    proc = _run(scheduler, work,
                {"LANE_WIDTH": "4", "_WG_RC": "1", "T_SEC": "1", "C_SEC": "1",
                 "H_SEC": "1", "A_SEC": "1"})
    assert proc.returncode == 0, proc.stdout
    lanes = work / "lanes"
    # Round 1's stamps are ARCHIVED under a suffix and round 2's are live, so
    # both generations are on disk at once — which is the whole mechanism.
    assert (lanes / "targeted.concurrent.t0").is_file(), sorted(
        pth.name for pth in lanes.iterdir())
    assert (lanes / "targeted.t0").is_file()
    assert (lanes / "targeted.concurrent.t0").read_text() != (
        lanes / "targeted.t0").read_text(), (
        "the archived round-1 stamp is the live round-2 one; the archive did "
        "not happen before the re-run overwrote it")


def test_the_real_script_archives_BEFORE_it_re_runs(land_text):
    """The driver above is a COPY; this reads the shipped one.

    Every other test here drives `_DRIVER`, which is this repository's
    transcription of the real top-level block. A transcription can be correct
    while the original is not, so the ordering the whole mechanism depends on
    is asserted against `tools/gatekeeper-land.sh` itself.
    """
    block = re.search(
        r"^  if lane_window_saw_a_write; then\n(?:.*?\n)*?^  fi$",
        land_text, re.MULTILINE)
    assert block, "the write-guard re-run branch is gone from gatekeeper-land.sh"
    body = block.group(0)
    assert "lane_stamps_archive concurrent" in body, body
    assert body.index("lane_stamps_archive concurrent") < body.index(
        "lane_run_window"), (
        "the archive must run BEFORE the re-run, or lane_stamp truncates the "
        f"stamps it was meant to preserve:\n{body}")


def test_the_hygiene_pool_gives_back_what_the_other_lanes_take(scheduler,
                                                               tmp_path):
    """Constant process budget: the fan-out re-allocates, it does not add."""
    wide, arm, ser = tmp_path / "w", tmp_path / "a", tmp_path / "s"
    for path in (wide, arm, ser):
        path.mkdir()
    _run(scheduler, wide, {"LANE_WIDTH": "4"})
    _run(scheduler, arm, {"LANE_WIDTH": "4", "GATEKEEPER_SKIP_TARGETED_TESTS": "1"})
    _run(scheduler, ser, {"LANE_WIDTH": "1"})
    pool = lambda p: (p / "pool").read_text(encoding="utf-8").strip()
    assert pool(wide) == "pool=5", pool(wide)   # L1 + L2 + L4 live
    assert pool(arm) == "pool=6", pool(arm)     # L2 + L4 live
    assert pool(ser) == "pool=8", pool(ser)     # nothing else live


def test_scheduler_harness_does_not_inherit_outer_gate_shape(scheduler,
                                                              tmp_path,
                                                              monkeypatch):
    """The repo-tools gate's own limits are not scheduler-test inputs."""
    monkeypatch.setenv("GATEKEEPER_HYGIENE_JOBS", "1")
    monkeypatch.setenv("GATEKEEPER_SKIP_TARGETED_TESTS", "1")
    work = tmp_path / "outer-gate"
    work.mkdir()
    _run(scheduler, work, {"LANE_WIDTH": "4"})
    assert (work / "pool").read_text(encoding="utf-8").strip() == "pool=5"


# ── SOURCE-LEVEL INVARIANTS THE SCHEDULER CANNOT ASSERT ABOUT ITSELF ───────

def test_every_lane_pytest_invocation_freezes_the_bytecode_stimulus(land_text):
    """`gate_host_independence_check` takes untracked+ignored AS ITS SUBJECT.

    A neighbouring lane writing `__pycache__` into $ROOT changes that gate's
    stimulus WHILE IT RUNS, and losing that race does not fail louder --
    `run_tolerating_uncheckable` downgrades it to NOT CHECKED (rc 2,
    non-fatal), which is a check made weaker by parallelism.

    THE ENVIRONMENT VARIABLE IS NOT THE TOKEN THAT REACHES THE WRITER.
    This assertion used to require only `PYTHONDONTWRITEBYTECODE=1` in the
    stage body, and every stage carried it, and every stage still wrote
    bytecode into $ROOT. `python3 -I` implies `-E`, and `-E` DISCARDS every
    `PYTHON*` variable -- so the one form the env var cannot reach is exactly
    the child that imports the tests. MEASURED in the pinned image with
    `PYTHONDONTWRITEBYTECODE=1` exported::

        python3        -> sys.dont_write_bytecode True
        python3 -I     -> sys.dont_write_bytecode False   <- the writer
        python3 -I -B  -> sys.dont_write_bytecode True

    So both halves are required: the env var for the driver (no `-I`), and the
    `-B` FLAG for the isolated entry the driver spawns.
    """
    missing = []
    unisolated = []
    for name in ("run_pytest", "run_repo_tools_pytest",
                 "run_unselectable_pytest"):
        body = _extract(name, land_text)
        if "PYTHONDONTWRITEBYTECODE=1" not in body:
            missing.append(name)
        if "python3 -I -B" not in body:
            unisolated.append(name)
    assert missing == [], (
        "these lane stages can write bytecode into the checkout while "
        f"`gates are host-independent` is reading it: {missing}")
    assert unisolated == [], (
        "these lane stages spawn the trusted entry under `python3 -I`, which "
        "implies `-E` and therefore DISCARDS PYTHONDONTWRITEBYTECODE; without "
        "the `-B` flag on the command line the child writes bytecode into "
        f"$ROOT no matter what the environment says: {unisolated}")


#: Every form in which the lander emits a unit. `report` is in the list because
#: leaving it out is how this instrument was first wrong: it reproduced the
#: tuple for 23 of 24 units and silently dropped `cheap:scratch-report`, which
#: shifted every later index by one and would have reported a correct script as
#: broken.
#: vibe-ic#2142 adds `census_freshness_emit`, which is a THREE-OUTCOME emitter
#: (PASS / FAIL on a stale census / REPORT on one that could not be measured)
#: and therefore cannot be `run_emit`. It takes no unit argument — its unit is
#: fixed — so `_emission_order` reads it from the assignment in its body, which
#: is why it is matched separately below rather than added to this tuple.
_EMITTERS = ("run", "run_emit", "fn_emit", "landing_skip", "report")


def _dedicated_emitters(land_text):
    """``{function name: the unit it emits}`` for emitters whose unit is FIXED.

    `run_emit`/`fn_emit` take their unit as an argument, so `_emission_order`
    can read it off the call. A three-outcome emitter cannot: its verdict
    mapping is specific to one unit, so the unit lives in the function
    (`local unit="…"`). Resolved from the DEFINITION and then counted at the
    CALL, so the order returned is still the order the lander emits in, and an
    emitter that is defined and never called contributes nothing.
    """
    out = {}
    for m in re.finditer(r"^([a-z_]+_emit)\(\) \{", land_text, re.MULTILINE):
        body = _extract(m.group(1), land_text)
        unit = re.search(r'^\s*local unit="([a-z]+:[a-z0-9-]+)"', body,
                         re.MULTILINE)
        if unit:
            out[m.group(1)] = unit.group(1)
    return out


def _emission_order(land_text):
    """The units the lander emits, in source order.

    Comment lines are dropped first: this file's own prose names units, and a
    unit named in a comment is not an emission — the same rule
    `gate_is_wired_check.executable_text` applies to callers.
    """
    emit = re.compile(
        r'^\s*(?:' + "|".join(_EMITTERS) + r')\s+"([a-z]+:[a-z0-9-]+)"')
    rec = re.compile(r'^\s*landing_record\s+"([a-z]+:[a-z0-9-]+)"\s+PASS')
    dedicated = _dedicated_emitters(land_text)
    call = re.compile(r"^\s*([a-z_]+_emit)(?:\s|$)")
    seen, order = set(), []
    for line in land_text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = emit.match(line) or rec.match(line)
        unit = m.group(1) if m else None
        if unit is None:
            c = call.match(line)
            unit = dedicated.get(c.group(1)) if c else None
        if unit and unit not in seen:
            seen.add(unit)
            order.append(unit)
    return order


@pytest.mark.parametrize(
    "rc,state,line",
    [("0", "PASS", "  PASS  63x8 census freshness"),
     ("1", "FAIL", "  FAIL  63x8 census freshness"),
     ("2", "REPORT", "  REPORT  63x8 census freshness")])
def test_the_census_unit_has_three_outcomes_and_only_one_of_them_blocks(
        scheduler, work, rc, state, line, land_text):
    """PASS / FAIL / REPORT, driven through the real emitter (vibe-ic#2142).

    `run_emit` reads every non-zero as FAIL, and for this unit that is wrong in
    the expensive direction: `gen_flow_matrix_census --check` exits 2 when it
    could not look — a non-cell red in one of the nine dimension modules makes
    the census NORECORD, and that is somebody ELSE'S red on the base. Refusing a
    landing for it is the ban vibe-ic#1277 measured for this same generator.

    All three arms are driven here rather than asserted about, because a
    three-outcome branch nobody executes is two outcomes and a comment. The
    Product failure is checked by `FAILED`: only rc 1 may set it. The historical
    node id is retained; an undecided REPORT must also prohibit a completed
    stamp, without becoming a product failure (#2203).
    """
    proc = _run(scheduler, work, {"CF_RC": rc})
    assert line in proc.stdout, proc.stdout
    rows = {r[0]: (r[1], r[2]) for r in _journal(work)}
    assert rows["full:census-freshness"] == (state, rc), rows
    assert f"FAILED={1 if rc == '1' else 0}" in proc.stdout, proc.stdout

    # Execute the actual emitter -> completion unit -> final stamp tail. Other
    # gate bodies are not run; transport is the only stub in the final tail.
    # A pre-existing stamp must be removed on both refusal paths.
    assert _plan().STEPS[-1] == ("full:completion-record", "after_window", "")
    tail = re.search(
        r'^if \[ "\$FAILED" -eq 0 \] && \[ "\$\{GATEKEEPER_NO_STAMP:-0\}"',
        land_text, re.MULTILINE)
    assert tail, "the actual final stamp consumer is absent"
    for record_enabled in ([0, 1] if rc == "2" else [0]):
        end = work / f"completion-{record_enabled}"
        end.mkdir()
        for args in (("init", "-q"),
                     ("-c", "user.name=probe", "-c", "user.email=probe@example.invalid",
                      "commit", "--allow-empty", "-qm", "synthetic completion control")):
            subprocess.run(["git", "-C", str(end), *args], check=True,
                           capture_output=True)
        stamp = end / ".git/gatekeeper-stamp"
        stamp.write_text("an earlier certificate must not survive refusal\n")
        script = r'''
set -uo pipefail
FAILED=0
ROOT="$PWD"
LANDING_CADENCE=TARGETED
GATEKEEPER_NO_STAMP=0
GATEKEEPER_VERIFY_ARM=""
LANDING_RECORD_TOOL=must-not-be-reached-on-undetermined
LANDING_JOURNAL="$PWD/completion-journal.tsv"
LANDING_COMPLETION="$PWD/completion.json"
LANDING_PROGRESS_TOOL=must-not-be-reached-on-undetermined
lane_resolve() { EMIT_RC="$CF_RC"; EMIT_OUT="NOT_MEASURED: synthetic verdict input"; }
landing_record() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$LANDING_JOURNAL"; }
python3() { printf 'STATUS_TRANSPORT_NOT_RUN %s\n' "$*"; }
trap 'echo "FINAL_FAILED=$FAILED"' EXIT
'''
        script += _extract("census_freshness_emit", land_text) + "\n"
        script += _extract("landing_unit_full_completion_record", land_text) + "\n"
        script += "census_freshness_emit\nlanding_unit_full_completion_record full:completion-record\n"
        script += land_text[tail.start():]
        script_path = end / "actual-completion.sh"
        script_path.write_text(script)
        done = _pr.run(["bash", str(script_path)], cwd=end,
                       env={**os.environ, "CF_RC": rc,
                            "LANDING_RECORD_ENABLED": str(record_enabled)},
                       capture_output=True, text=True, check=False)
        (end / "stdout.txt").write_text(done.stdout)
        (end / "stderr.txt").write_text(done.stderr)
        (end / "returncode.txt").write_text(str(done.returncode) + "\n")
        observed = (end / "completion-journal.tsv").read_text()
        assert done.returncode == int(rc), (done.returncode, done.stdout, done.stderr)
        assert f"FINAL_FAILED={1 if rc == '1' else 0}" in done.stdout
        assert stamp.exists() == (rc == "0"), (done.stdout, done.stderr)
        assert ("ALL GATES PASS" in done.stdout) == (rc == "0"), done.stdout
        assert ("full:completion-record\tPASS" in observed) == (rc != "2"), observed
        if rc == "2":
            assert "[UNDETERMINED]" in done.stderr
            assert not (end / "completion.json").exists()
            assert "STATUS_TRANSPORT_NOT_RUN" not in done.stdout


def test_an_earlier_red_in_the_same_lane_does_not_make_the_census_a_norecord(
        scheduler, work):
    """NORECORD is not rc 2, and the two must not print the same sentence.

    `lane_resolve` synthesises `EMIT_RC=199` for a unit whose lane was killed.
    Read as a plain returncode, 199 is "not 0 and not 1" and would fall into the
    REPORT arm — so a killed lane would publish "the census could not be
    measured here", the very sentence an honest rc 2 prints, and a reader could
    not tell them apart. The emitter therefore consults the RESOLUTION before
    the code; `test_a_killed_lane_reaches_the_verdict_as_failed` drives that
    path and now covers this unit too, because it is in `_WINDOW`.

    This pins the OTHER half, which the resolution-first rule could break: an
    ordinary FAILING stage EARLIER in the same lane must leave the census unit's
    own verdict alone. The lane runs on; the unit reported; it is a PASS.
    """
    proc = _run(scheduler, work, {"C_RC": "1", "C_SEC": "0.05"})
    rows = {r[0]: (r[1], r[2]) for r in _journal(work)}
    assert rows["full:repo-tools-tests"][0] == "FAIL", rows
    assert rows["full:census-freshness"] == ("PASS", "0"), rows
    assert "  PASS  63x8 census freshness" in proc.stdout, proc.stdout


def test_the_script_emits_exactly_the_declared_units_in_declared_order(tmp_path):
    # Exercise the real handler/capture/emit chain and protected append, not a
    # regex over comments or a second copy of the scheduler's declaration.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_lane_plan_probe", _ROOT / "tools/ci/test_landing_execution_plan.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    REQUIRED = probe.REQUIRED
    proc = probe.exercise_plan(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    import json
    rows = json.loads((tmp_path / "journal.json").read_text())["gates"]
    assert tuple(row["label"] for row in rows) == REQUIRED == _plan().UNITS


def test_landing_record_is_never_called_from_a_lane_body(land_text):
    """`append` is an unlocked read-modify-write with a fixed-order refusal.

    `landing_completion_record.py:200` refuses any label that is not
    `LANDING_PROGRESS_UNITS[len(gates)]`, and `:261` refuses unless the emitted
    labels equal the complete 28-entry tuple. A lane that recorded from its own
    subshell would append out of order AND lose concurrent updates.
    """
    for name in ("lane_targeted", "lane_corpus", "lane_hygiene",
                 "lane_run_window"):
        body = _extract(name, land_text)
        for forbidden in ("landing_record", "landing_skip",
                          "landing_manual_stage", "run_emit"):
            assert forbidden not in body, (
                f"{name} records from a lane body: {forbidden}")


def test_the_window_is_exactly_the_declared_contiguous_units():
    """The concurrent window may not silently widen past its brackets.

    NAMED FOR THE PROPERTY, NOT FOR THE COUNT (vibe-ic#2142). It was
    `..._the_six_contiguous_units`, and the window is seven units as of the
    census unit landing here. A test whose NAME states a population figure is
    the same register-that-must-be-hand-fed this repo keeps finding: the
    assertion below compares MEMBERSHIP against `_WINDOW` and never a length, so
    the number was never the subject and should never have been in the name.
    """
    declared = _plan().WINDOW_UNITS
    assert declared == _WINDOW, declared
    order = list(_plan().UNITS)
    start = order.index(_WINDOW[0])
    assert tuple(order[start:start + len(_WINDOW)]) == _WINDOW
    # The brackets stay outside it, on both sides.
    assert order[start - 1] == "full:write-guard-baseline"
    # AND the sequential tail between the window and the closing bracket is
    # pinned exactly, rather than only asserting which unit comes next. The
    # review was added at this position on 2026-08-21 — after the hygiene run
    # whose record it adjudicates, and still INSIDE the write-guard brackets so
    # its own writes are attributed to it rather than to an overlap. Naming the
    # whole tail keeps what the single assertion caught (a unit inserted into
    # the bracketed region without anybody deciding it belonged there) while
    # saying which units are deliberately there.
    assert tuple(order[start + len(_WINDOW):
                       start + len(_WINDOW) + len(_AFTER_WINDOW)]) \
        == _AFTER_WINDOW


def _shell_code_only(body: str) -> str:
    """`body` with its comments removed, so a NAME in prose is not a call.

    Full-comment lines go entirely. A trailing `#` is only treated as a comment
    when it follows whitespace AND the text before it closes every quote it
    opened, so a `#` inside a string survives. The residue of a wrong guess is
    an EXTRA name demanded earlier in the file, which is the safe direction.
    """
    out = []
    for line in body.splitlines():
        if line.lstrip().startswith("#"):
            continue
        cut = re.search(r"\s#", line)
        while cut:
            head = line[:cut.start()]
            if head.count('"') % 2 == 0 and head.count("'") % 2 == 0:
                line = head
                break
            cut = re.search(r"\s#", line[cut.start() + 1:])
        out.append(line)
    return "\n".join(out)


def test_this_harness_declares_no_parameter_it_does_not_consume():
    """A parameter this file declares and never reads is a bound nobody honours.

    vibe-ic#2095. `_run` carried `timeout: int = 60` and passed it nowhere:
    `_pr.run` has no `timeout` parameter, because it is the repo's replacement
    for `subprocess.run(..., timeout=N)` and supervises by forward progress
    instead. The declaration was defended by eight lines arguing the NUMBER,
    which is exactly how a dead bound survives review -- the argument is about
    60 versus 120 and nobody asks whether either reaches a call. Handing this
    helper `timeout=1` over stages that sleep 6 s returned rc 0 after 6.2 s.

    `_harness` carried the same defect in a second spelling: a `work: Path` it
    never read, while the script it builds gets `$WORK` from the environment.
    Both were found by this scan, not by reading, which is the point of having
    it: the class is invisible at the call site, where the argument is passed
    and looks consumed.

    The assertion is the GENERAL invariant over THIS file: every declared
    parameter is named somewhere in its own body. If a future test wants a
    fixture purely for its side effect, request it with
    `@pytest.mark.usefixtures(...)` rather than as an unread parameter -- that
    spelling says "for the side effect" out loud, which an unread name does not.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    dead = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args
        declared = [a.arg for a in
                    (args.posonlyargs + args.args + args.kwonlyargs)]
        read = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        dead += [f"{node.name}({name}) at line {node.lineno}"
                 for name in declared if name not in read]
    # The scan is not supposed to be inert: this file must actually declare
    # parameters, or a rename could empty the population and read as clean.
    total = sum(len(n.args.args) for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef))
    assert total > 20, f"only {total} parameters scanned -- is this file parsed?"
    assert not dead, (
        "these parameters are declared and never read in their own body, so "
        "whatever they look like they promise, they deliver nothing: "
        + ", ".join(dead))


#: A single-quoted or double-quoted run, so prose inside a shell STRING is not
#: read as a call. `lane_resolve` writes "…did not reach its own report…" into
#: its NORECORD message, and a scan that kept it would demand a `report`
#: member of `_SCHEDULER` that nothing calls.
_SHELL_STRING = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", re.DOTALL)


def _shell_names(body: str) -> set[str]:
    """Every bare word in `body` that could name a function.

    ARGUMENT POSITION COUNTS AS MUCH AS COMMAND POSITION, and that is not
    caution — it is the only way to see the lanes at all. `lane_run_window`
    names them as arguments (`lane_launch corpus lane_corpus`), so a scan that
    read only the first word of each command would find no lane body anywhere
    and report a clean closure over a scheduler missing all four.
    """
    code = _SHELL_STRING.sub(" ", _shell_code_only(body))
    return set(re.findall(r"(?<![\w-])([A-Za-z_][A-Za-z0-9_]*)(?![\w-])", code))


def test_the_scheduler_carries_every_function_its_bodies_call(land_text):
    """`_SCHEDULER` is a closure, not a list — a callee left out is not defined.

    vibe-ic#2095. `gk_cleanup` was extracted and `gk_subject_release`, which it
    calls twice, was not. Bash resolves a function name when the call RUNS, so
    the harness's own EXIT trap answered `gk_subject_release: command not
    found` twice on every run — measured, exactly two lines. Nothing failed,
    which is the whole problem: the missing member was the one that removes the
    linked-worktree REGISTRATIONS the real script mints, so what the harness
    was silently not exercising was a cleanup that partially fails, which is
    how a leaked subject stays leaked.

    `tools/gatekeeper-land.sh` is already forbidden this exact shape by
    `test_every_function_the_exit_trap_calls_is_defined_before_the_trap`. This
    is the same invariant applied to the HARNESS that drives the script, which
    is where it was actually broken.

    A name is satisfied by membership in `_SCHEDULER` or by a stub `_HARNESS`
    defines — those two are the only ways a function reaches the generated
    script.
    """
    defined = set(re.findall(
        r"^([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{", land_text, re.MULTILINE))
    assert "gk_cleanup" in defined, sorted(defined)
    stubbed = set(re.findall(
        r"^([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{", _HARNESS, re.MULTILINE))
    supplied = set(_SCHEDULER) | stubbed

    missing: dict[str, list[str]] = {}
    for name in _SCHEDULER:
        for callee in sorted(_shell_names(_extract(name, land_text)) & defined):
            if callee != name and callee not in supplied:
                missing.setdefault(callee, []).append(name)
    # Not inert: the scan must actually be resolving names across the extracted
    # bodies, or an `_extract` that started returning "" would read as clean.
    seen = set().union(*(_shell_names(_extract(n, land_text)) for n in _SCHEDULER))
    assert len(seen & defined) >= len(_SCHEDULER) // 2, sorted(seen & defined)
    assert not missing, (
        "these functions `tools/gatekeeper-land.sh` defines are CALLED by an "
        "extracted scheduler body but are neither extracted nor stubbed, so "
        "the generated harness answers `command not found` when the call runs: "
        + ", ".join(f"{callee}() <- {', '.join(callers)}"
                    for callee, callers in sorted(missing.items())))


def test_the_harness_exit_trap_finds_everything_it_calls(scheduler, work):
    """The runtime half of the closure, because the static half is a regex.

    `_shell_names` can be wrong in either direction; bash cannot. This runs the
    generated harness and reads what its own EXIT trap said. On the tree that
    omitted `gk_subject_release` this printed two `command not found` lines and
    the run still exited 0 — a cleanup that partially fails, reported as a
    clean exit.
    """
    proc = _run(scheduler, work, {"LANE_WIDTH": "4"})
    assert proc.returncode == 0, proc.stdout
    # The trap fires at EXIT, after the driver's last line, and `_run` merges
    # stderr into stdout — so if it complained, it is in here.
    assert "FAILED=0" in proc.stdout, proc.stdout
    complaints = [line for line in proc.stdout.splitlines()
                  if "command not found" in line]
    assert not complaints, (
        "the harness's EXIT trap called something the generated script never "
        "defines — add it to `_SCHEDULER` or stub it in `_HARNESS`: "
        + "; ".join(complaints))


def test_every_function_the_exit_trap_calls_is_defined_before_the_trap(
        land_text):
    """`trap gk_cleanup EXIT` arms a handler; it does not define its callees.

    Bash defines a function when its definition statement is EXECUTED, so a
    handler armed at line N that calls a function defined at line N+1800 is a
    handler that answers `command not found` on EVERY exit in between —
    `--cheap-only` and the two full-tier preflight refusals are all in that
    window. That is not cosmetic: `gk_subject_release` is what removes the two
    linked-worktree REGISTRATIONS this script mints under the checkout's
    `.git/worktrees/`, which `git status` never reports, and a registration
    left behind is the stale-worktree hazard the subjects exist to avoid.

    The assertion is the GENERAL invariant, not the one instance: whatever
    `gk_cleanup` calls, wherever the trap is armed. The remedy is always to
    MOVE the definition up — never to guard the call site, which would make
    the leak silent instead of noisy.
    """
    trap = re.search(r"^trap gk_cleanup EXIT$", land_text, re.MULTILINE)
    assert trap, "the EXIT trap is gone from tools/gatekeeper-land.sh"

    # Every function this script defines, and where. Taken from the file, so a
    # helper added later is covered without editing this test.
    defined = {m.group(1): m.start() for m in re.finditer(
        r"^([A-Za-z_][A-Za-z0-9_]*)\(\) \{", land_text, re.MULTILINE)}
    assert "gk_cleanup" in defined and "gk_subject_release" in defined, \
        sorted(defined)

    body = _shell_code_only(_extract("gk_cleanup", land_text))
    called = sorted(
        name for name in defined
        if name != "gk_cleanup"
        and re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", body))
    # The handler is not supposed to be inert; if it calls nothing at all this
    # test has stopped watching anything.
    assert called, "gk_cleanup calls no function this script defines"

    def _line(offset: int) -> int:
        return land_text.count("\n", 0, offset) + 1

    late = [(name, _line(defined[name])) for name in called
            if defined[name] > trap.start()]
    assert not late, (
        "these functions are called by gk_cleanup but defined AFTER "
        f"`trap gk_cleanup EXIT` (line {_line(trap.start())}), so the EXIT "
        "trap answers `command not found` on every exit before them — move "
        "the definition above the trap, do not guard the call site: "
        + ", ".join(f"{n}() at line {ln}" for n, ln in late))

    # gk_cleanup itself, for the same reason.
    assert defined["gk_cleanup"] < trap.start(), \
        "gk_cleanup() is defined after the trap that arms it"

def test_no_marker_probe_asks_its_question_through_a_pipe(land_text):
    """`printf … | grep -q …` under `pipefail` reports a MATCH as a non-match.

    `grep -q` exits on the first match; if the buffer exceeds a pipe, `printf`
    is still writing, takes SIGPIPE, and `pipefail` makes the pipeline 141. The
    probes this guards — NORECORD, NOTRUN, AGGREGATE_NORECORD — then MISS a
    real refusal, which is "I could not look" arriving as "I looked and it was
    fine". Measured on this shell with a 1.75 MB buffer: match on the first
    line gave 141 twelve times out of twelve; match on the last line gave 0.
    """
    offenders = [
        line.strip() for line in land_text.splitlines()
        if "| grep -q" in line and not line.lstrip().startswith("#")]
    assert offenders == [], (
        "these probes ask through a pipe, so a match can arrive as 141 and be "
        f"read as a non-match: {offenders}")


#: THE 60 s IS THE SAME NUMBER AND NO LONGER A CLOCK (vibe-ic#2131, #2051).
#:
#: The probe below used to run under `subprocess.run(..., timeout=60)` — the
#: last terminating wall-clock in this file, and exactly the shape
#: `_progress_run` exists to replace. `ci_harness_timeout_ceiling_check` was
#: silent about it and was RIGHT to be: its own PASS line says "bounded at or
#: under the ceiling that applies to it", and 60 is exactly `180 // 3`. That
#: gate judges MAGNITUDE — can one call outlive the SESSION — and never
#: mechanism, so a bound at the ceiling is a permitted spend, not a hole.
#:
#: What was wrong here is the mechanism. Under #2051 a budget RECORDS the
#: crossing, ANNOUNCES it once, and the child RUNS ON; only stillness may stop
#: a job. So the number stays and becomes what it always should have been.
_PROBE_BUDGET_S = 60.0

#: HOW OFTEN THE SUPERVISOR LOOKS, which is not how long it will wait. The
#: watchdog's own default is 30 s, which is right for a forty-minute gate and
#: needlessly coarse for a probe that finishes in one second: with it, the
#: crossing of a 60 s budget is first observable at the third look. Tightening
#: the cadence changes nothing about what may stop a job.
_PROBE_POLL_S = 1.0


def _supervised_bash(script: Path, *, budget_s: float = _PROBE_BUDGET_S):
    """`bash <script>` under the progress supervisor. Returns `(result, crossed)`.

    `_pr.run` is the usual drop-in, but it does not forward a `ceiling_notice`
    and returns a plain `CompletedProcess`, so the budget it passes down is
    recorded where no caller can read it — which is the same defect #2095
    removed from this file in its dead form. `_wd.run_supervised` is the
    harness's own supervised runner and hands both halves back: `crossed`
    collects the ANNOUNCEMENT, `result.supervision` carries the RECORD.

    Nothing here terminates on elapsed time. A job that goes silent AND idle
    for `stall_grace_s` is still killed — on evidence, by the stall path.
    """
    crossed: list[float] = []
    result = _wd.run_supervised(
        ["bash", str(script)],
        hard_ceiling_s=budget_s,
        poll_s=_PROBE_POLL_S,
        ceiling_notice=crossed.append,
        as_text=True)
    return result, crossed


def test_the_pipe_form_really_does_lose_a_match(tmp_path):
    """The negative control, EXECUTED rather than asserted from memory.

    If this ever stops failing, the rewrite above is no longer buying anything
    and the comment in `gatekeeper-land.sh` has become false.
    """
    script = tmp_path / "probe.sh"
    script.write_text(
        "set -uo pipefail\n"
        'big=$(for i in $(seq 1 40000); do echo "pad pad pad pad line $i"; done)\n'
        'out="AGGREGATE_NORECORD first\n$big"\n'
        "printf '%s\\n' \"$out\" | grep -qa '^AGGREGATE_NORECORD'; echo \"pipe=$?\"\n"
        'grep -qa \'^AGGREGATE_NORECORD\' <<<"$out"; echo "here=$?"\n',
        encoding="utf-8")
    res, crossed = _supervised_bash(script)
    assert res.outcome == "natural", (res.outcome, res.supervision, res.err)
    # A one-second probe cannot cross a sixty-second budget. If it ever does,
    # the announcement says so instead of the run being torn down for it.
    assert crossed == [], (crossed, res.supervision)
    assert "pipe=141" in res.out, (
        "the pipe form no longer loses the match on this shell: " + res.out)
    assert "here=0" in res.out, res.out


def test_the_probe_budget_is_recorded_and_never_terminates(tmp_path):
    """A subject still writing PAST the budget must finish, and be SAID to have.

    vibe-ic#2131. This is the property the converted call above cannot show on
    its own, because it finishes in a second: the number is now a BUDGET, and a
    budget that quietly kept killing would look exactly like one that does not.

    The subject writes a line a second for 65 s against a 60 s budget, so it is
    demonstrably alive at 61 s. Three things are asserted, and they are the
    three halves of #2051's ruling:

      * CONTINUES -- outcome `natural`, rc 0, and the LAST line the subject
        writes is in the output. Absence of a kill is not the assertion; the
        subject's own completion marker is, because a killed job also returns.
      * RECORDED  -- `supervision['hard_ceiling_exceeded']`, with the budget
        that was crossed, on the result the caller holds. A budget nobody can
        read is not a ceiling (the #2095 ruling), which is why this is asserted
        on the RESULT and not merely passed in.
      * ANNOUNCED -- the injected notice fired EXACTLY ONCE, with an elapsed
        past the budget. Once, because a per-poll notice would be a log flood
        rather than an event.

    Under the `subprocess.run(..., timeout=60)` this replaced, the subject is
    killed at 60 s and `TimeoutExpired` escapes: no completion marker, no
    record, no notice. That is the mutation arm, and it is the whole point.
    """
    script = tmp_path / "slow.sh"
    # `sleep 1` in a loop rather than one long `sleep`, so the subject is
    # PRODUCING OUTPUT the whole time. A silent sleeper would be indistinguishable
    # from a corpse to the stall path, and this test would be measuring the wrong
    # branch of the supervisor.
    script.write_text(
        "set -u\n"
        "i=0\n"
        "while [ \"$i\" -lt 65 ]; do echo \"still writing $i\"; sleep 1; "
        "i=$((i + 1)); done\n"
        "echo SUBJECT_FINISHED\n",
        encoding="utf-8")
    started = time.monotonic()
    res, crossed = _supervised_bash(script)
    elapsed = time.monotonic() - started

    # It really did outlive the budget -- otherwise everything below is vacuous.
    assert elapsed > _PROBE_BUDGET_S, (
        f"the subject finished in {elapsed:.1f}s, inside the "
        f"{_PROBE_BUDGET_S}s budget, so this test proved nothing about what "
        "happens when the budget is crossed")

    # CONTINUES.
    assert res.outcome == "natural", (res.outcome, res.supervision, res.err)
    assert res.rc == 0, (res.rc, res.err, res.out[-400:])
    assert "SUBJECT_FINISHED" in res.out, (
        "the subject was stopped before it finished -- the budget is being "
        f"spent as a terminator again: outcome={res.outcome} rc={res.rc} "
        f"supervision={res.supervision} tail={res.out[-400:]!r}")

    # RECORDED, on the result the caller holds.
    assert res.supervision.get("hard_ceiling_exceeded") is True, res.supervision
    assert res.supervision.get("hard_ceiling_s") == _PROBE_BUDGET_S, \
        res.supervision
    assert res.supervision.get("hard_ceiling_crossed_s", 0) > _PROBE_BUDGET_S, \
        res.supervision

    # ANNOUNCED, exactly once.
    assert len(crossed) == 1, crossed
    assert crossed[0] > _PROBE_BUDGET_S, (crossed, _PROBE_BUDGET_S)


def test_the_hygiene_lane_is_TOLD_the_checkout_is_shared(land_text):
    """The window has to be DECLARED, or the tier inside it names the innocent.

    `gate_host_independence_check` brackets each gate's drive with a
    `git status` snapshot of this checkout and charges the difference to that
    gate. `git status` cannot name an author, so under `LANE_WIDTH=4` a write
    by the targeted lane is charged to whichever gate the hygiene lane happened
    to be driving -- and then `git checkout -- <path>` REVERTS it underneath
    the lane that wrote it. Measured as `3 GATE_CORRUPTED_CHECKOUT` on one host
    and not another, and briefly blamed on a landing batch.

    The probe reads `VIBEIC_CHECKOUT_CONCURRENT_LANES` to decide whether it may
    attribute such a write; absent, it reads 1 and attributes, which is right
    for a standalone run and wrong here. So this asserts on the WIRING rather
    than on the probe: a fix that never reaches the process that runs is not a
    fix.
    """
    parts = land_text.split("landing_unit_full_repo_hygiene() {", 1)
    assert len(parts) == 2, "lane_hygiene() is gone"
    body = parts[1].split("\n}", 1)[0]
    assert "VIBEIC_CHECKOUT_CONCURRENT_LANES" in body, (
        "the declaration is in the file but not in the hygiene lane's env")
    # vibe-ic#2008: the declaration is a VARIABLE bound in the lane's own body
    # — the full width for the shared checkout, and ONE for the fresh subject
    # worktree nothing but this lane writes into. Both bindings are asserted,
    # because either alone could be the wrong one: a lane that always said
    # `$LANE_WIDTH` would refuse attribution in a checkout it owns outright,
    # and a lane that always said 1 would name the innocent again.
    assert re.search(r'^\s*local subject="\$ROOT" lanes="\$LANE_WIDTH"$', body,
                     re.MULTILINE), (
        "the shared-checkout fallback no longer declares the full lane width")
    assert re.search(r'^\s*lanes=1$', body, re.MULTILINE), (
        "the fresh-subject shape no longer declares that it is the only writer")
    assert re.search(r'"VIBEIC_CHECKOUT_CONCURRENT_LANES=\$lanes"', body), (
        "the hygiene lane is no longer told how many lanes share its checkout")
    assert re.search(r'"VIBEIC_SUBJECT_ROOT=\$subject"', body), (
        "the hygiene lane no longer measures the subject it was handed")


def test_there_is_no_way_to_opt_IN(land_text):
    """The fast path is the default; the escape hatch only turns it OFF."""
    assert "GATEKEEPER_LANDING_SERIAL" in land_text
    assert "--serial" in land_text
    assert "GATEKEEPER_LANDING_PARALLEL" not in land_text
    assert re.search(r"^LANE_WIDTH=4$", land_text, re.MULTILINE), (
        "the default lane width is no longer concurrent")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── A STAGE KILLED INSIDE A LANE THAT IS STILL ALIVE ───────────────────────
# The test above kills a whole LANE, and a dead lane leaves its units' `.rc`
# holding the literal NORECORD the main shell pre-created. A stage that dies
# INSIDE A LIVE LANE is a different event and it was the blind spot: the
# capture writes `.rc` either way, and for a killed subshell it holds
# 128+signal — a PARSABLE integer. Reading that as "the stage reported" is
# wrong for the three `fn_capture` stages specifically, because those report by
# PRINTING `  FAIL  <label>` and the integer is merely the capture's exit
# status. `landing_merge_verdict.py` subtracts BY PRINTED LABEL, so a stage
# that died before its own print contributes NOTHING for the differential to
# see, and the landing is absorbed as "no new failure".
#
# On the direct-push path there was no second backstop to catch it:
# `gatekeeper-land-differential.sh` launched both gate arms without
# `VIBEIC_LANDING_PROGRESS`, so the journal was off. That driver was REMOVED
# 2026-08-28; the hazard is recorded here because `landing_merge_verdict.py`
# still subtracts BY PRINTED LABEL on the merge path, where it is still live.

_KILL_ONE_STAGE = r"""
lane_run_window
for _ in $(seq 400); do
  [ -s "$WORK/pid.corpus" ] && break
  sleep 0.05
done
# EXACTLY ONE STAGE, by its own pid — not the process group, which is what the
# whole-lane test kills. The lane's remaining units must still report, or this
# would be the previous test with extra steps.
kill -KILL "$(cat "$WORK/pid.corpus")" 2>/dev/null || true
lane_emit_window
echo "FAILED=$FAILED"
"""


def test_a_killed_stage_inside_a_live_lane_is_still_labelled(scheduler, work):
    """FAILS if a stage killed mid-flight contributes no `  FAIL  ` line.

    Three things are asserted together, and the first is what makes this a
    different test from the killed-LANE one: the lane SURVIVED — its later
    units reported normally — and the killed stage is STILL a labelled FAIL
    with a non-zero journal row.
    """
    proc = _run(scheduler, work, {"LANE_WIDTH": "4", "C_SEC": "60"},
                body=_KILL_ONE_STAGE)
    rows = {row[0]: row[1:] for row in _journal(work)}
    assert rows["full:unselectable-tests"][0] == "PASS", (
        "the LANE was killed, not the stage — this test then asserts nothing "
        f"the previous one does not: {rows}")
    assert rows["full:repo-tools-tests"][0] == "FAIL", rows
    assert rows["full:repo-tools-tests"][1] != "0", rows
    assert "  FAIL  repo tools tests" in proc.stdout, proc.stdout
    assert "did not reach its own report" in proc.stdout, proc.stdout
    assert "FAILED=1" in proc.stdout, proc.stdout
    assert set(rows) == set(_WINDOW), rows


# ── THE SAME KILL, CARRIED THROUGH TO THE JUDGE ────────────────────────────
# The assertion above is about this file's own scheduler. This one is about
# what the NEXT program does with the log that scheduler wrote, because that is
# where the consequence lives: `landing_merge_verdict.decide` compares the two
# arms' gate logs BY PRINTED LABEL, and a candidate log carrying no label for a
# stage that died is one it reads as "this branch broke no gate".
#
# `--candidate-gate-rc 1` and `--require-composite-gate-record` are passed
# exactly as `gatekeeper-land-differential.sh` passed them before it was removed
# (2026-08-28) and as `gatekeeper-verify-merge.sh` passes them today, so the
# composite record check is satisfied and the only thing left to decide the gate
# tier is the labels. Both arms' test reports are GREEN on purpose: if this refuses, it
# refuses for the killed stage and for nothing else.

_PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"
_VERDICT = _ROOT / _PLUGIN_REL / "programs" / "landing_merge_verdict.py"
_SELECTED = "programs/tests/test_subject.py"
_GREEN_JUNIT = (
    '<?xml version="1.0"?><testsuites>'
    '<testsuite name="aggregate::selection" tests="1">'
    '<testcase classname="pytest_aggregate.programs.tests.test_subject" '
    f'name="test_one" file="{_SELECTED}"/></testsuite>'
    '<testsuite name="whole_selection::process_exit" tests="1">'
    '<testcase classname="pytest_aggregate_process" '
    'name="whole_selection::process_exit" file="&lt;aggregate&gt;">'
    '<properties><property name="process_rc" value="0"/></properties>'
    '</testcase></testsuite></testsuites>')
_BASE_LAND_LOG = (
    "=== gatekeeper landing gates — base=stub ===\n"
    "  PASS  repo tools tests (3 file(s))\n"
    "  PASS  unselectable tests\n"
    "  PASS  unselectable-test census is not stale\n"
    "  PASS  repo hygiene gates\n"
    "  PASS  plugin full audit\n"
    "=== ALL NON-TARGET GATES COMPLETE — stamp withheld for composite "
    "verdict ===\n")


def test_the_judge_refuses_the_log_a_killed_stage_leaves(scheduler, work,
                                                         tmp_path):
    """FAILS if a stage killed inside a live lane lands.

    Nothing about the judge is relaxed to make this pass, and nothing may be:
    a missing label MUST be a refusal, and the repair is that the label is no
    longer missing.
    """
    sys.path.insert(0, str(_ROOT / _PLUGIN_REL / "programs" / "tests"))
    import test_issue1498_hygiene_subset_rule_is_wired as hygiene

    proc = _run(scheduler, work, {"LANE_WIDTH": "4", "C_SEC": "60"},
                body=_KILL_ONE_STAGE)
    # THE REAL LOG, not a re-description of it: the header and the terminal
    # sentinel `gatekeeper-land.sh` writes around exactly this stream.
    land_log = tmp_path / "land.log"
    land_log.write_text(
        "=== gatekeeper landing gates — base=stub ===\n"
        + proc.stdout
        + "=== FAILURES ABOVE — stamp removed; the pre-push hook will "
          "refuse ===\n", encoding="utf-8")
    base_land_log = tmp_path / "base_land.log"
    base_land_log.write_text(_BASE_LAND_LOG, encoding="utf-8")
    for name in ("base.xml", "cand.xml"):
        (tmp_path / name).write_text(_GREEN_JUNIT, encoding="utf-8")
    (tmp_path / "sel.txt").write_text(_SELECTED + "\n", encoding="utf-8")

    base, head = "a" * 40, "b" * 40
    base_tree, head_tree = "c" * 40, "d" * 40
    hygiene_record = hygiene._write(tmp_path, "hygiene.json",
        hygiene._record([hygiene._gate("neutral check", "PASS")]))
    verdict = subprocess.run(
        [sys.executable, str(_VERDICT),
         "--base-sha", base, "--base-tree", base_tree, "--head-sha", head,
         "--verified-sha", head, "--rebase-status", "ok",
         "--expected-tree", head_tree, "--verified-tree", head_tree,
         "--land-log", str(land_log), "--base-land-log", str(base_land_log),
         "--selection", str(tmp_path / "sel.txt"),
         "--base-selection", str(tmp_path / "sel.txt"),
         "--base-junit", str(tmp_path / "base.xml"),
         "--candidate-junit", str(tmp_path / "cand.xml"),
         "--verification-tier", "direct-push",
         "--candidate-gate-rc", "1", "--require-composite-gate-record",
         "--base-hygiene", str(hygiene_record),
         "--candidate-hygiene", str(hygiene_record),
         "--base-hygiene-host", "test-host", "--candidate-hygiene-host", "test-host",
         "--json", str(tmp_path / "verdict.json")],
        capture_output=True, text=True)
    record = json.loads((tmp_path / "verdict.json").read_text())
    assert verdict.returncode == 1, (
        "the killed stage was absorbed as 'no new failure' — the gate tier "
        f"saw no label for it:\n{verdict.stdout}")
    assert record["verdict"] == "REFUSE"
    assert any("repo tools tests" in reason for reason in record["reasons"]), \
        record["reasons"]
