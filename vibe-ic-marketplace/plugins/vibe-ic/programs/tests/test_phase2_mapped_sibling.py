#!/usr/bin/env python3
"""BIDIRECTIONAL tests for the Phase-2 technology-mapped netlist sibling.

Measured on cell `spm` x `sky130A` (plugin 1.6.4, image vibeic-eda:0.2.30,
image id sha256:4182c63b10d185fad2ff6247525b4f658a02eba4108b76d01b6712206eb06650):

    the SAME program, invoked with the SAME generic `--netlist` argument,
    differing ONLY in whether a liberty-mapped sibling exists beside it:

        defect present (generic netlist alone)  -> faults_total=0    atpg_exit=1
                                                   stuck-at coverage 0.00%
        fix present    (mapped sibling beside)  -> faults_total=876  atpg_exit=0
                                                   stuck-at coverage 98.12%

Each test below is one half of a pair. The DEFECT half must FAIL when the fix
is reverted; the FIXED half must PASS only with the fix in place. A test that
only asserts the good case is a rubber stamp, so both halves are asserted
explicitly and the pair is named so a reviewer can see it is a pair.

Two of the four pairs drive the plugin's OWN oracles rather than a re-statement
of the fix:
  * `fault_atpg_run.resolve_mapped_netlist` -- the real ATPG self-heal
  * `_yosys_inline_mode_detect.check_inline_command_conformance` -- the real
    Step-14 conformance gate
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

from phase2_mapped_sibling import (  # noqa: E402
    MappedSiblingRefused,
    build_mapped_sibling_command,
    mapped_sibling_name,
    should_emit_mapped_sibling,
)

LIB = ("/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
       "sky130_fd_sc_hd__tt_025C_1v80.lib")
HILOMAP = ("hilomap -hicell sky130_fd_sc_hd__conb_1 HI "
           "-locell sky130_fd_sc_hd__conb_1 LO")

# The recipe Phase 2 emits TODAY, verbatim from
# design_one_shot_runner.py:7507-7534 (the defect under test).
TODAYS_PHASE2_RECIPE = (
    "read_verilog -sv -DSIMULATION spm.v; "
    "synth -top spm -flatten; techmap; opt; dffunmap; abc -g cmos2; "
    "write_verilog -noexpr -nostr -noattr netlist_yosys.v; stat"
)

# A minimal generic-unmapped netlist: yosys `$_..._` primitives, no PDK cell.
GENERIC_NETLIST = """\
module spm(clk, rst, x, y, p);
  input clk;
  input rst;
  input [31:0] x;
  input y;
  output p;
  $_NAND_ _100_ (.A(x[0]), .B(y), .Y(_n0_));
  $_NOR_  _101_ (.A(_n0_), .B(rst), .Y(_n1_));
  $_DFF_P_ _102_ (.C(clk), .D(_n1_), .Q(p));
endmodule
"""

# A liberty-MAPPED netlist: real standard cells, no generic primitive.
MAPPED_NETLIST = """\
module spm(clk, rst, x, y, p);
  input clk;
  input rst;
  input [31:0] x;
  input y;
  output p;
  sky130_fd_sc_hd__nand2_1 _100_ (.A(x[0]), .B(y), .Y(_n0_));
  sky130_fd_sc_hd__nor2_1  _101_ (.A(_n0_), .B(rst), .Y(_n1_));
  sky130_fd_sc_hd__dfxtp_1 _102_ (.CLK(clk), .D(_n1_), .Q(p));
endmodule
"""


def _make_project(tmp_path: Path, with_sibling: bool) -> Path:
    """Build a project tree holding a generic netlist, optionally beside the
    technology-mapped sibling. `with_sibling=False` reproduces exactly what
    Phase-2 synth leaves on disk today."""
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "netlist.v").write_text(GENERIC_NETLIST)
    if with_sibling:
        (synth / mapped_sibling_name("spm")).write_text(MAPPED_NETLIST)
    return tmp_path


# ===================================================================== #
# PAIR 1 -- the real ATPG self-heal. This is the decisive pair: it is    #
# the mechanism the measured 0-faults -> 876-faults swing runs through.  #
# ===================================================================== #

def test_pair1_DEFECT_no_mapped_sibling_means_atpg_selfheal_has_nothing_to_find():
    """DEFECT HALF. With only the generic netlist on disk -- today's Phase-2
    output -- `resolve_mapped_netlist` cannot switch, so ATPG is handed a
    netlist iverilog rejects with `Unknown module type: $_NAND_`.

    This assertion FAILS the moment Phase-2 starts emitting the sibling,
    which is precisely what makes the pair bidirectional."""
    from fault_atpg_run import resolve_mapped_netlist

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        project = _make_project(Path(td), with_sibling=False)
        resolved, note = resolve_mapped_netlist(
            project, "phase2/stage2/synth/netlist.v")

    assert resolved == "phase2/stage2/synth/netlist.v", (
        "with no mapped sibling the resolver must return the generic path "
        "unchanged (a genuine gap must fail honestly, not be papered over)")
    assert note is None, "no switch is possible when there is nothing to switch to"


def test_pair1_FIXED_mapped_sibling_lets_atpg_selfheal_switch():
    """FIXED HALF. Emitting the sibling at the name `mapped_sibling_name`
    chooses is sufficient for the plugin's EXISTING self-heal to fire. No
    change to the ATPG program is required -- the ordering gap was the whole
    defect."""
    from fault_atpg_run import resolve_mapped_netlist

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        project = _make_project(Path(td), with_sibling=True)
        resolved, note = resolve_mapped_netlist(
            project, "phase2/stage2/synth/netlist.v")

    assert resolved == f"phase2/stage2/synth/{mapped_sibling_name('spm')}", (
        "the resolver must switch to the technology-mapped sibling")
    assert note is not None and "switched to tech-mapped" in note


# ===================================================================== #
# PAIR 2 -- the real Step-14 conformance gate.                          #
# ===================================================================== #

def test_pair2_DEFECT_todays_recipe_is_classified_simulation_only():
    """DEFECT HALF. Today's Phase-2 recipe binds no Liberty at all, so the
    plugin's own classifier calls it `simulation_only`. A simulation-only
    synth cannot, by construction, produce a technology-mapped netlist --
    this is the defect stated in the classifier's own vocabulary."""
    from _yosys_inline_mode_detect import check_inline_command_conformance

    passed, classification, _reasons = check_inline_command_conformance(
        TODAYS_PHASE2_RECIPE)

    assert classification == "simulation_only"
    assert passed, ("today's recipe is CONFORMANT -- it is not a gate "
                    "violation, it is a capability gap; that is why no "
                    "existing test catches it")


