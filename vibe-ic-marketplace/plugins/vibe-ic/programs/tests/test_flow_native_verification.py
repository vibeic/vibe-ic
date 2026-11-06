from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from flow_native_adapters import Commands, formal
from flow_native_verification import eqy, eqy_partitions, gls, reset_boundary, xor


@pytest.mark.parametrize("event", ["posedge clk", "negedge clk", "posedge clk or posedge reset"])
@pytest.mark.parametrize("legacy", [False, True])
def test_native_formal_preserves_global_clock_state_checks(tmp_path, event, legacy):
    if not all(shutil.which(name) for name in ("sby", "yosys", "yices-smt2")):
        pytest.skip("Native formal tools are required")
    from formal_property_run import emit_invariant_sby

    rtl = tmp_path / "phase2/stage1/rtl/unit.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module unit(input clk,reset,data,output reg q);\n"
        f"always @({event}) "
        + ("if(reset) q<=0; else " if "reset" in event else "")
        + "q<=data; endmodule\n")
    harness = tmp_path / "phase2/stage1/formal/formal_unit.sv"
    harness.parent.mkdir(parents=True)
    harness.write_text("module formal_unit(input clk);\n"
        "(* anyseq *) wire data,reset; wire q; unit dut(clk,reset,data,q);\n"
        "reg past_valid=0; always @($global_clock) past_valid<=1;\n"
        "always @($global_clock) if(past_valid && !(!$past(clk) && clk))\n"
        "  state_sync: assert(q==$past(q));\nendmodule\n")
    deck = harness.with_suffix(".sby")
    deck.write_text(emit_invariant_sby([str(rtl)], str(harness), "formal_unit", [], []))
    if legacy:
        deck.write_text(deck.read_text().replace("multiclock on\n", ""))
    originals = {p: p.read_bytes() for p in (rtl, harness, deck)}
    directory = tmp_path / "run"
    directory.mkdir()
    result = formal(tmp_path, directory, {"top": "unit", "properties": [str(deck)]}, Commands(directory))
    proofs = [row for row in result["native_steps"] if row["name"] in {"SymbiYosys.prove", "SymbiYosys.bmc"}]
    assert len(proofs) == 2, result
    assert all(row["status"] == ("PASS" if event == "posedge clk" else "FAIL") for row in proofs), result
    assert (result["metrics"].get("unproved_required_properties") == 0) is (event == "posedge clk"), result
    assert {p: p.read_bytes() for p in originals} == originals


@pytest.mark.parametrize("bad", [False, True])
@pytest.mark.parametrize("relative", [False, True])
def test_native_formal_retries_an_unsupported_sv_read_without_changing_properties(
        tmp_path, bad, relative):
    if not all(shutil.which(name) for name in ("sby", "yosys", "yices-smt2")):
        pytest.skip("Native formal tools are required")
    from formal_property_run import emit_invariant_sby

    source = tmp_path / "phase2/stage1/formal"
    source.mkdir(parents=True)
    package = source / "unit_pkg.sv"
    package.write_text("package unit_pkg; parameter SET=1'b1; endpackage\n")
    header = tmp_path / "input/settings.vh"
    header.parent.mkdir()
    header.write_text("`define RESET_VALUE 0\n")
    rtl = source / "unit.sv"
    rtl.write_text("module unit import unit_pkg::*; (input clk, rst_n, output reg [1:0] q);\n"
        "`ifdef FORMAL\n`ifdef YOSYS\n`ifndef SYNTHESIS\n"
        f"always @(posedge clk) if(!rst_n) q<=2'd{int(bad)}; else q<=q+1;\n"
        "`else\nalways @(posedge clk) q<=1;\n`endif\n"
        "`else\nalways @(posedge clk) q<=1;\n`endif\n"
        "`else\nalways @(posedge clk) q<=1;\n`endif\nendmodule\n")
    harness = source / "proof.sv"
    harness.write_text("`include \"settings.vh\"\nmodule proof import unit_pkg::*; (input clk);\n"
        "(* anyseq *) reg rst_n; reg valid=0; wire [1:0] q; unit dut(clk,rst_n,q);\n"
        "always @(posedge clk) begin valid<=1; if(valid && !$past(rst_n)) assert(q==`RESET_VALUE); end endmodule\n")
    path = (lambda p: p.name) if relative else str
    deck = source / "proof.sby"
    deck.write_text(emit_invariant_sby([path(package), path(rtl)], path(harness),
        "proof", [], [], prove_depth=8, bmc_depth=8, include_files=[str(header)]))
    original = deck.read_bytes(), harness.read_bytes(), rtl.read_bytes()
    output = tmp_path / "output"
    output.mkdir()
    result = formal(tmp_path, output, {"top": "system"}, Commands(output))
    assert result["metrics"]["unproved_required_properties"] == int(bad), result
    assert {row["status"] for row in result["native_steps"]
            if row["name"] in {"SymbiYosys.prove", "SymbiYosys.bmc"}} == {"FAIL" if bad else "PASS"}
    assert result["exit_code"] == (2 if bad else 0), result
    scope = json.loads((output / "formal_scope.json").read_text())
    assert scope["proves_declared_top"] is False
    assert (deck.read_bytes(), harness.read_bytes(), rtl.read_bytes()) == original
    retry = list(output.rglob("sv_frontend.sby"))
    assert len(retry) == 2
    for entry in retry:
        text = entry.read_text()
        assert "read_verilog -formal -sv" in text and "sv_frontend.v" in text
        assert "depth 8" in text and "abc " in text
        lowered = entry.with_suffix(".v").read_text()
        assert "(* anyseq *)" in lowered and "assert (q == 0)" in lowered


@pytest.mark.parametrize("case", ["missing_formal", "missing_formal_bad", "formal_good", "formal_bad", "missing_both", "temporal"])
def test_native_formal_preserves_supplied_formal_include_branch(tmp_path, case):
    if not all(shutil.which(name) for name in ("sby", "yosys", "sv2v", "yices-smt2")):
        pytest.skip("Native formal tools are required")
    from formal_property_run import emit_invariant_sby

    root = tmp_path / "phase2/stage1/formal"
    root.mkdir(parents=True)
    vendor = tmp_path / "input/vendor_rtl/includes"
    vendor.mkdir(parents=True)
    headers = {
        "checks.svh": '`ifdef SYNTHESIS\n`include "synthesis_checks.svh"\n'
                      '`else\n`include "formal_checks.svh"\n`endif\n',
        "synthesis_checks.svh": "`define LOCAL_CHECK\n",
    }
    if case == "formal_bad":
        headers["formal_checks.svh"] = "`define LOCAL_CHECK assert(1'b0);\n"
    elif case == "formal_good":
        headers["formal_checks.svh"] = "`define LOCAL_CHECK assert(q==q);\n"
    elif case == "temporal":
        headers["formal_checks.svh"] = "`define LOCAL_CHECK assert(q |-> q);\n"
    elif case == "missing_both":
        del headers["synthesis_checks.svh"]
    for name, text in headers.items():
        (vendor / name).write_text(text)
    package = root / "unit_pkg.sv"
    package.write_text("package unit_pkg; parameter RESET=0; endpackage\n")
    rtl = root / "unit.sv"
    rtl.write_text('`include "checks.svh"\n'
        "module unit import unit_pkg::*; (input clk,rst_n,output reg q);\n"
        f"always @(posedge clk) begin if(!rst_n) q<={int(case == 'missing_formal_bad')}; else q<=!q;\n"
        "`LOCAL_CHECK\nend endmodule\n")
    harness = root / "proof.sv"
    harness.write_text("module proof import unit_pkg::*; (input clk);\n"
        "(* anyseq *) reg rst_n; reg valid=0; wire q; unit dut(clk,rst_n,q);\n"
        "always @(posedge clk) begin valid<=1; if(valid && !$past(rst_n)) assert(q==RESET); end endmodule\n")
    deck = root / "proof.sby"
    deck.write_text(emit_invariant_sby([str(package), str(rtl)], str(harness),
        "proof", [], [], prove_depth=8, bmc_depth=8))
    originals = {p: p.read_bytes() for p in [package, rtl, harness, deck, *vendor.iterdir()]}
    output = tmp_path / "output"
    output.mkdir()
    commands = Commands(output)
    result = formal(tmp_path, output, {"top": "system"}, commands)
    rows = [r for r in result["native_steps"] if r["name"] in {"SymbiYosys.prove", "SymbiYosys.bmc"}]
    expected = "PASS" if case == "formal_good" else "FAIL" if case == "formal_bad" else "NOT_MEASURED"
    assert len(rows) == 2 and {r["status"] for r in rows} == {expected}, result
    assert {p: p.read_bytes() for p in originals} == originals
    scope = json.loads((output / "formal_scope.json").read_text())
    assert scope["proves_declared_top"] is False
    assert "frontend" not in scope and "frontend_notes" not in scope
    assert not any("-DSYNTHESIS" in r["command"] for r in commands.records), commands.records
    if case.startswith("missing_"):
        assert "unproved_required_properties" not in result["metrics"]
        assert "formal_checks.svh" in result["detail"], result
    for path in output.rglob("sv_frontend.v"):
        assert "assert (q ==" in path.read_text()


@pytest.mark.parametrize("case", ["good", "bad", "next", "temporal"])
def test_native_formal_retries_enum_methods_with_original_assertions(tmp_path, case):
    if not all(shutil.which(name) for name in ("sby", "yosys", "sv2v", "yices-smt2")):
        pytest.skip("Native formal tools are required")
    from formal_property_run import emit_invariant_sby

    root = tmp_path / "phase2/stage1/formal"
    root.mkdir(parents=True)
    package = root / "table_pkg.sv"
    package.write_text("package table_pkg; typedef enum logic[1:0] {S0,S1,S2} state_t;\n"
        "localparam state_t VALUES[3]='{S0,S1,S2}; endpackage\n")
    harness = root / "proof.sv"
    condition = "state[0] |=> $past(state[0])" if case == "temporal" else "invalid == (state!=S0)"
    function = ("bit found=0; int i=0;\n"
        "for(state_t value=value.first();i<value.num();i++,value=value.next()) found|=(sig===value);\n"
        "return !found;" if case=="next" else "state_t value; return sig!=value.first();")
    harness.write_text("module proof import table_pkg::*; (input clk,input state_t state);\n"
        "function automatic bit outside_table(state_t sig);\n"
        + function + "\nendfunction\n"
        f"wire invalid=outside_table(state) ^ 1'b{int(case == 'bad')};\n"
        f"`ifdef YOSYS\nalways @(posedge clk) assert({condition});\n"
        f"`else\nassert property(@(posedge clk) {condition});\n`endif\nendmodule\n")
    deck = root / "proof.sby"
    deck.write_text(emit_invariant_sby([str(package)], str(harness), "proof", [], [], prove_depth=8, bmc_depth=8))
    originals = {p:p.read_bytes() for p in (package,harness,deck)}
    output = tmp_path / "output"
    output.mkdir()
    commands = Commands(output)
    result = formal(tmp_path, output, {"top":"system"}, commands)
    rows = [r for r in result["native_steps"] if r["name"] in {"SymbiYosys.prove", "SymbiYosys.bmc"}]
    expected = "NOT_MEASURED" if case in {"next","temporal"} else "FAIL" if case == "bad" else "PASS"
    assert len(rows)==2 and {r["status"] for r in rows}=={expected},result
    assert {p:p.read_bytes() for p in originals}==originals
    retries = list(output.rglob("slang_frontend.sby"))
    assert len(retries)==2,result
    for retry in retries:
        text=retry.read_text()
        assert "--no-synthesis-define" in text and "--ignore-assertions" not in text
        assert "depth 8" in text and str(harness) in text
    assert not any("-DSYNTHESIS" in r["command"] for r in commands.records)
    if case=="temporal":
        assert "SVA" in result["detail"] or "sequence" in result["detail"].lower(),result
    if case=="next":
        assert "next" in result["detail"] and "unproved_required_properties" not in result["metrics"],result


