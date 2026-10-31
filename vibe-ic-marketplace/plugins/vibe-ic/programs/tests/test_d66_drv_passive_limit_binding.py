"""Passive supply roles require independently reconstructed census proof."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import drv_signoff_judge as judge


def example():
    meta = {'kind': 'pin', 'cell_class': 'physical', 'net_class': 'data',
            'cell': 'filler', 'cell_pin': 'VDD', 'driver_pin': None, 'net': 'VDD'}
    return meta, {'pin': 'fill/VDD', 'limit': 1.0, 'measured': 0.0, 'slack': 1.0}


def test_independently_proven_passive_pin_owes_no_timing_model():
    meta, row = example()
    missing = []
    result = judge._annotate_limits(row, 'max_slew',
        {'name': 'scene', 'linked_liberties': [], '_physical_pin_proofs': {'fill/VDD': meta}},
        {}, {'fill/VDD': meta}, {}, missing)
    assert result is False
    assert missing == []


@pytest.mark.parametrize('mutation', ['no_proof', 'different_proof', 'logic', 'clock', 'driver'])
def test_missing_timing_model_still_refuses_without_passive_proof(mutation):
    meta, row = example()
    proof = dict(meta)
    if mutation == 'no_proof':
        proof = None
    elif mutation == 'different_proof':
        proof['net'] = 'different'
    elif mutation == 'logic':
        meta['cell_class'] = proof['cell_class'] = 'std'
    elif mutation == 'clock':
        meta['net_class'] = proof['net_class'] = 'clock'
    elif mutation == 'driver':
        meta['driver_pin'] = proof['driver_pin'] = 'fill/VDD'
    missing = []
    result = judge._annotate_limits(row, 'max_slew',
        {'name': 'scene', 'linked_liberties': [], '_physical_pin_proofs': {'fill/VDD': proof}},
        {}, {'fill/VDD': meta}, {}, missing)
    assert result is False
    assert any('Liberty identity unresolved' in item for item in missing)
