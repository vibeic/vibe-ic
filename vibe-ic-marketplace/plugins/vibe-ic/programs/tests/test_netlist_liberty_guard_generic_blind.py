#!/usr/bin/env python3
"""BIDIRECTIONAL tests: `_netlist_matches_liberty` must reject an UNMAPPED netlist.

The guard's own docstring states its purpose:

    "A single unknown master => the netlist was mapped to a DIFFERENT PDK and
     must NOT be reused -- preserve-provenance must never launder a wrong-PDK
     netlist into a PASS."

Its master regex requires a master name to start with ``[A-Za-z_]``, so a yosys
generic primitive (``$_NAND_``, ``$_DFF_P_``) never matches. On a netlist mapped
to NO PDK the sample came back empty and fell into the ``if not masters:
return True`` legacy-trust arm -- "safe to reuse" for the one netlist that most
needed rejecting.

MEASURED on cell `spm` x `sky130A` (plugin 1.6.4):
    _netlist_matches_liberty("phase2/stage2/synth/netlist.v",
                             ".../sky130_fd_sc_hd__tt_025C_1v80.lib") -> True
on a file holding 179 $_NAND_ / 117 $_NOR_ / 90 $_NOT_ / 33 $_DFF_P_ and zero
sky130 cells.

Each test is one half of a pair; the DEFECT half fails when the fix is reverted.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3  # noqa: E402

# Minimal liberty holding exactly the cells the MAPPED fixture instantiates.
LIBERTY_TEXT = """\
library (sky130_fd_sc_hd__tt_025C_1v80) {
  cell (sky130_fd_sc_hd__nand2_1) { area : 3.75; }
  cell (sky130_fd_sc_hd__nor2_1)  { area : 3.75; }
  cell (sky130_fd_sc_hd__dfxtp_1) { area : 20.0; }
}
"""

GENERIC_NETLIST = """\
module spm(clk, rst, x, y, p);
  input clk;
  wire _n0_, _n1_;
  $_NAND_ _100_ (.A(x[0]), .B(y), .Y(_n0_));
  $_NOR_  _101_ (.A(_n0_), .B(rst), .Y(_n1_));
  $_DFF_P_ _102_ (.C(clk), .D(_n1_), .Q(p));
endmodule
"""

MAPPED_NETLIST = """\
module spm(clk, rst, x, y, p);
  input clk;
  wire _n0_, _n1_;
  sky130_fd_sc_hd__nand2_1 _100_ (.A(x[0]), .B(y), .Y(_n0_));
  sky130_fd_sc_hd__nor2_1  _101_ (.A(_n0_), .B(rst), .Y(_n1_));
  sky130_fd_sc_hd__dfxtp_1 _102_ (.CLK(clk), .D(_n1_), .Q(p));
endmodule
"""

# Mapped to a DIFFERENT PDK -- the case the guard already caught. Pinned so the
# fix cannot be mistaken for the reason this one is rejected.
WRONG_PDK_NETLIST = """\
module spm(clk, rst, x, y, p);
  input clk;
  gf180mcu_fd_sc_mcu7t5v0__nand2_1 _100_ (.A1(x[0]), .A2(y), .ZN(_n0_));
  gf180mcu_fd_sc_mcu7t5v0__dffq_1  _102_ (.CLK(clk), .D(_n0_), .Q(p));
endmodule
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def test_DEFECT_unmapped_netlist_must_not_be_reported_reusable(tmp_path):
    """DEFECT HALF. This is the assertion the shipped guard FAILS: a netlist
    with zero library cells is reported reusable. It passes only with the fix."""
    nl = _write(tmp_path, "netlist.v", GENERIC_NETLIST)
    lib = _write(tmp_path, "lib.lib", LIBERTY_TEXT)
    assert p3._netlist_matches_liberty(nl, str(lib)) is False, (
        "a technology-UNMAPPED netlist is a strictly worse reuse candidate "
        "than a wrong-PDK one and must be rejected")


def test_FIXED_liberty_mapped_netlist_is_still_reusable(tmp_path):
    """FIXED HALF. The fix must not make the guard reject everything: a netlist
    whose masters all exist in the liberty is still reusable."""
    nl = _write(tmp_path, "spm_synth.v", MAPPED_NETLIST)
    lib = _write(tmp_path, "lib.lib", LIBERTY_TEXT)
    assert p3._netlist_matches_liberty(nl, str(lib)) is True


def test_wrong_pdk_netlist_still_rejected_for_the_original_reason(tmp_path):
    """Regression pin: the behaviour that already worked keeps working, and is
    rejected by the MASTER-SAMPLING arm, not by the new generic check."""
    nl = _write(tmp_path, "other.v", WRONG_PDK_NETLIST)
    lib = _write(tmp_path, "lib.lib", LIBERTY_TEXT)
    assert p3._netlist_matches_liberty(nl, str(lib)) is False
    assert not p3._GENERIC_PRIM_MASTER_RE.search(WRONG_PDK_NETLIST), (
        "the wrong-PDK fixture must contain no generic primitive, so its "
        "rejection is attributable to master sampling alone")


def test_legacy_trust_arms_are_preserved(tmp_path):
    """The fix must not disturb the documented legacy-trust behaviour on
    unreadable/absent inputs or an empty liberty."""
    lib = _write(tmp_path, "lib.lib", LIBERTY_TEXT)
    assert p3._netlist_matches_liberty(tmp_path / "absent.v", str(lib)) is True
    nl = _write(tmp_path, "mapped.v", MAPPED_NETLIST)
    assert p3._netlist_matches_liberty(nl, "") is True
    empty_lib = _write(tmp_path, "empty.lib", "")
    assert p3._netlist_matches_liberty(nl, str(empty_lib)) is True


def test_generic_regex_does_not_trip_on_comments_or_net_names(tmp_path):
    """The generic detector is anchored to an INSTANCE line, so a `$_` inside a
    comment or a net name must not cause a false rejection."""
    text = MAPPED_NETLIST.replace(
        "  wire _n0_, _n1_;",
        "  wire _n0_, _n1_;\n  // legacy note: was $_NAND_ before remap\n"
        "  wire \\$_not_a_cell_ ;")
    nl = _write(tmp_path, "commented.v", text)
    lib = _write(tmp_path, "lib.lib", LIBERTY_TEXT)
    assert p3._netlist_matches_liberty(nl, str(lib)) is True
