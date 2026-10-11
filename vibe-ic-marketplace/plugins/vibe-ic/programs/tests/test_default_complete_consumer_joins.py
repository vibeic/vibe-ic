"""Observe complete Default consumers at actual runner calls, without IC claims."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROGRAMS = Path(os.environ.get('VIBEIC_COMPONENT_JOIN_PROGRAMS',
                              str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import analog_one_shot_runner as analog
import design_one_shot_runner as design
import execution_backend_gates as gates
import execution_policy as policy
import phase1_one_shot_runner as phase1
import phase3_one_shot_runner as phase3
import step_output_collector as versions
import step_preflight as preflight


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    request = {**policy.request(), 'mode': 'default'}
    monkeypatch.setattr(policy, 'request', lambda: request)
    monkeypatch.setattr(policy, '_ordinary_runtime', None)


def write(project, relative, content=b'current invocation'):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def saved(project, sid):
    rows = [r for r in versions._read_index(project)['steps'] if r['id'] == sid]
    assert rows, f'no invocation for Step {sid}'
    folder = project / 'steps' / rows[-1]['folder']
    return folder, json.loads((folder / 'outputs.json').read_text())


def prior(folder, relative):
    records = json.loads((folder / 'before/outputs.json').read_text())['outputs']
    item = next(r for r in records if r['rel'] == relative)
    return (folder / 'before' / item['snapshot']).read_bytes()


def reject_consumer(monkeypatch):
    seen = []
    def reject(project, row):
        seen.append(str(row['id']))
        return {'status': 'FAIL', 'step': {'id': row['id'], 'status': 'FAIL'},
                'ledger': []}
    monkeypatch.setattr(gates, 'evaluate', reject)
    return seen


@pytest.mark.parametrize('runner,site,sid', [
    ('design_one_shot_runner', 'rtl_gen', '1'),
    ('design_one_shot_runner', 'asic_sdc', '7'),
    ('design_one_shot_runner', 'yosys_synth', '9'),
    ('phase3_one_shot_runner', 'synth', '9'),
])
def test_preflight_runs_consumer_after_actual_producer_without_leaking_kwarg(
        tmp_path, monkeypatch, runner, site, sid):
    seen = reject_consumer(monkeypatch)
    monkeypatch.setattr(preflight, 'decide', lambda *a, **k: preflight.Decision(
        runner=runner, site=site, flow_steps=[sid], allow=True, verdict='READY'))
    monkeypatch.setattr(preflight, 'record', lambda *a, **k: None)
    result = SimpleNamespace(name=site, status='PASS', detail='', extras={})
    def native(project):  # No **kwargs: internal flags must not leak to tools.
        assert not seen
        write(project, 'reports/native-current.log')
        return result
    assert preflight.gate(tmp_path, runner, site, lambda *a: None,
                          native, tmp_path,
                          _preflight_canonical_acceptance=True) is result
    assert seen == [sid]
    folder, record = saved(tmp_path, sid)
    assert record['status'] == 'FAIL' and not record['canonical_pass']
    assert (folder / 'files/reports/native-current.log').read_bytes() == b'current invocation'
    assert versions.latest_pass(tmp_path, sid) is None


@pytest.mark.parametrize('incoming', [0, 1])
def test_phase1_complete_consumer_runs_after_second_track_and_keeps_first_failure(
        tmp_path, monkeypatch, incoming):
    seen = reject_consumer(monkeypatch)
    def expert(project):
        assert not seen
        write(project, 'reports/phase1/expert-track-current.json', b'{"verdict":"PASS"}')
        return 0
    monkeypatch.setattr(phase1, '_run_expert_track', expert)
    assert phase1.run_phase1_second_track(tmp_path, incoming) == incoming
    assert seen == (['D1'] if incoming == 0 else [])
    assert saved(tmp_path, 'D1')[1]['status'] == 'FAIL'
    assert versions.latest_pass(tmp_path, 'D1') is None


def test_real_fmeda_pass_cannot_mask_rejecting_complete_consumer(tmp_path, monkeypatch):
    seen = reject_consumer(monkeypatch)
    rel = 'reports/phase2/safety/fmeda_coverage.json'
    path = write(tmp_path, rel, b'previous coverage')
    def native(argv, **kwargs):
        assert not path.exists() and not seen
        path.write_text('{"verdict":"PASS"}')
        return SimpleNamespace(returncode=0, stdout='current coverage', stderr='')
    monkeypatch.setattr(design._pr, 'run', native)
    assert design.step_fmeda_fault_injection(tmp_path).status == 'PASS'
    assert seen == ['FS1']
    folder, record = saved(tmp_path, 'FS1')
    assert record['status'] == 'FAIL' and not record['canonical_pass']
    assert prior(folder, rel) == b'previous coverage'
    assert (folder / 'files' / rel).read_bytes() == path.read_bytes()


@pytest.mark.parametrize('name,sid', [
    ('step_signoff_metrics_aggregate', '37.4'),
    ('step_ip_release_docs_gen', '37.5ip'),
    ('step_ic_release_docs_gen', '37.5ic'),
])
def test_real_final_producer_invokes_complete_consumer_after_all_outputs(
        tmp_path, monkeypatch, name, sid):
    seen = reject_consumer(monkeypatch)
    monkeypatch.setattr(phase3, '_ordinary_phase3_row', lambda *a, **k: None)
    monkeypatch.setattr(phase3, '_canonical_step_condition', lambda *a: (True, 'IC fixture'))
    monkeypatch.setattr(phase3, '_ip_delivery_declared_na', lambda *a: (False, '', {}))
    monkeypatch.setattr(phase3, '_write_ip_release_docs_context', lambda *a, **k:
                        write(tmp_path, 'reports/ip-context.json', b'{}'))
    monkeypatch.setattr(phase3, '_emit_drc_attribution_reports', lambda *a: [])
    calls = []
    def native(label, argv, t0, **kwargs):
        assert not seen
        calls.append(argv)
        write(tmp_path, 'reports/final-producer-current.log')
        return SimpleNamespace(returncode=0, stdout='produced', stderr=''), None
    monkeypatch.setattr(phase3, '_run_producer', native)
    assert getattr(phase3, name)(tmp_path).status == 'PASS'
    assert seen == [sid]
    assert len(calls) == (2 if sid == '37.4' else 1)
    assert saved(tmp_path, sid)[1]['status'] == 'FAIL'
    assert versions.latest_pass(tmp_path, sid) is None


@pytest.mark.parametrize('rc,status', [(0, 'FAIL'), (1, 'FAIL'), (2, 'NOT_MEASURED'),
                                     (69, 'NOT_MEASURED')])
def test_real_a9_cosim_keeps_native_result_and_complete_consumer(tmp_path, monkeypatch, rc, status):
    seen = reject_consumer(monkeypatch)
    monkeypatch.setattr(analog._pr, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=rc, stdout='current cosim', stderr=''))
    result = analog._a9_cosim(tmp_path, SimpleNamespace(container='transport fixture'))
    assert result['rc'] == rc
    assert seen == (['A9'] if rc == 0 else [])
    assert saved(tmp_path, 'A9')[1]['status'] == status
    assert versions.latest_pass(tmp_path, 'A9') is None


@pytest.mark.parametrize('rc,fresh,status', [(0, False, 'NOT_MEASURED'),
                                         (0, True, 'FAIL'), (1, False, 'FAIL')])
def test_actual_phase2_dt1_cannot_borrow_previous_coverage(tmp_path, monkeypatch, rc, fresh, status):
    seen = reject_consumer(monkeypatch)
    write(tmp_path, 'phase2/stage2/dft/cut_netlist.v', b'module top(input clk); endmodule')
    rel = 'reports/phase2/dft/transition_coverage.json'
    output = write(tmp_path, rel, b'previous PASS coverage')
    def native(argv, **kwargs):
        assert not output.exists(), 'previous coverage must be saved before launching'
        assert argv[argv.index('--max-faults') + 1] == '400'
        assert not seen
        if fresh:
            output.write_text('{"verdict":"PASS"}')
        return SimpleNamespace(returncode=rc, stdout='', stderr='no fresh output')
    monkeypatch.setattr(design._pr, 'run', native)
    result = preflight.retained_call(tmp_path, 'DT1', design._run_transition_atpg,
                                    tmp_path, 'clk', 'fixture-pdk', canonical_acceptance=True)
    assert result['rc'] == (2 if rc == 0 and not fresh else rc)
    assert seen == (['DT1'] if fresh and rc == 0 else [])
    folder, record = saved(tmp_path, 'DT1')
    assert record['status'] == status and not record['canonical_pass']
    assert prior(folder, rel) == b'previous PASS coverage'
    assert versions.latest_pass(tmp_path, 'DT1') is None


def test_actual_phase2_dft_chain_retains_dt1_precondition_without_native_launch(tmp_path, monkeypatch):
    write(tmp_path, 'phase2/stage2/synth/netlist.v', b'module top(input clk); endmodule')
    rel = 'reports/phase2/dft/transition_coverage.json'
    output = write(tmp_path, rel, b'previous coverage before unmet precondition')
    monkeypatch.setattr(design._pr, 'run', lambda *a, **k:
                        pytest.fail('missing cut netlist cannot launch ATPG'))
    monkeypatch.setattr(design, 'step_lec_equivalence', lambda *a, **k: a[3])
    monkeypatch.setattr(design, '_derive_dft_clock_name', lambda *a, **k: 'clk')
    result = design.step_dft_lec_chain(tmp_path, 'top', 'unused', 'digital', full_chip=False)
    assert isinstance(result, list)
    folder, record = saved(tmp_path, 'DT1')
    assert record['status'] == 'NOT_MEASURED' and not record['canonical_pass']
    assert not output.exists()
    assert prior(folder, rel) == b'previous coverage before unmet precondition'
    assert (tmp_path / 'phase2/stage2/dft/transition_atpg_not_run.json').is_file()


def test_real_step8_postcheck_consumer_rejects_after_native_pass(tmp_path, monkeypatch):
    from test_step8_post_prelayout import project
    project(tmp_path)
    seen = reject_consumer(monkeypatch)
    result = design.step_sdc_validation_post_prelayout(tmp_path, 'top')
    assert result.status == 'PASS', result.detail
    assert seen == ['8']
    assert saved(tmp_path, '8')[1]['status'] == 'FAIL'
    assert versions.latest_pass(tmp_path, '8') is None


def test_real_analog_main_reaches_each_complete_consumer_without_leaking_control_flag(
        tmp_path, monkeypatch):
    from test_step_preflight_analog_phase1 import _analog_project
    project = _analog_project(tmp_path, with_l5=True)
    seen = reject_consumer(monkeypatch)
    def ready(project, runner, site, **kwargs):
        return preflight.Decision(runner=runner, site=site, flow_steps=[site],
                                  allow=True, verdict='READY')
    monkeypatch.setattr(preflight, 'decide', ready)
    monkeypatch.setattr(preflight, 'record', lambda *a, **k: None)
    produced = []
    def native(project, block, name, args=None):
        produced.append(name)
        write(project, f'reports/analog/current-{name}.json', b'{"current":true}')
        return analog.StepResult(name, block.get('name'), 'PASS', 0.0, 'native fixture')
    monkeypatch.setattr(analog, 'step_for_block', native)
    monkeypatch.setattr(analog._pr, 'run', lambda *a, **k:
                        SimpleNamespace(returncode=2, stdout='no L22 scenario', stderr=''))
    monkeypatch.setattr(sys, 'argv', ['analog_one_shot_runner', str(project)])
    analog.main()
    assert produced == list(analog._AI_STEP_NAMES)
    assert seen == [f'A{i}' for i in range(1, 9)]
    for sid in seen:
        record = saved(project, sid)[1]
        assert record['status'] == 'FAIL' and not record['canonical_pass']
        assert versions.latest_pass(project, sid) is None
    # A9 is complete only at the once-per-chip cosim call after all blocks.
    assert saved(project, 'A9')[1]['status'] == 'NOT_MEASURED'


def test_ultra_complete_leaf_keeps_existing_behavior_without_default_history(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'ultra'})
    seen = reject_consumer(monkeypatch)
    monkeypatch.setattr(phase1, '_run_expert_track', lambda *a: 0)
    assert phase1.run_phase1_second_track(tmp_path, 0) == 0
    assert not seen and not (tmp_path / 'steps/index.json').exists()
