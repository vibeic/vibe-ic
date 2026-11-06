"""Retain public routing and real native lint controls after rollup removal."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import benchmark_dispatch as dispatch
import benchmark_io_adapter as io
import flow_phase_attribution as attribution
import task_nature_route as routes


def test_rtl_evidence_exit_uses_the_existing_router_registry():
    for name, row in routes.EVIDENCE_EXIT.items():
        expected = name in ("existence", "lint_validated", "behaviour", "proof")
        assert routes.is_rtl_only_evidence(name) is expected
        assert routes.is_rtl_only_evidence(exit_step=row["exit_step"]) is expected
        assert routes.is_rtl_only_evidence(name, exit_step=row["exit_step"]) is expected
        assert routes.is_rtl_only_evidence(name, exit_step="unrecognised") is False
    assert routes.is_rtl_only_evidence() is False
    assert routes.is_rtl_only_evidence("unrecognised") is False


@pytest.mark.parametrize("valid", [True, False])
def test_public_native_lint_and_collector_preserve_supplied_inputs(tmp_path, valid):
    assert shutil.which("verilator"), "native validation requires Verilator"
    project = tmp_path / "project"
    prompt = ("Module name: plain\nInput value_i and output value_o are eight-bit vectors. "
              "Output value_o is the bitwise inversion of value_i.\n")
    documents = [project / "input/docs/spec.md", project / "input/phase1_prompt.md"]
    for path in documents:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prompt)
    rtl = project / "phase2/stage1/rtl/plain.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module plain(input [7:0] value_i, output [7:0] value_o);\n"
                   + ("assign value_o = ~value_i;\n" if valid else "assign value_o = ;\n")
                   + "endmodule\n")
    original = {path: path.read_bytes() for path in [*documents, rtl]}
    argv = dispatch._solver_argv(PROGRAMS / "vibe_ic_one_shot_runner.py",
                                 project, "2", "2", "ip", "original", "rtl")
    argv += ["--from", "rtl_validation_and_lint", "--to", "rtl_validation_and_lint"]
    invocation = subprocess.run(argv, capture_output=True, text=True, timeout=80)
    assert (invocation.returncode == 0) is valid, invocation.stdout + invocation.stderr
    native = json.loads((project / "reports/flow_engine.json").read_text())
    lint = next(row for row in native["steps"] if row["name"] == "rtl_validation_and_lint")
    assert lint["status"] == ("PASS" if valid else "FAIL"), native
    compiler = next(row for row in lint["native_steps"] if row["name"] == "verilator")
    assert compiler["ran"] is True
    assert compiler["exit_code"] == int(not valid)
    measured = json.loads((project / "reports/phase2/lint/rtl_hygiene.json").read_text())
    assert isinstance(measured, list)
    assert bool(measured) is not valid
    collected = io.collect("verilogeval-v2", project.name, project,
                            supplied_rtl=True, required_top="plain")
    assert collected["ok"] is True, collected
    assert collected["completion"].encode() == original[rtl]
    assert io.collect("verilogeval-v2", project.name, project,
                      required_top="plain")["ok"] is False
    ledger = dispatch._required_gate_ledger({"exit": "2", "phases": attribution.attribute(project)})
    assert ledger["eligibility"] == ("ELIGIBLE" if valid else "INELIGIBLE"), ledger
    assert {path: path.read_bytes() for path in original} == original
