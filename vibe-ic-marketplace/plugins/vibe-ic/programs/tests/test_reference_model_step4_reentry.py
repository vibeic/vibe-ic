"""A reference model filled after Step 4 asked for it can still be measured.

Step 4 hands a missing model to the expert and asks for a re-run. Before this,
nothing returned an unchanged candidate to the runner, so a candidate whose
required `sim` gate failed on an unfilled hook could never become acceptable.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import benchmark_dispatch as bd  # noqa: E402
import professional_tb_gen as tb  # noqa: E402


MODEL = '''\
import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def reference_model(dut):
    dut.a.value = 1
    await Timer(1, units="ns")
    assert int(dut.y.value) == 1
    dut._log.info("PROFESSIONAL_TB PASS")
'''
SIM_FAILED = {"failed_required": ["sim"], "in_scope": {"sim": "FAIL"},
              "eligibility": "INELIGIBLE"}
SIM_PASSED = {"failed_required": [], "in_scope": {"sim": "PASS"},
              "eligibility": "ELIGIBLE"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _project(tmp_path: Path, *, tier="hook_unfilled", measured=None, model=None) -> Path:
    project = tmp_path / "proj"
    out = project / "phase2/stage1/sim_professional/neutral"
    out.mkdir(parents=True)
    if model is not None:
        (out / "expert_reference_tb.py").write_text(model)
    report = project / bd._PROFESSIONAL_TB_REPORT
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "out_dir": str(out), "reference_model_tier": tier,
        **({"reference_model_sha256": measured} if measured else {})}))
    return project


@pytest.fixture
def sim_failed(monkeypatch):
    monkeypatch.setattr(bd, "_required_gate_ledger", lambda _result: SIM_FAILED)


def test_model_filled_after_an_unfilled_hook_reenters(tmp_path, sim_failed):
    project = _project(tmp_path, model=MODEL)
    reason = bd._reference_model_reentry_reason(project, {})
    assert reason and reason.startswith("REFERENCE_MODEL_CHANGED")
    assert _sha(MODEL) in reason


def test_a_hook_that_is_still_unfilled_does_not_reenter(tmp_path, sim_failed):
    assert bd._reference_model_reentry_reason(_project(tmp_path), {}) is None


@pytest.mark.parametrize("model", [
    MODEL.replace('dut._log.info("PROFESSIONAL_TB PASS")', 'pass'),
    MODEL + "\nraise cocotb.result.TestSkip()\n",
    "this is not python (",
    MODEL + "\x00",
], ids=["no-pass-token", "testskip", "unparsable", "nul-byte"])
def test_a_model_the_producer_would_reject_does_not_reenter(tmp_path, sim_failed, model):
    assert bd._reference_model_reentry_reason(_project(tmp_path, model=model), {}) is None


def test_the_measured_model_does_not_reenter_again(tmp_path, sim_failed):
    """A real mismatch on the model already measured stays a failure, not a loop."""
    project = _project(tmp_path, tier="expert_filled", measured=_sha(MODEL), model=MODEL)
    assert bd._reference_model_reentry_reason(project, {}) is None


def test_legacy_expert_report_without_identity_gets_one_fresh_attempt(tmp_path, sim_failed):
    project = _project(tmp_path, tier="expert_filled", model=MODEL)
    reason = bd._reference_model_reentry_reason(project, {})
    decision = "REGATE" if reason else "KEEP"
    assert decision == "REGATE"
    report = project / bd._PROFESSIONAL_TB_REPORT
    current = json.loads(report.read_text())
    current["reference_model_sha256"] = _sha(MODEL)
    report.write_text(json.dumps(current))
    assert bd._reference_model_reentry_reason(project, {}) is None


def test_a_replaced_model_reenters_after_a_measured_failure(tmp_path, sim_failed):
    project = _project(tmp_path, tier="expert_filled", measured=_sha("older"), model=MODEL)
    assert bd._reference_model_reentry_reason(project, {})


def test_a_tier_that_never_reads_the_model_does_not_reenter(tmp_path, sim_failed):
    """A generated reference ignores the file, so re-entry could never change anything."""
    project = _project(tmp_path, tier="closed_form", model=MODEL)
    assert bd._reference_model_reentry_reason(project, {}) is None


def test_a_passing_sim_gate_does_not_reenter(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "_required_gate_ledger", lambda _result: SIM_PASSED)
    assert bd._reference_model_reentry_reason(_project(tmp_path, model=MODEL), {}) is None


def test_an_accepted_candidate_does_not_reenter(tmp_path, sim_failed):
    project = _project(tmp_path, model=MODEL)
    assert bd._reference_model_reentry_reason(project, {"accepted": True}) is None


@pytest.mark.parametrize("report_text", [None, "not json", "[]"],
                         ids=["absent", "corrupt", "wrong-shape"])
def test_an_unusable_gate_report_does_not_reenter(tmp_path, sim_failed, report_text):
    project = _project(tmp_path, model=MODEL)
    report = project / bd._PROFESSIONAL_TB_REPORT
    if report_text is None:
        report.unlink()
    else:
        report.write_text(report_text)
    assert bd._reference_model_reentry_reason(project, {}) is None


@pytest.mark.parametrize("tier", [[], {}], ids=["list", "object"])
def test_malformed_model_tier_keeps_ordinary_resume_ineligible(tmp_path, monkeypatch, tier):
    import test_benchmark_program_first_ai_review as parent

    run, task, _runner = parent._dispatched_parent_task(tmp_path)
    parent._solve_report(run, task)
    project = Path(task["project"])
    out = project / "phase2/stage1/sim_professional/dut"
    out.mkdir(parents=True)
    report = project / bd._PROFESSIONAL_TB_REPORT
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"out_dir": str(out), "reference_model_tier": tier}))
    monkeypatch.setattr(bd, "_required_gate_ledger", lambda _result: {
        **SIM_FAILED, "unmeasured_required": []})
    parent._stub_dispatched_reentry(monkeypatch)

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    result = json.loads((run / "solve_report.json").read_text())["results"][0]
    assert result["accepted"] is False


def test_ineligible_row_names_the_model_only_when_step4_is_waiting_on_it(tmp_path):
    project = _project(tmp_path)
    assert bd._reference_model_next(project) == {}
    report = project / bd._PROFESSIONAL_TB_REPORT
    handoff = {"status": "REQUIRED", "artifact_path": "/x/expert_reference_tb.py"}
    report.write_text(json.dumps({"reference_model_handoff": handoff}))
    row = bd._reference_model_next(project)
    assert row["reference_model_handoff"] == handoff
    assert "/x/expert_reference_tb.py" in row["required_next"]
    assert "semantic PASS does not discharge" in row["required_next"]
    report.unlink()
    assert bd._reference_model_next(project) == {}
    assert bd._reference_model_next(None) == {}


def test_identity_is_none_unless_the_producer_would_load_the_model(tmp_path):
    assert tb.reference_model_identity(tmp_path) is None
    (tmp_path / "expert_reference_tb.py").write_text(MODEL)
    assert tb.reference_model_identity(tmp_path) == _sha(MODEL)


def _backup_task(tmp_path, exit_step, required_top="TopModule"):
    project = tmp_path / "proj"
    (project / "input").mkdir(parents=True)
    (project / "input/phase1_prompt.md").write_text("repair this module")
    return bd._make_ai_backup_task(
        "P1", project, ["rtl-repair"], "route_declaration", "detail", "bench",
        tmp_path, tmp_path, required_top=required_top, exit_step=exit_step)


@pytest.mark.parametrize("exit_step", ["4", "9", 15])
def test_backup_task_names_the_model_when_its_window_reaches_step4(tmp_path, exit_step):
    handoff = _backup_task(tmp_path, exit_step)["reference_model_handoff"]
    assert handoff["status"] == "CONDITIONAL"
    assert handoff["fallback_skill"] == "testbench-gen"
    assert handoff["artifact_path"].endswith(
        "phase2/stage1/sim_professional/TopModule/expert_reference_tb.py")


@pytest.mark.parametrize("exit_step", ["2", "3", None, "D13"])
def test_backup_task_stays_unchanged_before_step4(tmp_path, exit_step):
    assert "reference_model_handoff" not in _backup_task(tmp_path, exit_step)


def test_backup_task_without_a_fixed_top_says_which_directory_is_open(tmp_path):
    handoff = _backup_task(tmp_path, "4", required_top=None)["reference_model_handoff"]
    assert "/sim_professional/<top_module>/" in handoff["artifact_path"]