def test_native_formal_keeps_an_uncompilable_sv_model_unmeasured(tmp_path):
    if not all(shutil.which(name) for name in ("sby", "yosys", "sv2v")):
        pytest.skip("Native formal tools are required")
    from formal_property_run import emit_invariant_sby

    source = tmp_path / "phase2/stage1/formal"
    source.mkdir(parents=True)
    harness = source / "proof.sv"
    harness.write_text("module proof(input clk); always @(posedge clk) assert( ; endmodule\n")
    deck = source / "proof.sby"
    deck.write_text(emit_invariant_sby([], str(harness), "proof", [], []))
    original = deck.read_bytes(), harness.read_bytes()
    output = tmp_path / "output"
    output.mkdir()
    result = formal(tmp_path, output, {}, Commands(output))
    assert "unproved_required_properties" not in result["metrics"], result
    assert all(row["status"] == "NOT_MEASURED" for row in result["native_steps"]), result
    assert (deck.read_bytes(), harness.read_bytes()) == original


@pytest.mark.parametrize("reset_value", [0, 1])
def test_native_formal_binds_retained_internal_state(tmp_path, reset_value):
    if not shutil.which("sby"):
        pytest.skip("Native SymbiYosys is required")
    from formal_property_run import emit_invariant_sby

    root = tmp_path / "phase2/stage1/formal"
    root.mkdir(parents=True)
    rtl = root / "unit.v"
    rtl.write_text("module unit(input clk, rst, a, output wire q); reg state; "
                   f"always @(posedge clk) if(rst) state <= 1'b{reset_value}; "
                   "else state <= a; assign q = state; endmodule\n")
    harness = root / "proof.sv"
    harness.write_text("module proof(input clk);\n"
                       "(* anyseq *) reg rst, a; wire q; unit dut(clk,rst,a,q);\n"
                       "// @observe observed = dut.state\n"
                       "(* keep *) wire observed;\n"
                       "reg valid=0; reg reset_q=0;\n"
                       "always @(posedge clk) begin valid<=1; reset_q<=rst;\n"
                       "if(valid && reset_q) assert(observed == 0); end\n"
                       "endmodule\n")
    task = root / "proof.sby"
    task.write_text(emit_invariant_sby([str(rtl)], str(harness), "proof", [], []))
    output = tmp_path / "output"
    output.mkdir()
    result = formal(tmp_path, output, {}, Commands(output))
    assert result["metrics"].get("unproved_required_properties") == reset_value, result
    assert [row["status"] for row in result["native_steps"] if not row["name"].endswith(".Cover")] == [
        "FAIL" if reset_value else "PASS"] * 2, result


@pytest.mark.parametrize("case", ["guard_reached", "guard_unreached", "cover_reached", "cover_unreached", "plain"])
def test_formal_runs_native_cover_targets_without_inventing_absent_counts(tmp_path, case):
    if not all(shutil.which(name) for name in ("sby", "yosys", "yices-smt2")):
        pytest.skip("Native SymbiYosys and Yosys cover tools are required")
    import flow_engine
    from formal_property_run import emit_invariant_sby

    source = tmp_path / "phase2/stage1/formal"
    source.mkdir(parents=True)
    harness = source / "proof.sv"
    unreachable = case.endswith("unreached")
    statements = "assume(!req);\n" if unreachable else ""
    statements += "if(req) assert(req);\n" if case.startswith("guard") else "assume(ack); assert(ack);\n"
    if case.startswith("cover"):
        statements += "cover(req);\n"
    harness.write_text("module proof(input clk); (* anyseq *) reg req, ack;\n"
                       "always @(posedge clk) begin\n" + statements + "end endmodule\n")
    deck = source / "proof.sby"
    deck.write_text(emit_invariant_sby([], str(harness), "proof", [], [], prove_depth=8, bmc_depth=8))
    original = harness.read_bytes(), deck.read_bytes()
    output = tmp_path / "output"
    output.mkdir()
    result = formal(tmp_path, output, {}, Commands(output))
    cover_rows = [row for row in result["native_steps"] if row["name"].endswith(".Cover")]
    assert result["metrics"]["unproved_required_properties"] == 0, result
    table = json.loads((Path(__file__).resolve().parents[2] / "flow/steps.json").read_text())
    row = next(row for row in table["steps"] if row["name"] == "formal_verification")
    measured = flow_engine.measure(row["checks"], result["metrics"], {}, {"always": True, "has_digital": True}, tmp_path)
    assert flow_engine.evaluate(flow_engine.ToolResult(**result), measured) == (
        "FAIL" if unreachable else "PASS"), result
    if case == "plain":
        assert cover_rows == []
        assert "vacuous_required_proofs" not in result["metrics"]
        assert "No native cover targets were present" in result["detail"]
    else:
        assert len(cover_rows) == 2, result
        assert {row["status"] for row in cover_rows} == ({"FAIL"} if unreachable else {"PASS"}), result
        assert result["metrics"]["vacuous_required_proofs"] == (2 if unreachable else 0)
    assert (harness.read_bytes(), deck.read_bytes()) == original


@pytest.mark.parametrize("unreachable", [False, True])
def test_formal_preserves_existing_native_cover_task(tmp_path, unreachable):
    if not all(shutil.which(name) for name in ("sby", "yosys", "yices-smt2")):
        pytest.skip("Native SymbiYosys and Yosys cover tools are required")
    source = tmp_path / "phase2/stage1/formal"
    source.mkdir(parents=True)
    harness = source / "proof.sv"
    harness.write_text("module proof(input clk); (* anyseq *) reg req, ack;\n"
        "always @(posedge clk) begin assume(ack); assert(ack);\n"
        + ("assume(!req);\n" if unreachable else "") + "cover(req); end endmodule\n")
    deck = source / "proof.sby"
    deck.write_text("[tasks]\nsafety\nreach\n[options]\nsafety: mode prove\nreach: mode cover\n"
        "depth 8\n[engines]\nsafety: abc pdr\nreach: smtbmc yices\n"
        "[script]\nread_verilog -formal -sv proof.sv\nprep -top proof\n[files]\nproof.sv\n")
    output = tmp_path / "output"
    output.mkdir()
    result = formal(tmp_path, output, {}, Commands(output))
    native = next(row for row in result["native_steps"] if row["name"] == "SymbiYosys.reach")
    assert native["status"] == ("FAIL" if unreachable else "PASS"), result
    assert result["metrics"]["unproved_required_properties"] == 0
    assert result["metrics"]["vacuous_required_proofs"] == (2 if unreachable else 0)


@pytest.mark.parametrize("declared_top,proves_top", [("system", False), ("leaf", True)])
def test_formal_scope_does_not_block_native_property_results(tmp_path, declared_top, proves_top):
    if not all(shutil.which(name) for name in ("sby", "yosys", "yices-smt2")):
        pytest.skip("Native SymbiYosys and Yosys cover tools are required")
    import flow_engine

    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    source = rtl / "unit.v"
    source.write_text("module system(input clk, rst_n, output q);\n"
        "leaf component(.clk(clk),.rst_n(rst_n),.q(q)); endmodule\n"
        "module leaf(input clk, rst_n, output reg q);\n"
        "always @(posedge clk) if(!rst_n) q<=0; else q<=~q; endmodule\n")
    output = tmp_path / "output"
    output.mkdir()
    result = formal(tmp_path, output, {"rtl": [str(source)], "top": declared_top}, Commands(output))
    scope = json.loads((output / "formal_scope.json").read_text())
    assert scope["declared_top"] == declared_top
    assert scope["proves_declared_top"] is proves_top
    assert scope["authoring"]["descended_to_leaf"] is not proves_top
    assert scope["authoring"]["proves_declared_top"] is proves_top
    assert {subject for task in scope["tasks"] for subject in task["subjects"]} == {"leaf"}
    assert f"proves_declared_top={str(proves_top).lower()}" in result["detail"]
    assert result["metrics"]["unproved_required_properties"] == 0, result
    assert flow_engine.evaluate(flow_engine.ToolResult(**result), [{"status": "PASS"}]) == "PASS", result


def partition(tmp_path, name, word, flags=""):
    listing = tmp_path / "partition.list"
    with listing.open("a") as stream:
        stream.write(f"unit {name} {flags} : y\n")
    status = tmp_path / "strategies" / name / "sat/status"
    status.parent.mkdir(parents=True)
    status.write_text(word + "\n")


@pytest.mark.parametrize("word,flags,expected,count", [
    ("PASS", "", "PASS", 0),
    ("FAIL", "", "FAIL", 1),
    ("UNKNOWN", "", "NOT_MEASURED", None),
    ("TIMEOUT", "", "NOT_MEASURED", None),
    ("PASS", "xbits", "PASS", 0),
    ("UNKNOWN", "xbits", "NOT_MEASURED", None),
    ("FAIL", "xbits", "FAIL", 1),
])
def test_native_partition_verdicts(tmp_path, word, flags, expected, count):
    partition(tmp_path, "output", word, flags)
    status, value, _, reports = eqy_partitions(tmp_path)
    assert (status, value) == (expected, count)
    assert all(path.is_file() for path in reports)


def test_missing_partition_status_never_becomes_zero(tmp_path):
    partition(tmp_path, "first", "PASS")
    with (tmp_path / "partition.list").open("a") as stream:
        stream.write("unit second : q\n")
    assert eqy_partitions(tmp_path)[:2] == ("NOT_MEASURED", None)
    assert eqy_partitions(tmp_path / "absent")[:2] == ("NOT_MEASURED", None)


def test_missing_proof_inputs_do_not_launch(tmp_path):
    result = eqy(tmp_path, tmp_path, {}, Commands(tmp_path), state={}, config={})
    assert result["ran"] is False
    assert result["metrics"] == {}


def test_eqy_default_strategies_have_no_runtime_cutoff(tmp_path, monkeypatch):
    gold, gate, liberty = [tmp_path / name for name in ("gold.v", "gate.v", "cells.lib")]
    gold.write_text("module unit(input a, output y); assign y=a; endmodule\n")
    gate.write_text(gold.read_text())
    liberty.write_text("library(neutral) {}\n")
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(liberty)]}}
    commands = Commands(tmp_path)
    monkeypatch.setattr(commands, "run", lambda argv: None)
    eqy(tmp_path, tmp_path, {}, commands, state={"nl": str(gate)}, config=config)
    script = (tmp_path / "equivalence.eqy").read_text()
    assert "timeout" not in script
    assert "[strategy sat]\nuse sat\ndepth 5\n" in script
    assert "[strategy pdr]\nuse sby\nengine abc pdr -rfi\n" in script


def reset_docs(project):
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({"clock_and_reset_waveform": {
        "clocks": [{"name": "clk", "edge": "posedge"}],
        "resets": [{"name": "rst_n", "polarity": "active_low", "sync": "synchronous"}]}}))


def test_ambiguous_reset_declarations_do_not_invent_a_boundary(tmp_path):
    reset_docs(tmp_path)
    assert reset_boundary(tmp_path) == (("clk", "posedge"), ("rst_n", "active_low"))
    (tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "resets": [{"name": "rst_n", "polarity": "active_high"}]}))
    assert reset_boundary(tmp_path) is None


def test_reset_domain_alias_does_not_merge_distinct_source_pins(tmp_path):
    reset_docs(tmp_path)
    docs = tmp_path / "phase1/generated_docs"
    path = docs / "L8_TIMING_WAVEFORM.json"
    document = json.loads(path.read_text())
    document["clock_and_reset_waveform"]["resets"][0].update(name="reset_domain", source_pin="rst_n")
    path.write_text(json.dumps(document))
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"reset_domains": [
        {"name": "reset_domain", "source_pin": "other_reset", "polarity": "active_low"}]}))
    assert reset_boundary(tmp_path) is None


