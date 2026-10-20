#!/usr/bin/env python3
"""FULLSTACKTB (2026-09-29) — Step 5's full-stack population must be FUNCTIONAL.

MEASURED on both DIE benchmark runs (spm, subservient): the full-stack
testbench the flow generates was the connectivity skeleton (no stimulus, zero
golden compares), and `bit_level_full_stack_tb_check` answered every IC without
a command protocol with VACUOUS_PASS (`DESIGN_DECLARED_NA`), so Step 5 carried
it as a partially-vacuous PASS clause. The functional oracle that did exist
drove the bare core, never the pad-ring chip top the die is.

Pinned here, each with its known-negative:
  * the gate REFUSES a connectivity-only population (NOT_MEASURED + INCOMPLETE,
    never a pass) and refuses a DIE whose chip top is not built;
  * a population is credited only through the REQUIRED top (the pad-ring chip
    top on a DIE route), with testbench, transcript, sources and design input
    re-verified by the gate — a record cannot vouch for itself;
  * the producer drives the design's own L10 cases, each with the oracle its
    input states, through the chip top, honours the population, the corners and
    the reset-mid-computation scenario the case's own text states, and never
    counts a coverage FIGURE as a functional case.

The simulator is a stand-in here (the host carries none); the real simulation
of both benchmark ICs through their pad-ring tops is the replay in the lane
report. chip-AGNOSTIC: every fixture is a synthetic design.
"""
from __future__ import annotations

import importlib
import hashlib
import json
import re
import sys
import os
import shutil
import subprocess
import time
from unittest.mock import patch
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import bit_level_full_stack_tb_check as gate  # noqa: E402
import arith_oracle_tb_gen as aog  # noqa: E402


def _fsf():
    return importlib.import_module("full_stack_functional_tb")


# ---------------------------------------------------------------------------
# a synthetic serial-parallel arithmetic core (8-bit), optionally on a DIE
# ---------------------------------------------------------------------------
CORE = "dut_core"
CORE_V = f"""module {CORE} (input clk, input rst, input [7:0] x, input y,
                  output p);
  reg [15:0] acc; assign p = acc[0];
  always @(posedge clk) if (rst) acc <= 0; else acc <= acc + (y ? x : 0);
endmodule
"""
CHIP_TOP_V = f"""// generated pad-ring top (synthetic)
module chip_top (
    input clk,
    input rst,
    input [7:0] x,
    input y,
    output p,
    inout VDD,
    inout VSS
);
    wire clk__core, rst__core, y__core, p__core, t0;
    wire [7:0] x__core;
    TIELO u_tie0 (.ZN(t0));
    PADIN u_pad_clk (.PAD(clk), .Y(clk__core));
    PADIN u_pad_rst (.PAD(rst), .Y(rst__core));
    PADIN u_pad_y (.PAD(y), .Y(y__core));
    PADIN u_pad_x_0 (.PAD(x[0]), .Y(x__core[0]));
    PADOUT u_pad_p (.A(p__core), .PAD(p));
    {CORE} u_core (.clk(clk__core), .rst(rst__core), .x(x__core),
                   .y(y__core), .p(p__core));
endmodule
"""
MODELS = {
    "/pdk/libs.ref/io/verilog/io.v":
        "module PADIN(input PAD, output Y); assign Y = PAD; endmodule\n"
        "module PADOUT(input A, output PAD); assign PAD = A; endmodule\n",
    "/pdk/libs.ref/sc/verilog/sc.v":
        "module TIELO(output ZN); assign ZN = 1'b0; endmodule\n",
}


# Public neutral source controls for the changed arithmetic observation surface.
# Transport below only records proposed argv; no simulator is launched.
def _observation_project(tmp_path, *, width=8, renamed=False, period=10, delay=0):
    from test_serial_parallel_declared_function_oracle import _declared_scenario_project
    project = tmp_path / "neutral_observation"
    cases = _declared_scenario_project(project, width=width, renamed=renamed, latency=1)
    _write(project / 'input/submission_template/SELF_TAPEOUT.txt', 'self tape-out\n')
    gd = project / "phase1/generated_docs"
    l9_path = gd / "L9_INTEGRATION_SPEC.json"
    l9 = json.loads(l9_path.read_text())
    l9['clocks'][0]['period_ns'] = period
    l9_path.write_text(json.dumps(l9))
    names = ({'clk': 'i_clk', 'rst': 'i_rst', 'x': 'operand_word',
              'y': 'serial_bit', 'p': 'result_bit'} if renamed else
             {n: n for n in ('clk', 'rst', 'x', 'y', 'p')})
    c, r, x, y, p = [names[n] for n in ('clk', 'rst', 'x', 'y', 'p')]
    top = project / "phase3/stage3/pnr/neutral_pad_surface.v"
    _write(top, f'''module neutral_pad_surface(input {c}, {r},
        input [{width-1}:0] {x}, input {y}, output {p});
        wire core_clock, core_result;
        OBSIN clock_pad(.PAD({c}), .Y(core_clock));
        neutral_serial core(.{c}(core_clock), .{r}({r}), .{x}({x}),
                            .{y}({y}), .{p}(core_result));
        OBSOUT result_pad(.A(core_result), .PAD({p}));
        endmodule\n''')
    _write(project / _fsf().CHIP_TOP_RECORD_REL, json.dumps({
        'verdict': 'WROTE', 'core_module': 'neutral_serial',
        'chip_top_module': 'neutral_pad_surface',
        'chip_top_verilog': str(top.relative_to(project))}))
    models = {'/neutral/observation.v': f'''`timescale 1ns/1ps
        module OBSIN(input PAD, output Y); buf #{delay}(Y,PAD); endmodule
        module OBSOUT(input A, output PAD); buf #{delay}(PAD,A); endmodule\n'''}
    calls = []
    def transport(argv, wd, container, simulator, timeout):
        calls.append(argv)
        return 83, 'source-only transport refusal; no simulator executed'
    return project, cases, models, calls, transport


@pytest.mark.parametrize('width,renamed,period,delay', [
    (4, False, 10, 0), (8, True, 24, 0.2), (12, False, 16, 0.4)])
def test_new_padded_scenarios_request_observation_before_dispatch(
        tmp_path, monkeypatch, width, renamed, period, delay):
    project, cases, models, calls, transport = _observation_project(
        tmp_path, width=width, renamed=renamed, period=period, delay=delay)
    monkeypatch.setattr(importlib.import_module('testbench_gen'), '_detect_ic_class',
                        lambda project: 'digital_arithmetic_primitive')
    fs = _fsf()
    result = fs.generate(project, route='DIE', dispatch=transport,
                         model_resolver=lambda *args: (models, 'neutral source model'))
    assert result['verdict'] == 'NOT_MEASURED', result
    assert calls == [], 'unsupported observation must stop before any dispatch'
    assert result['reason_class'] == 'MISSING_OBSERVATION_CONTRACT', result
    assert result['counts']['executed'] == 0 and result['counts']['rows'] == 3
    requests = result['arithmetic_scenario_requests']
    assert {r['case'] for r in requests} == {c['name'] for c in cases}
    for case, entry in zip(cases, result['cases']):
        assert entry['state'] == 'no_oracle' and entry['step5_disposition']['blocking']
        request = next(r for r in requests if r['case'] == case['name'])
        assert request['verdict'] == 'NOT_MEASURED'
        assert request['fallback_skill'] == 'testbench-gen'
        assert request['reason_class'] == 'MISSING_OBSERVATION_CONTRACT'
        assert request['authored_tb'] == entry['tb']
        assert request['unsupported_requirements']
        assert entry['arithmetic_scenario_requests'] == [request]
        plan = aog._scenario_header(project / entry['tb'])
        assert plan['framing']['settled_latency'] == 1
        assert plan['comparisons'] == width * plan['transactions'] > 0
        assert result['full_stack_top']['source_sha256'] == fs.sha256_file(
            project / result['full_stack_top']['source'])
        for model in result['models']:
            assert fs.sha256_file(project / model['path']) == model['sha256']
    rc, consumed, sentinel = gate.functional_full_stack_verdict(project)
    assert rc == 2 and consumed['verdict'] == 'NOT_MEASURED', consumed
    assert sentinel.startswith('INCOMPLETE:') and consumed['counts']['executed'] == 0


def test_missing_observation_cli_publishes_existing_author_request(tmp_path, monkeypatch, capsys):
    project, cases, models, calls, transport = _observation_project(tmp_path)
    fs = _fsf(); tbg = importlib.import_module('testbench_gen')
    monkeypatch.setattr(tbg, '_detect_ic_class', lambda project: 'digital_arithmetic_primitive')
    monkeypatch.setattr(fs, 'default_dispatch', transport)
    monkeypatch.setattr(fs, 'default_model_resolver', lambda *args: (models, 'neutral source model'))
    output = project / 'component-cli.json'
    assert fs.main([str(project), '--route', 'DIE', '--container', 'source-double',
                    '--json', str(output)]) == 2
    published = json.loads(capsys.readouterr().out)
    assert published == json.loads(output.read_text())
    assert published['reason_class'] == 'MISSING_OBSERVATION_CONTRACT', published
    assert {r['case'] for r in published['arithmetic_scenario_requests']} == {c['name'] for c in cases}
    assert calls == [], 'CLI must publish the request before any simulator dispatch'


def test_direct_core_scenario_schedule_and_strict_comparators_stay_unchanged(tmp_path, monkeypatch):
    project, cases, models, calls, transport = _observation_project(tmp_path)
    tbg = importlib.import_module('testbench_gen')
    monkeypatch.setattr(tbg, '_detect_ic_class', lambda project: 'digital_arithmetic_primitive')
    result = _fsf().generate(project, route='HARDMACRO', dispatch=transport)
    assert len(calls) == 3
    assert not result.get('arithmetic_scenario_requests')
    for entry in result['cases']:
        path = project / entry['tb']
        plan = aog._scenario_header(path)
        text = path.read_text()
        assert 'always #5 clk=~clk;' in text and '@(posedge clk); #1;' in text
        assert plan['framing']['settled_latency'] == 1 and 'L=1;' in text
        assert 'p !== gv[v][k-L]' in text and 'if(k>=L)' in text
        assert 'clear_state(1)' in text and 'held_value=p' in text
        assert "p !== 1'b0 && p !== 1'b1" in text
        assert plan['comparisons'] == 8 * plan['transactions'] > 0
        for index, (a, b) in enumerate(plan['pairs']):
            assert f"gv[{index}]=8'd{a & b};" in text
        assert 'build_rc' in entry and entry['state'] == 'errored'


def test_new_handoff_retains_old_failures_and_authored_fullstack_provenance(tmp_path, monkeypatch):
    project, cases, models, calls, transport = _observation_project(tmp_path)
    fs = _fsf(); tbg = importlib.import_module('testbench_gen')
    monkeypatch.setattr(tbg, '_detect_ic_class', lambda project: 'digital_arithmetic_primitive')
    prior = fs.functional_dir(project)
    authored = ('module operand_limits; reg clk=0; reg rst=1; reg [7:0] x=0; '
                'reg y=0; wire p; neutral_serial dut(.clk(clk),.rst(rst),.x(x),.y(y),.p(p)); '
                'always #5 clk=~clk; endmodule\n')
    originals = {'functional_cases.json': '{"verdict":"FAIL","original":true}\n',
                 'run/operand_limits/run.log': 'FAIL: retained original measurement\n',
                 'operand_limits.v': authored,
                 'reset_situations.v': '// VIBEIC_TB_ORACLE: GENERATED by old_emitter\nold bytes\n'}
    for name, text in originals.items():
        _write(prior / name, text)
    result = fs.generate(project, route='DIE', dispatch=transport,
                         model_resolver=lambda *args: (models, 'neutral source model'))
    archive = project / result['previous_output']
    assert archive != prior and archive.is_dir()
    for name, text in originals.items():
        assert (archive / name).read_text() == text
    current_authored = prior / 'operand_limits.v'
    assert current_authored.read_text() == authored.replace('neutral_serial dut(', 'neutral_pad_surface dut(')
    assert len(calls) == 1 and calls[0][calls[0].index('-s') + 1] == 'operand_limits'
    entry = result['cases'][0]
    assert entry['family'] == 'authored_or_delivered'
    assert entry.get('reason_class') != 'MISSING_OBSERVATION_CONTRACT'
    assert not (project / 'input/tb').exists()
    assert result['preserved_authored'][0]['source'] == str((archive / 'operand_limits.v').relative_to(project))
    assert result['preserved_authored'][0]['sha256'] == fs.sha256_file(archive / 'operand_limits.v')
    second = fs.generate(project, route='DIE', dispatch=transport,
                         model_resolver=lambda *args: (models, 'neutral source model'))
    assert second['previous_output'] != result['previous_output']
    assert current_authored.read_text() == authored.replace('neutral_serial dut(', 'neutral_pad_surface dut(')
    assert len(calls) == 2 and second['cases'][0]['family'] == 'authored_or_delivered'
    for name, text in originals.items():
        assert (archive / name).read_text() == text


