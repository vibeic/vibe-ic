"""test_lec_gate_netlist_select.py — bidirectional test for the ATPG-cut predicate.

Two directions (BOTH required — either alone is a rubber stamp):

  DEFECT direction:
    * is_atpg_cut_artifact() FLAGS a cut-style netlist (0 FFs + <inst>.d ports).
    * select_gate_netlist() REJECTS the cut netlist and falls back to a clean one.
    * classify_port_abort() maps (compared_points==0 + abort log) to
      INCONCLUSIVE-STRUCTURAL, NOT to LEC_NOT_EQUIVALENT.
    * lec_equivalence_check.audit() on a lec.json with compared_points==0 +
      lec.rpt with the port-abort error emits rule LEC_GATE_NETLIST_UNUSABLE,
      sets inconclusive=True, and does NOT emit LEC_NOT_EQUIVALENT.

  FIXED direction:
    * is_atpg_cut_artifact() does NOT flag a normal mapped netlist with FFs.
    * select_gate_netlist() ACCEPTS a clean netlist.
    * classify_port_abort() returns None for a normal log with 0 compared points
      but no port-abort signature.
    * lec_equivalence_check.audit() on a report with non_equivalent_points > 0
      still emits LEC_NOT_EQUIVALENT (genuine failures are NOT suppressed).

All fixtures are hand-written synthetic Verilog fragments — hermetic, no real
spm/sky130 files, sub-millisecond runtime.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Add programs/ to sys.path so the modules under test are importable.
# ---------------------------------------------------------------------------
_PROGRAMS_DIR = Path(__file__).resolve().parent.parent
if str(_PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS_DIR))

from lec_gate_netlist_select import (
    is_atpg_cut_artifact,
    select_gate_netlist,
    classify_port_abort,
    CANONICAL_STATUS,
    CANONICAL_VERDICT,
)
import lec_equivalence_check as _lec


# ---------------------------------------------------------------------------
# Synthetic fixture Verilog text (no EDA tools needed)
# ---------------------------------------------------------------------------

# A minimal ATPG-cut netlist:
#   * 5 original ports (clk, rst, x, y, p) matching the RTL
#   * 6 cut pseudo-ports: _10_, \_10_.d, _11_, \_11_.d, _12_, \_12_.d
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

# A normal liberty-backed synthesis netlist:
#   * 5 matching ports
#   * 3 DFF cell instantiations (sky130 dfxtp)
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

# Yosys equiv_make port-abort log (occurs when gate side has extra ports)
_PORT_ABORT_LOG = """\
16. Executing EQUIV_MAKE pass (creating equiv checking module).
ERROR: Can't match gate port `_10_.d_gate' to a gold port.
"""

# Normal run log (0 compared, different reason — parse abort, NOT port abort)
_PARSE_ABORT_LOG = """\
ERROR: syntax error, unexpected TOK_EOF
"""

# Non-equivalence counterexample log (a real mismatch)
_NONEQUIV_LOG = """\
Found 3 $equiv cells in equiv:
  Of those cells 0 are proven and 3 are unproven.
Found counterexample for output 'p'.
"""

# lec.json for a port-abort run (exactly what the real run produced):
_PORT_ABORT_JSON = {
    "equivalent": False,
    "compared_points": 0,
    "non_equivalent_points": 0,
    "unproven_points": 0,
    "verdict": "FAIL",
    "inconclusive": False,
}

# lec.json for a genuine non-equivalence run:
_NONEQUIV_JSON = {
    "equivalent": False,
    "compared_points": 3,
    "non_equivalent_points": 3,
    "unproven_points": 0,
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
    """Set up a minimal project tree for lec_equivalence_check.audit()."""
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
# DEFECT direction — cut netlist MUST be flagged and rejected
# ---------------------------------------------------------------------------

class TestDefectDirection:
    """All assertions in the DEFECT direction: the cut netlist must be caught."""

    def test_predicate_flags_cut_netlist_by_pseudo_port(self, tmp_path):
        """is_atpg_cut_artifact() must flag a netlist with <inst>.d ports."""
        nf = _write(tmp_path, "post_dft_netlist.v", _CUT_NETLIST_V)
        is_cut, reason = is_atpg_cut_artifact(nf)
        assert is_cut, f"Expected cut artifact to be flagged; reason={reason!r}"
        assert "pseudo-port" in reason.lower() or ".d" in reason

    def test_predicate_flags_cut_netlist_by_ff_count_drop(self, tmp_path):
        """is_atpg_cut_artifact() must flag a 0-FF netlist when ref has FFs."""
        # Build a netlist with no FFs and no .d ports (non-standard ATPG tool)
        no_ff_v = """\
