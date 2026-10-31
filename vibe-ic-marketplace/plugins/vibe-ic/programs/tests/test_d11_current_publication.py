"""Actual engineering owner publication at the ordinary invocation/collector boundary."""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest
import benchmark_dispatch as dispatch
import flow_phase_attribution as attribution
from _hostpaths import require_repo


@pytest.fixture(scope='module')
def measured(tmp_path_factory):
    if shutil.which('verilator') is None:
        pytest.skip('native publication control requires the actual Verilator toolchain')
    root = tmp_path_factory.mktemp('current-owner')
    project = root / 'subject'
    (project / 'input').mkdir(parents=True)
    (project / 'input/phase1_prompt.md').write_text(
        'Implement a combinational buffer module neutral with input a and output y.')
    rtl = project / 'phase2/stage1/rtl/neutral.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module neutral(input a, output y); assign y=a; endmodule\n')
    registry = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'flow', 'flow109.json')
    features = next(p['features'] for p in json.loads(registry.read_text())['reference_profiles']
                    if p['name'] == 'RTL-only')
    manifest = project / 'input/flow109-manifest.json'
    manifest.write_text(json.dumps({'features': features}))
    (project / 'phase3').mkdir()
    (project / 'phase3/librelane_switch.json').write_text('{"steps":{"2":"direct"}}')
    current = project / 'reports/orchestrator/phase2_one_shot.json'
    current.parent.mkdir(parents=True)
    prior = {'project': str(project), 'verdict': 'NOT_MEASURED',
             'steps': [{'name': 'rtl_gen', 'status': 'NOT_MEASURED', 'detail': 'previous author handoff'}]}
    current.write_text(json.dumps(prior))
    programs = Path(dispatch.__file__).resolve().parent
    argv = [sys.executable, str(programs / 'vibe_ic_one_shot_runner.py'), str(project),
            '--route', 'ip', '--skip-analog', '--skip-hardware', '--skip-phase3',
            '--no-dashboard', '--rtl-input', 'original', '--flow', '109',
            '--flow109-manifest', str(manifest), '--entry-step', 'D11', '--exit-step', 'D11']
    process = dispatch._RunnerBudget(1, 1, 1).run(argv)
    assert process.rc == 0 and process.error is None, (process.stdout, process.stderr)
    return project, current, prior, argv, process


def test_actual_owner_replaces_old_author_report_at_all_consumers(measured):
    project, current, _, argv, process = measured
    got = dispatch._collect_runner_result(process, argv, 'verilogeval', 'neutral', project,
                                          supplied_rtl=True)
    # Pre-fix observes RUNNER_REPORT_NOT_FRESH, despite the native owner RC 0.
    actual = got.get('rtl_gen', got.get('runner_diagnostics', {}).get('reason_class'))
    assert actual == 'NOT_APPLICABLE', got
    assert got['ok'] is True
    parent = json.loads(current.read_text())
    ref = parent['runner_binding']['owner_report']
    child = project / ref['path']
    owned = json.loads(child.read_text())
    assert hashlib.sha256(child.read_bytes()).hexdigest() == ref['sha256']
    assert owned['runner_binding']['invocation_id'] != process.invocation_id
    assert owned['runner_binding']['parent_invocation']['invocation_id'] == process.invocation_id
    assert parent['runner_binding']['invocation_id'] == process.invocation_id
    phases = attribution.phase3_verifying(parent, None)
    ledger = dispatch._required_gate_ledger({'exit': '2', 'phases': {'phase3_verifying': phases}})
    assert ledger['eligibility'] == 'ELIGIBLE', ledger


@pytest.mark.parametrize('damage', ['stale_current', 'missing_child', 'child_hash',
                                  'parent_generation', 'child_payload', 'child_source', 'input'])
def test_real_owner_chain_rejects_stale_or_grafted_reports(measured, damage):
    project, current, prior, argv, process = measured
    parent = json.loads(current.read_text())
    child = project / parent['runner_binding']['owner_report']['path']
    prompt = project / 'input/phase1_prompt.md'
    receipt_path = Path(process.receipt_path)
    originals = {p: p.read_bytes() for p in (current, child, prompt, receipt_path)}
    try:
        candidate = process
        if damage == 'stale_current': current.write_text(json.dumps(prior))
        elif damage == 'missing_child': child.unlink()
        elif damage == 'input': prompt.write_text('A new unadmitted requirement.')
        else:
            owned = json.loads(child.read_text())
            if damage == 'parent_generation':
                owned['runner_binding']['parent_invocation']['invocation_id'] = 'foreign-parent'
            elif damage == 'child_payload': owned['verdict'] = 'FAIL'
            elif damage == 'child_source': owned['runner_binding']['source']['runner']['sha256'] = '0' * 64
            else: owned['runner_binding']['invocation_id'] = 'changed-child'
            child.write_text(json.dumps(owned))
            if damage != 'child_hash':
                # Rebind ordinary hashes so the parent/child semantic checks
                # must reject the graft, independently of a checksum mismatch.
                parent['runner_binding']['owner_report']['sha256'] = hashlib.sha256(child.read_bytes()).hexdigest()
                current.write_text(json.dumps(parent))
                receipt = copy.deepcopy(process.invocation)
                receipt['reports_after'] = dispatch._runner_report_snapshot(project)
                receipt_path.write_text(json.dumps(receipt))
                candidate = replace(process, invocation=receipt,
                    receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest())
        got = dispatch._collect_runner_result(candidate, argv, 'verilogeval', 'neutral', project,
                                              supplied_rtl=True)
        assert got['ok'] is False, (damage, got)
        assert got['runner_diagnostics'].get('reason'), (damage, got)
    finally:
        for path, raw in originals.items(): path.write_bytes(raw)
