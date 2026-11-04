"""v1.1.64 — spec_artifact_registry: the single-source-of-truth catalog of
structured artifact types. Thin delegating layer over the already-reviewed
canonical parsers/generators, so these tests pin the ROUTING (detect classifies
to the right type + extracts; generate routes to the right generator; prose with
no structural artifact yields nothing).
"""
import sys
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from _prose_handoff_assertions import assert_program_chain_candidate

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import spec_artifact_registry as R  # noqa: E402

_HDR = ("I would like you to implement a module named TopModule with the following\n"
        "interface. All input and output ports are one bit unless otherwise specified.\n\n")

FSM = _HDR + (
    " - input  clk\n - input  reset\n - input  in\n - output out\n\n"
    "Moore state machine. Synchronous active high reset to state A.\n\n"
    "  state | next state in=0, next state in=1 | output\n"
    "  A | A, B | 0\n  B | C, B | 0\n  C | A, D | 0\n  D | C, B | 1\n")

TRUTH = _HDR + (
    " - input  x3\n - input  x2\n - input  x1\n - output f\n\n"
    "Implement the combinational circuit described by this truth table:\n\n"
    "  x3 | x2 | x1 | f\n  0 | 0 | 0 | 0\n  0 | 0 | 1 | 1\n  0 | 1 | 0 | 1\n  0 | 1 | 1 | 0\n"
    "  1 | 0 | 0 | 1\n  1 | 0 | 1 | 0\n  1 | 1 | 0 | 0\n  1 | 1 | 1 | 1\n")

PROSE = _HDR + (
    " - input  clk\n - input  reset\n - output [7:0] q\n\n"
    "Build a counter that increments every clock and resets to 0 when reset is high.\n")


def test_detect_fsm_transition_table():
    arts = R.detect(FSM)
    keys = [a["type"] for a in arts]
    assert "fsm_transition_table" in keys
    fsm = next(a for a in arts if a["type"] == "fsm_transition_table")
    assert set(fsm["structured"]["states"]) == {"A", "B", "C", "D"}
    assert fsm["structured"]["reset"]["state"] == "A"
    assert "L6" in fsm["l_docs"]                     # taxonomy home


def test_detect_truth_table():
    arts = R.detect(TRUTH)
    tt = next((a for a in arts if a["type"] == "truth_table"), None)
    assert tt is not None
    assert tt["structured"]["output"] == "f"
    assert len(tt["structured"]["rows"]) == 8


def test_generate_routes_to_correct_generator():
    k, rtl = R.generate(FSM)
    assert k == "fsm_transition_table" and rtl and "module TopModule" in rtl
    k2, rtl2 = R.generate(TRUTH)
    assert k2 == "truth_table" and rtl2 and "module TopModule" in rtl2


def test_prose_yields_no_structural_artifact():
    # A plain prose counter has no table/k-map/FSM-table artifact, so nothing here
    # can be deterministically SOLVED and `generate` is None (honest: this is the
    # AI's job).
    #
    # THIS USED TO ASSERT `R.detect(PROSE) == []` AND THAT SAID TWO THINGS AT
    # ONCE. The claim the test is named for is the first one; the empty list also
    # asserted that the registry recognises NOTHING in this prompt, which was only
    # true while the registry could not read an interface. The prompt states three
    # ports, `pinout_table` is a live catalog element type, and reporting an
    # interface is not a solve -- a row that can synthesise RTL carries
    # `generate`, and the assertion below names exactly those and requires none of
    # them to fire. The bare `== []` could not distinguish "solved nothing" from
    # "recognised nothing", so it is split into the two claims it was standing in
    # for.
    detected = R.detect(PROSE)
    assert R.generate(PROSE) == (None, None)
    solvable = {a.key for a in R.REGISTRY if a.generate}
    assert [d["type"] for d in detected if d["type"] in solvable] == []
    pinout = next((d for d in detected if d["type"] == "pinout_table"), None)
    assert pinout is not None, "the prompt declares clk, reset and q"
    assert pinout["structured"]["pin_count"] == 3


