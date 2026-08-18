"""tests/test_phase1_issue17_l11_mode_classifier.py — v1.6.85

Closes #17 Bug C — L11 operating-mode vs FSM-state classifier.

OTP_RW / VCC2P5 / VCC1P2_VCC / POWER_DOWN are operating modes
(power domains / chip-level run modes), not FSM states. They must
NOT appear in L11.fsm_state_catalogue (which is subject to
fsm_state_coverage_check) and instead route to a new
L11.operating_modes[] field.

Reject-tests:
  1. operating_modes-labelled tokens classify as op-modes.
  2. fsm-state-labelled tokens that match the op-mode pattern
     STILL route to op-modes (the classifier wins over the label).
  3. positive control: real S_* state names route to fsm_states.
  4. unit test of _is_operating_mode_not_fsm_state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
for p in (str(PROGRAMS), str(PLUGIN_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from programs import phase1_one_shot_runner as p2a  # noqa: E402

_GEN_DIR = Path("phase1") / "generated_docs"


def _read(project: Path, name: str) -> dict:
    return json.loads((project / _GEN_DIR / f"{name}.json").read_text())


def _seed(project: Path) -> Path:
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    return project


def test_l11_separates_operating_modes_from_fsm_states(tmp_path):
    """When narrative explicitly labels both, op-modes and fsm-states
    land in their respective fields."""
    project = _seed(tmp_path / "modes_proj")
    extracted = {
        "datasheet.txt": (
            "Operating modes: OTP_RW (read/write), VCC2P5 (2.5V domain), "
            "VCC1P2_VCC (1.2V domain).\n"
            "FSM states: S_IDLE, S_RX, S_TX, S_VALIDATE.\n"
        ),
    }
    p2a.gen_l11_otp_content(project, extracted)
    l11 = _read(project, "L11_OTP_CONTENT")
    op_modes = l11.get("operating_modes") or []
    op_names = {m.get("name", "").upper() for m in op_modes}
    assert "OTP_RW" in op_names
    assert "VCC2P5" in op_names
    assert "VCC1P2_VCC" in op_names
    fsm_states = l11.get("fsm_state_catalogue") or []
    fsm_names = {s.get("name", "").upper() for s in fsm_states}
    # Power-domain / OTP_RW labels must NOT leak into fsm states.
    assert "OTP_RW" not in fsm_names
    assert "VCC2P5" not in fsm_names
    assert "VCC1P2_VCC" not in fsm_names


def test_l11_classifier_wins_over_input_label(tmp_path):
    """Even when input narrative labels VCC2P5 under "FSM states:",
    the chip-AGNOSTIC pattern classifier routes it to op-modes."""
    project = _seed(tmp_path / "mislabelled_proj")
    extracted = {
        "datasheet.txt": (
            "FSM states: VCC2P5, VCC1P2, OTP_RW, S_IDLE.\n"
        ),
    }
    p2a.gen_l11_otp_content(project, extracted)
    l11 = _read(project, "L11_OTP_CONTENT")
    op_names = {m.get("name", "").upper()
                for m in (l11.get("operating_modes") or [])}
    fsm_names = {s.get("name", "").upper()
                 for s in (l11.get("fsm_state_catalogue") or [])}
    assert "VCC2P5" in op_names
    assert "VCC1P2" in op_names
    assert "OTP_RW" in op_names
    assert "S_IDLE" in fsm_names
    # And S_IDLE must not be miscategorised as an op-mode.
    assert "S_IDLE" not in op_names


def test_l11_no_modes_in_input_flag_set_when_empty(tmp_path):
    """Project with no mode/state evidence emits empty op-modes
    plus the standard `no_<X>_in_input` flag."""
    project = _seed(tmp_path / "empty_proj")
    extracted = {"datasheet.txt": "No mode or state info here.\n"}
    p2a.gen_l11_otp_content(project, extracted)
    l11 = _read(project, "L11_OTP_CONTENT")
    assert (l11.get("operating_modes") or []) == []
    assert l11.get("no_operating_modes_in_input") is True


def test_is_operating_mode_not_fsm_state_unit():
    """Direct unit test of the classifier helper."""
    fn = p2a._is_operating_mode_not_fsm_state
    # Op-mode patterns — True.
    for nm in ("VCC2P5", "VCC1P2", "VCC1P2_VCC", "V2P5", "V1P2",
               "OTP_RW", "OTP_READ", "OTP_WRITE", "OTP_PROGRAM",
               "STANDBY", "SLEEP", "ACTIVE", "POWER_DOWN", "POWER_ON"):
        assert fn(nm), f"{nm} should classify as op-mode"
    # Real FSM states — False.
    for nm in ("S_IDLE", "S_RX", "S_TX", "S_VALIDATE", "S_WAIT_BR"):
        assert not fn(nm), f"{nm} should NOT classify as op-mode"
