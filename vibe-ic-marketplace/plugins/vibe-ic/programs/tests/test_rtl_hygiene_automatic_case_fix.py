"""Neutral ordinary-CLI controls for the optional automatic-case repair.

Original inputs are immutable; only an ordinary working source copy is fixed.
Native Icarus comparisons exercise all four-state selector values, including
the deliberately incorrect default-zero mutation. No design/oracle is used.
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'rtl_hygiene_lint.py'


def source(result_range='6:0'):
    hi, lo = map(int, result_range.split(':'))
    width = abs(hi - lo) + 1
    arms = '\n'.join(f"      4'd{i}: decode = {width}'d{(i * 3 + 1) % (1 << width)};"
                     for i in range(16))
    return f"""module dut(input [3:0] source, output [{result_range}] result);
  function automatic [{result_range}] decode(input logic [3:0]
                                            key);
    begin
      case (key)
{arms}
      endcase
    end
  endfunction
  assign result = decode(source);
endmodule
"""


def run(tmp_path, tag, argv):
    process = subprocess.Popen(list(map(str, argv)), cwd=tmp_path,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    (tmp_path / (tag + '.stdout')).write_text(result.stdout)
    (tmp_path / (tag + '.stderr')).write_text(result.stderr)
    (tmp_path / (tag + '.command.json')).write_text(json.dumps({
        'argv': list(map(str, argv)), 'pid': process.pid, 'rc': result.returncode,
        'input_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in tmp_path.glob('*.sv')},
    }, indent=2))
    return result


def prepare(tmp_path, text):
    original = tmp_path / 'original.sv'
    original.write_text(text)
    working = tmp_path / 'working.sv'
    shutil.copyfile(original, working)
    return original, working, original.read_bytes()


def lint(tmp_path, tag, path):
    report = tmp_path / (tag + '.json')
    result = run(tmp_path, tag, [sys.executable, SCRIPT, '--json', report, path])
    return result, json.loads(report.read_text())


@pytest.mark.parametrize('result_range', ['6:0', '40:8', '0:0'])
def test_ordinary_fix_preserves_original_and_clears_case_blocker(tmp_path, result_range):
    original, working, before = prepare(tmp_path, source(result_range))
    red, findings = lint(tmp_path, 'before', working)
    assert red.returncode == 1
    assert any(f['rule'] == 'case-no-default' and f['block_eligible'] for f in findings)
    fixed = run(tmp_path, 'fix', [sys.executable, SCRIPT, '--fix', working])
    assert fixed.returncode == 0, fixed.stderr
    width = abs(int(result_range.split(':')[0]) - int(result_range.split(':')[1])) + 1
    expected = before.replace(b'endcase', f"default: decode = {width}'bx;\n      endcase".encode())
    assert working.read_bytes() == expected
    green, after = lint(tmp_path, 'after', working)
    assert green.returncode == 0, green.stdout + green.stderr
    assert not any(f['rule'] == 'case-no-default' for f in after)
    run(tmp_path, 'idempotent', [sys.executable, SCRIPT, '--fix', working])
    assert working.read_bytes() == expected
    assert original.read_bytes() == before


def refusal_source(kind):
    text = source()
    if kind == 'static': return text.replace('function automatic', 'function static')
    if kind == 'partial': return text.replace("      4'd15: decode = 7'd46;\n", '')
    if kind == 'casex': return text.replace('case (key)', 'casex (key)')
    if kind == 'casez': return text.replace('case (key)', 'casez (key)')
    if kind == 'unique': return text.replace('case (key)', 'unique case (key)')
    if kind == 'initializer': return text.replace('    begin', "    reg saved = 1'b0;\n    begin", 1)
    if kind == 'retained-prefix': return text.replace('      case', "      decode = 7'd0;\n      case", 1)
    if kind == 'module-side-effect':
        return text.replace('  function', '  reg touched;\n  function', 1).replace(
            "decode = 7'd1;", "begin decode = 7'd1; touched = key[0]; end", 1)
    if kind == 'call': return text.replace("decode = 7'd1;", 'decode = $random;', 1)
    if kind == 'two-state-result': return text.replace('function automatic [', 'function automatic bit [')
    if kind == 'ref': return text.replace('input logic [3:0]', 'ref logic [3:0]')
    if kind == 'symbolic-width': return text.replace('  function', '  localparam W = 7;\n  function', 1).replace(
        'automatic [6:0]', 'automatic [W-1:0]')
    if kind == 'duplicate-label': return text.replace("4'd15:", "4'd14:")
    if kind == 'wide-label': return text.replace("4'd15:", "8'd15:")
    if kind == 'xz-label': return text.replace("4'd15:", "4'bxxxz:")
    if kind == 'attribute': return text.replace('  function', '  (* keep = 1 *) function', 1)
    if kind == 'include': return text.replace('  function', '  `include "observer.svh"\n  function', 1)
    if kind == 'misleading-return-width':
        return source('3:0').replace('automatic [3:0]', 'automatic logic [3:0]').replace(
            'input logic [3:0]', 'input logic [7:0]')
    raise AssertionError(kind)


@pytest.mark.parametrize('kind', [
    'static', 'partial', 'casex', 'casez', 'unique', 'initializer', 'retained-prefix',
    'module-side-effect', 'call', 'two-state-result', 'ref', 'symbolic-width',
    'duplicate-label', 'wide-label', 'xz-label', 'attribute', 'include', 'misleading-return-width',
])
def test_unsupported_function_is_byte_preserved(tmp_path, kind):
    (tmp_path / 'observer.svh').write_text('// neutral include closure\n')
    original, working, before = prepare(tmp_path, refusal_source(kind))
    red, findings = lint(tmp_path, 'before', working)
    assert red.returncode == 1
    assert any(f['block_eligible'] for f in findings)
    result = run(tmp_path, 'fix', [sys.executable, SCRIPT, '--fix', working])
    assert result.returncode == 0
    assert working.read_bytes() == before
    after, remaining = lint(tmp_path, 'after', working)
    assert after.returncode == red.returncode
    assert remaining == findings
    assert original.read_bytes() == before


@pytest.mark.parametrize('kind', ['pure', 'port', 'attribute', 'eco', 'multidecl', 'multiwriter', 'call', 'include-observer'])
def test_sink_without_complete_elaborated_census_is_preserved(tmp_path, kind):
    declaration = '  logic sink;'
    assignment = '  assign sink = ^source;'
    header = 'module dut(input [3:0] source, output result);'
    if kind == 'port':
        header = 'module dut(input [3:0] source, output result, output logic sink);'
        declaration = ''
    if kind == 'attribute': declaration = '  (* keep = 1 *) logic sink;'
    if kind == 'eco': declaration = '  (* dont_touch = 1 *) logic spare_eco;'; assignment = '  assign spare_eco = ^source;'
    if kind == 'multidecl': declaration = '  logic sink, other;'; assignment += '\n  assign other = &source;'
    if kind == 'multiwriter': assignment += '\n  assign sink = &source;'
    if kind == 'call': assignment = '  assign sink = $random;'
    include = '  `include "observer.svh"\n' if kind == 'include-observer' else ''
    (tmp_path / 'observer.svh').write_text('assign result = sink;\n')
    output = '' if include else '  assign result = source[0];\n'
    text = '\n'.join([header, declaration, assignment, include + output, 'endmodule\n'])
    original, working, before = prepare(tmp_path, text)
    red, findings = lint(tmp_path, 'before', working)
    result = run(tmp_path, 'fix', [sys.executable, SCRIPT, '--fix', working])
    assert result.returncode == 0
    assert working.read_bytes() == before
    after, remaining = lint(tmp_path, 'after', working)
    assert after.returncode == red.returncode
    assert remaining == findings
    if kind == 'pure':
        assert red.returncode == 1
        assert any(f['rule'] == 'unread-reg' and f['block_eligible'] for f in findings)
    assert original.read_bytes() == before


def test_native_bound_fix_remains_prohibited(tmp_path):
    original, working, before = prepare(tmp_path, source())
    result = run(tmp_path, 'bound-fix', [sys.executable, SCRIPT, '--top', 'dut', '--fix', working])
    assert result.returncode == 2
    assert '--fix cannot change a native elaboration input' in result.stderr
    assert working.read_bytes() == original.read_bytes() == before


def test_native_four_state_positive_zero_mutation_restore(tmp_path):
    assert shutil.which('iverilog') and shutil.which('vvp'), 'native tools required for this selector'
    original, working, before = prepare(tmp_path, source())
    result = run(tmp_path, 'fix', [sys.executable, SCRIPT, '--fix', working])
    assert result.returncode == 0
    fixed = working.read_bytes()
    assert b"default: decode = 7'bx;" in fixed
    parent = tmp_path / 'parent.sv'
    parent.write_bytes(before.replace(b'module dut(', b'module parent('))
    tb = tmp_path / 'compare_tb.sv'
    tb.write_text('''module compare_tb;
  reg [3:0] source;
  wire [6:0] a, b;
  parent p(source, a);
  dut d(source, b);
  integer i, j, n, errors;
  function [0:0] digit(input integer code);
    case (code) 0: digit=1'b0; 1: digit=1'b1; 2: digit=1'bx; 3: digit=1'bz; endcase
  endfunction
  initial begin
    errors=0;
    if ($bits(d.decode(4'b0)) != 7 || $bits(source) != 4) $fatal(1, "width");
    for (i=0; i<256; i=i+1) begin
      n=i;
      for (j=0; j<4; j=j+1) begin source[j]=digit(n%4); n=n/4; end
      #1;
      $display("CHOICE %0d %b %b %b", i, source, a, b);
      if (a !== b) errors=errors+1;
    end
    $display("COMPARED=256 MISMATCHES=%0d", errors);
    if (errors) $fatal(1, "four-state mismatch");
    $finish;
  end
endmodule
''')
    for tag, content, expected_rc in [('positive', fixed, 0), ('zero-mutation', fixed.replace(
            b"default: decode = 7'bx;", b"default: decode = 7'b0;"), 1), ('restore', fixed, 0)]:
        working.write_bytes(content)
        compiled = run(tmp_path, tag + '-compile', ['iverilog', '-g2012', '-s', 'compare_tb',
                        '-o', tmp_path / (tag + '.vvp'), parent, working, tb])
        assert compiled.returncode == 0, compiled.stderr
        simulated = run(tmp_path, tag, ['vvp', tmp_path / (tag + '.vvp')])
        assert simulated.returncode == expected_rc, simulated.stdout + simulated.stderr
        assert simulated.stdout.count('CHOICE ') == 256
        assert ('COMPARED=256 MISMATCHES=240' if expected_rc else 'COMPARED=256 MISMATCHES=0') in simulated.stdout
    assert original.read_bytes() == before
    assert working.read_bytes() == fixed
