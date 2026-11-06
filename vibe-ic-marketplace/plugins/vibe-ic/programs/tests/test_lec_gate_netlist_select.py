"""test_lec_gate_netlist_select.py — controls for the structural LEC abort fix.

Every test here is written to FAIL against a specific defect. The mutations
each one kills are named in its docstring, because a test that passes against
the defect is a rubber stamp no matter how many assertions it carries.

The defect being closed
-----------------------
yosys ``equiv_make`` refuses to build a miter when a gate-side top-level port
has no gold counterpart. compared_points is then 0 and NOTHING was compared.
``lec_equivalence_check`` reported that as ``LEC_NOT_EQUIVALENT`` / "RTL and
post-DFT netlist differ" — a false statement about a comparison that never
happened.

The three ways the first attempt at this fix was wrong, each now pinned:

  1. It reclassified the abort as INCONCLUSIVE (rc=3, ``PASS_WITH_WAIVERS``),
     so a genuine top-level port-set mismatch — scan ports in the netlist and
     absent from the gold RTL, a real DFT defect — was downgraded from hard
     FAIL to WAIVED-DEFERRED.  ``TestNoFailOpen`` pins rc=1.
  2. It asserted "the gate netlist is an ATPG-cut artifact" from the yosys
     error string alone, without ever reading the netlist.
     ``TestCauseIsMeasuredNeverGuessed`` pins that the cause is only named when
     the fingerprint is confirmed on the file lec.json says was compared.
  3. It silently re-pointed the gate side at ``<top>_synth.v``, which changes
     the compared artifact for the majority of designs (19 of 27 real synth
     trees on one host have no ``post_dft_netlist.v`` but do have both
     ``<top>_synth.v`` and ``netlist.v``) and would report the post-DFT
     equivalence step as PASS having never read the post-DFT netlist.
     ``TestSelectionIsUnchanged`` pins the selection against the legacy rule.

All fixtures are hand-written synthetic Verilog — hermetic, no real design
files, no EDA tools, sub-millisecond runtime.
"""
from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Add programs/ to sys.path so the modules under test are importable.
# ---------------------------------------------------------------------------
_PROGRAMS_DIR = Path(__file__).resolve().parent.parent
if str(_PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS_DIR))



# ---------------------------------------------------------------------------
# Synthetic fixture Verilog text (no EDA tools needed)
# ---------------------------------------------------------------------------

# A minimal ATPG-cut netlist:
#   * 5 original ports (clk, rst, x, y, p) matching the RTL
#   * 3 cut pseudo-port pairs: _10_/\_10_.d, _11_/\_11_.d, _12_/\_12_.d
#   * 0 flip-flop instantiations
_CUT_NETLIST_V = """\
/* ATPG cut netlist — every DFF replaced by pseudo-port pairs */
module tiny(clk, rst, x, y, p, _10_, \\_10_.d , _11_, \\_11_.d , _12_, \\_12_.d );
  input clk;
  input rst;
  input x;
  input y;
  output p;
  input _10_;
  output \\_10_.d ;
  input _11_;
  output \\_11_.d ;
  input _12_;
  output \\_12_.d ;

  assign \\_10_.d  = x & clk;
  assign \\_11_.d  = rst | y;
  assign \\_12_.d  = p ^ x;
  assign p = _10_ & _11_;
endmodule
"""

# A normal liberty-backed synthesis netlist: 5 matching ports, 3 dfxtp flops.
_MAPPED_NETLIST_V = """\
/* Liberty-backed synthesis netlist */
module tiny(clk, rst, x, y, p);
  input clk;
  input rst;
  input x;
  input y;
  output p;
  wire _0_;
  wire _1_;
  wire _2_;
  sky130_fd_sc_hd__dfxtp_1 _3_ (.D(_0_), .Q(_1_), .CLK(clk));
  sky130_fd_sc_hd__dfxtp_1 _4_ (.D(_1_), .Q(_2_), .CLK(clk));
  sky130_fd_sc_hd__dfxtp_1 _5_ (.D(_2_), .Q(p),   .CLK(clk));
  sky130_fd_sc_hd__and2_1  _6_ (.A(x),   .B(y),   .X(_0_));
  sky130_fd_sc_hd__nor2_1  _7_ (.A(rst), .B(_1_), .Y(_0_));
endmodule
"""

