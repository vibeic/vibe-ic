#!/usr/bin/env python3
"""Step 16 — the clock plan that was never re-derived, keyed on CONTENT.

THE DEFECT. `step_canonicalize_artefacts`'s Step-16 block decided whether to
rewrite `phase3/stage3/cts/clock_plan.json` on the PLAN's own content alone::

    _needs_refresh = not (isinstance(_cl, list) and _cl)

so once the plan carried a populated `clocks` array it was never written again,
however much later the constraints were regenerated. The plan is DERIVED from
the project's SDCs: an SDC edited after it was written (a re-run at a different
period, a clock added) leaves the stale plan in place, and every skew target
keyed off it describes the old design. Nothing anywhere could see the drift.

WHY THIS IS NOT MTIME — the first attempt at this fix keyed staleness on mtime
and it did not survive review, for two reasons that are both load-bearing:

  1. MTIME DOES NOT SURVIVE COPYING. git does not restore mtimes. Over the 17
     tracked `clock_plan.json` files (`git ls-files benchmark-data`) the mtime
     rule fired on SIX in one checkout and FIVE in another worktree of the same
     commit — identical bytes, different answer — every hit naming
     `phase3/stage3/pnr/constraint.sdc`. A finding whose count depends on the
     order git wrote files is not measuring the artefact. Clone, copy, rsync
     and archive extraction are how this corpus and every user project are
     distributed. Content-keyed, the same 17 files yield 0 findings on every
     tree; `test_a_checkout_ordering_mtime_skew_is_not_staleness` reproduces
     that exact shape (plan 15 min older than constraint.sdc, content equal).
  2. THE PRODUCER COULD OVERWRITE A GOOD PLAN WITH A FABRICATED ONE. Staleness
     set `_needs_refresh = True`; the refresh block then re-derived clocks and,
     when it found none, injected a synthetic `{"clk", 10.0 ns}` before an
     UNCONDITIONAL write. So SDCs absent or moved + a primary DEF present + a
     provenance mismatch replaced a correct MULTI-CLOCK plan with one
     fabricated clock — and the replacement then satisfied every downstream
     substance check. `test_stale_refresh_never_replaces_a_good_plan_with_a_
     synthetic_one` EXECUTES that path (it was originally read, not run).

THE FIX, in three parts.
  * CONTENT KEY. The plan RECORDS `derived_from` = {relative SDC path: sha256}.
    Both sides compare that record against the SDCs present now. A plan that
    records nothing produces NO finding — absence of provenance is not evidence
    of staleness.
  * PRODUCER GUARD. A staleness-triggered refresh may only write when
    re-derivation actually produced clocks from real SDCs. Otherwise the
    existing plan is KEPT and the failure to re-derive is disclosed.
  * ONE DEFINITION. Producer and checker both call
    `_path_layout.clock_plan_input_sdcs` / `clock_plan_sdc_digests`, so the
    checker can no longer call stale what the producer calls fresh. The DEFs
    (`floorplan.def` / `placed.def`) are gone from the comparison entirely: the
    plan is built from `create_clock` statements and from nothing else, so a
    newer DEF cannot make it wrong, and they were the checker-side half of the
    producer/checker disagreement.

The gate slot stays ADVISORY (rc unchanged): the producer re-derives in the same
condition, so blocking here would fail already-complete runs for a provenance
fact rather than a wrong answer.

DIRECTION-1 GUARDS (`test_d1_*`) hold on the pre-fix tree too.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _path_layout as PL             # noqa: E402
import clock_plan_check as C          # noqa: E402
import phase3_one_shot_runner as R    # noqa: E402

_SDC = "create_clock -name clk -period 10.0 [get_ports clk]\n"
_SDC_REL = "phase3/stage3/pnr/constraint.sdc"


def _plan(*, derived_from=None, clocks=None) -> dict:
    doc = {
        "tool": "openroad",
        "primary_clock": (clocks or [{"name": "clk"}])[0]["name"],
        "clocks": clocks or [
            {"name": "clk", "period_ns": 10.0, "source": "clk"}],
    }
    if derived_from is not None:
        doc["derived_from"] = derived_from
    return doc


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _project(tmp: Path, *, sdc: str = _SDC, plan: dict = None) -> Path:
    """A project whose plan records the digest of the SDC actually on disk."""
    proj = tmp / "proj"
    _write(proj / _SDC_REL, sdc)
    if plan is None:
        plan = _plan(derived_from={
            _SDC_REL: hashlib.sha256(sdc.encode()).hexdigest()})
    _write(proj / "phase3/stage3/cts/clock_plan.json", json.dumps(plan))
    _write(proj / "phase3/stage3/pnr/floorplan.def",
           "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")
    _write(proj / "phase3/stage3/pnr/placed.def",
           "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")
    return proj


def _read_plan(proj: Path) -> dict:
    return json.loads(
        (proj / "phase3/stage3/cts/clock_plan.json").read_text())


# ===========================================================================
# The key is CONTENT, and it survives a copy
# ===========================================================================
def test_a_changed_sdc_is_seen_by_both_sides(tmp_path):
    """The condition the whole check exists for: the constraints were edited
    after the plan was derived from them."""
    proj = _project(tmp_path)
    (proj / _SDC_REL).write_text(
        "create_clock -name clk -period 4.0 [get_ports clk]\n")
    plan = _read_plan(proj)
    assert C._stale_inputs(proj, plan) == [_SDC_REL]
    assert R._clock_plan_stale_inputs(
        proj, plan, PL.clock_plan_input_sdcs(proj)) == [_SDC_REL]


def test_an_added_sdc_is_seen(tmp_path):
    """A constraint file the plan was never derived from is staleness too."""
    proj = _project(tmp_path)
    _write(proj / "constraints/extra.sdc",
           "create_clock -name clk2 -period 8.0 [get_ports clk2]\n")
    assert C._stale_inputs(proj, _read_plan(proj)) == ["constraints/extra.sdc"]


def test_a_checkout_ordering_mtime_skew_is_not_staleness(tmp_path):
    """THE REGRESSION THIS REPLACES, reproduced exactly.

    git does not restore mtimes, so after a clone the plan can easily be older
    than the SDC it was correctly derived from — that is the shape of all 5-6
    hits the mtime rule scored on the tracked corpus, every one naming
    `phase3/stage3/pnr/constraint.sdc`. Content unchanged, plan 15 minutes
    older: NO finding, from either side.
    """
    proj = _project(tmp_path)
    plan_p = proj / "phase3/stage3/cts/clock_plan.json"
    sdc_p = proj / _SDC_REL
    os.utime(plan_p, (1_785_077_203, 1_785_077_203))
    os.utime(sdc_p, (1_785_078_102, 1_785_078_102))
    assert sdc_p.stat().st_mtime > plan_p.stat().st_mtime, (
        "fixture does not reproduce the checkout-ordering skew")

    plan = _read_plan(proj)
    assert C._stale_inputs(proj, plan) == []
    assert R._clock_plan_stale_inputs(
        proj, plan, PL.clock_plan_input_sdcs(proj)) == []


def test_copying_the_whole_project_does_not_make_the_plan_stale(tmp_path):
    """The distribution shape: every file rewritten with a fresh mtime, in the
    order a checkout would write them. Content is what carries, so nothing
    fires."""
    proj = _project(tmp_path)
    for p in sorted(proj.rglob("*")):
        if p.is_file():
            p.write_bytes(p.read_bytes())          # same content, new mtime
    plan = _read_plan(proj)
    assert C._stale_inputs(proj, plan) == []
    assert R._clock_plan_stale_inputs(
        proj, plan, PL.clock_plan_input_sdcs(proj)) == []


def test_a_newer_def_is_not_staleness(tmp_path):
    """A DEF is not an input to an SDC-derived plan: the plan's clock records
    come from `create_clock` statements and from nothing else, so a newer
    floorplan/placement cannot make it wrong. Both DEFs were in the mtime
    version's comparison set, and they were the checker-side half of the
    producer/checker disagreement (the producer compared against the primary
    DEF, the checker against floorplan + placed).

    Both content AND mtime are moved, so a rule keyed on either fires."""
    proj = _project(tmp_path)
    plan_p = proj / "phase3/stage3/cts/clock_plan.json"
    os.utime(plan_p, (1_785_077_203, 1_785_077_203))
    for rel in ("phase3/stage3/pnr/floorplan.def",
                "phase3/stage3/pnr/placed.def"):
        p = proj / rel
        p.write_text("VERSION 5.8 ;\nDESIGN top ;\nCOMPONENTS 1 ;\n"
                     "END DESIGN\n")
        os.utime(p, (1_785_078_103, 1_785_078_103))
        assert p.stat().st_mtime > plan_p.stat().st_mtime

    assert C._stale_inputs(proj, _read_plan(proj)) == []
    assert R._clock_plan_stale_inputs(
        proj, _read_plan(proj), PL.clock_plan_input_sdcs(proj)) == []


def test_a_plan_with_no_provenance_record_yields_no_finding(tmp_path):
    """Absence of evidence. A plan written before `derived_from` existed says
    nothing about its inputs, and inventing staleness for it is what let a good
    plan be overwritten."""
    proj = _project(tmp_path, plan=_plan())          # no derived_from
    plan = _read_plan(proj)
    assert "derived_from" not in plan
    assert C._stale_inputs(proj, plan) == []
    assert R._clock_plan_stale_inputs(
        proj, plan, PL.clock_plan_input_sdcs(proj)) == []


def test_the_checker_cannot_call_stale_what_the_producer_calls_fresh(tmp_path):
    """(iii), DRIVEN — not a source-inspection assertion.

    The checker used a curated directory list (`_find_sdc_files`) and the
    producer a project-wide `rglob`. On the tracked corpus those two views
    disagree on the file set for 9 of the 26 SDC-bearing roots. Build a project
    in that shape — an SDC in `input/constraints/` that the curated list does
    NOT reach once `phase3/stage3/pnr` is populated — record the plan the way
    the producer would, and require both sides to agree.
    """
    proj = _project(tmp_path)
    _write(proj / "input/constraints/extra.sdc",
           "create_clock -name clk2 -period 8.0 [get_ports clk2]\n")
    curated = {str(p.relative_to(proj)) for p in C._find_sdc_files(proj)}
    assert "input/constraints/extra.sdc" not in curated, (
        "fixture does not reproduce the divergence: the curated list already "
        "reaches the extra SDC")

    # The plan as the producer writes it: derived from EVERY *.sdc.
    plan = _plan(derived_from=PL.clock_plan_sdc_digests(proj))
    _write(proj / "phase3/stage3/cts/clock_plan.json", json.dumps(plan))

    checker = C._stale_inputs(proj, plan)
    producer = R._clock_plan_stale_inputs(
        proj, plan, PL.clock_plan_input_sdcs(proj))
    assert checker == producer == [], (
        f"the checker calls stale what the producer calls fresh: "
        f"checker={checker} producer={producer}")


def test_the_shared_definition_is_the_producers_historical_set(tmp_path):
    """Adopting the shared helper must not move a clock into or out of any
    plan: its SET is exactly `rglob('*.sdc')`, only the order is canonical."""
    proj = _project(tmp_path)
    _write(proj / "input/constraints/extra.sdc", _SDC)
    _write(proj / "steps/7_constraints/top.sdc", _SDC)
    assert set(PL.clock_plan_input_sdcs(proj)) == set(proj.rglob("*.sdc"))


# ===========================================================================
# PRODUCER — the write must not destroy a real measurement
# ===========================================================================
def _run_step16(proj: Path) -> list:
    """Drive the REAL Step-16 producer — `step_canonicalize_artefacts` calls
    exactly this function, with exactly these arguments."""
    notes: list = []
    R.emit_clock_plan(proj, proj / "phase3/stage3/cts/clock_plan.json",
                      proj / "phase3/stage3/pnr/routed.def",
                      proj / "phase3/stage3/pnr", notes)
    return notes


def test_stale_refresh_never_replaces_a_good_plan_with_a_synthetic_one(
        tmp_path):
    """THE PATH THAT WAS READ BUT NOT RUN, now executed.

    Set up exactly the described state: a CORRECT multi-clock plan, a
    provenance record that no longer matches (the SDC it named is gone), and a
    primary DEF present so the refresh block is entered. On the pre-guard tree
    the re-derivation finds no SDC, injects the synthetic single 10 ns "clk",
    and writes it over the good plan unconditionally.
    """
    good = _plan(clocks=[
        {"name": "clk_core", "period_ns": 4.0, "source": "clk_core"},
        {"name": "clk_io", "period_ns": 20.0, "source": "clk_io"},
    ], derived_from={_SDC_REL: hashlib.sha256(_SDC.encode()).hexdigest()})
    proj = _project(tmp_path, plan=good)
    (proj / _SDC_REL).unlink()                      # SDCs absent / moved
    _write(proj / "phase3/stage3/pnr/routed.def",
           "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")

    plan_before = _read_plan(proj)
    assert R._clock_plan_stale_inputs(
        proj, plan_before, PL.clock_plan_input_sdcs(proj)) == [_SDC_REL], \
        "fixture does not reproduce the trigger"

    _run_step16(proj)

    after = _read_plan(proj)
    assert [c["name"] for c in after["clocks"]] == ["clk_core", "clk_io"], (
        "a stale-provenance refresh replaced a real multi-clock plan with the "
        f"synthetic fallback: {after}")


def test_a_stale_refresh_that_can_re_derive_does_rewrite(tmp_path):
    """The two-sided control: the guard must not turn the refresh off. With a
    real SDC present, a stale plan IS re-derived — and the new plan records the
    provenance that makes it fresh."""
    stale = _plan(clocks=[{"name": "old", "period_ns": 99.0, "source": "old"}],
                  derived_from={_SDC_REL: "0" * 64})
    proj = _project(tmp_path, plan=stale)
    _write(proj / "phase3/stage3/pnr/routed.def",
           "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")

    _run_step16(proj)

    after = _read_plan(proj)
    assert [c["name"] for c in after["clocks"]] == ["clk"], after
    assert after["derived_from"][_SDC_REL] == hashlib.sha256(
        _SDC.encode()).hexdigest()
    assert C._stale_inputs(proj, after) == []


def test_a_first_write_with_no_sdc_still_gets_the_nominal_fallback(tmp_path):
    """The guard is scoped to the STALENESS trigger. On the original trigger
    (no plan, or a plan with no clocks) there is no real measurement to
    destroy, and the synthetic nominal clock is still better than nothing."""
    proj = _project(tmp_path, plan={"primary_clock": "clk"})   # no `clocks`
    (proj / _SDC_REL).unlink()
    _write(proj / "phase3/stage3/pnr/routed.def",
           "VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n")
    _run_step16(proj)
    after = _read_plan(proj)
    assert [c["name"] for c in after["clocks"]] == ["clk"], after
    assert after["clocks"][0]["period_ns"] == 10.0


def test_the_step16_block_actually_calls_the_producer_under_test():
    """A helper nothing calls is not a fix, and a test driving a function the
    flow does not use proves nothing. Pin the wiring."""
    src = inspect.getsource(R.step_canonicalize_artefacts)
    assert "emit_clock_plan(" in src, (
        "step_canonicalize_artefacts no longer emits the clock plan through "
        "the function these tests drive")
    emit = inspect.getsource(R.emit_clock_plan)
    assert "_clock_plan_stale_inputs(" in emit, (
        "the producer no longer consults the staleness decision")
    assert "stale_refresh" in emit, (
        "the producer no longer distinguishes a staleness refresh from a "
        "first write — the synthetic fallback can clobber a good plan again")


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
    proj = _project(tmp_path)
    (proj / _SDC_REL).write_text(
        "create_clock -name clk -period 4.0 [get_ports clk]\n")
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert ("WARNING", "CLOCK_PLAN_STALE") in _rules(doc), _rules(doc)
    msg = [f["message"] for f in doc["findings"]
           if f["rule"] == "CLOCK_PLAN_STALE"][0]
    assert _SDC_REL in msg, msg


def test_gate_does_not_flag_a_fresh_plan(tmp_path):
    proj = _project(tmp_path)
    _, doc = _run_gate(proj, tmp_path / "o.json")
    assert "CLOCK_PLAN_STALE" not in [f["rule"] for f in doc["findings"]]


def test_the_staleness_disclosure_is_advisory(tmp_path):
    """Blocking would FAIL every already-completed run for a provenance
    condition that produced no wrong content."""
    proj = _project(tmp_path)
    (proj / _SDC_REL).write_text(
        "create_clock -name clk -period 4.0 [get_ports clk]\n")
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verdict"] == "PASS", doc["verdict"]


# ===========================================================================
# DIRECTION-1 GUARDS — hold on the pre-fix tree too
# ===========================================================================
def test_d1_a_dropped_sdc_clock_still_fails(tmp_path):
    """The gate's real blocking job must survive the new advisory finding."""
    proj = _project(tmp_path)
    (proj / _SDC_REL).write_text(
        _SDC + "create_clock -name clk_div2 -period 20.0 [get_ports clk_div2]\n")
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert doc["verdict"] == "FAIL"
    assert "SDC_CLOCK_DROPPED" in [f["rule"] for f in doc["findings"]]


