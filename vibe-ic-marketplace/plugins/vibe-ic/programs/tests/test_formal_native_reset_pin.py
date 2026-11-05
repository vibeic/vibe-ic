"""Reset metadata comes from native reset pins; no transition SAT is needed."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import formal_harness_gen as fhg
import formal_property_run as fpr
import formal_proof_evidence_check as gate
import formal_structural_check as fsc

NAME = "L8.clock_and_reset_waveform.resets.0.name"
CLAIMS = [{"rule": rule, "signal": "rst_n", "value": value} for rule, value in (
    ("reset_port", ""), ("reset_polarity", "active_low"), ("reset_sync", "synchronous"))]
RTL = """module neutral(input clk,rst_n,sel,d,output y);
reg q;
always @(posedge clk) if (!rst_n) q<=0; else q<=d;
assign y=sel?q:1'b1;
endmodule
"""


def no_transition_sat(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("reset metadata must not run the transition SAT batch")
    monkeypatch.setattr(fsc, "reset_control_mapping", refuse)


@pytest.mark.parametrize("edit,expected", [
    (lambda s: s, [fsc.PASS] * 3),
    (lambda s: s.replace("if (!rst_n)", "if (rst_n)"),
     [fsc.PASS, fsc.REFUTED, fsc.PASS]),
    (lambda s: s.replace("posedge clk", "posedge clk or negedge rst_n"),
     [fsc.PASS, fsc.PASS, fsc.REFUTED]),
    (lambda s: s.replace("if (!rst_n) q<=0; else q<=d;", "q<=rst_n;"),
     [fsc.NOT_DISCHARGED] * 3),
    (lambda s: s.replace("if (!rst_n) q<=0; else q<=d;", "q<=d;"),
     [fsc.NOT_DISCHARGED] * 3),
    (lambda s: s.replace("if (!rst_n)", "if (!rst_n || sel)"),
     [fsc.NOT_DISCHARGED] * 3),
])
def test_native_pin_metadata_without_transition_sat(tmp_path, monkeypatch, edit, expected):
    no_transition_sat(monkeypatch)
    rtl = tmp_path / "neutral.v"
    rtl.write_text(edit(RTL))
    evidence = fsc.check([rtl], "neutral", CLAIMS, tmp_path / "native")
    assert [c["verdict"] for c in evidence["claims"]] == expected, evidence
    assert all("reset_control_mapping" not in c for c in evidence["claims"])


def test_normal_cli_never_invokes_transition_sat_and_missing_port_stays_open(tmp_path, monkeypatch, capsys):
    no_transition_sat(monkeypatch)
    rtl = tmp_path / "neutral.v"
    rtl.write_text(RTL)
    for signal, expected in (("rst_n", fsc.PASS), ("absent_reset", fsc.NOT_APPLICABLE)):
        output = tmp_path / f"{signal}.json"
        rc = fsc.main(["--rtl", str(rtl), "--top", "neutral", "--claim", f"reset_port:{signal}:",
                       "--work-dir", str(tmp_path / signal), "--json", str(output)])
        capsys.readouterr()
        assert json.loads(output.read_text())["claims"][0]["verdict"] == expected
        assert rc == (0 if expected == fsc.PASS else 1)


def native_model(kind="$sdff", *, root=2, parameter="SRST_POLARITY"):
    pin = "ARST" if kind == "$adff" else "SRST"
    return {"modules": {"neutral": {"ports": {
        "rst_n": {"direction": "input", "bits": [2]},
        "y": {"direction": "output", "bits": [4]}}, "cells": {
            "state": {"type": kind, "parameters": {parameter: 0},
                      "connections": {"CLK": [5], pin: [root], "D": [3], "Q": [4]},
                      "port_directions": {"CLK": "input", pin: "input", "D": "input", "Q": "output"}}}}}}


@pytest.mark.parametrize("model", [native_model("$dff"), native_model("$unknown"),
    native_model(root=9), native_model(parameter="OTHER_POLARITY")])
def test_unrecognized_cell_root_or_parameter_is_not_a_reset_witness(model):
    assert all(fsc.check_claim(model, "neutral", c)["verdict"] != fsc.PASS for c in CLAIMS)


def test_supported_inverter_root_preserves_effective_polarity():
    model = native_model(root=9)
    cells = model["modules"]["neutral"]["cells"]
    cells["invert"] = {"type": "$not", "connections": {"A": [2], "Y": [9]},
                       "port_directions": {"A": "input", "Y": "output"}}
    cells["state"]["parameters"]["SRST_POLARITY"] = 1
    assert [fsc.check_claim(model, "neutral", c)["verdict"] for c in CLAIMS] == [fsc.PASS] * 3


@pytest.mark.parametrize("polarity", [2, "10", 3, -1])
def test_non_boolean_native_polarity_is_unknown(polarity):
    model = native_model()
    model["modules"]["neutral"]["cells"]["state"]["parameters"]["SRST_POLARITY"] = polarity
    assert [fsc.check_claim(model, "neutral", c)["verdict"] for c in CLAIMS] == [fsc.NOT_DISCHARGED] * 3


@pytest.mark.parametrize("pin", [[2, "x"], [2, "0"], [2, "1"], [2, 3]])
def test_reset_pin_is_scalar_in_native_connections(pin):
    model = native_model()
    model["modules"]["neutral"]["cells"]["state"]["connections"]["SRST"] = pin
    assert [fsc.check_claim(model, "neutral", c)["verdict"] for c in CLAIMS] == [fsc.NOT_DISCHARGED] * 3


def binding_fixture(tmp_path, monkeypatch, rtl=RTL):
    no_transition_sat(monkeypatch)
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L3_PROTOCOL.json").write_text(json.dumps({"no_opcodes_in_input": True}))
    (docs / "L6_FSM.json").write_text(json.dumps({"no_fsm_in_input": True}))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({"clock_and_reset_waveform": {
        "clocks": [{"name": "clk", "edge": "posedge"}],
        "resets": [{"name": "rst_n", "polarity": "active_low", "sync": "synchronous"}]}}))
    rd = tmp_path / "phase2/stage1/rtl"
    rd.mkdir(parents=True)
    (rd / "neutral.v").write_text(rtl)
    formal = tmp_path / "phase2/stage1/formal"
    formal.mkdir(parents=True)
    contract = fhg.declaration_obligations(tmp_path)
    contract["unresolved_obligations"] = contract["obligations"]
    contract["structural_subject"] = {"top": "neutral", "rtl_files": [str(rd / "neutral.v")],
                                      "clock": "clk", "resets": ["rst_n"]}
    (formal / "property_contract.json").write_text(json.dumps(contract))
    harness = formal / "formal_neutral.sv"
    # Software consumer control: task status below is fixture data, not a proof.
    body = """module formal_neutral(input clk,rst_n,sel,d);
