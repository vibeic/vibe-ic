"""The step record must not contradict the runner, and must not say "running"
after the run is over.

Both defects were measured on the same 3-problem VerilogEval-Human run driven
through the real front door, and both come out of one code path: the status a
step gets in `steps/index.json` was derived from output-file EXISTENCE and
file MTIME alone, never from the verdict of the process that executed the step.

  DEFECT 1 -- `yosys_synth` returned FAIL (yosys rc=0, but synth_netlist_check
  rejected a 0-cell netlist) AFTER it had already written both artefacts flow
  step 9 declares. Existence therefore said "pass" while the runner's own
  report said FAIL, and `steps/index.json` -- what a dashboard, a human and any
  per-step tally read -- published the pass on all three problems.

  DEFECT 2 -- flow step D1 was recorded "running" on two of the three problems
  and "pass" on the third. The difference is mechanical: the third wrote all
  nineteen of D1's declared outputs; the other two were missing exactly one
  (phase1/extraction_patterns.json) while a sibling output had been written
  seconds earlier, which is the whole of `_lightweight_status`'s "running"
  test. That answer is true only at the instant of the query, and the collector
  froze it into a file nobody re-evaluates -- a step permanently
  indistinguishable from one that is still working.

Each test below is paired with a CONTROL that must stay green, because the
cheap way to pass either of these is to over-apply the fix: paint FAIL on rows
whose verdict is not theirs, or delete "running" from the vocabulary outright.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

import flow_dashboard_data as FDD   # noqa: E402
import step_output_collector as SOC  # noqa: E402
import step_preflight as SPF        # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures — built from the flow's OWN declarations, never from hard-coded paths
# --------------------------------------------------------------------------- #
def _declared_outputs(step_id: str):
    _doc, steps = FDD._load_flow()
    for st in steps:
        if str(st.get("id")) == step_id:
            return list(st.get("required_outputs") or [])
    raise AssertionError(f"flow declares no step {step_id!r}")


def _write_declared(project: Path, specs) -> None:
    """Materialise each declared output spec as a real file."""
    for spec in specs:
        rel = spec.split(" OR ")[0].replace("*", "X")
        p = project / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}\n")


def _orchestrator(project: Path, filename: str, steps) -> None:
    o = project / "reports" / "orchestrator"
    o.mkdir(parents=True, exist_ok=True)
    (o / filename).write_text(json.dumps(
        {"project": str(project), "verdict": "FAIL", "steps": steps}, indent=2))


def _index_status(project: Path, step_id: str) -> str:
    SOC.materialize(project)
    doc = json.loads((project / "steps" / "index.json").read_text())
    for st in doc["steps"]:
        if str(st.get("id")) == step_id:
            return str(st.get("status"))
    raise AssertionError(f"steps/index.json carries no step {step_id!r}")


# --------------------------------------------------------------------------- #
# the mapping this join stands on
# --------------------------------------------------------------------------- #
def test_the_runner_plan_still_maps_yosys_synth_to_flow_step_9():
    """The join is a lookup in the runner's OWN declared plan, not a guess.

    If this declaration ever moves, the two tests below would go quietly
    vacuous -- they would stop joining anything and pass for the wrong reason.
    """
    plan = SPF.RUNNER_PLANS["design_one_shot_runner"]
    assert ("yosys_synth", ("9",)) in plan.sites


# --------------------------------------------------------------------------- #
# DEFECT 1 — the runner's FAIL must reach the step record
# --------------------------------------------------------------------------- #
def test_a_failed_step_is_not_published_as_pass(tmp_path):
    # Step 9's declared artefacts BOTH exist: the runner wrote them and only
    # then judged the netlist unacceptable. File existence alone says "pass".
    _write_declared(tmp_path, _declared_outputs("9"))
    _orchestrator(tmp_path, "phase2_one_shot.json", [
        {"name": "yosys_synth", "status": "FAIL",
         "detail": "yosys rc=0 but synth_netlist_check FAILed (rc=1); cells=0"},
    ])
    assert _index_status(tmp_path, "9") == "fail"


def test_a_step_the_runner_did_not_fail_keeps_its_artefact_status(tmp_path):
    """CONTROL. Same tree, runner reports yosys_synth PASS -> step 9 stays pass.

    Without this, a fix that stamps `fail` on every joined row would pass the
    test above while destroying the record it was meant to repair.
    """
    _write_declared(tmp_path, _declared_outputs("9"))
    _orchestrator(tmp_path, "phase2_one_shot.json", [
        {"name": "yosys_synth", "status": "PASS", "detail": "cells=412"},
    ])
    assert _index_status(tmp_path, "9") == "pass"


def test_a_retried_step_is_judged_by_its_final_record(tmp_path):
    """CONTROL. The RTL repair/retry loop re-dispatches rtl_gen: BLOCKED, then PASS.

    Only the LAST record is the run's answer for flow step 1. A join that
    reacted to any failing record would report a red step 1 on every repair run
    that recovered -- which is most of them.
    """
    _write_declared(tmp_path, _declared_outputs("1"))
    _orchestrator(tmp_path, "phase2_one_shot.json", [
        {"name": "rtl_gen", "status": "BLOCKED", "detail": "input absent"},
        {"name": "rtl_gen", "status": "PASS", "detail": "deterministic emit"},
    ])
    assert _index_status(tmp_path, "1") != "fail"


def test_a_multi_step_site_is_left_unattributed(tmp_path):
    """CONTROL. `pnr` executes flow steps 15-22; its FAIL names no single row.

    Painting one verdict across eight rows sends the reader somewhere specific
    and wrong, so the join must decline it.
    """
    span = dict(SPF.RUNNER_PLANS["phase3_one_shot_runner"].sites)["pnr"]
    assert len(span) > 1, "fixture assumes pnr still spans several flow steps"
    for sid in span:
        _write_declared(tmp_path, _declared_outputs(sid))
    _orchestrator(tmp_path, "phase3_one_shot.json", [
        {"name": "pnr", "status": "FAIL", "detail": "route failed"},
    ])
    for sid in span:
        assert _index_status(tmp_path, sid) != "fail", sid


def test_two_sites_on_one_step_fold_by_verdict_not_by_list_order(tmp_path):
    """Phase 3 splits flow step 31 (DRC + LVS + ERC + Density) across the `drc`
    and `lvs` sites. They are contemporaneous dispatches of ONE step, so a
    passing one must not erase a failing one just by sitting later in the list.

    Both orders are asserted: an implementation that folds by iteration order
    passes one of them and fails the other.
    """
    _write_declared(tmp_path, _declared_outputs("31"))
    passing = {"name": "drc", "status": "PASS", "detail": "0 violations"}
    failing = {"name": "lvs", "status": "FAIL", "detail": "netlist mismatch"}
    for order in ([passing, failing], [failing, passing]):
        _orchestrator(tmp_path, "phase3_one_shot.json", list(order))
        assert _index_status(tmp_path, "31") == "fail", \
            [st["name"] for st in order]


def test_a_later_phase_supersedes_an_earlier_verdict_for_the_same_step(tmp_path):
    """CONTROL. Flow step 9 is executed by phase 2's `yosys_synth` AND by phase
    3's `synth`. A phase-3 re-run that succeeds is the run's final answer, so
    the earlier phase-2 failure must not keep the row red forever."""
    _write_declared(tmp_path, _declared_outputs("9"))
    _orchestrator(tmp_path, "phase2_one_shot.json", [
        {"name": "yosys_synth", "status": "FAIL", "detail": "cells=0"}])
    assert _index_status(tmp_path, "9") == "fail"
    _orchestrator(tmp_path, "phase3_one_shot.json", [
        {"name": "synth", "status": "PASS", "detail": "resynthesised"}])
    assert _index_status(tmp_path, "9") == "pass"


# --------------------------------------------------------------------------- #
# DEFECT 2 — a persisted record may not say "running"
# --------------------------------------------------------------------------- #
def _step_d1_partially_written(tmp_path: Path):
    """D1 with all but one declared output present, every file freshly written
    -- the exact shape that produced the frozen "running"."""
    specs = _declared_outputs("D1")
    assert len(specs) > 1
    _write_declared(tmp_path, specs[:-1])
    return specs


def test_no_persisted_step_record_can_say_running(tmp_path):
    _step_d1_partially_written(tmp_path)
    status = _index_status(tmp_path, "D1")
    assert status != "running"
    # and it must not have been "resolved" by calling an incomplete step done
    assert status != "pass"
    # every OTHER row of the durable record is bound by the same rule
    doc = json.loads((tmp_path / "steps" / "index.json").read_text())
    assert [s["id"] for s in doc["steps"] if s["status"] == "running"] == []


def test_a_live_query_can_still_say_running(tmp_path):
    """CONTROL, and the proof this was not fixed by deleting the state.

    A polling dashboard asks "what is true right now" and re-asks; for it,
    "running" is the correct and useful answer on the very same tree. Only the
    caller that PERSISTS the answer gives up the right to say it.
    """
    _step_d1_partially_written(tmp_path)
    live = FDD.collect(tmp_path, live=True)
    frozen = FDD.collect(tmp_path, live=False)

    def _d1(data):
        for ph in data["phases"]:
            for st in ph["steps"]:
                if st["id"] == "D1":
                    return st["status"]
        raise AssertionError("no D1")

    assert _d1(live) == "running"
    assert _d1(frozen) == "partial"