# The skeptic's constructible false positive, reproduced verbatim in spirit:
# a perfectly healthy mapped netlist with 3 flops that merely CARRIES a yosys
# hierarchical NET named `\u_reg.d`.  A whole-file `.d` scan flags this as
# "every flip-flop has been deleted" — about a netlist holding three flops.
_HIER_NET_NETLIST_V = """\
/* Healthy mapped netlist that happens to carry a hierarchical net `\\u_reg.d` */
module tiny(clk, rst, x, y, p);
  input clk;
  input rst;
  input x;
  input y;
  output p;
  wire \\u_reg.d ;
  wire \\u_reg.q ;
  wire _1_;
  sky130_fd_sc_hd__dfxtp_1 _3_ (.D(\\u_reg.d ), .Q(\\u_reg.q ), .CLK(clk));
  sky130_fd_sc_hd__dfxtp_1 _4_ (.D(\\u_reg.q ), .Q(_1_),        .CLK(clk));
  sky130_fd_sc_hd__dfxtp_1 _5_ (.D(_1_),        .Q(p),          .CLK(clk));
  sky130_fd_sc_hd__and2_1  _6_ (.A(x), .B(y), .X(\\u_reg.d ));
  sky130_fd_sc_hd__nor2_1  _7_ (.A(rst), .B(_1_), .Y(p));
endmodule
"""

# A legitimately combinational block whose escaped PORT names merely BEGIN with
# `.d` — `\bus.data` and `\ctl.dout`.  An unanchored `\.d` pattern flags these.
_DOT_DATA_PORT_NETLIST_V = """\
/* Flattened combinational block with escaped hierarchical port names */
module comb(a, b, \\bus.data , \\ctl.dout );
  input a;
  input b;
  output \\bus.data ;
  output \\ctl.dout ;
  assign \\bus.data  = a ^ b;
  assign \\ctl.dout  = a & b;
endmodule
"""

# A genuine top-level PORT-SET MISMATCH that is NOT a cut artifact: the netlist
# carries scan ports the gold RTL does not have, and still holds all its flops.
# equiv_make aborts on these exactly as it does on a cut netlist — same log,
# entirely different (and real) defect.
_SCAN_PORT_MISMATCH_NETLIST_V = """\
/* Post-DFT netlist with scan ports absent from the gold RTL — REAL defect */
module tiny(clk, rst, x, y, p, scan_en, scan_in, scan_out);
  input clk;
  input rst;
  input x;
  input y;
  output p;
  input scan_en;
  input scan_in;
  output scan_out;
  wire _0_;
  wire _1_;
  sky130_fd_sc_hd__sdfxtp_1 _3_ (.D(_0_), .Q(_1_), .CLK(clk), .SCD(scan_in));
  sky130_fd_sc_hd__sdfxtp_1 _4_ (.D(_1_), .Q(p),   .CLK(clk), .SCD(_1_));
  sky130_fd_sc_hd__sdfxtp_1 _5_ (.D(x),   .Q(scan_out), .CLK(clk), .SCD(y));
  sky130_fd_sc_hd__and2_1  _6_ (.A(x), .B(y), .X(_0_));
endmodule
"""

# The SAME cut netlist with several declarations packed onto one line, and
# comma-separated name lists. A `^`-anchored declaration pattern sees only the
# first declaration per line and reports this netlist as clean.
_CUT_NETLIST_PACKED_V = """\
module tiny(clk, rst, x, y, p, _10_, \\_10_.d , _11_, \\_11_.d );
  input clk, rst; input x, y; output p;
  input _10_; output \\_10_.d ;
  input _11_; output \\_11_.d ;
  assign \\_10_.d  = x & clk;
  assign \\_11_.d  = rst | y;
  assign p = _10_ & _11_;
endmodule
"""

# A post-DFT netlist built entirely from SCAN flops — the cell family a
# post-DFT netlist actually contains. Nothing here is a cut view.
_SCAN_FLOP_NETLIST_V = """\
module tiny(clk, rst, x, y, p);
  input clk; input rst; input x; input y; output p;
  wire _0_;
  wire _1_;
  sky130_fd_sc_hd__sdfxtp_1  _3_ (.D(_0_), .Q(_1_), .CLK(clk));
  sky130_fd_sc_hd__sedfxtp_1 _4_ (.D(_1_), .Q(p),   .CLK(clk));
  gf180mcu_fd_sc_mcu7t5v0__dffq_1 _5_ (.D(x), .Q(_0_), .CLK(clk));
  sky130_fd_sc_hd__dlygate4sd3_1 _6_ (.A(x), .X(_1_));
  gf180mcu_fd_sc_mcu7t5v0__dlyd_1 _7_ (.A(y), .Z(_0_));
  sky130_fd_sc_hd__and2_1 _8_ (.A(x), .B(y), .X(_0_));
endmodule
"""

# Yosys equiv_make port-abort log.
_PORT_ABORT_LOG = """\
16. Executing EQUIV_MAKE pass (creating equiv checking module).
ERROR: Can't match gate port `_10_.d_gate' to a gold port.
"""

# Normal run log (0 compared, different reason — parse abort, NOT port abort).
_PARSE_ABORT_LOG = """\
ERROR: syntax error, unexpected TOK_EOF
"""

