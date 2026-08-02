#!/usr/bin/env python3
"""A create_clock on a board OSCILLATOR port must carry the OSCILLATOR's period.

The existing period rule compares the SDC against the DESIGN's declared clock
period. A generator that binds the design period to a board oscillator port
therefore agrees with itself and PASSes, while telling the FPGA tool the wrong
frequency for the physical part soldered to the board.

The port name is the independent witness: a port called ``CLOCK_50`` is wired to
a 50 MHz can whatever the design wants, and a slower application clock can only
be reached through a divider or PLL — which in SDC is a
``create_generated_clock``. With no generated clock the SDC is asserting that
the oscillator itself runs at the design's period.

Board-file port naming is a convention, not a chip/vendor/SKU token, so these
fixtures are shape-only.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent
        / "fpga_sdc_clock_constraint_check.py")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fpga_sdc_clock_constraint_check import (  # noqa: E402
    port_name_declared_freq_mhz,
)


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


def _make(tmp_path: Path, *, port: str, sdc_period_ns: float,
          rtl_period_ns: float, generated_clock: bool = False) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase2" / "stage1" / "fpga").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl" / "top.v").write_text(
        "module top(input clk, input d, output reg q);\n"
        "  always @(posedge clk) q <= d;\n"
        "endmodule\n")
    (proj / "phase2" / "stage1" / "rtl" / "rtl_constants_pkg.sv").write_text(
        f"package rtl_constants_pkg;\n"
        f"  parameter CLOCK_PERIOD_NS = {rtl_period_ns};\n"
        f"endpackage\n")
    sdc = (f"create_clock -name {{app_clk}} -period {sdc_period_ns} "
           f"[get_ports {{{port}}}]\n"
           "derive_pll_clocks\n"
           "derive_clock_uncertainty\n")
    if generated_clock:
        sdc += ("create_generated_clock -name div -source "
                f"[get_ports {{{port}}}] -divide_by 10 [get_pins div_reg/q]\n")
    (proj / "phase2" / "stage1" / "fpga" / "design.sdc").write_text(sdc)
    return proj


# ------------------------- the name reader --------------------------- #

@pytest.mark.parametrize("port,mhz", [
    ("CLOCK_50", 50.0), ("clk_50", 50.0), ("SYSCLK_125", 125.0),
    ("CLK_100MHZ", 100.0), ("clk_100mhz", 100.0),
    ("OSC_32KHZ", 0.032), ("XTAL_25MHZ", 25.0),
])
def test_port_name_frequency_is_read(port: str, mhz: float) -> None:
    got = port_name_declared_freq_mhz(port)
    assert got is not None, f"{port} states a frequency"
    assert got[0] == pytest.approx(mhz)


@pytest.mark.parametrize("port", [
    "clk", "clk_i", "core_clk", "CLK_0", "clk_1", "clk_2",   # indices, not MHz
    "CLOCK_2000",                                            # outside the band
    "data_50", "",
])
def test_port_name_without_a_frequency_is_not_invented(port: str) -> None:
    assert port_name_declared_freq_mhz(port) is None


# --------------------------- the rule -------------------------------- #

def test_design_period_bound_to_a_board_oscillator_port_fails(
        tmp_path: Path) -> None:
    """The regression: SDC and design agree (so the existing period rule is
    silent) but both disagree with the oscillator by 10x."""
    proj = _make(tmp_path, port="CLOCK_50", sdc_period_ns=200.0,
                 rtl_period_ns=200.0)
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    out = r.stdout + r.stderr
    assert "FPGA_SDC_BOARD_OSC_MISMATCH" in out
    assert "10.0x" in out
    assert "50 MHz" in out and "20 ns" in out


def test_matching_oscillator_period_passes(tmp_path: Path) -> None:
    proj = _make(tmp_path, port="CLOCK_50", sdc_period_ns=20.0,
                 rtl_period_ns=20.0)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "BOARD_OSC_MISMATCH" not in (r.stdout + r.stderr)


def test_generated_clock_downgrades_to_advisory(tmp_path: Path) -> None:
    """A declared divider is exactly the legitimate board-osc -> app-clock
    topology, so the same numbers must not block."""
    proj = _make(tmp_path, port="CLOCK_50", sdc_period_ns=200.0,
                 rtl_period_ns=200.0, generated_clock=True)
    r = _run(proj)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "WARN — FPGA_SDC_BOARD_OSC_MISMATCH" in out


def test_small_drift_warns_but_does_not_block(tmp_path: Path) -> None:
    """Short of a whole multiple this is a rounding/margin choice, not a wrong
    oscillator: 22 ns on a 20 ns can is 1.1x, over the 5 % notice threshold and
    well under the 2x block threshold."""
    proj = _make(tmp_path, port="CLOCK_50", sdc_period_ns=22.0,
                 rtl_period_ns=22.0)
    r = _run(proj)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "FPGA_SDC_BOARD_OSC_DRIFT" in out


def test_port_that_states_no_frequency_is_untouched(tmp_path: Path) -> None:
    proj = _make(tmp_path, port="sys_clk_in", sdc_period_ns=200.0,
                 rtl_period_ns=200.0)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "BOARD_OSC" not in (r.stdout + r.stderr)
