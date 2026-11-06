"""Native adopted-netlist CDC/RDC and SDC exception controls."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import pytest
import _cdc_netlist as native
import flow109_netlist_cdc as d45

pytestmark = pytest.mark.skipif(shutil.which("yosys") is None, reason="native yosys absent")

def _put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return name

def _case(project, *, inconsistent=False, multi_domain=False):
    source = """
module neutral(input clk, input rst_n, input d, output reg q);
always @(posedge clk or negedge rst_n)
  if (!rst_n) q <= 1'b0; else q <= d;
endmodule
"""
    if multi_domain:
        source = """
module neutral(input clk_a, input clk_b, input rst_n, input da, input db,
               output reg qa, output reg qb);
always @(posedge clk_a or negedge rst_n) if (!rst_n) qa <= 1'b0; else qa <= da;
always @(posedge clk_b or negedge rst_n) if (!rst_n) qb <= 1'b0; else qb <= db;
endmodule
"""
    netlist = _put(project, "adopted/current.v", source)
    liberty = _put(project, "adopted/current.lib", "library(neutral) {}\n")
    sdc = ("create_clock -name clk_a -period 10 [get_ports clk_a]\n"
           "create_clock -name clk_b -period 12 [get_ports clk_b]\n" if multi_domain else
           "create_clock -name clk -period 10 [get_ports clk]\n")
    if inconsistent:
        sdc += "set_false_path -from [get_clocks clk] -to [get_clocks missing_domain]\n"
    sdc = _put(project, "phase3/current.sdc", sdc)
    intent = _put(project, "phase1/generated_docs/L8_TIMING_WAVEFORM.json", {
        "clock_domains": [{"name": "clk", "period_ns": 10}], "reset": "rst_n"})
    return {"top": "neutral", "netlist": netlist, "liberties": [liberty],
            "sdc": [sdc], "intent": intent}


def test_single_domain_without_crossings_runs_consumers_as_bounded_component(tmp_path):
    context = _case(tmp_path)
    result = d45.execute(tmp_path, context)
    assert result["native_started"] is True
    assert result["component_status"] == "PASS"
    assert result["reason"] is None
    assert result["checks"]["implemented_crossing_census"]["status"] == "PASS"
    assert result["checks"]["new_unexplained_crossings"]["status"] == "PASS"
    assert result["checks"]["reset_dependency"]["status"] == "PASS"
    assert result["checks"]["exception_reconciliation"]["status"] == "PASS"
    assert result["checks"]["protocol_semantics"]["status"] == "PASS"
    assert result["metrics"]["decoded_flop_count"] == 1
    assert result["metrics"]["decoded_async_reset_flop_count"] == 1
    assert result["metrics"]["decoded_sync_reset_flop_count"] == 0
    assert result["consumers"]["cdc_crossing_check"]["passed"] is True
    assert result["consumers"]["sdc_exception_correlation_check"]["verdict"] == "PASS"

def test_unjustified_current_sdc_exception_is_a_real_refusal(tmp_path):
    context = _case(tmp_path, inconsistent=True)
    result = d45.execute(tmp_path, context)
    assert result["native_started"] is True
    assert result["component_status"] == "FAIL"
    assert result["reason"] == "D45_EXCEPTION_INCONSISTENT"
    check = result["checks"]["exception_reconciliation"]
    assert check["status"] == "FAIL"
    assert "SDC_EXCEPTION_UNJUSTIFIED" in check["categories"]

def test_two_clock_no_crossing_keeps_protocol_semantics_not_measured(tmp_path):
    context = _case(tmp_path, multi_domain=True)
    result = d45.execute(tmp_path, context)
    assert result["native_started"] is True
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D45_PROTOCOL_SEMANTICS_UNSUPPORTED"
    assert result["checks"]["protocol_semantics"]["status"] == "NOT_MEASURED"

def test_current_native_failure_remains_failed_default_row(tmp_path):
    context = _case(tmp_path, inconsistent=True)
    component = d45.execute(tmp_path, context)
    assert component["component_status"] == "FAIL"
    assert component["reason"] == "D45_EXCEPTION_INCONSISTENT"


def test_preparation_refusal_keeps_its_reason_at_completion(tmp_path):
    context = _case(tmp_path)
    (tmp_path / context["netlist"]).unlink()
    component = d45.execute(tmp_path, context)
    assert component["native_started"] is False
    assert component["component_status"] == "NOT_MEASURED"
    assert component["reason"] == "D45_NATIVE_UNAVAILABLE_OR_UNSUPPORTED"


def test_changed_adopted_netlist_refuses_before_native_launch(tmp_path):
    context = _case(tmp_path)
    (tmp_path / "adopted/current.v").write_text("module changed; endmodule\n")
    result = d45.execute(tmp_path, context)
    assert result["native_started"] is True
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D45_NATIVE_MODEL_FAILED"


def test_partial_declared_library_closure_refuses_before_native_launch(tmp_path):
    context = _case(tmp_path)
    context["liberties"].append("adopted/io.lib")
    result = d45.execute(tmp_path, context)
    assert result["native_started"] is False
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D45_NATIVE_UNAVAILABLE_OR_UNSUPPORTED"


def test_yosys_internal_async_dff_is_not_mislabeled_as_zero_flops(tmp_path):
    model = {"modules": {"neutral": {"attributes": {"top": 1},
        "ports": {"clk": {"direction": "input", "bits": [2]},
                  "rst": {"direction": "input", "bits": [3]},
                  "d": {"direction": "input", "bits": [4]},
                  "q": {"direction": "output", "bits": [5]}},
        "netnames": {}, "cells": {"ff": {"type": "$_DFF_PP0_",
            "port_directions": {"C": "input", "D": "input", "Q": "output", "R": "input"},
            "connections": {"C": [2], "D": [4], "Q": [5], "R": [3]},
            "parameters": {}, "attributes": {}}}}}}
    path = tmp_path / "mapped.json"
    path.write_text(json.dumps(model))
    netlist = native.load(path, "neutral")
    observed_types = (netlist.cells["ff"]["type"], tuple(f.type for f in netlist.flops))
    assert observed_types == ("$_DFF_PP0_", ("$_DFF_PP0_",))
    assert native.clock_domains(netlist) == ["clk"]
    assert netlist.flops[0].arst == 3 and netlist.flops[0].arst_value == ["0"]

def test_yosys_internal_simple_dff_is_decoded_with_clock_and_reset_mux(tmp_path):
    model = {"modules": {"neutral": {"attributes": {"top": 1},
        "ports": {"clk": {"direction": "input", "bits": [2]},
                  "rst": {"direction": "input", "bits": [3]},
                  "d": {"direction": "input", "bits": [4]},
                  "q": {"direction": "output", "bits": [5]}},
        "netnames": {"reset_mux": {"bits": [6]}},
        "cells": {
            "mux": {"type": "$mux", "port_directions": {"A": "input", "B": "input", "S": "input", "Y": "output"},
                "connections": {"A": [4], "B": ["0"], "S": [3], "Y": [6]}, "parameters": {}, "attributes": {}},
            "ff": {"type": "$_DFF_P_", "port_directions": {"C": "input", "D": "input", "Q": "output"},
                "connections": {"C": [2], "D": [6], "Q": [5]}, "parameters": {}, "attributes": {}}}}}}
    path = tmp_path / "mapped.json"
    path.write_text(json.dumps(model))
    netlist = native.load(path, "neutral")
    assert native.clock_domains(netlist) == ["clk"]
    assert len(netlist.flops) == 1
    assert netlist.flops[0].type == "$_DFF_P_"
    assert netlist.flops[0].srst == 3
