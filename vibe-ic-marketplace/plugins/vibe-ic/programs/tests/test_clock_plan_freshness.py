#!/usr/bin/env python3
"""Step 16 — the clock plan that was never re-derived.

THE DEFECT. `step_canonicalize_artefacts`'s Step-16 block decided whether to
rewrite `phase3/stage3/cts/clock_plan.json` on CONTENT alone::

    _needs_refresh = not (isinstance(_cl, list) and _cl)

so once the plan carried a populated `clocks` array it was never written again,
however much later the design was regenerated. The plan is DERIVED from the
project's SDCs: an SDC edited after it was written (a re-run at a different
period, a clock added) leaves the stale plan in place, and every skew target
keyed off it describes the old design. `clock_plan_check.py` had no mtime logic
of any kind, so nothing anywhere could see the drift.

MEASURED on the real completed run `campaign_pr427/spm/converge_ihp-sg13g2`
(pure-digital standard cell; clock plan, SDC and DEFs are digital artefacts):

    clock_plan.json  1785077203
    floorplan.def    1785078102   (+15 min)
    placed.def       1785078103   (+15 min)

    origin/main   clock_plan_check -> PASS, findings all INFO
    this branch   clock_plan_check -> PASS, plus WARNING CLOCK_PLAN_STALE
                  naming phase2/stage1/fpga/spm.sdc,
                  phase3/stage3/pnr/constraint.sdc, floorplan.def, placed.def

On that run the stale plan's CONTENT still agreed with the live constraint.sdc
(clk / 10 ns), so this was a structural gap, not a live wrong answer — which is
exactly why the fix is on the PRODUCER and the gate slot is advisory.

THE FIX, in two halves.
  * PRODUCER (`_clock_plan_stale_inputs`, used by the Step-16 block): refresh
    also when the plan is older than an input it is derived from. Re-deriving
    is a few SDC reads and a small JSON, and is idempotent, so the artefact's
    mtime ends up >= its inputs'.
  * GATE (`clock_plan_check._stale_inputs`): report the condition for plans
    written by an older runner. ADVISORY — rc is unchanged. Blocking here would
    FAIL every already-completed run for a provenance condition the producer
    fix prevents going forward, and no live divergence was ever measured.

DIRECTION-1 GUARDS (`test_d1_*`) hold on the pre-fix tree too.
"""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import clock_plan_check as C          # noqa: E402
import phase3_one_shot_runner as R    # noqa: E402

_PLAN = {
    "tool": "openroad",
    "primary_clock": "clk",
    "clocks": [{"name": "clk", "period_ns": 10.0, "source": "clk"}],
}
_SDC = "create_clock -name clk -period 10.0 [get_ports clk]\n"


def _write(p: Path, text: str, mtime: float) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    os.utime(p, (mtime, mtime))
    return p


def _project(tmp: Path, *, plan_mtime: float, sdc_mtime: float,
             def_mtime: float) -> Path:
    proj = tmp / "proj"
    _write(proj / "phase3/stage3/cts/clock_plan.json",
           json.dumps(_PLAN), plan_mtime)
    _write(proj / "phase3/stage3/pnr/constraint.sdc", _SDC, sdc_mtime)
    _write(proj / "phase3/stage3/pnr/floorplan.def",
           "VERSION 5.8 ;\nDESIGN spm ;\nEND DESIGN\n", def_mtime)
    _write(proj / "phase3/stage3/pnr/placed.def",
           "VERSION 5.8 ;\nDESIGN spm ;\nEND DESIGN\n", def_mtime)
    return proj


# ===========================================================================
# PRODUCER — the runner's own staleness decision
# ===========================================================================
def test_producer_sees_a_plan_older_than_its_sdc(tmp_path):
    """The content test alone said "fresh"; the plan predates the SDC it is
    derived from."""
    proj = _project(tmp_path, plan_mtime=1_785_077_203,
                    sdc_mtime=1_785_078_102, def_mtime=1_785_078_103)
    stale = R._clock_plan_stale_inputs(
        proj, proj / "phase3/stage3/cts/clock_plan.json",
        [proj / "phase3/stage3/pnr/constraint.sdc",
         proj / "phase3/stage3/pnr/placed.def"])
    assert stale == ["phase3/stage3/pnr/constraint.sdc",
                     "phase3/stage3/pnr/placed.def"], stale


def test_producer_leaves_a_fresh_plan_alone(tmp_path):
    """The two-sided control: re-deriving on every pass would be churn, and a
    check that can only say "stale" is not a check."""
    proj = _project(tmp_path, plan_mtime=1_785_079_000,
                    sdc_mtime=1_785_078_102, def_mtime=1_785_078_103)
    assert R._clock_plan_stale_inputs(
        proj, proj / "phase3/stage3/cts/clock_plan.json",
        [proj / "phase3/stage3/pnr/constraint.sdc",
         proj / "phase3/stage3/pnr/placed.def"]) == []


