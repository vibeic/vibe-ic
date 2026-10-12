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


def test_default_first_sta_publishes_clock_provenance_before_disclosure(tmp_path, monkeypatch):
    project, produce = _produce(tmp_path, monkeypatch)
    import clock_target_provenance as provenance
    target = project / provenance.PROVENANCE_REL
    assert not target.exists()
    assert produce()['verdict'] == 'PASS'
    assert target.is_file(), 'the first Default STA consumer has no clock-source record'
    doc = json.loads(target.read_text())
    assert doc['period_ns'] == 24.0 and doc['assumed'] is False
    from sta_assumed_clock_disclosure_check import main as disclosure
    assert disclosure([str(project), '--json', str(tmp_path / 'disclosure.json')]) == 0


def test_default_refreshes_clock_provenance_and_keeps_target_disagreement(tmp_path, monkeypatch):
    project, produce = _produce(tmp_path, monkeypatch)
    import clock_target_provenance as provenance
    target = project / provenance.PROVENANCE_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'period_ns': 999.0, 'assumed': False}))
    assert produce()['verdict'] == 'PASS'
    assert json.loads(target.read_text())['period_ns'] == 24.0
    (project / 'config.json').write_text(json.dumps({'CLOCK_PERIOD': 36.0}))
    assert produce()['verdict'] == 'PASS'
    assert json.loads(target.read_text())['period_ns'] == 36.0
    from clock_target_record_agreement_check import main as agreement
    # The controlled native reports still measured 24 ns. Updating provenance
    # must expose that mismatch, rather than changing their measured clock.
    assert agreement([str(project), '--json', str(tmp_path / 'agreement.json')]) == 1


def test_default_stamps_an_assumed_clock_before_disclosure_without_changing_sdc(tmp_path, monkeypatch):
    project, produce = _produce(tmp_path, monkeypatch)
    (project / 'config.json').unlink()
    monkeypatch.setattr(runner, '_resolve_clock_spec', lambda *args, **kwargs: (24.0, 'clk'))
    sdc = project / 'phase3/stage3/pnr/constraint.sdc'
    before = sdc.read_bytes()
    assert produce()['verdict'] == 'PASS'
    import clock_target_provenance as provenance
    doc = json.loads((project / provenance.PROVENANCE_REL).read_text())
    assert doc['assumed'] is True and doc['period_ns'] == 24.0
    stamped = json.loads((project / signoff.SIGNOFF_RECORD).read_text())
    assert stamped['clock_period_assumed'] is True
    assert provenance.ASSUMED_DISCLOSURE in stamped['clock_period_note']
    assert sdc.read_bytes() == before
    from sta_assumed_clock_disclosure_check import main as disclosure
    assert disclosure([str(project), '--json', str(tmp_path / 'disclosure.json')]) == 0


def test_default_keeps_assumption_on_current_signoff_records_before_final_consumer(tmp_path, monkeypatch):
    project, _ = _produce(tmp_path, monkeypatch)
    (project / 'config.json').unlink()
    monkeypatch.setattr(runner, '_resolve_clock_spec', lambda *args, **kwargs: (24.0, 'clk'))
    import clock_target_provenance as provenance
    def current_record_writer(project, name, program, output, extra):
        # Control these instruments' outputs, while the real native-producer
        # seam, clock-source emitter, stamping and disclosure consumer run.
        target = project / output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({'verdict': 'PASS'}))
        return runner.StepResult(name, 'PASS', 0.0, '', [str(target)])
    monkeypatch.setattr(runner, '_run_declared_signoff_gate', current_record_writer)
    params = {'step_id': '23', 'top': 'top', 'pdk_root': str(tmp_path),
              'image_id': 'fixture', 'execution_mode': 'default'}
    backend.produce(project, params)
    from sta_assumed_clock_disclosure_check import check
    report = check(project)
    assert report['verdict'] == 'PASS', report
    for relative in provenance.SIGNOFF_RELS:
        target = project / relative
        if target.exists():
            assert json.loads(target.read_text())['clock_period_assumed'] is True
