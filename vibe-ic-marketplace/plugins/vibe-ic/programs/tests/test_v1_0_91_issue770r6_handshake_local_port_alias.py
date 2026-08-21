"""ORGANIC #770 round-6 — the TRUE root cause of the final FP: the TB-local ↔
DUT-port NAME MAP.

The toggle detector and the multi-module port union (r3/r5) both work. The block
was the DUT-port membership test: the axis_joiner TB declares a LOCAL reg
(`reg m_tready;`), WIRES it to the DUT's port via a named connection
(`.m_axis_tready(m_tready)`), and TOGGLES the local reg. The port set holds the
PORT name (`m_axis_tready`); the membership test on the toggled LOCAL name
(`m_tready`) missed.

Fix: build a TB-local → DUT-port alias map from named instance connections
`.<dut_port>(<tb_local>)`; map a driven local name to its DUT port; the DUT PORT
it reaches must itself be a valid/ready handshake line.

§4.05 NO-LEAK: a handshake port connected but driven to ONE constant (no toggle);
a decoy local reg connected to NO DUT handshake port; a local wired to a
NON-handshake DUT port (e.g. `.m_axis_tdata(myready)`) — all still GAP/BLOCK.
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
_RTL = ("module axis_joiner(input clk, input s_axis_tvalid, "
        "output s_axis_tready, output m_axis_tvalid, input m_axis_tready, "
        "output [7:0] m_axis_tdata);\nendmodule\n")


def _run(tmp_path, tb):
    (tmp_path / "s.md").write_text(_SPEC)
    (tmp_path / "r.sv").write_text(_RTL)
    (tmp_path / "tb.sv").write_text(tb)
    return subprocess.run(
        [sys.executable, str(_SPEC_COV), "--spec", str(tmp_path / "s.md"),
         "--rtl", str(tmp_path / "r.sv"), "--tb", str(tmp_path / "tb.sv"),
         "--strict"], capture_output=True, text=True)


_INST = ("axis_joiner u(.clk(clk), .s_axis_tvalid(s_axis_tvalid), "
         ".s_axis_tready(), .m_axis_tvalid(), .m_axis_tready({ready}), "
         ".m_axis_tdata({tdata}));\n")


# ── the alias-map helper ─────────────────────────────────────────────────────
def test_770r6_alias_map_from_named_connections():
    tb = ("module tb; reg m_tready;\n"
          + _INST.format(ready="m_tready", tdata="") + "endmodule\n")
    amap = SC._tb_local_to_dut_port(SC._SRC.strip_comments(tb))
    assert amap.get("m_tready") == "m_axis_tready", amap
    # a same-name connection is a no-op (not in the map).
    assert "clk" not in amap


# ── NEW-PATH: TB-local toggled reg wired to a DUT handshake port → covered ────
def test_770r6_fp_local_alias_to_dut_handshake_port_covered(tmp_path):
    tb = ("module tb; reg clk=0; reg s_axis_tvalid; reg m_tready;\n"
          + _INST.format(ready="m_tready", tdata="")
          + "always #5 clk=~clk;\n"
          "initial begin s_axis_tvalid=1; m_tready=1; #20; m_tready=0; #20; "
          "m_tready=1; #20; $finish; end endmodule\n")
    r = _run(tmp_path, tb)
    assert r.returncode == 0, r.stdout


def test_770r6_direct_port_toggle_still_covered(tmp_path):
    tb = ("module tb; reg clk=0; reg s_axis_tvalid; reg m_axis_tready;\n"
          + _INST.format(ready="m_axis_tready", tdata="")
          + "initial begin s_axis_tvalid=1; m_axis_tready=1; #10; "
          "m_axis_tready=0; #10; m_axis_tready=1; #10; $finish; end endmodule\n")
    r = _run(tmp_path, tb)
    assert r.returncode == 0, r.stdout


# ── §4.05 NO-LEAK ────────────────────────────────────────────────────────────
def test_770r6_noleak_aliased_but_one_constant_blocks(tmp_path):
    tb = ("module tb; reg clk=0; reg s_axis_tvalid; reg m_tready;\n"
          + _INST.format(ready="m_tready", tdata="")
          + "initial begin s_axis_tvalid=1; m_tready=1; #20; $finish; end "
          "endmodule\n")
    assert _run(tmp_path, tb).returncode == 1


def test_770r6_noleak_decoy_unconnected_local_blocks(tmp_path):
    tb = ("module tb; reg clk=0; reg s_axis_tvalid; reg m_axis_tready; "
          "reg decoy_ready;\n"
          + _INST.format(ready="m_axis_tready", tdata="")
          + "initial begin s_axis_tvalid=1; m_axis_tready=1; decoy_ready=1; "
          "#10; decoy_ready=0; #10; decoy_ready=1; #10; $finish; end "
          "endmodule\n")
    assert _run(tmp_path, tb).returncode == 1


def test_770r6_noleak_local_wired_to_nonhandshake_port_blocks(tmp_path):
    # `myready` (handshake-shaped NAME) wired to m_axis_tdata (NOT a handshake
    # port) and toggled — must NOT credit the handshake (judge the PORT).
    tb = ("module tb; reg clk=0; reg s_axis_tvalid; reg m_axis_tready; "
          "reg myready;\n"
          + _INST.format(ready="m_axis_tready", tdata="myready")
          + "initial begin s_axis_tvalid=1; m_axis_tready=1; myready=1; #10; "
          "myready=0; #10; myready=1; #10; $finish; end endmodule\n")
    assert _run(tmp_path, tb).returncode == 1


# ── r6 Step-2.7 remediation: alias-scope §4.05 no-leak ───────────────────────
# Review reproduced a HIGH: when the TB instantiates the DUT **and** a separate
# monitor/helper module that shares a handshake port NAME (`m_axis_tready`), the
# flat alias map credited a toggle of the MONITOR's port to the DUT — while the
# DUT's own port was tied to a constant. A `.shared_port(local)` connection
# cannot be attributed to the DUT vs the sibling, so the alias-credit path must
# refuse an AMBIGUOUS port (owned by ≥2 distinct TB-instantiated module types).
_RTL_DUT_PLUS_MONITOR = (
    "module axis_joiner(input clk, input s_axis_tvalid, output s_axis_tready, "
    "output m_axis_tvalid, input m_axis_tready, output [7:0] m_axis_tdata);\n"
    "endmodule\n"
    "module helper_monitor(input clk, output m_axis_tready, input observe);\n"
    "endmodule\n")


def test_770r6_review_alias_scope_monitor_shared_port_blocks(tmp_path):
    """The DUT's m_axis_tready is tied to a constant (1'b1, never toggled); only
    the MONITOR's same-named port is toggled (via local `mon_ready`). The DUT
    handshake is NEVER exercised → must BLOCK (was a reproduced rc=0 leak)."""
    (tmp_path / "s.md").write_text(_SPEC)
    (tmp_path / "r.sv").write_text(_RTL_DUT_PLUS_MONITOR)
    (tmp_path / "tb.sv").write_text(
        "module tb; reg clk=0; reg s_axis_tvalid; reg mon_ready;\n"
        " axis_joiner dut(.clk(clk), .s_axis_tvalid(s_axis_tvalid), "
        ".s_axis_tready(), .m_axis_tvalid(), .m_axis_tready(1'b1), "
        ".m_axis_tdata());\n"
        " helper_monitor mon(.clk(clk), .m_axis_tready(mon_ready), "
        ".observe(1'b0));\n"
        " always #5 clk=~clk;\n"
        " initial begin s_axis_tvalid=1; mon_ready=1; #20; mon_ready=0; #20; "
        "mon_ready=1; #20; $finish; end endmodule\n")
    r = subprocess.run(
        [sys.executable, str(_SPEC_COV), "--spec", str(tmp_path / "s.md"),
         "--rtl", str(tmp_path / "r.sv"), "--tb", str(tmp_path / "tb.sv"),
         "--strict"], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout


def test_770r6_review_ambiguous_port_helper():
    tb = ("module tb; reg clk=0; reg mon_ready;\n"
          " axis_joiner dut(.clk(clk), .m_axis_tready(1'b1));\n"
          " helper_monitor mon(.clk(clk), .m_axis_tready(mon_ready));\n"
          "endmodule\n")
    ambig = SC._ambiguous_port_names(_RTL_DUT_PLUS_MONITOR, tb)
    assert "m_axis_tready" in ambig, ambig          # shared by both types
    # a single-module-type TB has NO ambiguity → alias path untouched.
    single = ("module tb; reg m_tready; axis_joiner dut(.clk(1'b0), "
              ".m_axis_tready(m_tready)); endmodule\n")
    assert SC._ambiguous_port_names(_RTL_DUT_PLUS_MONITOR, single) == set()


def test_770r6_review_two_types_unique_handshake_port_still_covered(tmp_path):
    """PRECISION (no over-block): the TB instantiates the DUT **and** a logger
    that does NOT share the handshake port name, so m_axis_tready is owned by the
    DUT alone (unambiguous). A local aliased to the DUT's m_axis_tready and
    toggled IS still credited → rc=0. The ambiguity guard must not block this."""
    rtl = (_RTL.rstrip()
           + "\nmodule ev_logger(input clk, input log_en);\nendmodule\n")
    (tmp_path / "s.md").write_text(_SPEC)
    (tmp_path / "r.sv").write_text(rtl)
    (tmp_path / "tb.sv").write_text(
        "module tb; reg clk=0; reg s_axis_tvalid; reg m_tready;\n"
        " axis_joiner dut(.clk(clk), .s_axis_tvalid(s_axis_tvalid), "
        ".s_axis_tready(), .m_axis_tvalid(), .m_axis_tready(m_tready), "
        ".m_axis_tdata());\n"
        " ev_logger lg(.clk(clk), .log_en(1'b1));\n"
        " always #5 clk=~clk;\n"
        " initial begin s_axis_tvalid=1; m_tready=1; #20; m_tready=0; #20; "
        "m_tready=1; #20; $finish; end endmodule\n")
    r = subprocess.run(
        [sys.executable, str(_SPEC_COV), "--spec", str(tmp_path / "s.md"),
         "--rtl", str(tmp_path / "r.sv"), "--tb", str(tmp_path / "tb.sv"),
         "--strict"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
