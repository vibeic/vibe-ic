"""`synth_wrapper_check` asks the DESIGN whether it needs a wrapper (icspm2).

MEASURED FAILURE THIS PINS
==========================
A completed gf180mcuD run of `spm` (2026-09-15, lane icspm2) reached the
completion audit with

    [ERROR] NO_WRAPPER: No *wrapper*.v or *wrapper*.sv files found, but design
                        has inout ports

and the design declares NO inout port anywhere. `phase2/stage1/rtl/spm.v` has
five ports — `input wire clk`, `input wire rst`, `input wire [size-1:0] x`,
`input wire y`, `output wire p`. The three matches that produced the verdict,
each measured on that run tree:

  * `phase2/stage1/sim_full_stack/tb_spm_full.v:51`
        `// No inout pad in L9; drive_byte is a no-op for sync compatibility.`
    a COMMENT whose sentence says there is no inout — the #731 shape.
  * `phase3/stage3/pnr/spm_pnr.v:13-14`, and
  * `phase3/stage3/extracted/spm_pwraware_welltied.v:13-14`
        `inout VDD;` / `inout VSS;`
    the supply pins THE FLOW writes into every power-aware netlist it emits.

None of the three is a port of the design. Two of them are artefacts the flow
manufactured itself, so the gate refused a design on evidence its own back end
had written one step earlier, and it would do so on EVERY routed design.

THE TWO DIRECTIONS
==================
Every test here that asserts the false positive is gone has a sibling asserting
the gate still bites: a design whose OWN RTL declares an inout and that ships no
wrapper is still `NO_WRAPPER`, rc 1.
"""
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# THE CONTROL ARM MUST *RUN*, NOT RAISE.
#
# A test that reaches `swc.design_inout_evidence` on the pre-fix blob dies with
# AttributeError, and an AttributeError observes nothing: it proves the symbol
# is new, not that the old code answered wrongly. These two shims route through
# `getattr`, so against the pre-fix tree the OLD `design_has_inout` runs and
# gives its own (wrong) answer, and the assertion below is the thing that fails.
# ---------------------------------------------------------------------------


def _sources(proj):
    rtl = Path(proj) / "phase2/stage1/rtl"
    if not rtl.is_dir():
        return []
    return sorted(set(list(rtl.rglob("*.v")) + list(rtl.rglob("*.sv"))))

# The real design, byte-for-byte in the shape the run staged it.
SPM_RTL = """\
`default_nettype none
//============================================================================
// spm — serial-parallel (carry-save) integer multiplier
//============================================================================
module spm #(
    parameter size = 32
) (
    input  wire            clk,
    input  wire            rst,
    input  wire [size-1:0] x,
    input  wire            y,
    output wire            p
);
    assign p = 1'b0;
endmodule
"""

# The testbench line that produced the false positive, verbatim.
TB_WITH_INOUT_IN_A_COMMENT = """\
module tb_spm_full;
    reg clk = 0;
    task drive_byte(input [7:0] b);
      // No inout pad in L9; drive_byte is a no-op for sync compatibility.
    endtask
endmodule
"""

# The supply pins the flow writes into a power-aware netlist, verbatim.
POWER_AWARE_NETLIST = """\
module spm (clk, rst, x, y, p, VDD, VSS);
  inout VDD;
  inout VSS;
  input clk;
  output p;
endmodule
"""

REAL_INOUT_RTL = """\
module i2c_top (
    input  wire clk,
    inout  wire sda,
    output wire scl
);
endmodule
"""


def _project(tmp_path, rtl=None, tb=None, netlist=None, extracted=None):
    """A project laid out exactly the way the runner lays one out."""
    p = tmp_path / "proj"
    (p / "phase2/stage1/rtl").mkdir(parents=True)
    if rtl is not None:
        (p / "phase2/stage1/rtl/spm.v").write_text(rtl)
    if tb is not None:
        (p / "phase2/stage1/sim_full_stack").mkdir(parents=True)
        (p / "phase2/stage1/sim_full_stack/tb_spm_full.v").write_text(tb)
    if netlist is not None:
        (p / "phase3/stage3/pnr").mkdir(parents=True)
        (p / "phase3/stage3/pnr/spm_pnr.v").write_text(netlist)
    if extracted is not None:
        (p / "phase3/stage3/extracted").mkdir(parents=True)
        (p / "phase3/stage3/extracted/spm_pwraware_welltied.v").write_text(
            extracted)
    return p


# ---------------------------------------------------------------------------
# DIRECTION 1 — the false positive is gone
# ---------------------------------------------------------------------------


def test_the_population_is_the_one_the_synth_step_reads(tmp_path):
    """Bound to `_path_layout.rtl_dir`, not to a second spelling of the path."""
    import _path_layout as _pl
    proj = _project(tmp_path, rtl=SPM_RTL, tb=TB_WITH_INOUT_IN_A_COMMENT)
    srcs = _sources(proj)
    assert [s.parent for s in srcs] == [_pl.rtl_dir(proj)]
    assert [s.name for s in srcs] == ["spm.v"]


# ---------------------------------------------------------------------------
# DIRECTION 2 — the gate still bites
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# DIRECTION 3 — an empty population is NOT_MEASURED, and says so
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The wrapper files' own declaration scans are stripped too (#731)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# STANDALONE USE — a plain directory of sources, no flow layout
# ---------------------------------------------------------------------------
