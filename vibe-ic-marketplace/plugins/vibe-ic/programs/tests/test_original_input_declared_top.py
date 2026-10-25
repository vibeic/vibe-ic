"""Original public module metadata reaches the existing deterministic producer."""
import re
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _path_layout as pl
import design_one_shot_runner as runner
import benchmark_dispatch as dispatch
import flow_phase_attribution as fpa
import port_parser


BODY = """All input and output ports are one bit.
 - input x3
 - input x2
 - input x1
 - output f

Implement the combinational circuit described by this complete truth table:
 x3 | x2 | x1 | f
 0 | 0 | 0 | 0
 0 | 0 | 1 | 0
 0 | 1 | 0 | 0
 0 | 1 | 1 | 1
 1 | 0 | 0 | 0
 1 | 0 | 1 | 1
 1 | 1 | 0 | 1
 1 | 1 | 1 | 1
"""


@pytest.mark.parametrize("declaration", ["unique", "missing", "conflicting"])
def test_original_program_emit_uses_only_unique_public_module_name(tmp_path, declaration):
    root = tmp_path / "unrelated_container_name"
    prompt = BODY if declaration == "missing" else "Module name: cedar_vote\n" + BODY
    if declaration == "conflicting":
        prompt += "\nModule name: other_owner\n"
    source = root / "input/phase1_prompt.md"
    source.parent.mkdir(parents=True)
    source.write_text(prompt)
    previous = pl._RTL_INPUT
    try:
        pl.select_rtl_input(root, "original", "1", "1")
        result = runner.step_rtl_gen(root, "unknown")
    finally:
        pl._RTL_INPUT = previous
    files = list((root / "phase2/stage1/rtl").glob("*.sv"))
    if declaration != "unique":
        assert not files
        assert result.extras["fallback_skill"] == "spec-to-rtl"
        return
    assert result.status == "PASS", result
    assert [file.name for file in files] == ["cedar_vote.sv"]
    text = files[0].read_text()
    assert re.search(r"\bmodule\s+cedar_vote\b", text)
    inputs, outputs = port_parser.parse_ports(text)
    assert set(inputs) == {("x3", 1), ("x2", 1), ("x1", 1)}
    assert set(outputs) == {("f", 1)}
    if shutil.which("iverilog"):
        compiled = subprocess.run(["iverilog", "-g2012", "-s", "cedar_vote",
                                   "-o", str(tmp_path / "native.vvp"), str(files[0])],
                                  capture_output=True, text=True)
        assert compiled.returncode == 0, compiled.stderr


@pytest.mark.parametrize("override", [None, "wrong_owner"])
def test_original_ordinary_step1_through_step2_uses_same_public_top(tmp_path, override):
    if not shutil.which("yosys"):
        pytest.skip("fresh native hygiene elaboration requires Yosys")
    root = tmp_path / "unrelated_container_name"
    source = root / "input/phase1_prompt.md"
    source.parent.mkdir(parents=True)
    source.write_text("Module name: cedar_vote\n" + BODY)
    switch = root / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True)
    switch.write_text('{"steps":{"2":"direct"}}')
    program = Path(runner.__file__).parent / "vibe_ic_one_shot_runner.py"
    command = [sys.executable, str(program), str(root), "--entry-step", "1", "--exit-step", "2",
               "--rtl-input", "original", "--route", "ip", "--skip-analog",
               "--skip-hardware", "--skip-phase3", "--no-dashboard"]
    if override:
        command += ["--top-name", override]
    native = subprocess.run(command, capture_output=True, text=True)
    rtl = list((root / "phase2/stage1/rtl").glob("*.sv"))
    if override:
        assert native.returncode != 0
        assert "ORIGINAL_TOP_CONFLICT" in native.stderr
        assert not rtl
        return
    assert [path.name for path in rtl] == ["cedar_vote.sv"]
    inputs, outputs = port_parser.parse_ports(rtl[0].read_text())
    assert set(inputs) == {("x3", 1), ("x2", 1), ("x1", 1)}
    assert set(outputs) == {("f", 1)}
    report = json.loads((root / "reports/orchestrator/phase2_one_shot.json").read_text())
    solving = next(row for row in report["steps"] if row["name"] == "rtl_gen")
    validate = next(row for row in report["steps"] if row["name"] == "rtl_validate")
    assert solving["status"] == "PASS", solving
    assert validate["status"] == "PASS", validate
    invocation = validate["extras"]["command"]
    assert invocation[invocation.index("--top-module") + 1] == "cedar_vote"
    ledger = dispatch._required_gate_ledger({
        "exit": "2", "phases": {"phase3_verifying": fpa.phase3_verifying(report, None)}})
    (root / "reports/required_gate_ledger.json").write_text(json.dumps(ledger, indent=2))
    assert ledger["eligibility"] == "ELIGIBLE", ledger
