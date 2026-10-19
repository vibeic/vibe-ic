"""Physical verification check lists do not request new analog blocks."""
from pathlib import Path
import json
import os
import subprocess
import sys

import pytest

PROGRAMS = Path(os.environ.get('L5_INTENT_TEST_PROGRAMS',
    str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as D

OBLIGATION = ('Pad-only native component geometry contained no DUT routing or '
    'electrical proof. Full-stream annulus verification remained NOT_MEASURED '
    'after a bounded timeout; PDK DRC/LVS/ERC, power connectivity, IR/EM/ESD '
    'capacity, timing and release acceptance remain unmeasured obligations.')
CLAMP = 'The chip integrates an on-chip ESD clamp diode operating at 1.8 V.'
LDO = 'The chip integrates an LDO regulator with 1.8 V output.'


@pytest.mark.parametrize('name,paragraph,expected', [
    ('unmeasured-physical-obligations', OBLIGATION, set()),
    ('physical-check-list', 'Physical signoff must check DRC/LVS/ERC/IR/EM/ESD.', set()),
    ('reordered-check-list', 'Verification of ESD/IR/EM remains pending.', set()),
    ('real-clamp', CLAMP, {'esd'}),
    ('real-esd-protection', 'The chip provides on-chip ESD protection at 1.8 V.', {'esd'}),
    ('real-esd-network', 'The chip integrates an ESD network at 1.8 V.', {'esd'}),
    ('check-list-before-real-clamp', OBLIGATION + ' ' + CLAMP, {'esd'}),
    ('real-clamp-before-check-list', CLAMP + ' ' + OBLIGATION, {'esd'}),
    ('ldo-and-check-list', LDO + '\n\n' + OBLIGATION, {'ldo'}),
    ('ldo-and-clamp', LDO + '\n\n' + CLAMP, {'ldo', 'esd'}),
    ('shared-protection-tail-first', 'Verify the ESD/IR/EM protection network at 1.8 V.', {'esd'}),
    ('shared-protection-tail-last', 'Verify the IR/EM/ESD protection network at 1.8 V.', {'esd'}),
    ('integrated-shared-tail', 'An on-chip ESD/IR/EM protection network must undergo verification at 1.8 V.', {'esd'}),
    ('mixed-shared-tail', LDO + '\n\nAn on-chip ESD/IR/EM protection network must undergo verification at 1.8 V.', {'ldo', 'esd'}),
    ('decimal-before-checklist', 'Physical verification at 1.8 V covers DRC/LVS/ERC/IR/EM/ESD.', set()),
    ('soft-wrapped-checklist', 'Physical verification must check DRC/LVS/ERC/IR/\nEM/ESD.', set()),
    ('adjective-shared-network', 'An on-chip ESD/IR/EM bidirectional protection network must undergo verification at 1.8 V.', {'esd'}),
    ('prefix-shared-network', 'The on-chip protection network for ESD/IR/EM must undergo verification at 1.8 V.', {'esd'}),
])
def test_native_l5_and_ordinary_parity_read_the_same_block_intent(
        tmp_path, name, paragraph, expected):
    source = '# Implementation\nThe core supply is 1.8 V.\n\n' + paragraph + '\n'
    docs = tmp_path / 'input/docs'
    docs.mkdir(parents=True)
    (docs/'implementation.md').write_text(source)
    emitted = D.gen_l5_adi_spec(tmp_path, {'implementation.md': source})
    l5 = json.loads(emitted.path.read_text())
    actual = {b['type'] for b in l5['analog_blocks']}
    assert actual == expected, {'actual_types': sorted(actual),
                                'expected_types': sorted(expected)}
    before = emitted.path.read_bytes()
    argv = [sys.executable, str(PROGRAMS/'analog_content_detected_must_emit_l5_check.py'),
            str(tmp_path)]
    done = subprocess.run(argv, capture_output=True, text=True)
    (tmp_path/'parity.stdout').write_text(done.stdout)
    (tmp_path/'parity.stderr').write_text(done.stderr)
    (tmp_path/'EXECUTION.json').write_text(json.dumps({'argv':argv,'rc':done.returncode}))
    # The ordinary consumer's existing no-keyword VACUOUS_PASS is rc 2.
    # It never counts as an executed analog correspondence PASS.
    assert done.returncode == (0 if expected else 2), done.stdout + done.stderr
    assert emitted.path.read_bytes() == before


def test_missing_real_esd_block_remains_an_ordinary_consumer_failure(tmp_path):
    docs = tmp_path/'input/docs'
    docs.mkdir(parents=True)
    (docs/'implementation.md').write_text(CLAMP)
    emitted = D.gen_l5_adi_spec(tmp_path, {'implementation.md': CLAMP})
    l5 = json.loads(emitted.path.read_text())
    assert {b['type'] for b in l5['analog_blocks']} == {'esd'}
    # Negative control in an isolated neutral fixture, never benchmark credit.
    l5['analog_blocks'] = []
    emitted.path.write_text(json.dumps(l5))
    done = subprocess.run([sys.executable,
        str(PROGRAMS/'analog_content_detected_must_emit_l5_check.py'), str(tmp_path)],
        capture_output=True, text=True)
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'esd' in done.stdout.lower()


def test_missing_shared_tail_esd_is_not_hidden_by_present_ldo(tmp_path):
    source = LDO + '\n\nAn on-chip ESD/IR/EM protection network must undergo verification at 1.8 V.'
    docs = tmp_path/'input/docs'
    docs.mkdir(parents=True)
    (docs/'implementation.md').write_text(source)
    emitted = D.gen_l5_adi_spec(tmp_path, {'implementation.md': source})
    payload = json.loads(emitted.path.read_text())
    assert {b['type'] for b in payload['analog_blocks']} == {'ldo', 'esd'}
    payload['analog_blocks'] = [b for b in payload['analog_blocks'] if b['type'] != 'esd']
    emitted.path.write_text(json.dumps(payload))
    done = subprocess.run([sys.executable,
        str(PROGRAMS/'analog_content_detected_must_emit_l5_check.py'), str(tmp_path)],
        capture_output=True, text=True)
    assert done.returncode == 1, done.stdout + done.stderr
