"""Run the generated clockless hook and persistent references under real Cocotb."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

import pytest


PROGRAMS = Path(os.environ.get(
    "VIBEIC_PROFESSIONAL_TB_SUBJECT", str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
SPEC = importlib.util.spec_from_file_location(
    "professional_clock_subject", PROGRAMS / "professional_tb_gen.py")
PTB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PTB)


def _project(root, kind, *, wrong=False, missing=False):
    docs = root / "phase1/generated_docs"
    docs.mkdir(parents=True)
    ports = [{"name": "sample", "dir": "input", "width": 3},
             {"name": "result", "dir": "output", "width": 3}]
    body = "assign result = " + ("~sample;" if wrong else "sample;")
    header = "input [2:0] sample, output [2:0] result"
    if kind == "mux":
        ports += [{"name": "choose", "dir": "input", "width": 1},
                  {"name": "alternate", "dir": "input", "width": 3}]
        header += ", input choose, input [2:0] alternate"
        body = "assign result = " + (
            "choose ? sample : alternate;" if wrong else
            "choose ? alternate : sample;")
    l9 = {"top_module": "neutral_unit", "top_ports": ports}
    if kind == "clocked":
        ports += [{"name": "ck_tick", "dir": "input", "width": 1},
                  {"name": "reset_n", "dir": "input", "width": 1}]
        l9.update({"clock_domains": [{"name": "ck_tick", "source_pin": "ck_tick"}],
                   "reset_domains": [{"name": "reset_n", "polarity": "active_low",
                                      "sync": "async"}]})
        (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
            "clocks": [{"name": "ck_tick", "period_ns": 14}]}))
        header = "input [2:0] sample, input ck_tick, reset_n, output reg [2:0] result"
        body = ("always @(posedge ck_tick or negedge reset_n) "
                "if (!reset_n) result <= 0; else result <= " +
                ("~sample;" if wrong else "sample;"))
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    rtl = root / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    if missing:
        header = header.replace(missing, "different_input")
        body = body.replace(missing, "different_input")
    (rtl / "neutral_unit.sv").write_text(
        "`timescale 1ns/1ps\nmodule neutral_unit(" + header + ");\n" + body + "\nendmodule\n")
    return root


def _fill_reference(project, kind):
    result = PTB.generate(project)
    out = Path(result["out_dir"])
    shape, _ = PTB.classify_dut(project, "generic")
    # Copy the producer's actual-port clock/reset support into the persistent
    # expert file. The reference below follows this fixture's public contract.
    header = PTB._emit_common_header(shape)
    if kind == "mux":
        body = """
    comparisons = 0
    for choose in range(2):
        for sample in range(8):
            for alternate in range(8):
                dut.choose.value = choose
                dut.sample.value = sample
                dut.alternate.value = alternate
                await Timer(1, units="ns")
                assert int(dut.result.value) == (alternate if choose else sample)
                comparisons += 1
    assert comparisons == 128
"""
    elif kind == "clocked":
        body = """
    assert CLK == "ck_tick" and RST == "reset_n" and HALF_NS == 7
    assert int(dut.result.value) == 0
    for sample in range(8):
        await FallingEdge(dut.ck_tick)
        dut.sample.value = sample
        await RisingEdge(dut.ck_tick)
        await ReadOnly()
        assert int(dut.result.value) == sample
"""
    else:
        body = """
    for sample in range(8):
        dut.sample.value = sample
        await Timer(1, units="ns")
        assert int(dut.result.value) == sample
"""
    (out / "expert_reference_tb.py").write_text(header + '''
@cocotb.test()
async def public_contract_reference(dut):
    _start_clock(dut)
    await _reset(dut)
''' + body + '''
    dut._log.info("PROFESSIONAL_TB PASS")
''')


def _native_run(project, monkeypatch):
    if not all(shutil.which(t) for t in ("iverilog", "cocotb-config", "make")):
        pytest.skip("native Icarus/Cocotb tools unavailable")
    monkeypatch.setitem(sys.modules, "professional_tb_gen", PTB)
    import design_one_shot_runner as runner
    import professional_tb_check as consumer
    step = runner.step_professional_tb_gen(project, "neutral_unit", "neutral-unused")
    report = json.loads((project / "reports/phase2/gates/professional_tb.json").read_text())
    checked = consumer.check(project)
    (project / "native-values.json").write_text(json.dumps({
        "step_status": step.status, "report": report, "consumer": checked}, indent=2))
    log = (Path(report["out_dir"]) / "cocotb_run.log").read_text()
    return step, report, checked, log


@pytest.mark.parametrize("kind", ["buffer", "mux", "clocked"])
def test_native_unfilled_hook_is_skipped_and_unmeasured(tmp_path, monkeypatch, kind):
    project = _project(tmp_path, kind)
    step, report, checked, log = _native_run(project, monkeypatch)
    assert step.status == "NOT_MEASURED", (step, log)
    assert report["ran_cocotb"] is True
    assert report["functional_mismatch"] is False
    denominator = report["cocotb_test_denominator"]
    assert (denominator["tests"], denominator["skipped"], denominator["passed"],
            denominator["failures"], denominator["errors"]) == (1, 1, 0, 0, 0)
    assert "reference_model hook unfilled" in log
    assert report["status"] == checked["status"] == "INCOMPLETE"


@pytest.mark.parametrize("kind", ["buffer", "mux", "clocked"])
@pytest.mark.parametrize("wrong", [False, True])
def test_native_filled_reference_measures_good_and_bad_logic(tmp_path, monkeypatch, kind, wrong):
    project = _project(tmp_path, kind, wrong=wrong)
    _fill_reference(project, kind)
    step, report, checked, log = _native_run(project, monkeypatch)
    assert report["reference_model_tier"] == "expert_filled"
    assert report["ran_cocotb"] is True
    assert report["cocotb_test_denominator"]["tests"] == 1
    assert report["cocotb_test_denominator"]["skipped"] == 0
    assert (step.status, checked["verdict"], report["functional_mismatch"]) == (
        ("FAIL", "FAIL", True) if wrong else ("PASS", "PASS", False)), log
    assert (report["cocotb_test_denominator"]["failures"] == 1) is wrong
    if wrong:
        assert "AssertionError" in log, log
        assert "AttributeError" not in log, log


@pytest.mark.parametrize("kind,missing,filled", [
    ("buffer", "sample", True), ("clocked", "sample", True),
    ("clocked", "ck_tick", True), ("clocked", "ck_tick", False)])
def test_native_missing_public_port_still_fails(tmp_path, monkeypatch, kind, missing, filled):
    project = _project(tmp_path, kind, missing=missing)
    if filled:
        _fill_reference(project, kind)
    step, report, checked, log = _native_run(project, monkeypatch)
    assert (step.status, checked["verdict"]) == ("FAIL", "FAIL")
    assert report["cocotb_test_denominator"]["failures"] == 1
    assert f"contains no child object named {missing}" in log
