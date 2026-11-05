import copy

import pytest

import flow_engine as engine
import flow_native_adapters as adapters
import test_flow109_package_ready as fixture


@pytest.mark.parametrize('change,expected', [
    ('none', 'PASS'), ('disconnected', 'FAIL'), ('missing_tech', 'NOT_MEASURED'),
    ('missing_def', 'NOT_MEASURED'), ('declared_package', 'NOT_MEASURED')])
def test_selected_readiness_uses_actual_geometry_without_legacy_records(
        tmp_path, monkeypatch, change, expected):
    monkeypatch.setattr(fixture, '_gds', lambda path: None)
    project = fixture._project(tmp_path)
    for path in [fixture.D75.DECLARATION, fixture.D75.IO_REPORT]:
        (project / path).unlink()
    current_def = project / fixture.D75.PAD_DEF
    if change == 'disconnected':
        current_def.write_text(current_def.read_text().replace(
            '+ PLACED ( 1820000 640000 ) N ;', '+ PLACED ( 1000000 640000 ) N ;'))
    state = {'def': str(current_def)} if change != 'missing_def' else {}
    config = {'DEFAULT_CORNER': 'nom_tt',
              'TECH_LEFS': {'nom_*': str(project / 'input/pdk/tech.tlef')},
              'PAD_LEFS': [str(project / 'input/pdk/io.lef')]}
    if change == 'missing_tech':
        config['TECH_LEFS'] = {}
    row = next(row for row in engine.read_json(engine.TABLE)['steps']
               if row['name'] == 'package_and_test_readiness')
    result = engine.ToolResult(**adapters.execute(project, tmp_path / 'result',
        copy.deepcopy(row['tool']), {'delivery_target': 'gds'}, state=state, config=config))
    checks = engine.measure(row['checks'], result.metrics, config,
                            {'package_declared': change == 'declared_package'}, project)
    assert engine.evaluate(result, checks) == expected
    if change in {'none', 'declared_package'}:
        assert result.metrics['pad_connected_nets_count'] == 1
        assert result.metrics['pad_not_connected_nets_count'] == 0
    elif change == 'disconnected':
        assert result.metrics['pad_not_connected_nets_count'] == 1
    else:
        assert result.ran is False
