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

import lec_gate_netlist_select as _gns
from lec_gate_netlist_select import (
    is_atpg_cut_artifact,
    gate_netlist_for_lec,
    legacy_gate_netlist_rel,
    classify_port_abort,
    port_abort_cause,
    cut_pseudo_ports,
    CANONICAL_STATUS,
    CANONICAL_VERDICT,
)
import lec_equivalence_check as _lec


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


def _rc(proj: Path) -> int:
    """Run the CLI the flow gate runs (`program_exit_zero`) and return rc."""
    return _lec.main([str(proj)])


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

        res = _lec.audit(proj)
        assert res.passed is False
        assert res.inconclusive is False, (
            "a structural abort must NOT enter the INCONCLUSIVE tier — that "
            "routes step 13 to rc=3 / WAIVED-DEFERRED")
        assert {f.severity for f in res.findings} == {"ERROR"}

        assert _rc(proj) == 1, "must stay a hard FAIL (rc=1)"
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

        res = _lec.audit(proj)
        assert res.passed is False
        assert res.inconclusive is False
        assert _rc(proj) == 1
        assert "PASS_WITH_WAIVERS" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 2. THE CAUSE MUST BE MEASURED, NEVER GUESSED FROM THE LOG STRING
# ---------------------------------------------------------------------------

