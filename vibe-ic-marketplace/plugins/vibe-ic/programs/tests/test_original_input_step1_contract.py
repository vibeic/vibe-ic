"""The ordinary RTL owner can explicitly consume original source bytes."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _flow_yaml as fy
import _path_layout as pl
import benchmark_io_adapter as bio
import benchmark_dispatch as dispatch
import design_one_shot_runner as runner
import flow_phase_attribution as fpa
import lesson_consumption_check as lessons
import step_preflight as preflight
import step_required_inputs_check as sri


PROMPT = "Module name: median_window\r\nRetain the median of five accepted bytes.\r\n來源尾端。\r\n"


@pytest.fixture(autouse=True)
def restore_contract():
    previous = pl._RTL_INPUT
    yield
    pl._RTL_INPUT = previous


def project(tmp_path, context=None, prompt=PROMPT):
    root = tmp_path / "unit"
    bio.stage("cvdp", {"id": "unit", "record": {"input": {
        "prompt": prompt, "context": context or {}}}}, root)
    return root


def test_shared_projection_keeps_default_and_physical_dependencies(tmp_path):
    root = project(tmp_path)
    rows = {str(row["id"]): row for row in fy.load()["steps"]}
    assert any(str(item["from"]) == "D1" for item in rows["1"]["required_inputs"])
    assert any(str(item["from"]) == "D1" for item in rows["2"]["required_inputs"])
    pl.select_rtl_input(root, "original", "1", "2")
    raw = {str(row["id"]): row for row in fy.load()["steps"]}
    assert raw["1"]["blocks_on"] == []
    assert raw["2"]["blocks_on"] == [1]
    assert raw["4"] == rows["4"]
    by_id = rows
    assert sri.check_one(root, rows["1"], by_id, {}, None)["verdict"] == "READY"
    decision = preflight.entry_admission(root, "design_one_shot_runner", "1")
    assert decision["admitted"], decision
    assert decision["span"] == ("1",)
    other = tmp_path / "other"
    (other / "input").mkdir(parents=True)
    (other / "input/phase1_prompt.md").write_text("A different structured project.\n")
    assert pl.rtl_input(other) == "structured"
    assert not preflight.entry_admission(other, "design_one_shot_runner", "1")["admitted"]
    assert sri.input_contract(raw["1"], "structured") == rows["1"]


def test_raw_reader_and_handoff_preserve_complete_prompt_and_context(tmp_path):
    root = project(tmp_path, {"requirements.txt": "每五筆一組。\r\nNo sliding window.\r\n"})
    # Stale generated prose must never complete a raw deterministic recognizer.
    generated = root / "phase1/generated_docs"
    generated.mkdir(parents=True)
    (generated / "L1_OLD.json").write_text('{"ic_name":"stale_owner"}')
    pl.select_rtl_input(root, "original", "1", "1")
    gathered = runner._gather_phase1_plain_spec_text(root)
    assert gathered.refusal is None
    assert gathered.text.startswith(PROMPT)
    assert "每五筆一組。\r\nNo sliding window.\r\n" in gathered.text
    assert "stale_owner" not in pl.gather_spec_text(root, gathered.text)
    assert runner.detect_ic_class(root)[0] == "unknown"
    assert runner._try_deterministic_rtl_dispatch(root, 0) is None
    hint, extras = runner._stage_author_knowledge_digests(root)
    assert extras["input_authority"] == "original"
    assert extras["read_prompt_from"] == str(root / "input/phase1_prompt.md")
    assert extras["original_prompt_sha256"] == hashlib.sha256(PROMPT.encode()).hexdigest()
    assert extras["original_prompt_bytes"] == len(PROMPT.encode())
    assert len(extras["read_context_from"]) == 1
    context = extras["read_context_from"][0]
    assert Path(context["path"]).read_bytes() == "每五筆一組。\r\nNo sliding window.\r\n".encode()
    assert "COMPLETE original prompt" in hint
    assert "declaration_contract" not in extras
    assert pl.gather_spec_text(root).startswith(PROMPT)
    assert lessons.main(["--project", str(root), "--rtl-input", "original",
                         "--digest", extras["lessons_digest"]]) == 0


@pytest.mark.parametrize("scope", [("D1", "2"), ("1", "4"), ("1", None), (None, None)])
def test_original_is_only_an_explicit_bounded_rtl_contract(tmp_path, scope):
    root = project(tmp_path)
    with pytest.raises(ValueError, match="bounded Step 1/2"):
        pl.select_rtl_input(root, "original", *scope)


@pytest.mark.parametrize("supplied", ["embedded", "context", "vendor"])
def test_supplied_rtl_cannot_be_renamed_spec_generation(tmp_path, supplied):
    root = project(tmp_path, {"rtl/unit.sv": "module unit(input a,output y);assign y=a;endmodule"}
                   if supplied == "context" else None)
    if supplied == "embedded":
        (root / "input/phase1_prompt.md").write_text(
            "Fix this module.\n```verilog\nmodule unit(input a,output y);\nendmodule\n```\n")
    elif supplied == "vendor":
        source = root / "input/vendor_rtl/unit.sv"
        source.parent.mkdir(parents=True)
        source.write_text("module unit;endmodule\n")
    with pytest.raises(ValueError, match="supplied RTL"):
        pl.select_rtl_input(root, "original", "1", "2")
    pl.select_rtl_input(root, "structured")
    assert pl.rtl_input(root) == "structured"


@pytest.mark.parametrize("mutation", ["prompt", "context", "symlink"])
def test_original_input_mutation_or_link_is_refused(tmp_path, mutation):
    root = project(tmp_path, {"requirements.txt": "Use disjoint groups.\n"})
    pl.select_rtl_input(root, "original", "1", "1")
    if mutation == "prompt":
        (root / "input/phase1_prompt.md").write_bytes(b"Same path, different source.\n")
    else:
        source = root / "input/public_original/files/requirements.txt"
        if mutation == "context":
            source.write_text("Use a sliding window.\n")
        else:
            source.unlink()
            source.symlink_to(root / "input/phase1_prompt.md")
    with pytest.raises(ValueError, match="PUBLIC_INPUT_HANDOFF_INVALID"):
        pl.original_input_sources(root)


def test_standalone_checker_selects_same_contract(tmp_path, capsys):
    root = project(tmp_path)
    assert sri.main([str(root), "--step", "1", "--rtl-input", "original", "--quiet"]) == 0
    assert sri.main([str(root), "--step", "1", "--quiet"]) == 1
    assert sri.main([str(root), "--step", "4", "--rtl-input", "original", "--quiet"]) == 2


@pytest.mark.parametrize("broken", [False, True])
def test_original_direct_step2_runs_native_hygiene_without_future_synthesis(tmp_path, broken):
    if not shutil.which("verilator"):
        pytest.skip("fresh native RTL lint requires Verilator")
    root = project(tmp_path, prompt="Module name: unit\nCombinational one-bit input a and output y. y follows a.\n")
    rtl = root / "phase2/stage1/rtl/unit.sv"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module unit(input a, output y);\n"
                   + ("missing_cell u(.a(a),.y(y));\n" if broken else "assign y = a;\n")
                   + "endmodule\n")
    switch = root / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True)
    switch.write_text('{"steps":{"2":"direct"}}')
    pl.select_rtl_input(root, "original", "2", "2")
    result = runner.step_rtl_lint_tool(root, top_name="unit")
    assert result.name == "rtl_validate"
    assert result.status == ("FAIL" if broken else "PASS"), result
    assert result.extras["producer"] == "rtl_lint_tool"
    assert result.extras["checker"] == "verilator_lint_gate"
    assert result.extras["tool_mode"] == "direct"
    assert result.extras["exit_code"] == int(broken)
    assert "--project" not in result.extras["command"]
    report = root / "reports/phase2/lint/rtl_hygiene.json"
    findings = json.loads(report.read_text())["blocking"]
    assert bool(findings) is broken
    assert not (root / "phase2/stage2/synth/yosys.log").exists()
    # Consume the real ordinary report, including its actual entry sentinel.
    # No AI review, D1 PASS or site-status fixture is authored by this test.
    program = Path(runner.__file__).parent / "vibe_ic_one_shot_runner.py"
    invocation = subprocess.run([
        sys.executable, str(program), str(root), "--entry-step", "2", "--exit-step", "2",
        "--rtl-input", "original", "--route", "ip", "--top-name", "unit",
        "--skip-analog", "--skip-hardware", "--skip-phase3", "--no-dashboard",
    ], capture_output=True, text=True)
    report_path = root / "reports/orchestrator/phase2_one_shot.json"
    assert report_path.is_file(), invocation.stderr
    measured = json.loads(report_path.read_text())
    site = next(row for row in measured["steps"] if row["name"] == "rtl_validate")
    assert site["status"] == ("FAIL" if broken else "PASS"), site
    assert site["extras"]["producer"] == "rtl_lint_tool"
    assert site["extras"]["exit_code"] == int(broken)
    ledger = dispatch._required_gate_ledger({
        "exit": "2", "phases": {"phase3_verifying": fpa.phase3_verifying(measured, None)}})
    (root / "reports/required_gate_ledger.json").write_text(json.dumps(ledger, indent=2))
    assert ledger["eligibility"] == ("INELIGIBLE" if broken else "ELIGIBLE"), ledger
    assert ledger["in_scope"]["rtl_validate"] == ("FAIL" if broken else "PASS")
    final_findings = json.loads(report.read_text())
    assert bool(final_findings["blocking"]) is broken
    assert not (root / "phase2/stage2/synth/yosys.log").exists()
    pl.select_rtl_input(root, "structured")
    assert runner.step_rtl_lint_tool(root, top_name="unit") is None
