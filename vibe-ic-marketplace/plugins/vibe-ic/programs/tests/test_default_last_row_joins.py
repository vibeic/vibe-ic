"""Observe the remaining actual Default completion calls without native IC claims."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROGRAMS = Path(os.environ.get('VIBEIC_LAST_JOIN_PROGRAMS',
                              str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import design_one_shot_runner as design
import execution_backend_gates as gates
import execution_policy as policy
import phase3_one_shot_runner as phase3
import step_output_collector as versions


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    request = {**policy.request(), 'mode': 'default'}
    monkeypatch.setattr(policy, 'request', lambda: request)
    monkeypatch.setattr(policy, '_ordinary_runtime', None)


def write(project, rel, data=b'current evidence'):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def saved(project, sid):
    entry = next((r for r in versions._read_index(project)['steps'] if r['id'] == sid), None)
    assert entry is not None, f'no actual completion history for Step {sid}'
    folder = project / 'steps' / entry['folder']
    return folder, json.loads((folder / 'outputs.json').read_text())


def before(folder, rel):
    rows = json.loads((folder / 'before/outputs.json').read_text())['outputs']
    row = next(r for r in rows if r['rel'] == rel)
    return (folder / 'before' / row['snapshot']).read_bytes()


def reject(monkeypatch):
    seen = []
    def consume(project, row):
        seen.append(str(row['id']))
        return {'status': 'FAIL', 'step': {'id': row['id'], 'status': 'FAIL'}, 'ledger': []}
    monkeypatch.setattr(gates, 'evaluate', consume)
    return seen


def test_final_manifest_consumes_2_3_4_after_their_actual_reports(tmp_path, monkeypatch):
    seen = reject(monkeypatch)
    write(tmp_path, 'phase2/stage1/rtl/top.v', b'module top(input clk); endmodule')
    write(tmp_path, design._SYNTH_LOG_REL, b'current synthesis transcript')
    plan = [design.StepResult('yosys_synth', 'PASS', 0.0, 'current synthesis')]
    result = design._complete_phase2_frontend(tmp_path, plan, 'top')
    assert result.status == 'PASS'
    assert seen == ['5', '6', '39', '2', '3', '4']
    for sid in ('2', '3', '4'):
        folder, record = saved(tmp_path, sid)
        assert record['status'] == 'FAIL' and not record['canonical_pass']
        assert versions.latest_pass(tmp_path, sid) is None
    assert (tmp_path / 'reports/phase2/lint/rtl_hygiene.json').is_file()
    assert (tmp_path / 'reports/phase2/cdc/crossing.json').is_file()


def test_step2_supplementary_writer_runs_before_complete_consumer(tmp_path, monkeypatch):
    import flow_declared_producer_run as declared
    written = []
    def produce(project, sid, **kwargs):
        assert sid == '2'
        assert (project / 'reports/phase2/cdc/crossing.json').is_file()
        write(project, 'reports/phase2/lint/rom_init_lint.json', b'{"findings":[]}')
        written.append(sid)
        return {'verdict': 'PRODUCED'}
    def consume(project, row):
        if str(row['id']) in ('2', '3', '4'):
            assert written == ['2']
            assert (project / 'reports/phase2/lint/rom_init_lint.json').is_file()
        return {'status': 'FAIL', 'step': {'id': row['id'], 'status': 'FAIL'}, 'ledger': []}
    monkeypatch.setattr(declared, 'run_for_step', produce)
    monkeypatch.setattr(gates, 'evaluate', consume)
    write(tmp_path, 'phase2/stage1/rtl/top.v', b'module top(input clk); endmodule')
    assert design._complete_phase2_frontend(tmp_path, [], 'top').status == 'PASS'
    assert written == ['2']


def test_actual_lightweight_dft_keeps_conditional_status_without_native_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(design._pr, 'run', lambda *a, **k: pytest.fail('ATPG cannot run here'))
    result = design._step_dft_insertion(tmp_path, 'top', 'unused', 'clk', '', False, False)
    assert result.status == 'NOT_APPLICABLE'
    assert result.rows[0].name == 'dft_insertion'
    record = saved(tmp_path, '11')[1]
    assert record['status'] == 'NOT_APPLICABLE' and not record['canonical_pass']


@pytest.mark.parametrize('fresh', [True, False])
def test_actual_post_dft_cannot_borrow_old_netlist(tmp_path, monkeypatch, fresh):
    seen = reject(monkeypatch)
    write(tmp_path, 'phase2/stage2/dft/scan_netlist.v', b'module top(input clk); endmodule')
    rel = 'phase2/stage2/synth/post_dft_netlist.v'
    output = write(tmp_path, rel, b'previous post-DFT netlist')
    def native(*args, **kwargs):
        assert not output.exists()
        if fresh:
            output.write_text('module top(input clk); endmodule')
        return 0, 'current opt_clean', ''
    monkeypatch.setattr(design, '_docker_exec', native)
    result = design._step_post_dft_optimization(tmp_path, 'unused')
    assert result.status == ('PASS' if fresh else 'NOT_MEASURED')
    assert seen == (['12'] if fresh else [])
    folder, record = saved(tmp_path, '12')
    assert record['status'] == ('FAIL' if fresh else 'NOT_MEASURED')
    assert before(folder, rel) == b'previous post-DFT netlist'
    assert not record['canonical_pass']


@pytest.mark.parametrize('native_status', ['PASS', 'FAIL'])
def test_actual_lec_list_acceptance_belongs_only_to_current_lec(tmp_path, monkeypatch, native_status):
    seen = reject(monkeypatch)
    write(tmp_path, 'phase2/stage1/rtl/top.v', b'module top(input clk); endmodule')
    nl = write(tmp_path, 'phase2/stage2/synth/top_synth.v', b'module top(input clk); endmodule')
    monkeypatch.setattr(design._lec_gns, 'lec_subject_for_step13',
                        lambda *a: (str(nl.relative_to(tmp_path)), 'current subject', False))
    monkeypatch.setattr(design, '_lec_eqy_arm', lambda project, top, subject, rows: rows)
    def native(*args, **kwargs):
        write(tmp_path, 'reports/lec.json', json.dumps({'verdict': native_status}).encode())
        write(tmp_path, 'reports/lec.rpt', native_status.encode())
        return SimpleNamespace(returncode=0 if native_status == 'PASS' else 1, stdout='', stderr='')
    monkeypatch.setattr(design.subprocess, 'run', native)
    prefix = design.StepResult('dft_insertion', 'FAIL' if native_status == 'PASS' else 'PASS', 0.0, 'previous step')
    rows = design.step_lec_equivalence(tmp_path, 'top', 'unused', [prefix])
    assert rows[0] is prefix
    assert rows[-1].status == native_status, rows[-1].detail
    assert seen == (['13'] if native_status == 'PASS' else [])
    record = saved(tmp_path, '13')[1]
    assert record['status'] == 'FAIL' and not record['canonical_pass']
    assert [r['name'] for r in record['result']['step_rows']] == ['lec_equivalence']


def test_actual_step32_publish_preserves_both_prior_decision_files(tmp_path, monkeypatch):
    seen = reject(monkeypatch)
    out = tmp_path / 'phase3/stage3/postroute_timing_repair'
    rels = [str((out / name).relative_to(tmp_path)) for name in (
        'postroute_timing_repair_decision.json', 'postroute_timing_repair_decision.canonical.json')]
    for rel in rels:
        write(tmp_path, rel, b'previous decision')
    monkeypatch.setattr(phase3, '_step32_decision_record', lambda *a: {'action': 'current decision'})
    written, notes = [], []
    rc = phase3._publish_step32_decision(tmp_path, {}, tmp_path / 'stance',
                                        tmp_path / 'sta', out, None, written, notes)
    assert rc == 0 and not notes and seen == ['32']
    folder, record = saved(tmp_path, '32')
    assert record['status'] == 'FAIL' and not record['canonical_pass']
    for rel in rels:
        assert before(folder, rel) == b'previous decision'
        assert json.loads((tmp_path / rel).read_text())['action'] == 'current decision'


@pytest.mark.parametrize('drc_status', ['PASS', 'FAIL'])
def test_complete_physical_result_cannot_hide_native_drc_failure(tmp_path, monkeypatch, drc_status):
    seen = reject(monkeypatch)
    rows = [phase3.StepResult('drc', drc_status, 0.0, 'current DRC'),
            phase3.StepResult('lvs', 'PASS', 0.0, 'current LVS')]
    result = phase3._complete_physical_verification(tmp_path, rows)
    assert result.status == drc_status
    assert seen == (['31'] if drc_status == 'PASS' else [])
    record = saved(tmp_path, '31')[1]
    assert record['status'] == 'FAIL' and not record['canonical_pass']


@pytest.mark.parametrize('scope', ['ELIGIBLE_FOR_AUDIT', 'NOT_ELIGIBLE_FOR_RELEASE'])
@pytest.mark.parametrize('audit_rc', [0, 1, 2])
def test_actual_final_receipt_writes_stage3_audit_before_complete_consumer(tmp_path, monkeypatch, scope, audit_rc):
    seen = reject(monkeypatch)
    rel = 'reports/phase3/gates/stage3_compliance.json'
    report = write(tmp_path, rel, b'previous stage3 audit')
    rows = [phase3.StepResult(name, 'PASS', 0.0, 'current native result')
            for name in ('drc', 'lvs', 'gds')]
    def audit(argv, **kwargs):
        assert not report.exists()
        assert Path(argv[1]).name == 'stage3_compliance.py'
        assert (tmp_path / 'reports/phase3/layout_receipts.json').is_file()
        report.write_text('{"verdict":"PASS"}')
        return SimpleNamespace(returncode=audit_rc, stdout='', stderr='')
    monkeypatch.setattr(phase3._pr, 'run', audit if scope == 'ELIGIBLE_FOR_AUDIT'
                        else lambda *a, **k: pytest.fail('cannot audit a non-release layout'))
    rc = phase3._publish_final_layout_receipts(tmp_path, {'release_verdict': scope}, rows)
    assert rc == (0 if scope == 'ELIGIBLE_FOR_AUDIT' and audit_rc in (0, 1) else 2)
    assert seen == (['31', '37'] if rc == 0 else ['31'])
    folder, record = saved(tmp_path, '37')
    assert record['status'] == ('FAIL' if rc == 0 else 'NOT_MEASURED')
    assert not record['canonical_pass']
    assert before(folder, rel) == b'previous stage3 audit'
    if scope == 'ELIGIBLE_FOR_AUDIT':
        assert (folder / 'files' / rel).read_bytes() == report.read_bytes()
    else:
        assert report.read_bytes() == b'previous stage3 audit'


def test_ultra_receipt_writer_keeps_existing_order_without_default_audits(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'ultra'})
    monkeypatch.setattr(phase3._pr, 'run', lambda *a, **k: pytest.fail('new Default audit leaked to Ultra'))
    assert phase3._publish_final_layout_receipts(tmp_path, {}, []) == 0
    assert (tmp_path / 'reports/phase3/layout_receipts.json').is_file()
    assert not (tmp_path / 'steps/index.json').exists()


def test_missing_physical_result_is_disclosed_without_crashing(tmp_path, monkeypatch):
    seen = reject(monkeypatch)
    result = phase3._complete_physical_verification(tmp_path, [])
    assert result.status == 'NOT_MEASURED' and result.reason_class == 'input_absent'
    assert seen == []
    assert saved(tmp_path, '31')[1]['status'] == 'NOT_MEASURED'