class TestCauseIsMeasuredNeverGuessed:
    """Kills: naming the ATPG-cut cause from the yosys error text alone.

    A mutation that makes ``port_abort_cause`` return ``(True, ...)``
    unconditionally, or that drops the ``is_atpg_cut_artifact`` confirmation,
    fails ``test_unconfirmed_cause_is_not_asserted``.
    """

    def test_confirmed_cut_names_the_cut_and_the_upstream_producer(self, tmp_path):
        proj = _make_project(
            tmp_path / "a", "post_dft_netlist.v", _CUT_NETLIST_V,
            _PORT_ABORT_JSON, _PORT_ABORT_LOG)
        res = _lec.audit(proj)
        rules = [f.rule for f in res.findings]
        assert CANONICAL_STATUS in rules, f"got rules={rules}"
        assert "LEC_NOT_EQUIVALENT" not in rules, (
            "'RTL and post-DFT netlist differ' is false when nothing was "
            f"compared; rules={rules}")
        msg = [f.message for f in res.findings if f.rule == CANONICAL_STATUS][0]
        assert "fault_atpg_run.py" in msg, (
            "a confirmed cut artifact must name the upstream producer so the "
            "next agent fixes the byte-copy, not the design")
        assert "post_dft_netlist.v" in msg

    def test_unconfirmed_cause_is_not_asserted(self, tmp_path):
        """Netlist has scan ports and all its flops — NOT a cut artifact.

        The finding must still fire (nothing was compared) but it must NOT
        claim the flip-flops were deleted.
        """
        proj = _make_project(
            tmp_path / "b", "post_dft_netlist.v",
            _SCAN_PORT_MISMATCH_NETLIST_V,
            _PORT_ABORT_JSON, _PORT_ABORT_LOG)
        res = _lec.audit(proj)
        rules = [f.rule for f in res.findings]
        assert CANONICAL_STATUS in rules, f"got rules={rules}"
        msg = [f.message for f in res.findings if f.rule == CANONICAL_STATUS][0]
        assert "unconfirmed" in msg.lower(), (
            "with no cut fingerprint on the compared netlist the cause must be "
            f"declared unconfirmed, not guessed; message={msg!r}")
        assert "fault_atpg_run.py" not in msg, (
            "must not blame the ATPG byte-copy for a netlist that still holds "
            f"its flip-flops; message={msg!r}")
        assert "scan" in msg.lower(), (
            "the message must point at the real diagnostic step (diff the "
            "top-level port sets) instead of a fabricated cause")

    def test_port_abort_cause_requires_the_named_file_to_exist(self, tmp_path):
        proj = tmp_path / "p"
        (proj / "phase2" / "stage2" / "synth").mkdir(parents=True)
        ok, ev = port_abort_cause(proj, "post_dft_netlist.v (synth)")
        assert ok is False and ev == ""

    def test_port_abort_cause_ignores_a_non_netlist_gate_field(self, tmp_path):
        proj = tmp_path / "p"
        synth = proj / "phase2" / "stage2" / "synth"
        synth.mkdir(parents=True)
        (synth / "post_dft_netlist.v").write_text(_CUT_NETLIST_V)
        assert port_abort_cause(proj, "") == (False, "")
        assert port_abort_cause(proj, "unknown") == (False, "")


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

    @pytest.mark.parametrize("have_post_dft,have_top_synth,have_netlist",
                             _PRESENCE_MATRIX)
    def test_matches_legacy_rule_on_every_presence_combination(
            self, tmp_path, have_post_dft, have_top_synth, have_netlist):
        synth = tmp_path / "phase2" / "stage2" / "synth"
        synth.mkdir(parents=True)
        if have_post_dft:
            (synth / "post_dft_netlist.v").write_text(_MAPPED_NETLIST_V)
        if have_top_synth:
            (synth / "tiny_synth.v").write_text(_MAPPED_NETLIST_V)
        if have_netlist:
            (synth / "netlist.v").write_text(_MAPPED_NETLIST_V)

        # The rule the runner used before this capture existed, verbatim.
        expected = ("phase2/stage2/synth/post_dft_netlist.v"
                    if (synth / "post_dft_netlist.v").is_file()
                    else "phase2/stage2/synth/netlist.v")

        rel, _note, _is_cut = gate_netlist_for_lec(tmp_path, "tiny")
        assert rel == expected, (
            f"gate selection drifted from the legacy rule "
            f"(post_dft={have_post_dft}, top_synth={have_top_synth}, "
            f"netlist={have_netlist}): expected {expected}, got {rel}")
        assert legacy_gate_netlist_rel(tmp_path) == expected

    def test_a_cut_post_dft_is_still_selected_and_flagged(self, tmp_path):
        """The load-bearing one: a CUT post_dft_netlist.v must still be the
        compared artifact.

        Substituting ``tiny_synth.v`` here is exactly the refuted behaviour —
        it makes the step named `13_equivalence_check_rtl_post_dft_netlist`
        report PASS having never read the post-DFT netlist, and leaves the
        upstream byte-copy unflagged.
        """
        synth = tmp_path / "phase2" / "stage2" / "synth"
        synth.mkdir(parents=True)
        (synth / "post_dft_netlist.v").write_text(_CUT_NETLIST_V)
        (synth / "tiny_synth.v").write_text(_MAPPED_NETLIST_V)
        (synth / "netlist.v").write_text(_MAPPED_NETLIST_V)

        rel, note, is_cut = gate_netlist_for_lec(tmp_path, "tiny")
        assert rel == "phase2/stage2/synth/post_dft_netlist.v", (
            f"must NOT substitute a different netlist; got {rel}")
        assert is_cut is True
        assert "UNUSABLE" in note and "fault_atpg_run.py" in note

    def test_top_name_cannot_influence_the_selection(self, tmp_path):
        synth = tmp_path / "phase2" / "stage2" / "synth"
        synth.mkdir(parents=True)
        (synth / "tiny_synth.v").write_text(_MAPPED_NETLIST_V)
        (synth / "netlist.v").write_text(_MAPPED_NETLIST_V)
        for top in ("tiny", "other", ""):
            rel, _n, _c = gate_netlist_for_lec(tmp_path, top)
            assert rel == "phase2/stage2/synth/netlist.v", (
                f"top_name={top!r} changed the selection to {rel}")

    def test_runner_delegates_and_keeps_no_selection_logic_of_its_own(self):
        """The runner must not carry a second copy of this decision.

        The refuted version computed a 'reference context' by running the
        liberty-cell regex over the RTL — a number that is meaningless (0 for
        one real design, 1 for a core holding 1272 flops) — by deep-importing
        private helpers. Reverting the runner alone was invisible to the whole
        original suite; this makes it visible.
        """
        import design_one_shot_runner as _runner
        src = inspect.getsource(_runner.step_dft_lec_chain)
        # Comments explain the decision; only executable lines are pinned.
        code = "\n".join(re.sub(r"#.*$", "", ln) for ln in src.splitlines())
        assert "_lec_gns.gate_netlist_for_lec(" in code, (
            "step_dft_lec_chain must delegate the gate selection")
        assert "_count_ff_cells" not in code and "_extract_ports" not in code, (
            "the runner must not deep-import private predicate helpers to "
            "rebuild a reference context")
        assert "_synth.v" not in code, (
            "the runner must not name a <top>_synth.v fallback")
        # The delegated call must be the ONLY source of gate_netlist: no local
        # re-derivation, and no `gate_netlist = <path expression>` anywhere.
        direct = [ln for ln in code.splitlines()
                  if re.match(r"\s*gate_netlist\s*=(?!=)", ln)]
        assert not direct, (
            f"gate_netlist must come from the delegated tuple unpack, not a "
            f"local re-derivation; found {direct}")
        unpack = [ln for ln in code.splitlines()
                  if re.match(r"\s*gate_netlist\s*,", ln)]
        assert len(unpack) == 1, (
            f"expected exactly one delegated selection site; found {unpack}")


