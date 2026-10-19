"""Frozen neutral spec, actual lint consumer, and narrow scope controls."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import rtl_hygiene_lint as lint

FIXTURES = Path(__file__).parent / 'fixtures' / 'continuous_function_dependencies'
RULE = 'continuous-function-hidden-global'
UNRESOLVED = 'continuous-function-dependency-unresolved'


def findings(tmp_path, text, rule=RULE):
    path = tmp_path / 'subject.sv'
    path.write_text(text)
    return [f for f in lint.lint_file(path) if f.rule == rule]


def test_frozen_hidden_dependency_reaches_actual_lint_file():
    rows = [f for f in lint.lint_file(FIXTURES / 'hidden.sv') if f.rule == RULE]
    assert len(rows) == 1
    assert 'done_a' in rows[0].symbol and 'done_b' in rows[0].symbol
    assert rows[0].severity == 'WARN' and rows[0].block_eligible


def test_explicit_fixture_has_no_hidden_dependency():
    assert not [f for f in lint.lint_file(FIXTURES / 'explicit.sv') if f.rule == RULE]


def test_module_input_and_transitive_helper(tmp_path):
    rows = findings(tmp_path, '''
module transport(input wire request, response, output wire done);
  function automatic bit leaf(input bit a);
    leaf = a & response;
  endfunction
  function automatic bit choose(input bit a);
    choose = leaf(a);
  endfunction
  assign done = choose(request);
endmodule
''')
    assert len(rows) == 1 and 'response' in rows[0].symbol
    assert 'choose' in rows[0].message and 'leaf' in rows[0].message


@pytest.mark.parametrize('text', [
    '''module m(input a, b, output y);
function automatic bit f(input bit a, b); f=a & b; endfunction
assign y=f(a,b); endmodule''',
    '''module m(input a, output y);
parameter bit b=1; localparam bit c=0;
typedef enum logic {Off,On} flag_t;
function automatic bit f(input bit q);
bit local_value; local_value=q ^ b ^ c; f=local_value ^ On;
endfunction
assign y=f(a); endmodule''',
    '''module m(input a, b, output y);
function automatic bit f(input bit a); bit b; b=a; f=b; endfunction
assign y=f(a); endmodule''',
    '''module m(input a, b, output logic y);
function automatic bit f(input bit a); f=a & b; endfunction
always_comb y=f(a); endmodule''',
    '''module m(input a, b, output y);
function automatic bit f(input bit q); f=q & b; endfunction
assign y=f(b); endmodule''',
    '''module first(input a, output y);
function automatic bit f(input bit q); f=q; endfunction
assign y=f(a); endmodule
module second(input b, output y); assign y=b; endmodule''',
    '''module m(input a, output y);
// function f reads fake; assign y=f(a);
function automatic bit f(input bit q); f=q; endfunction
initial $display("mutable b; function f; assign y=f(a)");
assign y=f(a); endmodule''',
])
def test_no_false_global_classification(tmp_path, text):
    assert findings(tmp_path, text) == []


@pytest.mark.parametrize('body', [
    'f = a ? f(a) : b;',
    'f = external_helper(a) & b;',
])
def test_incomplete_analysis_is_visible_not_rewritten(tmp_path, body):
    text = 'module m(input a,b,output y); function automatic bit f(input bit a); '
    text += body + ' endfunction assign y=f(a); endmodule'
    rows = findings(tmp_path, text, UNRESOLVED)
    assert rows and all(not f.block_eligible for f in rows)
    assert all('NOT_MEASURED' in f.message for f in rows)


def test_existing_cli_reports_concrete_rule(tmp_path):
    source = tmp_path / 'subject.sv'
    source.write_text('''module m(input wire a,b,output wire y);
function automatic bit f(input bit q); f=q & b; endfunction
assign y=f(a); endmodule''')
    report = tmp_path / 'lint.json'
    cp = subprocess.run([sys.executable, lint.__file__, '--json', str(report),
                         str(source)], capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert any(f['rule'] == RULE for f in json.loads(report.read_text()))


def test_actual_icarus_before_after_same_assertions(tmp_path):
    iv, vvp = shutil.which('iverilog'), shutil.which('vvp')
    if not iv or not vvp:
        pytest.skip('native Icarus unavailable; not a simulator PASS')
    for case, expected in [('hidden', 1), ('explicit', 0), ('hidden', 1)]:
        output = tmp_path / (case + '.vvp')
        compiled = subprocess.run([iv, '-g2012', '-s', 'dependency_probe', '-o',
                                   str(output), str(FIXTURES / (case + '.sv'))],
                                  capture_output=True, text=True)
        assert compiled.returncode == 0, compiled.stdout + compiled.stderr
        cp = subprocess.run([vvp, str(output)], capture_output=True, text=True, timeout=20)
        assert cp.returncode == expected, cp.stdout + cp.stderr
        assert 'FIRST_COMPLETE' in cp.stdout


def test_fix_does_not_rewrite_function_signature(tmp_path):
    source = tmp_path / 'subject.sv'
    before = '''module m(input a,b,output wire y);
function automatic bit f(input bit q); f=q & b; endfunction
assign y=f(a); endmodule'''
    source.write_text(before)
    subprocess.run([sys.executable, lint.__file__, '--fix', str(source)],
                   capture_output=True, text=True, check=True)
    assert source.read_text() == before


@pytest.mark.parametrize('text', [
    '''module m(input a,b,output y);
generate if (1) begin:g
  wire b=a;
  function automatic bit f(input bit q); f=q & b; endfunction
  assign y=f(a);
end endgenerate endmodule''',
    '''module m(input a,b,output y);
function automatic bit f(input bit q); f=q & m.b; endfunction
assign y=f(a); endmodule''',
    '''module m(input a,b,output y);
function automatic bit f(input bit q);
begin:inner bit b; b=q; end
f=q & b;
endfunction assign y=f(a); endmodule''',
    '''module m(input a,b,output y);
function automatic bit f(input bit q); f=q & b; endfunction
generate if(1) begin:g wire b=a; assign y=f(b); end endgenerate
endmodule''',
    '''module m(input a,b,output y);
function automatic bit f(input bit q); f=q & b; endfunction
assign y=f(m.b); endmodule''',
    '''module m(input a,input [1:0] b,output y);
function automatic bit f(input bit q); f=q ^ (^b); endfunction
assign y=f(b[0]); endmodule''',
    '''`ifdef ACTIVE
module m(input a,b,output y);
function automatic bit f(input bit q); f=q & b; endfunction
assign y=f(a); endmodule
`endif''',
])
def test_unmodeled_scope_has_no_concrete_accusation(tmp_path, text):
    assert findings(tmp_path, text) == []
    assert findings(tmp_path, text, UNRESOLVED)


def test_non_ansi_formal_excludes_same_named_module_port(tmp_path):
    assert findings(tmp_path, '''module m(a,b,y); input a,b; output y;
function f; input b; reg local_value; begin local_value=b; f=local_value; end
endfunction assign y=f(a); endmodule''') == []


def test_module_function_called_in_generate_remains_resolved(tmp_path):
    rows = findings(tmp_path, '''module m(input a,b,output y);
function automatic bit f(input bit q); f=q & b; endfunction
generate if (1) begin:g assign y=f(a); end endgenerate
endmodule''')
    assert len(rows) == 1 and rows[0].symbol == 'b'
