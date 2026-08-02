"""A reported supply voltage of ZERO is the absence of a measurement.

The IR-drop reporter parsed PSM's `Supply voltage :` banner with two guards —
"line absent" and "value unparseable" — both falling back to the nominal. A
parsed **0.0** matched neither and went straight into

    worst_ir_uv / (vdd_v * 1e6) * 100.0

which raised ZeroDivisionError and aborted the sign-off chain on a run whose
routing and GDS streamout had already succeeded.

Zero is what PSM prints when it found no source to analyse on the net: an
unconnected macro supply pin, or a rail declared in SPECIALNETS with no
geometry under it. So the repair is NOT a third fallback to nominal — that
would publish an IR percentage and a budget PASS against a voltage the tool
never measured, which is worse than the crash. The absence is published as an
absence.

NDA: no chip, PDK, foundry, vendor or part token appears here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phase3_one_shot_runner import _ir_supply_from_psm_log  # noqa: E402


def test_zero_supply_is_not_a_measurement():
    v, measured = _ir_supply_from_psm_log("Supply voltage   : 0.00e+00 V\n")
    assert v == 0.0
    assert measured is False


def test_zero_supply_does_not_fall_back_to_nominal():
    """The fix must not invent a voltage PSM never reported."""
    v, _ = _ir_supply_from_psm_log("Supply voltage   : 0.00e+00 V\n")
    assert v != 1.8


def test_plain_zero_forms_are_all_caught():
    for form in ("0", "0.0", "0.00e+00", "-0.0"):
        v, measured = _ir_supply_from_psm_log(f"Supply voltage : {form} V")
        assert measured is False, form
        assert v <= 0.0, form


def test_real_supply_is_a_measurement():
    v, measured = _ir_supply_from_psm_log("Supply voltage   : 1.80e+00 V\n")
    assert v == pytest.approx(1.8)
    assert measured is True


def test_absent_banner_keeps_the_historical_nominal():
    """PSM ran; this reader could not find the line. Behaviour unchanged."""
    v, measured = _ir_supply_from_psm_log("no banner here at all")
    assert v == pytest.approx(1.8)
    assert measured is True


def test_unparseable_banner_keeps_the_historical_nominal():
    v, measured = _ir_supply_from_psm_log("Supply voltage   : NaNV V\n")
    assert v == pytest.approx(1.8)
    assert measured is True


def test_nominal_is_overridable():
    v, measured = _ir_supply_from_psm_log("nothing", nominal_v=3.3)
    assert v == pytest.approx(3.3)
    assert measured is True


def test_the_shape_that_crashed_no_longer_divides_by_zero():
    """The exact expression from the reporter, guarded by `measured`."""
    log = (
        "[WARNING PSM-0039] Unconnected instance u_blk/VDD at (1.0um, 2.0um).\n"
        "[ERROR PSM-0069] Check connectivity failed on VDD.\n"
        "Supply voltage   : 0.00e+00 V\n"
        "Worstcase IR drop: 0.00e+00 V\n"
    )
    vdd_v, measured = _ir_supply_from_psm_log(log)
    worst_uv = 0.0
    pct = (round(worst_uv / (vdd_v * 1e6) * 100.0, 3) if measured else None)
    assert pct is None