def test_registry_catalog_is_nonempty_and_typed():
    assert "fsm_transition_table" in R.types()
    assert "truth_table" in R.types()
    for a in R.REGISTRY:
        assert a.key and a.title and a.l_docs            # every entry has a taxonomy home


_PUBLIC_CASES = {
    'counter': (
        'counter_popcount',
        'Implement a 4-bit up counter that counts from 0 through 15, inclusive, '
        'with a period of 16. The reset input is active high synchronous, and '
        'should reset the counter to 0. When enable is high the counter increments, '
        'and when enable is low the counter holds. Reset has priority over enable.\n'
        'module LogicBlock(input clk, input enable, input reset, output reg [3:0] q);\n',
        '''module tb;
reg clk=0, enable=0, reset=1;
wire [3:0] positional_q, named_q;
LogicBlock positional(clk, enable, reset, positional_q);
LogicBlock named(.clk(clk), .enable(enable), .reset(reset), .q(named_q));
initial begin
 #1;clk=1;#1;clk=0;reset=0;enable=1;#1;clk=1;#1;
 $display("COUNTER named=%d positional=%d",named_q,positional_q);
 if(named_q !== 4'd1) $fatal(1,"named control failed");
 if(positional_q !== 4'd1) $fatal(1,"positional contract failed");
 $finish;
end
endmodule
'''),
    'interleaved': (
        'comb_gate',
        'Implement two independent AND gates with these exact output functions:\n'
        'p1y: p1a and p1b\np2y: p2a and p2b\n'
        'module LogicBlock(input p1a, input p1b, output p1y, input p2a, input p2b, output p2y);\n',
        '''module tb;
wire p1a=1'b1,p1b=1'b1,p2a=1'b1,p2b=1'b0;
wire p1y,p2y,np1y,np2y;
LogicBlock positional(p1a,p1b,p1y,p2a,p2b,p2y);
LogicBlock named(.p1a(1'b1),.p1b(1'b1),.p1y(np1y),.p2a(1'b1),.p2b(1'b0),.p2y(np2y));
initial begin
 #1;$display("GATES named=%b%b positional=%b%b",np1y,np2y,p1y,p2y);
 if({np1y,np2y} !== 2'b10) $fatal(1,"named control failed");
 if({p1y,p2y} !== 2'b10) $fatal(1,"positional contract failed");
 $finish;
end
endmodule
'''),
}


@pytest.mark.parametrize('family', ['counter', 'interleaved'])
@pytest.mark.parametrize('entry', ['registry', 'chain'])
def test_generated_public_order_reaches_positional_and_named_consumers(tmp_path, family, entry):
    import deterministic_emit_chain as chain
    import module_port_audit as audit
    import rtl_repair_contract as contract
    kind, prompt, tb = _PUBLIC_CASES[family]
    if entry == 'chain':
        result = chain.try_emit_ex(prompt, '', 'LogicBlock')
        assert_program_chain_candidate(result, prompt)
    emitted_kind, rtl = result[:2] if entry == 'chain' else R.generate(prompt, 'LogicBlock')
    assert emitted_kind == kind and rtl
    iverilog, vvp = shutil.which('iverilog'), shutil.which('vvp')
    if not iverilog or not vvp:
        pytest.skip('NOT_RUN: Icarus iverilog/vvp are required for the public connection control')
    dut, bench, compiled = tmp_path / 'dut.sv', tmp_path / 'tb.sv', tmp_path / 'dut.vvp'
    dut.write_text(rtl)
    bench.write_text(tb)
    command = [iverilog, '-g2012', '-s', 'tb', '-o', str(compiled), str(dut), str(bench)]
    build = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert build.returncode == 0, (build.stdout, build.stderr)
    run = subprocess.run([vvp, str(compiled)], capture_output=True, text=True, timeout=20)
    (tmp_path / 'observation.json').write_text(json.dumps({
        'entry': entry, 'emitter': emitted_kind, 'compile_argv': command,
        'compile_rc': build.returncode, 'sim_rc': run.returncode,
        'stdout': run.stdout, 'stderr': run.stderr}, indent=2))
    assert run.returncode == 0, (run.stdout, run.stderr)
    facts = contract.prompt_rtl_source_facts(prompt)
    expected = audit.parse_modules(facts['header'] + '\nendmodule', 'prompt')[0].port_order
    assert audit.parse_modules(rtl, 'program')[0].port_order == expected
    assert contract.validate_prompt_header(
        rtl, prompt, contract.prompt_header_preservation(facts))['verdict'] == 'PASS'


