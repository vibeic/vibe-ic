import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('librelane')
from librelane.common import Toolbox
from librelane.flows import Flow
from librelane.state import State

import flow_engine as engine
import io_pad_chip_top_gen as io
import pad_assignment_gen as assignment


@pytest.mark.parametrize('io_code,assignment_code,expected', [
    (0, 0, 'PASS'), (1, 0, 'FAIL'), (2, 0, 'NOT_MEASURED'), (0, 1, 'FAIL')])
def test_selected_interface_step_runs_native_producers_and_keeps_their_verdicts(
        tmp_path, monkeypatch, io_code, assignment_code, expected):
    calls = []
    rtl = tmp_path / 'unit.v'
    rtl.write_text('module unit(input clk, input d, output q); assign q=d; endmodule\n')
    owner = Flow.factory.get('Classic')({'DESIGN_NAME': 'unit', 'PDK': 'sky130A',
        'VERILOG_FILES': [str(rtl)], 'CLOCK_PORT': 'clk'}, design_dir=str(tmp_path))

    def io_run(argv):
        calls.append('io')
        output = tmp_path / 'reports/phase3/io_pad_chip_top.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({'program': 'io_pad_chip_top_gen',
            'verdict': 'WROTE' if io_code == 0 else 'REFUSE' if io_code == 1 else 'NOT_AVAILABLE',
            'pad_instances': {'u_clock': {}, 'u_data': {}, 'u_output': {}},
            'rule': 'native producer result'}))
        return io_code

    def assign(argv):
        calls.append('assignment')
        output = Path(argv[argv.index('--json') + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({'program': 'pad_assignment_gen',
            'verdict': 'WROTE' if assignment_code == 0 else 'REFUSE',
            'questions_answered': 8, 'questions_unanswered': [], 'reason': 'native producer result'}))
        return assignment_code

    monkeypatch.setattr(io, 'main', io_run)
    monkeypatch.setattr(assignment, 'main', assign)
    chain = engine.NativeChain(tmp_path, {'delivery_target': 'gds'})
    chain.owner = SimpleNamespace(config=owner.config, gating_config_vars={})
    chain.config = owner.config.to_raw_dict()
    chain.state = State()
    chain.toolbox = Toolbox(str(tmp_path / 'tool_tmp'))
    row = next(row for row in engine.read_json(engine.TABLE)['steps']
               if row['name'] == 'package_load_and_test_interface_feasibility')
    (tmp_path / 'step').mkdir()
    result = chain.execute(tmp_path / 'step', row['tool'])
    assert calls == (['io', 'assignment'] if io_code == 0 else ['io'])
    assert engine.evaluate(result, []) == expected
    if expected == 'PASS':
        assert result.metrics['package_interface__pad__count'] == 3
        assert result.metrics['package_interface__unanswered__count'] == 0
