"""Existing producer calls retain old bytes and their actual canonical verdict."""
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROGRAMS = Path(os.environ.get('VIBEIC_CANONICAL_RETENTION_PROGRAMS',
                              str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import execution_backend_gates as gates
import execution_policy as policy
import phase1_one_shot_runner as phase1
import phase3_one_shot_runner as phase3
import step_output_collector as versions
import vibe_ic_one_shot_runner as front


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(policy, '_ordinary_runtime', None)


def saved(project, sid):
    row = next((r for r in versions._read_index(project)['steps'] if r['id'] == sid), None)
    assert row is not None, f'Step {sid} did not retain its invocation'
    folder = project / 'steps' / row['folder']
    return folder, json.loads((folder / 'outputs.json').read_text())


def prior_bytes(folder, relative):
    manifest = json.loads((folder / 'before/outputs.json').read_text())
    entry = next(row for row in manifest['outputs'] if row['rel'] == relative)
    return (folder / 'before' / entry['snapshot']).read_bytes()


@pytest.mark.parametrize('name,sid', [
    ('foundry_handoff', '38'), ('tapeout_checklist', '36'), ('gds_xor', '37.3')])
def test_real_pre_audit_refusal_preserves_the_file_it_invalidates(tmp_path, monkeypatch, name, sid):
    entry = next(e for e in phase3._PRE_AUDIT_PRODUCERS if e[0] == name)
    original = tmp_path / entry[2]
    original.parent.mkdir(parents=True)
    original.write_bytes(b'{"evidence":"previous producer bytes"}')
    def refuse(project, actual_name, *_args):
        assert actual_name == name
        assert not original.exists(), 'a failed retry must not consume the old working copy'
        return phase3._signoff_not_checked(name, 0.0, 'producer cannot run')
    monkeypatch.setattr(phase3, '_run_declared_signoff_gate', refuse)
    rows = phase3.run_pre_audit_producers(tmp_path, only_names=[name])
    assert rows[0].status == 'NOT_MEASURED'
    folder, record = saved(tmp_path, sid)
    before = json.loads((folder / 'before/outputs.json').read_text())
    kept = next(r for r in before['outputs'] if r['rel'] == entry[2])
    assert (folder / 'before' / kept['snapshot']).read_bytes() == b'{"evidence":"previous producer bytes"}'
    assert record['status'] == 'NOT_MEASURED' and not record['canonical_pass']
    assert versions.latest_pass(tmp_path, sid) is None
    assert [r['id'] for r in versions._read_index(tmp_path)['steps']] == [sid]


def test_producer_success_is_not_a_canonical_pass(tmp_path, monkeypatch):
    output = tmp_path / 'reports/audit/tapeout_checklist.json'
    def produce(project, name, *_args):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('{"producer":"current bytes"}')
        return phase3.StepResult(name, 'PASS', 0.0, 'producer completed', [str(output)])
    monkeypatch.setattr(phase3, '_run_declared_signoff_gate', produce)
    monkeypatch.setattr(gates, 'evaluate', lambda project, row: {
        'status': 'FAIL', 'step': {'id': row['id'], 'status': 'FAIL'},
        'ledger': [{'gate': 'tapeout_signoff_check', 'rc': 1, 'verdict': 'FAIL'}]})
    assert phase3.run_pre_audit_producers(tmp_path, only_names=['tapeout_checklist'])[0].status == 'PASS'
    _, record = saved(tmp_path, '36')
    assert record['status'] == 'FAIL'
    assert record['result']['canonical_consumer']['ledger'][0]['rc'] == 1
    assert not record['canonical_pass']
    assert versions.latest_pass(tmp_path, '36') is None


def test_consumer_acceptance_and_failed_retry_keep_distinct_versions(tmp_path, monkeypatch):
    output = tmp_path / 'reports/audit/tapeout_checklist.json'
    content = [b'{"attempt":1}', b'{"attempt":2}']
    def produce(project, name, *_args):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content.pop(0))
        return phase3.StepResult(name, 'PASS', 0.0, 'producer completed', [str(output)])
    outcomes = iter(['PASS', 'FAIL'])
    def consume(project, row):
        assert output.read_bytes() in (b'{"attempt":1}', b'{"attempt":2}')
        status = next(outcomes)
        return {'status': status, 'step': {'id': row['id'], 'status': status}, 'ledger': []}
    monkeypatch.setattr(phase3, '_run_declared_signoff_gate', produce)
    monkeypatch.setattr(gates, 'evaluate', consume)
    phase3.run_pre_audit_producers(tmp_path, only_names=['tapeout_checklist'])
    folder, record = saved(tmp_path, '36')
    assert record['canonical_pass'] is True
    relative = str(output.relative_to(tmp_path))
    assert record['result']['canonical_consumer']['outputs'] == {
        relative: {relative: hashlib.sha256(b'{"attempt":1}').hexdigest()}}
    accepted = versions.latest_pass(tmp_path, '36')
    assert accepted['folder'] == str(folder.relative_to(tmp_path / 'steps'))
    phase3.run_pre_audit_producers(tmp_path, only_names=['tapeout_checklist'])
    newer, failed = saved(tmp_path, '36')
    assert newer != folder and failed['status'] == 'FAIL' and not failed['canonical_pass']
    assert (folder / 'files/reports/audit/tapeout_checklist.json').read_bytes() == b'{"attempt":1}'
    assert (newer / 'files/reports/audit/tapeout_checklist.json').read_bytes() == b'{"attempt":2}'
    assert versions.latest_pass(tmp_path, '36')['folder'] == accepted['folder']


def test_unknown_input_identity_does_not_claim_current_pass(tmp_path):
    attempt = versions.begin_step(tmp_path, '1')
    versions.finish_step(tmp_path, attempt, verdict='PASS', canonical_pass=True)
    historical = versions.latest_pass(tmp_path, '1')
    assert historical['status'] == 'PASS'
    assert historical['current_inputs'] is False


def test_step05_producer_completion_reaches_the_real_refusing_consumer(tmp_path):
    assert phase1._run_step_0_5ic(tmp_path) == 0
    _, record = saved(tmp_path, '0.5ic')
    assert record['status'] != 'PASS'
    assert record['result']['canonical_consumer']['status'] != 'PASS'
    assert not record['canonical_pass']
    assert versions.latest_pass(tmp_path, '0.5ic') is None


def test_step05_current_declared_die_reaches_the_real_accepting_consumer(tmp_path):
    import area_budget_basis_gen as area
    from programs.tests.test_r0929_deliverable_consistency import _project
    from programs.tests._route_fixture import stage_owner_route
    project = _project(tmp_path)
    path = project / 'input/step_0_5ic_answers.json'
    answers = json.loads(path.read_text())
    answers['operator_template']['absent_reason'] = (
        'The fixture owner requested independent DIE delivery without an operator or purchased slot.')
    path.write_text(json.dumps(answers))
    stage_owner_route(project, 'ic')
    assert area.main([str(project), '--answers', str(path), '--out', str(path)]) == 0
    assert phase1._run_step_0_5ic(project) == 0
    folder, record = saved(project, '0.5ic')
    assert record['status'] == 'PASS' and record['canonical_pass'] is True
    consumer = record['result']['canonical_consumer']
    assert consumer['status'] == 'PASS'
    assert {r['gate'] for r in consumer['ledger']} >= {
        'submission_template_check', 'tapeout_declaration_check'}
    assert versions.latest_pass(project, '0.5ic')['folder'] == str(folder.relative_to(project / 'steps'))


def test_real_derived_refusal_retains_deleted_flag_and_returned_reason(tmp_path, monkeypatch):
    flag = phase3._pl.postroute_timing_repair_dir(tmp_path) / 'no_repair_needed.flag'
    flag.parent.mkdir(parents=True)
    flag.write_bytes(b'previous repair evidence')
    def refuse(*_args, **_kwargs):
        flag.unlink()
        return SimpleNamespace(returncode=2, stdout='', stderr='current basis absent')
    monkeypatch.setattr(phase3.subprocess, 'run', refuse)
    outcome = phase3._run_derived_artefact_generators(tmp_path, None, skip_names=[
        'foundry_handoff_pack_gen.py', 'tapeout_checklist_gen.py'])
    assert outcome[0]['rc'] == 2
    folder, record = saved(tmp_path, '32')
    before = json.loads((folder / 'before/outputs.json').read_text())
    retained = next(r for r in before['outputs'] if r['rel'] == str(flag.relative_to(tmp_path)))
    assert (folder / 'before' / retained['snapshot']).read_bytes() == b'previous repair evidence'
    assert record['result']['producer_return']['message'] == 'current basis absent'
    assert not record['canonical_pass']


def test_atpg_missing_inputs_retains_each_actual_disclosure(tmp_path, monkeypatch):
    monkeypatch.setattr(phase3._pr, 'run', lambda *_a, **_k: pytest.fail('native must not start'))
    written, notes = [], []
    assert phase3.run_at_speed_atpg_producers(tmp_path, written, notes) is None
    assert written == [] and len(notes) == 3
    for sid in ('DT1', 'DT2', 'DT3'):
        folder, record = saved(tmp_path, sid)
        relative = phase3._ATPG_NOT_RUN_REL[sid]
        assert (folder / 'files' / relative).read_bytes() == (tmp_path / relative).read_bytes()
        assert record['result']['producer_return']['rc'] == 2
        assert record['status'] == 'NOT_MEASURED' and not record['canonical_pass']
        assert versions.latest_pass(tmp_path, sid) is None


def test_atpg_due_retry_cannot_consume_its_previous_report(tmp_path, monkeypatch):
    monkeypatch.setattr(phase3, 'atpg_librelane_views', lambda *_: ([], None))
    monkeypatch.setattr(phase3, 'atpg_missing_inputs', lambda *_: [])
    monkeypatch.setattr(phase3, 'atpg_needs_regrade', lambda *_: True)
    monkeypatch.setattr(phase3, 'routed_sdc_clock', lambda *_: 10)
    for relative in phase3._ATPG_COVERAGE_REL.values():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'previous grade bytes')
    seen = []
    def no_output(argv, **_kwargs):
        path = Path(argv[argv.index('--json') + 1])
        assert not path.exists(), 'due retry must invalidate the old working report after capture'
        seen.append(path)
        return SimpleNamespace(returncode=0, stdout='', stderr='producer wrote nothing')
    monkeypatch.setattr(phase3._pr, 'run', no_output)
    written, notes = [], []
    phase3.run_at_speed_atpg_producers(tmp_path, written, notes)
    assert written == [] and len(seen) == 3
    for sid, relative in phase3._ATPG_COVERAGE_REL.items():
        folder, record = saved(tmp_path, sid)
        assert prior_bytes(folder, relative) == b'previous grade bytes'
        assert not (tmp_path / relative).exists()
        assert record['result']['producer_return']['producer_rc'] == 0
        assert record['status'] == 'NOT_MEASURED' and not record['canonical_pass']
        disclosure = json.loads((tmp_path / phase3._ATPG_NOT_RUN_REL[sid]).read_text())
        assert disclosure['not_run_stage'] == 'producer_wrote_no_artifact'