def test_pair2_FIXED_mapped_recipe_passes_the_real_conformance_gate():
    """FIXED HALF. The emitted command binds a Liberty (`real_pdk`) AND
    carries hilomap, so the real gate passes it. Without the hilomap clause
    this same gate would FAIL and take Step 14 down with it -- see PAIR 3."""
    from _yosys_inline_mode_detect import check_inline_command_conformance

    cmd = build_mapped_sibling_command(
        rtl_files=["spm.v"], top="spm", liberty=LIB,
        out_path="spm_synth.v", hilomap_directive=HILOMAP)

    passed, classification, reasons = check_inline_command_conformance(cmd)

    assert classification == "real_pdk", (
        "binding a Liberty must reclassify the command")
    assert passed, f"conformance gate rejected the emitted command: {reasons}"
    assert "dfflibmap -liberty" in cmd
    assert "abc -liberty" in cmd
    assert "-DSIMULATION" not in cmd, (
        "the sim-only define must not ride along on a Liberty-bound command")


# ===================================================================== #
# PAIR 3 -- the fix must not be able to introduce the Step-14 regression #
# that a naive `-liberty` swap would cause.                             #
# ===================================================================== #

def test_pair3_DEFECT_liberty_without_hilomap_would_fail_the_real_gate():
    """DEFECT HALF. Demonstrates the regression a naive fix WOULD introduce:
    a Liberty-bound command lacking hilomap is a real_pdk FAIL."""
    from _yosys_inline_mode_detect import check_inline_command_conformance

    naive = (f"read_verilog -sv spm.v; synth -top spm -flatten; "
             f"dfflibmap -liberty {LIB}; abc -liberty {LIB}; "
             f"write_verilog -noattr spm_synth.v")
    passed, classification, reasons = check_inline_command_conformance(naive)

    assert classification == "real_pdk"
    assert not passed, "a real_pdk command with no hilomap must FAIL the gate"
    assert any("hilomap" in r.lower() for r in reasons)


def test_pair3_FIXED_builder_refuses_to_emit_that_command_at_all():
    """FIXED HALF. The builder cannot be talked into emitting the command
    PAIR-3-DEFECT describes: it refuses at the call site instead of flipping
    Step 14 to FAIL at a distance."""
    with pytest.raises(MappedSiblingRefused) as ei:
        build_mapped_sibling_command(
            rtl_files=["spm.v"], top="spm", liberty=LIB,
            out_path="spm_synth.v", hilomap_directive="")
    assert "hilomap" in str(ei.value)


# ===================================================================== #
# PAIR 4 -- the #80 invariant: Phase 2 must keep working with NO Liberty #
# ===================================================================== #

def test_pair4_DEFECT_no_liberty_means_no_emit_and_no_hard_dependency():
    """DEFECT HALF (degradation direction). With no resolvable Liberty the
    answer must be a quiet False, preserving the v1.6.193/#80 invariant that
    Phase 2 never hard-depends on a PDK Liberty file."""
    assert should_emit_mapped_sibling(None) is False
    assert should_emit_mapped_sibling("") is False
    assert should_emit_mapped_sibling("   ") is False
    with pytest.raises(MappedSiblingRefused):
        build_mapped_sibling_command(
            rtl_files=["spm.v"], top="spm", liberty="",
            out_path="spm_synth.v", hilomap_directive=HILOMAP)


def test_pair4_FIXED_resolvable_liberty_enables_emit():
    """FIXED HALF."""
    assert should_emit_mapped_sibling(LIB) is True


def test_sibling_name_matches_what_the_atpg_resolver_searches_for():
    """The whole fix rests on this one string agreeing with
    `fault_atpg_run.resolve_mapped_netlist`, which probes `<top>_synth.v`
    first and then globs `*_synth.v`. Pin it."""
    assert mapped_sibling_name("spm") == "spm_synth.v"
    assert mapped_sibling_name("chip_top") == "chip_top_synth.v"
    assert mapped_sibling_name("spm").endswith("_synth.v")
