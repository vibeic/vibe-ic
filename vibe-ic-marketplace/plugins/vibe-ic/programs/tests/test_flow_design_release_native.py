import json

import pytest

pytest.importorskip('librelane')
from librelane.state import State, DesignFormat

import flow_engine as engine
import flow_native_adapters as adapters
from test_flow_ip_docs_native import native_release


@pytest.mark.parametrize('change,expected', [
    ('none', 'PASS'), ('wrong_top', 'FAIL'), ('hollow', 'FAIL'),
    ('missing_gds', 'NOT_MEASURED'), ('missing_netlist', 'NOT_MEASURED')])
def test_design_release_runs_actual_programs_without_approval_or_seals(
        tmp_path, monkeypatch, change, expected):
    project, name, state, _ = native_release(tmp_path, monkeypatch)
    table = engine.read_json(engine.TABLE)
    row = next(row for row in table['steps'] if row['name'] == 'design_release')
    config = {'DESIGN_NAME': name, 'DEFAULT_CORNER': 'nominal', 'PDK': 'sky130A', 'LIB': {}}
    if change == 'wrong_top':
        config['DESIGN_NAME'] = 'different_top'
    elif change == 'hollow':
        import klayout.db as k
        k.Layout().write(str(state.get('gds')))
    elif change == 'missing_gds':
        state = State(state, overrides={DesignFormat.GDS: None})
    elif change == 'missing_netlist':
        state = State(state, overrides={DesignFormat.NETLIST: None})
    result = engine.ToolResult(**adapters.execute(project, tmp_path / 'step', row['tool'],
        {'delivery_target': 'foundry_handoff'}, state=state, config=config))
    measurements = engine.measure(row['checks'], result.metrics, config, {'always': True}, project)
    assert engine.evaluate(result, measurements) == expected, result
    if change == 'none':
        assert result.metrics['release_document_count'] == 4
        assert [item['name'] for item in result.native_steps] == [
            'foundry_handoff_pack_gen', 'tapeout_checklist_gen', 'foundry_handoff_package_check']
        package = project / row['tool']['destination']
        assert not (project / 'input/release_approval.json').exists()
        assert not (package / 'release_manifest.json').exists()
        assert not (package / 'SHA256SUMS').exists()
        mask = json.loads((package / 'mask_spec.json').read_text())
        assert mask['design_top'] == name


def test_only_foundry_handoff_router_window_reaches_design_release(tmp_path):
    table = engine.read_json(engine.TABLE)
    for target, end in [('gds', '37'), ('shippable_gds', '37.5ic'), ('foundry_handoff', '38')]:
        route = {'delivery_target': target, 'entry_step': table['steps'][0]['name'], 'verify_through': end}
        features = engine.design_features(tmp_path, route, table)
        selected = engine.select_steps(table, route, features, None, None)
        assert ('design_release' in [row['name'] for row in selected]) == (target == 'foundry_handoff')