@pytest.mark.parametrize('mutation', ['stale_identity', 'missing_population'])
def test_observation_source_receipt_controls_still_refuse_missing_evidence(tmp_path, mutation):
    project, cases, models, calls, transport = _observation_project(tmp_path)
    plan = aog.arithmetic_scenario_plan(project, 'digital_arithmetic_primitive', cases[0])
    tb = _write(project / 'source_probe.v', aog.emit_arithmetic_scenario_module(cases[0]['name'], plan))
    transcript = _write(project / 'synthetic_source_transcript.txt',
        f"ARITH_SCENARIO_DONE transactions={plan['transactions']} comparisons={plan['comparisons']} errors=0 held_edges=2\n")
    sources = {path: digest for path, digest in plan['binding'].items() if Path(path).suffix == '.v'}
    captured, reason = aog.capture_arithmetic_scenario_execution(project, tb, transcript, sources)
    # This is a source consumer fixture, never a simulator or native receipt.
    assert captured and captured['complete'], reason
    row = {'tb_file': str(tb), 'arithmetic_scenario': captured}
    if mutation == 'stale_identity':
        declaration = project / 'plugin_output/declaration.json'
        declaration.write_text(declaration.read_text() + ' ')
    else:
        captured['complete'] = False
    state, detail = aog.arithmetic_scenario_case_state(row)
    assert state == 'NOT_EXECUTED' and 'NOT_MEASURED' in detail

CASES = [
    {"name": "random_equivalence", "kind": "coverage_goal",
     "stimulus": "隨機 ≥ 100 組 (x, y),全部對 golden model 一致",
     "expected": "100% PASS (binary)"},
    {"name": "corner_operand", "kind": "coverage_goal",
     "stimulus": "x = 0、y_stream = 0、x = MAX_POS、x = MIN_NEG、y = MAX_POS、"
                 "y = MIN_NEG、x = -1、y = -1",
     "expected": "100% PASS"},
    {"name": "reset", "kind": "coverage_goal",
     "stimulus": "reset 期間 / reset 解除瞬間 / reset 在計算進行中 assert 三種情況",
     "expected": "100% PASS"},
    {"name": "toggle_branch_coverage", "kind": "functional_vector",
     "stimulus": "同 random run;非 sign-off gate", "expected": "≥ 95%"},
]


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _authored_integrity_tb(name: str) -> str:
    """Public INPUT for gate integrity fixtures, with explicit author choices.

    These checks specify the L2 multiplier, not the synthetic CORE_V's behavior.
    _FakeSim transports the declared population; no native result is claimed.
    """
    case = next(c for c in CASES if c["name"] == name)
    nv = 25 if name == "corner_operand" else 225
    schedule = """
    // L10 operand boundaries: 0, MAX_POS, MIN_NEG, -1; also include 1.
    for (i=0; i<5; i=i+1) for (j=0; j<5; j=j+1) begin
      clear_state(1);
      complete_pair(values[i], values[j], -1);
    end
""" if name == "corner_operand" else """
    // L10 reset: held, released, and asserted DURING computation.
    // 25 pairs * (3 interruption positions * 2 reset holds + 3 pulses) = 225.
    for (i=0; i<5; i=i+1) for (j=0; j<5; j=j+1) begin
      for (position=1; position<=7; position=position+3) begin
        for (hold_edges=1; hold_edges<=3; hold_edges=hold_edges+2) begin
          clear_state(1);
          interrupt_pair(values[i], values[j], position);
          clear_state(hold_edges);
          // First released edge restarts bit0; compare the full restarted word.
          complete_pair(values[i], values[j], -1);
        end
      end
      for (position=1; position<=7; position=position+3) begin
        clear_state(1);
        // A synchronous reset pulse wholly BETWEEN edges must not clear state.
        complete_pair(values[i], values[j], position);
      end
    end
"""
    header = (
        "// Authored public synthetic INPUT; source fixture only.\n"
        "// L2: p = x * y mod 2^N (serial-parallel multiplier), N=8.\n"
        f"// Original L10: {json.dumps(case, ensure_ascii=False)}\n"
        "// Author observation contract: selected PADIN/PADOUT are zero-delay\n"
        "// continuous assignments; 10ns clock, negedge stimulus, posedge+1ns\n"
        "// settled sample. signed_2c, LSB_first, settled_edge_offset1.\n"
        "// Hold x through final product bit; rearm with one synchronous\n"
        "// active-high reset edge (reset coverage additionally holds three).\n"
    )
    body = r"""`timescale 1ns/1ps
module @NAME@;
  localparam integer NV = @NV@;
  reg clk=0, rst=1;
  reg [7:0] x=0;
  reg y=0;
  wire p;
  supply1 VDD;
  supply0 VSS;
  chip_top dut(.clk(clk), .rst(rst), .x(x), .y(y), .p(p),
               .VDD(VDD), .VSS(VSS));
  always #5 clk=~clk;
  reg [7:0] values [0:4];
  integer i, j, position, hold_edges;
  integer errors=0, transactions=0, passed=0, comparisons=0;

  // Independent L2 golden, including negative two's-complement operands.
  function [7:0] product;
    input [7:0] a, b;
    reg signed [15:0] full_product;
    begin
      full_product = $signed(a) * $signed(b);
      product = full_product[7:0];
    end
  endfunction

  task clear_state;
    input integer cycles;
    integer edge_index;
    begin
      @(negedge clk); rst=1; x=0; y=0;
      for (edge_index=0; edge_index<cycles; edge_index=edge_index+1) begin
        @(posedge clk); #1;
        if (p !== 1'b0) begin
          errors=errors+1;
          $display("ORACLE_MISMATCH: held synchronous reset p=%b", p);
        end
      end
      // Keep reset high until the next transaction's first negedge stimulus.
    end
  endtask

  task stream_edge;
    input [7:0] a, b;
    input integer k;
    begin
      @(negedge clk); rst=0; x=a;
      if (k<8) y=b[k]; else y=0;
      @(posedge clk); #1;
    end
  endtask

  task compare_bit;
    input [7:0] golden;
    input integer bit_index;
    begin
      if (p !== golden[bit_index]) begin
        errors=errors+1;
        $display("ORACLE_MISMATCH: bit=%0d expected=%b actual=%b",
                 bit_index, golden[bit_index], p);
      end
    end
  endtask

  task interrupt_pair;
    input [7:0] a, b;
    input integer stop_edge;
    integer k;
    reg [7:0] golden;
    begin
      golden=product(a,b);
      for (k=0; k<stop_edge; k=k+1) begin
        stream_edge(a,b,k);
        if (k>=1) compare_bit(golden,k-1);
      end
      // Abort here by synchronous reset; this prefix is not a scored word.
    end
  endtask

  task complete_pair;
    input [7:0] a, b;
    input integer pulse_edge;
    integer k, prior_errors;
    reg [7:0] golden;
    reg held_p;
    begin
      golden=product(a,b); prior_errors=errors;
      for (k=0; k<=8; k=k+1) begin
        stream_edge(a,b,k);
        if (k>=1) begin
          compare_bit(golden,k-1);
          comparisons=comparisons+1;
        end
        if (k==pulse_edge) begin
          // Intentional reset exception: +2ns..+3ns after this posedge,
          // wholly before the next negedge/posedge. A sync reset has no edge.
          held_p=p; #1; rst=1; #1; rst=0; #1;
          if (p !== held_p) begin
            errors=errors+1;
            $display("ORACLE_MISMATCH: between-edge reset changed p");
          end
        end
      end
      // x is still a through bit7's settled comparison at edge offset8.
      transactions=transactions+1;
      if (errors==prior_errors) passed=passed+1;
    end
  endtask

  initial begin
    values[0]=8'd0; values[1]=8'd1; values[2]=8'd127;
    values[3]=8'd128; values[4]=8'd255;
@SCHEDULE@
    if (transactions!=NV || comparisons!=8*NV)
      $fatal(1, "authored population mismatch");
    $display("ORACLE_TB_DONE pass=%0d/%0d", passed, NV);
    if (errors!=0) $fatal(1, "oracle/reset errors=%0d", errors);
    $finish;
  end
endmodule
"""
    return header + body.replace("@NAME@", name).replace("@NV@", str(nv)).replace(
        "@SCHEDULE@", schedule)


def _supplement_integrity_input(proj: Path, *, author_cases=True, models=None) -> None:
    """Declare the neutral interface and exact selected wrapper/model inputs."""
    declaration_path = proj / "plugin_output/declaration.json"
    declaration = (json.loads(declaration_path.read_text())
                   if declaration_path.is_file() else {})
    declaration.update({
        "integer_encoding": "signed_2c", "bit_order": "LSB_first",
        "latency_cycles": 1, "latency_cycles_origin": "settled_edge_offset",
        "reset_polarity": "active_high", "transaction_rearm": "clocked_reset",
        "rearm_reset_cycles": 1, "parallel_hold": "through_final_product_bit"})
    top_record = proj / _fsf().CHIP_TOP_RECORD_REL
    if top_record.is_file():
        top = json.loads(top_record.read_text())
        wrapper = proj / top["chip_top_verilog"]
        selected_models = _resolver(proj, set(), None)[0] if models is None else models
        binding = {str(wrapper.resolve()): _fsf().sha256_file(wrapper)}
        binding.update({str(Path(path).resolve()): hashlib.sha256(text.encode()).hexdigest()
                        for path, text in selected_models.items()})
        declaration.setdefault("verification_stimuli", {}).setdefault(
            "arithmetic_observation", {})[top["chip_top_module"]] = {
                "clock": "clk", "output": "p", "settle_ns": 0,
                "sample_offset_ns": 1, "binding": binding}
    _write(declaration_path, json.dumps(declaration))
    l9_path = proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9 = json.loads(l9_path.read_text())
    l9["clocks"] = [{"name": "clk", "period_ns": 10}]
    l9["reset_domains"] = [
        {"name": "rst", "sync": "synchronous", "polarity": "active_high"}]
    l9_path.write_text(json.dumps(l9))
    if author_cases:
        for name in ("corner_operand", "reset"):
            _write(proj / "input/tb" / f"{name}.v", _authored_integrity_tb(name))


