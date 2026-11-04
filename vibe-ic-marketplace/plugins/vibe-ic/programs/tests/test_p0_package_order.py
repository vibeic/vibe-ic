"""Single-pass tools receive packages before their users; tool errors remain errors."""
import json
import subprocess
from pathlib import Path

import p0_tool_frontend_check as frontend


def project(root):
    rtl = root / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    for name, text in {
        'a_top.sv': 'module top(output use_pkg::word_t q); assign q=0; endmodule',
        'b_use.sv': 'package use_pkg; import base_pkg::*; typedef data_t word_t; endpackage',
        'z_base.sv': 'package base_pkg; typedef logic [7:0] data_t; endpackage',
    }.items():
        (rtl / name).write_text(text + '\n')
    docs = root / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module': 'top'}))
    return root


def test_packages_precede_their_single_pass_consumers(tmp_path, monkeypatch):
    root = project(tmp_path)
    calls = []
    def invoke(tool, args, *unused):
        calls.append((tool, args))
        if tool == 'verilator':
            files = [Path(arg).name for arg in args if arg.endswith('.sv')]
            rc = 0 if files == ['z_base.sv', 'b_use.sv', 'a_top.sv'] else 1
            return subprocess.CompletedProcess([], rc, '', 'package declared after use' if rc else '')
        return subprocess.CompletedProcess([], 0, '', '')
    monkeypatch.setattr(frontend, '_invoke', invoke)
    result = frontend.check(root, 'test-image')
    assert result['passed'], result['findings']
    script = calls[0][1][-1]
    assert script.index('z_base.sv') < script.index('b_use.sv') < script.index('a_top.sv')


def test_ordering_does_not_hide_a_native_compiler_error(tmp_path, monkeypatch):
    root = project(tmp_path)
    def invoke(tool, args, *unused):
        return subprocess.CompletedProcess([], 1 if tool == 'verilator' else 0,
                                           '', '%Error: undefined signal\n' if tool == 'verilator' else '')
    monkeypatch.setattr(frontend, '_invoke', invoke)
    result = frontend.check(root, 'test-image')
    assert not result['passed']
    assert result['tools']['Verilator.Lint']['exit_code'] == 1
    assert 'Verilator lint failed' in result['findings']
