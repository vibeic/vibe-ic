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


@pytest.mark.parametrize("supplied", ["embedded", "context", "context_changed", "vendor"])
def test_original_authority_keeps_supplied_rtl_bound_to_the_source(tmp_path, supplied):
    root = project(tmp_path, {"rtl/unit.sv": "module unit(input a,output y);assign y=a;endmodule"}
                   if supplied.startswith("context") else None,
                   prompt=("Complete this module.\n```verilog\nmodule unit(input a,output y);\nendmodule\n```\n"
                           if supplied == "embedded" else PROMPT))
    if supplied == "context_changed":
        (root / "input/rtl/unit.sv").write_text("module unit;endmodule\n")
    elif supplied == "vendor":
        source = root / "input/vendor_rtl/unit.sv"
        source.parent.mkdir(parents=True)
        source.write_text("module unit;endmodule\n")
    if supplied in {"context_changed", "vendor"}:
        with pytest.raises(ValueError, match="unbound supplied RTL"):
            pl.select_rtl_input(root, "original", "1", "2")
    else:
        pl.select_rtl_input(root, "original", "1", "2")
        gathered = runner._gather_phase1_plain_spec_text(root)
        if supplied == "embedded":
            assert "module unit(input a,output y);" in gathered.text
        else:
            _, handoff = runner._stage_author_knowledge_digests(root)
            context = handoff["read_context_from"]
            assert len(context) == 1
            assert Path(context[0]["path"]).read_bytes() == (
                root / "input/rtl/unit.sv").read_bytes()
            assert context[0]["sha256"] == hashlib.sha256(
                Path(context[0]["path"]).read_bytes()).hexdigest()
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
    # This is bounded native-consumer evidence, not D09-to-D11 acceptance.
    from _route_fixture import stage_owner_route
    stage_owner_route(root, "ip")
    program = Path(runner.__file__)
    invocation = subprocess.run([
        sys.executable, str(program), str(root), "--entry-step", "2", "--exit-step", "2",
        "--rtl-input", "original", "--top-name", "unit",
        "--skip-analog", "--skip-hardware", "--skip-phase3",
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


@pytest.mark.parametrize("prose,allowed", [
    ("Write a new module lane_cell with input d and output q. The supplied module is context.", True),
    ("Fix this module.", True),
    ("Optimize this module for area.", True),
    ("Complete this module.", True),
])
def test_embedded_context_uses_existing_task_nature(tmp_path, prose, allowed):
    prompt = prose + "\n```verilog\nmodule wrapper(input d,output q);\nassign q=d;\nendmodule\n```\n"
    root = project(tmp_path, prompt=prompt)
    if allowed:
        pl.select_rtl_input(root, "original", "1", "2")
        assert pl.gather_spec_text(root).startswith(prompt)
    else:
        with pytest.raises(ValueError, match="supplied RTL"):
            pl.select_rtl_input(root, "original", "1", "2")


def test_original_catalog_consumer_reads_the_selected_complete_source(tmp_path):
    import catalog_synth_safe_params_check as catalog
    root = project(tmp_path, {"requirements.txt": "No catalog core is reused.\n"},
                   prompt="Module name: neutral_unit\nInput a drives output q.\n")
    pl.select_rtl_input(root, "original", "1", "2")
    rc, result = catalog.run(root, None)
    assert (rc, result["verdict"]) == (0, "NOT_APPLICABLE"), result
    assert result["declaration"]["documents"] == [
        str(p.relative_to(root)) for p in pl.original_input_sources(root)]
    pl.select_rtl_input(root, "structured")
    rc, reverse = catalog.run(root, None)
    assert (rc, reverse["verdict"]) == (1, "NOT_MEASURED"), reverse
    assert "declaration missing" in reverse["reason"]


def test_original_consumer_projection_preserves_native_rtl_obligations(tmp_path):
    from _hostpaths import require_repo
    import execution_backend_gates as gates
    # Read the shipped artifact; the test does not reconstruct either contract.
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
                          "phase1_phase2_phase3.yaml")
    root = project(tmp_path)
    structured = {str(r["id"]): r for r in fy.load(source)["steps"]}
    pl.select_rtl_input(root, "original", "1", "2")
    original = {str(r["id"]): r for r in fy.load(source)["steps"]}
    commands = gates.required_commands(original["2"])
    assert any(c.startswith("rtl_hygiene_lint --project . --define SYNTHESIS --severity ERROR")
               and "--rtl-input original" in c for c in commands)
    assert any(c.startswith("rom_init_lint ") for c in commands)
    assert any(c.startswith("crosslayer_rewrite_equivalence_check ") for c in commands)
    assert not any(c.startswith("slot_pad_budget_check ") for c in commands)
    assert "--rtl-input original" in gates.required_commands(original["1"])[-1]
    for step in ("1", "2"):
        assert sri.input_contract(original[step], "structured") == structured[step]
    assert original["4"] == structured["4"]


def test_original_native_top_cannot_be_replaced_by_a_different_sole_module(tmp_path):
    root = project(tmp_path, prompt="Module name: requested_unit\nOutput q follows input a.\n")
    rtl = root / "phase2/stage1/rtl/other_unit.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module other_unit(input a,output q);assign q=a;endmodule\n")
    pl.select_rtl_input(root, "original", "1", "2")
    assert runner._v661_resolve_dut_module(root, "", None) is None


