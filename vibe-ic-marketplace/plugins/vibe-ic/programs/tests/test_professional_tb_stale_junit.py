"""A professional verdict must belong to the current generator invocation."""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path


PROGRAMS = Path(os.environ.get(
    "VIBEIC_PROFESSIONAL_RUNNER_SUBJECT",
    str(Path(__file__).resolve().parents[1]),
)).resolve()
SPEC = importlib.util.spec_from_file_location(
    "professional_runner_subject", PROGRAMS / "design_one_shot_runner.py")
assert SPEC is not None and SPEC.loader is not None
SUBJECT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SUBJECT
SPEC.loader.exec_module(SUBJECT)


def test_unfilled_current_run_invalidates_prior_green_junit(
        tmp_path, monkeypatch):
    out = tmp_path / "phase2/stage1/sim_professional/dut"
    out.mkdir(parents=True)
    stale = out / "results.xml"
    stale.write_text(
        "<testsuite tests='1' failures='0' errors='0' skipped='0'>"
        "<testcase name='prior_arm'/></testsuite>")
    generated = {
        "status": "PASS",
        "dut_kind": "generic",
        "out_dir": str(out),
        "reference_model_tier": "hook_unfilled",
        "files": ["tb_dut.py"],
    }
    stub = types.SimpleNamespace(generate=lambda _project: generated)
    monkeypatch.setitem(sys.modules, "professional_tb_gen", stub)

    step = SUBJECT.step_professional_tb_gen(
        tmp_path, "dut", "configured-container")
    assert step.status == "INCOMPLETE"
    assert stale.exists() is False
    report = (tmp_path / "reports/phase2/gates/professional_tb.json").read_text()
    assert '"stale_results_invalidated": true' in report
