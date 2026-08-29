#!/usr/bin/env python3
"""The landing tier's concurrent window, asserted on the scheduler itself.

`tools/gatekeeper-land.sh` runs `LANDING_PROGRESS_UNITS[15..20]` as four lanes.
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


_ROOT = Path(__file__).resolve().parents[1]
_LAND = _ROOT / "tools" / "gatekeeper-land.sh"

# The scheduler, by name. Extracted rather than duplicated: a copy of these
# bodies in a test would keep passing after the original stopped matching it.
_SCHEDULER = (
    "gk_cleanup",
    "lane_write",
    "lane_reported",
    "run_capture",
    "fn_capture",
    "lane_resolve",
    "run_emit",
    "fn_emit",
    "run",
    "lane_stamp",
    "lane_timed",
    "lane_launch",
    "lane_join",
    "lane_report_window",
    "lane_window_reset",
    "lane_hygiene",
    "lane_run_window",
    "lane_emit_window",
    "lane_window_saw_a_write",
)

_WINDOW = (
    "full:targeted-tests",
    "full:repo-tools-tests",
    "full:unselectable-tests",
    "full:unselectable-census",
    "full:repo-hygiene",
    "full:plugin-audit",
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
    # LANE_WINDOW_UNITS is data the scheduler reads, so it is taken from the
    # script too rather than restated here.
    units = re.search(
        r"^LANE_WINDOW_UNITS=\(\n(?:.*?\n)*?\)$", land_text, re.MULTILINE)
    assert units, "LANE_WINDOW_UNITS is gone from tools/gatekeeper-land.sh"
    return "\n".join([units.group(0)]
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
ROOT="$WORK"
PROGRAMS="$WORK/programs"
JOURNAL="$WORK/journal.tsv"; : > "$JOURNAL"

landing_record() {
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$JOURNAL"
}
landing_skip() { landing_record "$1" SKIP 0 "$2"; }
landing_manual_stage() {
  local unit="$1" before="$2"
  if [ "$FAILED" -gt "$before" ]; then landing_record "$unit" FAIL 1
  else landing_record "$unit" PASS 0; fi
}

__SCHEDULER__
trap gk_cleanup EXIT

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
  sleep "$2" >/dev/null 2>&1
  mark "$1" end
  echo "stub stage $1 says something"
  [ "$3" -eq 0 ] || { echo "FAIL: stub $1"; FAILED=1; }
  return "$3"
}
lane_targeted() { fn_capture "full:targeted-tests" stage targeted "$T_SEC" "$T_RC"; }
lane_corpus() {
  fn_capture "full:repo-tools-tests"   stage corpus "$C_SEC" "$C_RC"
  fn_capture "full:unselectable-tests" stage corpus2 0.05 0
  run_capture "full:unselectable-census" bash -c 'echo census ok'
}
lane_audit()   { run_capture "full:plugin-audit" stage audit "$A_SEC" 0; }
export WORK T_SEC C_SEC H_SEC A_SEC
"""

_DRIVER = r"""
lane_run_window
if [ "$LANE_WIDTH" -gt 1 ]; then
  for _lane in $LANE_LAUNCHED; do lane_join "$_lane"; done
  if lane_window_saw_a_write; then
    echo "  REPORT  serial re-run"
    LANE_WIDTH=1
    lane_run_window
  fi
fi
lane_emit_window
lane_report_window
echo "FAILED=$FAILED"
"""


def _harness(scheduler: str, work: Path, body: str = _DRIVER) -> str:
    return _HARNESS.replace("__SCHEDULER__", scheduler) + body


