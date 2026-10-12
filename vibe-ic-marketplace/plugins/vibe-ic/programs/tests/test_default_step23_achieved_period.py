"""Default publishes achieved timing from the selected STA outputs now."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import execution_backend_producers as backend
import librelane_contract as contract
import librelane_signoff as signoff
import phase3_one_shot_runner as runner
import test_f15_step23_gates_read_the_tool_arm as fixture


def _produce(tmp_path, monkeypatch, *, worst=1.0):
    project = fixture.tool_project(
        tmp_path, setup={'max_ss_125C_4v50': worst})
    (project / 'config.json').write_text(json.dumps({'CLOCK_PERIOD': 24.0}))
    nominal = project / 'phase3/stage3/extracted/top.spef'
    nominal.write_text('*SPEF "IEEE 1481-1998"\n')
    pdk = SimpleNamespace(name='p')
    monkeypatch.setattr(backend, '_parameters',
                        lambda *args: (runner, contract, pdk, 'fixture'))
    monkeypatch.setattr(runner, '_librelane_handed_spefs',
                        lambda *args: {'nom': nominal})

    def selected_native_outputs(*args, **kwargs):
        # Only native execution is controlled. Real selected-arm parsing,
        # achieved-period production and independent gates remain in use.
        record = project / signoff.SIGNOFF_RECORD
        doc = json.loads(record.read_text())
        doc['corners'] = signoff.corner_timing(project / fixture.STA)
        record.write_text(json.dumps(doc))

    monkeypatch.setattr(runner, '_librelane_signoff_record', selected_native_outputs)
    params = {'step_id': '23', 'top': 'top', 'pdk_root': str(tmp_path),
              'image_id': 'fixture', 'execution_mode': 'default'}
    return project, lambda: backend.produce_signoff(project, params)


@pytest.mark.parametrize('worst', [1.0, 0.25, -0.5])
def test_default_writes_current_worst_corner_achieved_period(tmp_path, monkeypatch, worst):
    project, produce = _produce(tmp_path, monkeypatch, worst=worst)
    target = project / 'reports/phase3/achievable_fmax.json'
    assert not target.exists()
    assert produce()['verdict'] == 'PASS'
    assert target.is_file(), 'selected STA ran, but its achieved period was not published'
    doc = json.loads(target.read_text())
    assert doc['worst_setup_slack_ns'] == worst
    assert doc['achievable_period_ns'] == 24.0 - worst
    assert doc['relaxation_applied'] is False
    from achieved_period_recorded_check import main
    assert main([str(project), '--json', str(tmp_path / 'period_gate.json')]) == 0
    from post_route_signoff_corner_check import main as corner_gate
    assert corner_gate([str(project), '--json', str(tmp_path / 'corner_gate.json')]) == (1 if worst < 0 else 0)


def test_default_rerun_does_not_leave_the_previous_achieved_period(tmp_path, monkeypatch):
    project, produce = _produce(tmp_path, monkeypatch)
    target = project / 'reports/phase3/achievable_fmax.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'worst_setup_slack_ns': 99, 'achievable_period_ns': 1}))
    assert produce()['verdict'] == 'PASS'
    assert json.loads(target.read_text())['worst_setup_slack_ns'] == 1.0
    report = project / fixture.STA / 'max_ss_125C_4v50' / signoff.CORNER_REPORT
    report.write_text(fixture.corner_report('max_ss_125C_4v50', 0.125, 0.4))
    fixture.rebind(project)
    assert produce()['verdict'] == 'PASS'
    doc = json.loads(target.read_text())
    assert doc['worst_setup_slack_ns'] == 0.125
    assert doc['achievable_period_ns'] == 23.875
