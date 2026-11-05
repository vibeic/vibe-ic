"""Exercise the actual native EQY gold read, including real negative proofs."""
import shutil
import subprocess

import pytest
import librelane_eqy as native


@pytest.mark.parametrize('damage', [None, 'changed_function', 'invalid_syntax'])
def test_eqy_reads_synthesis_sv_scope_and_retains_native_refusals(tmp_path, damage):
    if not shutil.which('eqy') or not shutil.which('yosys'):
        pytest.skip('native EQY and Yosys required')
    header = tmp_path / 'macros.svh'
    header.write_text('`define WORD_WIDTH 4\n')
    package = tmp_path / 'types.sv'
    package.write_text('package types; typedef logic [`WORD_WIDTH-1:0] word_t; endpackage\n')
    rtl = tmp_path / 'top.sv'
    expression = 'a[0] ^ a[1]' if damage != 'invalid_syntax' else ''
    rtl.write_text('module top(input types::word_t [1:0] a, output types::word_t y);\n'
        '`ifdef SELECT_LOGIC\nassign y = ' + expression + ';\n'
        '`else\nassign y = ~a[0];\n`endif\nendmodule\n')
    mapped = tmp_path / 'mapped.v'
    operation = '&' if damage == 'changed_function' else '^'
    mapped.write_text('module top(input [7:0] a, output [3:0] y);\n'
                     f'assign y = a[3:0] {operation} a[7:4];\nendmodule\n')
    liberty = tmp_path / 'cells.lib'
    liberty.write_text('library(neutral) {}\n')
    sources = [rtl, package, header]
    config = {'USE_SLANG': True, 'VERILOG_DEFINES': ['SELECT_LOGIC']}
    # On the predecessor the keyword is unavailable: run its actual emitted
    # script so the failing observation is a native parse abort, not TypeError.
    import inspect
    kwargs = {'synthesis': config} if 'synthesis' in inspect.signature(native.eqy_script).parameters else {}
    script = native.eqy_script('top', sources, mapped, str(liberty), **kwargs)
    path = tmp_path / 'top.eqy'
    path.write_text(script)
    run = subprocess.run(['eqy', '-f', '-d', str(tmp_path / 'scratch'), str(path)],
                         cwd=tmp_path, capture_output=True, text=True, timeout=60)
    (tmp_path / 'native.log').write_text(run.stdout + run.stderr)
    if damage == 'invalid_syntax':
        assert run.returncode != 0
        assert not (tmp_path / 'scratch/PASS').exists()
    elif damage == 'changed_function':
        assert run.returncode != 0
        assert (tmp_path / 'scratch/FAIL').exists(), run.stdout + run.stderr
    else:
        assert run.returncode == 0, run.stdout + run.stderr
        observed = native.judge_eqy(tmp_path, tmp_path / 'observed.json')
        assert observed['verdict'] == 'PASS', observed
        assert observed['compared_points'] > 0
        assert native.eqy_script('top', sources, mapped, str(liberty), **kwargs) == script
