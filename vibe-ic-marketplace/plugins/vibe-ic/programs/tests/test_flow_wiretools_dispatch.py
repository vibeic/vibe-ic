import json
from pathlib import Path

import flow_native_adapters as adapters
import tapeout_precheck


def test_precheck_dispatch_reads_captured_state_without_component_records(tmp_path, monkeypatch):
    gds = tmp_path / 'unit.gds'
    gds.touch()
    called = {}

    def run(project, **kwargs):
        called.update(kwargs)
        return {'verdict': 'PASS', 'exit_code': 0,
                'measurement': {'polygon_count': 12, 'zero_area_polygon_count': 0},
                'checks': [], 'command': ['klayout', '-b']}

    monkeypatch.setattr(tapeout_precheck, 'execute', run)
    result = adapters.execute(tmp_path, tmp_path / 'step', {'adapter': 'tapeout_precheck'},
                              {'delivery_target': 'gds'}, state={'gds': str(gds)},
                              config={'DESIGN_NAME': 'unit'})
    assert result['ran'], result
    assert result['exit_code'] == 0
    assert result['metrics']['polygon_count'] == 12
    assert called['gds'] == str(gds)
    assert called['config']['DESIGN_NAME'] == 'unit'
    assert not (tmp_path / 'reports/flow109/components').exists()


def test_generated_precheck_uses_background_adapter():
    table = json.loads((Path(adapters.__file__).parents[1] / 'flow/steps.json').read_text())
    tool = next(row['tool'] for row in table['steps'] if row['name'] == 'tapeout_precheck')
    assert tool['adapter'] == 'tapeout_precheck'
    assert tool['parallel'] is True


def test_precheck_without_state_stream_does_not_discover_a_different_layout(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('The native State has no final GDS.')

    monkeypatch.setattr(tapeout_precheck, 'execute', unexpected)
    result = adapters.execute(tmp_path, tmp_path / 'step', {'adapter': 'tapeout_precheck'},
                              {'delivery_target': 'gds'}, state={})
    assert not result['ran']
    assert result['exit_code'] is None
    assert 'State' in result['detail']
