"""ORGANIC #770 round-5 — the FINAL (50th) prose-FP of the convergence corpus.

axis_joiner_0001 --strict still hard-blocked the handshake item even though its
TB drives `m_tready` to BOTH 0 and 1 (flat sequential statements). Root cause was
NOT the handshake detector (the r3 distinct-RHS path credits a flat toggle) but
`_rtl_port_name_set`: it parsed only the FIRST/chosen module, so a MULTI-MODULE
RTL whose top is NOT first (a helper module precedes the joiner) lost the top's
port surface → the real `m_tready` DUT port was absent from the port set → the
DUT-port gate force-emptied → the toggle was rejected AND the provenance
corroboration saw no handshake port → advisory/uncovered.

Fix: `_rtl_port_name_set` resolves the DUT DESIGN — the TB-instantiated top +
its reachable submodules — and unions THOSE modules' ports (NOT a blind union of
every module: r5 Step-2.7 caught that a helper-only `*tready`/reset port would
let a TB-local same-named reg satisfy the item). When the TB can't be resolved it
falls back to all-modules (no-leak biased — the negatives still block).

§4.05 NO-LEAK: a handshake the TB never drives / only holds at one constant /
only toggles a NON-valid/ready decoy / lives only in an un-instantiated helper
still GAPs/BLOCKs.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import spec_coverage_check as SC  # noqa: E402

_SPEC_COV = _PROGRAMS / "spec_coverage_check.py"

_SPEC = ("# AXIS joiner\nThe joiner uses a standard valid/ready handshake "
         "with backpressure on the master stream.\n")
# a MULTI-MODULE RTL whose top (axis_joiner) is NOT the first module.
_RTL_MULTI = (
    "module helper(input a); endmodule\n"
    "module axis_joiner(input clk, input s_tvalid, output s_tready, "
    "output m_tvalid, input m_tready, output [7:0] m_tdata);\nendmodule\n")


def _run(tmp_path, tb):
    (tmp_path / "s.md").write_text(_SPEC)
    (tmp_path / "r.sv").write_text(_RTL_MULTI)
    (tmp_path / "tb.sv").write_text(tb)
    return subprocess.run(
        [sys.executable, str(_SPEC_COV), "--spec", str(tmp_path / "s.md"),
         "--rtl", str(tmp_path / "r.sv"), "--tb", str(tmp_path / "tb.sv"),
         "--strict"], capture_output=True, text=True)


# the verbatim axis_joiner TB shape: a FLAT m_tready 1 → 0 → 1 drive.
_FLAT_TB = (
    "module tb; reg clk=0; reg s_tvalid; reg m_tready;\n"
    "axis_joiner u(.clk(clk), .s_tvalid(s_tvalid), .s_tready(), .m_tvalid(), "
    ".m_tready(m_tready), .m_tdata());\n"
    "always #5 clk=~clk;\n"
    "initial begin s_tvalid=1; m_tready=1;\n"
    "  repeat(9)@(posedge clk); @(negedge clk); m_tready=0;"
    " repeat(2)@(posedge clk); @(negedge clk); m_tready=1;\n"
    "  #20; $finish; end endmodule\n")


# ── the unioned-port-set helper ──────────────────────────────────────────────
def test_770r5_port_set_fallback_unions_all_when_tb_unknown():
    """With no TB to resolve the DUT, `_rtl_port_name_set` falls back to unioning
    every module (no-leak biased — the negatives still block), so a top that is
    not the first module still contributes its handshake ports."""
    names = SC._rtl_port_name_set(_RTL_MULTI)
    assert {"m_tready", "m_tvalid", "s_tready", "s_tvalid"} <= names, names


# ── NEW-PATH: the multi-module flat-toggle FP now PASSes ─────────────────────
def test_770r5_fp_multimodule_flat_handshake_covered(tmp_path):
    r = _run(tmp_path, _FLAT_TB)
    assert r.returncode == 0, r.stdout
    assert "[OK]   handshake" in r.stdout or "handshake" not in r.stdout


# ── §4.05 NO-LEAK (each still BLOCKs on the same multi-module RTL) ────────────
def test_770r5_noleak_handshake_never_driven_blocks(tmp_path):
    tb = ("module tb; reg clk=0; reg s_tvalid; reg m_tready;\n"
          "axis_joiner u(.clk(clk),.s_tvalid(s_tvalid),.s_tready(),.m_tvalid(),"
          ".m_tready(m_tready),.m_tdata());\n"
          "initial begin s_tvalid=1; m_tready=1; #20; $finish; end endmodule\n")
    assert _run(tmp_path, tb).returncode == 1


def test_770r5_noleak_decoy_nonvalidready_toggle_blocks(tmp_path):
    tb = ("module tb; reg clk=0; reg s_tvalid; reg m_tready; reg internal_req;"
          " integer i;\n"
          "axis_joiner u(.clk(clk),.s_tvalid(s_tvalid),.s_tready(),.m_tvalid(),"
          ".m_tready(m_tready),.m_tdata());\n"
          "initial begin m_tready=1; s_tvalid=1; for(i=0;i<4;i=i+1) begin "
          "internal_req=(i%2); #5; end $finish; end endmodule\n")
    assert _run(tmp_path, tb).returncode == 1


def test_770r5_noleak_single_constant_drive_blocks(tmp_path):
    tb = ("parameter BP=1;\nmodule tb; reg clk=0; reg s_tvalid; reg m_tready;\n"
          "axis_joiner u(.clk(clk),.s_tvalid(s_tvalid),.s_tready(),.m_tvalid(),"
          ".m_tready(m_tready),.m_tdata());\n"
          "initial begin s_tvalid=1; m_tready=BP; #20; $finish; end endmodule\n")
    assert _run(tmp_path, tb).returncode == 1


# ── #478 END-STATE: real program via subprocess, returncode assert ───────────
def test_770r5_endstate_flat_toggle_rc0(tmp_path):
    r = _run(tmp_path, _FLAT_TB)
    assert r.returncode == 0, r.stdout
    assert "spec-coverage ok" in r.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── r5 Step-2.7 remediation: helper-only handshake/reset port must NOT credit ──
_RTL_HELPER_HS = (
    "module dut_top(input clk, input [7:0] data_in, output [7:0] data_out);"
    " endmodule\n"
    "module helper(input m_tvalid, output m_tready); endmodule\n")


def test_770r5_review_helper_only_handshake_does_not_credit(tmp_path):
    """r5 Step-2.7 §4.05: a `*tready` that lives ONLY in a HELPER module the DUT
    top does NOT instantiate is NOT part of the bound design — a TB driving a
    TB-local same-named reg must NOT satisfy the handshake item. The port set is
    the DUT design (TB-instantiated top + reachable submodules), not all modules."""
    (tmp_path / "s.md").write_text(_SPEC)
    (tmp_path / "r.sv").write_text(_RTL_HELPER_HS)
    (tmp_path / "tb.sv").write_text(
        "module tb; reg clk=0; reg m_tready;\n"
        "dut_top u(.clk(clk), .data_in(8'd0), .data_out());\n"
        "initial begin m_tready=1; #5; m_tready=0; #5; m_tready=1; #5; "
        "$finish; end endmodule\n")
    r = subprocess.run(
        [sys.executable, str(_SPEC_COV), "--spec", str(tmp_path / "s.md"),
         "--rtl", str(tmp_path / "r.sv"), "--tb", str(tmp_path / "tb.sv"),
         "--strict"], capture_output=True, text=True)
    # the handshake item must NOT be covered (the DUT top has no handshake port).
    assert "[OK]   handshake" not in r.stdout, r.stdout


def test_770r5_dut_module_names_is_tb_instantiated_design():
    """`_dut_module_names` returns the TB-instantiated top (+ submodules), NOT a
    blind union of every module — a helper the TB never binds is excluded."""
    dut = SC._dut_module_names(
        _RTL_HELPER_HS,
        "module tb; dut_top u(.clk(1'b0)); endmodule\n")
    assert dut == ["dut_top"], dut
    # ports are then DUT-only — the helper's m_tready is NOT present.
    names = SC._rtl_port_name_set(
        _RTL_HELPER_HS, "module tb; dut_top u(.clk(1'b0)); endmodule\n")
    assert "m_tready" not in names and "data_in" in names, names


def test_770r5_review_helper_only_reset_does_not_credit(tmp_path):
    """r5 Step-2.7 §4.05: a reset port living ONLY in an un-instantiated helper
    must NOT credit reset coverage when a TB drives a TB-local same-named reg."""
    rtl = ("module dut_top(input clk, input [7:0] d, output [7:0] q); endmodule\n"
           "module helper(input reset_n); endmodule\n")
    (tmp_path / "s.md").write_text(
        "# Design\nThe design has an asynchronous reset reset_n.\n")
    (tmp_path / "r.sv").write_text(rtl)
    (tmp_path / "tb.sv").write_text(
        "module tb; reg clk=0; reg reset_n; dut_top u(.clk(clk),.d(8'd0),.q());\n"
        "initial begin reset_n=0; #5; reset_n=1; #5; $finish; end endmodule\n")
    # reset_n is not a DUT port → reset stays UNCOVERED (not credited).
    assert "reset_n" not in SC._rtl_reset_ports(rtl, (tmp_path / "tb.sv").read_text())


def test_770r5_fallback_unknown_tb_unions_all_modules():
    """No-leak biased fallback: when the TB / its instantiation cannot be
    determined, the port set unions ALL modules (the never-driven/decoy negatives
    still block, so the wider set is safe)."""
    names = SC._rtl_port_name_set(_RTL_HELPER_HS, None)
    assert {"m_tready", "data_in"} <= names, names