# ---------------------------------------------------------------------------
# 4. THE PREDICATE MUST NOT FIRE ON A HEALTHY NETLIST
# ---------------------------------------------------------------------------

class TestPredicateFalsePositives:
    """Kills: M4 (unanchored `.d`) and the whole-file `.d` scan.

    Both mutations put "every flip-flop has been deleted" into a sign-off
    report about a netlist that holds all of its flip-flops.
    """

    def test_flags_the_real_cut_netlist(self, tmp_path):
        nf = _write(tmp_path, "post_dft_netlist.v", _CUT_NETLIST_V)
        is_cut, reason = is_atpg_cut_artifact(nf)
        assert is_cut, f"cut netlist must be flagged; reason={reason!r}"
        assert "pseudo-port" in reason and "0 sequential cells" in reason

    def test_hierarchical_net_named_dot_d_is_not_a_cut_artifact(self, tmp_path):
        """The skeptic's constructible false positive.

        `\\u_reg.d` here is a NET, not a port, and the netlist holds 3 flops.
        A whole-file scan reports '3 <inst>.d pseudo-port(s) ... every
        flip-flop has been deleted'.
        """
        nf = _write(tmp_path, "netlist.v", _HIER_NET_NETLIST_V)
        is_cut, reason = is_atpg_cut_artifact(nf)
        assert not is_cut, (
            f"a hierarchical NET named `.d` in a netlist with flops must not "
            f"be read as a deleted-flop pseudo-port; reason={reason!r}")
        assert cut_pseudo_ports(_HIER_NET_NETLIST_V) == set()

    def test_escaped_ports_beginning_with_dot_d_are_not_cut_ports(self, tmp_path):
        """M4: dropping the end-anchor from the `.d` pattern.

        `\\bus.data` and `\\ctl.dout` are legitimate escaped port names in a
        genuinely combinational block — 0 flops, so the FF corroboration does
        not save us here. Only the anchor does.
        """
        nf = _write(tmp_path, "netlist.v", _DOT_DATA_PORT_NETLIST_V)
        is_cut, reason = is_atpg_cut_artifact(nf)
        assert not is_cut, (
            f"`.data` / `.dout` ports are not `<inst>.d` pseudo-ports; "
            f"reason={reason!r}")
        assert cut_pseudo_ports(_DOT_DATA_PORT_NETLIST_V) == set()

    def test_normal_mapped_netlist_is_not_flagged(self, tmp_path):
        nf = _write(tmp_path, "netlist.v", _MAPPED_NETLIST_V)
        assert is_atpg_cut_artifact(nf)[0] is False

    def test_pure_combinational_design_is_not_flagged(self, tmp_path):
        nf = _write(tmp_path, "netlist.v", """\
module comb(a, b, y);
  input a; input b; output y;
  assign y = a ^ b;
endmodule
""")
        assert is_atpg_cut_artifact(nf)[0] is False

    def test_scan_port_mismatch_netlist_is_not_flagged(self, tmp_path):
        nf = _write(tmp_path, "post_dft_netlist.v",
                    _SCAN_PORT_MISMATCH_NETLIST_V)
        is_cut, reason = is_atpg_cut_artifact(nf)
        assert not is_cut, (
            f"a real port-set mismatch is not a cut artifact; reason={reason!r}")

    def test_cut_ports_plus_surviving_flops_is_not_a_cut_view(self, tmp_path):
        """The FF corroboration, pinned. A netlist that has BOTH a `.d` port
        and flops has not had its flops deleted, whatever the port is called.
        """
        mixed = _CUT_NETLIST_V.replace(
            "  assign p = _10_ & _11_;",
            "  sky130_fd_sc_hd__dfxtp_1 _9_ (.D(x), .Q(p), .CLK(clk));")
        nf = _write(tmp_path, "netlist.v", mixed)
        assert is_atpg_cut_artifact(nf)[0] is False

    def test_missing_file_is_not_flagged(self, tmp_path):
        assert is_atpg_cut_artifact(tmp_path / "nope.v") == (False, "")


# ---------------------------------------------------------------------------
# 4b. THE STRUCTURAL PARSERS MUST ACTUALLY SEE WHAT IS THERE
# ---------------------------------------------------------------------------