# 60 s AND NOT MORE, and the number is not free. `ci_harness_timeout_ceiling_check`
# derives a per-call ceiling from the harness bound the workflow declares --
# `harness / CEILING_DIVISOR` -- and on this tree that is 60. Four sites below
# used to pass `timeout=120`; every one of them was flagged, and correctly: the
# harness kills the whole file before a 120 s inner bound can fire, so the larger
# number was a bound that could never be reached, read by the next author as a
# real allowance. The stubs these drive sleep 6 s and 3 s, so 60 is still 6x the
# work; raising it again is a change to the harness bound, not to this line.
def _run(scheduler: str, work: Path, env: dict[str, str], *,
         body: str = _DRIVER, timeout: int = 60) -> subprocess.CompletedProcess:
    script = work / "harness.sh"
    script.write_text(_harness(scheduler, work, body), encoding="utf-8")
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
    full.update({"WORK": str(work), "T_SEC": "1", "C_SEC": "1", "H_SEC": "1",
                 "A_SEC": "1", "T_RC": "0", "C_RC": "0", "LANE_WIDTH": "4"})
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
    lanes = ("targeted", "corpus", "audit")
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
    assert set(seen) == {"targeted", "corpus", "hygiene", "audit"}, proc.stdout

    # THE ORDER OF THE SLEEPS, RECOVERED FROM THE REPORT: targeted sleeps 6 s,
    # corpus 3 s (plus a 0.05 s second stage), hygiene and audit ~0.
    assert seen["targeted"] > seen["corpus"] > seen["audit"], (
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
    assert seen["targeted"] > seen["corpus"] > seen["audit"], (
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
    assert set(seen) == {"targeted", "corpus", "hygiene", "audit"}, proc.stdout
    # THE SIGNATURE: every lane reads the barrier, so the spread collapses and
    # a ~0 s lane is indistinguishable from the 6 s one.
    assert max(seen.values()) - min(seen.values()) <= 1, (
        "the join-stamped form no longer collapses on this host, so the test "
        f"above is not discriminating: {seen}\n{proc.stdout}")
    assert seen["audit"] >= 6, (
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
rm -f "$LANE_DIR/full:plugin-audit.rc"
lane_emit_window
echo "FAILED=$FAILED"
"""
    proc = _run(scheduler, work, {"LANE_WIDTH": "4"}, body=body)
    rows = {row[0]: row[1:] for row in _journal(work)}
    assert rows["full:plugin-audit"] == ("FAIL", "199"), rows
    assert "  FAIL  plugin full audit" in proc.stdout, proc.stdout


def test_the_exit_trap_leaves_no_lane_descendant_alive(scheduler, work):
    """A killed gate must not leave pytest writing into a stamped tree."""
    body = r"""
lane_run_window
sleep 0.6
echo "PIDS=$LANE_LIVE_PIDS"
"""
    proc = _run(scheduler, work, {"LANE_WIDTH": "4", "H_SEC": "60",
                                  "T_SEC": "60", "C_SEC": "60", "A_SEC": "60"},
                body=body, timeout=60)
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
_EMITTERS = ("run", "run_emit", "fn_emit", "landing_skip", "report")


def _emission_order(land_text):
    """The units the lander emits, in source order.

    Comment lines are dropped first: this file's own prose names units, and a
    unit named in a comment is not an emission — the same rule
    `gate_is_wired_check.executable_text` applies to callers.
    """
    emit = re.compile(
        r'^\s*(?:' + "|".join(_EMITTERS) + r')\s+"([a-z]+:[a-z0-9-]+)"')
    rec = re.compile(r'^\s*landing_record\s+"([a-z]+:[a-z0-9-]+)"\s+PASS')
    seen, order = set(), []
    for line in land_text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = emit.match(line) or rec.match(line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            order.append(m.group(1))
    return order


def test_the_script_emits_exactly_the_declared_units_in_declared_order(
        land_text):
    """THE CONTRACT NOTHING WAS CHECKING (added 2026-08-21).

    `landing_completion_record.py:200` refuses any label that is not
    `LANDING_PROGRESS_UNITS[len(gates)]` and `:261` refuses unless the emitted
    labels equal the complete tuple — so a unit added to the script at the
    wrong position, or added to the tuple and never emitted, refuses EVERY
    landing with `[NORECORD] landing completion record is incomplete`. That is
    the most expensive failure this file can prevent and it was checked only
    indirectly, for the six units inside the concurrent window.

    Discovered while adding `full:gatekeeper-review`: nothing compared the
    script's own emission order against the tuple at all, so the risk was
    carried by whoever last edited either.
    """
    record = _ROOT / "tools" / "ci" / "landing_completion_record.py"
    block = re.search(r"LANDING_PROGRESS_UNITS = \(\n((?:.*?\n)*?)\)",
                      record.read_text(encoding="utf-8"), re.MULTILINE).group(1)
    declared = re.findall(r'"([^"]+)"', block)
    emitted = _emission_order(land_text)
    assert emitted == declared, (
        "the lander's emission order and the declared tuple have diverged; "
        f"first difference at index "
        f"{next((i for i, (a, b) in enumerate(zip(emitted, declared)) if a != b), min(len(emitted), len(declared)))}"
        f"\n  emitted:  {emitted}\n  declared: {declared}")


def test_landing_record_is_never_called_from_a_lane_body(land_text):
    """`append` is an unlocked read-modify-write with a fixed-order refusal.

    `landing_completion_record.py:200` refuses any label that is not
    `LANDING_PROGRESS_UNITS[len(gates)]`, and `:261` refuses unless the emitted
    labels equal the complete 25-entry tuple. A lane that recorded from its own
    subshell would append out of order AND lose concurrent updates.
    """
    for name in ("lane_targeted", "lane_corpus", "lane_hygiene", "lane_audit",
                 "lane_run_window"):
        body = _extract(name, land_text)
        for forbidden in ("landing_record", "landing_skip",
                          "landing_manual_stage", "run_emit"):
            assert forbidden not in body, (
                f"{name} records from a lane body: {forbidden}")


def test_the_window_is_exactly_the_six_contiguous_units(land_text):
    """The concurrent window may not silently widen past its brackets."""
    units = re.search(r"^LANE_WINDOW_UNITS=\(\n((?:.*?\n)*?)\)$",
                      land_text, re.MULTILINE)
    declared = re.findall(r'"([^"]+)"', units.group(1))
    assert tuple(declared) == _WINDOW, declared

    record = _ROOT / "tools" / "ci" / "landing_completion_record.py"
    text = record.read_text(encoding="utf-8")
    block = re.search(r"LANDING_PROGRESS_UNITS = \(\n((?:.*?\n)*?)\)",
                      text, re.MULTILINE).group(1)
    order = re.findall(r'"([^"]+)"', block)
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
    proc = subprocess.run(["bash", str(script)], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, timeout=60,
                          check=False)
    assert "pipe=141" in proc.stdout, (
        "the pipe form no longer loses the match on this shell: " + proc.stdout)
    assert "here=0" in proc.stdout, proc.stdout


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
    assert re.search(r'"VIBEIC_CHECKOUT_CONCURRENT_LANES=\$LANE_WIDTH"',
                     land_text), (
        "the hygiene lane is no longer told how many lanes share its checkout")
    parts = land_text.split("lane_hygiene() {", 1)
    assert len(parts) == 2, "lane_hygiene() is gone"
    body = parts[1].split("\n}", 1)[0]
    assert "VIBEIC_CHECKOUT_CONCURRENT_LANES" in body, (
        "the declaration is in the file but not in the hygiene lane's env")


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
    assert rows["full:unselectable-census"][0] == "PASS", rows
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
    import _protected_transition_fixture as protected

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
    receipt = protected.receipt_for(
        tmp_path / "protected.json", base_commit=base, base_tree=base_tree,
        candidate_commit=head, candidate_tree=head_tree)
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
         "--protected-transition-receipt", str(receipt),
         "--json", str(tmp_path / "verdict.json")],
        capture_output=True, text=True)
    record = json.loads((tmp_path / "verdict.json").read_text())
    assert verdict.returncode == 1, (
        "the killed stage was absorbed as 'no new failure' — the gate tier "
        f"saw no label for it:\n{verdict.stdout}")
    assert record["verdict"] == "REFUSE"
    assert any("repo tools tests" in reason for reason in record["reasons"]), \
        record["reasons"]