@pytest.mark.parametrize("different", [False, True])
@pytest.mark.parametrize("domain_alias", [False, True])
def test_actual_eqy_uses_documented_reset_state(tmp_path, different, domain_alias):
    if not shutil.which("eqy"):
        pytest.skip("Native EQY is required")
    reset_docs(tmp_path)
    if domain_alias:
        docs = tmp_path / "phase1/generated_docs"
        path = docs / "L8_TIMING_WAVEFORM.json"
        document = json.loads(path.read_text())
        document["clock_and_reset_waveform"]["resets"][0].update(name="reset_domain", source_pin="rst_n")
        path.write_text(json.dumps(document))
        (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"reset_domains": [
            {"name": "rst_n", "source_pin": "rst_n", "polarity": "active_low"}]}))
    gold, gate, liberty = [tmp_path / name for name in ("gold.v", "gate.v", "cells.lib")]
    gold.write_text("module unit(input clk, rst_n, a, output reg q);\n"
                   "always @(posedge clk) if(!rst_n) q<=1; else q<=a; endmodule\n")
    value = "~a" if different else "a"
    gate.write_text("module unit(input clk, rst_n, a, output wire q);\n"
                   "reg inverted; assign q=~inverted;\n"
                   f"always @(posedge clk) if(!rst_n) inverted<=0; else inverted<=~({value}); endmodule\n")
    liberty.write_text("library(neutral) {}\n")
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(liberty)]}}
    result = eqy(tmp_path, tmp_path, {}, Commands(tmp_path), state={"nl": str(gate)}, config=config)
    assert result["metrics"].get("unproved_equivalence") == int(different), result
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result


@pytest.mark.parametrize("different", [False, True])
@pytest.mark.parametrize("physical", [None, "CORE SPACER", "CORE WELLTAP"])
def test_actual_eqy_detects_unequal_logic(tmp_path, different, physical):
    if not shutil.which("eqy"):
        pytest.skip("Native EQY is required")
    gold, gate, liberty = [tmp_path / name for name in ("gold.v", "gate.v", "cells.lib")]
    gold.write_text("module unit(input a, b, output y); assign y = a ^ b; endmodule\n")
    operation = "&" if different else "^"
    gate.write_text(f"module unit(input a, b, output y); assign y = a {operation} b; endmodule\n")
    liberty.write_text("library(neutral) {}\n")
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(liberty)]}}
    if physical:
        gate.write_text(gate.read_text().replace("endmodule", "\nFRAME frame();\nendmodule"))
        lef = tmp_path / "cells.lef"
        lef.write_text(f"MACRO FRAME\n CLASS {physical} ;\nEND FRAME\n")
        config["CELL_LEFS"] = {"typical": [str(lef)]}
    result = eqy(tmp_path, tmp_path, {"metric": "final_lec_unproved"}, Commands(tmp_path),
                 state={"nl": str(gate)}, config=config)
    assert result["ran"], result
    assert result["metrics"]["unproved_equivalence"] == int(different), result
    assert result["metrics"]["final_lec_unproved"] == int(different), result
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result
    assert not (tmp_path / "result.json").exists()


def test_actual_eqy_undecided_strategy_is_not_a_design_failure(tmp_path):
    if not shutil.which("eqy"):
        pytest.skip("Native EQY is required")
    reset_docs(tmp_path)
    gold, gate, liberty = [tmp_path / name for name in ("gold.v", "gate.v", "cells.lib")]
    for path, state, tap in ((gold, "gold_delay", 4), (gate, "gate_delay", 5)):
        path.write_text("module unit(input clk,rst_n,a,output q);\n"
            f"reg [5:0] {state}; always @(posedge clk) if(!rst_n) {state}<=0; "
            f"else {state} <= {{{state}[4:0],a}}; assign q={state}[{tap}];\nendmodule\n")
    liberty.write_text("library(neutral) {}\n")

    class OneFrame(Commands):
        def run(self, argv, cwd=None):
            if argv[0] == "eqy":
                script = Path(argv[-1])
                script.write_text(script.read_text().split("[strategy pdr]", 1)[0].replace("depth 5", "depth 1"))
            return super().run(argv, cwd)

    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(liberty)]}}
    result = eqy(tmp_path, tmp_path, {}, OneFrame(tmp_path), state={"nl": str(gate)}, config=config)
    assert result["native_steps"][0]["status"] == "NOT_MEASURED", result
    assert not result["metrics"], result
    assert "undecided" in result["detail"], result


def test_actual_eqy_native_strategy_timeout_is_unmeasured(tmp_path, monkeypatch):
    if not shutil.which("eqy"):
        pytest.skip("Native EQY is required")
    import librelane_eqy

    original_script = librelane_eqy.eqy_script

    def timed_script(*args, **kwargs):
        kwargs["timeout"] = 1
        return original_script(*args, **kwargs)

    monkeypatch.setattr(librelane_eqy, "eqy_script", timed_script)
    gold, gate, liberty = [tmp_path / name for name in ("gold.v", "gate.v", "cells.lib")]
    gold.write_text("module unit(input [19:0] a,b,output [39:0] y); assign y=a*b; endmodule\n")
    gate.write_text("module unit(input [19:0] a,b,output reg [39:0] y); integer i; "
                   "always @* begin y=0; for(i=0;i<20;i=i+1) "
                   "if(b[i]) y=y+({20'b0,a}<<i); end endmodule\n")
    liberty.write_text("library(neutral) {}\n")
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(liberty)]}}
    result = eqy(tmp_path, tmp_path, {}, Commands(tmp_path), state={"nl": str(gate)}, config=config)
    assert result["native_steps"][0]["status"] == "NOT_MEASURED", result
    assert not result["metrics"], result
    assert (tmp_path / "equivalence.eqy").read_text().count("timeout 1\n") == 2
    statuses = list((tmp_path / "scratch/strategies").glob("*/*/status"))
    assert any(path.read_text().strip() == "TIMEOUT" for path in statuses)



@pytest.mark.parametrize("model_key", ["PAD_LIBS", "EXTRA_LIBS", "PAD_VERILOG_MODELS", "EXTRA_VERILOG_MODELS", "LIBERTY_SIBLING", "SIMULATION_DIRECTIVES"])
@pytest.mark.parametrize("different", [False, True])
def test_eqy_preserves_chip_ports_and_declared_external_logic(tmp_path, model_key, different):
    if not shutil.which("eqy"):
        pytest.skip("Native EQY is required")
    gold, gate, core = [tmp_path / name for name in ("gold.v", "gate.v", "core.lib")]
    gold.write_text("module unit(input a, output y, output vss);\nwire x;\n"
        "PADIN input_cell(.PAD(a),.Y(x));\nPADGND supply_cell(.GND(vss));\nassign y=x; endmodule\n")
    gate.write_text(gold.read_text().replace("assign y=x", "assign y=~x" if different else "assign y=x"))
    core.write_text("library(neutral) {}\n")
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(core)]}}
    if model_key.endswith("LIBS") or model_key == "LIBERTY_SIBLING":
        model = tmp_path / "external.lib"
        model.write_text('library(external) {cell(PADIN) {pin(PAD) {direction:input;}'
            'pin(Y) {direction:output; function:"PAD";}} '
            'cell(PADGND) {pin(GND) {direction:output; function:"0";}}}\n')
        if model_key == "LIBERTY_SIBLING":
            directory = tmp_path / "pdk/lib"
            directory.mkdir(parents=True)
            moved = directory / model.name
            moved.write_text(model.read_text())
            model.unlink()
            model = moved
            models = tmp_path / "pdk/verilog"
            models.mkdir()
            (models / "models.v").write_text("module PADIN(input PAD,output Y); assign Y=PAD; endmodule\n"
                                            "module PADGND(output GND); assign GND=0; endmodule\n")
        config["PAD_LIBS" if model_key == "LIBERTY_SIBLING" else model_key] = (
            {"typical": [str(model)]} if model_key == "PAD_LIBS" else [str(model)])
    else:
        declared, model = tmp_path / "blackbox.v", tmp_path / "external_models.v"
        declared.write_text("(* blackbox *) module PADIN(input PAD, output Y); endmodule\n"
                           "(* blackbox *) module PADGND(output GND); endmodule\n")
        model.write_text("module PADIN(input PAD,output Y); assign Y=PAD; endmodule\n"
                         "module PADGND(output GND); assign GND=0; endmodule\n")
        if model_key == "SIMULATION_DIRECTIVES":
            model.write_text("`suppress_faults\n`enable_portfaults\n`delay_mode_path\n" + model.read_text())
        config["PAD_VERILOG_MODELS" if model_key == "SIMULATION_DIRECTIVES" else model_key] = [str(declared)]
    result = eqy(tmp_path, tmp_path, {}, Commands(tmp_path), state={"nl": str(gate)}, config=config)
    assert result["metrics"].get("unproved_equivalence") == int(different), result
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result
    for side in ("gold", "gate"):
        ports = json.loads((tmp_path / f"{side}.before-normalization.json").read_text())["modules"]["unit"]["ports"]
        assert set(ports) == {"a", "y", "vss"}


def test_eqy_missing_external_model_stays_unmeasured(tmp_path):
    if not shutil.which("eqy"):
        pytest.skip("Native EQY is required")
    gold, gate, core = [tmp_path / name for name in ("gold.v", "gate.v", "core.lib")]
    gold.write_text("module unit(input a, output y); PADIN input_cell(.PAD(a),.Y(y)); endmodule\n")
    gate.write_text(gold.read_text())
    core.write_text("library(neutral) {}\n")
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(core)]}}
    result = eqy(tmp_path, tmp_path, {}, Commands(tmp_path), state={"nl": str(gate)}, config=config)
    assert result["native_steps"][0]["status"] == "NOT_MEASURED", result
    assert not result["metrics"]


def test_eqy_core_uses_real_pdk_defaults_without_unused_io_models(tmp_path):
    if not shutil.which("eqy"):
        pytest.skip("Native EQY is required")
    pytest.importorskip("librelane")
    from librelane.flows import Flow
    gold = tmp_path / "gold.v"
    gold.write_text("module unit(input a, output y); assign y=a; endmodule\n")
    flow = Flow.factory.get("Classic")({"DESIGN_NAME": "unit", "PDK": "sky130A",
        "VERILOG_FILES": [str(gold)]}, design_dir=str(tmp_path))
    config = flow.config.to_raw_dict()
    assert config["PAD_LIBS"], "The real optional PDK IO defaults must be present in this control"
    result = eqy(tmp_path, tmp_path, {}, Commands(tmp_path), state={"nl": str(gold)}, config=config)
    assert result["native_steps"][0]["status"] == "PASS", result
    assert result["metrics"]["unproved_equivalence"] == 0
    script = (tmp_path / "equivalence.eqy").read_text()
    for paths in config["PAD_LIBS"].values():
        for path in paths:
            assert str(path) not in script


def test_eqy_reports_native_witness_interpreter_failure(tmp_path, monkeypatch):
    gold, core, witness = [tmp_path / name for name in ("gold.v", "core.lib", "yosys-witness")]
    gold.write_text("module unit(input a,output y);assign y=a;endmodule\n")
    core.write_text("library(neutral) {}\n")
    witness.write_text("#!/usr/bin/env python3\n")
    monkeypatch.setattr(shutil, "which", lambda name: str(witness))
    exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda path: False if str(path) == "/usr/bin/env" else exists(path))

    class NativeFailure(Commands):
        def run(self, argv, cwd=None):
            scratch = tmp_path / "scratch"
            scratch.mkdir()
            partition(scratch, "unit", "UNKNOWN")
            log = scratch / "strategies/unit/pdr/unit/logfile.txt"
            log.parent.mkdir(parents=True)
            log.write_text("yosys-witness: /usr/bin/env: bad interpreter: No such file or directory\n")
            self.records.append({"command": list(map(str, argv)), "exit_code": 1, "log": str(log)})
            return subprocess.CompletedProcess(argv, 1, "", "")

    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(core)]}}
    result = eqy(tmp_path, tmp_path, {}, NativeFailure(tmp_path), state={"nl": str(gold)}, config=config)
    assert not result["metrics"] and result["exit_code"] == 1
    assert "yosys-witness cannot execute" in result["detail"] and "/usr/bin/env" in result["detail"]