def test_atpg_retiring_old_disclosures_keeps_their_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(phase3, 'atpg_librelane_views', lambda *_: (None, None))
    monkeypatch.setattr(phase3, 'atpg_needs_regrade', lambda *_: False)
    monkeypatch.setattr(phase3._pr, 'run', lambda *_a, **_k: pytest.fail('valid grade is reused'))
    for mapping in (phase3._ATPG_NOT_RUN_REL, phase3._ATPG_NOT_RUN_LEGACY_COLOCATED_REL):
        for relative in mapping.values():
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'previous refusal bytes')
    phase3.run_at_speed_atpg_producers(tmp_path, [], [])
    for sid in ('DT1', 'DT2', 'DT3'):
        folder, record = saved(tmp_path, sid)
        for mapping in (phase3._ATPG_NOT_RUN_REL, phase3._ATPG_NOT_RUN_LEGACY_COLOCATED_REL):
            relative = mapping[sid]
            assert prior_bytes(folder, relative) == b'previous refusal bytes'
            assert not (tmp_path / relative).exists()
        assert record['result']['producer_return']['rc'] is None
        assert not record['canonical_pass'], 'reuse without new production is historical evidence'


MIXED = [
    ('M1', 'mixed_signal_top_lvs_run.py', 'top_lvs_run.json'),
    ('M2', 'mixed_signal_power_domain_run.py', 'power_domain_producer_audit.json'),
    ('M3', 'mixed_signal_m3_run.py', 'm3_producer_audit.json'),
    ('M4', 'mixed_signal_signoff_run.py', 'signoff_producer_audit.json'),
]