wire rst_active = !rst_n;
wire y;
neutral dut(.clk(clk),.rst_n(rst_n),.sel(sel),.d(d),.y(y));
always @(posedge clk) if (rst_active && sel) a_qualified: assert(y==0);
endmodule
"""
    harness.write_text(body)
    fpr._program_discharge(formal, None, body)
    import _chip_synth_read as csr
    results = {"unresolved_obligations": [{"id": NAME}], "all_proved": True,
               "properties": [{"task": "prove", "status": "PASS", "bound": "unbounded"}],
               "proof_inputs": {"files": {harness.name: hashlib.sha256(body.encode()).hexdigest()}},
               "chip_read": csr.current_chip_read(tmp_path, "neutral")}
    return formal, harness, results


def test_native_pin_closes_binding_for_qualified_output_property(tmp_path, monkeypatch):
    formal, harness, results = binding_fixture(tmp_path, monkeypatch)
    assert not gate._reset_guarded_properties(harness.read_text(), {"y"})
    row, = gate.binding_dispositions(tmp_path, formal, results)
    assert row["status"] == gate.DISCHARGED_BY_BINDING, row
    assert row["property"] is None
    assert "native Yosys reset pin" in row["reason"]


@pytest.mark.parametrize("rtl", [
    RTL.replace("if (!rst_n) q<=0; else q<=d;", "q<=rst_n;"),
    RTL.replace("if (!rst_n) q<=0; else q<=d;", "q<=d;"),
    RTL.replace("if (!rst_n)", "if (!rst_n || sel)"),
    RTL.replace("clk,rst_n,sel,d", "clk,sel,d").replace("if (!rst_n) q<=0; else q<=d;", "q<=d;"),
])
def test_binding_requires_an_actual_native_reset_pin(tmp_path, monkeypatch, rtl):
    formal, harness, results = binding_fixture(tmp_path, monkeypatch, rtl)
    row, = gate.binding_dispositions(tmp_path, formal, results)
    assert row["status"] == gate.BINDING_OUTSTANDING, row


@pytest.mark.parametrize("stale", ["rtl", "evidence", "contract", "harness"])
def test_native_reset_binding_refuses_stale_evidence(tmp_path, monkeypatch, stale):
    formal, harness, results = binding_fixture(tmp_path, monkeypatch)
    path = {"rtl": tmp_path / "phase2/stage1/rtl/neutral.v",
            "evidence": formal / fpr.STRUCTURAL_EVIDENCE,
            "contract": formal / "property_contract.json", "harness": harness}[stale]
    path.write_text(path.read_text() + "\n")
    row, = gate.binding_dispositions(tmp_path, formal, results)
    assert row["status"] == gate.BINDING_OUTSTANDING, row