@pytest.mark.parametrize("change", ["none", "unused_models", "renamed_core_ports", "open_pad_pins", "unknown_core",
    "inline_unknown_core", "inline_z_core", "inline_undriven_core", "core", "core_pin", "terminal", "instance", "type",
    "direct_output", "direct_bad_output", "direct_unknown_output", "physical_corner", "physical_spacer",
    "physical_core_spacer", "physical_welltap", "welltap_with_rewire", "welltap_with_core",
    "unclassified_physical", "functional_filler_name", "physical_with_rewire"])
@pytest.mark.parametrize("package_output", [False, True])
@pytest.mark.parametrize("logical_pad_ports", [False, True])
def test_chip_eqy_separates_pad_wrapper_from_resettable_core(tmp_path, change, package_output, logical_pad_ports):
    if not shutil.which("eqy"):
        pytest.skip("Native EQY is required")
    reset_docs(tmp_path)
    core, gold, gate, cells = [tmp_path / name for name in
                              ("core.v", "wrapper.v", "gate.v", "cells.lib")]
    models = tmp_path / "models"
    models.mkdir()
    pads = models / "pads.v"
    core.write_text("module core(input clk,rst_n,a,output reg q);\n"
                    "always @(posedge clk) if(!rst_n) q<=1; else q<=a;\nendmodule\n")
    wrapper = ("module unit(inout clk,rst_n,a,q);\nwire ic,ir,ia,oq;\n"
               "INPAD pclk(.PAD(clk),.Y(ic));\nINPAD prst(.PAD(rst_n),.Y(ir));\n"
               "INPAD pa(.PAD(a),.Y(ia));\nOUTPAD pq(.A(oq),.PAD(q));\n")
    if package_output:
        wrapper = wrapper.replace("inout clk,rst_n,a,q", "input clk,rst_n,a,output q")
    if change in {"direct_output", "direct_bad_output", "direct_unknown_output"}:
        wrapper = wrapper.replace(");", ",output monitor);", 1)
    gold.write_text(wrapper + "core u_core(.clk(ic),.rst_n(ir),.a(ia),.q(oq));\nendmodule\n")
    if change == "renamed_core_ports":
        core.write_text(core.read_text().replace("clk", "core_clk").replace("rst_n", "core_rst_n"))
        gold.write_text(gold.read_text().replace(".clk(", ".core_clk(").replace(".rst_n(", ".core_rst_n("))
    behavior = "~ia" if change in {"core", "welltap_with_core"} else "ir" if change == "core_pin" else "ia"
    implemented = (wrapper + "reg state;\nassign oq=state;\n"
                   f"always @(posedge ic) if(!ir)state<=1;else state<={behavior};\nendmodule\n")
    if change == "terminal":
        implemented = implemented.replace(".PAD(a)", ".PAD(rst_n)")
    elif change == "instance":
        implemented = implemented.replace("INPAD pa(", "INPAD renamed(")
    elif change == "type":
        implemented = implemented.replace("INPAD pa(", "INPAD_ALT pa(")
    gate.write_text(implemented)
    if change in {"direct_output", "direct_bad_output", "direct_unknown_output"}:
        gold_value = "1'bx" if change == "direct_unknown_output" else "oq"
        gate_value = "~oq" if change == "direct_bad_output" else gold_value
        gold.write_text(gold.read_text().replace("endmodule", f"assign monitor={gold_value};\nendmodule"))
        gate.write_text(gate.read_text().replace("endmodule", f"assign monitor={gate_value};\nendmodule"))
    if change == "unknown_core":
        core.write_text("module core(input clk,rst_n,a,output q); assign q=1'bx; endmodule\n")
        gate.write_text(wrapper + "assign oq=1'bx;\nendmodule\n")
    elif change in {"inline_unknown_core", "inline_z_core", "inline_undriven_core"}:
        assignment = {"inline_unknown_core": "assign oq=1'bx;\n", "inline_z_core": "assign oq=1'bz;\n"}.get(change, "")
        gold.write_text(wrapper + assignment + "endmodule\n")
        gate.write_text(gold.read_text())
    cells.write_text("library(neutral) {}\n")
    pads.write_text("(* blackbox *)\nmodule INPAD(inout PAD,output Y); endmodule\n"
                    "(* blackbox *)\nmodule INPAD_ALT(inout PAD,output Y); endmodule\n"
                    "(* blackbox *)\nmodule OUTPAD(input A,inout PAD); endmodule\n")
    if change == "open_pad_pins":
        pads.write_text(pads.read_text().replace("inout PAD", "inout UNUSED,inout PAD"))
    if change == "unused_models":
        (models / "functional.v").write_text(
            "module INPAD(inout PAD,output Y); assign Y=PAD; endmodule\n"
            "module INPAD_ALT(inout PAD,output Y); assign Y=PAD; endmodule\n"
            "module OUTPAD(input A,inout PAD); assign PAD=A; endmodule\n"
            "module UNUSED(inout A,Y); rnmos (Y,A,1'b1); endmodule\n")
    if logical_pad_ports:
        pads.write_text(pads.read_text().replace("INPAD(inout PAD", "INPAD(input PAD")
            .replace("INPAD_ALT(inout PAD", "INPAD_ALT(input PAD")
            .replace("OUTPAD(input A,inout PAD", "OUTPAD(input A,output PAD"))
    physical = {"physical_corner": "ENDCAP TOPRIGHT", "physical_spacer": "PAD SPACER",
                "physical_core_spacer": "CORE SPACER", "physical_welltap": "CORE WELLTAP",
                "welltap_with_rewire": "CORE WELLTAP", "welltap_with_core": "CORE WELLTAP",
                "unclassified_physical": "PAD INOUT",
                "functional_filler_name": "PAD INPUT", "physical_with_rewire": "PAD SPACER"}
    if change in physical:
        lef = models / "cells.lef"
        lef.write_text(f"MACRO FRAME\n CLASS {physical[change]} ;\nEND FRAME\n")
        if change == "functional_filler_name":
            pads.write_text(pads.read_text() + "module FRAME(input D,output Y); assign Y=~D; endmodule\n")
            instance = "FRAME filler_corner(.D(a),.Y(unused_signal));"
        else:
            pads.write_text(pads.read_text() + "module FRAME(inout VDD,VSS); endmodule\n")
            instance = "FRAME inserted(.VDD(clk),.VSS(rst_n));"
        gate.write_text(gate.read_text().replace("endmodule", instance + "\nendmodule"))
        if change in {"physical_with_rewire", "welltap_with_rewire"}:
            gate.write_text(gate.read_text().replace(".PAD(a)", ".PAD(rst_n)"))
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(core), str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(cells)]},
              "PAD_VERILOG_MODELS": [str(pads)]}
    if change in physical:
        config["PAD_LEFS"] = [str(lef)]
    result = eqy(tmp_path, tmp_path, {}, Commands(tmp_path), state={"nl": str(gate)}, config=config)
    rows = {row["name"]: row["status"] for row in result.get("native_steps", [])}
    wrapper_failures = {"terminal", "instance", "type", "direct_bad_output", "unclassified_physical",
                        "functional_filler_name", "physical_with_rewire", "welltap_with_rewire"}
    assert rows.get("Yosys.Wrapper") == ("FAIL" if change in wrapper_failures else "PASS"), result
    if change in {"none", "unused_models", "renamed_core_ports", "open_pad_pins", "core", "core_pin", "direct_output",
                  "direct_bad_output", "physical_welltap", "welltap_with_core"}:
        assert rows.get("Yosys.EQY.Core") == ("FAIL" if change in {"core", "core_pin", "direct_bad_output", "welltap_with_core"} else "PASS"), result
    if change in {"unknown_core", "inline_unknown_core", "inline_z_core", "inline_undriven_core", "direct_unknown_output"}:
        assert rows.get("Yosys.EQY.Core") == "PASS" and result["exit_code"] == 0, result
        assert result["metrics"]["unproved_equivalence"] == 0, result
    elif change in {"none", "unused_models", "renamed_core_ports", "open_pad_pins", "direct_output",
                    "physical_corner", "physical_spacer", "physical_core_spacer", "physical_welltap"}:
        assert result["metrics"]["unproved_equivalence"] == 0, result
    else:
        assert result["metrics"].get("unproved_equivalence", 0) > 0, result
    for side in ("gold", "gate"):
        module = json.loads((tmp_path / "core" / (side + ".json")).read_text())["modules"]["unit"]
        assert not any(cell["type"] in {"INPAD", "INPAD_ALT", "OUTPAD"} for cell in module["cells"].values())



@pytest.mark.parametrize("change", ["none", "core", "signal", "rail", "missing_pad", "no_power_view", "rail_logic",
                                    "rail_state", "paired_rail_state"])
@pytest.mark.parametrize("slang", [False, True])
def test_chip_eqy_uses_native_power_view_and_keeps_supply_checks(tmp_path, change, slang):
    if not shutil.which("eqy"):
        pytest.skip("Native EQY is required")
    if slang and not shutil.which("slang"):
        pytest.skip("Native Slang is required")
    models, gold, gate, power, liberty, lef = [tmp_path / name for name in
        ("pads.v", "gold.v", "gate.v", "power.v", "cells.lib", "pads.lef")]
    models.write_text("(* blackbox *) module INPAD(input PAD,PD,PU,output Y,inout VP,VN); endmodule\n"
        "(* blackbox *) module OUTPAD(input A,output PAD,inout VP,VN); endmodule\n"
        "(* blackbox *) module SUPPLY(inout VP,VN); endmodule\n")
    liberty.write_text('library(neutral) {\ncell(TIELOW) {pin(Y) {direction: output; function: "0";}}\n'
        'cell(TIEHIGH) {pin(Y) {direction: output; function: "1";}}\n'
        'cell(BUF) {pin(A) {direction: input;} pin(Y) {direction: output; function: "A";}}\n}\n')
    lef.write_text("\n".join(f"MACRO {master}\n CLASS {'PAD INOUT' if master in {'INPAD', 'OUTPAD', 'SUPPLY'} else 'CORE'} ;\n"
        " PIN VP\n  DIRECTION INOUT ;\n  USE POWER ;\n END VP\n"
        " PIN VN\n  DIRECTION INOUT ;\n  USE GROUND ;\n END VN\n"
        f"END {master}\n" for master in ("INPAD", "OUTPAD", "SUPPLY", "TIELOW", "TIEHIGH", "BUF")))
    gold.write_text("module unit(input a,b,output y,inout supply_high,supply_low); wire internal,core_out,high,low;\n"
        "TIELOW t0(.Y(low));\nTIEHIGH t1(.Y(high));\nBUF core_gate(.A(internal),.Y(core_out));\n"
        "INPAD pi(.PAD(a),.PD(low),.PU(high),.Y(internal),.VP(supply_high),.VN(supply_low));\n"
        + ("OUTPAD po(.A(core_out & supply_high)," if change == "rail_logic" else "OUTPAD po(.A(core_out),")
        + ".PAD(y),.VP(supply_high),.VN(supply_low));\n"
        "SUPPLY pv(.VP(supply_high),.VN(supply_low)); endmodule\n")
    operation = "~internal" if change == "core" else "internal"
    gate.write_text("module unit(input a,b,output y); wire internal,core_out,high,low;\n"
        f"TIELOW t0(.Y(low));\nTIEHIGH t1(.Y(high));\nBUF core_gate(.A({operation}),.Y(core_out));\n"
        "INPAD pi(.PAD(a),.PD(low),.PU(high),.Y(internal)); OUTPAD po(.A(core_out),.PAD(y));\n"
        "SUPPLY pv(); endmodule\n")
    high, low = ("supply_low", "supply_high") if change == "rail" else ("supply_high", "supply_low")
    power.write_text("module unit(input a,b,output y,inout supply_high,supply_low); wire internal,core_out,high,low;\n"
        "TIELOW t0(.Y(low),.VP(supply_high),.VN(supply_low));\n"
        "TIEHIGH t1(.Y(high),.VP(supply_high),.VN(supply_low));\n"
        f"BUF core_gate(.A({operation}),.Y(core_out),.VP(supply_high),.VN(supply_low));\n"
        f"INPAD pi(.PAD({'b' if change == 'signal' else 'a'}),.PD(low),.PU(high),.Y(internal),.VP({high}),.VN({low}));\n"
        "OUTPAD po(.A(core_out),.PAD(y),.VP(supply_high),.VN(supply_low));\n"
        + ("" if change == "missing_pad" else "SUPPLY pv(.VP(supply_high),.VN(supply_low)); ")
        + "endmodule\n")
    if change in {"rail_state", "paired_rail_state"}:
        for path in (gold, gate, power):
            expression = "internal & supply_high" if path == gold or (
                path == power and change == "paired_rail_state") else "internal"
            path.write_text(path.read_text().replace("input a,b,", "input a,b,c,")
                .replace("wire internal,core_out,high,low;", "wire internal,core_out,high,low;\n"
                         f"reg sampled; always @(posedge c) sampled <= {expression};\n")
                .replace("BUF core_gate(.A(internal)", "BUF core_gate(.A(sampled)"))
    state = {"nl": str(gate)}
    if change != "no_power_view":
        state["pnl"] = str(power)
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)],
              "DEFAULT_CORNER": "typical", "LIB": {"typical": [str(liberty)]},
              "PAD_VERILOG_MODELS": [str(models)], "PAD_LEFS": [str(lef)], "USE_SLANG": slang}
    result = eqy(tmp_path, tmp_path, {}, Commands(tmp_path), state=state, config=config)
    rows = {row["name"]: row["status"] for row in result.get("native_steps", [])}
    assert rows.get("Yosys.Wrapper") == ("PASS" if change in {"none", "rail_state", "paired_rail_state"} else "FAIL"), result
    if change in {"none", "core", "no_power_view"}:
        assert rows.get("Yosys.EQY.Core") == ("FAIL" if change == "core" else "PASS"), result
    assert (result["metrics"].get("unproved_equivalence") == 0) is (change in {"none", "paired_rail_state"}), result
    if change in {"rail_state", "paired_rail_state"}:
        assert (rows.get("Yosys.EQY.Core") == "PASS") is (change == "paired_rail_state"), result
    if change == "none":
        for side in ("gold", "gate"):
            ports = json.loads((tmp_path / "core" / (side + ".json")).read_text())["modules"]["unit"]["ports"]
            assert not any(name in {"supply_high", "supply_low"} or name.endswith((".VP", ".VN")) for name in ports)


