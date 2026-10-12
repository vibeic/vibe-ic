"""Actual Default call seams retain evidence; these are not native IC claims."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROGRAMS = Path(os.environ.get('VIBEIC_FINAL_ENTRY_PROGRAMS',
                              str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import design_one_shot_runner as design
import execution_backend_gates as gates
import execution_policy as policy
import flow_compliance_check as fcc
import phase3_one_shot_runner as phase3
import step_output_collector as versions
import step_preflight as preflight
import vibe_ic_one_shot_runner as front


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(policy, '_ordinary_runtime', None)


def saved(project, sid):
    entry = next((r for r in versions._read_index(project)['steps'] if r['id'] == sid), None)
    assert entry is not None, f'no actual invocation saved for Step {sid}'
    folder = project / 'steps' / entry['folder']
    return folder, json.loads((folder / 'outputs.json').read_text())


def prior(folder, relative):
    outputs = json.loads((folder / 'before/outputs.json').read_text())['outputs']
    item = next(r for r in outputs if r['rel'] == relative)
    return (folder / 'before' / item['snapshot']).read_bytes()


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


def test_actual_full_stack_call_preserves_previous_failed_record(tmp_path, monkeypatch):
    import full_stack_functional_tb as functional
    relative = 'phase2/stage1/sim_full_stack/results.json'
    path = write(tmp_path, relative, b'previous full-stack evidence')
    def generate(project, container):
        path.write_text('{"verdict":"NOT_MEASURED","reason":"no execution"}')
        return {'verdict': 'NOT_MEASURED', 'reason': 'no execution', 'counts': {}}
    monkeypatch.setattr(functional, 'generate', generate)
    result = design.step_full_stack_functional_tb(tmp_path, None)
    folder, record = saved(tmp_path, '5')
    assert result.status == record['status'] == 'NOT_MEASURED'
    assert prior(folder, relative) == b'previous full-stack evidence'
    assert (folder / 'files' / relative).read_bytes() == path.read_bytes()
    assert versions.latest_pass(tmp_path, '5') is None


def manifest_plan(project):
    import hashlib
    write(project, 'phase2/stage1/rtl/top.v', b'module top(input a, output b); assign b=a; endmodule\n')
    write(project, 'phase2/stage1/formal/proof.sby', b'[options]\nmode prove\n')
    write(project, 'phase2/stage1/formal/results.json', b'{"verdict":"PASS"}')
    write(project, 'phase2/stage1/sim_full_stack/results.json', b'{"verdict":"PASS"}')
    sof = write(project, 'phase2/stage1/fpga/output_files/top.sof', b'unit transport fixture')
    write(project, 'phase2/stage1/fpga/output_files/top.map.rpt',
          b'Info: Quartus Prime Full Compilation was successful.\n')
    return [
        design.StepResult('fpga_compile', 'PASS', 0.0, 'fixture compile record'),
        design.StepResult('fpga_burn', 'PASS', 0.0, 'fixture burn record', extras={
            'burn_provenance': {'sof_path': str(sof),
                                'sof_sha256': 'sha256:' + hashlib.sha256(sof.read_bytes()).hexdigest(),
                                'burn_at': '2026-10-12T00:00:00Z'}, 'cable_name': 'fixture'}),
        design.StepResult('usb_hid_tester_verify', 'PASS', 0.0, 'fixture observations',
                          extras={'observed': ['F2'], 'expected': 'F2'}),
    ]


@pytest.mark.parametrize('failed', ['5', '6', '39'])
def test_actual_shared_emitter_records_each_rows_own_consumer(tmp_path, monkeypatch, failed):
    plan = manifest_plan(tmp_path)
    seen = []
    def consume(project, row):
        sid = str(row['id'])
        seen.append(sid)
        status = 'FAIL' if sid == failed else 'PASS'
        return {'status': status, 'step': {'id': sid, 'status': status}, 'ledger': []}
    monkeypatch.setattr(gates, 'evaluate', consume)
    result = design.step_emit_phase2_manifests(tmp_path, plan, 'top')
    assert result.status == 'PASS'  # Emitting reports is not canonical acceptance.
    assert seen == ['5', '6', '39']
    for sid in seen:
        _, record = saved(tmp_path, sid)
        assert record['status'] == ('FAIL' if sid == failed else 'PASS')
        assert record['canonical_pass'] is (sid != failed)
        assert record['result']['step_rows'][0]['step_id'] == sid
        if sid == failed:
            assert versions.latest_pass(tmp_path, sid) is None
        else:
            assert record['result']['canonical_consumer']['outputs']


def test_manifest_no_board_does_not_get_canonical_pass_from_emitter_pass(tmp_path):
    write(tmp_path, 'phase2/stage1/rtl/top.v', b'module top(input a, output b); assign b=a; endmodule\n')
    result = design.step_emit_phase2_manifests(tmp_path, [], 'top')
    assert result.status == 'PASS'
    for sid in ('5', '6', '39'):
        _, record = saved(tmp_path, sid)
        assert record['status'] != 'PASS'
        assert not record['canonical_pass']
        assert versions.latest_pass(tmp_path, sid) is None


def test_shared_independent_result_list_cannot_invent_acceptance(tmp_path, monkeypatch):
    def forbidden(*args):
        raise AssertionError('independent component list is not one complete emitter')
    monkeypatch.setattr(gates, 'evaluate', forbidden)
    @preflight.retained_steps(('5', '6'), canonical_acceptance=True)
    def independent(project):
        return [SimpleNamespace(name='component', status='PASS', detail='', extras={})]
    independent(tmp_path)
    for sid in ('5', '6'):
        _, record = saved(tmp_path, sid)
        assert record['status'] == 'NOT_MEASURED' and not record['canonical_pass']


def test_real_die_finishing_no_gds_keeps_tuple_abi_and_no_pass(tmp_path):
    result = phase3._die_finishing(tmp_path, 'top', object(), tmp_path / 'absent.gds')
    assert result == (False, 'no GDS to seal')
    _, record = saved(tmp_path, '26.5ic')
    assert record['status'] == 'NOT_MEASURED' and not record['canonical_pass']


def test_real_die_finishing_nested_call_does_not_interrupt_parent(tmp_path, monkeypatch):
    def native(project, *_args):
        write(project, 'phase3/stage3/pnr/die_finished.def', b'current DEF')
        write(project, 'reports/phase3/die_finishing.json', b'{"verdict":"FAIL"}')
        return True, 'producer finished, consumer still owns acceptance', 'PASS'
    monkeypatch.setattr(phase3, '_die_finishing_native', native)
    monkeypatch.setattr(gates, 'evaluate', lambda project, row: {
        'status': 'FAIL', 'step': {'id': row['id'], 'status': 'FAIL'}, 'ledger': []})
    @preflight.retained_step('37')
    def parent(project):
        assert phase3._die_finishing(project, 'top', object(), project / 'top.gds')[0]
        write(project, 'reports/parent-finished.log', b'parent completed after child')
        return SimpleNamespace(name='gds', status='PASS', detail='completed', extras={})
    assert parent(tmp_path).status == 'PASS'
    folder, record = saved(tmp_path, '37')
    assert record['status'] == 'PASS' and not record['canonical_pass']
    assert (folder / 'files/reports/parent-finished.log').read_bytes() == b'parent completed after child'
    _, child = saved(tmp_path, '26.5ic')
    assert child['status'] == 'FAIL' and not child['canonical_pass']
    assert not versions._ACTIVE_LOCAL_CALLS


@pytest.mark.parametrize('rc,status', [(1, 'FAIL'), (2, 'NOT_MEASURED')])
def test_actual_die_finishing_keeps_native_failure_or_capability_status(tmp_path, monkeypatch, rc, status):
    import librelane_contract as ll
    gds = write(tmp_path, 'phase3/stage3/pnr/top.gds', b'fixture GDS; native call is stubbed')
    pdk = SimpleNamespace(tech_lef='/pdk/fixture/libs.ref/tech.lef')
    monkeypatch.setattr(ll, 'selected_mode', lambda *args: 'direct')
    monkeypatch.setattr(phase3._pr, 'run_best_effort', lambda *args, **kwargs:
                        SimpleNamespace(returncode=rc, stdout='die_finishing_gen: refused', stderr=''))
    result = phase3._die_finishing(tmp_path, 'top', pdk, gds)
    assert result[0] is False and 'refused' in result[1]
    _, record = saved(tmp_path, '26.5ic')
    assert record['status'] == status
    assert record['result']['step_rows'][0]['status'] == status
    assert not record['canonical_pass']


def test_nested_existing_leaf_calls_both_finish_without_false_recovery(tmp_path):
    @preflight.retained_step('31')
    def child(project):
        return SimpleNamespace(name='drc', status='PASS', detail='', extras={})
    @preflight.retained_step('37')
    def parent(project):
        child(project)
        return SimpleNamespace(name='gds', status='PASS', detail='', extras={})
    assert parent(tmp_path).status == 'PASS'
    assert saved(tmp_path, '31')[1]['status'] == 'PASS'
    assert saved(tmp_path, '37')[1]['status'] == 'PASS'
    assert not versions._ACTIVE_LOCAL_CALLS


def test_exception_unwinds_local_call_stack_and_partial_evidence_is_recovered(tmp_path):
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


def test_stage_analog_call_keeps_previous_report_before_refusal(tmp_path, monkeypatch):
    relative = 'reports/analog/stage_analog_compliance.json'
    report = write(tmp_path, relative, b'previous analog evidence')
    write(tmp_path, 'phase2/stage2/synth/netlist.v', b'module top; endmodule\n')
    def produce(argv, **kwargs):
        assert not report.exists()
        report.write_text('{"overall":"INCOMPLETE"}')
        return SimpleNamespace(returncode=2)
    monkeypatch.setattr(front.subprocess, 'run', produce)
    args = [str(tmp_path), '--stage-id', 'stage_analog', '--strict', '--json', str(report)]
    assert front._run_phase('analog preproduction', PROGRAMS / 'flow_compliance_check.py', args) == 2
    history = list((report.parent/'history').glob('stage_analog_compliance_*'))
    assert len(history) == 1
    assert (history[0]/'before.json').read_bytes() == b'previous analog evidence'
    assert (history[0]/'after.json').read_bytes() == report.read_bytes()
    assert not any(r['id'] == '14' for r in versions._read_index(tmp_path)['steps'])
    assert versions.latest_pass(tmp_path, '14') is None


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


@pytest.mark.parametrize('no_analog', [True, False])
@pytest.mark.parametrize('rc', [0, 1, 2])
def test_scoped_analog_audit_is_not_a_synthesis_invocation(tmp_path, monkeypatch, no_analog, rc):
    write(tmp_path, 'generated_docs/L5_ADI_SPEC.json', json.dumps({'no_analog': no_analog}).encode())
    relative = 'reports/analog/stage_analog_compliance.json'
    report = write(tmp_path, relative, b'previous scoped analog audit')
    consumer_calls = []
    monkeypatch.setattr(gates, 'evaluate', lambda *args: consumer_calls.append(args) or {'status': 'FAIL', 'ledger': [], 'step': {'id': '14', 'status': 'FAIL'}})
    def produce(argv, **kwargs):
        assert not report.exists()
        assert argv[argv.index('--stage-id') + 1] == 'stage_analog'
        report.write_text(json.dumps({'overall': 'PASS' if rc == 0 else 'FAIL', 'scope': 'stage_analog'}))
        return SimpleNamespace(returncode=rc)
    monkeypatch.setattr(front.subprocess, 'run', produce)
    args = [str(tmp_path), '--stage-id', 'stage_analog', '--strict', '--json', str(report)]
    assert front._run_phase('scoped analog audit', PROGRAMS/'flow_compliance_check.py', args) == rc
    assert consumer_calls == []
    assert not any(r['id'] == '14' for r in versions._read_index(tmp_path)['steps'])
    assert not (tmp_path/'phase2/stage2/synth/netlist.v').exists()
    history = list((report.parent/'history').glob('stage_analog_compliance_*'))
    assert len(history) == 1
    assert (history[0]/'before.json').read_bytes() == b'previous scoped analog audit'
    assert (history[0]/'after.json').read_bytes() == report.read_bytes()
