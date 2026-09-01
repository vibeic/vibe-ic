#!/usr/bin/env python3
"""Issue #1968: applicability is a design verdict, never an argv crash.

The production break these tests catch is deleting (or bypassing) a declared
invocation contract for one of the 36 P0 gates that rejected the umbrella's
generic positional argv at the measured base revision.  A protocol-free design
must receive a real verdict or an explicit declaration-derived N/A for each of
the 36. A protocol design that declares the corresponding inputs must dispatch
all 36 through their real CLIs, so none can disappear behind
``NOT_INVOCABLE`` or a broad class skip.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


def _load_flow():
    spec = importlib.util.spec_from_file_location(
        "fcc_i1968", PROGRAMS / "flow_compliance_check.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["fcc_i1968"] = module
    spec.loader.exec_module(module)
    return module


F = _load_flow()


# Literal, hand-checked population measured on the accepted base.  Deriving the
# expectation from the production registry would let a deleted contract delete
# its own test oracle.
ISSUE_1968_GATES = (
    "backlog_sanitize_check",
    "bit_count_modulo_check",
    "cmd_arg_range_validation_check",
    "crc_bitorder_check",
    "crc_seed_consistency_check",
    "cross_constant_invariant_check",
    "fpga_async_input_synchronizer_check",
    "fpga_qsf_lint",
    "fresh_agent_provenance_check",
    "interface_encoding_audit",
    "json_schema_check",
    "l12_sequence_implementation_check",
    "l9_completeness_check",
    "mask_application_check",
    "module_port_audit",
    "oe_pattern_check",
    "openroad_tcl_deprecation_check",
    "otp_write_lock_gate_check",
    "output_artifact_check",
    "packet_length_check_present",
    "payload_bit_position_check",
    "periodic_signal_required_check",
    "phase1_gate_contract_check",
    "practical_notes_specificity_check",
    "pre_awake_silence_check",
    "protocol_gap_check",
    "pulse_decoder_edge_check",
    "response_payload_template_check",
    "rtl_precheck_gate",
    "scope_periodic_pulse_check",
    "testbench_exists_check",
    "tester_oracle_health_check",
    "transient_signal_latch_check",
    "tristate_bus_check",
    "tristate_self_rx_mask_check",
    "warn_acceptance_policy_check",
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _write_rtl(project: Path) -> Path:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top #(parameter FRAME_MIN = 2, parameter FRAME_MAX = 8)(\n"
        "  input wire clk, input wire rst_n, input wire frame_end,\n"
        "  input wire bus_idle, input wire rx,\n"
        "  inout wire serial_bus, output wire periodic_tick,\n"
        "  output reg [7:0] crc_out);\n"
        "  reg serial_oe; reg serial_out; reg [7:0] bit_count;\n"
        "  assign serial_bus = serial_oe ? serial_out : 1'bz;\n"
        "  assign periodic_tick = bit_count[2];\n"
        "  always @(posedge clk or negedge rst_n) begin\n"
        "    if (!rst_n) begin bit_count <= 0; crc_out <= 0; end\n"
        "    else begin bit_count <= bit_count + 1'b1; crc_out <= {crc_out[6:0], rx}; end\n"
        "  end\n"
        "endmodule\n")
    return rtl


def _protocol_free_project(tmp_path: Path) -> Path:
    project = tmp_path / "arithmetic_project"
    _write_rtl(project)
    _write_json(project / "reports" / "ic_class.json", {
        "ic_class": "digital_arithmetic_primitive",
        "protocol_class": "none",
        "has_command_protocol": False,
        "has_otp": False,
        "has_inout_id_bus": False,
    })
    _write_json(project / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json", {
        "schema_version": 2,
        "doc_class": "cmd_protocol",
        "opcodes": [],
        "no_opcodes_in_input": True,
        "crc_parameters": None,
        "no_crc_parameters_in_input": True,
    })
    _write_json(project / "phase1" / "generated_docs" / "L4_REGMAP.json", {
        "schema_version": 2,
        "doc_class": "regmap",
        "registers": [],
        "register_map_present": False,
        "otp_layout": None,
    })
    _write_json(project / "phase1" / "generated_docs" / "L11_OTP_CONTENT.json", {
        "schema_version": 2,
        "doc_class": "otp_content",
        "otp_present": False,
        "no_otp_layout_in_input": True,
    })
    return project


def _declared_protocol_project(tmp_path: Path) -> Path:
    project = tmp_path / "declared_protocol_project"
    rtl = _write_rtl(project)
    generated = project / "phase1" / "generated_docs"
    _write_json(project / "reports" / "ic_class.json", {
        "ic_class": "serial_peripheral_controller",
        "protocol_class": "framed_serial",
        "has_command_protocol": True,
        "has_otp": True,
        "has_inout_id_bus": True,
    })
    _write_json(generated / "L3_CMD_PROTOCOL.json", {
        "schema_version": 2,
        "doc_class": "cmd_protocol",
        "opcodes": [{"name": "PING", "value": "0x01"}],
        "crc_parameters": {
            "signal": "crc_out",
            "seed": "0xff",
            "bit_order": "msb_first",
            "vectors_json": "phase1/generated_docs/crc_vectors.json",
        },
        "bit_layouts": {"0": {"bit_0": "rx"}},
        "protocol_gap": {
            "name": "frame_gap",
            "end_signal": "frame_end",
            "bus_idle": "bus_idle",
            "min_cycles": 2,
        },
    })
    _write_json(generated / "crc_vectors.json", {
        "rtl_params": {
            "width": 8,
            "poly": 7,
            "init": 255,
            "reflect_input": False,
            "reflect_output": False,
            "xor_output": 0,
        },
        "spec_vectors": [{
            "input_hex": "31 32 33 34 35 36 37 38 39",
            "expected_crc_hex": "0xf4",
            "source": "synthetic protocol fixture",
        }],
    })
    _write_json(generated / "L4_REGMAP.json", {
        "schema_version": 2,
        "doc_class": "regmap",
        "registers": [{"name": "CTRL", "offset": 0}],
        "register_map_present": True,
        "otp_layout": {
            "fields": [{"name": "LOCK", "lsb": 0, "width": 1}],
            "mask_sources": [{"signal": "crc_out", "and_mask": "0xff"}],
        },
    })
    _write_json(generated / "L9_INTEGRATION_SPEC.json", {
        "schema_version": 2,
        "doc_class": "integration_spec",
        "top_module": "top",
        "interfaces": [{
            "name": "serial_bus",
            "direction": "inout",
            "drivers": ["serial_oe", "serial_out"],
        }],
        "ports": [{"name": "clk", "direction": "input"}],
        "registers": [{"name": "CTRL", "offset": 0}],
        "timing": {"clock": "clk"},
        "reset": {"name": "rst_n", "active": "low"},
    })
    _write_json(generated / "L11_OTP_CONTENT.json", {
        "schema_version": 2,
        "doc_class": "otp_content",
        "otp_present": True,
        "otp_layout": {"lockbits": [{"name": "LOCK", "bit": 0}]},
    })
    _write_json(generated / "L12_BEHAVIORAL_SEQUENCES.json", {
        "schema_version": 2,
        "doc_class": "behavioral_sequences",
        "sequences": [{"id": "PING", "steps": ["receive", "reply"]}],
        "periodic_signals": [{
            "name": "periodic_tick",
            "period_const": "8",
            "output_port": "periodic_tick",
        }],
        "constant_invariants": [{
            "left": "FRAME_MAX", "op": ">=", "right": "FRAME_MIN",
        }],
    })
    fpga = project / "phase2" / "stage1" / "fpga"
    fpga.mkdir(parents=True)
    (fpga / "top.qsf").write_text(
        "set_global_assignment -name TOP_LEVEL_ENTITY top\n"
        f"set_global_assignment -name VERILOG_FILE {rtl / 'top.v'}\n")
    refs = project / "references"
    refs.mkdir()
    (refs / "reference.v").write_text("module reference(input clk); endmodule\n")
    (project / "reports").mkdir(exist_ok=True)
    backlog = project / "community" / "backlogs"
    backlog.mkdir(parents=True)
    (backlog / "README.md").write_text("# Synthetic backlog fixture\n")
    _write_json(project / "reports" / "tester_oracle.json", {
        "burn_command": ["/bin/true"],
        "tester_command": ["/bin/true"],
        "expected_bytes": [1],
    })
    (project / "scope_samples.csv").write_text(
        "time_us,voltage\n0.0,0.0\n1.0,3.3\n2.0,0.0\n")
    return project


def _run_issue_population(project: Path, monkeypatch):
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES", ISSUE_1968_GATES)
    records = []
    F._run_structural_rtl_gates(project, records_out=records)
    assert tuple(r["name"] for r in records) == ISSUE_1968_GATES
    return records


def test_protocol_free_design_gets_real_verdict_or_derived_na_for_all_36(
        tmp_path, monkeypatch):
    records = _run_issue_population(_protocol_free_project(tmp_path), monkeypatch)
    assert not [r for r in records if r["verdict"] == "NOT_INVOCABLE"]
    assert not [r for r in records
                if r["evidence"].get("skip_kind") == "class-not-applicable"]
    derived_na = [r for r in records
                  if r["evidence"].get("skip_kind") ==
                  "declaration-not-present"]
    real_verdicts = [r for r in records if r not in derived_na]
    assert derived_na and real_verdicts
    pre_awake = next(r for r in records
                     if r["name"] == "pre_awake_silence_check")
    assert pre_awake in derived_na
    assert all("N/A" in r["message"] and "declaration" in r["message"]
               for r in derived_na)
    assert all(r["evidence"].get("gate_started") for r in real_verdicts)
    assert {r["verdict"] for r in records} <= {
        "PASS", "FAIL", "SKIP", "WAIVED", "INCOMPLETE"}


def test_declared_protocol_design_dispatches_all_36_without_argv_crash(
        tmp_path, monkeypatch):
    records = _run_issue_population(_declared_protocol_project(tmp_path), monkeypatch)
    assert not [r for r in records if r["verdict"] == "NOT_INVOCABLE"]
    assert not [r for r in records
                if r["evidence"].get("skip_kind") in {
                    "class-not-applicable", "declaration-not-present"}]
    assert all(r["evidence"].get("invocation_contract") for r in records)
    assert all(r["evidence"].get("gate_started") for r in records)
    # A live control may PASS, FAIL, or report an input-shaped SKIP/INCOMPLETE;
    # it may not disappear before its parser/check body ran.
    assert {r["verdict"] for r in records} <= {
        "PASS", "FAIL", "SKIP", "WAIVED", "INCOMPLETE"}
    assert any(r["verdict"] == "FAIL" for r in records), (
        "the deliberately incomplete protocol control did not exercise any "
        "blocking gate; the control would not prove the family can still bite")


def test_malformed_declaration_stays_live_instead_of_becoming_derived_na(
        tmp_path, monkeypatch):
    project = _protocol_free_project(tmp_path)
    l3 = project / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json"
    l3.write_text('{"schema_version": 2, "opcodes": [')
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES", ("json_schema_check",))

    records = []
    F._run_structural_rtl_gates(project, records_out=records)

    assert len(records) == 1
    record = records[0]
    assert record["evidence"].get("gate_started") is True
    assert record["evidence"].get("skip_kind") != "declaration-not-present"
    assert record["verdict"] == "FAIL"
