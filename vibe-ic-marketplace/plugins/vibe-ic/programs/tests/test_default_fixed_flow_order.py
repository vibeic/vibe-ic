"""Cold/resume Default order controls. Synthetic transport is not IC proof."""
import json
from pathlib import Path

import pytest
import execution_policy as policy


@pytest.fixture(autouse=True)
def default_mode(monkeypatch):
    original = policy.request
    monkeypatch.setattr(policy, 'request', lambda: dict(original(), mode='default'))
    monkeypatch.setattr(policy, '_ordinary_runtime', None)










@pytest.mark.parametrize('case', ['clean', 'adopted', 'measured_fail'])
def test_real_cold_step32_does_not_require_a_future_step22_spef(tmp_path, monkeypatch, case):
    from test_default_step32_output_publication import test_current_step32_publishes_before_its_output_receipt
    test_current_step32_publishes_before_its_output_receipt(tmp_path, monkeypatch, case)
    receipts = list(tmp_path.glob('project/reports/phase3/default_steps/32/backend_result.json'))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt['verdict'] == ('FAIL' if case == 'measured_fail' else 'PASS')
    assert not list(tmp_path.rglob('*.spef'))






def test_pinned_native_stream_recipe_accepts_the_recorded_cli_flags():
    import subprocess
    import sys
    from librelane.common import get_script_dir
    recipe = Path(get_script_dir()) / 'klayout/stream_out.py'
    result = subprocess.run([sys.executable, str(recipe), '--help'],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    for flag in ('--input-lef', '--output', '--top', '--lyp', '--lyt', '--lym', '--with-gds-file'):
        assert flag in result.stdout, (flag, result.stdout)