class TestStructuralParsers:
    """Kills: a predicate that is silently a no-op on real netlists.

    Both defects here were found by running the predicate against a
    hand-built reproduction of the real artifact rather than against the
    synthetic fixture it was written from. Both made the predicate return
    "clean" — the same class of failure as the refuted "reference context",
    which computed a flip-flop count of 1 for a core holding 1272 flops.
    """

    def test_packed_declarations_on_one_line_are_all_seen(self, tmp_path):
        """`input _10_; output \\_10_.d ;` on ONE line.

        A declaration pattern anchored at `^` sees only the first declaration
        per line, so every `.d` pseudo-port after it is invisible and the cut
        netlist reads as clean.
        """
        assert cut_pseudo_ports(_CUT_NETLIST_PACKED_V) == {"_10_.d", "_11_.d"}
        nf = _write(tmp_path, "post_dft_netlist.v", _CUT_NETLIST_PACKED_V)
        assert is_atpg_cut_artifact(nf)[0] is True

    def test_comma_separated_names_are_all_seen(self):
        ports = _gns._extract_ports(_CUT_NETLIST_PACKED_V)
        assert {"clk", "rst", "x", "y", "p"} <= ports, sorted(ports)

    @pytest.mark.parametrize("cell", [
        "sky130_fd_sc_hd__dfxtp_1",
        "sky130_fd_sc_hd__sdfxtp_1",      # SCAN flop — a post-DFT netlist is
        "sky130_fd_sc_hd__sedfxtp_1",     # made of these
        "sky130_fd_sc_hd__edfxtp_1",
        "sky130_fd_sc_hd__dfrtp_2",
        "gf180mcu_fd_sc_mcu7t5v0__dffq_1",
        "gf180mcu_fd_sc_mcu7t5v0__sdffq_1",
        "sky130_fd_sc_hd__dlxtp_1",
        "$_DFF_P_", "$_SDFFE_PP0P_", "$_ALDFF_PP_", "$_DLATCH_P_",
        "$dff", "$adff", "$aldff",
    ])
    def test_state_elements_are_recognised(self, cell):
        assert _gns._is_ff_type(cell), (
            f"{cell} holds state; missing it hollows out the corroboration "
            "exactly on post-DFT netlists")

    @pytest.mark.parametrize("cell", [
        "sky130_fd_sc_hd__and2_1", "sky130_fd_sc_hd__nor2_1",
        "sky130_fd_sc_hd__buf_4", "sky130_fd_sc_hd__conb_1",
        "sky130_fd_sc_hd__decap_3", "sky130_fd_sc_hd__diode_2",
        "sky130_fd_sc_hd__fill_1",
        "sky130_fd_sc_hd__dlygate4sd3_1",   # `dl` prefix, holds no state
        "gf180mcu_fd_sc_mcu7t5v0__dlyd_1",
    ])
    def test_combinational_and_delay_cells_are_not_state(self, cell):
        assert not _gns._is_ff_type(cell)

    def test_scan_flop_netlist_counts_its_flops(self, tmp_path):
        nf = _write(tmp_path, "post_dft_netlist.v", _SCAN_FLOP_NETLIST_V)
        assert _gns._count_ff_cells(_gns._read_safe(nf)) == 3
        assert is_atpg_cut_artifact(nf)[0] is False

    def test_pin_connections_named_input_are_not_ports(self):
        """`.input(...)` is a PIN CONNECTION and `\\input` an escaped net name.

        Treating either as a port declaration would sweep the connected net
        names into the port set, where one ending in `.d` becomes a phantom
        cut pseudo-port.
        """
        src = """\
module comb(a, b, y);
  input a; input b; output y;
  wire \\input ;
  some_macro _1_ (.input(a), .output(\\bus.d ), .Y(y));
  assign y = a & b;
endmodule
"""
        ports = _gns._extract_ports(src)
        assert ports == {"a", "b", "y"}, sorted(ports)
        assert cut_pseudo_ports(src) == set()

    def test_port_connections_are_not_read_as_cell_types(self):
        """`.D(\\u_reg.d )` is a NET reference inside a connection list.

        Counting the whole line would let a net name decide the cell type.
        """
        line = "  sky130_fd_sc_hd__and2_1 _6_ (.A(x), .B(\\u_reg.dff ), .X(y));\n"
        assert _gns._count_ff_cells(line) == 0


# ---------------------------------------------------------------------------
# 5. THE CLASSIFIER GUARDS — each one has a test that fails when it is dropped
# ---------------------------------------------------------------------------

