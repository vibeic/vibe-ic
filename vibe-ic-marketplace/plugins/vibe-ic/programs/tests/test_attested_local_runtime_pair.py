"""Runtime preflight against the actual host-owned LOCAL launch identity."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _eda_pin as pin
import _runtime_pair_preflight as pair
import librelane_contract as local


def test_actual_local_launch_is_the_preflight_identity():
    identity = local.local_image_attestation()
    result = pair.preflight()
    assert result['verdict'] == pair.RUNTIME_PAIR_MATCH
    assert result['container'] == identity['cid']
    assert result['found_digest'] == pin.reference_digest(identity['image'])


def test_wrong_image_is_refused(monkeypatch):
    identity = local.local_image_attestation()
    wrong = 'sha256:' + ('0' if identity['image'][-1] != '0' else '1') * 64
    monkeypatch.setattr(pin, 'resolved_image_digest', lambda env=None: wrong)
    result = pair.preflight()
    assert result['verdict'] == pair.RUNTIME_PAIR_MISMATCH, result
    assert result['evidence']


def test_missing_attestation_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv(local.LOCAL_ATTESTATION_ENV, str(tmp_path / 'missing.json'))
    result = pair.preflight()
    assert result['verdict'] == pair.RUNTIME_PAIR_MISMATCH, result
    assert result['evidence']