@pytest.mark.parametrize("direct_output", [False, True])
def test_pad_boundary_removes_logical_package_outputs_and_keeps_core_outputs(tmp_path, direct_output):
    if not shutil.which("yosys"):
        pytest.skip("Native Yosys is required")
    from flow_native_verification import eqy_pad_views

    models, source = tmp_path / "pads.v", tmp_path / "unit.v"
    models.write_text("(* blackbox *) module INPAD(input PAD,output Y); endmodule\n"
                      "(* blackbox *) module OUTPAD(input A,output PAD); endmodule\n")
    ports = "input [6:0] a,output [6:0] y,inout vdd,vss"
    if direct_output:
        ports += ",output monitor"
    source.write_text(f"module unit({ports});\nwire [6:0] internal;\n"
        + "\n".join(f"INPAD pi{i}(.PAD(a[{i}]),.Y(internal[{i}])); "
                      f"OUTPAD po{i}(.A(~internal[{i}]),.PAD(y[{i}]));" for i in range(7))
        + ("\nassign monitor=internal[0];" if direct_output else "") + "\nendmodule\n")
    script = (f"[gold]\nread_verilog -sv {source}\n[gate]\nread_verilog -sv {source}\n"
              "[script]\nproc\n")
    result, count, _, _ = eqy_pad_views(tmp_path, "unit", script,
        {"liberty": [], "types": {"INPAD", "OUTPAD"}, "defines": [], "include_dirs": []},
        [models], Commands(tmp_path), None)
    assert result is not None and count == 0
    for side in ("gold", "gate"):
        module = json.loads((tmp_path / "core" / (side + ".json")).read_text())["modules"]["unit"]
        assert "y" not in module["ports"] or module["ports"]["y"]["direction"] != "output"
        assert (module["ports"].get("monitor", {}).get("direction") == "output") == direct_output
        assert not any(cell["type"] in {"INPAD", "OUTPAD"} for cell in module["cells"].values())



@pytest.mark.parametrize("different", [False, True])
def test_power_pad_boundary_keeps_paired_interfaces_consistent(tmp_path, different):
    if not shutil.which("eqy"):
        pytest.skip("Native EQY is required")
    gold, gate, liberty, model = [tmp_path / name for name in ("gold.v", "gate.v", "cells.lib", "pads.v")]
    interface = "module unit(input a,output y,output \\VDD! );\nPADGND supply(.GND(\\VDD! ));\n"
    gold.write_text(interface + "assign y=a; endmodule\n")
    gate.write_text(interface + "reg unused; always @(posedge a) unused <= \\VDD! ; "
        + "assign y=" + ("~a" if different else "a") + "; endmodule\n")
    liberty.write_text("library(neutral) {}\n")
    model.write_text("(* blackbox *) module PADGND(inout GND); endmodule\n")
    config = {"DESIGN_NAME": "unit", "VERILOG_FILES": [str(gold)], "DEFAULT_CORNER": "typical",
              "LIB": {"typical": [str(liberty)]}, "PAD_VERILOG_MODELS": [str(model)]}
    result = eqy(tmp_path, tmp_path, {}, Commands(tmp_path), state={"nl": str(gate)}, config=config)
    assert result["metrics"]["unproved_equivalence"] == int(different), result
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result
    interfaces = []
    for side in ("gold", "gate"):
        ports = json.loads((tmp_path / "core" / (side + ".json")).read_text())["modules"]["unit"]["ports"]
        interfaces.append({name: port["direction"] for name, port in ports.items()})
    assert interfaces[0] == interfaces[1]
    assert interfaces[0]["VDD!"] == "output"


def test_xor_reuses_native_state_number(tmp_path):
    state = SimpleNamespace(metrics={"design__xor_difference__count": 3})
    commands = Commands(tmp_path)
    result = xor(tmp_path, tmp_path, {}, commands,
                 state=state, config={})
    assert result["ran"] and result["metrics"]["design__xor_difference__count"] == 3
    assert not commands.records and result["tool_seconds"] == 0


def test_absent_xor_views_are_not_a_zero_count(tmp_path):
    class EmptyState(dict):
        metrics = {}
    result = xor(tmp_path, tmp_path, {}, Commands(tmp_path), state=EmptyState(), config={})
    assert not result["ran"] and not result["metrics"]


def test_stream_xor_does_not_satisfy_finished_geometry(tmp_path):
    class FinishedState(dict):
        metrics = {"design__xor_difference__count": 0}
    state = FinishedState({"gds": "finished.gds", "mag_gds": "before.gds"})
    result = xor(tmp_path, tmp_path, {"metric": "unexplained_stream_xor"}, Commands(tmp_path),
                 state=state, config={"PRIMARY_GDSII_STREAMOUT_TOOL": "magic"})
    assert not result["ran"] and not result["metrics"]
    assert "core rectangle" in result["detail"]


@pytest.mark.parametrize("different", [False, True])
@pytest.mark.parametrize("sealed", [False, True])
def test_finished_geometry_uses_current_gds(tmp_path, different, sealed):
    pytest.importorskip("librelane")
    pya = pytest.importorskip("klayout.db")
    from librelane.common import Path as NativePath
    from librelane.config import Config
    from librelane.state import State
    from librelane_plugins.librelane_plugin_vibeic.signoff import FinishingXOR
    paths = []
    for side, edge in (("before", 100), ("finished", 99 if different else 100)):
        layout = pya.Layout()
        cell = layout.create_cell("unit")
        cell.shapes(layout.layer(1, 0)).insert(pya.Box(0, 0, edge, 100))
        path = tmp_path / f"{side}.gds"
        layout.write(str(path))
        paths.append(NativePath(str(path)))
    metrics = {"design__xor_difference__count": 0, "design__core__bbox": "0 0 1 1"}
    if sealed:
        metrics["design__seal_ring__verified"] = 1
        seal_step = tmp_path / "steps/seal_ring_and_die_identification"
        seal_step.mkdir(parents=True)
        (seal_step / "state_out.json").write_text(State({"gds": paths[0]}).dumps())
    state = State({"mag_gds": paths[0], "gds": paths[1]}, metrics=metrics)
    config, _ = Config.load({"DESIGN_NAME": "unit", "PDK": "sky130A",
        "VIBEIC_FINISHING_PRE_GDS": str(paths[0])},
        FinishingXOR.get_all_config_variables(), design_dir=str(tmp_path))
    config = config.copy(PRIMARY_GDSII_STREAMOUT_TOOL="magic")
    result = xor(tmp_path, tmp_path / "native", {"metric": "unexplained_stream_xor"}, Commands(tmp_path),
                 state=state, config=config)
    assert result["metrics"].get("unexplained_stream_xor") == int(different), result
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result


@pytest.mark.parametrize("different", [False, True])
def test_original_klayout_xor_invocation(tmp_path, different):
    pytest.importorskip("librelane")
    pya = pytest.importorskip("klayout.db")
    from librelane.config import Config
    from librelane.common import Path as NativePath
    from librelane.state import State
    from librelane.steps.klayout import XOR
    if not shutil.which("klayout"):
        pytest.skip("Native KLayout is required")
    paths = []
    for side, edge in (("a", 100), ("b", 101 if different else 100)):
        layout = pya.Layout()
        cell = layout.create_cell("unit")
        cell.shapes(layout.layer(1, 0)).insert(pya.Box(0, 0, edge, 100))
        path = tmp_path / f"{side}.gds"
        layout.write(str(path))
        paths.append(NativePath(str(path)))
    config, _ = Config.load({"DESIGN_NAME": "unit", "PDK": "sky130A"},
                            XOR.get_all_config_variables(), design_dir=str(tmp_path))
    state = State({"mag_gds": paths[0], "klayout_gds": paths[1]})
    result = xor(tmp_path, tmp_path / "native", {}, Commands(tmp_path),
                 state=state, config=config)
    assert result["ran"], result
    assert result["metrics"]["design__xor_difference__count"] == int(different), result
    assert result["native_steps"][0]["status"] == ("FAIL" if different else "PASS"), result


def gls_fixture(project, *, different=False, annotated=True, cocotb=False):
    project.mkdir(parents=True, exist_ok=True)
    netlist, model, sdf = [project / name for name in ("netlist.v", "model.v", "timing.sdf")]
    operation = "~a" if different else "a"
    model.write_text("`timescale 1ns/1ps\nmodule delay_cell(input a, output y);\n"
                     f"assign y={operation}; specify (a=>y)=(1,1); endspecify endmodule\n")
    netlist.write_text("module unit(input a, output y);\ndelay_cell gate(.a(a),.y(y));\nendmodule\n")
    delays = "(DELAY (ABSOLUTE (IOPATH a y (1:1:1) (1:1:1))))" if annotated else ""
    connection = ('(CELL (CELLTYPE "unit") (INSTANCE) (DELAY (ABSOLUTE '
                  '(INTERCONNECT a gate/a (0.5:0.5:0.5)))))\n') if annotated else ""
    sdf.write_text('(DELAYFILE (SDFVERSION "3.0") (DESIGN "unit") (DIVIDER /) (TIMESCALE 1ns)\n'
                   + connection + f'(CELL (CELLTYPE "delay_cell") (INSTANCE gate) {delays}))\n')
    benches = project / "phase2/stage1/sim"
    benches.mkdir(parents=True)
    if cocotb:
        tb = benches / "tb_unit.py"
        tb.write_text("import cocotb\nfrom cocotb.triggers import Timer\n"
            "@cocotb.test()\nasync def function(dut):\n"
            "    dut.a.value=0\n    await Timer(3,unit='ns')\n"
            "    dut.a.value=1\n    await Timer(3,unit='ns')\n    assert int(dut.y.value)==1\n")
    else:
        tb = benches / "tb_unit.v"
        tb.write_text("`timescale 1ns/1ps\nmodule tb_unit;\nreg a=0; wire y;\nunit dut(a,y);\n"
            "initial begin #5; a=1; #5;\n"
            "if(y!==1) begin $display(\"ORACLE_TB_DONE pass=0/1\"); $fatal(1,\"functional mismatch\"); end\n"
            "$display(\"ORACLE_TB_DONE pass=1/1\"); $finish; end\nendmodule\n")
    class NativeState(dict):
        metrics = {}
    state = NativeState(nl=str(netlist), sdf={"typical": str(sdf)})
    config = {"DESIGN_NAME": "unit", "CELL_VERILOG_MODELS": [str(model)]}
    return state, config


