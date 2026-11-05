"""Compile the emitted source closure and honor the supported simulator choice."""
from pathlib import Path
import sys

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import professional_tb_gen as generator
import design_one_shot_runner as runner
from test_professional_tb_gen import _mk_spm_project


@pytest.mark.parametrize('missing', [False, True])
def test_emitted_bundle_compiles_its_header_or_reports_missing(tmp_path, missing):
    project = _mk_spm_project(tmp_path)
    rtl = project / 'phase2/stage1/rtl'
    (rtl / 'spm.v').write_text('`include "width.vh"\nmodule spm(input clk,rst, input [`W-1:0] x,input y,output p);assign p=y;endmodule\n')
    if not missing:
        (rtl / 'width.vh').write_text('`define W 32\n')
    result = generator.generate(project)
    out = Path(result['out_dir'])
    import _eda_pin
    command = ['make', '-B', 'SIM=icarus', 'sim_build/sim.vvp']
    rc, stdout, stderr = runner._run_sim_stage(command, out, _eda_pin.default_container_name())
    assert (rc == 0) == (not missing), stdout + stderr



@pytest.mark.parametrize('simulator,fails', [('verilator', False), ('icarus', False), ('verilator', True)])
def test_normal_simulator_dispatch_preserves_native_failure(tmp_path, monkeypatch, simulator, fails):
    out = tmp_path / 'bundle'
    out.mkdir()
    monkeypatch.setenv('SIM', simulator)
    monkeypatch.setattr(generator, 'generate', lambda _: {
        'status': 'PASS', 'dut_kind': 'parallel_arith', 'out_dir': str(out), 'rtl_files': 1})
    (tmp_path / 'adder.v').write_text('module neutral_top(input [7:0] a,b,output [7:0] p);assign p=a+b;endmodule\n')
    (out / 'Makefile').write_text(generator.emit_makefile({'top': 'neutral_top'}, ['../adder.v']))
    (out / 'tb_neutral_top.py').write_text(
        'import cocotb\nfrom cocotb.triggers import Timer\n'
        '@cocotb.test()\nasync def compare(dut):\n'
        '    dut.a.value=17\n    dut.b.value=23\n'
        '    await Timer(10, unit="ns")\n'
        '    assert int(dut.p.value) == %d\n'
        '    print("PROFESSIONAL_TB PASS")\n' % (41 if fails else 40))
    commands = []
    original_run = runner._run
    def execute(argv, **kwargs):
        commands.append(argv[-1])
        return original_run(argv, **kwargs)
    monkeypatch.setattr(runner, '_run', execute)
    result = runner.step_professional_tb_gen(tmp_path, 'neutral_top', '')
    assert any('SIM=' + simulator in cmd for cmd in commands), commands
    assert result.status == ('FAIL' if fails else 'PASS'), result.detail
