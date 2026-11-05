from pathlib import Path
from types import SimpleNamespace
import importlib
import sys

import pytest

import flow_engine as engine
import flow_native_adapters as adapters


ANALOG = [8, 9, 11, 12, 13, 14, 15, 28, 29, 30, 43, 44, 45, 46, 47, 48, 49, 62, 100]
MIXED = [10, 27, 50, 53, 82, 83, 85, 97, 101]
BRANCHES = {51: 'D31', 52: 'D32', 64: 'D42', 65: 'D43', 69: 'D47',
            70: 'D48', 76: 'D54', 78: 'D56', 79: 'D57', 80: 'D58',
            84: 'D60', 93: 'D69', 94: 'D70'}
CONNECTIONS = [(position, 'analog', f'A{index:02d}')
               for index, position in enumerate(ANALOG, 1)] + [
    (position, 'mixed', f'M{index:02d}') for index, position in enumerate(MIXED, 1)
] + [(position, 'analog', native) for position, native in BRANCHES.items()]


@pytest.mark.parametrize('position,family,native_step', CONNECTIONS)
def test_selected_connection_returns_native_numbers(tmp_path, monkeypatch, position, family, native_step):
    table = engine.read_json(engine.TABLE)
    row = table['steps'][position - 1]
    features = engine.design_features(tmp_path, {'delivery_target': 'ip_hardmacro'}, table)
    features.update(analog_physical=True, digital_physical=False)
    tool = engine.choose_tool(row['tool'], features)
    native = importlib.import_module('flow_native_' + family)
    if native_step.startswith('D'):
        assert row['name'] in native.BRANCHES
    else:
        assert native.NATIVE_STEPS[row['name']] == native_step
    calls = []

    def execute(project, directory, selected, commands, *, state=None, config=None, route=None):
        calls.append((selected['step'], project))
        return {'ran': True, 'exit_code': 0, 'metrics': {'native_voltage_v': 1.25},
                'reports': [], 'detail': 'native measurement'}

    monkeypatch.setitem(sys.modules, 'flow_native_' + family, SimpleNamespace(execute=execute))
    result = adapters.execute(tmp_path, tmp_path / 'work', tool, {'delivery_target': 'ip_hardmacro'})
    assert calls == [(row['name'], tmp_path)]
    assert result['ran'] is True
    assert result['metrics']['native_voltage_v'] == 1.25


@pytest.mark.parametrize('position', [15, 28, 29, 30, 46, 47, 27, 83, 97])
def test_long_native_measurements_use_background_lane(position):
    table = engine.read_json(engine.TABLE)
    tool = engine.choose_tool(table['steps'][position - 1]['tool'], {})
    assert tool['parallel'] is True


@pytest.mark.parametrize('position', list(BRANCHES))
def test_digital_profile_keeps_its_native_tool(position):
    row = engine.read_json(engine.TABLE)['steps'][position - 1]
    features = engine.design_features(Path('/nonexistent'), {'delivery_target': 'ip_hardmacro'},
                                     engine.read_json(engine.TABLE))
    features.update(analog_physical=False, digital_physical=True, ic=False)
    assert engine.choose_tool(row['tool'], features).get('adapter') != 'analog'