@pytest.mark.parametrize("different,annotated,expected", [
    (False, True, "PASS"), (True, True, "FAIL"), (False, False, "NOT_MEASURED"),
])
@pytest.mark.parametrize("cocotb", [False, True])
def test_native_gls_annotations_and_function(tmp_path, different, annotated, expected, cocotb):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    if cocotb and not shutil.which("cocotb-config"):
        pytest.skip("Native cocotb is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project, different=different, annotated=annotated, cocotb=cocotb)
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert result["native_steps"][0]["status"] == expected, result
    if expected == "NOT_MEASURED":
        assert "gls_failures" not in result["metrics"]
    else:
        assert result["metrics"]["gls_failures"] == int(different), result
        assert result["metrics"]["final_gls_function_timing_errors"] == int(different), result
        assert result["metrics"]["sdf_delays_applied"] > 0, result
    assert not (directory / "result.json").exists()


def test_gls_names_missing_native_inputs(tmp_path):
    result = gls(tmp_path, tmp_path, {}, Commands(tmp_path), state={}, config={})
    assert not result["ran"] and "State netlist" in result["detail"]


def declared_vector_chip_fixture(project, *, different=False):
    from testbench_gen import emit_unit_tbs

    state, config = gls_fixture(project, different=different)
    rtl = project / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "core_unit.v").write_text(
        "module core_unit(input clk,rst_n,input [7:0] message,output [7:0] digest); "
        "assign digest=message; endmodule\n")
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    cases = [{"name": f"vector_{index}", "kind": "known_answer_vector",
              "inputs": {"message": value}, "expected_outputs": {"digest": value},
              "citation": "Input vector table", "source": "input_document",
              "evidence": "input/docs/spec.md"}
             for index, value in enumerate(("00", "a5", "5a", "ff"))]
    (docs / "L10_TEST_CASES.json").write_text(json.dumps({"test_cases": cases}))
    assert emit_unit_tbs(project, top="core_unit", scaffold=False, case_stated=True) == 4
    benches = sorted((project / "phase2/stage1/sim/tb").glob("*.v"))
    model = Path(config["CELL_VERILOG_MODELS"][0])
    model.write_text(model.read_text() + "module clock_cell(input a,output y); "
        "assign y=a; specify (a=>y)=(1,1); endspecify endmodule\n")
    Path(state["nl"]).write_text(
        "module chip_unit(input clk,rst_n,input [7:0] message,output [7:0] digest);\n"
        "wire delayed_clk; reg [7:0] stored; clock_cell clock_input(.a(clk),.y(delayed_clk));\n"
        "always @(posedge delayed_clk) stored<=message;\n"
        + "\n".join(f"delay_cell gate{bit}(.a(stored[{bit}]),.y(digest[{bit}]));" for bit in range(8))
        + "\nendmodule\n")
    Path(state["sdf"]["typical"]).write_text(
        '(DELAYFILE (SDFVERSION "3.0") (DESIGN "chip_unit") (DIVIDER /) (TIMESCALE 1ns)\n'
        '(CELL (CELLTYPE "chip_unit") (INSTANCE) (DELAY (ABSOLUTE '
        '(INTERCONNECT clk clock_input/a (0.5:0.5:0.5)))))\n'
        '(CELL (CELLTYPE "clock_cell") (INSTANCE clock_input) '
        '(DELAY (ABSOLUTE (IOPATH a y (1:1:1) (1:1:1)))))\n'
        + "\n".join(f'(CELL (CELLTYPE "delay_cell") (INSTANCE gate{bit}) '
                       '(DELAY (ABSOLUTE (IOPATH a y (1:1:1) (1:1:1)))))' for bit in range(8)) + ")\n")
    sdc = project / "timing.sdc"
    sdc.write_text("set_units -time ns\ncreate_clock -period 24 [get_ports clk]\n")
    state["sdc"] = str(sdc)
    config["DESIGN_NAME"] = "chip_unit"
    return state, config, benches


@pytest.mark.parametrize("different", [False, True])
def test_gls_regenerates_declared_vectors_on_native_chip_ports(tmp_path, different):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config, benches = declared_vector_chip_fixture(project, different=different)
    original = {path: path.read_bytes() for path in benches}
    result = gls(project, directory, {"testbenches": [str(path) for path in benches]},
                 Commands(directory), state=state, config=config)
    assert len(result["native_steps"]) == 4, result
    assert {row["status"] for row in result["native_steps"]} == ({"FAIL"} if different else {"PASS"}), result
    assert all(row["sdf_delays_applied"] > 0 and row["sdf_errors"] == 0 for row in result["native_steps"]), result
    assert (result["metrics"]["gls_failures"] > 0) is different, result
    assert {path: path.read_bytes() for path in benches} == original
    assert all("chip_unit dut" in Path(row["generated_testbench"]).read_text()
               for row in result["native_steps"]), result
    assert all("always #12 clk = ~clk;" in path.read_text()
               for path in directory.glob("corner_*/annotated_tb.v"))


def test_gls_keeps_typed_vector_refusal_instead_of_boot_fallback(tmp_path):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    from testbench_gen import emit_unit_tbs

    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config, benches = declared_vector_chip_fixture(project)
    rtl = project / "phase2/stage1/rtl/core_unit.v"
    rtl.write_text("module core_unit(input clk,rst_n,input [7:0] message,"
                   "output [7:0] digest,ciphertext,output req_o); "
                   "assign digest=message; assign ciphertext=1; assign req_o=1; endmodule\n")
    l10 = project / "phase1/generated_docs/L10_TEST_CASES.json"
    document = json.loads(l10.read_text())
    document["test_cases"][0].update(
        stimulus="reset release, first bus access within 2 cycles",
        expected="first bus access within 2 cycles")
    document["test_cases"][0]["expected_outputs"]["ciphertext"] = "01"
    l10.write_text(json.dumps(document))
    assert emit_unit_tbs(project, top="core_unit", scaffold=False, case_stated=True) == 4
    bench = benches[0]
    original = {path: path.read_bytes() for path in benches}
    assert "EXPECTED_DIGEST" in bench.read_text() and "EXPECTED_CIPHERTEXT" in bench.read_text()
    for different in (False, True):
        source, executable = directory / f"core_{different}.v", directory / f"core_{different}.vvp"
        source.write_text(rtl.read_text().replace("assign digest=message", "assign digest=8'hff")
                          if different else rtl.read_text())
        compiled = subprocess.run(["iverilog", "-g2012", "-s", bench.stem, "-o", str(executable),
                                   str(bench), str(source)], capture_output=True, text=True)
        assert compiled.returncode == 0, compiled.stderr
        completed = subprocess.run(["vvp", str(executable)], capture_output=True, text=True)
        assert bool(completed.returncode) is different, (completed.stdout, completed.stderr)
    netlist = Path(state["nl"])
    netlist.write_text("module chip_unit(input clk,rst_n,input [7:0] message,"
        "output [7:0] digest,output req_o);\nwire delayed_clk; wire [7:0] raw=8'hff; "
        "clock_cell clock_input(.a(clk),.y(delayed_clk)); assign req_o=1;\n"
        + "\n".join(f"delay_cell gate{bit}(.a(raw[{bit}]),.y(digest[{bit}]));" for bit in range(8))
        + "\nendmodule\n")
    result = gls(project, directory, {"testbenches": [str(bench)]},
                 Commands(directory), state=state, config=config)
    row = result["native_steps"][0]
    assert row["status"] == "NOT_MEASURED" and not row["ran"], result
    assert "ciphertext" in row["detail"], result
    assert "gls_failures" not in result["metrics"], result
    assert {path: path.read_bytes() for path in benches} == original


@pytest.mark.parametrize("source", ["authored", "delivered", "input_delivered", "unbound", "unknown_case"])
def test_gls_does_not_replace_unavailable_core_checks(tmp_path, source):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config, benches = declared_vector_chip_fixture(project)
    bench = benches[0]
    if source == "authored":
        bench.write_text("".join(bench.read_text().splitlines(keepends=True)[1:]))
    elif source == "delivered":
        bench.write_text("// DELIVERED: input/sim/tb/vector_0.v\n" + bench.read_text())
    elif source == "input_delivered":
        delivered = project / "input/sim/tb/vector_0.v"
        delivered.parent.mkdir(parents=True)
        delivered.write_bytes(bench.read_bytes())
    else:
        path = project / "phase1/generated_docs/L10_TEST_CASES.json"
        document = json.loads(path.read_text())
        if source == "unbound":
            document["test_cases"][0]["expected_outputs"] = {"unavailable_result": "00"}
        else:
            document["test_cases"] = document["test_cases"][1:]
        path.write_text(json.dumps(document))
    original = bench.read_bytes()
    result = gls(project, directory, {"testbenches": [str(bench)]},
                 Commands(directory), state=state, config=config)
    assert result["native_steps"][0]["status"] == "NOT_MEASURED", result
    assert not result["native_steps"][0]["ran"]
    assert "gls_failures" not in result["metrics"]
    assert bench.read_bytes() == original


@pytest.mark.parametrize("different", [False, True])
def test_gls_regenerates_declared_register_bus_vectors(tmp_path, different):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    from testbench_gen import emit_unit_tbs

    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project, different=different)
    rtl = project / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    header = ("(input clk,reset_n,cs,we,input [7:0] address,input [31:0] write_data,"
              "output [31:0] read_data,output error)")
    (rtl / "core_unit.v").write_text("module core_unit" + header + "; endmodule\n")
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    registers = [{"name": "CTRL", "address": "0x08", "access": "R/W", "fields": [
        {"field_name": "INIT", "lsb": 0, "bits": "0"},
        {"field_name": "NEXT", "lsb": 1, "bits": "1"}]},
        {"name": "STATUS", "address": "0x09", "access": "R", "fields": [
        {"field_name": "READY", "lsb": 0, "bits": "0"},
        {"field_name": "VALID", "lsb": 1, "bits": "1"}]}]
    registers.extend({"name": f"BLOCK{index}", "address": hex(16 + index), "access": "W"}
                     for index in range(16))
    registers.extend({"name": f"DIGEST{index}", "address": hex(32 + index), "access": "R"}
                     for index in range(8))
    (docs / "L4_REGMAP.json").write_text(json.dumps({"registers": registers}))
    case = {"name": "bus_vector", "kind": "known_answer_vector",
            "inputs": {"message": "01"}, "expected_outputs": {"digest": "a5" * 32},
            "citation": "Input vector table", "source": "input_document",
            "evidence": "input/docs/spec.md"}
    (docs / "L10_TEST_CASES.json").write_text(json.dumps({"test_cases": [case]}))
    assert emit_unit_tbs(project, top="core_unit", scaffold=False, case_stated=True) == 1
    bench = project / "phase2/stage1/sim/tb/bus_vector.v"
    original = bench.read_bytes()
    model = Path(config["CELL_VERILOG_MODELS"][0])
    model.write_text(model.read_text() + "module clock_cell(input a,output y); "
        "assign y=a; specify (a=>y)=(1,1); endspecify endmodule\n")
    Path(state["nl"]).write_text("module chip_unit" + header + ";\n"
        "wire delayed_clk; reg [31:0] first_word,raw; reg valid;\n"
        "clock_cell clock_input(.a(clk),.y(delayed_clk)); assign error=0;\n"
        "always @(posedge delayed_clk or negedge reset_n)\n"
        "if(!reset_n) begin first_word<=0;valid<=0;end else if(cs&&we) begin\n"
        "if(address==16) first_word<=write_data;\n"
        "if(address==8&&write_data[0]) valid<=first_word==32'h01800000; end\n"
        "always @* begin raw=0; if(address==9) raw={30'b0,valid,1'b1};\n"
        "else if(address>=32&&address<40) raw=32'ha5a5a5a5;end\n"
        + "\n".join(f"delay_cell gate{bit}(.a(raw[{bit}]),.y(read_data[{bit}]));" for bit in range(32))
        + "\nendmodule\n")
    Path(state["sdf"]["typical"]).write_text(
        '(DELAYFILE (SDFVERSION "3.0") (DESIGN "chip_unit") (DIVIDER /) (TIMESCALE 1ns)\n'
        '(CELL (CELLTYPE "chip_unit") (INSTANCE) (DELAY (ABSOLUTE '
        '(INTERCONNECT clk clock_input/a (0.5:0.5:0.5)))))\n'
        '(CELL (CELLTYPE "clock_cell") (INSTANCE clock_input) '
        '(DELAY (ABSOLUTE (IOPATH a y (1:1:1) (1:1:1)))))\n'
        + "\n".join(f'(CELL (CELLTYPE "delay_cell") (INSTANCE gate{bit}) '
                       '(DELAY (ABSOLUTE (IOPATH a y (1:1:1) (1:1:1)))))' for bit in range(32)) + ")\n")
    sdc = project / "timing.sdc"
    sdc.write_text("set_units -time ns\ncreate_clock -period 24 [get_ports clk]\n")
    state["sdc"] = str(sdc)
    config["DESIGN_NAME"] = "chip_unit"
    result = gls(project, directory, {"testbenches": [str(bench)]},
                 Commands(directory), state=state, config=config)
    native = result["native_steps"][0]
    assert native["status"] == ("FAIL" if different else "PASS"), result
    assert native["sdf_delays_applied"] > 0 and native["sdf_errors"] == 0, result
    assert (result["metrics"]["gls_failures"] > 0) is different
    assert bench.read_bytes() == original
    assert "always #12 clk = ~clk;" in (directory / "corner_1/annotated_tb.v").read_text()