class TestClassifierGuards:
    """Kills: M5 (dropping the ``zero_miter`` guard) and dropping the
    ``compared_points != 0`` guard inside ``classify_port_abort``.

    Each guard is pinned at the level where it is the ONLY thing standing:
    the compared>0 guard at the unit level, the zero_miter guard at the audit
    level with a run that compared 0 points but recorded a counterexample.
    """

    def test_returns_the_structural_verdict_for_the_abort_log(self):
        assert classify_port_abort(_PORT_ABORT_LOG, 0) == CANONICAL_VERDICT

    def test_returns_none_for_a_non_port_abort_log(self):
        assert classify_port_abort(_PARSE_ABORT_LOG, 0) is None

    def test_returns_none_when_points_were_compared(self):
        assert classify_port_abort(_PORT_ABORT_LOG, 5) is None

    def test_counterexample_wins_over_a_stale_abort_line(self, tmp_path):
        """M5: the ``zero_miter`` guard is not redundant.

        compared_points==0 AND the abort signature is in the log — the two
        conditions ``classify_port_abort`` checks — but the run also recorded 3
        non-equivalent points. That is a real mismatch and must keep the
        mismatch verdict.
        """
        proj = _make_project(
            tmp_path / "a", "netlist.v", _MAPPED_NETLIST_V,
            {"equivalent": False, "compared_points": 0,
             "non_equivalent_points": 3, "unproven_points": 0,
             "gate": "netlist.v (synth)", "verdict": "FAIL",
             "inconclusive": False},
            _NONEQUIV_WITH_STALE_ABORT_LOG)

        res = _lec.audit(proj)
        rules = {f.rule for f in res.findings}
        assert "LEC_NOT_EQUIVALENT" in rules, (
            f"a recorded counterexample must not be relabelled a structural "
            f"abort; rules={sorted(rules)}")
        assert "LEC_NONEQUIV_POINTS" in rules
        assert CANONICAL_STATUS not in rules
        assert _rc(proj) == 1


# ---------------------------------------------------------------------------
# 6. GENUINE FAILURES AND GENUINE PASSES ARE UNTOUCHED
# ---------------------------------------------------------------------------

class TestNoOverreach:
    """Kills: suppressing real non-equivalence, or inventing a new pass."""

    def test_genuine_nonequivalence_still_fails_hard(self, tmp_path):
        proj = _make_project(
            tmp_path / "c", "netlist.v", _MAPPED_NETLIST_V,
            _NONEQUIV_JSON, _NONEQUIV_LOG)
        res = _lec.audit(proj)
        rules = {f.rule for f in res.findings}
        assert "LEC_NOT_EQUIVALENT" in rules
        assert res.passed is False and res.inconclusive is False
        assert _rc(proj) == 1

    def test_equivalent_false_without_any_rpt_keeps_the_old_rule(self, tmp_path):
        """No .rpt at all ⇒ no abort evidence ⇒ the original rule and the
        original wording, unchanged."""
        proj = _make_project(
            tmp_path / "d", "post_dft_netlist.v", _CUT_NETLIST_V,
            _PORT_ABORT_JSON)  # no rpt
        res = _lec.audit(proj)
        rules = {f.rule for f in res.findings}
        assert "LEC_NOT_EQUIVALENT" in rules, f"got {sorted(rules)}"
        assert CANONICAL_STATUS not in rules
        assert _rc(proj) == 1

    def test_a_clean_pass_is_still_a_pass(self, tmp_path):
        proj = _make_project(
            tmp_path / "e", "netlist.v", _MAPPED_NETLIST_V,
            {"equivalent": True, "compared_points": 70,
             "non_equivalent_points": 0, "unproven_points": 0,
             "gate": "netlist.v (synth)", "verdict": "PASS",
             "inconclusive": False},
            "Equivalence successfully proven!\nProved 70 $equiv cells.\n")
        res = _lec.audit(proj)
        assert res.passed is True, [f.rule for f in res.findings]
        assert _rc(proj) == 0

    def test_module_is_pure(self):
        """No subprocess / docker / network in the predicate module."""
        src = Path(_gns.__file__).read_text()
        imports = re.findall(r"^\s*(?:import|from)\s+([\w.]+)", src,
                             re.MULTILINE)
        banned = {"subprocess", "os", "shutil", "requests", "socket",
                  "urllib", "http"}
        assert not (banned & {m.split(".")[0] for m in imports}), (
            f"{_gns.__file__} must stay a pure filesystem reader; "
            f"imports={imports}")
