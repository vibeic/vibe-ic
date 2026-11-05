"""Clock planning reports the actual native clock tree, including failures."""
import json

import pytest

import flow_engine as engine


@pytest.mark.parametrize('status,code,ran', [('PASS', 0, True), ('FAIL', 1, True),
                                           ('NOT_MEASURED', None, False)])
def test_clock_planning_reads_the_later_native_tree(tmp_path, monkeypatch, status, code, ran):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L8_TIMING_WAVEFORM.json').write_text(json.dumps({'clock_domains': [
        {'domain_kind': 'primary', 'source_pin': 'clk', 'period_ns': 20}]}))
    names = {'pre_layout_timing', 'clock_planning', 'clock_tree_synthesis'}
    select = engine.select_steps
    monkeypatch.setattr(engine, 'select_steps', lambda *args: [row for row in select(*args) if row['name'] in names])
    calls = []
    metrics = {'clock__skew__worst_setup': 0.2, 'clock__skew__worst_hold': -0.1}

    def native(self, directory, tool):
        calls.append(tool['steps'][0])
        if 'OpenROAD.CTS' in tool['steps']:
            return engine.ToolResult(ran, code, metrics, ['native-cts.log'])
        return engine.ToolResult(True, 0, {'timing__setup__ws': 10,
            'unconstrained_required_paths': 0, 'unconstrained_endpoints': 0, 'invalid_timing_exceptions': 0})

    monkeypatch.setattr(engine.NativeChain, 'execute', native)
    route = {'entry_step': 'pre_layout_timing', 'verify_through': 'clock_tree_synthesis',
             'delivery_target': 'gds', 'input_contract': 'structured'}
    result = engine.run(tmp_path, route=route, from_name=route['entry_step'], to_name=route['verify_through'])
    rows = {row['name']: row for row in result['steps']}
    planned = rows['clock_planning']
    assert rows['pre_layout_timing']['status'] == 'PASS'
    assert calls == ['OpenROAD.CheckSDCFiles', 'OpenROAD.CTS']
    assert planned['status'] == status
    assert planned['native_metrics'] == metrics
    assert planned['reports'] == ['native-cts.log']
    if ran:
        assert planned['review_from'] == 'clock_tree_synthesis'
