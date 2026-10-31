import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import drv_signoff_anchor as anchor


def test_pdk_anchor_uses_existing_entrypoint_aware_launcher(monkeypatch):
    calls = []
    monkeypatch.setattr(anchor._ll, 'run_container', lambda argv, **kw: (
        calls.append(argv) or subprocess.CompletedProcess(
            argv, 0, '{"sha256":"' + 'ab' * 32 + '"}', '')))
    result = anchor.image_pdk_anchor('pinned-image', 'sky130A', 'sky130_fd_sc_hd')
    assert result['sha256'] == 'ab' * 32
    assert '--entrypoint' in calls[0]
    assert '--skip' not in calls[0]
