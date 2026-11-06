#!/usr/bin/env python3
"""#3165 — clock edge owns a complete-state applicability route.

These deliberately use reset in data and enable plus dotted, post-flatten
state names.  They are not reset/value tests: the positive edge must close,
the opposite edge must refute, and a derived clock must remain refused.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import formal_structural_check as fsc  # noqa: E402
import formal_harness_gen as fhg  # noqa: E402
import formal_property_run as fpr  # noqa: E402
from _tool_probes import skip_not_verified  # noqa: E402


HIER = '''module neutral_leaf(input wire clk, rst, clear, enable, data, output wire value);
reg forced;
reg held;
always @(posedge clk) begin
  if (enable) forced <= data & ~(rst & clear);
  if (enable & ~rst) held <= data;
end
assign value = forced ^ held;
endmodule
module neutral_clock(input wire clk, rst, clear, enable, data, output wire out);
neutral_leaf leaf(.clk(clk), .rst(rst), .clear(clear), .enable(enable), .data(data), .value(out));
endmodule
'''

DERIVED = HIER.replace(".clk(clk)", ".clk(clk_g)").replace(
    "neutral_leaf leaf", "wire clk_g = clk & enable;\nneutral_leaf leaf")
HARNESS_HIER = HIER.replace(
    "output wire out);\nneutral_leaf leaf(.clk(clk), .rst(rst), .clear(clear), .enable(enable), .data(data), .value(out));",
    "output reg out);\nwire leaf_value;\nneutral_leaf leaf(.clk(clk), .rst(rst), .clear(clear), .enable(enable), .data(data), .value(leaf_value));\nalways @(posedge clk) if (rst) out <= 1'b0; else out <= leaf_value;")
CLAIM = {"rule": "clock_edge", "signal": "clk", "value": "posedge"}
KLASS = {"clock": "clk", "resets": ["rst"]}


def _check(tmp_path: Path, rtl: str) -> dict:
    if shutil.which("yosys") is None:
        skip_not_verified(
            "yosys not on PATH, so #3165's native structural control cannot run",
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_issue3165_clock_edge_claim_specific.py")
    source = tmp_path / "neutral_clock.v"
    source.write_text(rtl)
    return fsc.check([source], "neutral_clock", [CLAIM], tmp_path / "native",
                     container=None, simdef="", klass=KLASS)


def test_hierarchical_reset_qualified_state_passes_only_clock_edge_route(tmp_path):
    result = _check(tmp_path, HIER)
    assert result["verdict"] == fsc.PASS
    assert result["claims"][0]["verdict"] == fsc.PASS
    assert result["claims"][0]["flops_clocked"] == 2
    assert result["applicability"]["inside"] is False
    assert any(row.startswith("C3 ") for row in result["applicability"]["failed_preconditions"])
    assert any(row.startswith("C6 ") for row in result["applicability"]["failed_preconditions"])
    assert result["clock_edge_applicability"] == {
        "class": "complete-state direct-clock observation", "inside": True,
        "failed_preconditions": []}
    raw = fsc.sync_state_facts(
        json.loads((tmp_path / "native" / "formal_structural_netlist_raw.json").read_text()),
        "neutral_clock", "clk")
    opt = fsc.sync_state_facts(
        json.loads((tmp_path / "native" / "formal_structural_netlist.json").read_text()),
        "neutral_clock", "clk")
    assert raw["ok"] and opt["ok"]
    assert sorted((r["name"], r["width"]) for r in raw["registers"]) == [
        ("leaf.forced", 1), ("leaf.held", 1)]
    assert sorted((r["name"], r["width"]) for r in opt["registers"]) == [
        ("leaf.forced", 1), ("leaf.held", 1)]
    assert raw["clock_edge"] == opt["clock_edge"] == "posedge"


def test_hierarchical_opposite_edge_is_refuted(tmp_path):
    result = _check(tmp_path, HIER.replace("posedge", "negedge"))
    assert result["verdict"] == fsc.REFUTED
    assert result["claims"][0]["verdict"] == fsc.REFUTED
    assert result["clock_edge_applicability"]["inside"] is True


def test_derived_clock_stays_named_not_discharged(tmp_path):
    result = _check(tmp_path, DERIVED)
    assert result["verdict"] == fsc.NOT_DISCHARGED
    assert result["claims"][0]["verdict"] == fsc.NOT_DISCHARGED
    assert result["clock_edge_applicability"]["inside"] is False
    assert "optimized-state census unavailable" in result["claims"][0]["finding"]


def test_harness_producer_and_structural_consumer_close_the_claim(tmp_path):
    if shutil.which("sby") is None:
        skip_not_verified(
            "sby not on PATH, so #3165's normal producer-to-consumer route cannot run",
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_issue3165_clock_edge_claim_specific.py")
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L3_PROTOCOL.json").write_text(json.dumps({"no_opcodes_in_input": True}))
    (docs / "L6_FSM.json").write_text(json.dumps({"no_fsm_in_input": True}))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "clock_and_reset_waveform": {"clocks": [{"name": "clk", "edge": "posedge"}],
                                     "resets": [{"name": "rst"}]}}))
    rtl_dir = tmp_path / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    rtl = rtl_dir / "neutral_clock.v"
    rtl.write_text(HARNESS_HIER)
    generated = fhg.generate(project=tmp_path, top="neutral_clock")
    assert generated["verdict"] == "EMITTED", generated
    contract = json.loads((tmp_path / "phase2/stage1/formal/property_contract.json").read_text())
    clock_obligation = next(o for o in contract["unresolved_obligations"]
                            if o["id"] == "L8.clock_and_reset_waveform.clocks.0.edge")
    assert "program_refused" not in clock_obligation
    result = fpr.run(tmp_path, harness=Path(generated["harness_path"]),
                     rtl=[Path(p) for p in generated["rtl_files"]],
                     top=generated["harness_module"], container=None, timeout=300)
    assert "L8.clock_and_reset_waveform.clocks.0.edge" in result[
        "program_discharged_obligations"]


# #3340 public portable fixture, verbatim; scalar is only its existing control.
ARRAY = """module neutral(input clk,rst_n,we,input [1:0] addr,input [3:0] d,output [3:0] y);
reg [3:0] words [0:3];
always @(posedge clk) begin
 if (!rst_n) words[0] <= 0;
 else if (we) words[addr] <= d;
