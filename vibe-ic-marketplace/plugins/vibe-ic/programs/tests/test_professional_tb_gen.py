"""Tests for professional_tb_gen — deterministic pro-TB generation from L-docs.

Pure/structural tests (no container/sim). The full cocotb run (208/208 on the
spm bit-serial multiplier) is exercised in the commercial-PDK/clean-run integration.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import professional_tb_gen as T  # noqa: E402


def _mk_spm_project(tmp: Path) -> Path:
    """A minimal project: L9 interface (x parametric bus, y/p serial, clk/rst)
    + L2 prose (multiplier) + a parametric RTL (parameter size = 32)."""
    gd = tmp / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": {
        "top_module": "spm",
        "top_ports": [
            {"name": "clk", "dir": "input", "width": 1},
            {"name": "rst", "dir": "input", "width": 1},
            {"name": "x", "dir": "input"},           # parametric width (no number)
            {"name": "y", "dir": "input", "width": 1},
            {"name": "p", "dir": "output", "width": 1}],
        "clocks": [{"name": "clk", "edge": "posedge", "period_ns": 10}],
        "reset_domains": [{"name": "rst", "polarity": "active_high",
                           "sync": "sync"}],
    }}))
    (gd / "L2_FRS.json").write_text(json.dumps({"frs_sections": [
        {"title": "Function", "content": "serial-parallel multiplier "
         "p = (x * y) mod 2^N"}]}))
    # Use the filename Phase 1 ACTUALLY writes. This fixture previously wrote
    # `L16_COMPLIANCE.json`, a name that exists in ZERO real runs — so the test
    # passed while the production read path was dead in every real run. A
    # fixture that invents the file the code happens to open cannot fail.
    (gd / "L16_COMPLIANCE_PROPERTIES.json").write_text(json.dumps({
        "properties": [
            {"english_form": "x must not change during a multiply",
             "anchor_token": "must"}]}))
    rtl = tmp / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "spm.v").write_text(
        "module spm #(parameter size = 32)("
        "input clk, input rst, input [size-1:0] x, input y, output p);\n"
        "endmodule\n")
    return tmp


def test_classify_serial_stream(tmp_path):
    proj = _mk_spm_project(tmp_path)
    shape, why = T.classify_dut(proj, "digital_arithmetic_primitive")
    assert shape is not None, why
    assert shape["kind"] == "serial_stream"
    assert shape["x_port"] == "x" and shape["y_port"] == "y"
    assert shape["p_port"] == "p"
    assert shape["operator"] == "*"


def test_width_resolves_from_rtl_param(tmp_path):
    proj = _mk_spm_project(tmp_path)
    _, ports = T._aog._load_top_ports(proj)
    assert T._resolve_tb_width(proj, ports) == 32   # DUT compiled at size=32


def test_generate_emits_streaming_tb(tmp_path):
    proj = _mk_spm_project(tmp_path)
    res = T.generate(proj)
    assert res["status"] == "PASS"
    assert res["dut_kind"] == "serial_stream"
    assert res["reference_model_tier"] == "streaming_bounded_latency"
    out = Path(res["out_dir"])
    tb = (out / "tb_spm.py").read_text()
    # the streaming scoreboard + coverage + reference are present
    assert "streaming scoreboard locked" in tb
    assert "def _ref(xv, yv)" in tb and "(xv * yv)" in tb
    assert "MAX_LATENCY" in tb and "professional_stream_test" in tb
    assert "N = 32" in tb
    # coverage model + assertions + makefile + vplan emitted
    cov = json.loads((out / "spm_coverage_model.json").read_text())
    assert cov["fields"]["covergroups"][0]["coverpoints"]
    sva = (out / "spm_assertions.sva").read_text()
    assert "assert property" in sva and "isunknown" in sva
    assert (out / "Makefile").is_file()
    assert (out / "verification_plan.json").is_file()


def test_reset_initialises_all_data_inputs_before_asserting(tmp_path):
    # REGRESSION (spm serial-multiplier fail): the generated _reset() MUST drive
    # every data input to a known 0 BEFORE asserting reset, so no X propagates
    # into the datapath / streaming scoreboard during power-up. Without this the
    # bounded-latency + bit-order calibrator locked a WRONG (order, latency) and
    # produced 203/208 false mismatches on functionally-correct RTL; with it the
    # SAME RTL scores 208/208. chip-AGNOSTIC: inputs derived from the interface.
    proj = _mk_spm_project(tmp_path)
    res = T.generate(proj)
    tb = (Path(res["out_dir"]) / "tb_spm.py").read_text()
    # the data inputs are enumerated (x, y) and clk/rst are NOT reset-driven
    assert "DUT_INPUTS = [" in tb
    dut_inputs_line = next(l for l in tb.splitlines()
                           if l.startswith("DUT_INPUTS ="))
    assert "'x'" in dut_inputs_line and "'y'" in dut_inputs_line
    assert "'clk'" not in dut_inputs_line and "'rst'" not in dut_inputs_line
    # ordering: the input-zeroing loop appears BEFORE reset is asserted
    body = tb.split("async def _reset(dut):", 1)[1]
    zero_at = body.index("for _sig in DUT_INPUTS")
    assert_at = body.index("getattr(dut, RST).value = 1")
    assert zero_at < assert_at, "inputs must be zeroed before reset is asserted"
    assert ".value = 0" in body[zero_at:assert_at]


def test_reset_zeroes_inputs_for_parallel_arith(tmp_path):
    # chip-AGNOSTIC: the same input-zeroing must appear for a parallel-arith DUT
    # (different emit path, same _emit_common_header) — the operand ports a/b are
    # enumerated in DUT_INPUTS, clk/rst are not.
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": {
        "top_module": "adder",
        "top_ports": [{"name": "clk", "dir": "input", "width": 1},
                      {"name": "rst", "dir": "input", "width": 1},
                      {"name": "a", "dir": "input", "width": 8},
                      {"name": "b", "dir": "input", "width": 8},
                      {"name": "sum", "dir": "output", "width": 8}],
        "clocks": [{"name": "clk", "edge": "posedge", "period_ns": 10}],
        "reset_domains": [{"name": "rst", "polarity": "active_high"}]}}))
    (gd / "L2_FRS.json").write_text(json.dumps({"frs_sections": [
        {"title": "Function", "content": "sum = a + b"}]}))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "adder.v").write_text(
        "module adder(input clk, rst, input [7:0] a, b, output [7:0] sum);"
        "endmodule\n")
    res = T.generate(tmp_path)
    tb = (Path(res["out_dir"]) / "tb_adder.py").read_text()
    dut_inputs_line = next(l for l in tb.splitlines()
                           if l.startswith("DUT_INPUTS ="))
    assert "'a'" in dut_inputs_line and "'b'" in dut_inputs_line
    assert "'clk'" not in dut_inputs_line and "'rst'" not in dut_inputs_line
    body = tb.split("async def _reset(dut):", 1)[1]
    assert body.index("for _sig in DUT_INPUTS") < body.index(
        "getattr(dut, RST).value = 1")


def test_coverage_model_has_bins_and_cross(tmp_path):
    proj = _mk_spm_project(tmp_path)
    shape, _ = T.classify_dut(proj, "digital_arithmetic_primitive")
    cov = T.build_coverage_model(shape)
    cps = cov["fields"]["covergroups"][0]["coverpoints"]
    assert len(cps) >= 2
    names = {b["name"] for b in cps[0]["bins"]}
    assert {"zero", "one", "max"} <= names
    assert cov["fields"]["covergroups"][0]["crosses"]


def test_generic_class_emits_nonvacuous_hook(tmp_path):
    # A DUT with no closed-form ref + no serial shape -> generic hook that
    # SKIPs (never a vacuous pass).
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": {
        "top_module": "widget",
        "top_ports": [{"name": "clk", "dir": "input", "width": 1},
                      {"name": "rst", "dir": "input", "width": 1},
                      {"name": "ctrl", "dir": "input", "width": 4},
                      {"name": "status", "dir": "output", "width": 4}],
        "clocks": [{"name": "clk", "edge": "posedge", "period_ns": 10}],
        "reset_domains": [{"name": "rst", "polarity": "active_high"}]}}))
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "widget.v").write_text(
        "module widget(input clk, rst, input [3:0] ctrl, output [3:0] status);"
        "endmodule\n")
    res = T.generate(tmp_path)
    assert res["dut_kind"] == "generic"
    tb = (Path(res["out_dir"]) / "tb_widget.py").read_text()
    assert "TestSkip" in tb and "unfilled" in tb   # never a vacuous PASS
