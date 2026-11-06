"""Hardware report parsing retains absent, invalid and measured outcomes."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


_CHECKER = _PROGRAMS / "analog_a9_hw_verify_check.py"




def _project(tmp_path: Path, hw: dict | None) -> Path:
    """A cosim-complete analog project; `hw` None == no bench measurement."""
    (tmp_path / "phase1" / "analog").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "blk1").mkdir(parents=True)
    (tmp_path / "phase3" / "mixed_signal" / "cosim").mkdir(parents=True)
    blocks = json.dumps({"blocks": [{"name": "blk1"}]})
    (tmp_path / "phase1" / "analog" / "analog_block_list.json").write_text(blocks)
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(blocks)
    cosim = tmp_path / "phase3" / "mixed_signal" / "cosim"
    (cosim / "mixed_signal_results.json").write_text(json.dumps(
        {"scenarios": [{"name": "s1", "status": "PASS"},
                       {"name": "s2", "status": "PASS"}]}))
    (cosim / "blk1_cosim_results.json").write_text(
        json.dumps({"simulation_passed": True}))
    if hw is not None:
        (tmp_path / "phase3" / "analog" / "blk1"
         / "hw_measurements.json").write_text(json.dumps(hw))
    return tmp_path


# ── the defect ───────────────────────────────────────────────────────────────





# ── the checker's own three tiers ────────────────────────────────────────────

def _run_checker(project: Path) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(_CHECKER), str(project)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


@pytest.mark.parametrize("hw,rc,token", [
    # The GATE's own tokens, not step statuses: this runs the checker as a
    # subprocess and reads its stdout.
    (None, 0, "VACUOUS_PASS"),                        # never measured
    ({"measurements": {}}, 1, "FAIL"),                # measured, no numbers
    ({"measurements": {"gain_db": 42.1}}, 0, "PASS"),  # really measured
])
def test_checker_tiers(tmp_path, hw, rc, token):
    """The tiers the gate depends on. A checker that could not FAIL would make
    the wiring decorative."""
    got_rc, out = _run_checker(_project(tmp_path, hw=hw))
    assert got_rc == rc, (got_rc, out[:300])
    assert token in out, out[:300]


# ── the general defect: a required gate must read the same disclosure ────────





# ── the wiring and the naming, pinned ────────────────────────────────────────