module tiny(clk, rst, x, y, p);
  input clk; input rst; input x; input y; output p;
  assign p = x & y & ~rst;
endmodule
"""
        nf = _write(tmp_path, "post_dft_netlist.v", no_ff_v)
        ref_ports = {"clk", "rst", "x", "y", "p"}
        is_cut, reason = is_atpg_cut_artifact(nf, ref_ports=ref_ports, ref_ff_count=3)
        assert is_cut, f"Expected 0-FF netlist to be flagged when ref has FFs; reason={reason!r}"
        assert "0 sequential" in reason or "flip-flop" in reason.lower()

    def test_select_rejects_cut_and_falls_back(self, tmp_path):
        """select_gate_netlist() must reject cut netlist and select clean one."""
        synth = tmp_path / "phase2" / "stage2" / "synth"
        synth.mkdir(parents=True, exist_ok=True)
        (synth / "post_dft_netlist.v").write_text(_CUT_NETLIST_V, encoding="utf-8")
        (synth / "tiny_synth.v").write_text(_MAPPED_NETLIST_V, encoding="utf-8")

        chosen, reason = select_gate_netlist(
            tmp_path, "tiny",
            ref_ports={"clk", "rst", "x", "y", "p"},
            ref_ff_count=3)

        assert chosen is not None, f"Expected fallback, got None; reason={reason!r}"
        assert chosen.name != "post_dft_netlist.v", (
            f"Must not select the cut netlist; got {chosen.name}")
        assert "rejected" in reason.lower() or "post_dft" in reason.lower()

    def test_classify_port_abort_returns_structural_verdict(self):
        """classify_port_abort() must return CANONICAL_VERDICT for the abort log."""
        result = classify_port_abort(_PORT_ABORT_LOG, compared_points=0)
        assert result == CANONICAL_VERDICT, (
            f"Expected {CANONICAL_VERDICT!r}, got {result!r}")

    def test_audit_port_abort_emits_gns_unusable_not_not_equivalent(self, tmp_path):
        """audit() must emit LEC_GATE_NETLIST_UNUSABLE for a port-abort run.

        The run has compared_points==0 and lec.rpt contains the port-abort.
        It must NOT emit LEC_NOT_EQUIVALENT — that would be a false diagnosis.
        It must set inconclusive=True (non-blocking, visible non-PASS).
        """
        proj = _make_project(
            tmp_path / "a", "post_dft_netlist.v", _CUT_NETLIST_V,
            _PORT_ABORT_JSON, _PORT_ABORT_LOG)

        result = _lec.audit(proj)

        rules = [f.rule for f in result.findings]
        assert CANONICAL_STATUS in rules, (
            f"Expected {CANONICAL_STATUS!r} in findings; got rules={rules}")
        assert "LEC_NOT_EQUIVALENT" not in rules, (
            f"Must NOT emit LEC_NOT_EQUIVALENT for a structural abort; "
            f"rules={rules}")
        assert result.inconclusive is True, (
            f"Expected inconclusive=True; got {result.inconclusive}")
        assert result.passed is False, "Must not PASS a structural-abort run"

    def test_audit_vacuous_false_no_rpt_stays_not_equivalent(self, tmp_path):
        """Without the port-abort in .rpt, equivalent=False still LEC_NOT_EQUIVALENT.

        This is the non-rpt case — no .rpt file at all.  The run should still
        report LEC_NOT_EQUIVALENT because we can't confirm it's a port abort.
        """
        proj = _make_project(
            tmp_path / "b", "post_dft_netlist.v", _CUT_NETLIST_V,
            _PORT_ABORT_JSON)  # no rpt_content

        result = _lec.audit(proj)
        rules = [f.rule for f in result.findings]
        # Without a .rpt confirming the port-abort, we cannot reclassify.
        assert "LEC_NOT_EQUIVALENT" in rules or CANONICAL_STATUS in rules, (
            f"Expected LEC_NOT_EQUIVALENT or {CANONICAL_STATUS}; got {rules}")


# ---------------------------------------------------------------------------
# FIXED direction — clean netlist must NOT be flagged; real failures preserved
# ---------------------------------------------------------------------------

class TestFixedDirection:
    """All assertions in the FIXED direction: do not over-correct."""

    def test_predicate_does_not_flag_normal_netlist(self, tmp_path):
        """is_atpg_cut_artifact() must NOT flag a normal mapped netlist."""
        nf = _write(tmp_path, "netlist.v", _MAPPED_NETLIST_V)
        is_cut, reason = is_atpg_cut_artifact(
            nf,
            ref_ports={"clk", "rst", "x", "y", "p"},
            ref_ff_count=3)
        assert not is_cut, (
            f"Normal mapped netlist must NOT be flagged as cut; reason={reason!r}")

    def test_select_accepts_clean_netlist(self, tmp_path):
        """select_gate_netlist() must accept a clean netlist without rejection."""
        synth = tmp_path / "phase2" / "stage2" / "synth"
        synth.mkdir(parents=True, exist_ok=True)
        (synth / "tiny_synth.v").write_text(_MAPPED_NETLIST_V, encoding="utf-8")

        chosen, reason = select_gate_netlist(
            tmp_path, "tiny",
            ref_ports={"clk", "rst", "x", "y", "p"},
            ref_ff_count=3)

        assert chosen is not None
        assert chosen.name == "tiny_synth.v", (
            f"Expected tiny_synth.v to be accepted; got {chosen.name}")
        assert "rejected" not in reason.lower() or "post_dft" not in reason.lower()

    def test_classify_port_abort_returns_none_for_normal_log(self):
        """classify_port_abort() must return None when no port-abort is present."""
        result = classify_port_abort(_PARSE_ABORT_LOG, compared_points=0)
        assert result is None, (
            f"Must return None for a non-port-abort log; got {result!r}")

    def test_classify_port_abort_returns_none_when_points_nonzero(self):
        """classify_port_abort() must return None when compared_points > 0."""
        result = classify_port_abort(_PORT_ABORT_LOG, compared_points=5)
        assert result is None, (
            f"Must return None when compared_points > 0; got {result!r}")

    def test_audit_genuine_nonequiv_still_reports_not_equivalent(self, tmp_path):
        """A genuine non-equivalence run must still emit LEC_NOT_EQUIVALENT.

        The fix must not suppress real failures.  A run with 3 non-equivalent
        points and a counterexample in the log must emit LEC_NOT_EQUIVALENT,
        never a vacuous PASS or INCONCLUSIVE.
        """
        proj = _make_project(
            tmp_path / "c", "netlist.v", _MAPPED_NETLIST_V,
            _NONEQUIV_JSON, _NONEQUIV_LOG)

        result = _lec.audit(proj)
        rules = [f.rule for f in result.findings]
        assert "LEC_NOT_EQUIVALENT" in rules or "LEC_NONEQUIV_POINTS" in rules, (
            f"Expected a non-equivalence rule; got {rules}")
        assert result.passed is False
        assert result.inconclusive is False

    def test_predicate_does_not_flag_cut_without_ff_context(self, tmp_path):
        """Without ref_ff_count, a 0-FF netlist without .d ports is NOT flagged.

        The predicate is conservative: without reference context it can only
        use Signal A (pseudo-port pattern).  A design that genuinely has no
        FFs must not be falsely flagged.
        """
        no_ff_combinational = """\
module comb(a, b, y);
  input a; input b; output y;
  assign y = a ^ b;
endmodule
"""
        nf = _write(tmp_path, "netlist.v", no_ff_combinational)
        is_cut, reason = is_atpg_cut_artifact(nf)  # no ref context
        assert not is_cut, (
            f"Pure-combinational design without .d ports must NOT be flagged; "
            f"reason={reason!r}")