def _mk_project(tmp_path: Path, *, die: bool, chip_top: bool = True,
                cases=None, integrity_input: bool = False) -> Path:
    proj = tmp_path / "proj"
    gd = proj / "phase1" / "generated_docs"
    _write(gd / "L3_CMD_PROTOCOL.json", json.dumps(
        {"opcodes": [], "no_opcodes_in_input": True}))
    _write(gd / "L4_REGMAP.json", json.dumps({"registers": []}))
    _write(gd / "L2_FRS.json", json.dumps(
        {"function": "p = x * y mod 2^N (serial-parallel multiplier)"}))
    _write(gd / "L9_INTEGRATION_SPEC.json", json.dumps({
        "top_module": CORE,
        "top_ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "rst", "direction": "input", "width": 1},
            {"name": "x", "direction": "input", "width": 8},
            {"name": "y", "direction": "input", "width": 1},
            {"name": "p", "direction": "output", "width": 1}]}))
    _write(gd / "L10_TEST_CASES.json", json.dumps(
        {"test_cases": CASES if cases is None else cases}, ensure_ascii=False))
    _write(proj / "phase2" / "stage1" / "rtl" / f"{CORE}.v", CORE_V)
    sfs = proj / "phase2" / "stage1" / "sim_full_stack"
    # the connectivity skeleton + its results, exactly the refused shape
    _write(sfs / f"tb_{CORE}_full.v",
           f"module tb_{CORE}_full; {CORE} u_dut(); endmodule\n")
    _write(sfs / "results.json", json.dumps(
        {"pass": False, "functional_verified": False,
         "functional_coverage": {"scored_with_golden": 0},
         "command_oracle_applicable": False, "per_vector": []}))
    if die:
        _write(proj / "input" / "submission_template" / "SELF_TAPEOUT.txt",
               "self tape-out\n")
        if chip_top:
            _write(proj / "phase3" / "stage3" / "pnr" / "chip_top_io.v",
                   CHIP_TOP_V)
            _write(proj / "reports" / "phase3" / "io_pad_chip_top.json",
                   json.dumps({"verdict": "WROTE",
                               "chip_top_module": "chip_top",
                               "core_module": CORE,
                               "chip_top_verilog":
                                   "phase3/stage3/pnr/chip_top_io.v"}))
    _supplement_integrity_input(proj, author_cases=integrity_input)
    return proj


def _resolver(project, used, container):
    # These are authored neutral INPUT bytes, not files borrowed from a PDK.
    sources = {str(_write(project / "input/models" / Path(path).name, text)): text
               for path, text in MODELS.items()}
    return sources, "fixture models"


# Issue 3330: the public two-comparison core/envelope input. Reuse the ordinary
# project factory and authored-TB ladder; execute the production dispatch.
_BINDING_INSTANCES = {
    'wildcard': 'core dut(.*);',
    'explicit': 'core dut(.a(a),.y(y));',
    'mixed': 'core dut(.a(~drive),.*);',
    'implicit_named': 'core dut(.a,.*);',
    'wildcard_first': 'core dut(.*, .a(~drive));',
    'all_overridden': 'core dut(.*, .a(a), .y(y));',
    'parameterized': 'core #(.W($clog2(2))) dut(.*);',
    'array': 'core dut[0:0](.*);',
    'comments': '/* core example(.*); */ core dut(/* binding */ .*);',
    'no_extra': 'core dut(.*);',
}


def _binding_project(tmp_path, variant='wildcard', *, defect=None):
    fs = _fsf()
    case = {'name': 'tb', 'kind': 'functional_vector',
            'stimulus': 'a=0 then a=1; compare y=a', 'expected': '100% PASS'}
    project = _mk_project(tmp_path, die=True, cases=[case])
    gd = project / 'phase1/generated_docs'
    _write(gd / 'L2_FRS.json', json.dumps({'function': 'y = a'}))
    _write(gd / 'L9_INTEGRATION_SPEC.json', json.dumps({'top_module': 'core',
        'top_ports': [{'name': 'a', 'direction': 'input', 'width': 1},
                      {'name': 'y', 'direction': 'output', 'width': 1}]}))
    parameter = '#(parameter W=1)' if variant == 'parameterized' else ''
    _write(project / f'phase2/stage1/rtl/{CORE}.v',
           f'module core {parameter}(input a,output y); assign y=a; endmodule\n')
    extra = '' if variant == 'no_extra' else ',inout VPWR'
    logic = 'assign y=~a;' if defect == 'bad_logic' else 'core u_core(.a(a),.y(y));'
    top = _write(project / 'phase3/stage3/pnr/chip_top_io.v',
                 f'module envelope {parameter}(input a,output y{extra}); {logic} endmodule\n')
    _write(project / fs.CHIP_TOP_RECORD_REL, json.dumps({
        'verdict': 'WROTE', 'core_module': 'core', 'chip_top_module': 'envelope',
        'chip_top_verilog': str(top.relative_to(project))}))
    inst = _BINDING_INSTANCES[variant]
    signals = 'reg a=0; wire y;'
    drive = 'a=1;'
    if variant in ('mixed', 'wildcard_first'):
        signals = 'reg drive=1; wire y;'
        drive = 'drive=0;'
    if defect == 'missing_signal':
        signals = 'wire y;'
        drive = ''
    if defect == 'missing_output':
        signals = 'reg a=0;'
    if defect == 'multiple':
        inst += ' core other(.*);'
    if defect == 'comma_instances':
        inst = 'core dut(.*), other(.*);'
    tb = f'''module tb;
{signals}
{inst}
initial begin
 #1; if(y!==0) begin $display("[TB tb] FAIL zero mismatch"); $fatal(1,"zero mismatch"); end
 {drive} #1; if(y!==1) begin $display("[TB tb] FAIL one mismatch"); $fatal(1,"one mismatch"); end
 $display("ORACLE_TB_DONE pass=2/2");
 $display("[TB tb] PASS two actual output comparisons"); $finish;
end
endmodule
'''
    if defect == 'wrong_expected':
        tb = tb.replace('if(y!==0)', 'if(y!==1)')
    if variant == 'comments':
        tb = tb.replace('initial begin', 'initial begin\n $display("core example(.*);");')
    _write(project / 'input/tb/tb.v', tb)
    if defect == 'missing_source':
        top.unlink()
    return project


