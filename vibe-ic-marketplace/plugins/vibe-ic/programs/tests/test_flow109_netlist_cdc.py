"""D45 adopted-netlist CDC/RDC row-local dispatch controls."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import _cdc_netlist as native
import flow109
import flow109_admission as admission
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
    row["profile"] = row["profiles"][0]
    return {"requested_step": "D45", "native_step_id": "flow109.D45",
            "context_sha256": "d" * 64,
            "resolved_row": row}


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
    image = "source-owned-developer-control"
    config = _put(project, "adopted/sta-config.json", {
        "DEFAULT_CORNER": "control_tt", "CELL_LIBS": {"control_*": ["/pdk/current.lib"]},
        "PAD_LIBS": None, "EXTRA_LIBS": None, "MACROS": None})
    receipt = _put(project, "adopted/sta-receipt.json", {"input": {"image": image,
        "config_files": {"/pdk/current.lib": liberty["sha256"]}},
        "sha256": {"config.json": config["sha256"]}})
    sdc = ("create_clock -name clk_a -period 10 [get_ports clk_a]\n"
           "create_clock -name clk_b -period 12 [get_ports clk_b]\n" if multi_domain else
           "create_clock -name clk -period 10 [get_ports clk]\n")
    if inconsistent:
        sdc += "set_false_path -from [get_clocks clk] -to [get_clocks missing_domain]\n"
    sdc = _put(project, "phase3/current.sdc", sdc)
    intent = _put(project, "phase1/generated_docs/L8_TIMING_WAVEFORM.json", {
        "clock_domains": [{"name": "clk", "period_ns": 10}], "reset": "rst_n"})
    _put(project, d45.INPUT, {"schema": d45.SCHEMA, "top": "neutral",
        "adopted_netlist": netlist, "sdc": [sdc], "image": image,
        "sta_config": config, "sta_receipt": receipt,
        "library_files": {"/pdk/current.lib": liberty},
        "clock_reset_intent": intent})


def _frontdoor_case(project):
    _case(project)
    _put(project, "input/submission_template/tapeout_declaration.json", {
        "answers": {"deliverable": "DIE", "top_cell": "neutral"},
        "answer_provenance": {"deliverable": {
            "answered_by": "owner", "citation": "D45 neutral native control"}}})
    features = next(item["features"] for item in flow109.load_registry()["reference_profiles"]
                    if item["name"] == "Small digital IC without DFT")
    plan = flow109.resolve_plan(features)
    config = _put(project, "input/d45-operation.json",
                  {"operation": "D45 supported Default row completion"})
    reference = _put(project, "input/d45-reference.json",
                     {"scope": "developer native control; not product qualification"})
    not_applicable = {"applicable": False,
                      "reason": "D45 structural reader loads receipt-bound Liberty files"}
    uses, records = [], []
    for use in flow109.resolve_step(plan, "D45")["tool_uses"]:
        binary = Path(shutil.which(use["executable_name"])).resolve()
        executable = {"path": str(binary), "sha256": d45._sha(binary)}
        identity = {"use_id": use["use_id"], "tool_id": use["tool_id"],
                    "version": "pinned native test image", "build_sha256": executable["sha256"],
                    "executable": executable, "config": config, "pdk": not_applicable,
                    "deck": not_applicable, "corner": "receipt-bound-control",
                    "semantics": {"purpose": use["purpose"],
                                  "native_steps": use["native_steps"]}}
        record = {"use_id": use["use_id"], "status": "QUALIFIED",
                  "identity": identity, "reference_evidence": [reference]}
        records.append(record)
        uses.append({**identity, "qualification_sha256": admission.canonical_sha(record)})
    _put(project, "qualifications.json",
         {"schema": "vibeic.flow109.qualifications.v1", "uses": records})
    manifest = project / "manifest.json"
    manifest.write_text(json.dumps({"features": features,
        "runtime_tool_uses": uses, "qualification_registry": "qualifications.json"}))
    return manifest


def test_single_domain_without_crossings_runs_consumers_as_bounded_component(tmp_path):
    _case(tmp_path)
    result = d45.execute(tmp_path, _context())
    assert result["native_started"] is True
    assert result["component_status"] == "PASS"
    assert result["reason"] is None
    assert result["checks"]["implemented_crossing_census"]["status"] == "PASS"
    assert result["checks"]["new_unexplained_crossings"]["status"] == "PASS"
    assert result["checks"]["reset_dependency"]["status"] == "PASS"
    assert result["checks"]["exception_reconciliation"]["status"] == "PASS"
    assert result["checks"]["protocol_semantics"]["status"] == "PASS"
    assert result["flow109_acceptance"] == "NOT_MEASURED"
    assert result["metrics"]["decoded_flop_count"] == 1
    assert result["metrics"]["decoded_async_reset_flop_count"] == 1
    assert result["metrics"]["decoded_sync_reset_flop_count"] == 0
    assert result["consumers"]["cdc_crossing_check"]["passed"] is True
    assert result["consumers"]["sdc_exception_correlation_check"]["verdict"] == "PASS"


def test_current_native_receipt_completes_only_the_supported_default_row(tmp_path):
    _case(tmp_path)
    context = _context()
    component = d45.execute(tmp_path, context)
    completion = d45.consume_default_row_completion(tmp_path, context, component)
    assert completion["default_row_status"] == "PASS", completion
    assert completion["completed"] is True
    assert completion["required_checks"] == list(d45.REQUIRED_COMPLETION_CHECKS)
    assert completion["selected_obligations"] == list(d45.REQUIRED_COMPLETION_OBLIGATIONS)
    assert completion["flow109_acceptance"] == "NOT_MEASURED"
    assert completion["whole_flow_acceptance"] == "NOT_MEASURED"
    assert completion["whole_ic_acceptance"] == "NOT_MEASURED"
    receipt = tmp_path / completion["component_receipt"]["path"]
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() == completion["component_receipt"]["sha256"]


def test_actual_frontdoor_publishes_d45_default_row_without_flow_acceptance(tmp_path):
    manifest = _frontdoor_case(tmp_path)
    env = dict(os.environ)
    env.pop(flow109.CONTEXT_ENV, None)
    env.pop(flow109.ATTEMPT_ENV, None)
    runner = Path(d45.__file__).parent / "vibe_ic_one_shot_runner.py"
    launched = subprocess.run([sys.executable, str(runner), str(tmp_path),
        "--flow", "109", "--flow109-manifest", str(manifest),
        "--entry-step", "D45", "--exit-step", "D45", "--route", "ic",
        "--no-dashboard"], capture_output=True, text=True, env=env)
    assert launched.returncode == 0, launched.stdout + launched.stderr
    result = json.loads((tmp_path / "reports/flow109/default_rows/D45.json").read_text())
    assert result["default_row_status"] == "PASS"
    assert result["completed"] is True
    assert result["flow109_acceptance"] == "NOT_MEASURED"
    assert "Default row PASS; flow acceptance NOT_MEASURED" in launched.stdout


def test_missing_raw_native_receipt_cannot_complete_default_row(tmp_path):
    _case(tmp_path)
    context = _context()
    component = d45.execute(tmp_path, context)
    (tmp_path / component["receipt"]["path"]).unlink()
    completion = d45.consume_default_row_completion(tmp_path, context, component)
    assert completion["default_row_status"] == "NOT_MEASURED"
    assert completion["completed"] is False
    assert completion["reason"] == "D45_COMPLETION_RECEIPT_MISSING"


def test_stale_native_input_cannot_complete_default_row(tmp_path):
    _case(tmp_path)
    context = _context()
    component = d45.execute(tmp_path, context)
    (tmp_path / "adopted/current.v").write_text("module changed; endmodule\n")
    completion = d45.consume_default_row_completion(tmp_path, context, component)
    assert completion["default_row_status"] == "NOT_MEASURED"
    assert completion["completed"] is False
    assert completion["reason"] == "D45_COMPLETION_INPUT_STALE"


def test_current_native_failure_remains_failed_default_row(tmp_path):
    _case(tmp_path, inconsistent=True)
    context = _context()
    component = d45.execute(tmp_path, context)
    assert component["component_status"] == "FAIL"
    completion = d45.consume_default_row_completion(tmp_path, context, component)
    assert completion["default_row_status"] == "FAIL", completion
    assert completion["completed"] is False
    assert completion["reason"] == "D45_EXCEPTION_INCONSISTENT"


def test_unjustified_current_sdc_exception_is_a_real_refusal(tmp_path):
    _case(tmp_path, inconsistent=True)
    result = d45.execute(tmp_path, _context())
    assert result["native_started"] is True
    assert result["component_status"] == "FAIL"
    assert result["reason"] == "D45_EXCEPTION_INCONSISTENT"
    check = result["checks"]["exception_reconciliation"]
    assert check["status"] == "FAIL"
    assert "SDC_EXCEPTION_UNJUSTIFIED" in check["categories"]


def test_two_clock_no_crossing_keeps_protocol_semantics_not_measured(tmp_path):
    _case(tmp_path, multi_domain=True)
    result = d45.execute(tmp_path, _context())
    assert result["native_started"] is True
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D45_PROTOCOL_SEMANTICS_UNSUPPORTED"
    assert result["checks"]["protocol_semantics"]["status"] == "NOT_MEASURED"


def test_changed_adopted_netlist_refuses_before_native_launch(tmp_path):
    _case(tmp_path)
    (tmp_path / "adopted/current.v").write_text("module changed; endmodule\n")
    result = d45.execute(tmp_path, _context())
    assert result["native_started"] is False
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D45_INPUT_STALE_OR_MISSING"


def test_partial_declared_library_closure_refuses_before_native_launch(tmp_path):
    _case(tmp_path)
    manifest = json.loads((tmp_path / d45.INPUT).read_text())
    config = json.loads((tmp_path / manifest["sta_config"]["path"]).read_text())
    config["PAD_LIBS"] = {"control_*": ["/pdk/io.lib"]}
    config_path = tmp_path / manifest["sta_config"]["path"]
    config_path.write_text(json.dumps(config))
    manifest["sta_config"]["sha256"] = hashlib.sha256(config_path.read_bytes()).hexdigest()
    receipt_path = tmp_path / manifest["sta_receipt"]["path"]
    receipt = json.loads(receipt_path.read_text())
    receipt["sha256"]["config.json"] = manifest["sta_config"]["sha256"]
    receipt_path.write_text(json.dumps(receipt))
    manifest["sta_receipt"]["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    (tmp_path / d45.INPUT).write_text(json.dumps(manifest))
    result = d45.execute(tmp_path, _context())
    assert result["native_started"] is False
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D45_LIBRARY_CLOSURE_INCOMPLETE"


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


def test_registry_selects_only_the_d45_row_local_adapter():
    registry = json.loads((Path(d45.__file__).parent.parent / "flow/flow109.json").read_text())
    row = next(item for item in registry["rows"] if item["id"] == "D45")
    profile = row["profiles"][0]
    assert profile["dispatch"]["adapter"] == "flow109_netlist_cdc"
    assert profile["dispatch"]["native_step_id"] == "flow109.D45"
    assert profile["dispatch"]["engine_families"] == ["python3", "yosys"]
