"""An undecidable static helper audit must defer to real simulation/JUnit."""
from pathlib import Path
import subprocess

import pytest
from test_coverage_stimulus_attribution import _professional_project, V
import professional_tb_gen as generator

SOURCE = '''import cocotb
from cocotb.triggers import Timer
from collections import deque

class Bus:
    def __init__(self, dut):
        self.dut = dut
        self.compared = 0
    def put(self, name, value):
        getattr(self.dut, name).value = value
    def get(self, name):
        return int(getattr(self.dut, name).value)
    async def run(self):
        queue = deque([0, 1, 0, 1])
        while queue:
            value = queue.popleft()
            self.put('ck4', 0)
            self.put('sample', value)
            await Timer(5, unit='ns')
            self.put('ck4', 1)
            await Timer(5, unit='ns')
            assert self.get('result') == EXPECTED
            self.compared += 1

@cocotb.test()
async def compare(dut):
    bus = Bus(dut)
    await bus.run()
    assert bus.compared == 4
    print('PROFESSIONAL_TB PASS')
'''


def execute(command, cwd):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def case(tmp_path, expected):
    project, bundle = _professional_project(tmp_path)
    (bundle / 'expert_reference_tb.py').write_text(SOURCE.replace('EXPECTED', expected))
    result = generator.generate(project)
    assert result['reference_model_tier'] == 'expert_filled'
    tb = bundle / 'tb_converter.py'
    audit = V.functional_stimulus_audit(tb)
    assert not audit['decidable'], audit
    return project, tb


def test_helper_model_runs_and_reader_accepts_its_passing_native_junit(tmp_path):
    project, tb = case(tmp_path, 'value')
    dat = Path(V.verilate_professional_tb_and_run(
        [str(project / 'phase2/stage1/rtl/converter.v')], tb,
        project / 'build', project / 'run', exec_fn=execute, build_jobs=1))
    assert dat.is_file()
    assert V._check_professional_execution(tb, dat) is None
    assert V.parse_coverage_dat(str(dat))['totals']['line']['total'] > 0


def test_helper_model_wrong_result_fails_native_comparison(tmp_path):
    project, tb = case(tmp_path, '(value ^ 1)')
    with pytest.raises(SystemExit, match='PROFESSIONAL_COVERAGE_SIMULATION_REFUSED'):
        V.verilate_professional_tb_and_run(
            [str(project / 'phase2/stage1/rtl/converter.v')], tb,
            project / 'build', project / 'run', exec_fn=execute, build_jobs=1)
