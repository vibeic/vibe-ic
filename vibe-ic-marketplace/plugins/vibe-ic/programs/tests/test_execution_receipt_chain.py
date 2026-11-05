"""Pure neutral controls for the existing execution_modes receipt chain."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import execution_policy as policy
from programs.tests import test_execution_modes as H


_launchers = []

@pytest.fixture(autouse=True)
def isolated_transport(monkeypatch):
    monkeypatch.setattr(policy, '_ordinary_runtime', None)
    for name in (policy.ENV, policy._CAPABILITY_FD_ENV, 'VIBEIC_EXECUTION_AUTH_SOCKET'):
        # real_entry writes these locators directly. Record even an absent
        # original key so monkeypatch restores it after the issuer FD closes.
        monkeypatch.setenv(name, os.environ.get(name, ''))
        monkeypatch.delenv(name)
    yield
    for proc, fd, channel in _launchers:
        channel.close(); proc.wait(timeout=10)
        try: os.close(fd)
        except OSError: pass
    _launchers.clear()






















def test_postfix_chain_passes_and_records_all_links(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'), H.adapter('b'))
    root = tmp_path / 'run'
    controller.run(ctx, root, 'ultra-mode')
    assert (root / 'frozen-work.json').is_file()
    assert (root / 'issued-comparison.json').is_file()
    comparison = json.loads((root / 'comparison.json').read_text())
    assert [row['arm_id'] for row in comparison['arm_receipts']] == ['a', 'b']
    assert len(comparison['eligible_arms']) == 2
    adopted = controller.adopt(ctx, root, H.choice(ctx, root, 'a'))
    assert adopted['status'] == 'ADOPTED'
    assert adopted['frozen_work_digest'] == json.loads((root / 'plan.json').read_text())['frozen_work_digest']
    assert adopted['comparison_digest']
    assert adopted['acceptance_rerun']['status'] == 'PASS'
    assert controller.verify_adoption(ctx, root)['selected'] == 'a'
































































def test_default_run_auto_adopts_sole_eligible_without_choice_file(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a'), H.adapter('b'))
    root = tmp_path / 'default'
    result = controller.run(ctx, root)
    assert result['status'] == 'ADOPTED'
    assert result['selected'] == 'a'
    assert not (root / 'choice.json').exists()
    assert json.loads((root / 'result.json').read_text())['status'] == 'ADOPTED'
    assert json.loads((root / 'adoption.json').read_text())['status'] == 'ADOPTED'
    assert [p.name for p in root.iterdir() if p.is_dir() and p.name in ('a', 'b')] == ['a']


@pytest.mark.parametrize('fault,expected', [
    ('fail_gate', 'FAIL'), ('unmeasured', 'NOT_MEASURED'),
])
def test_default_failure_or_unmeasured_result_is_not_auto_adopted(tmp_path, fault, expected):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a', fault=fault))
    root = tmp_path / fault
    result = controller.run(ctx, root)
    assert result['status'] == expected
    assert result['selected'] is None
    assert not (root / 'adoption.json').exists()




def test_ultra_fail_precedes_unmeasured_when_no_arm_is_eligible(tmp_path):
    ctx = H.context(tmp_path)
    controller = H.controller(H.adapter('a', fault='fail_gate'),
                              H.adapter('b', fault='process_error'))
    result = controller.run(ctx, tmp_path / 'ultra', 'ultra-mode')
    assert result['candidate_statuses'] == {'a': 'FAIL', 'b': 'NOT_MEASURED'}
    assert result['status'] == 'FAIL'
    comparison = json.loads((tmp_path / 'ultra/comparison.json').read_text())
    issued = json.loads((tmp_path / 'ultra/issued-comparison.json').read_text())
    assert comparison['status'] == issued['payload']['status'] == 'FAIL'




























def test_ultra_diversity_ignores_arm_labels_when_provider_identity_matches(tmp_path):
    first = H.adapter('neutral_a')
    second = replace(H.adapter('neutral_a'), arm_id='neutral_b', tool_id=first.tool_id,
                     engine_families=('caller_label_b',))
    plan = H.controller(first, second).plan(H.context(tmp_path), 'ultra-mode')
    assert plan['arms'] == ['neutral_a']
    assert next(row for row in plan['portfolio'] if row['arm_id'] == 'neutral_b')['admission'] == 'SAME_ENGINE_FAMILY'
