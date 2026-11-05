"""Existing producer calls retain old bytes and their actual canonical verdict."""
import os
from pathlib import Path
import sys

import pytest

PROGRAMS = Path(os.environ.get('VIBEIC_CANONICAL_RETENTION_PROGRAMS',
                              str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(PROGRAMS))
import execution_policy as policy
import step_output_collector as versions


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    monkeypatch.setattr(policy, 'request', lambda: {'mode': 'default'})
    monkeypatch.setattr(policy, '_ordinary_runtime', None)




def test_view_observations_without_invocation_times_are_not_complete_acceptance(tmp_path):
    versions.materialize(tmp_path)
    assert versions.current_acceptance(tmp_path, 0) == []












def test_unknown_input_identity_does_not_claim_current_pass(tmp_path):
    attempt = versions.begin_step(tmp_path, '1')
    versions.finish_step(tmp_path, attempt, verdict='PASS', canonical_pass=True)
    historical = versions.latest_pass(tmp_path, '1')
    assert historical['status'] == 'PASS'
    assert historical['current_inputs'] is False














MIXED = [
    ('M1', 'mixed_signal_top_lvs_run.py', 'top_lvs_run.json'),
    ('M2', 'mixed_signal_power_domain_run.py', 'power_domain_producer_audit.json'),
    ('M3', 'mixed_signal_m3_run.py', 'm3_producer_audit.json'),
    ('M4', 'mixed_signal_signoff_run.py', 'signoff_producer_audit.json'),
]