def test_d1_a_missing_plan_still_fails(tmp_path):
    proj = _project(tmp_path)
    (proj / "phase3/stage3/cts/clock_plan.json").unlink()
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert "CLOCK_PLAN_MISSING" in [f["rule"] for f in doc["findings"]]


def test_d1_a_clock_with_no_period_still_fails(tmp_path):
    proj = _project(tmp_path, plan={
        "primary_clock": "clk", "clocks": [{"name": "clk", "source": "clk"}]})
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 1
    assert "CLOCK_NO_PERIOD" in [f["rule"] for f in doc["findings"]]


def test_d1_a_healthy_fresh_plan_still_passes(tmp_path):
    proj = _project(tmp_path)
    r, doc = _run_gate(proj, tmp_path / "o.json")
    assert r.returncode == 0
    assert doc["verdict"] == "PASS"


def test_an_unreadable_sdc_is_not_called_stale(tmp_path):
    """A digest that cannot be computed is not evidence of change — and it must
    not be reported as an added file either."""
    proj = _project(tmp_path)
    real_read = Path.read_bytes
    target = proj / _SDC_REL

    def boom(self, *a, **kw):
        if self == target:
            raise OSError("simulated read failure")
        return real_read(self, *a, **kw)

    Path.read_bytes = boom
    try:
        # The recorded path can no longer be hashed, so it reads as changed —
        # which is the FAIL-CLOSED direction for a provenance claim. What must
        # NOT happen is a crash or a fabricated extra entry.
        out = C._stale_inputs(proj, _read_plan(proj))
        assert out == [_SDC_REL], out
    finally:
        Path.read_bytes = real_read