def _binding_native(project):
    launched = []
    real_popen = subprocess.Popen
    def observe(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        launched.append((process, {'argv': args[0], 'pid': process.pid,
                                  'parent_pid': os.getpid()}))
        return process
    with patch.object(subprocess, 'Popen', observe):
        result = _fsf().generate(project, route='DIE', model_resolver=_resolver)
    handles = []
    for process, row in launched:
        row['rc'] = process.poll()
        assert row['rc'] is not None, row
        handles.append(row)
    _write(project / 'native_handles.json', json.dumps(handles, indent=2))
    rc, consumed, sentinel = gate.functional_full_stack_verdict(project)
    _write(project / 'consumer.json', json.dumps(
        {'rc': rc, 'report': consumed, 'sentinel': sentinel}, indent=2))
    return result, rc, consumed


@pytest.mark.skipif(not shutil.which('iverilog'), reason='native Icarus required')
@pytest.mark.parametrize('variant', list(_BINDING_INSTANCES))
def test_original_wildcard_binding_native_producer_and_consumer(tmp_path, variant):
    project = _binding_project(tmp_path, variant)
    result, rc, consumed = _binding_native(project)
    entry, = result['cases']
    assert entry['build_rc'] == 0, entry
    assert entry['run_rc'] == 0 and entry['checks'] == {'passed': 2, 'total': 2}, entry
    assert result['verdict'] == 'PASS' and result['counts']['rows'] == 1, result
    assert rc == 0 and consumed['verdict'] == 'PASS', consumed
    text = (project / entry['tb']).read_text()
    assert 'VPWR' not in text
    if variant in ('mixed', 'wildcard_first'):
        assert '.a(~drive)' in text
    if variant == 'comments':
        assert '/* core example(.*); */' in text
        assert '$display("core example(.*);");' in text


@pytest.mark.skipif(not shutil.which('iverilog'), reason='native Icarus required')
@pytest.mark.parametrize('defect', ['missing_signal', 'missing_output', 'bad_logic',
                                    'wrong_expected', 'missing_source',
                                    'multiple', 'comma_instances'])
def test_original_wildcard_binding_preserves_native_failures(tmp_path, defect):
    project = _binding_project(tmp_path, defect=defect)
    result, rc, consumed = _binding_native(project)
    assert result['counts']['rows'] == (0 if defect == 'missing_source' else 1)
    mismatch = defect in ('bad_logic', 'wrong_expected')
    assert rc == (1 if mismatch else 2), consumed
    assert result['verdict'] == ('FAIL' if mismatch else 'NOT_MEASURED')
    if defect in ('missing_signal', 'missing_output'):
        entry, = result['cases']
        assert entry['build_rc'] != 0 and entry['state'] == 'errored', entry
        log = (project / entry['build_log']).read_text()
        assert ('a' if defect == 'missing_signal' else 'y') in log and 'VPWR' not in log, log
    elif mismatch:
        entry, = result['cases']
        assert entry['build_rc'] == 0 and entry['run_rc'] != 0, entry
        assert entry['state'] == 'failed'
    else:
        assert json.loads((project / 'native_handles.json').read_text()) == []
        if defect != 'missing_source':
            assert result['cases'][0]['state'] == 'no_oracle'


def test_original_wildcard_binding_requires_original_port_context():
    fs = _fsf()
    text, reason = fs.retarget_instance('module tb; core dut(.*); endmodule',
                                       'core', 'envelope')
    assert (text is None, 'MISSING_ORIGINAL_PORT_BINDINGS' in reason) == (True, True)
    explicit, reason = fs.retarget_instance('core dut(.a(a),.y(y));', 'core', 'envelope')
    assert explicit == 'envelope dut(.a(a),.y(y));'


class _FakeSim:
    """A simulator stand-in: builds succeed; a run reports what the TB's own
    population is, scored as `outcome(case, nv)` says. It reads the testbench
    it is asked to run, so a TB that is not there cannot be 'run'."""

    def __init__(self, outcome=None):
        self.calls = []
        self.tb_for = {}
        self.outcome = outcome or (lambda case, nv: (nv, nv))

    def __call__(self, argv, run_dir, container, tool, timeout):
        self.calls.append(list(argv))
        if argv[0] == "iverilog":
            self.tb_for[str(run_dir)] = argv[-1]
            return 0, ""
        tb = Path(self.tb_for[str(run_dir)])
        text = tb.read_text()
        case = tb.stem
        plan = aog._scenario_header(tb)
        if plan is not None:
            a, b = self.outcome(case, plan["transactions"])
            errors = max(0, b - a)
            word = "FAIL" if errors else "PASS"
            records = []
            remaining, remaining_errors = b, errors
            for phase in plan.get("populations", []):
                measured = min(remaining, phase["transactions"])
                phase_errors = min(remaining_errors, measured)
                records.append(
                    f"ARITH_SCENARIO_POPULATION family={phase['scenario']} "
                    f"transactions={measured} comparisons={measured * plan['spec']['width']} "
                    f"errors={phase_errors}\n")
                remaining -= measured
                remaining_errors -= phase_errors
            if plan["scenario"] == "random_transactions" and errors == 0:
                declared = plan["framing"]
                order = 0 if declared["bit_order"] == "LSB" else 1
                records.append(
                    f"ORACLE_TB_FRAMING in_order={order} out_order={order} "
                    f"latency_cycles={declared['settled_latency']} "
                    f"latency_origin={aog.SERIAL_LATENCY_ORIGIN}\n")
            return (1 if errors else 0), (
                "".join(records) +
                f"ARITH_SCENARIO_DONE transactions={b} "
                f"comparisons={b * plan['spec']['width']} errors={errors} held_edges=2\n"
                f"[TB {case}] {word}: source-only simulator stand-in\n")
        m = re.search(r"\blocalparam\s+integer\s+[^;]*\bNV\s*=\s*(\d+)\s*[,;]", text)
        if m:
            nv = int(m.group(1))
            a, b = self.outcome(case, nv)
            return 0, f"ORACLE_TB_DONE pass={a}/{b}\n"
        a, b = self.outcome(case, 1)
        word = "PASS" if a == b else "FAIL"
        return (0 if word == "PASS" else 1), f"[TB {case}] {word} — ok\n"


@pytest.fixture
def arith_class(monkeypatch):
    import testbench_gen as tbg
    monkeypatch.setattr(tbg, "_detect_ic_class",
                        lambda project: "digital_arithmetic_primitive")


def _run_gate(proj: Path, tmp_path: Path, capsys=None):
    out = tmp_path / "gate.json"
    old = sys.argv
    sys.argv = ["bit_level_full_stack_tb_check.py", str(proj), "--json",
                str(out)]
    try:
        rc = gate.main()
    finally:
        sys.argv = old
    stdout = capsys.readouterr().out if capsys is not None else ""
    return rc, json.loads(out.read_text()), stdout


# ===========================================================================
# THE GATE — a connectivity-only population is refused
# ===========================================================================
def test_connectivity_only_population_is_refused_not_vacuous(tmp_path, capsys):
    """KNOWN-POSITIVE of the refusal: skeleton + 0 golden vectors, no record."""
    proj = _mk_project(tmp_path, die=False)
    rc, res, out = _run_gate(proj, tmp_path, capsys)
    assert rc == 2, res
    assert res["verdict"] == "NOT_MEASURED", res
    assert res["reason_class"] == "ZERO_DENOMINATOR"
    assert res["pass"] is False and res["vacuous_pass"] is False
    assert res["rule"] == "functional_full_stack_population_absent"
    # the sentinel that makes flow_compliance raise INCOMPLETE, last, column 0
    assert out.rstrip().splitlines()[-1].startswith("INCOMPLETE:")


def test_die_route_without_chip_top_is_blocked(tmp_path, capsys):
    """A DIE whose pad-ring chip top is not built yet measures nothing."""
    proj = _mk_project(tmp_path, die=True, chip_top=False)
    rc, res, out = _run_gate(proj, tmp_path, capsys)
    assert rc == 2
    assert res["verdict"] == "NOT_MEASURED"
    assert res["reason_class"] == "BLOCKED_BY_UPSTREAM"
    assert res["required_top"]["pad_ring"] is True
    assert "INCOMPLETE:" in out


# ===========================================================================
# THE PRODUCER — functional cases through the pad-ring chip top
# ===========================================================================
def test_producer_drives_every_case_through_the_pad_ring_top(tmp_path,
                                                            arith_class):
    proj = _mk_project(tmp_path, die=True)
    sim = _FakeSim()
    rec = _fsf().generate(proj, "ctr", dispatch=sim,
                          model_resolver=_resolver)
    assert rec["verdict"] == "PASS", rec["reason"]
    by = {c["name"]: c for c in rec["cases"]}
    assert rec["counts"]["executed"] == 3 and rec["counts"]["passed"] == 3
    assert by["toggle_branch_coverage"]["state"] == "excluded"
    assert not (proj / "phase2/stage1/sim_full_stack/functional"
                / "toggle_branch_coverage.v").exists()
    for name in ("random_equivalence", "corner_operand", "reset"):
        c = by[name]
        assert c["state"] == "passed", c
        text = (proj / c["tb"]).read_text()
        assert _fsf().instance_count(text, "chip_top") == 1
        assert _fsf().instance_count(text, CORE) == 0
        assert c["family"] == "declared_arithmetic_scenario"
    # compiled with the staged PDK models, the chip top and the core RTL
    build = next(a for a in sim.calls if a[0] == "iverilog")
    joined = " ".join(build)
    assert "phase3/stage3/pnr/chip_top_io.v" in joined
    assert f"rtl/{CORE}.v" in joined
    assert sum("/functional/models/" in a for a in build) == 2


def test_the_case_text_decides_population_corners_and_reset_scenario(
        tmp_path, arith_class):
    proj = _mk_project(tmp_path, die=True)
    rec = _fsf().generate(proj, "ctr", dispatch=_FakeSim(),
                          model_resolver=_resolver)
    by = {c["name"]: c for c in rec["cases"]}
    random_tb = proj / by["random_equivalence"]["tb"]
    rnd = random_tb.read_text()
    random_plan = aog._scenario_header(random_tb)
    nv = random_plan["transactions"]
    assert nv >= 100 and by["random_equivalence"]["declared_population"] == 100
    assert "framing calibrated on the first 28" not in rnd
    assert random_plan["framing"]["bit_order"] == "LSB"
    assert random_plan["framing"]["settled_latency"] == 1
    corner_tb = proj / by["corner_operand"]["tb"]
    corner = corner_tb.read_text()
    corner_plan = aog._scenario_header(corner_tb)
    # MIN_NEG for an 8-bit operand is the pattern 128, crossed with itself
    assert [0, 0] in corner_plan["pairs"]
    assert [128, 128] in corner_plan["pairs"]
    reset_tb = proj / by["reset"]["tb"]
    reset = reset_tb.read_text()
    reset_plan = aog._scenario_header(reset_tb)
    assert reset_plan["scenario"] == "reset_situations"
    assert reset_plan["transactions"] == 9 * len(reset_plan["pairs"])
    assert "interrupted(vi,4,1);" in reset
    assert "interrupted(vi," not in corner


def test_a_case_short_of_its_stated_population_is_not_a_pass(tmp_path,
                                                            arith_class):
    proj = _mk_project(tmp_path, die=True)
    # the simulator reports FEWER vectors than the case states
    sim = _FakeSim(lambda case, nv: (min(nv, 50), min(nv, 50))
                   if case == "random_equivalence" else (nv, nv))
    rec = _fsf().generate(proj, "ctr", dispatch=sim, model_resolver=_resolver)
    by = {c["name"]: c for c in rec["cases"]}
    assert by["random_equivalence"]["state"] == "short_population"
    assert rec["verdict"] == "NOT_MEASURED"


def test_producer_refuses_a_chip_top_it_has_no_models_for(tmp_path,
                                                         arith_class):
    proj = _mk_project(tmp_path, die=True)
    rec = _fsf().generate(
        proj, "ctr", dispatch=_FakeSim(),
        model_resolver=lambda p, u, c: ({"/pdk/io.v": MODELS[
            "/pdk/libs.ref/io/verilog/io.v"]}, "io only"))
    assert rec["verdict"] == "NOT_MEASURED"
    assert rec["reason_class"] == "EXECUTION_ERROR"
    assert "TIELO" in rec["reason"]
    assert not list((proj / "phase2/stage1/sim_full_stack/functional")
                    .glob("*.v"))


def test_producer_before_the_chip_top_exists_runs_nothing(tmp_path,
                                                         arith_class):
    proj = _mk_project(tmp_path, die=True, chip_top=False)
    sim = _FakeSim()
    rec = _fsf().generate(proj, "ctr", dispatch=sim, model_resolver=_resolver)
    assert rec["verdict"] == "NOT_MEASURED"
    assert rec["reason_class"] == "BLOCKED_BY_UPSTREAM"
    assert sim.calls == []


def test_off_the_pad_ring_route_the_core_is_the_full_stack_top(tmp_path,
                                                              arith_class):
    proj = _mk_project(tmp_path, die=False)
    rec = _fsf().generate(proj, None, dispatch=_FakeSim(),
                          model_resolver=_resolver)
    assert rec["full_stack_top"]["pad_ring"] is False
    assert rec["full_stack_top"]["module"] == CORE
    assert rec["verdict"] == "PASS"
    assert rec["models"] == []


# ===========================================================================
# THE GATE — crediting a population, and refusing one that cannot vouch
# ===========================================================================
def _passing_die(tmp_path, arith_class=None, *, integrity_input=False):
    proj = _mk_project(tmp_path, die=True, integrity_input=integrity_input)
    rec = _fsf().generate(proj, "ctr", dispatch=_FakeSim(),
                          model_resolver=_resolver)
    assert rec["verdict"] == "PASS"
    return proj, rec


def test_gate_credits_a_population_measured_through_the_chip_top(
        tmp_path, arith_class, capsys):
    proj, _rec = _passing_die(tmp_path)
    rc, res, out = _run_gate(proj, tmp_path, capsys)
    assert rc == 0, res
    assert res["verdict"] == "PASS" and res["functional_verified"] is True
    assert res["vacuous_pass"] is False
    assert res["counts"] == {"executed": 3, "passed": 3, "failed": 0,
                             "short": 0}
    assert res["required_top"]["module"] == "chip_top"
    assert "INCOMPLETE" not in out


def test_gate_fails_a_case_whose_oracle_disagreed(tmp_path, arith_class,
                                                  capsys):
    proj = _mk_project(tmp_path, die=True, integrity_input=True)
    sim = _FakeSim(lambda case, nv: (nv - 1, nv) if case == "corner_operand"
                   else (nv, nv))
    rec = _fsf().generate(proj, "ctr", dispatch=sim, model_resolver=_resolver)
    assert rec["verdict"] == "FAIL"
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 1 and res["verdict"] == "FAIL"
    assert res["counts"]["failed"] == 1


def test_gate_refuses_a_transcript_that_is_not_the_recorded_one(
        tmp_path, arith_class, capsys):
    proj, rec = _passing_die(tmp_path, integrity_input=True)
    log = proj / next(c for c in rec["cases"]
                      if c["name"] == "reset")["run_log"]
    log.write_text(log.read_text() + "\n")
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["verdict"] == "NOT_MEASURED"
    assert res["rule"] == "functional_record_inconsistent"


def test_gate_rescores_the_transcript_rather_than_trusting_the_record(
        tmp_path, arith_class, capsys):
    """A record that says `passed` over a transcript with no verdict marker."""
    proj, rec = _passing_die(tmp_path, integrity_input=True)
    fsf = _fsf()
    c = next(c for c in rec["cases"] if c["name"] == "corner_operand")
    log = proj / c["run_log"]
    log.write_text("simulation finished\n")
    c["run_log_sha256"] = fsf.sha256_file(log)      # the record is re-sealed
    fsf.record_path(proj).write_text(json.dumps(rec))
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_record_inconsistent"
    assert "scores errored" in res["rationale"]


def test_gate_refuses_a_testbench_that_bypasses_the_pad_ring(
        tmp_path, arith_class, capsys):
    proj, rec = _passing_die(tmp_path)
    fsf = _fsf()
    c = next(c for c in rec["cases"] if c["name"] == "reset")
    tb = proj / c["tb"]
    tb.write_text(tb.read_text().replace("chip_top dut", f"{CORE} dut"))
    c["tb_sha256"] = fsf.sha256_file(tb)            # the record is re-sealed
    fsf.record_path(proj).write_text(json.dumps(rec))
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_record_inconsistent"
    assert "does not instantiate the required top" in res["rationale"]


def test_gate_refuses_a_record_measured_through_the_core_on_a_die(
        tmp_path, arith_class, capsys):
    proj = _mk_project(tmp_path, die=True)
    # a population measured OFF the pad-ring route, then the die is declared
    rec = _fsf().generate(proj, None, route="HARDMACRO", dispatch=_FakeSim(),
                          model_resolver=_resolver)
    assert rec["verdict"] == "PASS"
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_record_wrong_top"


def test_gate_refuses_a_record_of_bytes_that_have_changed(
        tmp_path, arith_class, capsys):
    proj, _rec = _passing_die(tmp_path, integrity_input=True)
    rtl = proj / "phase2" / "stage1" / "rtl" / f"{CORE}.v"
    rtl.write_text(rtl.read_text() + "// edited\n")
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_record_stale"


def test_gate_refuses_a_population_that_executed_nothing(tmp_path, capsys,
                                                         monkeypatch):
    """No oracle family grounds any case -> the record is empty -> refused."""
    import testbench_gen as tbg
    monkeypatch.setattr(tbg, "_detect_ic_class", lambda project: None)
    proj = _mk_project(tmp_path, die=True, cases=[
        {"name": "blinky", "kind": "functional_vector",
         "stimulus": "blinky.hex", "expected": "GPIO toggles"}])
    rec = _fsf().generate(proj, "ctr", dispatch=_FakeSim(),
                          model_resolver=_resolver)
    assert rec["counts"]["executed"] == 0
    assert rec["cases"][0]["state"] == "no_oracle"
    rc, res, out = _run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["verdict"] == "NOT_MEASURED"
    assert out.rstrip().splitlines()[-1].startswith("INCOMPLETE:")


# ===========================================================================
# TRANSCRIPT SCORING — each side of every pair
# ===========================================================================
@pytest.mark.parametrize("rc,text,state", [
    (0, "ORACLE_TB_DONE pass=28/28\n", "passed"),
    (0, "ORACLE_TB_DONE pass=27/28\nORACLE_MISMATCH: no single\n", "failed"),
    (0, "ORACLE_TB_DONE pass=0/0\n", "errored"),
    (0, "[TB c1] PASS — holds\n", "passed"),
    (1, "[TB c1] FAIL: x asserted\n", "failed"),
    (0, "[TB other] PASS — holds\n", "errored"),
    (0, "simulation finished\n", "errored"),
    (1, "", "errored"),
])
def test_score_transcript_pairs(rc, text, state):
    assert _fsf().score_transcript("c1", rc, text)["state"] == state


def test_coverage_figure_is_not_a_functional_acceptance():
    fsf = _fsf()
    assert fsf.acceptance_is_coverage_figure({"expected": "≥ 95%"})
    assert not fsf.acceptance_is_coverage_figure(
        {"expected": "100% PASS (binary)"})
    assert not fsf.acceptance_is_coverage_figure({"expected": "PASS"})


# ===========================================================================
# THE CASE-TEXT READERS (arith_oracle_tb_gen)
# ===========================================================================
def test_declared_population_reads_the_stimulus_not_the_acceptance():
    assert aog.declared_vector_population(
        {"stimulus": "隨機 ≥ 10000 組 (x, y)", "expected": "100% PASS"}) == 10000
    assert aog.declared_vector_population(
        {"stimulus": "at least 2,048 random pairs"}) == 2048
    assert aog.declared_vector_population(
        {"stimulus": "同 random run", "expected": "≥ 95%"}) is None
    assert aog.declared_vector_population({"stimulus": "≥ 95% toggle"}) is None


def test_named_corners_are_width_bit_patterns():
    case = {"stimulus": "x = 0、x = MAX_POS、x = MIN_NEG、y = -1"}
    assert aog.named_corner_values(case, 8) == [0, 127, 128, 255]
    assert aog.named_corner_values({"stimulus": "random pairs"}, 8) == []


def test_reset_mid_computation_grammar():
    assert aog.reset_mid_computation_case(
        {"stimulus": "reset 在計算進行中 assert"})
    assert aog.reset_mid_computation_case(
        {"stimulus": "assert reset during a computation"})
    assert not aog.reset_mid_computation_case(
        {"stimulus": "reset 解除後 10 cycle 內取得第一條 instruction"})


def test_the_historical_sample_is_unchanged_without_case_text():
    spec = {"width": 8, "operator": "*", "signed": False}
    base = aog.select_operand_pairs(spec, "mixed")
    assert len(base) == 28
    assert aog.select_operand_pairs(spec, "mixed", min_vectors=None,
                                    extra_corners=()) == base
    grown = aog.select_operand_pairs(spec, "random", min_vectors=500)
    assert len(grown) == 500 and len(set(grown)) == 500
    named = aog.select_operand_pairs(spec, "corners", extra_corners=[0, 128])
    assert named[:4] == [(0, 0), (0, 128), (128, 0), (128, 128)]


def test_small_populations_keep_the_full_framing_search():
    spec = {"top": "t", "operator": "*", "width": 8, "signed": False,
            "parallel": "x", "serial_in": "y", "serial_out": "p",
            "clk": "clk", "rst": "rst", "reset_active_low": False,
            "parallel_is_lhs": True, "other_inputs": [],
            "ports": [{"name": n, "dir": d} for n, d in
                      (("clk", "input"), ("rst", "input"), ("x", "input"),
                       ("y", "input"), ("p", "output"))]}
    small = aog.emit_serial_oracle_module("m", spec, [(1, 2)] * 28)
    large = aog.emit_serial_oracle_module(
        "m", spec, [(i, i + 1) for i in range(40)])
    assert "calibrated" not in small
    assert "for (_vi = 0; _vi < NV; _vi = _vi + 1) begin" in small
    assert "framing calibrated on the first 28" in large
    with pytest.raises(ValueError):
        aog.emit_serial_oracle_module("m", dict(spec, rst=None), [(1, 2)],
                                      abort_before_each=True)


# ===========================================================================
# THE WIRING — Phase 2 step and the phase-3 re-run after the pad ring
# ===========================================================================
def test_phase2_step_publishes_the_records_word(monkeypatch, tmp_path):
    import design_one_shot_runner as dsor
    fsf = _fsf()
    for verdict, cls, want, want_cls in (
            ("PASS", None, "PASS", ""),
            ("FAIL", None, "FAIL", ""),
            ("NOT_MEASURED", "ZERO_DENOMINATOR", "NOT_MEASURED",
             "no_population"),
            ("NOT_MEASURED", "BLOCKED_BY_UPSTREAM", "NOT_MEASURED",
             "input_absent")):
        monkeypatch.setattr(fsf, "generate", lambda p, c, _v=verdict, _c=cls: {
            "verdict": _v, "reason_class": _c, "reason": "r",
            "counts": {"executed": 1}, "full_stack_top": {"module": "t"}})
        res = dsor.step_full_stack_functional_tb(tmp_path, "ctr")
        assert res.name == "full_stack_functional_tb"
        assert res.status == want and res.reason_class == want_cls


def test_phase3_reruns_the_producer_only_after_the_pad_ring_is_written(
        monkeypatch, tmp_path):
    import phase3_one_shot_runner as p3
    fsf = _fsf()
    seen = []
    monkeypatch.setattr(fsf, "generate", lambda p, c: seen.append(p) or {
        "verdict": "PASS", "counts": {"executed": 2}, "reason": "ok"})
    monkeypatch.setattr(p3, "_chip_path_requests_pad_ring", lambda p: True)
    monkeypatch.setattr(p3, "step_io_pad_chip_top_gen",
                        lambda p, c, pdk, **kw: p3.StepResult(
                            "io_pad_chip_top_gen", "PASS", 0.0, "rc=0"))
    res = p3._padring_producer_dispatch(tmp_path, "ctr", None)
    assert res.status == "PASS" and seen == [tmp_path]
    assert res.extras["full_stack_functional"]["verdict"] == "PASS"
    seen.clear()
    monkeypatch.setattr(p3, "step_io_pad_chip_top_gen",
                        lambda p, c, pdk, **kw: p3.StepResult(
                            "io_pad_chip_top_gen", "FAIL", 0.0, "rc=1"))
    res = p3._padring_producer_dispatch(tmp_path, "ctr", None)
    assert res.status == "FAIL" and seen == []


# The ordinary front door must reach the producer that owns the missing top.
# All prerequisites here are neutral source-fixture checks; the simulator
# boundary is the existing stand-in, so these do not claim native IC sign-off.
def _phase2_pad_fixture(tmp_path, monkeypatch):
    import time
    from dataclasses import asdict
    import design_one_shot_runner as design
    import execution_policy as execution
    import flow_compliance_check as compliance
    import _flow_yaml
    import step_output_collector as versions
    import vibe_ic_one_shot_runner as outer

    monkeypatch.setattr(execution, 'request', lambda: {'mode': 'default'})
    project = _mk_project(tmp_path, die=True, chip_top=False)
    started = time.time()
    producer = design.step_full_stack_functional_tb(project, None)
    assert producer.status == 'NOT_MEASURED'
    assert json.loads(_fsf().record_path(project).read_text())['reason_class'] == 'BLOCKED_BY_UPSTREAM'
    _write(project / 'neutral_prerequisite.json', '{"measured": true}')
    # D1's existing conditional review consumer also reads the inline neutral
    # L-docs. Bind this test-only review to exactly those authored fixture bytes.
    import ai_signed_judgement as judgement
    _write(project / 'reports/audit/ai_judgements/D1.json', json.dumps({
        'schema': judgement.SCHEMA, 'step_id': 'D1', 'verdict': 'PASS',
        'signed_by': 'ic-expert-agent', 'judgement': 'reviewed neutral unit fixture L-docs',
        'evidence_sha256': judgement.evidence_sha256(project, 'D1')}))
    compliance._GATE_LEDGER.clear()
    rows = []
    declared = [r for r in _flow_yaml.load()['steps']
                if (isinstance(r['id'], int) and 1 <= r['id'] <= 6)
                or (not isinstance(r['id'], int) and (
                    str(r.get('phase_scope') or '').strip().lower() == 'agnostic'
                    or compliance._STAGE_PHASE.get(
                        str(r.get('stage') or '').strip()) in (None, '2')))]
    for declaration in declared:
        sid = declaration['id']
        clause = {'json_field_true': {'file': 'neutral_prerequisite.json', 'field': 'measured'}}
        if sid == 5:
            clause = {'program_exit_zero':
                      'bit_level_full_stack_tb_check . --json '
                      'reports/phase2/gates/bit_level_full_stack.json'}
        row = compliance.check_step(project, {'id': sid, 'name': 'neutral_prerequisite',
                      'stage': 'stage1', 'required_outputs': ['neutral_prerequisite.json'],
                      'gate': clause}, {})
        rows.append(asdict(row))
    assert all(r['status'] == ('NOT_MEASURED' if str(r['id']) == '5' else 'PASS')
               for r in rows), [(r['id'], r['status'], r.get('failed_gates'),
                                 r.get('conditional_note')) for r in rows]
    functional = next(r for r in rows if str(r['id']) == '5')
    attempt = versions.begin_step(project, '5')
    versions.finish_step(project, attempt, verdict=functional['status'],
                         result={'canonical_consumer': {'step': functional}})
    audit = {'program': 'flow_compliance_check', 'project': str(project),
             'scope': {'phase': '2', 'stage': None, 'stage_id': None,
                       'steps_judged': [str(r['id']) for r in rows], 'step_count': len(rows)},
             'overall': 'NOT_MEASURED', 'steps': rows,
             'gate_execution_ledger': list(compliance._GATE_LEDGER)}
    _write(project / 'reports/phase2/gates/phase2_compliance.json', json.dumps(audit))
    report = {'project': str(project), 'verdict': 'NOT_MEASURED', 'steps': [
        asdict(design.StepResult('neutral_measurable', 'PASS')),
        asdict(producer), asdict(design.StepResult('final_audit', 'NOT_MEASURED',
                                                  reason_class='partial_population'))]}
    _write(outer._phase_report_path(project, 'phase2_one_shot.json'), json.dumps(report))
    return project, report, started


def _actual_outer_phase3_entry(project, report, started):
    """Execute the real Phase-2 halt statements and Phase-3 entry expression.

    Reading the actual caller also lets the exact base answer with its old
    cycle's VALUE (False), rather than failing on a missing new helper symbol.
    """
    import ast
    from types import SimpleNamespace
    import execution_policy as execution
    import vibe_ic_one_shot_runner as outer
    tree = ast.parse(Path(outer.__file__).read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_main')
    body = next(n for n in ast.walk(main) if isinstance(n, ast.If) and any(
        isinstance(x, ast.Assign) and ast.unparse(x) == "halted_at = 'phase2'"
        for x in n.body) and 'NOT_MEASURED' in ast.unparse(n.test))
    # Its sibling immediately preceding this halt owns the named deferral.
    siblings = next(value for n in ast.walk(main) for value in vars(n).values()
                    if isinstance(value, list) and body in value)
    pos = siblings.index(body)
    nodes = [body]
    if pos and '_phase2_pad_top_deferral(' in ast.unparse(siblings[pos - 1]):
        nodes.insert(0, siblings[pos - 1])
    verdict, _ = outer._row_verdict(project, 'phase2_one_shot.json', 1, started, 'phase2')
    env = dict(vars(outer), project=project, rep=report, verdict=verdict, rc=1,
               _execution=execution,
               args=SimpleNamespace(skip_phase3=False), _p3_skip_by_exit=False,
               _phase_started={'phase2': started}, _phase2_pad_top_deferred=None,
               halted_at='')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), outer.__file__, 'exec'), env)
    entry = next(n for n in main.body if isinstance(n, ast.If)
                 and n.body and "_phase_runner('phase3')" in ast.unparse(n.body[0]))
    entered = eval(compile(ast.Expression(entry.test), outer.__file__, 'eval'), env)
    return entered, env


