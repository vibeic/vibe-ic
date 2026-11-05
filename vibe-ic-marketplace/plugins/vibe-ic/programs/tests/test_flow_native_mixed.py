from pathlib import Path
import json
import importlib
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flow_native_mixed as mixed
import mixed_signal_m3_run as m3
import mixed_signal_top_lvs_run as lvs
import mixed_signal_power_domain_run as power
import _mixed_signal_native as native
from flow_engine import ToolResult, evaluate



@pytest.fixture(autouse=True)
def current_producer_modules():
    global m3, lvs, power, native
    m3 = importlib.import_module("mixed_signal_m3_run")
    lvs = importlib.import_module("mixed_signal_top_lvs_run")
    power = importlib.import_module("mixed_signal_power_domain_run")
    native = importlib.import_module("_mixed_signal_native")

def invoke(tmp_path, step, **kwargs):
    return mixed.execute(tmp_path, tmp_path / "work", {"native_step": step, "top": "unit"}, None, **kwargs)


def test_interface_audit_is_documentary(tmp_path):
    root = tmp_path / "phase3/analog"
    (root / "block").mkdir(parents=True)
    (root / "analog_block_list.json").write_text('{"blocks":[{"name":"block"}]}')
    (root / "block/interface.json").write_text('{"pins":[{"name":"a","direction":"input","type":"analog","voltage_domain":"1.8V"}]}')
    result = invoke(tmp_path, "M01")
    assert result["ran"] and result["metrics"]["interface_errors"] == 0
    assert "no electrical measurement" in result["detail"]
    assert evaluate(ToolResult(**result), []) == "PASS"


@pytest.mark.parametrize("step", ["M02", "M06", "M08"])
def test_scenarios_keep_native_numbers_and_coverage_gap(tmp_path, monkeypatch, step):
    def produce(project, top, container):
        assert top == "unit" and container == "host"
        for kind, rel in m3.OUTPUTS.items():
            path = project / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"scenarios": [{"id": "s", "metrics": {"voltage": 1.25}}]} if kind == "cosim" else {"blockers": ["noise unavailable"]}))
        return {"verdict": "NOT_MEASURED", "execution": [{"command": ["ngspice"], "exit_code": 0}]}
    monkeypatch.setattr(m3, "produce", produce)
    result = invoke(tmp_path, step)
    assert result["ran"] and result["metrics"]["s.voltage"] == 1.25
    assert "noise unavailable" in result["detail"]
    assert evaluate(ToolResult(**result), []) == "NOT_MEASURED"


@pytest.mark.parametrize("step", ["M03", "M07"])
def test_lvs_reports_real_comparison(tmp_path, monkeypatch, step):
    monkeypatch.setattr(lvs, "resolve_top", lambda p, top: (top, "declared"))
    monkeypatch.setattr(lvs, "resolve_pdk", lambda p, pdk: (pdk, "declared"))
    def run(project, top, container, pdk, **kwargs):
        assert (top, pdk, container) == ("unit", "tech", "host")
        return {"verdict": "FAIL", "compared": True, "lvs_report": "reports/lvs.rpt", "reason": "net mismatch"}
    monkeypatch.setattr(lvs, "run", run)
    result = invoke(tmp_path, step, config={"PDK": "tech"})
    assert result["ran"] and evaluate(ToolResult(**result), []) == "FAIL"


def test_lvs_refusal_is_not_a_comparison(tmp_path, monkeypatch):
    monkeypatch.setattr(lvs, "resolve_top", lambda p, top: (top, "declared"))
    monkeypatch.setattr(lvs, "resolve_pdk", lambda p, pdk: (None, "unknown"))
    monkeypatch.setattr(lvs, "run", lambda *a, **k: {"verdict": "FAIL", "compared": False, "reason": "missing GDS"})
    result = invoke(tmp_path, "M03")
    assert not result["ran"] and "missing GDS" in result["detail"]
    assert evaluate(ToolResult(**result), []) == "NOT_MEASURED"


def test_power_uses_native_structural_producer(tmp_path, monkeypatch):
    monkeypatch.setattr(power, "inputs", lambda p, top: ({"upf": p / "unit.upf", "netlist": p / "unit.v"}, [p / "cells.lib"]))
    monkeypatch.setattr(power, "power_model", lambda *a: None)
    monkeypatch.setattr(power, "library_cells", lambda *a: None)
    def run(script, work, container):
        (work / "netlist.json").write_text('{}')
        (work / "yosys.log").write_text('done')
        return 0
    monkeypatch.setattr(power, "run_tool", run)
    monkeypatch.setattr(power, "derive", lambda *a: {"power_domain.json": {"examined_cells": 7}})
    result = invoke(tmp_path, "M04")
    assert result["ran"] and result["metrics"]["examined_cells"] == 7
    assert evaluate(ToolResult(**result), []) == "PASS"



def test_power_missing_protection_is_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(power, "inputs", lambda p, top: ({"upf": p / "unit.upf", "netlist": p / "unit.v"}, [p / "cells.lib"]))
    monkeypatch.setattr(power, "power_model", lambda *a: None)
    monkeypatch.setattr(power, "library_cells", lambda *a: None)
    def run(script, work, container):
        (work / "netlist.json").write_text('{}')
        return 0
    monkeypatch.setattr(power, "run_tool", run)
    def derive(*args):
        raise power.Refusal("MISSING_ISOLATION_CELL", "unprotected crossing")
    monkeypatch.setattr(power, "derive", derive)
    result = invoke(tmp_path, "M04")
    assert result["ran"] and "MISSING_ISOLATION_CELL" in result["detail"]
    assert evaluate(ToolResult(**result), []) == "FAIL"