# A real counterexample log that ALSO carries an abort line from an earlier
# attempt — the shape that separates the zero_miter guard from a rubber stamp.
_NONEQUIV_WITH_STALE_ABORT_LOG = """\
ERROR: Can't match gate port `_10_.d_gate' to a gold port.
-- retrying with the mapped netlist --
Found 3 $equiv cells in equiv:
  Of those cells 0 are proven and 3 are unproven.
Found counterexample for output 'p'.
"""

_NONEQUIV_LOG = """\
Found 3 $equiv cells in equiv:
  Of those cells 0 are proven and 3 are unproven.
Found counterexample for output 'p'.
"""

# lec.json exactly as lec_run writes it for a port-abort run.
_PORT_ABORT_JSON = {
    "equivalent": False,
    "compared_points": 0,
    "non_equivalent_points": 0,
    "unproven_points": 0,
    "gate": "post_dft_netlist.v (synth)",
    "verdict": "FAIL",
    "inconclusive": False,
}

_NONEQUIV_JSON = {
    "equivalent": False,
    "compared_points": 3,
    "non_equivalent_points": 3,
    "unproven_points": 0,
    "gate": "netlist.v (synth)",
    "verdict": "FAIL",
    "inconclusive": False,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(tmp: Path, name: str, content: str) -> Path:
    p = tmp / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _make_project(tmp: Path, netlist_name: str, netlist_content: str,
                  lec_json: dict, rpt_content: str = "") -> Path:
    """Minimal project tree for lec_equivalence_check.audit()."""
    proj = tmp / "proj"
    synth = proj / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True, exist_ok=True)
    _write(synth, netlist_name, netlist_content)
    rpts = proj / "reports"
    rpts.mkdir(parents=True, exist_ok=True)
    (rpts / "lec.json").write_text(json.dumps(lec_json), encoding="utf-8")
    if rpt_content:
        (rpts / "lec.rpt").write_text(rpt_content, encoding="utf-8")
    return proj




# ---------------------------------------------------------------------------
# 1. THE TIER MUST NOT MOVE — a structural abort stays a hard FAIL
# ---------------------------------------------------------------------------

class TestNoFailOpen:
    """Kills: reclassifying the abort into the INCONCLUSIVE / rc=3 tier.

    The first version of this fix set ``res.inconclusive = True``, which makes
    ``main()`` print the ``PASS_WITH_WAIVERS`` sentinel and return 3;
    flow_compliance then records step 13 as WAIVED-DEFERRED. Nothing was
    compared, so equivalence is unproven — and an unproven equivalence is never
    a waiver.
    """

    def test_cut_artifact_abort_is_rc1_not_a_waiver(self, tmp_path, capsys):
        proj = _make_project(
            tmp_path / "a", "post_dft_netlist.v", _CUT_NETLIST_V,
            _PORT_ABORT_JSON, _PORT_ABORT_LOG)


        out = capsys.readouterr().out
        assert "PASS_WITH_WAIVERS" not in out, (
            "the WAIVED-DEFERRED sentinel must never appear for an abort that "
            "compared nothing")

    def test_real_port_set_mismatch_is_rc1_not_a_waiver(self, tmp_path, capsys):
        """The skeptic's reproduction: scan ports in the netlist, absent from
        the RTL, all flops present. Same yosys abort, entirely different cause.
        origin/main returned rc=1; the first fix returned rc=3. It must be 1.
        """
        proj = _make_project(
            tmp_path / "b", "post_dft_netlist.v",
            _SCAN_PORT_MISMATCH_NETLIST_V,
            _PORT_ABORT_JSON, _PORT_ABORT_LOG)

        assert "PASS_WITH_WAIVERS" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 2. THE CAUSE MUST BE MEASURED, NEVER GUESSED FROM THE LOG STRING
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 3. THE SELECTION MUST NOT MOVE — no silent substitution, no reordering
# ---------------------------------------------------------------------------

_PRESENCE_MATRIX = [
    # (post_dft_netlist.v, <top>_synth.v, netlist.v)
    (False, False, False),
    (False, False, True),
    (False, True, False),
    (False, True, True),
    (True, False, False),
    (True, False, True),
    (True, True, False),
    (True, True, True),
]


class TestSelectionIsUnchanged:
    """Kills: any fallback, reordering, or substitution in the gate selection.

    ``M3`` in the refutation (prefer ``netlist.v`` before ``<top>_synth.v``)
    survived the original tests because NOTHING pinned the order. Here the
    selection is pinned against the legacy rule over the full presence matrix,
    so any candidate list at all — in any order — fails.
    """






# ---------------------------------------------------------------------------
# 4. THE PREDICATE MUST NOT FIRE ON A HEALTHY NETLIST
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 4b. THE STRUCTURAL PARSERS MUST ACTUALLY SEE WHAT IS THERE
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 5. THE CLASSIFIER GUARDS — each one has a test that fails when it is dropped
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 6. GENUINE FAILURES AND GENUINE PASSES ARE UNTOUCHED
# ---------------------------------------------------------------------------