def _actual_late_rollup(env, phase3_started):
    import ast
    import vibe_ic_one_shot_runner as outer
    env.update(_phase3_ran=True, _phase_started={'phase3': phase3_started},
               plan=[('phase2', 'NOT_MEASURED', 1), ('phase3', 'PASS', 0)])
    main = next(n for n in ast.parse(Path(outer.__file__).read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == '_main')
    node = next((n for n in main.body if isinstance(n, ast.If)
                 and '_resolve_phase2_pad_top(' in ast.unparse(n)), None)
    if node:
        exec(compile(ast.Module(body=[node], type_ignores=[]), outer.__file__, 'exec'), env)
    return env['plan'][0][1:]


def _late_pad_producer(project, monkeypatch, *, outcome='pass'):
    import phase3_one_shot_runner as phase3
    fsf = _fsf()
    monkeypatch.setattr(fsf, 'default_dispatch', _FakeSim(
        (lambda case, nv: (nv - 1, nv)) if outcome == 'sim_fail' else None))
    monkeypatch.setattr(fsf, 'default_model_resolver', _resolver)

    def write_pad(p, *_args, **_kwargs):
        if outcome not in ('missing_pad', 'pad_fail'):
            _write(p / 'phase3/stage3/pnr/chip_top_io.v', CHIP_TOP_V)
            _write(p / 'reports/phase3/io_pad_chip_top.json', json.dumps({
                'verdict': 'WROTE', 'chip_top_module': 'chip_top', 'core_module': CORE,
                'chip_top_verilog': 'phase3/stage3/pnr/chip_top_io.v'}))
            _supplement_integrity_input(p, author_cases=False)
            if outcome == 'old_pad':
                import os
                import time
                for target in ('phase3/stage3/pnr/chip_top_io.v',
                               'reports/phase3/io_pad_chip_top.json'):
                    os.utime(p / target, (time.time() - 30, time.time() - 30))
        return phase3.StepResult('io_pad_chip_top_gen',
                                 'FAIL' if outcome == 'pad_fail' else 'PASS')

    monkeypatch.setattr(phase3, 'step_io_pad_chip_top_gen', write_pad)
    if outcome == 'generator_error':
        def unavailable(*_a, **_kw):
            raise OSError('neutral generator unavailable')
        monkeypatch.setattr(fsf, 'generate', unavailable)
    return phase3._padring_producer_dispatch(project, None, None)


def test_default_outer_reaches_phase3_for_only_its_pad_top_obligation(tmp_path, monkeypatch):
    project, report, started = _phase2_pad_fixture(tmp_path, monkeypatch)
    entered, env = _actual_outer_phase3_entry(project, report, started)
    assert entered is True
    owed = env['_phase2_pad_top_deferred']
    assert (owed['status'], owed['state'], owed['owner']) == (
        'NOT_MEASURED', 'DEFERRED', 'phase3.io_pad_chip_top_gen')
    assert owed['phase2_process'] == {'verdict': 'NOT_MEASURED', 'rc': 1}
    assert report['verdict'] == 'NOT_MEASURED'


def test_default_late_pad_population_resolves_with_actual_terminal_consumer(
        tmp_path, monkeypatch, arith_class):
    import time
    project, report, started = _phase2_pad_fixture(tmp_path, monkeypatch)
    entered, env = _actual_outer_phase3_entry(project, report, started)
    phase3_started = time.time()
    if entered:
        res = _late_pad_producer(project, monkeypatch)
        assert res.extras.get('full_stack_functional_terminal', {}).get('verdict') == 'PASS'
    assert _actual_late_rollup(env, phase3_started) == ('PASS', 0)
    rec = json.loads(_fsf().record_path(project).read_text())
    assert rec['counts']['executed'] > 0
    assert gate.functional_full_stack_verdict(project)[0] == 0
    # The original child report and its failed early measurement remain history.
    assert json.loads((project / 'reports/orchestrator/phase2_one_shot.json').read_text())['verdict'] == 'NOT_MEASURED'


@pytest.mark.parametrize('mutation', ['phase2_fail', 'extra_incomplete', 'extra_gate_fail',
                                     'wrong_gate', 'wrong_rc', 'empty_ledger',
                                     'missing_audit_row', 'scoped_audit', 'stale_gate'])
def test_default_phase2_other_obligations_still_block(tmp_path, monkeypatch, mutation):
    import os
    project, report, started = _phase2_pad_fixture(tmp_path, monkeypatch)
    audit_path = project / 'reports/phase2/gates/phase2_compliance.json'
    audit = json.loads(audit_path.read_text())
    if mutation == 'phase2_fail':
        report['steps'][0]['status'] = 'FAIL'
        report['verdict'] = 'FAIL'
    elif mutation == 'extra_incomplete':
        audit['steps'][0].update(status='NOT_MEASURED', reason_class='partial_population')
    elif mutation == 'extra_gate_fail':
        audit['gate_execution_ledger'].append({'gate': 'neutral_measurable', 'verdict': 'FAIL', 'rc': 1})
    elif mutation == 'wrong_gate':
        audit['gate_execution_ledger'][0]['gate'] = 'unrelated_checker'
    elif mutation == 'wrong_rc':
        audit['gate_execution_ledger'][0]['rc'] = 1
    elif mutation == 'empty_ledger':
        audit['gate_execution_ledger'] = []
    elif mutation == 'missing_audit_row':
        audit['steps'].pop(0)
    elif mutation == 'scoped_audit':
        audit['scope']['stage_id'] = 'stage1'
    elif mutation == 'stale_gate':
        path = project / 'reports/phase2/gates/bit_level_full_stack.json'
        os.utime(path, (started - 30, started - 30))
    audit_path.write_text(json.dumps(audit))
    _write(project / 'reports/orchestrator/phase2_one_shot.json', json.dumps(report))
    entered, env = _actual_outer_phase3_entry(project, report, started)
    assert entered is False
    assert env['halted_at'] == 'phase2'


@pytest.mark.parametrize('mutation,want', [
    ('absent', 'NOT_MEASURED'), ('missing_pad', 'NOT_MEASURED'),
    ('pad_fail', 'NOT_MEASURED'), ('generator_error', 'NOT_MEASURED'),
    ('sim_fail', 'FAIL'), ('stale', 'NOT_MEASURED'), ('context', 'NOT_MEASURED'),
    ('source', 'NOT_MEASURED'), ('rtl', 'NOT_MEASURED'), ('pad_record', 'NOT_MEASURED'),
    ('input', 'NOT_MEASURED'), ('old_pad', 'NOT_MEASURED'),
    ('protocol_context', 'NOT_MEASURED'),
    ('empty_source', 'NOT_MEASURED'), ('unrelated_source', 'NOT_MEASURED')])
def test_default_late_terminal_missing_wrong_or_failed_still_blocks(
        tmp_path, monkeypatch, arith_class, mutation, want):
    import time
    project, report, started = _phase2_pad_fixture(tmp_path, monkeypatch)
    entered, env = _actual_outer_phase3_entry(project, report, started)
    assert entered is True
    phase3_started = time.time()
    if mutation != 'absent':
        _late_pad_producer(project, monkeypatch, outcome=mutation)
    path = project / 'reports/phase3/gates/full_stack_functional.json'
    if mutation in ('stale', 'context', 'source', 'empty_source', 'unrelated_source'):
        terminal = json.loads(path.read_text())
        if mutation == 'stale':
            terminal['post_padring']['started_at'] = phase3_started - 30
        elif mutation == 'context':
            terminal['post_padring']['project'] = str(tmp_path / 'other_project')
        elif mutation == 'source':
            terminal['post_padring']['source']['bit_level_full_stack_tb_check.py'] = '0' * 64
        elif mutation == 'empty_source':
            terminal['post_padring']['source'] = {}
        else:
            terminal['post_padring']['source'] = {
                'unrelated_source.py': '0' * 64}
        path.write_text(json.dumps(terminal))
    elif mutation == 'rtl':
        p = project / f'phase2/stage1/rtl/{CORE}.v'
        p.write_text(p.read_text() + '\n// changed current RTL\n')
    elif mutation == 'pad_record':
        p = project / 'reports/phase3/io_pad_chip_top.json'
        p.write_text(p.read_text() + '\n')
    elif mutation == 'input':
        p = project / 'phase1/generated_docs/L10_TEST_CASES.json'
        p.write_text(p.read_text() + '\n')
    elif mutation == 'protocol_context':
        p = project / 'phase1/generated_docs/L3_CMD_PROTOCOL.json'
        p.write_text(json.dumps({'opcodes': [{'name': 'new_command', 'code': 1}]}))
    status, rc = _actual_late_rollup(env, phase3_started)
    assert status == want and rc != 0
    if mutation == 'generator_error':
        assert json.loads(path.read_text())['reason_class'] == 'EXECUTION_ERROR'


def test_default_late_actual_pad_generator_then_functional_terminal(
        tmp_path, monkeypatch, arith_class):
    """The real pad source producer writes the top; only the simulator is a stand-in."""
    import time
    import io_pad_chip_top_gen as pads
    import phase3_one_shot_runner as phase3
    import test_io_pad_chip_top_gen as pad_fixture
    project, report, started = _phase2_pad_fixture(tmp_path, monkeypatch)
    # The PDK helper is the established neutral LEF/config corpus. The real
    # generator reads this inline INPUT and the project's actual L9 ports.
    pdk_root = pad_fixture._pdk(tmp_path / 'neutral_pdk')
    _write(pdk_root / 'testpdk/libs.ref/testlib_io/lib/io.lib', '''library(neutral) {
cell(testlib_io__in) {
pin(PAD) {
direction: input;
is_pad: true;
}
pin(Y) {
direction: output;
function: "PAD";
}
}
cell(testlib_io__bi) {
pin(PAD) {
direction: inout;
is_pad: true;
function: "A";
three_state: "OE";
}
pin(A) {
direction: input;
}
pin(OE) {
direction: input;
related_power_pin: "VDDIO";
}
pin(TIELO) {
direction: output;
function: "0";
related_power_pin: "VDDIO";
}
}
}
''')
    # This pad-generator API control uses the declared direct synthetic
    # netlist. It does not claim a native LibreLane synthesis receipt.
    _write(project / 'phase3/librelane_switch.json', json.dumps({'steps': {'9': 'direct'}}))
    _write(project / f'phase2/stage2/synth/{CORE}_synth.v', CORE_V)
    _write(project / 'input/docs/L3_external_interface.md', '''---
layer: L3
---
# External interface
The I/O cell library is delegated to the PDK i/o pad defaults.
## Physical Pad Placement
| Pad side | signals |
|---|---|
| South (S) | `rst` |
| East (E) | `clk` |
| North (N) | `x[7:0]` |
| West (W) | `y` / `p` |
''')

    def actual_pad(p, *_a, **_k):
        rc, produced = pads.run(p, str(pdk_root), 'testpdk')
        assert rc == 0 and produced['verdict'] == 'WROTE', produced
        _write(p / 'reports/phase3/io_pad_chip_top.json', json.dumps(produced))
        _supplement_integrity_input(p, author_cases=False, models=models(p, set(), None)[0])
        return phase3.StepResult('io_pad_chip_top_gen', 'PASS')

    monkeypatch.setattr(phase3, 'step_io_pad_chip_top_gen', actual_pad)
    fsf = _fsf()
    monkeypatch.setattr(fsf, 'default_dispatch', _FakeSim())

    def models(p, used, _container):
        record = json.loads((p / 'reports/phase3/io_pad_chip_top.json').read_text())
        cells = {}
        for item in record['pad_instances'].values():
            terminal, core_pin = item['terminal'], item['core_pin']
            if item['direction'] == 'input':
                cells[item['master']] = (
                    f'module {item["master"]}(input {terminal}, output {core_pin}); '
                    f'assign {core_pin} = {terminal}; endmodule\n')
            else:
                cells[item['master']] = (
                    f'module {item["master"]}(inout {terminal}, input {core_pin}, input OE, output TIELO); '
                    f'assign TIELO = 1\'b0; assign {terminal} = OE ? 1\'bz : {core_pin}; endmodule\n')
        text = ''.join(cells.values())
        source = _write(p / 'input/models/neutral_pad_models.v', text)
        return {str(source): text}, 'neutral pad models'

    monkeypatch.setattr(fsf, 'default_model_resolver', models)
    entered, env = _actual_outer_phase3_entry(project, report, started)
    phase3_started = time.time()
    if entered:
        result = phase3._padring_producer_dispatch(project, None, None)
        assert result.status == 'PASS'
        assert result.extras.get('full_stack_functional_terminal', {}).get('verdict') == 'PASS', result.extras
        produced = json.loads((project / 'reports/phase3/io_pad_chip_top.json').read_text())
        assert len(produced['pad_instances']) == 12
    assert _actual_late_rollup(env, phase3_started) == ('PASS', 0)


# Issue 3132: tiny PUBLIC native components. No owner design or oracle is used.
# The INPUT author states the schedule before any producer/simulator executes.
_TIMED_CONFIGS = {
    'core4': (4, False, 10, 0, 0, False, 'clocked_reset', 1),
    'wrapped4_zero': (4, True, 10, 0, 0, False, 'clocked_reset', 1),
    'core8_renamed': (8, False, 18, 0, 0, True, 'clocked_reset', 1),
    'wrapped8_delayed': (8, True, 18, 1.2, 1.4, True, 'clocked_reset', 1),
    'wrapped12_continuous': (12, True, 14, 0.3, 0.8, False, 'continuous', 0),
}


def _timed_input(root, key, *, mode='good', refusal=None):
    """Self-authored serial multiply, same declarations/bytes in all proof arms."""
    fs = _fsf()
    width, wrapped, period, cd, od, renamed, rearm, latency = _TIMED_CONFIGS[key]
    root = Path(root)
    gd = root / 'phase1/generated_docs'; gd.mkdir(parents=True)
    rd = root / 'phase2/stage1/rtl'; rd.mkdir(parents=True)
    (root / 'plugin_output').mkdir()
    names = ['clk', 'rst', 'x', 'y', 'p']
    if renamed:
        names = ['i_clk', 'i_rst', 'operand_word', 'serial_bit', 'result_bit']
    c, r, x, y, p = names
    cases = [{'name': name, 'kind': 'functional_vector', 'expected': '100% PASS',
              'coverage_scope': scope} for name, scope in [
        ('operand_limits', 'Operand boundaries: zero, one, MAX; all Cartesian combinations'),
        ('transaction_sequence', 'Consecutive transactions: at least 16 operand pairs using declared rearm, no extra idle cycles'),
        ('reset_situations', 'Synchronous reset held, released, and asserted during computation; between-edge reset pulses must not reset'),
    ]]
    (gd / 'L2_FRS.json').write_text(json.dumps({'ic_class': 'digital_arithmetic_primitive',
        'frs_sections': [{'content': f'{p} = ({x} * {y}) mod 2^{width}; serial-parallel multiply'}]}))
    (gd / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({
        'top_module': 'public_serial_product', 'ic_class': 'digital_arithmetic_primitive',
        'top_ports': [{'name': name, 'direction': d, 'width': w} for name, d, w in
                      [(c, 'input', 1), (r, 'input', 1), (x, 'input', width),
                       (y, 'input', 1), (p, 'output', 1)]],
        'clocks': [{'name': c, 'period_ns': period}],
        'reset_domains': [{'name': r, 'polarity': 'active_high', 'sync': 'sync'}]}))
    (gd / 'L10_TEST_CASES.json').write_text(json.dumps({'test_cases': cases}))
    reset = "1'b0" if mode == 'ignored_reset' else r
    delay_cycles = latency + int(mode == 'wrong_cycle')
    expression = "1'bx" if mode == 'unknown' else ('~total[0]' if mode == 'wrong_product' else 'total[0]')
    regs = ''.join(f'reg pipe{i}=0;\n' for i in range(delay_cycles))
    reset_pipe = ''.join(f'pipe{i}<=0; ' for i in range(delay_cycles))
    pipeline = ''.join(f'pipe{i}<=' + (expression if i == 0 else f'pipe{i-1}') + '; '
                       for i in range(delay_cycles))
    output = f'pipe{delay_cycles-1}' if delay_cycles else expression
    # LSB recurrence derives each product bit from the partial sum; the last
    # bit discards the carry (mod 2^N), allowing the declared continuous rearm.
    core = rd / 'public_serial_product.v'
    core.write_text(f'''`timescale 1ns/1ps
module public_serial_product(input {c}, {r}, input [{width-1}:0] {x}, input {y}, output reg {p}=0);
reg [{width}:0] carry=0;
wire [{width}:0] total = carry + ({y} ? {{1'b0,{x}}} : 0);
integer index=0;
{regs}always @(posedge {c}) begin
 if ({reset}) begin carry<=0; index<=0; {p}<=0; {reset_pipe}end
 else begin
  carry <= (index=={width-1}) ? 0 : (total >> 1);
  index <= (index=={width-1}) ? 0 : index+1;
  {pipeline}{p} <= {output};
 end
end
endmodule
''')
    binding = {}
    if wrapped:
        _write(root / 'input/submission_template/SELF_TAPEOUT.txt', 'self tape-out\n')
        top = root / 'phase3/stage3/pnr/public_surface.v'
        _write(top, f'''`timescale 1ns/1ps
module public_surface(input {c}, {r}, input [{width-1}:0] {x}, input {y}, output {p});
wire selected_clock, core_result;
PUBLIC_CLK clock_pad(.A({c}), .Y(selected_clock));
public_serial_product core(.{c}(selected_clock), .{r}({r}), .{x}({x}), .{y}({y}), .{p}(core_result));
PUBLIC_OUT output_pad(.A(core_result), .Y({p}));
endmodule
''')
        model = root / 'input/models/public_delay.v'
        _write(model, f'''`timescale 1ns/1ps
module PUBLIC_CLK(input A, output Y); buf #{cd}(Y,A); endmodule
module PUBLIC_OUT(input A, output Y); buf #{od}(Y,A); endmodule
''')
        _write(root / fs.CHIP_TOP_RECORD_REL, json.dumps({
            'verdict': 'WROTE', 'core_module': 'public_serial_product',
            'chip_top_module': 'public_surface', 'chip_top_verilog': str(top.relative_to(root))}))
        binding = {str(f.relative_to(root)): fs.sha256_file(f) for f in (top, model)}
    observation = {'clock': c, 'output': p, 'settle_ns': cd + od,
                   'sample_offset_ns': cd + od + 0.75, 'binding': binding}
    if refusal == 'stale_model':
        observation['binding']['input/models/public_delay.v'] = '0' * 64
    elif refusal == 'wrong_clock':
        observation['clock'] = 'absent_clock'
    elif refusal == 'outside_cycle':
        observation['sample_offset_ns'] = period / 2
    elif refusal == 'before_settle':
        observation['sample_offset_ns'] = cd + od
    declaration = {'bit_order': 'LSB_first', 'latency_cycles': latency,
        'latency_cycles_origin': 'settled_edge_offset', 'integer_encoding': 'unsigned',
        'reset_polarity': 'active_high', 'transaction_rearm': rearm,
        'rearm_reset_cycles': 2, 'parallel_hold': 'through_final_product_bit',
        'verification_stimuli': {'arithmetic_observation': {
            ('public_surface' if wrapped else 'public_serial_product'): observation}}}
    if refusal == 'missing':
        declaration['verification_stimuli'] = {}
    (root / 'plugin_output/declaration.json').write_text(json.dumps(declaration, sort_keys=True))
    return cases


def _timed_fixture(tmp_path, key, *, mode='good', refusal=None):
    root = tmp_path / 'public_input'
    frozen = os.environ.get('R70_NEUTRAL_ROOT')
    if frozen:
        shutil.copytree(Path(frozen) / f'{key}-{mode}-{refusal or "bound"}', root)
        for file in root.rglob('*'):
            if file.is_file():
                file.chmod(0o644)
    else:
        _timed_input(root, key, mode=mode, refusal=refusal)
    paths = [*root.glob('phase1/generated_docs/*.json'),
             root / 'plugin_output/declaration.json',
             *root.glob('phase2/stage1/rtl/*.v'), *root.glob('input/**/*'),
             *root.glob('phase3/stage3/pnr/*.v'), *root.glob('reports/**/*.json')]
    inventory = {str(f.relative_to(root)): _fsf().sha256_file(f) for f in paths if f.is_file()}
    (root / 'frozen_input_hashes.json').write_text(json.dumps(inventory, sort_keys=True, indent=2))
    return root


def _timed_native(root):
    # Native executable dispatch is the production default. The only injected
    # dependency supplies self-authored public model bytes, without any PDK.
    model = root / 'input/models/public_delay.v'
    resolver = (lambda *args: ({str(model): model.read_text()}, 'public declared delay model'))
    # Observe real Popen handles without substituting any simulator result.
    launched = []
    real_popen = subprocess.Popen
    def observed_popen(*args, **kwargs):
        started = time.time_ns()
        process = real_popen(*args, **kwargs)
        launched.append((process, {'argv': args[0], 'pid': process.pid,
                                  'parent_pid': os.getpid(), 'started_ns': started}))
        return process
    with patch.object(subprocess, 'Popen', observed_popen):
        result = _fsf().generate(root, model_resolver=resolver)
    handles = []
    for process, receipt in launched:
        receipt.update(rc=process.poll(), observed_terminal_ns=time.time_ns())
        assert receipt['rc'] is not None, receipt
        handles.append(receipt)
    (root / 'native_handles.json').write_text(json.dumps(handles, indent=2))
    rc, consumed, sentinel = gate.functional_full_stack_verdict(root)
    (root / 'consumer.json').write_text(json.dumps({'rc': rc, 'report': consumed, 'sentinel': sentinel}, indent=2))
    return result, rc, consumed


@pytest.mark.parametrize('key', list(_TIMED_CONFIGS))
def test_declared_timing_native_fullstack_and_consumer(tmp_path, key):
    root = _timed_fixture(tmp_path, key)
    result, rc, consumed = _timed_native(root)
    assert result['verdict'] == 'PASS' and rc == 0, (result, consumed)
    assert result['counts']['passed'] == 3 and result['counts']['executed'] == 3
    width, wrapped, period, cd, od, renamed, rearm, latency = _TIMED_CONFIGS[key]
    top = 'public_surface' if wrapped else 'public_serial_product'
    for entry in result['cases']:
        tb = root / entry['tb']; plan = aog._scenario_header(tb)
        transcript = (root / entry['run_log']).read_text()
        match = re.search(r'^ARITH_SCENARIO_DONE transactions=(\d+) comparisons=(\d+) errors=(\d+) held_edges=(\d+)$', transcript, re.M)
        assert match and tuple(map(int, match.groups()[:3])) == (plan['transactions'], plan['comparisons'], 0)
        expected_transactions = {'operand_limits': 9, 'transaction_sequence': 16, 'reset_situations': 180}[entry['name']]
        assert plan['transactions'] == expected_transactions
        assert plan['comparisons'] == width * expected_transactions
        assert entry['run_rc'] == 0 and entry['build_rc'] == 0
        assert _fsf().instance_count(tb.read_text(), top) == 1
        assert plan['observation']['clock_period_ns'] == period
        assert plan['observation']['sample_offset_ns'] == cd + od + 0.75
        assert plan['framing']['settled_latency'] == latency
        assert len(plan['pairs']) == (9 if entry['name'] == 'operand_limits' else
                                     16 if entry['name'] == 'transaction_sequence' else 20)
        # Independently inspect the actual simulator clock waveform, rather
        # than accepting the producer's claimed period in the plan header.
        trace = (root / entry['trace']['vcd']).read_text()
        clock = 'i_clk' if renamed else 'clk'
        symbol = re.search(r'\$var \w+ 1 (\S+) ' + clock + r' \$end', trace).group(1)
        assert '$timescale\n\t1ps\n$end' in trace
        time = 0; rising = []
        for line in trace.splitlines():
            if line.startswith('#'):
                time = int(line[1:])
            elif line == '1' + symbol:
                rising.append(time)
        assert len(rising) > 2 and set(b - a for a, b in zip(rising, rising[1:])) == {period * 1000}
    assert not (root / 'input/tb').exists()


@pytest.mark.parametrize('mode', ['wrong_product', 'wrong_cycle', 'ignored_reset', 'unknown'])
def test_declared_timing_native_bad_design_stays_blocking(tmp_path, mode):
    root = _timed_fixture(tmp_path, 'wrapped8_delayed', mode=mode)
    result, rc, consumed = _timed_native(root)
    assert result['verdict'] == 'FAIL' and rc == 1, (result, consumed)
    assert result['counts']['failed'] > 0
    for entry in result['cases']:
        assert entry['build_rc'] == 0
        assert entry['run_rc'] in (0, 1)
        plan = aog._scenario_header(root / entry['tb'])
        transcript = (root / entry['run_log']).read_text()
        match = re.search(r'^ARITH_SCENARIO_DONE transactions=(\d+) comparisons=(\d+) errors=(\d+) held_edges=(\d+)$', transcript, re.M)
        assert match and tuple(map(int, match.groups()[:2])) == (plan['transactions'], plan['comparisons'])
    assert consumed['verdict'] == 'FAIL'


@pytest.mark.parametrize('refusal', ['missing', 'stale_model', 'wrong_clock', 'outside_cycle', 'before_settle'])
def test_declared_timing_unsupported_contract_refuses_before_native(tmp_path, refusal):
    root = _timed_fixture(tmp_path, 'wrapped8_delayed', refusal=refusal)
    calls = []
    def forbidden(*args):
        calls.append(args)
        pytest.fail('unsupported timing dispatched a simulator')
    model = root / 'input/models/public_delay.v'
    result = _fsf().generate(root, dispatch=forbidden, model_resolver=lambda *args: ({str(model): model.read_text()}, 'public model'))
    assert not calls and result['verdict'] == 'NOT_MEASURED', result
    assert result['counts']['executed'] == 0 and result['counts']['rows'] == 3
    rc, consumed, _ = gate.functional_full_stack_verdict(root)
    assert rc == 2 and consumed['verdict'] == 'NOT_MEASURED'
    assert result.get('arithmetic_scenario_requests')
    assert all('plugin_output/declaration.json#/verification_stimuli/arithmetic_observation/' in
               '; '.join(r['unsupported_requirements'])
               for r in result['arithmetic_scenario_requests'])


@pytest.mark.parametrize('mutation', ['missing_population', 'stale_declaration', 'stale_model', 'stale_input_model'])
def test_declared_timing_consumer_rechecks_population_and_identity(tmp_path, mutation):
    root = _timed_fixture(tmp_path, 'wrapped8_delayed')
    result, rc, consumed = _timed_native(root)
    assert result['verdict'] == 'PASS' and rc == 0, (result, consumed)
    fs = _fsf()
    if mutation == 'missing_population':
        entry = result['cases'][0]; log = root / entry['run_log']
        shutil.copy2(log, log.with_suffix('.original'))
        log.write_text(re.sub(r'^ARITH_SCENARIO_DONE.*\n', '', log.read_text(), flags=re.M))
        entry['run_log_sha256'] = fs.sha256_file(log)
        fs.record_path(root).write_text(json.dumps(result))
    elif mutation == 'stale_declaration':
        file = root / 'plugin_output/declaration.json'
        file.write_text(file.read_text() + ' ')
    elif mutation == 'stale_model':
        file = root / result['models'][0]['path']
        file.write_text(file.read_text() + '\n// changed model identity\n')
    else:
        file = root / 'input/models/public_delay.v'
        file.write_text(file.read_text() + '\n// changed original selected model identity\n')
    rc, consumed, _ = gate.functional_full_stack_verdict(root)
    (root / 'mutated_consumer.json').write_text(json.dumps({'rc': rc, 'report': consumed}, indent=2))
    assert rc == 2 and consumed['verdict'] == 'NOT_MEASURED', consumed


@pytest.mark.parametrize('rc,record,marker,state', [
    (0, 'transactions=9 comparisons=72 errors=1 held_edges=2', True, 'failed'),
    (1, 'transactions=9 comparisons=72 errors=0 held_edges=2', False, 'failed'),
    (0, 'transactions=0 comparisons=0 errors=0 held_edges=2', True, 'errored'),
    (0, 'transactions=9 comparisons=72 errors=0 held_edges=2\nARITH_SCENARIO_DONE transactions=9 comparisons=72 errors=0 held_edges=2', True, 'errored'),
    (0, 'transactions=9 comparisons=72 errors=0 held_edges=2', True, 'passed'),
], ids=['errors_override_pass', 'nonzero_rc_blocks', 'empty_population', 'duplicate_population', 'canonical_success'])
def test_arithmetic_population_counters_keep_strict_score_precedence(rc, record, marker, state):
    # Source-only transcript controls, separate from the native DUT arms above.
    text = 'ARITH_SCENARIO_DONE ' + record + '\n'
    if marker:
        text += '[TB counter_case] PASS: scenario\n'
    assert _fsf().score_transcript('counter_case', rc, text)['state'] == state


# Issue3132 random residual: public tiny native DUT, no field/owner artifacts.
def _random_contract_input(tmp_path, *, key='wrapped8_delayed', mode='good',
                           refusal=None, bit_order='LSB_first'):
    root = tmp_path / 'random_public_input'
    _timed_input(root, key, mode=mode, refusal=refusal)
    case = {'name': 'random_contract', 'kind': 'functional_vector',
            'stimulus': 'Random at least 10000 operand pairs using the stated serial framing.',
            'expected': '100% PASS'}
    gd = root / 'phase1/generated_docs'
    (gd / 'L10_TEST_CASES.json').write_text(json.dumps({'test_cases': [case]}))
    declaration = root / 'plugin_output/declaration.json'
    data = json.loads(declaration.read_text()); data['bit_order'] = bit_order
    declaration.write_text(json.dumps(data, sort_keys=True))
    inventory = {str(f.relative_to(root)): _fsf().sha256_file(f)
                 for f in root.rglob('*') if f.is_file()}
    (root / 'random_public_input_hashes.json').write_text(
        json.dumps(inventory, sort_keys=True, indent=2))
    return root


def _random_assert_native_result(root, result, rc, consumed, expected):
    entry, = result['cases']
    assert result['verdict'] == expected and rc == (0 if expected == 'PASS' else 1), (result, consumed)
    assert entry['declared_population'] == 10000
    assert entry['checks']['total'] == 10000
    assert entry['build_rc'] == 0 and entry['run_rc'] is not None
    handles = json.loads((root / 'native_handles.json').read_text())
    assert len(handles) == 2 and all(h['rc'] is not None for h in handles)
    if expected == 'PASS':
        assert entry['run_rc'] == 0 and entry['checks']['passed'] == 10000
        assert consumed['counts']['executed'] == consumed['counts']['passed'] == 1
    return entry


@pytest.mark.parametrize('key', ['core8_renamed', 'wrapped8_delayed'])
def test_issue3132_random_uses_the_declared_fixed_schedule(tmp_path, key):
    root = _random_contract_input(tmp_path, key=key)
    result, rc, consumed = _timed_native(root)
    entry = _random_assert_native_result(root, result, rc, consumed, 'PASS')
    tb = root / entry['tb']; text = tb.read_text()
    plan = aog._scenario_header(tb)
    assert plan is not None and plan['scenario'] == 'random_transactions'
    assert plan['transactions'] == 10000 and plan['comparisons'] == 80000
    width, wrapped, period, cd, od, renamed, rearm, latency = _TIMED_CONFIGS[key]
    assert plan['framing']['settled_latency'] == latency == 1
    assert plan['observation']['clock_period_ns'] == period == 18
    assert plan['observation']['sample_offset_ns'] == cd + od + 0.75
    assert not any(token in text for token in ('MAXOFF', '_boff', '_drive_capture(1)'))
    log = (root / entry['run_log']).read_text()
    assert 'ORACLE_TB_DONE pass=10000/10000' in log
    assert 'ORACLE_TB_FRAMING in_order=0 out_order=0 latency_cycles=1 latency_origin=settled_edge_offset' in log


def test_issue3132_random_cannot_search_another_cycle(tmp_path):
    root = _random_contract_input(tmp_path, mode='wrong_cycle')
    result, rc, consumed = _timed_native(root)
    _random_assert_native_result(root, result, rc, consumed, 'FAIL')


def test_issue3132_random_cannot_search_another_bit_order(tmp_path):
    root = _random_contract_input(tmp_path, bit_order='MSB_first')
    result, rc, consumed = _timed_native(root)
    _random_assert_native_result(root, result, rc, consumed, 'FAIL')


@pytest.mark.parametrize('mode', ['wrong_product', 'ignored_reset', 'unknown'])
def test_issue3132_random_genuine_native_negative_controls(tmp_path, mode):
    root = _random_contract_input(tmp_path, mode=mode)
    result, rc, consumed = _timed_native(root)
    _random_assert_native_result(root, result, rc, consumed, 'FAIL')


@pytest.mark.parametrize('refusal', ['missing', 'stale_model', 'before_settle'])
def test_issue3132_random_requires_current_supported_observation(tmp_path, refusal):
    root = _random_contract_input(tmp_path, refusal=refusal)
    result, rc, consumed = _timed_native(root)
    assert result['verdict'] == consumed['verdict'] == 'NOT_MEASURED' and rc == 2, (result, consumed)
    assert result['counts']['executed'] == 0
    assert json.loads((root / 'native_handles.json').read_text()) == []
    assert result['reason_class'] == 'MISSING_OBSERVATION_CONTRACT'


@pytest.mark.parametrize('mutation', ['framing_transcript', 'stale_declaration', 'short_population'])
def test_issue3132_random_strict_consumer_rechecks_contract(tmp_path, mutation):
    root = _random_contract_input(tmp_path)
    result, rc, consumed = _timed_native(root)
    _random_assert_native_result(root, result, rc, consumed, 'PASS')
    fs = _fsf(); record = fs.record_path(root); rec = json.loads(record.read_text()); entry, = rec['cases']
    if mutation == 'stale_declaration':
        path = root / 'plugin_output/declaration.json'
        d = json.loads(path.read_text()); d['latency_cycles'] = 2
        path.write_text(json.dumps(d, sort_keys=True))
    else:
        path = root / entry['run_log']; text = path.read_text()
        if mutation == 'framing_transcript':
            # A count-correct, hash-current transcript must still obey framing.
            match = re.search(r'(?m)^ORACLE_TB_FRAMING .*$', text)
            assert match, text[-1000:]
            text = text[:match.start()] + 'ORACLE_TB_FRAMING in_order=0 out_order=0 latency_cycles=99 latency_origin=settled_edge_offset' + text[match.end():]
        else:
            text = text.replace('pass=10000/10000', 'pass=9999/9999')
            text = text.replace('transactions=10000 comparisons=80000', 'transactions=9999 comparisons=79992')
        path.write_text(text); entry['run_log_sha256'] = fs.sha256_file(path)
        if mutation == 'framing_transcript' and isinstance(entry.get('arithmetic_scenario'), dict):
            # Refresh descriptive receipt hashes too: refusal must come from
            # re-reading the actual framing, not merely a stale transcript hash.
            measured = entry['arithmetic_scenario']
            measured['transcript_sha256'] = fs.sha256_file(path)
            if isinstance(measured.get('framing'), dict):
                measured['framing']['latency_cycles'] = 99
        record.write_text(json.dumps(rec, indent=2))
    rc, checked, _ = gate.functional_full_stack_verdict(root)
    assert rc != 0 and checked['functional_verified'] is False, checked


def test_issue3132_legacy_native_search_receipt_does_not_evade_current_contract(tmp_path):
    root = _random_contract_input(tmp_path)
    tbg = importlib.import_module('testbench_gen')
    # Build historical search-family evidence with the real old emitter and
    # native dispatch, never a fabricated transcript or simulator verdict.
    with patch.object(tbg, '_emit_case_arithmetic_scenario', return_value=None):
        result, rc, consumed = _timed_native(root)
    entry, = result['cases']
    assert entry['family'] == 'declared_function_golden'
    assert entry['state'] == 'passed' and entry['run_rc'] == 0
    assert entry['checks'] == {'passed': 10000, 'total': 10000}
    log = (root / entry['run_log']).read_text()
    observed = re.search(r'ORACLE_TB_FRAMING in_order=0 out_order=0 latency_cycles=(\d+) latency_origin=settled_edge_offset', log)
    assert observed and int(observed.group(1)) == 2
    declaration = json.loads((root / 'plugin_output/declaration.json').read_text())
    assert declaration['latency_cycles'] == 1
    assert declaration['latency_cycles_origin'] == 'settled_edge_offset'
    assert rc == 2 and consumed['functional_verified'] is False, consumed
