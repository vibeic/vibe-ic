"""Tests for the v0.2.16 honest typed-N/A escapes in
l_doc_structured_field_count_check.py — L3 no-CRC / L11 no-OTP / L13 no-lab.

These complete the set begun by L5.no_analog / L12.no_calibration: a pure-
digital protocol IC (e.g. MDIO) genuinely has NO CRC / NO OTP fuses / NO lab
calibration, and the runner already emits explicit honest declarations. The
gate must ACCEPT those declarations while still FAILing for a bare missing /
empty / false-flagged field (the honesty guards).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PROG = Path(__file__).parent.parent / "l_doc_structured_field_count_check.py"
_spec = importlib.util.spec_from_file_location("_l_doc_sfc", _PROG)
mod = importlib.util.module_from_spec(_spec)
sys.modules["_l_doc_sfc"] = mod
_spec.loader.exec_module(mod)

_check = mod._check_l_doc


# ---------------------------------------------------------------------------
# L3 — honest no-CRC escape
# ---------------------------------------------------------------------------

_FIVE_OPCODES = [{"hex": f"{i:02x}", "name": f"op{i}"} for i in range(5)]


def test_l3_honest_no_crc_flag_passes():
    """crc_parameters:null + explicit no_crc_parameters_in_input:true → PASS."""
    data = {
        "opcodes": _FIVE_OPCODES,
        "crc_parameters": None,
        "no_crc_parameters_in_input": True,
    }
    ok, reason = _check(3, data)
    assert ok, reason


def test_l3_filled_crc_block_still_passes():
    """A genuinely-CRC protocol with a filled crc_parameters dict → PASS."""
    data = {
        "opcodes": _FIVE_OPCODES,
        "crc_parameters": {"polynomial_hex": "0x07", "init_hex": "0x00"},
    }
    ok, reason = _check(3, data)
    assert ok, reason


def test_l3_no_crc_false_still_fails():
    """no_crc_parameters_in_input:false (genuinely HAS crc) + empty block →
    requirement stays IN FORCE → FAIL (honesty guard (b))."""
    data = {
        "opcodes": _FIVE_OPCODES,
        "crc_parameters": None,
        "no_crc_parameters_in_input": False,
    }
    ok, _ = _check(3, data)
    assert not ok


def test_l3_bare_missing_crc_still_fails():
    """No crc_parameters and NO explicit no_crc flag → FAIL (honesty guard
    (a): a bare missing field never counts as an honest N/A)."""
    data = {"opcodes": _FIVE_OPCODES}
    ok, _ = _check(3, data)
    assert not ok


# ---------------------------------------------------------------------------
# L11 — honest no-OTP escape
# ---------------------------------------------------------------------------

def test_l11_otp_present_false_passes():
    """Real lpc/espi shape → PASS. v0.2.19: L11 jointly owns
    behavioral_sequences + calibration_tables + OTP, so a BARE otp_present:false
    no longer escapes on its own (see test_l11_bare_otp_present_false_fails);
    the real lpc/espi N/A stub carries the EXPLICIT no_otp_fsm_in_input:true
    flag, which is the honest layer-level "no OTP FSM in input" declaration."""
    data = {"otp_present": False, "no_otp_fsm_in_input": True,
            "behavioral_sequences": []}
    ok, reason = _check(11, data)
    assert ok, reason


def test_l11_bare_otp_present_false_fails():
    """v0.2.19: otp_present:false ALONE (no explicit no_otp/applicable flag,
    empty behavioral+calibration) is NOT a sufficient L11 escape — L11 also
    owns behavioral/calibration, so the ≥3 floor stays in force. Mirrors
    test_l_doc_digital_extractors_v0182::test_l11_still_required_without_escape."""
    data = {"otp_present": False, "behavioral_sequences": []}
    ok, _ = _check(11, data)
    assert ok is False


def test_l11_applicable_false_passes():
    """applicable:false (mdio N/A-stub shape, otp_present is a string) → PASS."""
    data = {
        "applicable": False,
        "no_otp_fsm_in_input": True,
        "otp_present": "functionally equivalent text, not a fuse bank",
    }
    ok, reason = _check(11, data)
    assert ok, reason


def test_l11_no_otp_fsm_flag_passes():
    """Explicit no_otp_fsm_in_input:true alone → PASS."""
    data = {"no_otp_fsm_in_input": True}
    ok, reason = _check(11, data)
    assert ok, reason


def test_l11_otp_present_string_only_still_fails():
    """otp_present as a free-text STRING with no explicit False/no_otp flag →
    FAIL (honesty guard (a): a string is not an explicit boolean N/A)."""
    data = {"otp_present": "the device identification register is OTP-like"}
    ok, _ = _check(11, data)
    assert not ok


def test_l11_bare_missing_still_fails():
    """No behavioral/cal entries and NO honest no-OTP signal → FAIL."""
    data = {"behavioral_sequences": [], "calibration_tables": []}
    ok, _ = _check(11, data)
    assert not ok


def test_l11_genuine_otp_content_still_passes():
    """A genuinely-OTP IC with ≥3 typed otp fields → PASS (unchanged)."""
    data = {"fields": {"ID": {"v": 1}, "IMSN": {"v": 2}, "ASN": {"v": 3}}}
    ok, reason = _check(11, data)
    assert ok, reason


# ---------------------------------------------------------------------------
# L13 — honest no-lab-calibration escape
# ---------------------------------------------------------------------------

def test_l13_lab_calibration_present_false_passes():
    """Explicit lab_calibration_present:false → PASS."""
    data = {"lab_calibration_present": False, "test_cases": []}
    ok, reason = _check(13, data)
    assert ok, reason


def test_l13_applicable_false_passes():
    """applicable:false (mdio N/A-stub shape) → PASS."""
    data = {"applicable": False, "test_cases": []}
    ok, reason = _check(13, data)
    assert ok, reason


def test_l13_bare_missing_still_fails():
    """No typed cases and NO honest no-lab signal → FAIL."""
    data = {"test_cases": []}
    ok, _ = _check(13, data)
    assert not ok


def test_l13_lab_present_true_still_fails():
    """lab_calibration_present:true (genuinely HAS lab cal) but no typed cases
    → requirement stays IN FORCE → FAIL."""
    data = {"lab_calibration_present": True, "test_cases": []}
    ok, _ = _check(13, data)
    assert not ok


def test_l13_genuine_cases_still_pass():
    """Five typed test cases → PASS (unchanged)."""
    data = {"test_cases": [{"id": i} for i in range(5)]}
    ok, reason = _check(13, data)
    assert ok, reason


# ---------------------------------------------------------------------------
# Do-not-weaken: L5 / L12 escapes still behave exactly as before.
# ---------------------------------------------------------------------------

def test_l5_no_analog_still_required_when_absent():
    """L5 with no analog blocks and NO no_analog flag → FAIL (unchanged)."""
    data = {"analog_blocks": []}
    ok, _ = _check(5, data)
    assert not ok


def test_l5_no_analog_true_passes():
    data = {"no_analog": True}
    ok, reason = _check(5, data)
    assert ok, reason


def test_l12_no_calibration_still_required_when_absent():
    """L12 with no calibration content and NO no_calibration flag → FAIL."""
    data = {"calibration_steps": []}
    ok, _ = _check(12, data)
    assert not ok


def test_l12_no_calibration_true_passes():
    data = {"no_calibration": True}
    ok, reason = _check(12, data)
    assert ok, reason
