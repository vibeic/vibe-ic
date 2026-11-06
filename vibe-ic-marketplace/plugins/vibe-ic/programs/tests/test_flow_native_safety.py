"""Native diagnostic injection uses engineering inputs and actual simulator results."""
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

import _fmeda_mechanisms as mechanisms
import fmeda_fault_injection_coverage as producer
import fmeda_coverage_check as reader
import flow_engine as engine
import flow_native_adapters as adapters


native = pytest.mark.skipif(not all(shutil.which(name) for name in ("yosys", "iverilog", "vvp")),
                            reason="Native Yosys and Icarus required")


def subject(project, detector="^code_i", legacy=False):
    rtl = project / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    source = rtl / "component.sv"
    source.write_text(f"""module encode(input [3:0] data_i, output [4:0] code_o);
assign code_o={{^data_i,data_i}}; endmodule
module decode(input [4:0] code_i, output err_o);
assign err_o={detector}; endmodule
module component(input [3:0] data_i, input [4:0] code_i,
                 output [4:0] code_o, output err_o);
encode encoder(.data_i(data_i),.code_o(code_o));
decode check_unit(.code_i(code_i),.err_o(err_o)); endmodule
""")
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "component"}))
    doc = {"top_module": "component", "rtl_files": ["phase2/stage1/rtl/component.sv"],
        "mechanisms": [{"id": "parity", "kind": "parity", "data_width": 4, "code_width": 5,
            "encoder": {"module": "encode", "instance": "component.encoder",
                        "input": "data_i", "output": "code_o"},
            "checker": {"module": "decode", "instance": "component.check_unit", "input": "code_i",
                        "detect": "err_o", "corrected_output": None}}]}
    if legacy:
        doc.update(schema="vibeic.fmeda-mechanisms.v1", authority="AUTHOR_ENGINEERING_DECLARATION",
                   rtl_files=[{"path": "phase2/stage1/rtl/component.sv",
                               "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}])
    (project / mechanisms.MANIFEST).write_text(json.dumps(doc))
    return doc


def options():
    return SimpleNamespace(asil="D", min_dc=None, max_vectors=64, timeout=300)


@native
def test_native_injection_needs_no_identity_receipts(tmp_path):
    subject(tmp_path)
    code, report = producer.run(tmp_path, options())
    assert code == 0, report
    row = report["mechanisms"][0]
    assert (row["injected_faults"], row["detected_faults"], row["diagnostic_coverage_pct"]) == (80, 80, 100.0)
    assert row["baseline_valid"] and row["baseline_golden_count"] == 16
    assert report["dc_floor_pct"] == 99.0
    assert "input_binding" not in report
    assert "sha256" not in row["raw_evidence"]


@pytest.mark.parametrize("detector,baseline", [("1'b0", True), ("1'b1", False)])
@native
def test_native_fault_escape_and_false_alarm_still_fail(tmp_path, detector, baseline):
    subject(tmp_path, detector)
    code, report = producer.run(tmp_path, options())
    assert code == 1, report
    row = report["mechanisms"][0]
    assert row["injected_faults"] == 80
    assert row["baseline_valid"] is baseline
    assert report["verdict"] == "FAIL"
    if baseline:
        assert row["detected_faults"] == 0 and row["diagnostic_coverage_pct"] == 0


@native
def test_native_reader_needs_no_project_or_receipt(tmp_path):
    subject(tmp_path, legacy=True)
    code, report = producer.run(tmp_path, options())
    assert code == 0, report
    report.pop("input_binding", None)
    report.pop("native_hierarchy", None)
    report.pop("schema", None)
    result = reader.check(report, "D", None)
    assert result["verdict"] == "PASS", result


@native
def test_native_safety_row_reports_only_measured_quantities(tmp_path):
    subject(tmp_path)
    row = next(row for row in engine.read_json(engine.TABLE)["steps"]
               if row["name"] == "safety_fault_injection_and_diagnostic_coverage")
    result = adapters.execute(tmp_path, tmp_path / "output", row["tool"], {})
    assert result["ran"] and result["exit_code"] == 0, result
    assert result["metrics"]["injected_faults"] == 80
    assert result["metrics"]["diagnostic_coverage_pct"] == 100.0
    assert "fault_population_coverage" not in result["metrics"]
    assert "diagnostic_coverage_latency" not in result["metrics"]
    checks = engine.measure(row["checks"], result["metrics"], {},
                            {"requires_functional_safety": True}, tmp_path)
    assert engine.evaluate(engine.ToolResult(**result), checks) == "NOT_MEASURED"


def test_missing_native_tool_is_unmeasured(tmp_path, monkeypatch):
    subject(tmp_path)
    original = mechanisms.shutil.which
    monkeypatch.setattr(mechanisms.shutil, "which", lambda name, *args, **kwargs:
                        None if name == "yosys" else original(name, *args, **kwargs))
    code, report = producer.run(tmp_path, options())
    assert code == 2 and report["verdict"] == "NOT_MEASURED", report
    assert report["measured"] is False