end
assign y=words[addr];
endmodule
"""
SCALAR = """module neutral(input clk,rst_n,we,input [1:0] addr,input [3:0] d,output reg [3:0] y);
always @(posedge clk) if(!rst_n) y<=0; else if(we) y<=d;
endmodule
"""


# #3358 exact public input: independent, fully observable 16-entry case ROM.
ARRAY_ROM = """module neutral(input clk,rst_n,we,input [1:0] addr,input [3:0] d,input [3:0] opcode,output [3:0] y,output reg [7:0] lookup);
reg [3:0] words [0:3];
always @(posedge clk) begin
 if (!rst_n) words[0] <= 0;
 else if (we) words[addr] <= d;
end
assign y=words[addr];
always @* begin
 case(opcode)
4'd0: lookup=8'd17;
4'd1: lookup=8'd206;
4'd2: lookup=8'd57;
4'd3: lookup=8'd143;
4'd4: lookup=8'd84;
4'd5: lookup=8'd233;
4'd6: lookup=8'd6;
4'd7: lookup=8'd190;
4'd8: lookup=8'd72;
4'd9: lookup=8'd165;
4'd10: lookup=8'd31;
4'd11: lookup=8'd249;
4'd12: lookup=8'd118;
4'd13: lookup=8'd3;
4'd14: lookup=8'd212;
4'd15: lookup=8'd95;
default: lookup=8'd0;
 endcase