def _generated(monkeypatch, prompt, rtl, top='LogicBlock'):
    from dataclasses import replace
    row = replace(R.REGISTRY[0], key='neutral_order', generate=lambda text, name: rtl)
    monkeypatch.setattr(R, 'REGISTRY', (row,))
    return R.generate(prompt, top)


def test_no_supplied_header_does_not_change_generated_source(monkeypatch):
    rtl = 'module LogicBlock(input b, output y, input a); assign y=a&b; endmodule\n'
    assert _generated(monkeypatch, 'Implement a conjunction of two inputs.', rtl) == ('neutral_order', rtl)


def test_already_ordered_declarations_remain_byte_identical(monkeypatch):
    header = 'module LogicBlock(input wire signed [3:0] a, b, output logic [3:0] y);'
    rtl = '// unchanged prefix\n' + header + '\nassign y=a&b; // unchanged body\nendmodule\n'
    assert _generated(monkeypatch, header, rtl) == ('neutral_order', rtl)


def test_parameters_signed_widths_and_comments_move_with_generated_clauses(monkeypatch):
    import module_port_audit as audit
    import rtl_repair_contract as contract
    parameters = '#(parameter W=$clog2(9), parameter NOTE="keep,(comma)")'
    header = ('module LogicBlock ' + parameters + '(\n'
              ' output logic signed [W-1:0] y,\n'
              ' input wire signed [W-1:0] a,\n'
              ' input logic [W-1:0] b\n);')
    declarations = ('\n input wire signed [W-1:0] a',
                    ' // input comment with a comma, retained\n input logic [W-1:0] b',
                    '\n output logic signed [W-1:0] y\n')
    prefix = '// keep prefix\nmodule LogicBlock ' + parameters + '('
    suffix = ');\n// keep body\nassign y = a ^ b;\nendmodule\n'
    rtl = prefix + ','.join(declarations) + suffix
    kind, result = _generated(monkeypatch, header, rtl)
    assert kind == 'neutral_order'
    assert result == prefix + ','.join((declarations[2], declarations[0], declarations[1])) + suffix
    assert audit.parse_modules(result, 'result')[0].port_order == ['y', 'a', 'b']
    facts = contract.prompt_rtl_source_facts(header)
    assert contract.validate_prompt_header(
        result, header, contract.prompt_header_preservation(facts))['verdict'] == 'PASS'


@pytest.mark.parametrize('generated_declaration,field,expected_token', [
    pytest.param('input wire signed [7:0] a', 'upper_bit', '7', id='width'),
    pytest.param('output wire signed [3:0] a', 'direction', 'output', id='direction'),
    pytest.param('input logic signed [3:0] a', 'net_type', 'logic', id='type'),
    pytest.param('input wire unsigned [3:0] a', 'signedness', 'unsigned', id='signedness'),
])
def test_order_normalization_does_not_replace_generated_declaration_facts(monkeypatch, generated_declaration, field, expected_token):
    import module_port_audit as audit
    import rtl_repair_contract as contract
    header = ('module LogicBlock(input wire signed [3:0] a, '
              'input wire [3:0] b, output wire [3:0] y);')
    rtl = ('module LogicBlock(input wire [3:0] b, ' + generated_declaration
           + ', output wire [3:0] y);\nassign y=a&b;\nendmodule\n')
    kind, result = _generated(monkeypatch, header, rtl)
    assert kind == 'neutral_order'
    assert audit.parse_modules(result, 'result')[0].port_order == ['a', 'b', 'y']
    expected = ('module LogicBlock(' + generated_declaration
                + ', input wire [3:0] b, output wire [3:0] y);\nassign y=a&b;\nendmodule\n')
    # This fixed fixture places a's declaration first. Pin each retained fact
    # as a scalar as well as comparing the complete significant token sequence.
    positions = {'direction': 3, 'net_type': 4, 'signedness': 5, 'upper_bit': 7}
    assert contract._header_tokens(result)[positions[field]] == expected_token
    assert contract._header_tokens(result) == contract._header_tokens(expected)
    assert result[result.index(';'):] == rtl[rtl.index(';'):]
    facts = contract.prompt_rtl_source_facts(header)
    assert contract.validate_prompt_header(
        result, header, contract.prompt_header_preservation(facts))['verdict'] == 'REFUSED'


