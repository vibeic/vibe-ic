"""Exercise selected Default tracks through the real front door and report reader."""
import json
from pathlib import Path

import pytest

from programs.tests.test_the_front_door_rollup_edges import (
    V, GUARD, _drive_main, _report, _save_complete_acceptance, project,
)
from programs.tests.test_execution_receipt_chain import isolated_transport


def drive_selected_tracks(project, monkeypatch, *, rejected=None, status='FAIL',
                          native_analog='PASS', excluded=False, semantic_fail=False):
    """Controlled native/AI outcomes; actual main(), versions and report reader."""
    called = []
    blocks = project / 'phase1/analog/analog_block_list.json'
    blocks.parent.mkdir(parents=True)
    blocks.write_text(json.dumps({'blocks': [{'name': 'control'}], 'block_count': 1}))
    if rejected == 'previous':
        _save_complete_acceptance(project, 'A2', 'FAIL', runner='analog_one_shot_runner')
    monkeypatch.setattr(V, '_need_analog', lambda *a: True)
    import ai_signed_judgement
    monkeypatch.setattr(ai_signed_judgement, 'pending', lambda *a: {})
    monkeypatch.setattr(V, '_capture_container_image', lambda *a: {'verdict': 'NOT_MEASURED'})
    monkeypatch.setattr(V, '_capture_pdk_revision', lambda *a: {'status': 'NOT_MEASURED'})
    monkeypatch.setattr(V._pl, 'emit_final_summary', lambda *a: False)

    def after_phase(name):
        if name != 'phase1':
            return
        called.append(name)
        native = V._run_phase

        def run(label, runner, args, env=None):
            runner = Path(runner)
            if runner.name == 'analog_one_shot_runner.py':
                called.append('analog')
                _report(project, 'analog_one_shot.json', {'verdict': native_analog})
                _save_complete_acceptance(
                    project, 'A9' if excluded else 'A2',
                    status if rejected == 'analog' else 'PASS',
                    runner='analog_one_shot_runner',
                    excluded='existing board exclusion' if excluded else '')
                return 1 if native_analog == 'FAIL' else 0
            sid = {'mixed_signal_top_lvs_run.py': 'M1',
                   'mixed_signal_power_domain_run.py': 'M2',
                   'mixed_signal_m3_run.py': 'M3',
                   'mixed_signal_signoff_run.py': 'M4'}.get(runner.name)
            if sid:
                called.append(sid)
                path = Path(args[args.index('--json') + 1])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({'program': runner.stem, 'verdict': 'PASS'}))
                _save_complete_acceptance(project, sid,
                    status if rejected == sid else 'PASS', runner='vibe_ic_one_shot_runner')
                return 0
            if runner.name in ('mixed_signal_cosim_check.py',
                               'mixed_signal_interface_si_check.py',
                               'mixed_signal_signoff_check.py'):
                path = Path(args[args.index('--json') + 1])
                path.parent.mkdir(parents=True, exist_ok=True)
                fails = semantic_fail and runner.name == 'mixed_signal_interface_si_check.py'
                path.write_text(json.dumps({'verdict': 'FAIL' if fails else 'PASS',
                                            'passed': not fails}))
                return 1 if fails else 0
            if 'phase2' in runner.name:
                called.append('phase2')
            elif 'phase3' in runner.name:
                called.append('phase3')
                rc = native(label, runner, args, env=env)
                audit = project / 'reports/audit/phase23_completion_audit.json'
                audit.parent.mkdir(parents=True, exist_ok=True)
                audit.write_text(json.dumps({'verdict': 'PASS'}))
                return rc
            return native(label, runner, args, env=env)
        monkeypatch.setattr(V, '_run_phase', run)

    rc, doc = _drive_main(project, monkeypatch,
        phase1=('PASS', 0, None), phase2=('PASS', 0),
        phase3=({'verdict': 'PASS', 'completion_audit_verdict': 'PASS'}, 0),
        after_phase=after_phase)
    return rc, doc, called


@pytest.mark.parametrize('rejected', ['analog', 'M1', 'M2', 'M3', 'M4'])
@pytest.mark.parametrize('status', ['FAIL', 'NOT_MEASURED'])
def test_default_selected_rejection_stops_next_producer_and_controls_rollup(
        project, monkeypatch, rejected, status):
    rc, doc, called = drive_selected_tracks(project, monkeypatch,
                                            rejected=rejected, status=status)
    expected = ['phase1', 'analog'] if rejected == 'analog' else (
        ['phase1', 'analog', 'phase2', 'phase3'] +
        ['M1', 'M2', 'M3', 'M4'][:int(rejected[1])])
    assert called == expected, 'a rejected selected track must stop the next producer'
    assert (rc, doc['verdict']) == (1, status)
    if rejected == 'analog':
        assert doc['halted_at'] == 'analog'
    assert GUARD._is_orchestrator_report(
        V._pl.report_path(project, 'vibe_ic_one_shot.json'), project)
    assert GUARD._expected_front_door_verdict(dict(doc, verdict='PASS'), doc['phases']) == status


@pytest.mark.parametrize('scope', ['accepted', 'previous', 'excluded_board'])
def test_default_accepted_selected_tracks_keep_success_and_valid_history(
        project, monkeypatch, scope):
    rc, doc, called = drive_selected_tracks(project, monkeypatch,
        rejected='previous' if scope == 'previous' else 'analog' if scope == 'excluded_board' else None,
        status='NOT_MEASURED', excluded=(scope == 'excluded_board'))
    assert called == ['phase1', 'analog', 'phase2', 'phase3', 'M1', 'M2', 'M3', 'M4']
    assert (rc, doc['verdict']) == (0, 'PASS')
    assert GUARD._is_orchestrator_report(
        V._pl.report_path(project, 'vibe_ic_one_shot.json'), project)
    forged = dict(doc, verdict='FAIL')
    assert GUARD._expected_front_door_verdict(forged, doc['phases']) == 'PASS'


def test_default_native_analog_failure_is_blocking_without_complete_rejection(
        project, monkeypatch):
    rc, doc, called = drive_selected_tracks(project, monkeypatch, native_analog='FAIL')
    assert called == ['phase1', 'analog']
    assert (rc, doc['verdict'], doc['halted_at']) == (1, 'FAIL', 'analog')


def test_default_native_m3_semantic_failure_prevents_m4_and_fails_whole_run(
        project, monkeypatch):
    rc, doc, called = drive_selected_tracks(project, monkeypatch, semantic_fail=True)
    assert called == ['phase1', 'analog', 'phase2', 'phase3', 'M1', 'M2', 'M3']
    assert (rc, doc['verdict']) == (1, 'FAIL')