@pytest.mark.parametrize('sid,program,audit', MIXED)
def test_mixed_phase_refusal_preserves_the_prior_audit(tmp_path, monkeypatch, sid, program, audit):
    primary = tmp_path / 'reports/analog/mixed_signal' / audit
    primary.parent.mkdir(parents=True)
    primary.write_bytes(b'previous producer audit')
    def produce(argv, **kwargs):
        assert argv[1] == str(PROGRAMS / program)
        assert kwargs['env'] == {'TASK': 'local'}
        if sid != 'M1':
            assert not primary.exists()
        primary.write_bytes(b'current refusal audit')
        return SimpleNamespace(returncode=2)
    monkeypatch.setattr(front.subprocess, 'run', produce)
    rc = front._run_phase('mixed control', PROGRAMS / program,
                          [str(tmp_path), '--json', str(primary)], env={'TASK': 'local'})
    assert rc == 2
    folder, record = saved(tmp_path, sid)
    relative = str(primary.relative_to(tmp_path))
    assert prior_bytes(folder, relative) == b'previous producer audit'
    assert (folder / 'files' / relative).read_bytes() == b'current refusal audit'
    assert record['status'] == 'NOT_MEASURED' and not record['canonical_pass']
    assert versions.latest_pass(tmp_path, sid) is None