@pytest.mark.parametrize('header', [
    'module LogicBlock(b,a,y);',
    'module LogicBlock(input a, input a, output y);',
    'module LogicBlock(input a,, input b, output y);',
])
def test_unusable_matching_supplied_headers_decline_order_normalization(monkeypatch, header):
    rtl = 'module LogicBlock(input b, input a, output y); assign y=a&b; endmodule'
    assert _generated(monkeypatch, header, rtl) == (None, None)


@pytest.mark.parametrize('source_kind', ['full_target', 'other_header', 'multiple_headers', 'complete_reference'])
@pytest.mark.parametrize('entry', ['registry', 'chain'])
def test_non_applicable_source_preserves_real_generator_behavior(source_kind, entry):
    import counter_popcount_synth as counter
    import deterministic_emit_chain as chain
    prompt = _PUBLIC_CASES['counter'][1]
    prose, header = prompt.split('module LogicBlock', 1)
    header = 'module LogicBlock' + header.strip()
    reference = header.replace('LogicBlock', 'Reference')
    fragments = {
        'full_target': header + "\nassign q=4'd0;\nendmodule",
        'other_header': reference,
        'multiple_headers': header + '\n' + reference,
        'complete_reference': (reference + "\nassign q=4'd0;\nendmodule\n"
                               'Create a new counter submodule LogicBlock with the same interface.'),
    }
    prompt = prose + fragments[source_kind]
    unchanged = counter.synth(prompt, 'LogicBlock')
    assert unchanged
    if entry == 'registry':
        observed = R.generate(prompt, 'LogicBlock')
    else:
        result = chain.try_emit_ex(prompt, '', 'LogicBlock')
        assert_program_chain_candidate(result, prompt)
        observed = result[:2]
    assert observed == ('counter_popcount', unchanged), observed


@pytest.mark.parametrize('rtl', [
    'module LogicBlock(input [3:0] b, a, output [3:0] y); assign y=a&b; endmodule',
    'module LogicBlock(b,a,y); input [3:0] a,b; output [3:0] y; assign y=a&b; endmodule',
    'module LogicBlock(input [3:0] b, input [3:0] b, output [3:0] y); endmodule',
    'module LogicBlock(input [3:0] b,, input [3:0] a, output [3:0] y); endmodule',
    'module LogicBlock(input [3:0] b, input [3:0] c, output [3:0] y); endmodule',
    'module Other(input [3:0] b, input [3:0] a, output [3:0] y); endmodule',
])
def test_unsupported_generated_declarations_decline_instead_of_inventing_ports(monkeypatch, rtl):
    header = 'module LogicBlock(input [3:0] a, input [3:0] b, output [3:0] y);'
    assert _generated(monkeypatch, header, rtl) == (None, None)


def test_checked_in_non_ansi_source_cannot_supply_missing_header_directions(monkeypatch):
    from _hostpaths import require_repo
    import module_port_audit as audit
    source = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                          'calibration', 'synth_const_no_hilomap_positive.v').read_text()
    name, start, body, _ = next(audit.module_regions(source))
    header = source[start:body]
    assert _generated(monkeypatch, header, source, name) == (None, None)
