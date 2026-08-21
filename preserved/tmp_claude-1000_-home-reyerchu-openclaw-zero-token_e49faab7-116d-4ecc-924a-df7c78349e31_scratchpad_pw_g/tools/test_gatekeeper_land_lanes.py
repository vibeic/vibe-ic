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


_ROOT = Path(__file__).resolve().parents[1]
_LAND = _ROOT / "tools" / "gatekeeper-land.sh"

# The scheduler, by name. Extracted rather than duplicated: a copy of these
# bodies in a test would keep passing after the original stopped matching it.
_SCHEDULER = (
    "gk_cleanup",
    "lane_write",
    "run_capture",
    "fn_capture",
    "lane_resolve",
    "run_emit",
    "run",
    "lane_launch",
    "lane_join",
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
  mark "$1" start; sleep "$2"; mark "$1" end
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
echo "FAILED=$FAILED"
"""


def _harness(scheduler: str, work: Path, body: str = _DRIVER) -> str:
    return _HARNESS.replace("__SCHEDULER__", scheduler) + body


def _run(scheduler: str, work: Path, env: dict[str, str], *,
         body: str = _DRIVER, timeout: int = 120) -> subprocess.CompletedProcess:
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
    return subprocess.run(
        ["bash", str(script)], env=full, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, timeout=timeout, check=False)


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
    non-fatal), which is a check made weaker by parallelism. `python3 -I` does
    not imply `-B`, so the token has to be written.
    """
    missing = []
    for name in ("run_pytest", "run_repo_tools_pytest",
                 "run_unselectable_pytest"):
        body = _extract(name, land_text)
        if "PYTHONDONTWRITEBYTECODE=1" not in body:
            missing.append(name)
    assert missing == [], (
        "these lane stages can write bytecode into the checkout while "
        f"`gates are host-independent` is reading it: {missing}")


def test_landing_record_is_never_called_from_a_lane_body(land_text):
    """`append` is an unlocked read-modify-write with a fixed-order refusal.

    `landing_completion_record.py:200` refuses any label that is not
    `LANDING_PROGRESS_UNITS[len(gates)]`, and `:261` refuses unless the emitted
    labels equal the complete 24-entry tuple. A lane that recorded from its own
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
    assert order[start + len(_WINDOW)] == "full:write-guard-final"


def test_there_is_no_way_to_opt_IN(land_text):
    """The fast path is the default; the escape hatch only turns it OFF."""
    assert "GATEKEEPER_LANDING_SERIAL" in land_text
    assert "--serial" in land_text
    assert "GATEKEEPER_LANDING_PARALLEL" not in land_text
    assert re.search(r"^LANE_WIDTH=4$", land_text, re.MULTILINE), (
        "the default lane width is no longer concurrent")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
