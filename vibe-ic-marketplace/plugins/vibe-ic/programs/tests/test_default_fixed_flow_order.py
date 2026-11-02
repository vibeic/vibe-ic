"""Cold/resume Default order controls. Synthetic transport is not IC proof."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import _flow_yaml as flow
import execution_policy as policy
import phase3_one_shot_runner as runner
import step_preflight as preflight
from _invocation_fixture import bind_invocation_top, preserve_invocation_runtime


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    original = policy.request
    monkeypatch.setattr(policy, 'request', lambda: dict(original(), mode='default'))
    monkeypatch.setattr(policy, '_ordinary_runtime', None)


def test_cold_order_has_no_future_dependency_and_preserves_all_legacy_ids():
    rows = flow.load()['steps']
    ids = [str(row['id']) for row in rows]
    assert len(ids) == len(set(ids)) == 70
    for row in rows:
        for upstream in row.get('blocks_on', []):
            assert ids.index(str(upstream)) < ids.index(str(row['id'])), (row['id'], upstream)
    assert runner._phase3_window_steps('32', '23') == ['32', '22', '23']
    assert runner._phase3_window_steps('37', '34') == ['37', '26.5ic', '34']
    assert runner._phase3_window_steps('37.4', '38') == ['37.4', '36', '37.5ip', '37.5ic', '38']
    by_id = {str(row['id']): row for row in rows}
    assert 'tapeout_checklist_gen' not in by_id['36']['programs']
    assert 'tapeout_checklist_gen' in by_id['38']['programs']
    assert by_id['32']['blocks_on'] == [21, 7]
    assert by_id['22']['blocks_on'] == [32]
    assert 'gds_antenna_deck_check' not in by_id['26']['programs']
    assert 'gds_antenna_deck_check' in by_id['37']['programs']


@pytest.mark.parametrize('entry,exit_', [('26.5ic', '27'), ('34', '37'), ('23', '32')])
def test_legacy_label_backward_resume_is_refused(entry, exit_):
    with pytest.raises(ValueError, match='reversed'):
        runner._phase3_window_steps(entry, exit_)


@pytest.mark.parametrize('sid,earlier,later', [('31', '37', '36'), ('34', '37', '31'), ('36', '37.4', '37.5ic')])
def test_actual_preflight_charges_due_inputs_in_yaml_order(tmp_path, sid, earlier, later):
    bind_invocation_top(tmp_path, 'unit')
    due, error = preflight.due_steps('phase3_one_shot_runner', 'default_step_' + sid)
    assert error is None
    assert earlier in due and later not in due
    decision = preflight.decide(tmp_path, 'phase3_one_shot_runner', 'default_step_' + sid)
    assert decision.flow_steps == [sid]
    assert not any(item.get('from') == earlier and item['state'] == 'not-yet-due'
                   for item in decision.inputs)
    assert not decision.allow, decision


def test_stage5_and_bounded_calls_share_the_actual_row_plan():
    plan = preflight.runner_plan('phase3_one_shot_runner')
    assert dict(plan.sites)['pnr'] == flow.ordered_step_ids(execution_stages=(4,))
    assert dict(plan.sites)['pnr'][-1] == '21'
    rows = flow.ordered_step_ids(execution_stages=(5,))
    assert tuple(runner._phase3_window_steps(rows[0], rows[-1])) == rows
    assert {'DT2', 'DT3'} <= set(rows)
    assert runner._phase3_window_sites(rows[0], rows[-1]) == ['default_backend']
    pruned = preflight.exit_pruned_sites(plan.sites, '37')
    assert 'default_step_26.5ic' in pruned
    assert 'default_step_32' not in pruned


@pytest.mark.parametrize('case', ['clean', 'adopted', 'measured_fail'])
def test_real_cold_step32_does_not_require_a_future_step22_spef(tmp_path, monkeypatch, case):
    from test_default_step32_output_publication import test_current_step32_publishes_before_its_output_receipt
    test_current_step32_publishes_before_its_output_receipt(tmp_path, monkeypatch, case)
    receipts = list(tmp_path.glob('project/reports/phase3/default_steps/32/backend_result.json'))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt['verdict'] == ('FAIL' if case == 'measured_fail' else 'PASS')
    assert not list(tmp_path.rglob('*.spef'))


@pytest.mark.parametrize('rejected_stage,status', [(None, 'PASS'), (5, 'FAIL'), (7, 'FAIL'), (7, 'NOT_MEASURED')])
def test_actual_cold_main_visits_each_stage_once_and_stops_all_later_writers(
        tmp_path, monkeypatch, rejected_stage, status):
    from test_phase3_postpnr_disclosure_and_gds_guard import (
        _project, _drive, OLD_DIE, OLD_UTIL, NEW_DIE, NEW_UTIL, TOP,
    )
    project = _project(tmp_path, cached_die=OLD_DIE, cached_util=OLD_UTIL)
    _drive(monkeypatch, project, die=NEW_DIE, util=NEW_UTIL)
    pnr = runner._pl.pnr_dir(project)
    (pnr / f'{TOP}.gds').unlink()
    source_gds = runner._pl.gds_dir(project) / f'{TOP}.gds'
    source_gds.unlink(missing_ok=True)
    calls, writers = [], []
    # This is an orchestration control over the actual main boundary. Native
    # stage outcomes are supplied; their independent complete consumers have
    # separate producer/consumer controls, and no whole-design PASS is claimed.
    monkeypatch.setattr(runner, '_default_prelayout_rejection', lambda *a: None)
    monkeypatch.setattr(runner, 'run_step11_dft_after_synth', lambda *a: [])
    monkeypatch.setattr(runner, 'run_step13_lec_on_pnr_input', lambda *a: [])
    monkeypatch.setattr(runner, '_ordinary_phase3_row', lambda *a: None)
    monkeypatch.setattr(runner, '_default_step15_with_backend_receipt',
                        lambda project, top, pdk, container, *a, **k: rows(
                            project, top, pdk, container,
                            list(flow.ordered_step_ids(execution_stages=(4,))), report_name='pnr'))

    def rows(project, top, pdk, container, ids, *, report_name='pnr', **kwargs):
        stages = {int(row['execution_stage']) for row in flow.load()['steps'] if str(row['id']) in ids}
        assert len(stages) == 1, ids
        stage = stages.pop()
        assert ids == list(flow.ordered_step_ids(execution_stages=(stage,), execution_tracks=('default',)))
        calls.append((stage, list(ids)))
        if stage == 4:
            for target in (pnr / 'routed.def', pnr / f'{TOP}.def'):
                target.write_text('DIEAREA ( 0 0 ) ( 1500000 1500000 ) ;\nPINS 0 ;\nEND PINS\n')
        if stage == 5:
            assert not (pnr / f'{TOP}.gds').exists(), 'no previous stream at cold route electrical stage'
        if stage == 6:
            (pnr / 'filled.def').write_bytes((pnr / 'routed.def').read_bytes())
            (pnr / f'{TOP}.gds').write_text('CURRENT STREAM FROM CURRENT FILLED LAYOUT\n')
            source_gds.parent.mkdir(parents=True, exist_ok=True)
            source_gds.write_bytes((pnr / f'{TOP}.gds').read_bytes())
        verdict = status if stage == rejected_stage else 'PASS'
        return runner.StepResult(report_name, verdict, 0, f'controlled stage {stage}',
            extras={'requested_steps': ids},
            reason_class=runner._V.ReasonClass.NOT_EXECUTED if verdict == 'NOT_MEASURED' else '')

    monkeypatch.setattr(runner, '_default_pnr_rows', rows)
    monkeypatch.setattr(runner, 'step_canonicalize_artefacts',
                        lambda *a, **k: runner.StepResult('canonicalize_artefacts', 'PASS', 0, 'controlled remaining physical evidence'))
    monkeypatch.setattr(runner, 'step_drv_promotion_corroboration',
                        lambda *a: runner.StepResult('drv_promotion_corroboration', 'PASS', 0, 'controlled measured reader'))
    monkeypatch.setattr(runner, 'step_declared_signoff_gates', lambda *a, **k: [])
    monkeypatch.setattr(runner, 'step_pad_ring_final_evidence',
                        lambda *a: runner.StepResult('pad_ring_final_evidence', 'PASS', 0, 'controlled current pin evidence'))
    monkeypatch.setattr(runner, '_run_derived_artefact_generators', lambda *a, **k: writers.append('legacy-derived') or [])
    import subprocess
    previous = subprocess.run
    def execution(argv, *args, **kwargs):
        if (isinstance(argv, (tuple, list)) and len(argv) > 1
                and Path(str(argv[1])).name == 'flow_declared_producer_run.py'):
            writers.append('legacy-global-declared')
        return previous(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', execution)
    runner.main()
    stages = [stage for stage, ids in calls]
    expected = [4, 5, 6, 7, 8] if rejected_stage is None else [s for s in (4, 5, 6, 7, 8) if s <= rejected_stage]
    assert stages == expected, calls
    flat = [sid for stage, ids in calls for sid in ids]
    assert len(flat) == len(set(flat)), flat
    assert writers == [], writers
    (project / 'FIXED_ORDER_MAIN_OBSERVATION.json').write_text(json.dumps({
        'calls': calls, 'legacy_writers': writers,
        'controlled_native_results_only': True, 'rejected_stage': rejected_stage,
        'rejected_status': status}, indent=2))


@pytest.mark.parametrize('first_status', ['PASS', 'FAIL', 'NOT_MEASURED'])
def test_final_handoff_produces_package_then_checklist_once(tmp_path, monkeypatch, first_status):
    calls = []
    def produce(project, name, *args):
        calls.append(name)
        verdict = first_status if name == 'foundry_handoff' else 'PASS'
        return runner.StepResult(name, verdict, 0, 'controlled process boundary',
            reason_class=runner._V.ReasonClass.NOT_EXECUTED if verdict == 'NOT_MEASURED' else '')
    monkeypatch.setattr(runner, '_run_pre_audit_producer', produce)
    result = runner._default_final_handoff(tmp_path, '')
    assert calls == (['foundry_handoff', 'tapeout_checklist'] if first_status == 'PASS' else ['foundry_handoff'])
    assert result.status == first_status


def test_pinned_native_stream_recipe_accepts_the_recorded_cli_flags():
    import subprocess
    import sys
    from librelane.common import get_script_dir
    recipe = Path(get_script_dir()) / 'klayout/stream_out.py'
    result = subprocess.run([sys.executable, str(recipe), '--help'],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    for flag in ('--input-lef', '--output', '--top', '--lyp', '--lyt', '--lym', '--with-gds-file'):
        assert flag in result.stdout, (flag, result.stdout)


def test_hardware_final_remains_visible_without_dispatch_to_unknown_backend():
    assert '39' in flow.ordered_step_ids(execution_stages=(8,))
    ids = flow.ordered_step_ids(execution_stages=(8,), execution_tracks=('default',))
    assert ids == ('37.4', '36', '37.5ip', '37.5ic', '38')
    assert 'default_step_39' not in dict(preflight.runner_plan('phase3_one_shot_runner').sites)
    row = next(row for row in flow.load()['steps'] if str(row['id']) == '39')
    assert row['execution_track'] == 'hardware'
    assert 'reports/phase2/fpga/on_board_pass.json' in row['required_outputs']
