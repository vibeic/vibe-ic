import json
from pathlib import Path

import pytest

import arith_oracle_tb_gen as testbench
import design_one_shot_runner as owner
import serial_parallel_mul_synth as producer


def design_documents(project, *, equation=True, width=True):
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    text = "Serial-parallel multiplier with synchronous active-low reset rst_n."
    if equation:
        text += " result = (parallel_data * serial_data) mod 2^BITS."
    ports = [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst_n", "direction": "input", "width": 1},
        {"name": "parallel_data", "direction": "input", "width": 4 if width else "BITS-1:0",
         "width_symbolic": "BITS-1:0"},
        {"name": "serial_data", "direction": "input", "width": 1, "description": "serial operand"},
        {"name": "result", "direction": "output", "width": 1, "description": "serial result"},
    ]
    (docs / "L2_FRS.json").write_text(json.dumps({"frs_sections": [{"content": text}]}))
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "arithmetic_unit", "top_ports": ports,
        "parameters": [{"name": "BITS", "default": 4}]}))
    return project


def test_native_producer_declares_the_source_function_and_emits_testbench(tmp_path):
    project = design_documents(tmp_path / "native")
    assert producer.main([str(project), "--emit", "--engine", "native"]) == 0
    function, reason = testbench.declared_function(project)
    assert function == {"result": "result", "operands": ["parallel_data", "serial_data"],
                        "operator": "*", "modulus_bits": 4}, reason
    report, code = testbench.generate(project, "digital_arithmetic_primitive")
    assert code == 0, report
    assert report["verdict"] == "TB_EMITTED"
    assert report["width"] == 4


def test_native_owner_does_not_require_a_signed_document_receipt(tmp_path):
    project = design_documents(tmp_path / "native")
    report = project / "reports/orchestrator/phase1_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"verdict": "PASS", "project": str(project)}))
    result = owner.step_rtl_gen(project, "digital_arithmetic_primitive", native_engine=True)
    assert result.status == "PASS", result.detail
    assert result.extras["deterministic_generator"] == "serial_parallel_mul_synth"
    assert (project / "phase2/stage1/rtl/arithmetic_unit.v").is_file()
    assert not (project / "reports/audit/ai_judgements").exists()


def test_native_function_is_not_inferred_from_a_multiplier_label(tmp_path):
    project = design_documents(tmp_path / "ambiguous", equation=False)
    assert producer.main([str(project), "--emit", "--engine", "native"]) == 2
    assert not (project / "declaration.json").exists()
    assert not (project / "phase2/stage1/rtl").exists()


@pytest.mark.parametrize("resolved_width,declared_width,expected", [
    (4, "WORD_WIDTH-bit (`[BITS-1:0]`)", 0),
    (8, "WORD_WIDTH-bit (`[BITS-1:0]`)", 2),
    (None, "WORD_WIDTH-bit (`[BITS-1:0]`)", 2),
    (4, "2*WORD_WIDTH-bit (`[BITS-1:0]`)", 2),
])
def test_equation_width_alias_uses_the_resolved_operand_declaration(
        tmp_path, resolved_width, declared_width, expected):
    project = design_documents(tmp_path / "native")
    docs = project / "phase1/generated_docs"
    source = docs / "L2_FRS.json"
    content = json.loads(source.read_text())
    content["frs_sections"][0]["content"] = content["frs_sections"][0]["content"].replace(
        "2^BITS", "2^WORD_WIDTH").replace(" result =", "\nresult =")
    source.write_text(json.dumps(content))
    interface = docs / "L9_INTEGRATION_SPEC.json"
    data = json.loads(interface.read_text())
    operand = next(port for port in data["top_ports"] if port["name"] == "parallel_data")
    operand["width_resolution"] = {"resolved_width": resolved_width, "width_declared": declared_width}
    interface.write_text(json.dumps(data))
    assert producer.main([str(project), "--emit", "--engine", "native"]) == expected
    if expected == 0:
        function, reason = testbench.declared_function(project)
        assert function["modulus_bits"] == 4, reason


def test_native_producer_does_not_guess_a_missing_operand_width(tmp_path):
    project = design_documents(tmp_path / "ambiguous", width=False)
    assert producer.main([str(project), "--emit", "--engine", "native"]) == 2
    assert not (project / "declaration.json").exists()


def test_legacy_declaration_output_remains_unchanged(tmp_path):
    project = design_documents(tmp_path / "legacy")
    assert producer.main([str(project), "--emit", "--engine", "legacy"]) == 0
    declaration = json.loads((project / "plugin_output/declaration.json").read_text())
    assert "function" not in declaration
    assert not (project / "declaration.json").exists()
