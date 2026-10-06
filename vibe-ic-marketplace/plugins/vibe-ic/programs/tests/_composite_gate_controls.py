"""Bounded refusal controls reusing the original real native Step16 run."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

import execution_modes as em
from execution_source_snapshot import SourceSnapshot, using


def assert_current_composite_refusals(controller, context, root, arm_id):
    arm = next(a for a in controller.registry.adapters(context.step_id) if a.arm_id == arm_id)
    baseline = json.loads((root / arm_id / 'receipt.json').read_text())
    out = root / 'composite-controls'
    out.mkdir()
    (out / 'native-eligible-receipt.json').write_text(json.dumps(baseline, indent=2) + '\n')
    report_path = Path(baseline['output_root']) / 'release-evidence.json'
    report_bytes = report_path.read_bytes()
    (out / 'native-release-evidence.json').write_bytes(report_bytes)
    gate = context.required_gates[0]
    results = {}

    def refuse(name, candidate, expected='GATE_EXECUTION_UNBOUND'):
        try:
            controller._eligible(candidate, context, arm)
        except em.Refusal as exc:
            results[name] = exc.code
            assert exc.code == expected, (name, exc.code)
        else:
            raise AssertionError(name + ' became eligible')

    # One transaction caches source parsing only; finalize freshly checks all
    # consumed source bytes. No Popen, validator or authority check is mocked.
    snapshot = SourceSnapshot(em._REPO_ROOT, arm.source_sha)
    with using(snapshot):
        controller._eligible(baseline, context, arm)
        for name, edit in (
            ('missing_projection', lambda r: r['evidence'].update(provenance={})),
            ('caller_nested_labels', lambda r: r['evidence'].update(provenance={
                'nested_gate_records': [{'gate': gate, 'command': r['processes'][0]['argv'],
                                         'rc': 0, 'verdict': 'PASS', 'worker_component': 'release-producer'}]})),
            ('wrong_observed_worker', lambda r: r['processes'][0].update(component='other-worker')),
            ('worker_argv', lambda r: r['processes'][0]['argv'].__setitem__(1, '/tmp/other-worker.py')),
            ('gate_argv', lambda r: r['gate_receipts'][gate]['argv'].append('--forged')),
            ('gate_source', lambda r: r['evidence']['provenance']['composite_gate_execution'].update(
                gate_sources={'/tmp/forged.py': '0' * 64})),
            ('typed_receipt_digest', lambda r: r['gate_receipts'][gate].update(typed_receipt_sha256='0' * 64)),
            ('output_digest', lambda r: r['gate_receipts'][gate].update(output_digest='0' * 64)),
            ('required_gate_census', lambda r: r['evidence']['gates'].update(forged_gate='PASS')),
        ):
            candidate = deepcopy(baseline)
            edit(candidate)
            refuse(name, candidate)
        candidate = deepcopy(baseline)
        candidate['binding']['source_sha'] = '0' * 40
        refuse('stale_binding', candidate, 'STALE_OR_UNBOUND_RECEIPT')
        candidate = deepcopy(baseline)
        candidate['evidence']['verdict'] = 'FAIL'
        candidate['evidence']['provenance'] = {}
        refuse('measured_fail_precedence', candidate, 'GATE_FAIL')
        candidate = deepcopy(baseline)
        candidate['processes'][0]['pid'] += 1
        try:
            controller._execution_authority(root, json.loads((root / 'plan.json').read_text()), candidate, arm)
        except em.Refusal as exc:
            results['issued_completion_mutation'] = exc.code
            assert exc.code == 'EXECUTION_AUTHORITY_MISMATCH'
        else:
            raise AssertionError('issued completion mutation became authoritative')
        try:
            report = json.loads(report_bytes)
            report['gate_records'][0]['argv'].append('--forged')
            report_path.write_text(json.dumps(report))
            candidate = deepcopy(baseline)
            candidate['evidence'] = asdict(arm.validate(Path(baseline['output_root']), baseline['binding']))
            assert not candidate['evidence']['provenance']
            refuse('cohashed_forged_current_gate_call', candidate)
            report_path.unlink()
            refuse('missing_current_typed_receipt', deepcopy(baseline))
        finally:
            report_path.write_bytes(report_bytes)
        snapshot.finalize()
    assert report_path.read_bytes() == report_bytes
    (out / 'refusals.json').write_text(json.dumps(results, indent=2) + '\n')
