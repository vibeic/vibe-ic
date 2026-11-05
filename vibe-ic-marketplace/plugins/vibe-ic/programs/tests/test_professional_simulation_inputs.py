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
