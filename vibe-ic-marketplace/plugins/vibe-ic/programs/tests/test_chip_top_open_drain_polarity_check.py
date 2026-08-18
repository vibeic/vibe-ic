#!/usr/bin/env python3
"""Tests for chip_top_open_drain_polarity_check.py.

Pins the BENCH-A open-drain wrapper polarity gate: the wrapper's
tristate `(oe_low_w == 1'bX)` selector MUST agree with the chip's
`assign <bus>_oe_low = <bus>_drive_low;` semantic (drive-active-high).
A wrapper that drives when oe_low==0 against a drive-active-high chip
holds the bus opposite at idle → FAIL.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "chip_top_open_drain_polarity_check.py"

_spec = importlib.util.spec_from_file_location(
    "chip_top_open_drain_polarity_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ----------------------------------------------------------------------
# fixture builders
# ----------------------------------------------------------------------
# RTL where oe_low is driven by *_drive_low → "1 means drive" semantic.
_RTL_DRIVE_ACTIVE_HIGH = (
    "module chip_top_asic(...);\n"
    "  assign id_bus_oe_low = id_bus_drive_low;\n"
    "  assign id_bus_drive_data = 1'b0;\n"
    "endmodule\n"
)

# RTL where oe_low is driven by a plain active-low OE (no drive_low) →
# drive_active_high == False, so wrapper must drive when oe_low==0.
_RTL_PLAIN_OE = (
    "module chip_top_asic(...);\n"
    "  assign id_bus_oe_low = ~bus_enable;\n"
    "  assign id_bus_drive_data = 1'b0;\n"
    "endmodule\n"
)

# RTL with no split-tristate at all → gate skips (rc 0).
_RTL_NO_SPLIT = (
    "module chip_top_asic(...);\n"
    "  assign something_else = 1'b0;\n"
    "endmodule\n"
)


def _wrapper_drives_when(bit: str) -> str:
    return (
        "module chip_top_gate_wrapper(...);\n"
        f"  assign id_bus = (oe_low_w == 1'b{bit}) ? drive_data_w : 1'bz;\n"
        "endmodule\n"
    )


def _wrapper_no_canonical() -> str:
    return (
        "module chip_top_gate_wrapper(...);\n"
        "  assign id_bus = drive_data_w;\n"
        "endmodule\n"
    )


def _run(wrapper_txt: str, rtl_txt: str, tmp_path: Path,
         bus_prefix: str | None = None) -> int:
    w = tmp_path / "chip_top_gate_wrapper.v"
    r = tmp_path / "chip_top_asic.sv"
    w.write_text(wrapper_txt)
    r.write_text(rtl_txt)
    argv = ["--wrapper", str(w), "--asic-rtl", str(r)]
    if bus_prefix:
        argv += ["--bus-prefix", bus_prefix]
    # main() parses sys.argv via argparse with no argv param, so patch.
    import sys
    old = sys.argv
    sys.argv = ["prog"] + argv
    try:
        return mod.main()
    finally:
        sys.argv = old


# ----------------------------------------------------------------------
# PASS — wrapper polarity matches chip semantic
# ----------------------------------------------------------------------
def test_pass_drive_active_high_wrapper_agrees(tmp_path):
    # chip: drive_active_high → wrapper must drive when oe_low==1
    rc = _run(_wrapper_drives_when("1"), _RTL_DRIVE_ACTIVE_HIGH, tmp_path)
    assert rc == 0


def test_pass_plain_oe_wrapper_drives_when_zero(tmp_path):
    # chip: NOT drive_active_high → wrapper must drive when oe_low==0
    rc = _run(_wrapper_drives_when("0"), _RTL_PLAIN_OE, tmp_path)
    assert rc == 0


# ----------------------------------------------------------------------
# FAIL — the real BENCH-A inverted-polarity defect
# ----------------------------------------------------------------------
def test_fail_inverted_polarity(tmp_path):
    # chip is drive-active-high but wrapper drives when oe_low==0 → inverted.
    rc = _run(_wrapper_drives_when("0"), _RTL_DRIVE_ACTIVE_HIGH, tmp_path)
    assert rc == 1


def test_fail_inverted_other_direction(tmp_path):
    # chip is plain-OE (drive when 0) but wrapper drives when oe_low==1.
    rc = _run(_wrapper_drives_when("1"), _RTL_PLAIN_OE, tmp_path)
    assert rc == 1


# ----------------------------------------------------------------------
# Edge — no split-tristate / non-canonical wrapper → skip with rc 0
# ----------------------------------------------------------------------
def test_skip_no_split_tristate_in_rtl(tmp_path):
    # No `assign id_bus_oe_low = ...` → skip (not a split-tristate chip).
    rc = _run(_wrapper_drives_when("0"), _RTL_NO_SPLIT, tmp_path)
    assert rc == 0


def test_skip_wrapper_missing_canonical_assign(tmp_path):
    # RTL has the oe_low, but wrapper has no canonical tristate ternary.
    rc = _run(_wrapper_no_canonical(), _RTL_DRIVE_ACTIVE_HIGH, tmp_path)
    assert rc == 0


def test_custom_bus_prefix(tmp_path):
    rtl = (
        "module chip_top_asic(...);\n"
        "  assign foo_oe_low = foo_drive_low;\n"
        "endmodule\n"
    )
    wrapper = (
        "module w(...);\n"
        "  assign foo = (oe_low_w == 1'b1) ? drive_data_w : 1'bz;\n"
        "endmodule\n"
    )
    rc = _run(wrapper, rtl, tmp_path, bus_prefix="foo")
    assert rc == 0
