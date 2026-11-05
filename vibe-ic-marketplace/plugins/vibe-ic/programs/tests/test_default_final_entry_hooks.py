"""Actual Default call seams retain evidence; these are not native IC claims."""
import json
import os
from pathlib import Path
import sys

import pytest

PROGRAMS = Path(os.environ.get('VIBEIC_FINAL_ENTRY_PROGRAMS',
                              str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import design_one_shot_runner as design
import execution_policy as policy
import flow_compliance_check as fcc
import step_output_collector as versions
from _invocation_fixture import bind_invocation_top


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(policy, '_ordinary_runtime', None)


def saved(project, sid):
    entry = next((r for r in versions._read_index(project)['steps'] if r['id'] == sid), None)
    assert entry is not None, f'no actual invocation saved for Step {sid}'
    folder = project / 'steps' / entry['folder']
    return folder, json.loads((folder / 'outputs.json').read_text())




def write(project, relative, content):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path




















@pytest.mark.parametrize('name,sid', [('step_fpga_compile', '6'), ('step_fpga_burn', '39')])
def test_actual_fpga_missing_input_is_saved_without_starting_hardware(tmp_path, name, sid):
    args = (tmp_path, 'top', 'unused') if sid == '6' else (tmp_path, 'top')
    result = getattr(design, name)(*args)
    assert result.status == 'NOT_MEASURED'
    _, record = saved(tmp_path, sid)
    assert record['status'] == 'NOT_MEASURED'
    assert record['result']['step_rows'][0]['detail'] == result.detail
    assert not record['canonical_pass']






















def test_exception_unwinds_local_call_stack_and_partial_evidence_is_recovered(tmp_path):
    bind_invocation_top(tmp_path, 'top')
    attempt = versions.begin_step(tmp_path, '37')
    with pytest.raises(KeyboardInterrupt):
        with versions.active_steps(tmp_path, [attempt]):
            write(tmp_path, 'reports/native-partial.log', b'partial bytes')
            raise KeyboardInterrupt()
    assert not versions._ACTIVE_LOCAL_CALLS
    following = versions.begin_step(tmp_path, '38')
    versions.finish_step(tmp_path, following, verdict='NOT_MEASURED')
    folder, interrupted = saved(tmp_path, '37')
    assert interrupted['status'] == 'INTERRUPTED'
    assert (folder / 'files/reports/native-partial.log').read_bytes() == b'partial bytes'




@pytest.mark.parametrize('verdict', ['PASS', 'FAIL', 'NOT_INVOCABLE'])
def test_actual_p0_main_retains_exact_typed_consumer_without_rerunning_it(tmp_path, monkeypatch, verdict):
    write(tmp_path, 'phase2/stage1/rtl/top.v', b'module top(input a, output b); assign b=a; endmodule\n')
    records = [fcc._p0_gate_record('fixture_check', verdict, 'actual fixture verdict',
                                  {'exit_code': 0 if verdict == 'PASS' else 1 if verdict == 'FAIL' else 2})]
    calls = []
    def structural(project, **kwargs):
        calls.append(project)
        kwargs['records_out'].extend(records)
        return verdict != 'FAIL', [], [], []
    monkeypatch.setattr(fcc, '_run_structural_rtl_gates', structural)
    monkeypatch.setattr(fcc, '_run_yosys_gates', lambda project: (True, []))
    monkeypatch.setattr(fcc, 'check_step', lambda project, row, *_a, **_k:
        fcc.StepResult(id=row['id'], name=row['name'], stage=row['stage'], status='PASS',
                       reasons=[], evidence=[]))
    fcc.main([str(tmp_path), '--phase', '2', '--strict-structural', '--json', str(tmp_path / 'audit.json')])
    _, record = saved(tmp_path, 'P0')
    assert calls == [tmp_path]
    actual = record['result']['canonical_consumer']
    assert actual['gate_records'] == records
    assert record['status'] == actual['status']
    assert record['canonical_pass'] is (verdict == 'PASS')
    assert bool(versions.latest_pass(tmp_path, 'P0')) is (verdict == 'PASS')




@pytest.mark.parametrize('verdict', ['PASS', 'FAIL'])
def test_nested_p0_main_preserves_the_existing_owner_and_its_verdict(
        tmp_path, monkeypatch, verdict):
    """Real main/collector ownership; the neutral structural leaf is isolated.

    Both observed field contexts still execute their own P0 consumer. They
    must not recover a live sibling's retained version or credit its result.
    Existing standalone P0 controls above cover canonical capture separately.
    """
    import hashlib

    monkeypatch.setattr(fcc, '_STRUCTURAL_RTL_GATES', ('retention_fixture_check',))
    monkeypatch.setattr(fcc, '_run_yosys_gates', lambda project: (True, []))
    monkeypatch.setattr(fcc, 'check_step', lambda project, row, *_a, **_k:
        fcc.StepResult(id=row['id'], name=row['name'], stage=row['stage'],
                       status='PASS', reasons=[], evidence=[]))
    for label, parent_scope in (('direct_child', 'ALL'),
                                ('stage2_child', 'ALL:stage2')):
        stage = 1
        project = tmp_path / label
        relative = 'phase2/stage1/rtl/top.v'
        rtl = write(project, relative,
                    b'module top(input a, output b); assign b=a; endmodule\n')
        inputs = {relative: {'sha256': hashlib.sha256(rtl.read_bytes()).hexdigest()}}
        owner = versions.begin_step(project, 'P0', inputs=inputs)
        folder = project / owner['storage_root'] / owner['folder']
        original_attempt = (folder / 'attempt.json').read_bytes()
        records = [fcc._p0_gate_record(
            'retention_fixture_check', verdict, 'neutral structural leaf result',
            {'exit_code': 0 if verdict == 'PASS' else 1})]
        calls = []

        def structural(actual_project, **kwargs):
            calls.append(actual_project)
            kwargs['records_out'].extend(records)
            return verdict == 'PASS', [], [], []

        monkeypatch.setattr(fcc, '_run_structural_rtl_gates', structural)
        monkeypatch.setenv('VIBEIC_FCC_ACTIVE_SCOPES', parent_scope)
        report_path = project / 'nested.json'
        rc = fcc.main([str(project), '--stage', str(stage), '--phase', '2',
                       '--strict-structural', '--json', str(report_path)])
        report = json.loads(report_path.read_text())
        p0 = next(row for row in report['steps'] if str(row['id']) == 'P0')
        owner_metadata = folder / ('outputs.json' if (folder / 'outputs.json').is_file()
                                   else 'attempt.json')
        observed_owner = json.loads(owner_metadata.read_text())['status']
        observation = {'stage': stage, 'parent_scope': parent_scope,
                       'structural_calls': len(calls), 'rc': rc,
                       'nested_overall': report['overall'],
                       'nested_p0_status': p0['status'],
                       'nested_gate_records': p0['gate_records'],
                       'observed_owner_status': observed_owner,
                       'scope': 'Real FCC main/collector; neutral structural leaf '
                                'and unrelated YAML row consumers are isolated.'}
        (project / 'P0_OWNER_OBSERVATION.json').write_text(json.dumps(observation))
        print('P0_OWNER_OBSERVATION ' + json.dumps(observation, sort_keys=True))
        assert observed_owner == 'RUNNING', (
            f'existing P0 owner changed to {observed_owner}')
        assert (folder / 'attempt.json').read_bytes() == original_attempt
        assert (folder / 'inputs' / relative).read_bytes() == rtl.read_bytes()
        assert calls == [project]
        assert p0['gate_records'] == records
        assert p0['status'] == verdict
        assert report['overall'] == verdict
        assert rc == (0 if verdict == 'PASS' else 1)
        finished = versions.finish_step(project, owner, verdict=verdict,
                                        result={'neutral_consumer': p0},
                                        canonical_pass=verdict == 'PASS')
        assert finished['status'] == verdict and not finished['capture_errors']
        assert finished['canonical_pass'] is (verdict == 'PASS')
        assert (folder / 'inputs' / relative).read_bytes() == rtl.read_bytes()
