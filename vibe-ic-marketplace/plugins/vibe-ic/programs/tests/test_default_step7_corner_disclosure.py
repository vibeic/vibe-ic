"""The native Step-7 routes record their current corner set without changing signoff."""
import json
from types import SimpleNamespace

import pytest

import _flow_yaml
import design_one_shot_runner as D
import pvt_matrix_check as G
from test_default_frontend_step7 import _run
from test_librelane_contract_production_defaults import _chip

REPORT = 'reports/phase3/single_corner_stance.json'


def test_step7_declares_its_corner_disclosure():
    row = next(row for row in _flow_yaml.load()['steps'] if row['id'] == 7)
    assert REPORT in row['required_outputs'], row


@pytest.mark.parametrize('count', [1, 2])
def test_phase2_emitter_records_current_corners(tmp_path, count):
    libs = tmp_path / 'input/pdk/liberty'
    libs.mkdir(parents=True)
    for name in ('tt', 'ss')[:count]:
        (libs / (name + '.lib')).write_text('library(x) { time_unit : "1ns"; }')
    path, seen = D._emit_step7_pvt_matrix(tmp_path, SimpleNamespace(liberty=''), 'unused')
    report = json.loads((tmp_path / REPORT).read_text())
    assert seen == count
    assert report['corner_count'] == count
    assert report['corners'] == [row['name'] for row in json.loads(path.read_text())['corners']]
    assert report['stance'] == 'CORNER_SET_RECORDED'


@pytest.mark.parametrize('route,corners', [
    ('core', None), ('chip', ['tool__ss_100C', 'tool__tt_025C']),
    ('chip', []),
])
def test_prelayout_records_every_current_route_without_rescuing_empty_tool_set(
        tmp_path, monkeypatch, route, corners):
    project = _chip(tmp_path) if route == 'chip' else tmp_path
    prior = project / REPORT
    prior.parent.mkdir(parents=True)
    prior.write_text('{"stance":"SINGLE_CORNER_DISCLOSED","multi_corner_claimed":false}\n')
    _result, matrix, _calls = _run(project, monkeypatch, corners=corners)
    assert G.audit(project)['rc'] == (1 if corners == [] else 0)
    report = json.loads(prior.read_text())
    assert report['stance'] == 'CORNER_SET_RECORDED', report
    assert report['corner_count'] == len(matrix['corners'])
    assert report['corners'] == [row['name'] for row in matrix['corners']]
