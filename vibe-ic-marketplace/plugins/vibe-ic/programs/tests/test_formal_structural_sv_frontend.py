from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import formal_structural_check as fsc


@pytest.mark.parametrize('edge,expected', [('posedge', fsc.PASS), ('negedge', fsc.REFUTED)])
def test_unpacked_sv_structural_read_keeps_native_clock_verdict(tmp_path, edge, expected):
    if shutil.which('yosys') is None:
        pytest.skip('native yosys required')
    rtl = tmp_path / 'm.sv'
    rtl.write_text('module m(input clk,rst,input logic [3:0] d[2],'
                   'output logic [3:0] q[2]); always @(' + edge +
                   ' clk) if(rst) begin q[0]<=0; q[1]<=0; end '
                   'else begin q[0]<=d[0]; q[1]<=d[1]; end endmodule\n')
    result = fsc.check([rtl], 'm',
        [{'rule': 'clock_edge', 'signal': 'clk', 'value': 'posedge'}], tmp_path)
    assert result['verdict'] == expected, result


@pytest.mark.parametrize('reset_test,polarity,timing,expected', [
    ('!rst_n', 'active_low', 'synchronous', fsc.PASS),
    ('rst_n', 'active_low', 'synchronous', fsc.REFUTED),
    ('!rst_n', 'active_low', 'asynchronous', fsc.REFUTED),
])
@pytest.mark.parametrize('variable_write', [False, True])
def test_native_sv_memory_reset_uses_the_existing_lowering(
        tmp_path, reset_test, polarity, timing, expected, variable_write):
    if shutil.which('yosys') is None:
        pytest.skip('native yosys required')
    rtl = tmp_path / 'neutral.sv'
    load = ('else if(we) words[addr]<=d[0];' if variable_write else
            "else begin words[0]<=d[0];words[1]<=d[0]^4'h1;"
            "words[2]<=d[0]^4'h2;words[3]<=d[0]^4'h3;end")
    rtl.write_text('module neutral(input logic clk,rst_n,we,input logic [1:0] addr,'
                   'input logic [3:0] d[2],output logic [3:0] y);'
                   'logic [3:0] words[0:3]; always_ff @(posedge clk) begin '
                   f'if({reset_test}) begin '
                   'words[0]<=0;words[1]<=0;words[2]<=0;words[3]<=0;end '
                   + load + ' end '
                   'assign y=words[addr];endmodule\n')
    result = fsc.check([rtl], 'neutral', [
        {'rule': 'reset_polarity', 'signal': 'rst_n', 'value': polarity},
        {'rule': 'reset_sync', 'signal': 'rst_n', 'value': timing},
    ], tmp_path, klass={'clock': 'clk', 'resets': ['rst_n']})
    assert result['verdict'] == expected, result
    construction, = result['reset_memory_construction']
    assert construction['inside'], construction
    assert all(view['q_count'] == 16 for view in construction['views'].values())
    assert [claim['verdict'] for claim in result['claims']] == [
        fsc.REFUTED if reset_test == 'rst_n' else fsc.PASS,
        fsc.REFUTED if timing == 'asynchronous' else fsc.PASS,
    ], result


@pytest.mark.parametrize('reset_test,timing,expected', [
    ('!rst_n', 'synchronous', fsc.PASS),
    ('rst_n', 'synchronous', fsc.REFUTED),
    ('!rst_n', 'asynchronous', fsc.REFUTED),
])
def test_native_synchronous_reset_dominates_its_data_input(
        tmp_path, reset_test, timing, expected):
    if shutil.which('yosys') is None:
        pytest.skip('native yosys required')
    rtl = tmp_path / 'neutral.v'
    rtl.write_text('module neutral(input clk,rst_n,en,input [3:0] d,'
                   'output reg [3:0] q); always @(posedge clk) '
                   f'if({reset_test}) q<=0; else if(en) q<=d^{{4{{rst_n}}}}; '
                   'endmodule\n')
    result = fsc.check([rtl], 'neutral', [
        {'rule': 'reset_polarity', 'signal': 'rst_n', 'value': 'active_low'},
        {'rule': 'reset_sync', 'signal': 'rst_n', 'value': timing},
    ], tmp_path, klass={'clock': 'clk', 'resets': ['rst_n']})
    assert result['applicability']['inside'], result
    assert result['verdict'] == expected, result


@pytest.mark.parametrize('memory', [False, True])
def test_native_reset_scope_keeps_unclassified_data_paths_open(tmp_path, memory):
    if shutil.which('yosys') is None:
        pytest.skip('native yosys required')
    rtl = tmp_path / 'neutral.sv'
    if memory:
        rtl.write_text('module neutral(input logic clk,rst_n,we,input logic [1:0] addr,'
                       'input logic [3:0] d[2],output logic [3:0] y);'
                       'logic [3:0] words[0:3];always_ff @(posedge clk) '
                       'if(we) words[addr]<=d[0]^{4{rst_n}};'
                       'assign y=words[addr];endmodule\n')
    else:
        rtl.write_text('module neutral(input clk,rst_n,input [3:0] d,'
                       'output reg [3:0] y);always @(posedge clk) '
                       'y<=d^{4{rst_n}};endmodule\n')
    result = fsc.check([rtl], 'neutral', [
        {'rule': 'reset_polarity', 'signal': 'rst_n', 'value': 'active_low'},
        {'rule': 'reset_sync', 'signal': 'rst_n', 'value': 'synchronous'},
    ], tmp_path, klass={'clock': 'clk', 'resets': ['rst_n']})
    assert result['verdict'] == fsc.NOT_DISCHARGED, result
    assert all(claim['verdict'] != fsc.PASS for claim in result['claims']), result


@pytest.mark.parametrize('partial', ['word', 'bit'])
def test_native_memory_reset_requires_each_actual_bus_bit(tmp_path, partial):
    if shutil.which('yosys') is None:
        pytest.skip('native yosys required')
    reset_last = '' if partial == 'word' else 'words[3][3:1]<=0;'
    rtl = tmp_path / 'neutral.sv'
    rtl.write_text('module neutral(input logic clk,rst_n,we,input logic [1:0] addr,'
                   'input logic [3:0] d[2],output logic [3:0] y);'
                   'logic [3:0] words[0:3]; always_ff @(posedge clk) begin '
                   'if(!rst_n) begin words[0]<=0;words[1]<=0;words[2]<=0;'
                   + reset_last + 'end else if(we) words[addr]<=d[0];end '
                   'assign y=words[addr];endmodule\n')
    result = fsc.check([rtl], 'neutral', [
        {'rule': 'reset_polarity', 'signal': 'rst_n', 'value': 'active_low'},
        {'rule': 'reset_sync', 'signal': 'rst_n', 'value': 'synchronous'},
    ], tmp_path, klass={'clock': 'clk', 'resets': ['rst_n']})
    assert result['verdict'] == fsc.NOT_DISCHARGED, result
    construction, = result['reset_memory_construction']
    assert not construction['inside'], construction
    assert all(view['q_count'] == 16 for view in construction['views'].values())
    assert any('without a known reset control' in failure
               for failure in construction['failed_preconditions']), construction
