"""Source controls: real semantic producer/owner with a labelled timing double."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import flow109
import librelane_contract as contract
import step_output_collector as versions
import vibe_ic_one_shot_runner as front
import design_one_shot_runner as design


def _prepared(project, monkeypatch, semantic_status='FAIL'):
    from test_step8_post_prelayout import project as semantic_project, put
    from test_flow109_selection import _write_dft_intent, profile
    import fault_scan_chain_insert as scan
    import _delivery_route

    semantic_project(project)
    if semantic_status == 'FAIL':
        deck = project / 'phase2/stage2/constraints/top.asic.sdc'
        deck.write_text(deck.read_text() +
                        'set_false_path -from [get_clocks clk] -to [get_clocks clk]\n')
    _write_dft_intent(project, monkeypatch, scan=False)
    assert _delivery_route.admit(project, 'ic') is None
    binding, problems = scan.load_d09_dft_contract(project)
    assert binding is not None and not problems
    # Only the native timing boundary is a double. The Step8 receipt below is
    # emitted by the real retained semantic producer and its actual checkers.
    inputs = {str(p.relative_to(project)): contract.digest(p) for p in [
        project / 'phase2/stage2/synth/top_synth.v',
        project / 'phase2/stage2/constraints/top.asic.sdc',
        project / 'phase2/stage2/constraints/pvt_matrix.json']}
    attempt = versions.begin_step(project, '10', inputs)
    put(project / 'phase3/stage3/sta/pre_pnr_timing.rpt',
        'SOURCE_CONTROL timing boundary double; not native STA qualification\n')
    put(project / 'reports/phase3/sta/pre_pnr_summary.json',
        {'scope': 'SOURCE_CONTROL timing boundary double'})
    baseline = versions.finish_step(
        project, attempt, verdict='PASS', canonical_pass=True,
        result={'canonical_consumer': {'status': 'PASS'}})
    semantic = design.step_sdc_validation_post_prelayout(project, 'top')
    assert semantic.status == semantic_status, semantic
    receipt = put(project / 'reports/flow109/d26_scan_mode.json', {
        'schema': 'vibeic.flow109.d26-timing-modes.v1', 'step_id': 'D26',
        'position': 38, 'top': 'top', 'aggregate_status': 'PASS',
        'functional_baseline': {'status': 'PASS', 'folder': baseline['folder'],
                                'canonical_pass': True, 'current_inputs': True,
                                'canonical_consumer_status': 'PASS'},
        'post_scan_arms': {}, 'modes_measured': ['functional_baseline'],
        'scan': {'applicability': 'NOT_APPLICABLE', 'status': 'NOT_APPLICABLE',
                 'd09_binding': binding}})
    manifest = put(project / 'manifest.json', {
        'features': profile('Small digital IC without DFT')})
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        monkeypatch.delenv(name, raising=False)
    args = SimpleNamespace(flow='109', flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode='default',
                           entry_step='D26', exit_step='D26', container='')
    assert flow109.prepare_front_door(args, project) is None
    acceptance = {'verdict': semantic_status,
                  'timing_modes_receipt': {
                      'path': str(receipt.relative_to(project)),
                      'sha256': contract.digest(receipt)}}
    return acceptance, Path(semantic.output_files[0]), receipt


@pytest.mark.parametrize('status,rc', [('PASS', 0), ('FAIL', 1)])
def test_d26_terminal_preserves_current_timing_semantic_conjunction(
        tmp_path, monkeypatch, status, rc):
    acceptance, semantic, timing = _prepared(tmp_path, monkeypatch, status)
    protected = {p: p.read_bytes() for root in
                 [tmp_path / 'steps', semantic.parent] for p in root.rglob('*') if p.is_file()}
    native_bytes = timing.read_bytes()
    answer = front._finish_d26_selected_owner(tmp_path, acceptance)
    observed_rc = {'PASS': 0, 'FAIL': 1}.get(answer['verdict'], 2)
    row = json.loads((tmp_path / 'reports/flow109/default_rows/D26.json').read_text())
    assert answer['verdict'] == status, answer
    assert observed_rc == rc
    assert row['default_row_status'] == status
    assert row['completed'] is (status == 'PASS')
    assert row['delivery_accepted'] is False
    assert timing.read_bytes() == native_bytes
    assert json.loads(native_bytes)['aggregate_status'] == 'PASS'
    assert all(p.read_bytes() == data for p, data in protected.items())
    if status == 'FAIL':
        ref = row['sdc_semantic_receipt']
        assert ref['status'] == 'FAIL'
        assert ref['path'] == str(semantic.relative_to(tmp_path))
        assert ref['sha256'] == contract.digest(semantic)


@pytest.mark.parametrize('case', [
    'missing', 'stale_receipt', 'forged_receipt', 'stale_input',
    'foreign', 'missing_version', 'changed_source', 'unbound_failure', 'forged_version',
])
def test_d26_terminal_refuses_unbound_semantic_failure(tmp_path, monkeypatch, case):
    acceptance, semantic, timing = _prepared(
        tmp_path, monkeypatch, 'PASS' if case in ('unbound_failure', 'forged_version') else 'FAIL')
    acceptance['verdict'] = 'FAIL'
    native_bytes = timing.read_bytes()
    if case == 'missing':
        semantic.unlink()
    elif case == 'stale_receipt':
        semantic.write_text(semantic.read_text() + '\n')
    elif case == 'forged_receipt':
        doc = json.loads(semantic.read_text())
        doc['exception_correlation'] = {'verdict': 'FAIL', 'findings': []}
        semantic.write_text(json.dumps(doc))
    elif case == 'stale_input':
        deck = tmp_path / 'phase2/stage2/constraints/top.asic.sdc'
        deck.write_text(deck.read_text() + '\n')
    elif case == 'foreign':
        other = tmp_path.parent / (tmp_path.name + '-foreign.json')
        other.write_bytes(semantic.read_bytes())
        semantic.unlink()
        semantic.symlink_to(other)
    elif case == 'missing_version':
        selected = next(r for r in versions._read_index(tmp_path)['steps'] if r['id'] == '8')
        (versions._versions_root(tmp_path) / selected['folder'] / 'outputs.json').unlink()
    elif case == 'changed_source':
        monkeypatch.setattr(front, 'PROGRAMS_DIR', tmp_path / 'unavailable-source')
    elif case == 'forged_version':
        index = versions._read_index(tmp_path)
        selected = next(r for r in index['steps'] if r['id'] == '8')
        selected['status'] = 'FAIL'
        (versions._versions_root(tmp_path) / 'index.json').write_text(json.dumps(index))
        path = versions._versions_root(tmp_path) / selected['folder'] / 'outputs.json'
        doc = json.loads(path.read_text())
        doc['status'] = 'FAIL'
        doc['result']['canonical_consumer'] = {
            'status': 'FAIL', 'ledger': [{'verdict': 'FAIL'}]}
        path.write_text(json.dumps(doc))
    answer = front._finish_d26_selected_owner(tmp_path, acceptance)
    row = json.loads((tmp_path / 'reports/flow109/default_rows/D26.json').read_text())
    assert answer['verdict'] == row['default_row_status'] == 'NOT_MEASURED', answer
    assert row['completed'] is False and row['delivery_accepted'] is False
    assert timing.read_bytes() == native_bytes