def test_gls_replays_every_state_corner(tmp_path):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project)
    state["sdf"]["second_corner"] = state["sdf"]["typical"]
    result = gls(project, directory, {"corners": "all"}, Commands(directory), state=state, config=config)
    assert [row["corner"] for row in result["native_steps"]] == ["typical", "second_corner"]
    assert all(row["status"] == "PASS" and row["tests"] == 1 for row in result["native_steps"])
    assert result["metrics"]["gls_failures"] == 0


def test_gls_default_matches_configured_single_corner(tmp_path):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project)
    state["sdf"]["unselected_corner"] = str(project / "absent.sdf")
    config["DEFAULT_CORNER"] = "typical"
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert [row["corner"] for row in result["native_steps"]] == ["typical"]
    assert result["metrics"]["gls_failures"] == 0
    report = json.loads((directory / "gls.json").read_text())
    assert report["unmeasured_corners"] == ["unselected_corner"]


def test_gls_requires_functional_evidence_even_with_annotation(tmp_path):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project)
    bench = project / "phase2/stage1/sim/tb_unit.v"
    bench.write_text(bench.read_text().replace('$display("ORACLE_TB_DONE pass=1/1");', ""))
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert result["metrics"]["sdf_delays_applied"] > 0
    assert "gls_failures" not in result["metrics"]
    assert result["native_steps"][0]["status"] == "NOT_MEASURED"


@pytest.mark.parametrize("connected", [False, True])
def test_gls_accepts_native_physical_cell_models(tmp_path, connected):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project)
    model = Path(config["CELL_VERILOG_MODELS"][0])
    port, connection = ("inout node", ".node(a)") if connected else ("", "")
    model.write_text(model.read_text() + f"module physical_cell({port}); endmodule\n")
    netlist = Path(state["nl"])
    netlist.write_text(netlist.read_text().replace("endmodule", f"physical_cell fill({connection});\nendmodule"))
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert result["native_steps"][0]["status"] == "PASS", result


@pytest.mark.parametrize("kind,different,expected", [
    ("passive", False, "PASS"), ("passive", True, "FAIL"),
    ("logic", False, "FAIL"), ("state", False, "FAIL"),
    ("signal", False, "FAIL"), ("constant", False, "FAIL"),
    ("init", False, "FAIL"), ("io", False, "FAIL"),
    ("macro", False, "FAIL"), ("conditional", False, "FAIL"),
    ("unused_signal", False, "FAIL"), ("ansi", False, "FAIL"),
    ("header_macro", False, "FAIL"),
])
def test_gls_omits_only_passive_supply_connectors(tmp_path, kind, different, expected):
    if not all(shutil.which(name) for name in ("yosys", "iverilog", "vvp")):
        pytest.skip("Native Yosys and Icarus are required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project, different=different)
    model = project / "connector.v"
    config["PAD_VERILOG_MODELS"] = [str(model)]
    behavior = {
        "passive": "assign p1=p0; assign g1=g0;",
        "signal": "assign p1=p0; assign g1=g0;",
        "logic": "assign p1=~p0; assign g1=g0;",
        "state": "reg q; always @(posedge p0) q<=p1; assign g1=q;",
        "constant": "assign p1=1'b1; assign g1=g0;",
        "init": "reg q=1'b0; assign p1=q; assign g1=g0;",
        "io": "assign p1=p0; assign g1=g0;",
        "macro": "`ifdef ACTIVE\nreg q; always @(posedge p0) q<=p1; assign g1=q;\n"
                 "`else\nassign p1=p0; assign g1=g0;\n`endif",
        "conditional": "reg q; always @(posedge p0) q<=p1; assign g1=q;",
        "unused_signal": "assign p1=p0; assign g1=g0;",
        "ansi": "assign p1=p0; assign g1=g0;",
        "header_macro": "assign p1=p0; assign g1=g0;",
    }[kind]
    names = "p0,p1,g0,g1" + (",unused" if kind == "unused_signal" else "")
    declarations = ("input p0; output p1; inout g0,g1;" if kind == "io" else f"inout {names};")
    header = f"module connector({names});\n{declarations}\n"
    source = header + behavior + "\nendmodule\n"
    if kind == "ansi":
        source = "module connector(inout p0,p1,g0,g1);\n" + behavior + "\nendmodule\n"
    elif kind == "macro":
        source = "`define ACTIVE\n" + source
    elif kind == "conditional":
        source = "`define ACTIVE\n`ifdef ACTIVE\n" + source + "`else\n" + header + \
                 "assign p1=p0; assign g1=g0;\nendmodule\n`endif\n"
    elif kind == "header_macro":
        library = Path(config["CELL_VERILOG_MODELS"][0])
        library.write_text(library.read_text() + "\n`define CONNECTOR_PORTS p0,p1,g0,g1\n")
        source = "module connector(`CONNECTOR_PORTS);\n" + declarations + "\n" + behavior + "\nendmodule\n"
    model.write_text(source)
    lef = project / "physical.lef"
    lef.write_text("MACRO connector\n" + "".join(
        f" PIN {pin}\n  DIRECTION INOUT ;\n  USE {use} ;\n END {pin}\n"
        for pin, use in [("p0", "POWER"), ("p1", "SIGNAL" if kind == "signal" else "POWER"),
                         ("g0", "GROUND"), ("g1", "GROUND")]
        + ([("unused", "SIGNAL")] if kind == "unused_signal" else [])) + "END connector\n")
    config["PAD_LEFS"] = [str(lef)]
    netlist = Path(state["nl"])
    netlist.write_text(netlist.read_text().replace("endmodule", "wire v0,v1,g0,g1,aux0,aux1;\n"
        "connector rail(.p0(v0),.p1(v1),.g0(g0),.g1(g1),.aux0(aux0),.aux1(aux1));\nendmodule"))
    original = netlist.read_bytes()
    original_sdf = Path(state["sdf"]["typical"]).read_bytes()
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert result["native_steps"][0]["status"] == expected, result
    assert netlist.read_bytes() == original
    assert Path(state["sdf"]["typical"]).read_bytes() == original_sdf
    if kind == "passive":
        summary = json.loads((directory / "gls.json").read_text())
        assert summary["physical_only_types_omitted"] == ["connector"]
        assert result["metrics"]["sdf_delays_applied"] > 0
        assert result["metrics"]["sdf_annotation_errors"] == 0
        assert bool(result["metrics"]["gls_failures"]) == different
    else:
        assert json.loads((directory / "gls.json").read_text())["physical_only_types_omitted"] == []


def test_gls_uses_the_native_sdc_clock(tmp_path):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project)
    netlist = Path(state["nl"])
    netlist.write_text(netlist.read_text().replace("input a", "input clk, input a"))
    sdc = project / "timing.sdc"
    sdc.write_text("create_clock -name clock -period 24 [get_ports clk]\n")
    state["sdc"] = str(sdc)
    bench = project / "phase2/stage1/sim/tb_unit.v"
    bench.write_text('`timescale 1ns/1ps\nmodule tb_unit;\nreg clk=0,a=0; wire y;\n'
        'unit dut(.clk(clk),.a(a),.y(y));\nalways #5 clk=~clk;\n'
        'time first_edge; initial begin @(posedge clk); first_edge=$time; '
        '@(posedge clk); $display("ORACLE_TB_DONE pass=%0d/1",($time-first_edge)==24); '
        '$finish; end endmodule\n')
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert result["metrics"]["gls_failures"] == 0, result
    assert result["native_steps"][0]["clock"]["clocks"][0]["bench_half_period"] == "12"


def timed_arithmetic_fixture(project, *, physical=False, different=False, scenario=False, delay=17):
    from test_serial_parallel_declared_function_oracle import _declared_scenario_project
    import arith_oracle_tb_gen as arithmetic
    import testbench_gen

    cases = _declared_scenario_project(project, mode="wrong_product" if different else "good")
    docs = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    interface = json.loads(docs.read_text())
    interface["clocks"][0]["period_ns"] = 24
    docs.write_text(json.dumps(interface))
    if scenario:
        case = cases[1]
        assert testbench_gen.emit_unit_tbs(project, top="neutral_serial", scaffold=False,
                                          case_stated=True, case_ids=[case["name"]]) == 1
        bench = project / "phase2/stage1/sim/tb" / (case["name"] + ".v")
    else:
        report, code = arithmetic.generate(project, "digital_arithmetic_primitive")
        assert code == 0, report
        bench = project / report["tb"]
    source = project / "phase2/stage1/rtl/neutral_serial.v"
    core = source.read_text()
    native = project / "native"
    corner = native / "typical"
    corner.mkdir(parents=True)
    netlist, model, sdc, sdf = [native / name for name in ("netlist.v", "models.v", "timing.sdc", "typical/timing.sdf")]
    model.write_text('`timescale 1ns/1ps\n'
        'module timing_cell(input a,output y); assign y=a; specify (a=>y)=(1,1); endspecify endmodule\n'
        'module input_cell(inout PAD,output Y); assign Y=PAD; specify (PAD=>Y)=(0,0); endspecify endmodule\n'
        'module output_cell(input A,inout PAD); assign PAD=A; specify (A=>PAD)=(1,1); endspecify endmodule\n')
    if physical:
        top, cell, arc, instance = "neutral_chip", "output_cell", "A PAD", "output_pad"
        netlist.write_text(core + 'module neutral_chip(inout clk,rst,inout [7:0] x,inout y,p);\n'
            'wire inner_clk, result; input_cell input_pad(.PAD(clk),.Y(inner_clk));\n'
            'neutral_serial logical(.clk(inner_clk),.rst(rst),.x(x),.y(y),.p(result));\n'
            'output_cell output_pad(.A(result),.PAD(p)); endmodule\n')
        interconnect = '(INTERCONNECT clk input_pad/PAD (0.1:0.1:0.1))\n(INTERCONNECT output_pad/PAD p (0.1:0.1:0.1))'
    else:
        top, cell, arc, instance = "neutral_serial", "timing_cell", "a y", "gate"
        netlist.write_text(core.replace("output reg p", "output wire p")
            .replace("integer idx=0;", "integer idx=0; reg core_p;\ntiming_cell gate(.a(core_p),.y(p));")
            .replace("p<=", "core_p<="))
        interconnect = '(INTERCONNECT gate/y p (0.1:0.1:0.1))'
    sdc.write_text("create_clock -name clock -period 24 [get_ports clk]\n")
    sdf.write_text(f'(DELAYFILE (SDFVERSION "3.0") (DESIGN "{top}") (DIVIDER /) (TIMESCALE 1ns)\n'
        f'(CELL (CELLTYPE "{top}") (INSTANCE) (DELAY (ABSOLUTE\n{interconnect})))\n'
        f'(CELL (CELLTYPE "{cell}") (INSTANCE {instance}) '
        f'(DELAY (ABSOLUTE (IOPATH {arc} ({delay}:{delay}:{delay}) ({delay}:{delay}:{delay}))))))\n')
    state = {"nl": str(netlist), "sdc": str(sdc), "sdf": {"typical": str(sdf)}}
    (native / "state_out.json").write_text(json.dumps(state))
    (corner / "max.rpt").write_text('Startpoint: state (rising edge-triggered flip-flop clocked by clock)\n'
        'Endpoint: p (output port clocked by clock)\nPath Group: clock\nPath Type: max\n'
        ' 19.000000 data required time\n 17.000000 data arrival time\n 2.000000 slack (MET)\n')
    config = {"DESIGN_NAME": top, "CELL_VERILOG_MODELS": [str(model)], "VERILOG_FILES": [str(source)]}
    return state, config, bench