def test_producer_treats_an_absent_plan_as_a_first_write(tmp_path):
    """Not a staleness decision — the existing content path handles it."""
    proj = _project(tmp_path, plan_mtime=1, sdc_mtime=2, def_mtime=2)
    (proj / "phase3/stage3/cts/clock_plan.json").unlink()
    assert R._clock_plan_stale_inputs(
        proj, proj / "phase3/stage3/cts/clock_plan.json",
        [proj / "phase3/stage3/pnr/constraint.sdc"]) == []


def test_the_step16_block_actually_consults_the_staleness_decision():
    """A helper nothing calls is not a fix. Pin the wiring in the producer."""
    src = inspect.getsource(R.step_canonicalize_artefacts)
    assert "_clock_plan_stale_inputs(" in src, (
        "the Step-16 block no longer consults the staleness decision")


# ===========================================================================
# GATE — the advisory disclosure
# ===========================================================================
def _run_gate(proj: Path, out: Path):
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "clock_plan_check.py"), str(proj),
         "--json", str(out)],
        capture_output=True, text=True, timeout=60)
    return r, json.loads(out.read_text())


def _rules(doc):
    return [(f["severity"], f["rule"]) for f in doc["findings"]]


def test_gate_discloses_a_stale_plan(tmp_path):
    """The real run's mtime shape, reproduced."""
    proj = _project(tmp_path, plan_mtime=1_785_077_203,
                    sdc_mtime=1_785_078_102, def_mtime=1_785_078_103)
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert ("WARNING", "CLOCK_PLAN_STALE") in _rules(doc), _rules(doc)
    msg = [f["message"] for f in doc["findings"]
           if f["rule"] == "CLOCK_PLAN_STALE"][0]
    assert "constraint.sdc" in msg and "placed.def" in msg, msg


def test_gate_does_not_flag_a_fresh_plan(tmp_path):
    proj = _project(tmp_path, plan_mtime=1_785_079_000,
                    sdc_mtime=1_785_078_102, def_mtime=1_785_078_103)
    _, doc = _run_gate(proj, tmp_path / "o.json")
    assert "CLOCK_PLAN_STALE" not in [f["rule"] for f in doc["findings"]]


def test_the_staleness_disclosure_is_advisory(tmp_path):
    """Blocking would FAIL every already-completed run for a provenance
    condition that produced no wrong content."""
    proj = _project(tmp_path, plan_mtime=1_785_077_203,
                    sdc_mtime=1_785_078_102, def_mtime=1_785_078_103)
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verdict"] == "PASS", doc["verdict"]


# ===========================================================================
# DIRECTION-1 GUARDS — hold on the pre-fix tree too
# ===========================================================================
def test_d1_a_dropped_sdc_clock_still_fails(tmp_path):
    """The gate's real blocking job must survive the new advisory finding."""
    proj = _project(tmp_path, plan_mtime=9_000_000_000,
                    sdc_mtime=1, def_mtime=1)
    (proj / "phase3/stage3/pnr/constraint.sdc").write_text(
        _SDC + "create_clock -name clk_div2 -period 20.0 [get_ports clk_div2]\n")
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert doc["verdict"] == "FAIL"
    assert "SDC_CLOCK_DROPPED" in [f["rule"] for f in doc["findings"]]


def test_d1_a_missing_plan_still_fails(tmp_path):
    proj = _project(tmp_path, plan_mtime=1, sdc_mtime=2, def_mtime=2)
    (proj / "phase3/stage3/cts/clock_plan.json").unlink()
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert "CLOCK_PLAN_MISSING" in [f["rule"] for f in doc["findings"]]


def test_d1_a_clock_with_no_period_still_fails(tmp_path):
    proj = _project(tmp_path, plan_mtime=9_000_000_000,
                    sdc_mtime=1, def_mtime=1)
    (proj / "phase3/stage3/cts/clock_plan.json").write_text(json.dumps(
        {"primary_clock": "clk",
         "clocks": [{"name": "clk", "source": "clk"}]}))
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert "CLOCK_NO_PERIOD" in [f["rule"] for f in doc["findings"]]


def test_d1_a_healthy_fresh_plan_still_passes(tmp_path):
    proj = _project(tmp_path, plan_mtime=9_000_000_000,
                    sdc_mtime=1, def_mtime=1)
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 0
    assert doc["verdict"] == "PASS"


def test_an_unstattable_plan_is_not_called_stale(tmp_path):
    """An unreadable mtime is not evidence of staleness — and the CONTENT
    test already rewrites an unreadable plan. (Not a direction-1 guard: both
    helpers are introduced by this change.)"""
    proj = _project(tmp_path, plan_mtime=1, sdc_mtime=2, def_mtime=2)
    plan = proj / "phase3/stage3/cts/clock_plan.json"
    real_stat = Path.stat

    def boom(self, *a, **kw):
        if self == plan:
            raise OSError("simulated stat failure")
        return real_stat(self, *a, **kw)

    Path.stat = boom
    try:
        assert C._stale_inputs(proj, plan) == []
        assert R._clock_plan_stale_inputs(
            proj, plan, [proj / "phase3/stage3/pnr/constraint.sdc"]) == []
    finally:
        Path.stat = real_stat
