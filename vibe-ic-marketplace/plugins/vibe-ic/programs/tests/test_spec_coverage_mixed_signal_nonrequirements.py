"""Mixed-signal coverage must retain real gaps without inventing RTL work."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


PROGRAMS = Path(os.environ.get(
    "VIBEIC_SPEC_COVERAGE_SUBJECT",
    str(Path(__file__).resolve().parents[1]),
)).resolve()
SPEC = importlib.util.spec_from_file_location(
    "spec_coverage_subject", PROGRAMS / "spec_coverage_check.py")
assert SPEC is not None and SPEC.loader is not None
SUBJECT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SUBJECT
SPEC.loader.exec_module(SUBJECT)


def _run(user_prompt="", l_docs=""):
    stations = {}
    if user_prompt:
        stations["user_prompt"] = user_prompt
    if l_docs:
        stations["l_docs"] = l_docs
    return SUBJECT.run(
        stations,
        "module d(input wire ck); always @(posedge ck) begin end endmodule",
        "module tb; endmodule",
        None,
        True,
    )


def test_explicit_absence_and_schema_instructions_are_not_requirements():
    report = _run(
        user_prompt="the die has NO reset pin",
        l_docs=(
            "Reset behavior verification.\n"
            "Spec does not specify DFT/scan topology; this is deferred to integration.\n"
            '"Look for scan / DFT / BIST / JTAG sections."\n'
            '"trim_loop": []\n'
            "floorplan\n"
        ),
    )
    kinds = {item["kind"] for item in report["items"]}
    assert kinds.intersection({
        "reset", "scan_chain", "jtag_tap", "bist",
        "calibration_field", "rounding_mode",
    }) == set()


def test_decimal_tail_does_not_mint_a_channel_count():
    report = _run(
        l_docs=(
            "incremental delta-sigma modulator core 1.2 V "
            "with 6 identical modulator channels"
        ),
    )
    requirements = {item["requirement"] for item in report["items"]}
    assert "ADC converter with 2 channel(s); the design must implement it and the TB / silicon must exercise the stated converter interface." not in requirements


def test_real_channel_count_is_retained():
    report = _run(
        l_docs="An array of 6 incremental delta-sigma modulator channels",
    )
    assert any(
        item["kind"] == "analog_converter" and "6 channel" in item["requirement"]
        for item in report["items"]
    )


def test_physical_corner_gap_is_advisory_to_a_digital_rtl_tb():
    report = _run(user_prompt="Supply rail is 1.8 V at -40/125 C.")
    assert report["blocked"] is False
    assert report["blocking_gaps"] == 0
    assert report["advisory_gaps"] >= 1
