"""Declared parameter minima become elaboration guards on two design shapes."""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import serial_parallel_mul_synth as synth
import spec_conformance_check as conformance
import pytest
from parameter_range_contract import minimums, has_elaboration_guard


def _project(tmp_path, name, *, minimum):
    project = tmp_path / name
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    ports = [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "operand", "direction": "input", "width": "WIDTH-1:0",
         "width_symbolic": "WIDTH-1:0", "msb": "WIDTH-1"},
        {"name": "serial_in", "direction": "input", "width": 1},
        {"name": "serial_out", "direction": "output", "width": 1},
    ]
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": name, "top_ports": ports, "ports": ports}))
    # The generator requires the design input to state its reset style (it
    # never chooses one), as test_serial_parallel_mul_synth's fixture does.
    (docs / "L2_FRS.json").write_text(json.dumps({
        "description": "serial-parallel multiplier: serial_out = operand * serial_in mod 2^WIDTH"
                       "; synchronous active-high reset"}))
    (docs / "L3_DETAIL_SPEC.json").write_text(json.dumps({
        "parameter_ranges": ([{"name": "WIDTH", "min": minimum}]
                             if minimum is not None else [])}))
    return project


def test_legal_minimum_is_emitted_and_gate_catches_missing_guard(tmp_path, capsys):
    project = _project(tmp_path, "filter_cell", minimum=5)
    spec, why = synth.extract_serial_parallel_mul_spec(project, "digital_arithmetic_primitive")
    assert spec is not None, why
    assert spec["size_min"] == 5
    rtl = synth.emit_rtl(spec)
    assert has_elaboration_guard(rtl, "WIDTH", 5)
    rtl_dir = project / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    source = rtl_dir / "filter_cell.v"
    source.write_text(rtl)
    args = ["--spec", str(project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"),
            "--rtl-dir", str(rtl_dir), "--top", "filter_cell"]
    assert conformance.main(args) == 0
    capsys.readouterr()
    source.write_text(rtl.replace("initial $fatal", "initial $display"))
    assert conformance.main(args) == 1
    assert "parameter-range-guard-missing" in capsys.readouterr().out


def test_other_parameter_has_no_invented_minimum(tmp_path):
    project = _project(tmp_path, "vector_cell", minimum=None)
    spec, why = synth.extract_serial_parallel_mul_spec(project, "digital_arithmetic_primitive")
    assert spec is not None, why
    assert spec.get("size_min") is None
    assert not has_elaboration_guard(synth.emit_rtl(spec), "WIDTH", 5)
    assert not has_elaboration_guard("// generate if (WIDTH < 5) begin initial $fatal(1); end endgenerate", "WIDTH", 5)
    assert not has_elaboration_guard("always @(*) if (WIDTH < 5) $fatal(1);", "WIDTH", 5)
    assert minimums("WIDTH >= 5") == {"width": 5}
    assert minimums("No requirement that WIDTH >= 5") == {}


def test_json_ranges_are_parameter_scoped_and_preserve_physical_requirements():
    doc = {"parameters": [{"name": "WIDTH", "description": "WIDTH >= 5; hold >= 0"}],
           "integration": "hold >= 0; slack >= 0; parameter DEPTH >= 3",
           "parameter_ranges": [{"name": "DEPTH", "min": 4}]}
    assert minimums(json.dumps(doc)) == {"width": 5, "depth": 4}
    assert doc["integration"].startswith("hold >= 0; slack >= 0")


def test_bare_json_range_uses_the_checked_modules_actual_parameters():
    from parameter_range_contract import rtl_parameter_names
    rtl = ('module core #(parameter WIDTH=5)(); endmodule '
           'module child #(parameter hold=0)(); endmodule')
    names = rtl_parameter_names(rtl, "core")
    assert names == frozenset({"width"})
    text = json.dumps({"description": "WIDTH >= 3; hold >= 0; slack >= 0"})
    assert minimums(text, declared_parameters=names) == {"width": 3}
    assert minimums(text, declared_parameters=rtl_parameter_names(rtl, "missing")) == {}


@pytest.mark.parametrize("guard", [True, False])
def test_physical_prose_does_not_create_rtl_guard_obligations(tmp_path, capsys, guard):
    project = _project(tmp_path, "filter_cell", minimum=5)
    spec, why = synth.extract_serial_parallel_mul_spec(project, "digital_arithmetic_primitive")
    assert spec is not None, why
    rtl = synth.emit_rtl(spec)
    source_dir = project / "phase2/stage1/rtl"
    source_dir.mkdir(parents=True)
    (source_dir / "filter_cell.v").write_text(
        rtl if guard else rtl.replace("initial $fatal", "initial $display"))
    l9 = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    doc = json.loads(l9.read_text())
    doc["integration"] = "Physical STA requires hold >= 0 and slack >= 0."
    l9.write_text(json.dumps(doc))
    rc = conformance.main(["--spec", str(l9), "--rtl-dir", str(source_dir),
                           "--top", "filter_cell"])
    output = capsys.readouterr().out
    assert rc == (0 if guard else 1), output
    assert "hold needs" not in output and "slack needs" not in output
    if not guard:
        assert "parameter-range-guard-missing" in output


def test_unrelated_counter_design_is_checked_without_multiplier_generator(tmp_path, capsys):
    project = tmp_path / "counter_bank"
    docs = project / "phase1/generated_docs"
    rtl_dir = project / "phase2/stage1/rtl"
    docs.mkdir(parents=True)
    rtl_dir.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "counter_bank", "ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "count", "direction": "output", "width": 8}]}))
    (docs / "L3_DETAIL_SPEC.json").write_text(json.dumps({
        "parameter_ranges": [{"name": "DEPTH", "min": 3}]}))
    source = rtl_dir / "counter_bank.sv"
    good = ("module counter_bank #(parameter DEPTH=4) (input wire clk, "
            "output wire [7:0] count); generate if (DEPTH < 3) begin : "
            "g_guard initial $fatal(1, \"DEPTH too small\"); end "
            "endgenerate assign count=0; endmodule")
    source.write_text(good)
    args = ["--spec", str(docs / "L9_INTEGRATION_SPEC.json"),
            "--rtl-dir", str(rtl_dir), "--top", "counter_bank"]
    assert conformance.main(args) == 0
    capsys.readouterr()
    source.write_text(good.replace("generate if (DEPTH < 3) begin : "
                                  "g_guard initial $fatal(1, \"DEPTH too small\"); "
                                  "end endgenerate", ""))
    assert conformance.main(args) == 1
    assert "parameter-range-guard-missing" in capsys.readouterr().out


def test_implicit_generate_guard():
    implicit = ("module guard_top #(parameter WIDTH=5)(); "
                "if (WIDTH < 5) begin : invalid initial $fatal(1, \"too small\"); end "
                "endmodule")
    assert has_elaboration_guard(implicit, "WIDTH", 5)


def test_fatal_must_be_in_invalid_branch_and_checked_top():
    wrong_branch = ("module guard_top #(parameter WIDTH=5)(); "
                    "generate if (WIDTH < 5) begin : invalid end endgenerate "
                    "generate if (WIDTH >= 5) begin : valid "
                    "initial $fatal(1, \"wrong side\"); end endgenerate endmodule")
    assert not has_elaboration_guard(wrong_branch, "WIDTH", 5)
    wrong_module = ("module guard_top #(parameter WIDTH=5)(); endmodule "
                    "module decoy #(parameter WIDTH=5)(); generate "
                    "if (WIDTH < 5) begin : invalid initial $fatal(1); end "
                    "endgenerate endmodule")
    assert not has_elaboration_guard(wrong_module, "WIDTH", 5)
    assert not has_elaboration_guard(wrong_module, "WIDTH", 5, top="guard_top")
    assert has_elaboration_guard(wrong_module, "WIDTH", 5, top="decoy")
    nested_legal = ("module guard_top #(parameter WIDTH=5)(); generate "
                    "if (WIDTH < 5) begin : invalid "
                    "if (WIDTH >= 5) begin : unreachable initial $fatal(1); end "
                    "end endgenerate endmodule")
    assert not has_elaboration_guard(nested_legal, "WIDTH", 5)


def test_conformance_checks_guard_in_selected_top_with_implicit_generate(tmp_path, capsys):
    project = _project(tmp_path, "filter_cell", minimum=5)
    spec, why = synth.extract_serial_parallel_mul_spec(project, "digital_arithmetic_primitive")
    assert spec is not None, why
    rtl = synth.emit_rtl(spec)
    implicit = rtl.replace("generate\n", "").replace("endgenerate\n", "")
    rtl_dir = project / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    source = rtl_dir / "filter_cell.v"
    source.write_text(implicit)
    args = ["--spec", str(project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"),
            "--rtl-dir", str(rtl_dir), "--top", "filter_cell"]
    assert conformance.main(args) == 0
    capsys.readouterr()
    decoy = ("\nmodule decoy #(parameter WIDTH=5)(); generate "
             "if (WIDTH < 5) begin : invalid initial $fatal(1); end "
             "endgenerate endmodule\n")
    missing = implicit.replace("initial $fatal", "initial $display") + decoy
    source.write_text(missing)
    assert conformance.main(args) == 1
    assert "parameter-range-guard-missing" in capsys.readouterr().out


def test_denial_after_a_bound_does_not_create_a_minimum(tmp_path, capsys):
    prose = "WIDTH >= 5 is not required."
    assert minimums(prose) == {}
    project = _project(tmp_path, "free_width", minimum=None)
    spec, why = synth.extract_serial_parallel_mul_spec(project, "digital_arithmetic_primitive")
    assert spec is not None, why
    rtl_dir = project / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "free_width.v").write_text(synth.emit_rtl(spec))
    (project / "phase1/generated_docs/L3_DETAIL_SPEC.json").write_text(
        json.dumps({"description": prose}))
    reread, why = synth.extract_serial_parallel_mul_spec(
        project, "digital_arithmetic_primitive")
    assert reread is not None, why
    assert reread.get("size_min") is None
    args = ["--spec", str(project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"),
            "--rtl-dir", str(rtl_dir), "--top", "free_width"]
    assert conformance.main(args) == 0
    assert "parameter-range-guard-missing" not in capsys.readouterr().out


def test_later_affirmative_minimum_survives_an_earlier_denial(tmp_path, capsys):
    prose = "No requirement that WIDTH >= 5. WIDTH >= 3 is required."
    assert minimums(prose) == {"width": 3}
    project = _project(tmp_path, "bounded_width", minimum=None)
    spec, why = synth.extract_serial_parallel_mul_spec(project, "digital_arithmetic_primitive")
    assert spec is not None, why
    rtl = synth.emit_rtl(spec)
    assert not has_elaboration_guard(rtl, "WIDTH", 3)
    rtl_dir = project / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "bounded_width.v").write_text(rtl)
    (project / "phase1/generated_docs/L3_DETAIL_SPEC.json").write_text(
        json.dumps({"description": prose}))
    reread, why = synth.extract_serial_parallel_mul_spec(
        project, "digital_arithmetic_primitive")
    assert reread is not None, why
    assert reread["size_min"] == 3
    args = ["--spec", str(project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"),
            "--rtl-dir", str(rtl_dir), "--top", "bounded_width"]
    assert conformance.main(args) == 1
    assert "parameter-range-guard-missing" in capsys.readouterr().out


def test_single_item_generate_fatal_guards_only_its_invalid_arm_and_top(tmp_path, capsys):
    project = _project(tmp_path, "single_item_top", minimum=5)
    spec, why = synth.extract_serial_parallel_mul_spec(project, "digital_arithmetic_primitive")
    assert spec is not None, why
    rtl = synth.emit_rtl(spec)
    old = ('    generate if (WIDTH < 5) begin : g_illegal_width\n'
           '        initial $fatal(1, "WIDTH must be >= 5");\n'
           '    end endgenerate\n\n')
    assert old in rtl
    one_item = '    if (WIDTH < 5) initial $fatal(1, "bad width");\n'
    rtl = rtl.replace(old, one_item)
    assert has_elaboration_guard(rtl, "WIDTH", 5, top="single_item_top")
    assert not has_elaboration_guard(rtl, "WIDTH", 5, top="other_top")
    wrong_side = ("module single_item_top #(parameter WIDTH=5)(); "
                  "if (WIDTH >= 5) if (WIDTH < 5) initial $fatal(1); endmodule")
    assert not has_elaboration_guard(wrong_side, "WIDTH", 5, top="single_item_top")
    rtl_dir = project / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "single_item_top.v").write_text(rtl)
    args = ["--spec", str(project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"),
            "--rtl-dir", str(rtl_dir), "--top", "single_item_top"]
    assert conformance.main(args) == 0
    assert "parameter-range-guard-missing" not in capsys.readouterr().out


def test_nested_single_item_false_condition_cannot_guard_invalid_width(tmp_path, capsys):
    project = tmp_path / "counter_bank"
    docs = project / "phase1/generated_docs"
    rtl_dir = project / "phase2/stage1/rtl"
    docs.mkdir(parents=True)
    rtl_dir.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "counter_bank", "ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "count", "direction": "output", "width": 8}]}))
    (docs / "L3_DETAIL_SPEC.json").write_text(json.dumps({
        "parameter_ranges": [{"name": "WIDTH", "min": 5}]}))
    rtl = ("module counter_bank #(parameter WIDTH=5) "
           "(input wire clk, output wire [7:0] count); "
           "generate if (WIDTH < 5) begin : invalid "
           "if (WIDTH >= 5) initial $fatal(1); end endgenerate "
           "assign count=0; endmodule")
    (rtl_dir / "counter_bank.sv").write_text(rtl)
    args = ["--spec", str(docs / "L9_INTEGRATION_SPEC.json"),
            "--rtl-dir", str(rtl_dir), "--top", "counter_bank"]
    assert conformance.main(args) == 1
    assert "parameter-range-guard-missing" in capsys.readouterr().out
    assert has_elaboration_guard(rtl, "WIDTH", 5, top="counter_bank") is False
    valid_nested = rtl.replace("if (WIDTH >= 5)", "if (WIDTH <= 4)")
    (rtl_dir / "counter_bank.sv").write_text(valid_nested)
    assert has_elaboration_guard(valid_nested, "WIDTH", 5, top="counter_bank")
    assert conformance.main(args) == 0
    capsys.readouterr()
    blocked_block = rtl.replace("initial $fatal(1);",
                                "begin : nested initial $fatal(1); end")
    (rtl_dir / "counter_bank.sv").write_text(blocked_block)
    assert has_elaboration_guard(blocked_block, "WIDTH", 5, top="counter_bank") is False
    assert conformance.main(args) == 1
    assert "parameter-range-guard-missing" in capsys.readouterr().out
    valid_block = blocked_block.replace("if (WIDTH >= 5)", "if (WIDTH <= 4)")
    (rtl_dir / "counter_bank.sv").write_text(valid_block)
    assert has_elaboration_guard(valid_block, "WIDTH", 5, top="counter_bank")
    assert conformance.main(args) == 0
