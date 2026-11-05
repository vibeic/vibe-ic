#!/usr/bin/env python3
"""Flow step FS1: the phase-2 runner runs the FMEDA producer before the audit.

The FS1 gate's first clause, `fmeda_fault_injection_coverage ... --json
reports/phase2/safety/fmeda_coverage.json`, is also run synchronously by
`design_one_shot_runner.step_fmeda_fault_injection` before the audit reads the
report. `main()` dispatches it after the DFT/LEC chain (FS1 blocks on step 11).

The arms call the real producer on a real RTL tree; no simulator is needed
because the designs here declare no safety mechanism or have no RTL.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
RUNNER = PROGRAMS / "design_one_shot_runner.py"
REPORT = "reports/phase2/safety/fmeda_coverage.json"


def _runner():
    spec = importlib.util.spec_from_file_location("design_one_shot_runner",
                                                  RUNNER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["design_one_shot_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


def _project(tmp_path: Path, rtl: dict) -> Path:
    project = tmp_path / "proj"
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    for name, text in rtl.items():
        (rtl_dir / name).write_text(text)
    return project


COUNTER = ("module cnt(input clk, input rst, output reg [3:0] q);\n"
           "  always @(posedge clk) if (rst) q <= 0; else q <= q + 1;\n"
           "endmodule\n")


def test_the_command_is_the_one_the_fs1_gate_states():
    mod = _runner()
    read = getattr(mod, "fmeda_producer_command", lambda *a: None)()
    assert read == ("fmeda_fault_injection_coverage . --rtl-dir "
                    "phase2/stage1/rtl --asil D --json " + REPORT)


def test_the_runner_writes_the_report_on_a_design_without_a_mechanism(tmp_path, monkeypatch):
    mod = _runner()
    project = _project(tmp_path, {"cnt.v": COUNTER})
    step = getattr(mod, "step_fmeda_fault_injection", None)
    assert step is not None, "no runner step produces FS1's report"
    actual_run = mod._pr.run
    called = []
    def observed_run(argv, *args, **kwargs):
        called.append(Path(argv[1]).name)
        return actual_run(argv, *args, **kwargs)
    monkeypatch.setattr(mod._pr, 'run', observed_run)
    row = step(project)
    report = json.loads((project / REPORT).read_text())
    assert report["program"] == "fmeda_fault_injection_coverage"
    assert report["verdict"] == "NOT_APPLICABLE"
    assert row.status == "NOT_MEASURED"
    assert row.output_files == [REPORT]
    # The reader has no native diagnostic counts for a non-safety design.
    assert called == ['fmeda_fault_injection_coverage.py', 'fmeda_coverage_check.py']
    recomputed = project / 'reports/phase2/safety/fmeda_coverage_gate.json'
    assert recomputed.is_file()
    assert json.loads(recomputed.read_text())['verdict'] == 'NOT_MEASURED'



def test_an_rtl_dir_with_no_source_is_not_measured(tmp_path):
    mod = _runner()
    project = _project(tmp_path, {"notes.txt": "no verilog here\n"})
    row = mod.step_fmeda_fault_injection(project)
    assert row.status == "NOT_MEASURED"
    assert row.reason_class == "input_absent"
    report = json.loads((project / REPORT).read_text())
    assert report["verdict"] == "UNMEASURED_NO_RTL_READ"


def test_a_failed_current_producer_cannot_reuse_a_stale_report(tmp_path,
                                                               monkeypatch):
    """A prior FS1 PASS must not survive a producer that writes nothing.

    MUTATION THIS CATCHES: reading the canonical report after a failed
    producer without clearing it first, which turns the stale PASS into the
    current run's result.
    """
    mod = _runner()
    project = _project(tmp_path, {"cnt.v": COUNTER})
    report = project / REPORT
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "program": "fmeda_fault_injection_coverage",
        "verdict": "PASS",
        "applicable": True,
        "injected_faults": 1,
        "detected_faults": 1,
        "baseline_valid": True,
    }))

    monkeypatch.setattr(
        mod._pr, "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="current producer failed"),
    )
    row = mod.step_fmeda_fault_injection(project)

    assert row.status == "NOT_MEASURED"
    assert row.extras["producer_exit"] == 1
    assert not report.exists(), "a failed run must not leave a stale report"


def test_a_flow_without_the_clause_runs_nothing(tmp_path):
    mod = _runner()
    project = _project(tmp_path, {"cnt.v": COUNTER})
    flow = tmp_path / "flow.yaml"
    flow.write_text("steps:\n  - id: FS1\n    programs: [fmeda_coverage_check]\n"
                    "    gate:\n      all_of:\n        - program_exit_zero: "
                    "\"fmeda_coverage_check . --json x.json\"\n")
    row = mod.step_fmeda_fault_injection(project, flow_yaml=flow)
    assert row.status == "NOT_MEASURED"
    assert row.reason_class == "not_executed"
    assert not (project / REPORT).exists()


def _main():
    for node in ast.parse(RUNNER.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("main not found")


def test_main_dispatches_fs1_after_the_dft_chain_and_inside_the_window():
    main = _main()
    lines = {}
    for call in (n for n in ast.walk(main) if isinstance(n, ast.Call)):
        name = getattr(call.func, "id", None) or getattr(call.func, "attr", "")
        lines.setdefault(name, []).append(call.lineno)
    assert "step_fmeda_fault_injection" in lines, \
        "main() never dispatches step FS1's producer"
    dft = [a.lineno for a in ast.walk(main) if isinstance(a, ast.Name)
           and a.id == "step_dft_lec_chain"]
    assert dft and min(lines["step_fmeda_fault_injection"]) > max(dft)
    # the dispatch sits in the else-branch of a test that reads the window
    for node in ast.walk(main):
        if isinstance(node, ast.If) and any(
                isinstance(c, ast.Call) and getattr(c.func, "id", "")
                == "step_fmeda_fault_injection"
                for s in node.orelse for c in ast.walk(s)):
            names = {n.id for n in ast.walk(node.test)
                     if isinstance(n, ast.Name)}
            assert {"_after_exit", "_bounded"} <= names
            break
    else:
        raise AssertionError("FS1 dispatch is not guarded by the run window")