@pytest.mark.parametrize("physical", [False, True])
@pytest.mark.parametrize("scenario", [False, True])
@pytest.mark.parametrize("different", [False, True])
def test_gls_regenerates_arithmetic_at_native_output_deadline(tmp_path, physical, scenario, different):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config, bench = timed_arithmetic_fixture(project, physical=physical,
                                                   scenario=scenario, different=different)
    original = bench.read_bytes()
    result = gls(project, directory, {"testbenches": [str(bench)]}, Commands(directory), state=state, config=config)
    row = result["native_steps"][0]
    assert row["status"] == ("FAIL" if different else "PASS"), result
    assert row["observation"]["sample_offset_ns"] == 19
    assert row["sdf_errors"] == 0, result
    assert row["sdf_delays_applied"] > 0
    assert (result["metrics"]["gls_failures"] > 0) == different
    assert bench.read_bytes() == original
    if scenario:
        import arith_oracle_tb_gen as arithmetic
        original_plan = arithmetic._scenario_header(bench)
        replay = arithmetic._scenario_header(directory / "corner_1/annotated_tb.v")
        assert replay["pairs"] == original_plan["pairs"]
        assert replay["framing"] == original_plan["framing"]


@pytest.mark.parametrize("failure", ["late_output", "sdf_error"])
def test_gls_arithmetic_preserves_native_failures(tmp_path, failure):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config, bench = timed_arithmetic_fixture(project, scenario=True,
                                                   delay=22 if failure == "late_output" else 17)
    if failure == "sdf_error":
        sdf = Path(state["sdf"]["typical"])
        sdf.write_text(sdf.read_text().replace("IOPATH a y", "IOPATH missing y"))
    result = gls(project, directory, {"testbenches": [str(bench)]}, Commands(directory), state=state, config=config)
    assert result["native_steps"][0]["status"] == "FAIL", result
    assert result["metrics"]["gls_failures"] > 0
    assert (result["native_steps"][0]["sdf_errors"] > 0) == (failure == "sdf_error")


def test_late_arithmetic_observers_preserve_every_drive_edge(tmp_path):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    from test_serial_parallel_declared_function_oracle import _declared_scenario_project
    import arith_oracle_tb_gen as arithmetic

    _declared_scenario_project(tmp_path)
    spec, why = arithmetic.extract_serial_arith_spec(tmp_path, "digital_arithmetic_primitive")
    assert spec, why
    traces = []
    for sample in (1, 19):
        bench, executable = tmp_path / f"observe_{sample}.v", tmp_path / f"observe_{sample}.vvp"
        bench.write_text(arithmetic.emit_serial_oracle_module("tb_stream", spec,
            clock_period_ns=24, sample_offset_ns=sample)
            + '\nmodule monitor; always @(negedge tb_stream.clk) #0 '
            '$strobe("DRIVE %0t %b %b %b",$time,tb_stream.rst,tb_stream.x,tb_stream.y); endmodule\n')
        built = subprocess.run(["iverilog", "-g2012", "-s", "tb_stream", "-s", "monitor",
            "-o", str(executable), str(bench), str(tmp_path / "phase2/stage1/rtl/neutral_serial.v")],
            capture_output=True, text=True)
        assert built.returncode == 0, built.stderr
        run = subprocess.run(["vvp", str(executable)], capture_output=True, text=True)
        assert "ORACLE_TB_DONE pass=28/28" in run.stdout, run.stdout
        traces.append([line for line in run.stdout.splitlines() if line.startswith("DRIVE ")])
    assert traces[0] == traces[1]


@pytest.mark.parametrize("period,sample,literal", [
    (2000.002, 1000.001, "1000.001"),
    (2000000000.002, 1000000000.001, "1000000000.001"),
])
@pytest.mark.parametrize("scenario", [False, True])
def test_generated_serial_clock_preserves_picosecond_precision(tmp_path, period, sample, literal, scenario):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    from test_serial_parallel_declared_function_oracle import _declared_scenario_project
    import arith_oracle_tb_gen as arithmetic

    cases = _declared_scenario_project(tmp_path)
    spec, why = arithmetic.extract_serial_arith_spec(tmp_path, "digital_arithmetic_primitive")
    assert spec, why
    bench, executable = tmp_path / "precision.v", tmp_path / "precision.vvp"
    if scenario:
        plan = arithmetic.arithmetic_scenario_plan(tmp_path, "digital_arithmetic_primitive", cases[1])
        assert plan
        plan["observation"].update(clock_period_ns=period, sample_offset_ns=sample)
        text = arithmetic.emit_arithmetic_scenario_module("tb_precision", plan)
    else:
        text = arithmetic.emit_serial_oracle_module("tb_precision", spec,
            clock_period_ns=period, sample_offset_ns=sample)
    period_ps = round(period * 1000)
    bench.write_text(text + '\n`timescale 1ps/1ps\nmodule monitor; time first_edge; initial begin '
        '@(posedge tb_precision.clk); first_edge=$time; @(posedge tb_precision.clk); '
        f'if (($time-first_edge)!=64\'d{period_ps}) '
        '$fatal(1,"Declared clock period changed: %0d",$time-first_edge); '
        '$display("PERIOD_PS=%0d",$time-first_edge); $finish; end endmodule\n')
    built = subprocess.run(["iverilog", "-g2012", "-s", "tb_precision", "-s", "monitor",
        "-o", str(executable), str(bench), str(tmp_path / "phase2/stage1/rtl/neutral_serial.v")],
        capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    run = subprocess.run(["vvp", str(executable)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert f"#{literal};" in text
    assert f"PERIOD_PS={period_ps}" in run.stdout


@pytest.mark.parametrize("outcome,expected", [("skip", "NOT_MEASURED"), ("fail", "FAIL"), ("pass", "PASS")])
@pytest.mark.parametrize("virtual_clock", [False, True])
def test_native_cocotb_gls_distinguishes_skipped_reference(tmp_path, outcome, expected, virtual_clock):
    if not all(shutil.which(name) for name in ("iverilog", "vvp", "cocotb-config")):
        pytest.skip("Native Icarus and cocotb are required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project, cocotb=True)
    if virtual_clock:
        sdc = project / "virtual.sdc"
        sdc.write_text("create_clock -name virtual -period 20\n")
        state["sdc"] = str(sdc)
    bench = project / "phase2/stage1/sim/tb_unit.py"
    action = {"skip": 'pytest.skip("reference model unfilled")',
              "fail": 'assert int(dut.y.value)==1, "functional mismatch"',
              "pass": "assert int(dut.y.value)==0"}[outcome]
    bench.write_text("import cocotb\nimport pytest\nfrom cocotb.triggers import Timer\n"
        "@cocotb.test()\nasync def reference(dut):\n"
        "    dut.a.value=0\n    await Timer(3,unit='ns')\n"
        f"    {action}\n")
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert result["native_steps"][0]["status"] == expected, result
    if outcome == "skip":
        assert "gls_failures" not in result["metrics"], result
    else:
        assert result["metrics"]["gls_failures"] == int(outcome == "fail"), result


@pytest.mark.parametrize("outcome,expected", [("skip", "NOT_MEASURED"), ("fail", "FAIL"), ("pass", "PASS")])
@pytest.mark.parametrize("period", [20, 24, 2000.002, 1000000000.002])
def test_generated_cocotb_chip_clock_uses_native_sdc(tmp_path, outcome, expected, period):
    if not all(shutil.which(name) for name in ("iverilog", "vvp", "cocotb-config")):
        pytest.skip("Native Icarus and cocotb are required")
    from professional_tb_gen import _emit_common_header

    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project, cocotb=True)
    netlist = Path(state["nl"])
    netlist.write_text(netlist.read_text().replace("module unit(input a", "module neutral_chip(inout clk, input a"))
    sdf = Path(state["sdf"]["typical"])
    sdf.write_text(sdf.read_text().replace('"unit"', '"neutral_chip"'))
    config["DESIGN_NAME"] = "neutral_chip"
    sdc = project / "clock.sdc"
    sdc.write_text(f"create_clock -name clock -period {period} [get_ports clk]\n")
    state["sdc"] = str(sdc)
    bench = project / "phase2/stage1/sim/tb_unit.py"
    header = _emit_common_header({"top": "logical_unit", "cr": {
        "clk": "clk", "rst": None, "period_ns": 10, "active_high": False},
        "ports": [{"name": "clk", "dir": "input"}, {"name": "a", "dir": "input"}]})
    action = {"skip": 'pytest.skip("reference model unfilled")',
              "fail": 'assert int(dut.y.value)==1, "functional mismatch"',
              "pass": "assert int(dut.y.value)==0"}[outcome]
    bench.write_text(header + "\nimport pytest\nfrom cocotb.utils import get_sim_time\n"
        "@cocotb.test()\nasync def reference(dut):\n"
        "    dut.a.value=0\n    _start_clock(dut)\n    await RisingEdge(dut.clk)\n"
        "    first=get_sim_time(unit='ps')\n    await RisingEdge(dut.clk)\n"
        "    measured=get_sim_time(unit='ps')-first\n"
        "    print(f'ACTUAL_CLOCK_NS={measured/1000}',flush=True)\n"
        f"    assert measured == {round(period * 1000)}\n"
        f"    {action}\n")
    original = bench.read_bytes()
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert result["native_steps"][0]["status"] == expected, result
    assert bench.read_bytes() == original
    logs = "\n".join(Path(path).read_text(errors="replace") for path in result["reports"]
                     if str(path).endswith(".log"))
    assert f"ACTUAL_CLOCK_NS={period}" in logs
    if outcome == "skip":
        assert "gls_failures" not in result["metrics"], result


def test_python_suite_without_clock_setting_is_not_native_clock_replay(tmp_path):
    if not all(shutil.which(name) for name in ("iverilog", "vvp", "cocotb-config")):
        pytest.skip("Native Icarus and cocotb are required")
    project, directory = tmp_path / "project", tmp_path / "run"
    directory.mkdir()
    state, config = gls_fixture(project, cocotb=True)
    netlist = Path(state["nl"])
    netlist.write_text(netlist.read_text().replace("input a", "input clk, input a"))
    sdc = project / "clock.sdc"
    sdc.write_text("create_clock -name clock -period 20 [get_ports clk]\n")
    state["sdc"] = str(sdc)
    result = gls(project, directory, {}, Commands(directory), state=state, config=config)
    assert result["native_steps"][0]["status"] == "NOT_MEASURED", result
    assert "no supported setting" in result["native_steps"][0]["detail"]
    assert "gls_failures" not in result["metrics"], result
