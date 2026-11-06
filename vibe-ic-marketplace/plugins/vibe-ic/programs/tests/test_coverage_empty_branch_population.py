"""Counter/consumer controls for Leader ruling166; SOFTWARE fixtures only."""
import json
import pytest
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




def test_other_tool_does_not_get_verilator_applicability():
    assert coverage.measured_empty_branch_population(payload(tool='other')) is None


def test_line_and_toggle_floors_still_apply(tmp_path):
    path = tmp_path / 'coverage.json'; path.write_text(json.dumps(payload()))
    for category in ('line', 'toggle'):
        assert coverage.main(['check', '--coverage-json', str(path), '--min-' + category, '101']) == 1
