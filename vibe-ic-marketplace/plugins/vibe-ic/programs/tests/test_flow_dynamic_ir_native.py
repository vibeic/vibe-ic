import json
from pathlib import Path

import pytest

pytest.importorskip('librelane')

import flow_engine as engine
import flow_ir_corners as ir


@pytest.fixture
def native_result(tmp_path, monkeypatch):
    calls = []
    result = engine.ToolResult(True, 0, {'ir__drop__worst__pct': 1.0}, native_steps=[
        {'name': 'OpenROAD.IRDropReport', 'ran': True, 'exit_code': 0, 'status': 'PASS'},
        {'name': 'Vibeic.TransientIR', 'ran': True, 'exit_code': 0, 'status': 'PASS'}])

    def run(chain, directory, tool):
        calls.append((chain.state, chain.config, tool))
        return result

    monkeypatch.setattr(engine.NativeChain, 'execute', run)
    monkeypatch.setattr(ir.Toolbox, 'filter_views', lambda self, config, views: ['selected.lib'])
    monkeypatch.setattr(ir.Toolbox, 'get_lib_voltage', lambda self, path: 1.8)
    state = object()
    config = {'DESIGN_NAME': 'unit', 'DEFAULT_CORNER': 'nominal', 'LIB': {'nominal': ['selected.lib']}}
    tool = {'adapter': 'ir_drop', 'steps': ['OpenROAD.IRDropReport', 'Vibeic.TransientIR']}
    return result, calls, state, config, tool


def execute(tmp_path, native_result):
    _, _, state, config, tool = native_result
    return ir.execute(tmp_path, tmp_path / 'native', tool, {'delivery_target': 'ip_hardmacro'},
                      state=state, config=config)


def status(result):
    checks = engine.measure([{'metric': 'ir__drop__worst__pct', 'operator': '<=', 'limit': 5.0}],
                            result['metrics'], {}, {'always': True})
    return engine.evaluate(engine.ToolResult(**result), checks)


def test_static_pass_cannot_replace_missing_dynamic_data(tmp_path, native_result):
    native, calls, state, config, _ = native_result
    result = execute(tmp_path, native_result)
    assert calls[0][0] is state
    assert calls[0][1] == config
    assert result['metrics']['ir__drop__static__worst__pct'] == 1.0
    assert status(result) == 'NOT_MEASURED'
    assert result['native_steps'][-1]['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('scaled', [0, 1])
@pytest.mark.parametrize('drop,expected', [(.036, 'PASS'), (.108, 'FAIL')])
def test_native_dynamic_number_uses_original_ir_limit(tmp_path, native_result, drop, expected, scaled):
    native, _, _, _, _ = native_result
    native.metrics.update({'vibeic__ir_dynamic__drop__worst': drop,
                           'vibeic__ir_dynamic__scaled_static_bound': scaled})
    result = execute(tmp_path, native_result)
    assert result['metrics']['ir__drop__dynamic__worst__pct'] == pytest.approx(drop / 1.8 * 100)
    assert status(result) == expected
    assert result['metrics']['dynamic_model'] == ('scaled_static_bound' if scaled else 'transient')


def test_selected_static_and_dynamic_tools_use_background_job_path():
    row = next(row for row in engine.read_json(engine.TABLE)['steps'] if row['name'] == 'candidate_ir_drop')
    for condition, first in [('ic', 'VibeIC.IRDropCorners'), ('otherwise', 'OpenROAD.IRDropReport')]:
        tool = next(profile['tool'] for profile in row['tool']['profiles'] if profile['when'] == condition)
        assert tool['adapter'] == 'ir_drop'
        assert tool['parallel'] is True
        assert tool['steps'] == [first, 'Vibeic.TransientIR']


def test_native_transient_missing_net_result_stays_unmeasured(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from librelane.state import DesignFormat
    from librelane.steps import StepException
    from librelane_plugins.librelane_plugin_vibeic import ir_drop as native
    import dynamic_ir_vectored_emit as dynamic

    step = object.__new__(native.TransientIR)
    step.config = {'LIB': {}, 'VDD_NETS': ['supply'], 'GND_NETS': ['ground']}
    step.step_dir = str(tmp_path)
    step.toolbox = SimpleNamespace(filter_views=lambda *args: ['selected.lib'],
                                   get_lib_voltage=lambda *args: 1.8)
    step.extract_env = lambda kwargs: (kwargs, {})
    step.err = lambda text: None
    monkeypatch.setattr(native.OpenROADStep, 'run', lambda *args, **kwargs: ({}, {}))
    monkeypatch.setattr(dynamic, 'derive_period_ns', lambda path: (20, 'sdc_create_clock'))
    (tmp_path / 'transient_ir.rpt').write_text('No dynamic solve output.\n')
    with pytest.raises(StepException, match='NOT_MEASURED.*no dynamic IR line'):
        step.run({DesignFormat.SPEF: {'nominal': 'selected.spef'}})


@pytest.mark.parametrize('declared_vdd', [None, ['supply_from_tool']])
def test_native_report_names_supply_nets_when_config_uses_tool_defaults(tmp_path, monkeypatch, declared_vdd):
    from types import SimpleNamespace
    from librelane.state import DesignFormat
    from librelane_plugins.librelane_plugin_vibeic import ir_drop as native
    import dynamic_ir_vectored_emit as dynamic

    step = object.__new__(native.TransientIR)
    step.config = {'LIB': {}, 'VDD_NETS': declared_vdd, 'GND_NETS': None}
    step.step_dir = str(tmp_path)
    step.toolbox = SimpleNamespace(filter_views=lambda *args: ['selected.lib'],
                                   get_lib_voltage=lambda *args: 1.8)
    step.extract_env = lambda kwargs: (kwargs, {})
    step.err = lambda text: None
    monkeypatch.setattr(native.OpenROADStep, 'run', lambda *args, **kwargs: ({}, {}))
    monkeypatch.setattr(dynamic, 'derive_period_ns', lambda path: (20, 'sdc_create_clock'))
    fixture = Path(__file__).parent / 'fixtures/librelane_irdrop/transient_quasi_static.rpt'
    report = fixture.read_text().replace('VDD', 'supply_from_tool').replace('VSS', 'ground_from_tool')
    (tmp_path / 'transient_ir.rpt').write_text(report)
    _, metrics = step.run({DesignFormat.SPEF: {'nominal': 'selected.spef'}})
    assert float(metrics['vibeic__ir_dynamic__drop__worst__net:supply_from_tool']) == pytest.approx(.0146)
    assert float(metrics['vibeic__ir_dynamic__drop__worst__net:ground_from_tool']) == pytest.approx(.0165)
    assert metrics['vibeic__ir_dynamic__scaled_static_bound'] == 1
    record = json.loads((tmp_path / 'transient_ir.json').read_text())
    assert record['nets_analysed'] == ['ground_from_tool', 'supply_from_tool']


def test_native_dynamic_reason_survives_adapter_summary(tmp_path, native_result):
    native, _, _, _, _ = native_result
    native.native_steps[-1].update(status='NOT_MEASURED', detail='Exact native solver reason.')
    result = execute(tmp_path, native_result)
    assert result['native_steps'][-1]['detail'].startswith('Exact native solver reason.')
