#!/usr/bin/env python3
"""ORGANIC #759 [P2, chip-AGNOSTIC] — spec_coverage_check reset-coverage FALSE
POSITIVE: the reset-port-name regex anchored the reset stem to start-of-string
or underscore `(?:^|_)`, so AMBA bus-prefixed active-low resets glued directly
to the stem (presetn = p+resetn, hresetn = h+resetn, hreset_n) broke the anchor
and were NOT recognised. `_rtl_reset_ports` then returned [], the coverage
tokens stayed the generic ['reset','rst','por'], and a TB faithfully driving the
real `presetn` port was scored UNCOVERED -> false BLOCK.

Fix: a generic, chip-AGNOSTIC AMBA reset-naming grammar — a short 1-4 char
bus/clock-domain prefix glued directly to reset/rst, ONLY when carrying the
active-low 'n' suffix (the noun-disambiguator that rejects preset / preset_value
/ prescaler / present / prdata) — plus AMBA literals in the exact set.

§4.05 NO-LEAK: a TB that never drives the actual reset port (only decoys like
preset_value / prescaler / present) must STILL score the reset UNCOVERED and
BLOCK under --strict.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import spec_coverage_check as M  # noqa: E402

_PROG = _PROGRAMS / "spec_coverage_check.py"


# ── (a) NEW-PATH: AMBA active-low resets are recognised ──────────────────────
def test_759_amba_resets_recognised():
    for nm in ("presetn", "preset_n", "hresetn", "hreset_n", "sresetn",
               "resetn", "rst_n", "arst_n"):
        assert M._is_reset_port_name(nm), nm


# ── (b) REGRESSION GUARD: reset-noun decoys are still rejected ────────────────
def test_759_reset_decoys_still_rejected():
    for nm in ("prescaler", "preset_value", "present", "prdata", "pwrite",
               "presence", "preselect"):
        assert not M._is_reset_port_name(nm), nm


# ── (c) §4.05 NEGATIVE NO-LEAK: a TB driving only decoys still BLOCKs ─────────
def test_759_noleak_decoy_only_tb_still_uncovered(tmp_path):
    spec = (tmp_path / "spec.md")
    spec.write_text(
        "# APB peripheral\nThe APB slave is reset by active-low `presetn`. "
        "All registers clear when `presetn` is low.\n")
    # TB references only decoy tokens, never the real presetn port.
    tb = (tmp_path / "tb.sv")
    tb.write_text(
        "module tb; reg prescaler; reg [7:0] preset_value; wire present;\n"
        "initial begin prescaler=0; preset_value=8'h10; #1; $finish; end\n"
        "endmodule\n")
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--spec", str(spec), "--tb", str(tb),
         "--strict"], capture_output=True, text=True)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "reset" in (cp.stdout + cp.stderr).lower()


# ── (d) #478 END-STATE: a TB driving the REAL presetn is COVERED -> rc 0 ──────
def test_759_endstate_real_reset_tb_passes_strict(tmp_path):
    """The coverage-token augmentation reads the RTL's reset ports (#759 makes
    `presetn` recognised there); with the real presetn port in the RTL and a TB
    that drives it, the reset item is COVERED and --strict exits 0."""
    spec = (tmp_path / "spec.md")
    spec.write_text(
        "# APB peripheral\nThe APB slave is reset by active-low `presetn`.\n")
    rtl = (tmp_path / "rtl.sv")
    rtl.write_text(
        "module apb(input pclk, input presetn, output [7:0] q); endmodule\n")
    tb = (tmp_path / "tb.sv")
    tb.write_text(
        "module tb; reg presetn, pclk; apb u(.pclk(pclk), .presetn(presetn),"
        " .q());\n"
        "initial begin presetn=0; #2; presetn=1; #10; $finish; end\n"
        "endmodule\n")
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--spec", str(spec), "--rtl", str(rtl),
         "--tb", str(tb), "--strict"], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "spec-coverage ok" in cp.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