def test_original_ai_fidelity_review_is_still_required(tmp_path):
    import ai_signed_judgement as judgement
    root = project(tmp_path, prompt="Module name: neutral_unit\nOutput q follows input a.\n")
    rtl = root / "phase2/stage1/rtl/neutral_unit.v"
    rtl.parent.mkdir(parents=True)
    # Native hygiene cannot decide this semantic error; the author handoff
    # must still lack acceptance until its evidence-bound review is supplied.
    rtl.write_text("module neutral_unit(input a,output q);assign q=~a;endmodule\n")
    (rtl.parent.parent / "fallback_skill.md").write_text("spec-to-rtl\n")
    pl.select_rtl_input(root, "original", "1", "2")
    awaiting = judgement.pending(root, ("1",))
    assert "1" in awaiting and "awaiting_signed_judgement" in awaiting["1"]
    rows = [{"name": "rtl_gen", "status": "PASS", "detail": "native structure only"}]
    judgement.demote_runner_rows(rows, awaiting)
    assert rows[0]["status"] == "NOT_MEASURED"


@pytest.mark.parametrize("broken", [False, True])
@pytest.mark.parametrize("task_nature", ["spec_generation", "completion"])
def test_original_shipped_gate_consumers_validate_the_actual_rtl(tmp_path, broken, task_nature):
    if not shutil.which("verilator") or not shutil.which("yosys"):
        pytest.skip("canonical RTL consumers require native Verilator and Yosys")
    from _hostpaths import require_repo
    import flow_compliance_check as compliance
    import task_nature_route as nature
    prompt = ("Module name: neutral_unit\nOutput q follows input a.\n"
              if task_nature == "spec_generation" else
              "Complete the following Verilog module without changing its interface. "
              "Output q follows input a.\nmodule neutral_unit(input a,output q);\nendmodule\n")
    root = project(tmp_path, prompt=prompt)
    receipt = nature.route_decision_receipt(prompt, nature=task_nature,
        requested_evidence="lint_validated", delivery_target="rtl")
    assert receipt["input_contract"] == "original"
    assert receipt["task_nature"] == task_nature
    rtl = root / "phase2/stage1/rtl/neutral_unit.sv"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module neutral_unit(input a,output q);\n" +
                   ("missing_cell u(.a(a),.q(q));\n" if broken else "assign q=a;\n") +
                   "endmodule\n")
    pl.select_rtl_input(root, "original", "1", "2")
    gathered = runner._gather_phase1_plain_spec_text(root)
    assert gathered.text == prompt
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
                          "phase1_phase2_phase3.yaml")
    rows = {str(row["id"]): row for row in fy.load(source)["steps"]}
    for step in ("1", "2"):
        passed, reasons = compliance._evaluate_gate(root, rows[step]["gate"])
        assert passed is not broken, (step, reasons)
    assert not (root / "phase1/generated_docs").exists()
    report = json.loads((root / "reports/phase2/lint/rtl_hygiene.json").read_text())
    assert any(finding["severity"] == "ERROR" for finding in report) is broken
    # Reverting the source selection restores the structured contract. The
    # same source tree cannot manufacture missing D1/L9 evidence.
    pl.select_rtl_input(root, "structured")
    structured = {str(row["id"]): row for row in fy.load(source)["steps"]}
    admitted = sri.check_one(root, structured["2"], structured, {}, None)
    assert admitted["verdict"] != "READY", admitted
