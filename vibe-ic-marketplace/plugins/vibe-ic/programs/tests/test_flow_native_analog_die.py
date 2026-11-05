import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import flow_native_analog_die as die


NAMES = sorted(set(die.NATIVE) | {
    "candidate_signal_integrity", "candidate_power_analysis", "candidate_ir_drop", "final_electrical_analysis"})


@pytest.mark.parametrize('name', NAMES)
def test_missing_products_need_no_hand_authored_step_input(tmp_path, monkeypatch, name):
    original = Path.read_text
    def read(path, *args, **kwargs):
        assert not ('input' in path.parts and 'flow109' in path.parts)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    result = die.execute(name, tmp_path, tmp_path / 'work', None)
    assert result['status'] == 'NOT_MEASURED'
    assert not result['native_ran']
    assert result['detail']
    assert '.json' not in result['detail']


@pytest.mark.parametrize('name', sorted(die.NATIVE))
@pytest.mark.parametrize('status', ['PASS', 'FAIL', 'NOT_MEASURED'])
def test_each_native_connection_uses_captured_state_and_preserves_result(tmp_path, monkeypatch, name, status):
    state, config = object(), {'PDK': 'native-process'}
    calls = []
    def native(project, directory, tool, route, captured, settings):
        calls.append((tool, captured, settings))
        return die._result('native report', status=status, ran=status != 'NOT_MEASURED',
                           metrics={'native_errors': 2 if status == 'FAIL' else 0})
    monkeypatch.setattr(die, '_native', native)
    result = die.execute(name, tmp_path, tmp_path / 'work', None, state=state, config=config,
                         route={'delivery_target': 'ip_hardmacro'})
    assert calls == [(die.NATIVE[name], state, config)]
    assert result['status'] == status
    assert result['metrics']['native_errors'] == (2 if status == 'FAIL' else 0)


def test_native_state_is_read_from_an_earlier_tool_product(tmp_path, monkeypatch):
    folder = tmp_path / 'steps/candidate_parasitic_extraction/magic_rcx'
    folder.mkdir(parents=True)
    (folder / 'state_out.json').write_text(json.dumps({'spice': 'native.spice'}))
    (folder / 'config.json').write_text(json.dumps({'PDK': 'native-process'}))
    monkeypatch.setitem(sys.modules, 'librelane.state', SimpleNamespace(State=SimpleNamespace(load=lambda data: data)))
    state, config = die._earlier_state(tmp_path, 'final_geometry_rc_and_pex')
    assert state == {'spice': 'native.spice'}
    assert config == {'PDK': 'native-process'}


def test_delivery_power_does_not_promote_partial_block_measurements(tmp_path):
    path = tmp_path / 'steps/analog_reliability/result.json'
    path.parent.mkdir(parents=True)
    rails = {'supply': {'current_a': {'avg': 0.0005}}}
    path.write_text(json.dumps({'tool_ran': True, 'native_metrics': {'rails': rails}}))
    result = die.execute('candidate_power_analysis', tmp_path, tmp_path / 'work', None)
    assert result['native_ran'] and result['reused_native']
    assert result['metrics']['rails'] == rails
    assert result['status'] == 'NOT_MEASURED'
    assert 'coverage' in result['detail']


@pytest.mark.parametrize('code,status', [(0, 'PASS'), (1, 'FAIL')])
def test_ir_uses_the_existing_native_consumer(tmp_path, monkeypatch, code, status):
    def ir(project, directory, tool, route, *, state=None, config=None):
        assert tool['steps'] == ['OpenROAD.IRDropReport', 'Vibeic.TransientIR']
        return {'ran': True, 'exit_code': code, 'metrics': {'ir__drop__worst__pct': 6 if code else 2},
                'native_steps': [{'name': 'native IR', 'ran': True, 'exit_code': code, 'status': status}]}
    monkeypatch.setitem(sys.modules, 'flow_ir_corners', SimpleNamespace(execute=ir))
    result = die.execute('candidate_ir_drop', tmp_path, tmp_path / 'work', None,
                         state=object(), config={'PDK': 'native-process'},
                         route={'delivery_target': 'ip_hardmacro'})
    assert result['status'] == status and result['native_ran']
    assert result['metrics']['ir__drop__worst__pct'] == (6 if code else 2)