def test_mixed_phase_completion_does_not_override_the_consumer(tmp_path, monkeypatch):
    monkeypatch.setattr(front.subprocess, 'run', lambda *_a, **_k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(gates, 'evaluate', lambda project, row: {
        'status': 'FAIL', 'step': {'id': row['id'], 'status': 'FAIL'},
        'ledger': [{'gate': 'mixed_signal_merge_check', 'rc': 1, 'verdict': 'FAIL'}]})
    assert front._run_phase('mixed control', PROGRAMS / MIXED[0][1], [str(tmp_path)]) == 0
    _, record = saved(tmp_path, 'M1')
    assert record['status'] == 'FAIL' and not record['canonical_pass']
    assert record['result']['canonical_consumer']['ledger'][0]['rc'] == 1


def test_mixed_phase_accepted_version_survives_a_failed_retry(tmp_path, monkeypatch):
    import _flow_yaml
    primary = tmp_path / 'reports/analog/mixed_signal' / MIXED[1][2]
    row = next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == 'M2')
    returns = iter([0, 2])
    def produce(*_args, **_kwargs):
        primary.parent.mkdir(parents=True, exist_ok=True)
        rc = next(returns)
        primary.write_text(json.dumps({'rc': rc}))
        if rc == 0:
            for relative in row['required_outputs']:
                path = tmp_path / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'controlled producer output')
        return SimpleNamespace(returncode=rc)
    monkeypatch.setattr(front.subprocess, 'run', produce)
    monkeypatch.setattr(gates, 'evaluate', lambda project, step: {
        'status': 'PASS', 'step': {'id': step['id'], 'status': 'PASS'}, 'ledger': []})
    args = [str(tmp_path), '--json', str(primary)]
    assert front._run_phase('mixed control', PROGRAMS / MIXED[1][1], args) == 0
    first, accepted = saved(tmp_path, 'M2')
    assert accepted['canonical_pass'] is True
    assert front._run_phase('mixed control', PROGRAMS / MIXED[1][1], args) == 2
    second, refused = saved(tmp_path, 'M2')
    assert second != first and not refused['canonical_pass']
    assert versions.latest_pass(tmp_path, 'M2')['folder'] == str(first.relative_to(tmp_path / 'steps'))
    assert json.loads((first / 'files' / primary.relative_to(tmp_path)).read_text()) == {'rc': 0}


def test_mixed_phase_interruption_preserves_partial_output(tmp_path, monkeypatch):
    primary = tmp_path / 'reports/analog/mixed_signal' / MIXED[2][2]
    def interrupt(*_args, **_kwargs):
        primary.parent.mkdir(parents=True, exist_ok=True)
        primary.write_bytes(b'partial native audit')
        raise KeyboardInterrupt('bounded interruption')
    monkeypatch.setattr(front.subprocess, 'run', interrupt)
    with pytest.raises(KeyboardInterrupt, match='bounded interruption'):
        front._run_phase('mixed control', PROGRAMS / MIXED[2][1],
                         [str(tmp_path), '--json', str(primary)])
    folder, record = saved(tmp_path, 'M3')
    assert record['status'] == 'INTERRUPTED' and not record['canonical_pass']
    assert (folder / 'files' / primary.relative_to(tmp_path)).read_bytes() == b'partial native audit'


def test_nonmixed_phase_does_not_create_a_mixed_version(tmp_path, monkeypatch):
    monkeypatch.setattr(front.subprocess, 'run', lambda *_a, **_k: SimpleNamespace(returncode=7))
    assert front._run_phase('other phase', PROGRAMS / 'phase1_one_shot_runner.py', [str(tmp_path)]) == 7
    assert not (tmp_path / 'steps').exists()