end
endmodule
"""


def _array_check(tmp_path, rtl, claims=None):
    if shutil.which("yosys") is None:
        skip_not_verified("yosys unavailable for native array clock observation",
                          "programs/tests/test_issue3165_clock_edge_claim_specific.py")
    source = tmp_path / "neutral.v"
    source.write_text(rtl)
    result = fsc.check([source], "neutral", claims or [CLAIM], tmp_path / "native",
                       klass={"clock": "clk", "resets": ["rst_n"]})
    (tmp_path / "public-check.json").write_text(json.dumps(result, indent=2))
    assert result["rtl_sha256"][str(source)] == fsc.file_sha256(source)
    return result


@pytest.mark.parametrize("rtl,verdict,width", [
    (ARRAY, fsc.PASS, 16), (SCALAR, fsc.PASS, 4),
    (ARRAY.replace("posedge clk", "negedge clk"), fsc.REFUTED, 16),
    (ARRAY.replace("words", "\\bank.words$ "), fsc.PASS, 16),
    (ARRAY_ROM, fsc.PASS, 16),
    (ARRAY_ROM.replace("posedge clk", "negedge clk"), fsc.REFUTED, 16),
    (ARRAY_ROM.replace("words", "entries").replace("opcode", "operation"), fsc.PASS, 16),
], ids=["memory", "scalar-control", "memory-negedge", "escaped-memory",
       "comb-rom", "comb-rom-negedge", "renamed-comb-rom"])
def test_register_array_public_clock_census(tmp_path, rtl, verdict, width):
    result = _array_check(tmp_path, rtl)
    assert result["verdict"] == verdict, result
    assert result["claims"][0]["verdict"] == verdict
    if width == 16:
        elaboration = result["clock_edge_elaborations"][0]
        aliases = result["clock_edge_source_aliases"]
        assert len([a for a in aliases.values() if a.get("memory")]) == 4
        for view in ("raw", "optimized"):
            observed = elaboration[view]
            assert observed["yosys_rc"] == 0
            assert observed["sha256"] == fsc.file_sha256(Path(observed["path"]))
            facts = observed["state"]
            assert facts["ok"] and len(facts["q_bits"]) == 16, facts
            assert sorted(r["width"] for r in facts["registers"]) == [4, 4, 4, 4]
            assert len({b for r in facts["registers"] for b in r["q"]}) == 16
            assert facts["clock_edge"] == ("negedge" if verdict == fsc.REFUTED else "posedge")
        assert result["applicability"]["inside"] is False  # reset scope unchanged
    else:
        for name in ("formal_structural_netlist_raw.json", "formal_structural_netlist.json"):
            facts = fsc.sync_state_facts(json.loads((tmp_path / "native" / name).read_text()),
                                          "neutral", "clk")
            assert facts["ok"] and len(facts["q_bits"]) == width


@pytest.mark.parametrize("case", ["mixed-edge", "second-clock", "derived-clock", "latch",
                                  "unknown-cell", "native-failure", "rom-undefined",
                                  "rom-writable-opposite", "rom-writable-async"])
def test_array_clock_unsupported_state_stays_not_discharged(tmp_path, case):
    rtl = ARRAY
    if case == "rom-undefined":
        rtl = ARRAY_ROM.replace("8'd17", "8'bxxxxxxxx")
    elif case.startswith("rom-writable-"):
        # A constant initializer cannot make memory with a runtime writer ROM.
        start = ARRAY_ROM.index("always @* begin")
        rtl = ARRAY_ROM[:start] + "reg [7:0] table_data [0:15];\ninitial begin\n" + "".join(
            f"table_data[{i}]=8'd{v};\n" for i, v in enumerate(
                [17, 206, 57, 143, 84, 233, 6, 190, 72, 165, 31, 249, 118, 3, 212, 95]))
        event = "@(negedge clk)" if case == "rom-writable-opposite" else "@*"
        rtl += ("end\nalways " + event + " if(we) table_data[opcode] <= {4'b0,d};\n"
                "always @* lookup=table_data[opcode];\nendmodule\n")
    elif case == "native-failure":
        rtl = rtl.replace("endmodule", "invalid syntax\nendmodule")
    elif case == "derived-clock":
        rtl = rtl.replace("posedge clk", "posedge gated").replace(
            "reg [3:0] words", "wire gated = clk & we;\nreg [3:0] words")
    else:
        aux = {"mixed-edge": "always @(negedge clk) aux <= d;",
               "second-clock": "always @(posedge rst_n) aux <= d;",
               "latch": "always @* if (we) aux = d;",
               "unknown-cell": "(* keep *) opaque cell0(.a(d), .y(aux));"}[case]
        rtl = rtl.replace("assign y=words[addr];", "reg [3:0] aux;\n" + aux
                          + "\nassign y=words[addr] ^ aux;")
        if case == "unknown-cell":
            rtl += "(* blackbox *) module opaque(input [3:0] a, output [3:0] y); endmodule\n"
    result = _array_check(tmp_path, rtl)
    assert result["verdict"] == fsc.NOT_DISCHARGED, result
    assert result["clock_edge_applicability"]["inside"] is False


@pytest.mark.parametrize("case", ["missing-word", "overlapping-words", "missing-source"])
def test_array_clock_incomplete_source_aliases_refuse(tmp_path, monkeypatch, case):
    native = fsc.run_yosys

    def incomplete(*args, **kwargs):
        rc, log, path = native(*args, **kwargs)
        if rc == 0:
            netlist = json.loads(path.read_text())
            mod = netlist["modules"]["neutral"]
            if case == "missing-source" and kwargs.get("tag") == "_raw":
                mod["memories"]["words"]["attributes"].pop("src")
            elif kwargs.get("tag") == "_clock_raw":
                if case == "missing-word":
                    del mod["netnames"]["words[2]"]
                elif case == "overlapping-words":
                    mod["netnames"]["words[2]"]["bits"] = mod["netnames"]["words[1]"]["bits"]
            path.write_text(json.dumps(netlist))
        return rc, log, path

    monkeypatch.setattr(fsc, "run_yosys", incomplete)
    result = _array_check(tmp_path, ARRAY)
    assert result["verdict"] == fsc.NOT_DISCHARGED, result
    assert result["clock_edge_applicability"]["inside"] is False


def test_array_clock_does_not_admit_reset_claims(tmp_path):
    result = _array_check(tmp_path, ARRAY, [CLAIM,
        {"rule": "reset_sync", "signal": "rst_n", "value": "synchronous"}])
    assert result["claims"][0]["verdict"] == fsc.PASS, result
    assert result["claims"][1]["verdict"] == fsc.NOT_DISCHARGED


@pytest.mark.parametrize("rtl", [ARRAY, ARRAY_ROM], ids=["plain", "comb-rom"])
def test_array_harness_property_consumer_receives_clock_claim(tmp_path, rtl):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L3_PROTOCOL.json").write_text(json.dumps({"no_opcodes_in_input": True}))
    (docs / "L6_FSM.json").write_text(json.dumps({"no_fsm_in_input": True}))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "clock_and_reset_waveform": {"clocks": [{"name": "clk", "edge": "posedge"}],
                                     "resets": [{"name": "rst_n"}]}}))
    rtl_dir = tmp_path / "phase2/stage1/rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "neutral.v").write_text(rtl)
    generated = fhg.generate(project=tmp_path, top="neutral")
    contract_path = tmp_path / "phase2/stage1/formal/property_contract.json"
    contract = json.loads(contract_path.read_text())
    clock_id = "L8.clock_and_reset_waveform.clocks.0.edge"
    obligation = next(o for o in contract["unresolved_obligations"] if o["id"] == clock_id)
    assert "program_refused" not in obligation, obligation
    # This original array has no registered-output temporal floor. The normal
    # producer explicitly routes its declarations through structural_subject.
    assert generated["verdict"] == "INCOMPLETE"
    assert contract["structural_subject"]["top"] == "neutral"
    formal_dir = contract_path.parent
    # Exercise the real run() structural producer and immutable readback
    # boundary without launching an unrelated temporal engine or claiming it.
    receipt = fpr._program_discharge(formal_dir, None, "")
    assert receipt is not None
    result = {"all_proved": False}
    fpr._attach_property_contract(result, formal_dir, None)
    (formal_dir / "consumer-readback.json").write_text(json.dumps(result, indent=2))
    assert clock_id in result.get("program_discharged_obligations", []), result
    assert result["unresolved_obligations"]  # reset binding remains open

    # The existing immutable consumer binding must refuse a changed source,
    # and accept the exact original bytes again without rewriting evidence.
    source = rtl_dir / "neutral.v"
    source.write_text(rtl + "// changed source after discharge\n")
    stale = {"all_proved": False}
    fpr._attach_property_contract(stale, formal_dir, None)
    assert clock_id not in stale.get("program_discharged_obligations", []), stale
    source.write_text(rtl)
    restored = {"all_proved": False}
    fpr._attach_property_contract(restored, formal_dir, None)
    assert clock_id in restored.get("program_discharged_obligations", []), restored
