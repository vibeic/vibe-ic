"""Operational receipts do not certify benchmark completion or erase failures."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
CONSUMERS = ['triage_record_check', 'benchmark_triage_absorption_audit']


def write(path, data):
    path.write_text(json.dumps(data))
    return path


def operational(tmp_path, category='PRODUCT_ENTRY_DEFECT'):
    phases = {k: {'status': 'NOT_MEASURED', 'reason': 'PROJECT_WORKER_ERROR'}
              for k in ['phase1_routing', 'phase2_solving',
                        'phase3_verifying', 'phase4_debugging']}
    row = {'id': 'unit', 'accepted': False, 'candidate_ready': False,
           'candidate_origin': 'NONE', 'worker_status': 'ERROR',
           'worker_error': 'RuntimeError: canonical D1 did not activate',
           'phases': phases}
    if category == 'PENDING_ACCEPTANCE':
        row.update(worker_status=None, worker_error=None,
                   candidate_origin='PROGRAM', candidate_ready=True,
                   awaiting_ai=True, awaiting_ai_review=True)
        row['phases']['phase3_verifying'] = {'run_verdict': 'PASS',
                                            'ran': {'lint': 'PASS'}, 'failed': []}
    source = write(tmp_path / 'solve_report.json',
                   {'bench': 'ordinary-suite', 'total': 1, 'accepted': 0,
                    'results': [row]})
    acceptance = write(tmp_path / 'program_first_ai_review_acceptance.json',
                       {'schema': 'vibeic.benchmark.program_first_ai_review.v3',
                        'status': 'PENDING', 'total': 1,
                        'accepted': 0, 'accepted_ids': []})
    record = {'bench': 'ordinary-suite', 'id': 'unit', 'category': category,
              'verdict': 'NOT_MEASURED', 'closeloop': False,
              'independent_blind_passes': None,
              'rationale': 'Entry blocked or independent acceptance pending',
              'evidence': str(source) + '#unit'}
    return record, source, acceptance


def cli(tmp_path, consumer, records):
    src = write(tmp_path / 'triage.json', {'records': records})
    out = tmp_path / (consumer + '.json')
    cp = subprocess.run([sys.executable, str(PROGRAMS / (consumer + '.py')),
                         str(src), '--json', str(out)], capture_output=True,
                        text=True, timeout=20)
    return cp, json.loads(out.read_text())


@pytest.mark.parametrize('consumer', CONSUMERS)
@pytest.mark.parametrize('category', ['PRODUCT_ENTRY_DEFECT', 'PENDING_ACCEPTANCE'])
def test_proven_operational_record_is_valid_but_unscorable(tmp_path, consumer, category):
    rec, source, acceptance = operational(tmp_path, category)
    cp, report = cli(tmp_path, consumer, [rec])
    assert cp.returncode == 0, cp.stderr
    assert report['verdict'] == 'VALID_UNMEASURED'
    assert report['records_valid'] is True
    assert report['benchmark_complete'] is False
    assert report['scorable'] is False
    assert report['score_status'] == 'NOT_MEASURED'
    assert report['n_records'] == report['n_unmeasured'] == 1
    assert report['unmeasured'][0]['id'] == 'unit'
    assert len(report['provenance']) == 1
    assert len(report['provenance'][0]['solve_sha256']) == 64
    assert len(report['provenance'][0]['acceptance_sha256']) == 64
    assert 'PASS:' not in cp.stdout
    assert report.get('n_exempt', 0) == report.get('n_absorbed', 0) == 0


@pytest.mark.parametrize('consumer', CONSUMERS)
@pytest.mark.parametrize('omit_pending', [False, True])
def test_residual_population_may_omit_only_verified_accepted_rows(
        tmp_path, consumer, omit_pending):
    rec, source, acceptance = operational(tmp_path, 'PENDING_ACCEPTANCE')
    solve = json.loads(source.read_text())
    accepted = {**solve['results'][0], 'id': 'closed', 'accepted': True,
                'awaiting_ai_review': False}
    solve['results'].append(accepted)
    acc = json.loads(acceptance.read_text())
    acc.update(accepted=1, accepted_ids=['closed'])
    solve['accepted'] = 1
    if omit_pending:
        solve['results'].append({**solve['results'][0], 'id': 'still_open'})
    solve['total'] = acc['total'] = len(solve['results'])
    write(source, solve)
    write(acceptance, acc)
    cp, report = cli(tmp_path, consumer, [rec])
    assert cp.returncode == (1 if omit_pending else 0), (cp.stdout, cp.stderr)
    assert report['verdict'] == ('FAIL' if omit_pending else 'VALID_UNMEASURED')
    assert report['benchmark_complete'] is False
    assert report['scorable'] is False
    assert report['n_records'] == 1


@pytest.mark.parametrize('consumer', CONSUMERS)
@pytest.mark.parametrize('mutation', [
    'missing_evidence', 'missing_source', 'missing_acceptance', 'wrong_fragment',
    'wrong_bench', 'wrong_id', 'bad_status', 'blind_pass', 'ambiguous_blind',
    'native_fail', 'failed_list', 'functional_fail', 'forged_complete',
    'forged_count', 'duplicate_source', 'duplicate_triage', 'missing_population',
    'accepted_row', 'malformed_phase', 'provenance_hash', 'conflicting_category',
    'conflicting_verdict', 'fake_entry', 'forged_row_count',
    'complete_claim', 'source_blind_pass', 'native_fail_detail',
    'bogus_status', 'score_pass',
])
def test_operational_claim_refuses_missing_or_contradictory_provenance(tmp_path, consumer, mutation):
    rec, source, acceptance = operational(tmp_path)
    data = json.loads(source.read_text())
    acc = json.loads(acceptance.read_text())
    records = [rec]
    if mutation == 'missing_evidence': rec.pop('evidence')
    elif mutation == 'missing_source': source.unlink()
    elif mutation == 'missing_acceptance': acceptance.unlink()
    elif mutation == 'wrong_fragment': rec['evidence'] = str(source) + '#other'
    elif mutation == 'wrong_bench': rec['bench'] = 'different-suite'
    elif mutation == 'wrong_id': rec['id'] = 'different-unit'
    elif mutation == 'bad_status': rec['verdict'] = 'PROBABLY_FINE'
    elif mutation == 'blind_pass': rec['independent_blind_passes'] = True
    elif mutation == 'ambiguous_blind': rec['independent_blind_passes'] = 'solved on retry'
    elif mutation == 'native_fail':
        data['results'][0]['phases']['phase3_verifying'] = {'ran': {'simulation': 'FAIL'}}
    elif mutation == 'failed_list':
        data['results'][0]['phases']['phase3_verifying']['failed'] = ['simulation']
    elif mutation == 'functional_fail': rec['functional_status'] = 'FAIL'
    elif mutation == 'forged_complete': acc['status'] = 'COMPLETE'
    elif mutation == 'forged_count': data['total'] = 2
    elif mutation == 'duplicate_source':
        data['results'].append(dict(data['results'][0])); data['total'] = 2
    elif mutation == 'duplicate_triage': records.append(dict(rec))
    elif mutation == 'missing_population':
        data['results'].append({**data['results'][0], 'id': 'other'})
        data['total'] = acc['total'] = 2
    elif mutation == 'accepted_row': data['results'][0]['accepted'] = True
    elif mutation == 'malformed_phase': data['results'][0]['phases'] = []
    elif mutation == 'provenance_hash': rec['evidence_sha256'] = '0' * 64
    elif mutation == 'conflicting_category': rec['letter'] = 'H'
    elif mutation == 'conflicting_verdict': rec['outcome'] = 'REAL_RTL_BUG'
    elif mutation == 'fake_entry': data['results'][0]['worker_error'] = None
    elif mutation == 'forged_row_count':
        acc.update(accepted=1, accepted_ids=['unit']); data['accepted'] = 1
    elif mutation == 'complete_claim': rec.update(status='COMPLETE', scorable=True)
    elif mutation == 'source_blind_pass': data['results'][0]['independent_blind_passes'] = True
    elif mutation == 'native_fail_detail':
        data['results'][0]['phases']['phase3_verifying']['status'] = 'FAIL: mismatch'
    elif mutation == 'bogus_status': rec['status'] = 'BOGUS'
    elif mutation == 'score_pass': rec['score_status'] = 'PASS'
    if source.exists(): write(source, data)
    if acceptance.exists(): write(acceptance, acc)
    cp, report = cli(tmp_path, consumer, records)
    assert cp.returncode == 1, (mutation, cp.stdout, cp.stderr)
    assert report['verdict'] == 'FAIL'
    assert report['n_records'] == len(records)
    assert report['records_valid'] is False
    assert report['benchmark_complete'] is report['scorable'] is False
    assert report['violations']


@pytest.mark.parametrize('consumer', CONSUMERS)
def test_empty_population_does_not_converge(tmp_path, consumer):
    cp, report = cli(tmp_path, consumer, [])
    assert cp.returncode == 1
    assert report['verdict'] == 'FAIL'
    assert report['benchmark_complete'] is report['scorable'] is False


@pytest.mark.parametrize('consumer', CONSUMERS)
@pytest.mark.parametrize('category', ['F', 'G', 'H'])
@pytest.mark.parametrize('close_loop', ['absent', 'attempted', 'justified'])
def test_measured_agent_fixable_requirements_are_preserved(tmp_path, consumer, category, close_loop):
    record = {'id': 'measured', 'category': category, 'verdict': 'REAL_RTL_BUG',
              'rationale': 'Incorrect reset polarity',
              'closeloop': close_loop == 'attempted'}
    if close_loop == 'justified': record['skip_justification'] = 'Deferred for recorded tool outage'
    if close_loop != 'absent': record['absorption_ref'] = 'general reset rule and executable control'
    cp, report = cli(tmp_path, consumer, [record])
    assert cp.returncode == (1 if close_loop == 'absent' else 0), cp.stderr
    assert report['n_records'] == 1
    if close_loop == 'absent':
        expected = ('agent_fixable_no_closeloop_no_skip' if consumer == CONSUMERS[0]
                    else 'unabsorbed_ai_solvable')
        assert expected in {v['rule'] for v in report['violations']}


@pytest.mark.parametrize('consumer', CONSUMERS)
@pytest.mark.parametrize('category', ['F', 'G', 'H', 'ENTRY_BOGUS'])
def test_raw_not_measured_cannot_launder_a_functional_category(tmp_path, consumer, category):
    record = {'id': 'failed', 'category': category, 'verdict': 'NOT_MEASURED',
              'closeloop': False, 'functional_status': 'FAIL'}
    cp, report = cli(tmp_path, consumer, [record])
    assert cp.returncode == 1
    assert report['violations']
    assert report['n_unmeasured'] == 0


@pytest.mark.parametrize('consumer', CONSUMERS)
def test_malformed_record_is_not_silently_dropped(tmp_path, consumer):
    cp, report = cli(tmp_path, consumer, [None])
    assert cp.returncode == 2
    assert report['verdict'] == 'IO_ERROR'


@pytest.mark.parametrize('consumer', CONSUMERS)
@pytest.mark.parametrize('claim', [{'status': 'COMPLETE'}, {'accepted': 1},
                                  {'total': 2}, {'n_records': 0}, {'scorable': True}])
def test_wrapper_cannot_forge_completion(tmp_path, consumer, claim):
    rec, _, _ = operational(tmp_path)
    src = write(tmp_path / 'claimed.json', {'records': [rec], **claim})
    out = tmp_path / 'report.json'
    cp = subprocess.run([sys.executable, str(PROGRAMS / (consumer + '.py')),
                         str(src), '--json', str(out)], capture_output=True,
                        text=True, timeout=20)
    assert cp.returncode == 2
    assert json.loads(out.read_text())['verdict'] == 'IO_ERROR'


@pytest.mark.parametrize('consumer', CONSUMERS)
@pytest.mark.parametrize('category', ['F', 'G', 'H'])
def test_mixed_population_keeps_measured_failure_obligations(tmp_path, consumer, category):
    rec, source, acceptance = operational(tmp_path)
    solve = json.loads(source.read_text())
    measured = {**solve['results'][0], 'id': 'measured'}
    measured['phases'] = {**measured['phases'],
                          'phase3_verifying': {'status': 'FAIL'}}
    solve['results'].append(measured)
    solve['total'] = 2
    write(source, solve)
    acc = json.loads(acceptance.read_text()); acc['total'] = 2
    write(acceptance, acc)
    failed = {'bench': rec['bench'], 'id': 'measured', 'category': category,
              'verdict': 'REAL_RTL_BUG', 'closeloop': False}
    cp, report = cli(tmp_path, consumer, [rec, failed])
    assert cp.returncode == 1
    assert report['n_records'] == 2
    assert report['n_unmeasured'] == report['n_functional'] == 1
    assert {v['id'] for v in report['violations']} == {'measured'}
    assert report['benchmark_complete'] is report['scorable'] is False


@pytest.mark.parametrize('consumer', CONSUMERS)
@pytest.mark.parametrize('origin', ['AI_BACKUP_PENDING', 'BOGUS'])
def test_pending_backup_needs_real_outstanding_obligation(tmp_path, consumer, origin):
    rec, source, _ = operational(tmp_path, 'PENDING_ACCEPTANCE')
    rec['evidence'] = 'solve_report.json#unit'
    data = json.loads(source.read_text())
    data['results'][0].update(candidate_origin=origin, candidate_ready=False,
                              awaiting_ai_review=False, awaiting_ai_backup=True)
    write(source, data)
    cp, report = cli(tmp_path, consumer, [rec])
    assert cp.returncode == (0 if origin == 'AI_BACKUP_PENDING' else 1)
    assert report['verdict'] == ('VALID_UNMEASURED' if origin == 'AI_BACKUP_PENDING' else 'FAIL')
    assert report['benchmark_complete'] is report['scorable'] is False
