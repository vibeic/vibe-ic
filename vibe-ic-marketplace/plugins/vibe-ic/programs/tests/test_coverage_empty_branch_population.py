"""Counter/consumer controls for Leader ruling166; SOFTWARE fixtures only."""
import json
import pytest
import flow109
import verilator_coverage_measure as coverage


def payload(*, line=2, toggle=2, branch=0, tool='verilator'):
    def points(total):
        return {'covered': total, 'total': total, 'pct': 100.0 if total else 0.0}
    return {'tool': tool, 'totals': {'line': points(line), 'toggle': points(toggle),
                                    'branch': points(branch)}}


@pytest.mark.parametrize('branches,pct,expected', [(0, 0.0, 0), (2, 50.0, 1)])
def test_checker_empty_population_is_na_and_real_branch_floor_remains(tmp_path, capsys, branches, pct, expected):
    data = payload(branch=branches)
    data['totals']['branch']['pct'] = pct
    path = tmp_path / 'coverage.json'; path.write_text(json.dumps(data))
    before = path.read_bytes()
    assert coverage.main(['check', '--coverage-json', str(path)]) == expected
    out = capsys.readouterr().out
    assert ('branch=NOT_APPLICABLE (0/0)' in out) is (branches == 0)
    assert path.read_bytes() == before


@pytest.mark.parametrize('line,toggle', [(0, 2), (2, 0), (0, 0)])
def test_empty_uninstrumented_population_stays_not_measured(tmp_path, line, toggle):
    from test_flow109_retained_frontend import case
    from test_flow109_selection import profile
    _, rtl = case(tmp_path, 'D13')
    data = payload(line=line, toggle=toggle)
    assert coverage.measured_empty_branch_population(data) is None
    data['scope_files'] = [str(rtl)]
    path = tmp_path / 'reports/phase2/coverage/coverage_verilator.json'
    path.write_text(json.dumps(data))
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D13', 'D13')
    assert flow109._retained_native_result(tmp_path, context)['component_status'] == 'NOT_MEASURED'


def test_other_tool_does_not_get_verilator_applicability():
    assert coverage.measured_empty_branch_population(payload(tool='other')) is None


def test_line_and_toggle_floors_still_apply(tmp_path):
    path = tmp_path / 'coverage.json'; path.write_text(json.dumps(payload()))
    for category in ('line', 'toggle'):
        assert coverage.main(['check', '--coverage-json', str(path), '--min-' + category, '101']) == 1


def test_simulation_reader_preserves_functional_fail_beside_branch_na(tmp_path):
    from test_flow109_retained_frontend import case
    from test_flow109_selection import profile
    _, rtl = case(tmp_path, 'D13')
    data = payload(); data['scope_files'] = [str(rtl)]
    (tmp_path / 'reports/phase2/coverage/coverage_verilator.json').write_text(json.dumps(data))
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D13', 'D13')
    result = flow109._retained_native_result(tmp_path, context)
    assert result['component_status'] == 'PASS'
    assert result['native_measurements']['branch_applicability']['status'] == 'NOT_APPLICABLE'
    execution = tmp_path / 'reports/phase2/sim/l10_execution.json'
    native = json.loads(execution.read_text()); native['cases'][0]['verdict'] = 'FAIL'
    execution.write_text(json.dumps(native))
    assert flow109._retained_native_result(tmp_path, context)['component_status'] == 'FAIL'
