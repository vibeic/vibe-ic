"""Bounded independent SOFTWARE reproduction; no native STA invocation."""
import json
from pathlib import Path
import pytest
import flow_compliance_check as fcc
import execution_backend_gates as gates
import librelane_signoff as signoff
import librelane_contract as contract
from test_flow109_scan_timing_modes import software, acquire, put, ref


@pytest.mark.parametrize('foreign', [False, True])
def test_normal_consumer_binds_scan_execution_image(software, monkeypatch, foreign):
    p, paths, state, native, failures = software
    ctx, coverage = acquire(software)
    assert coverage['status'] == 'PASS', coverage
    for mode in ('shift', 'capture'):
        record = coverage['modes'][mode][0]
        folder = (p / record['sta_state']['path']).parent
        receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
        fingerprint = receipt['input']
        fingerprint['image'] = ('unqualified-foreign@sha256:' + 'f' * 64
                                if foreign and mode == 'capture' else native['image'])
        put(folder / 'input_fingerprint.json', fingerprint)
        receipt['sha256']['input_fingerprint.json'] = contract.digest(folder / 'input_fingerprint.json')
        put(folder / 'vibeic_receipt.json', receipt)
        record['native_receipt'] = ref(p, folder / 'vibeic_receipt.json')
    put(p / signoff.SIGNOFF_RECORD, {'sta_state': str(put(p / 'functional-state.json', state)),
                                   'scan_timing_coverage': coverage})
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(put(p / 'context.json', ctx)))
    # Same explicit SOFTWARE functional upstream boundary as A's original control.
    monkeypatch.setattr(fcc, 'check_step', lambda *_a, **_k: fcc.StepResult(23, 'SOFTWARE upstream', 'phase3', 'PASS'))
    observed = gates.evaluate(p, gates.canonical_family_row('23'))
    put(p / 'B_OBSERVATION.json', {'SOFTWARE_ONLY': True, 'foreign': foreign,
        'expected': 'NOT_MEASURED' if foreign else 'PASS', 'actual': observed['status'],
        'capture_original_image': 'unqualified-foreign@sha256:' + 'f' * 64 if foreign else native['image'],
        'normal_consumer': observed})
    assert observed['status'] == ('NOT_MEASURED' if foreign else 'PASS'), observed


@pytest.mark.parametrize('damage,shift_failure,capture_failure,expected', [
    ('foreign-image', True, False, 'FAIL'),
    ('foreign-image', False, True, 'NOT_MEASURED'),
    ('foreign-launch', False, False, 'NOT_MEASURED'),
    ('missing-launch', False, False, 'NOT_MEASURED'),
    ('missing-image', False, False, 'NOT_MEASURED'),
    ('missing-source', False, False, 'NOT_MEASURED'),
    ('forged-source', False, False, 'NOT_MEASURED'),
    ('unqualified-original-runtime', False, False, 'NOT_MEASURED'),
])
def test_original_scan_origin_refusal_preserves_only_qualified_fail(
        software, monkeypatch, damage, shift_failure, capture_failure, expected):
    import copy
    p, paths, state, native, failures = software
    if shift_failure:
        failures['shift'] = 'hold_ws'
    if capture_failure:
        failures['capture'] = 'hold_ws'
    ctx, coverage = acquire(software)
    record = coverage['modes']['capture'][0]
    folder = (p / record['sta_state']['path']).parent
    receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
    fingerprint = receipt['input']
    if damage == 'foreign-image':
        fingerprint['image'] = 'unqualified-foreign@sha256:' + 'f' * 64
    if damage == 'foreign-launch':
        fingerprint['local_image']['cid'] = 'f' * 64
    if damage == 'missing-launch':
        fingerprint.pop('local_image')
    if damage == 'missing-image':
        fingerprint.pop('image')
    if damage == 'missing-source':
        record.pop('source_root')
    if damage == 'forged-source':
        record['operation_sources']['librelane_signoff.py:run'] = 'a' * 64
    if damage == 'unqualified-original-runtime':
        record['execution_context'] = copy.deepcopy(ctx)
        uses = copy.deepcopy(ctx['runtime_tool_uses'])
        uses[0]['version'] = 'FOREIGN_UNQUALIFIED_RUNTIME'
        record['execution_context'] = __import__('flow109').execution_context(
            __import__('flow109').resolve_plan(ctx['features']), 'D49', 'D49',
            runtime_tool_uses=uses, qualification_registry=ctx['qualification_registry'])
    put(folder / 'input_fingerprint.json', fingerprint)
    receipt['sha256']['input_fingerprint.json'] = contract.digest(folder / 'input_fingerprint.json')
    put(folder / 'vibeic_receipt.json', receipt)
    record['native_receipt'] = ref(p, folder / 'vibeic_receipt.json')
    put(p / signoff.SIGNOFF_RECORD, {'sta_state': str(put(p / 'functional-state.json', state)),
                                   'scan_timing_coverage': coverage})
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(put(p / 'context.json', ctx)))
    monkeypatch.setattr(fcc, 'check_step', lambda *_a, **_k: fcc.StepResult(23, 'SOFTWARE upstream', 'phase3', 'PASS'))
    observed = gates.evaluate(p, gates.canonical_family_row('23'))
    put(p / 'ORIGIN_OBSERVATION.json', {'scope': 'SOFTWARE_ONLY', 'damage': damage,
        'expected': expected, 'normal_consumer': observed})
    assert observed['status'] == expected, observed
    assert observed['scan_timing_coverage']['status'] == expected
