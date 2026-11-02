"""Compile the producer's unchanged file list; hook_unfilled is not function PASS."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / 'fixtures/professional_package_order'


def project(tmp_path, sources=None):
    root = tmp_path / 'project'
    rtl = root / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    gd = root / 'phase1/generated_docs'
    gd.mkdir(parents=True)
    shutil.copyfile(FIXTURE / 'L9_INTEGRATION_SPEC.json', gd / 'L9_INTEGRATION_SPEC.json')
    if sources is None:
        sources = {name: (FIXTURE / name).read_text()
                   for name in ['a_frame.sv', 'b_words.sv', 'z_defs.sv']}
    for name, text in sources.items():
        (rtl / name).write_text(text)
    return root


def generate_and_compile(root):
    if shutil.which('iverilog') is None:
        pytest.skip('Icarus unavailable: native file-list contract NOT_VERIFIED')
    cli = [sys.executable, str(PROGRAMS / 'professional_tb_gen.py'), str(root)]
    emitted = subprocess.run(cli, capture_output=True, text=True, check=False)
    (root / 'producer.stdout').write_text(emitted.stdout)
    (root / 'producer.stderr').write_text(emitted.stderr)
    assert emitted.returncode == 0, emitted.stdout + emitted.stderr
    result = json.loads(emitted.stdout)
    assert result['status'] == 'PASS', result
    assert result['reference_model_tier'] == 'hook_unfilled', result
    out = Path(result['out_dir'])
    makefile = out / 'Makefile'
    original_bytes = makefile.read_bytes()
    assignment = next(line for line in original_bytes.decode().replace('\\\n', ' ').splitlines()
                      if line.startswith('VERILOG_SOURCES = '))
    sources = assignment.split('=', 1)[1].split()
    assert len(sources) == result['rtl_files']
    assert all(not Path(source).is_absolute() for source in sources)
    argv = ['iverilog', '-g2012', '-s', 'frame_top', '-o', 'compiled.vvp', *sources]
    native = subprocess.run(argv, cwd=out, capture_output=True, text=True, check=False)
    (root / 'native.stdout').write_text(native.stdout)
    (root / 'native.stderr').write_text(native.stderr)
    (root / 'native.json').write_text(json.dumps({
        'argv': argv, 'cwd': str(out), 'returncode': native.returncode,
        'makefile_sha256': hashlib.sha256(original_bytes).hexdigest(),
        'sources': [{'reference': source,
                     'sha256': hashlib.sha256((out / source).read_bytes()).hexdigest()}
                    for source in sources]}, indent=2) + '\n')
    assert makefile.read_bytes() == original_bytes, 'native consumer must use the unmodified emitted list'
    assert 'TestSkip' in (out / 'tb_frame_top.py').read_text(), 'unfilled hook must not claim function PASS'
    print('NATIVE_FILELIST_OBSERVATION ' + json.dumps({
        'sources': sources, 'returncode': native.returncode,
        'stderr': native.stderr, 'producer_status': result['status'],
        'reference_model_tier': result['reference_model_tier']}, sort_keys=True))
    return [Path(source).name for source in sources], native


def test_transitive_public_packages_compile_from_the_emitted_filelist(tmp_path):
    names, native = generate_and_compile(project(tmp_path))
    assert native.returncode == 0, (names, native.stdout, native.stderr)
    assert names == ['z_defs.sv', 'b_words.sv', 'a_frame.sv']


@pytest.mark.parametrize('case', ['single_provider', 'other_provider_filename', 'ordinary_nonpackages'])
def test_existing_source_shapes_remain_compilable_and_lossless(tmp_path, case):
    main = (FIXTURE / 'a_frame.sv').read_text()
    if case == 'single_provider':
        sources = {'z_frame.sv': main, 'a_data.sv':
                   "package a_words; localparam logic[7:0]WordMask=8'h3a; endpackage\n"}
        expected = ['a_data.sv', 'z_frame.sv']
    elif case == 'other_provider_filename':
        sources = {'a_frame.sv': main, 'b_words.sv': (FIXTURE / 'b_words.sv').read_text(),
                   'provider_constants.sv': (FIXTURE / 'z_defs.sv').read_text()}
        expected = ['provider_constants.sv', 'b_words.sv', 'a_frame.sv']
    else:
        sources = {'z_tail.SV': 'module tail; endmodule\n',
                   'a_frame.sv': main.replace(' import a_words::*;\n', '').replace('data_i^WordMask', 'data_i'),
                   'a_aux.v': 'module aux; endmodule\n'}
        expected = ['a_aux.v', 'a_frame.sv', 'z_tail.SV']
    names, native = generate_and_compile(project(tmp_path, sources))
    assert native.returncode == 0, (names, native.stdout, native.stderr)
    assert names == expected
    assert len(names) == len(sources) and set(names) == set(sources)


def test_a_missing_package_provider_still_fails_native_compilation(tmp_path):
    sources = {name: (FIXTURE / name).read_text() for name in ['a_frame.sv', 'b_words.sv']}
    names, native = generate_and_compile(project(tmp_path, sources))
    assert len(names) == 2 and set(names) == set(sources)
    assert native.returncode != 0, 'ordering must not fabricate a missing package'


def test_a_package_cycle_keeps_all_sources_and_does_not_fake_compile_pass(tmp_path):
    sources = {name: (FIXTURE / name).read_text()
               for name in ['a_frame.sv', 'b_words.sv', 'z_defs.sv']}
    sources['z_defs.sv'] = sources['z_defs.sv'].replace('package z_defs;\n',
                                                                   'package z_defs;\n import a_words::*;\n')
    names, native = generate_and_compile(project(tmp_path, sources))
    assert len(names) == 3 and set(names) == set(sources)
    assert native.returncode != 0, 'unresolved cycle cannot be certified by a file-list sort'


def test_package_compile_order_does_not_replace_the_top_parameter_width(tmp_path):
    """Review R1 neutral unit: package AUX_WIDTH is not the top size default."""
    root = tmp_path / 'width-project'
    gd = root / 'phase1/generated_docs'
    gd.mkdir(parents=True)
    l9 = {'fields': {'top_module': 'spm', 'top_ports': [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst', 'dir': 'input', 'width': 1}, {'name': 'x', 'dir': 'input', 'width': 'size'}, {'name': 'y', 'dir': 'input', 'width': 1}, {'name': 'p', 'dir': 'output', 'width': 1}], 'clocks': [{'name': 'clk', 'period_ns': 10}], 'reset_domains': [{'name': 'rst', 'polarity': 'active_high', 'sync': 'sync'}]}}
    (gd / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps(l9))
    (gd / 'L2_FRS.json').write_text(json.dumps({'frs_sections': [
        {'title': 'Function', 'content': 'serial-parallel multiplier p = (x * y) mod 2^N'}]}))
    (root / 'declaration.json').write_text(json.dumps({
        'integer_encoding': 'unsigned',
        'function': {'result': 'p', 'operands': ['x', 'y'], 'operator': '*', 'modulus_bits': 32}}))
    rtl = root / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    sources = {'a_spm.sv': 'import z_defs::*;\nmodule spm #(parameter size = 32)(input logic clk, rst, input logic [size-1:0] x, input logic y, output logic p);\nendmodule\n', 'z_defs.sv': 'package z_defs;\n  parameter AUX_WIDTH = 4;\nendpackage\n'}
    for name, text in sources.items():
        (rtl / name).write_text(text)
    emitted = subprocess.run([sys.executable, str(PROGRAMS / 'professional_tb_gen.py'),
                              str(root)], capture_output=True, text=True, check=False)
    (root / 'producer.stdout').write_text(emitted.stdout)
    (root / 'producer.stderr').write_text(emitted.stderr)
    assert emitted.returncode == 0, emitted.stdout + emitted.stderr
    result = json.loads(emitted.stdout)
    assert result['status'] == 'PASS' and result['dut_kind'] == 'serial_stream', result
    out = Path(result['out_dir'])
    makefile = out / 'Makefile'
    before = makefile.read_bytes()
    line = next(line for line in before.decode().replace('\\\n', ' ').splitlines()
                if line.startswith('VERILOG_SOURCES = '))
    refs = line.split('=', 1)[1].split()
    argv = ['iverilog', '-g2012', '-s', 'spm', '-o', 'compiled.vvp', *refs]
    native = subprocess.run(argv, cwd=out, capture_output=True, text=True, check=False)
    tb = (out / 'tb_spm.py').read_text()
    n_line = next(line for line in tb.splitlines() if line.startswith('N = '))
    (root / 'native.json').write_text(json.dumps({'argv': argv, 'cwd': str(out),
        'returncode': native.returncode, 'stderr': native.stderr,
        'makefile_sha256': hashlib.sha256(before).hexdigest(), 'N_line': n_line,
        'refs': refs}, indent=2) + '\n')
    print('PARAMETRIC_WIDTH_OBSERVATION ' + json.dumps({'refs': refs,
        'compile_rc': native.returncode, 'N_line': n_line}, sort_keys=True))
    assert native.returncode == 0, native.stdout + native.stderr
    assert n_line == 'N = 32', n_line
    assert [Path(ref).name for ref in refs] == ['z_defs.sv', 'a_spm.sv']
    assert len(refs) == len(sources) and all(not Path(ref).is_absolute() for ref in refs)
    assert makefile.read_bytes() == before