def test_substrate_gap_is_explicit(tmp_path):
    result = invoke(tmp_path, "M05")
    assert not result["ran"] and "M05_SUBSTRATE_SUPPLY_MODEL_UNSUPPORTED_OPEN_DEFAULT" in result["detail"]


def test_signoff_reports_missing_native_sources(tmp_path):
    result = invoke(tmp_path, "M09")
    assert not result["ran"]
    for name in ("drc", "lvs", "antenna", "density", "scenarios"):
        assert name + ": native result absent" in result["detail"]
    assert evaluate(ToolResult(**result), []) == "NOT_MEASURED"


def test_signoff_reuses_lvs_and_preserves_state_count_scope(tmp_path):
    path = tmp_path / "steps/complete_top_level_layout_assembly/result.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"status": "PASS", "tool_ran": True,
                                "tool_exit_code": 0, "native_metrics": {}}))
    state = {"metrics": {"magic__drc_error__count": 3}}
    result = invoke(tmp_path, "M09", state=state)
    assert result["ran"] and result["metrics"]["magic__drc_error__count"] == 3
    assert "merged-top DRC was not measured" in result["detail"]
    assert result["native_steps"][0]["reused"]
    assert evaluate(ToolResult(**result), []) == "NOT_MEASURED"


def test_signoff_preserves_failed_merged_lvs(tmp_path):
    path = tmp_path / "steps/complete_top_level_layout_assembly/result.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"status": "FAIL", "tool_ran": True,
                                "tool_exit_code": 1, "native_metrics": {}}))
    result = invoke(tmp_path, "M09")
    assert result["ran"] and evaluate(ToolResult(**result), []) == "FAIL"


def test_native_scenarios_do_not_require_schema_or_unrelated_input_binding(tmp_path, monkeypatch):
    path = tmp_path / "input/mixed_signal/native.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "digital": {"netlist": "input/mixed_signal/design.v", "clock": "clk", "reset_n": "rst",
                    "drive": "drive", "sense": "sense", "response": "response"},
        "analog": {"netlist": "input/mixed_signal/model.sp", "subckt": "receiver", "ports": ["drive", "sense"],
                   "drive_low_v": 0, "drive_high_v": 1.2, "drive_transition_ns": 0.1,
                   "adc_low_v": 0.95, "adc_high_v": 1.1}}))
    (path.parent / "design.v").write_text("module unit(input clk,rst,sense,output drive,response); endmodule\n")
    (path.parent / "model.sp").write_text(".subckt receiver drive sense\nR1 drive sense 1k\n.ends receiver\n")
    rows = [{"id": "s", "native": {"clock_period_ns": 10, "tran_step_ns": 1,
                "measure_from_ns": 1, "cycles": 3},
             "criteria": [{"native_metric": "settled_voltage_min_v", "min": 1.0}]}]
    monkeypatch.setattr(m3, "plan", lambda project: rows)
    def forbidden(*args):
        raise AssertionError("unrelated hash census was requested")
    monkeypatch.setattr(m3, "inputs", forbidden)
    calls = []
    class Engine:
        def __init__(self, *args):
            self.execution, self.versions = [], {}
        def version(self, *args):
            pass
        def run(self, command, log, stage, cwd=None):
            calls.append(command[0])
            work = log.parent
            if command[0] == "vvp":
                tb = work / ("drive_tb.v" if "drive.vvp" in command[1] else "response_tb.v")
                token = re.search(r"M3RUN ([a-f0-9]+)", tb.read_text()).group(1)
                observations = (f"M3RUN {token}\n" + "".join(
                    f"M3OBS k={k} t={5 + 10*k}.000 drive=0 sense=0 response=0\n" for k in range(3))
                    + f"M3DONE {token}\n")
                log.write_text(observations)
            elif command[0] == "/usr/bin/time":
                (work / "wave.txt").write_text("0 0.9\n1e-8 0.9\n2e-8 0.9\n3e-8 0.9\n")
                (work / "ngspice.rss").write_text("1000\n")
            self.execution.append({"command": command, "exit_code": 0, "stage": stage})
    monkeypatch.setattr(native, "Engine", Engine)
    monkeypatch.setattr(native, "interface_si", lambda *args: {"verdict": "NOT_MEASURED", "blockers": ["noise absent"]})
    result = invoke(tmp_path, "M02")
    assert calls == ["iverilog", "vvp", "/usr/bin/time", "iverilog", "vvp"]
    assert result["ran"] and result["metrics"]["s.settled_voltage_min_v"] == 0.9
    assert result["metrics"]["s.settled_voltage_min_v.min"] == 1.0
    assert evaluate(ToolResult(**result), []) == "FAIL"
    assert not (tmp_path / m3.RECEIPT).exists()


def test_signoff_reads_worker_output_before_result_publication(tmp_path):
    path = tmp_path / "steps/complete_top_level_layout_assembly/native_1/mixed_results.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"step": "M07", "result": {"ran": True, "exit_code": 1,
        "metrics": {}, "detail": "LVS mismatch", "native_steps": [{"status": "FAIL"}]}}))
    result = invoke(tmp_path, "M09")
    assert result["ran"] and str(path) in result["reports"]
    assert evaluate(ToolResult(**result), []) == "FAIL"


def test_native_contract_preserves_declared_top(tmp_path):
    path = tmp_path / "input/mixed_signal/native.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"top": "wrapper", "scope": "declared_model_component"}))
    assert native.contract(tmp_path, "different_top")["top"] == "wrapper"
