"""D45 adopted-netlist CDC/RDC row-local dispatch controls."""
from __future__ import annotations

import hashlib
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
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _context():
    registry = json.loads((Path(d45.__file__).parent.parent / "flow/flow109.json").read_text())
    row = next(item for item in registry["rows"] if item["id"] == "D45")
    return {"requested_step": "D45", "native_step_id": "flow109.D45",
            "context_sha256": "d" * 64,
            "resolved_row": {"id": "D45", "profile": row["profiles"][0]}}


def _case(project, *, inconsistent=False):
    netlist = _put(project, "adopted/current.v", """
module neutral(input clk, input rst_n, input d, output reg q);
always @(posedge clk or negedge rst_n)
  if (!rst_n) q <= 1'b0; else q <= d;
endmodule
""")
    liberty = _put(project, "adopted/current.lib", "library(neutral) {}\n")
    sdc = "create_clock -name clk -period 10 [get_ports clk]\n"
    if inconsistent:
        sdc += "set_false_path -from [get_clocks clk] -to [get_clocks missing_domain]\n"
    sdc = _put(project, "phase3/current.sdc", sdc)
    intent = _put(project, "phase1/generated_docs/L8_TIMING_WAVEFORM.json", {
        "clock_domains": [{"name": "clk", "period_ns": 10}], "reset": "rst_n"})
    _put(project, d45.INPUT, {"schema": d45.SCHEMA, "top": "neutral",
        "adopted_netlist": netlist, "liberty": liberty, "sdc": [sdc],
        "clock_reset_intent": intent})


def test_current_adopted_netlist_runs_existing_consumers_without_protocol_pass(tmp_path):
    _case(tmp_path)
    result = d45.execute(tmp_path, _context())
    assert result["native_started"] is True
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D45_PROTOCOL_SEMANTICS_UNSUPPORTED"
    assert result["checks"]["implemented_crossing_census"]["status"] == "PASS"
    assert result["checks"]["new_unexplained_crossings"]["status"] == "PASS"
    assert result["checks"]["reset_dependency"]["status"] == "PASS"
    assert result["checks"]["exception_reconciliation"]["status"] == "PASS"
    assert result["checks"]["protocol_semantics"]["status"] == "NOT_MEASURED"
    assert result["consumers"]["cdc_crossing_check"]["passed"] is True
    assert result["consumers"]["sdc_exception_correlation_check"]["verdict"] == "PASS"


def test_unjustified_current_sdc_exception_is_a_real_refusal(tmp_path):
    _case(tmp_path, inconsistent=True)
    result = d45.execute(tmp_path, _context())
    assert result["native_started"] is True
    assert result["component_status"] == "FAIL"
    assert result["reason"] == "D45_EXCEPTION_INCONSISTENT"
    check = result["checks"]["exception_reconciliation"]
    assert check["status"] == "FAIL"
    assert "SDC_EXCEPTION_UNJUSTIFIED" in check["categories"]


def test_changed_adopted_netlist_refuses_before_native_launch(tmp_path):
    _case(tmp_path)
    (tmp_path / "adopted/current.v").write_text("module changed; endmodule\n")
    result = d45.execute(tmp_path, _context())
    assert result["native_started"] is False
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D45_INPUT_STALE_OR_MISSING"


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


def test_registry_selects_only_the_d45_row_local_adapter():
    registry = json.loads((Path(d45.__file__).parent.parent / "flow/flow109.json").read_text())
    row = next(item for item in registry["rows"] if item["id"] == "D45")
    profile = row["profiles"][0]
    assert profile["dispatch"]["adapter"] == "flow109_netlist_cdc"
    assert profile["dispatch"]["native_step_id"] == "flow109.D45"
    assert profile["dispatch"]["engine_families"] == ["python3", "yosys"]
