#!/usr/bin/env python3
"""Tests for clock_domain_reg_crossing_check.

Every test here is bidirectional: for each shape the gate is meant to catch
there is a NEGATIVE control (a design of the same shape that is correct, or a
single-clock design of the same shape) which must stay green. A test that only
ever exercises the failing direction cannot tell a working gate from one that
returns FAIL unconditionally.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import clock_domain_reg_crossing_check as C  # noqa: E402


def _audit(src: str):
    return C.audit_text(C.strip_comments(src), "t.v")


def _rules(findings, severity=None):
    return sorted(f.rule for f in findings
                  if severity is None or f.severity == severity)


# --------------------------------------------------------------------------
# The core shape: a register crossing clock domains with no synchroniser.
# --------------------------------------------------------------------------
UNSYNCED = """
module m(input ca, input cb, input rst_n, input e, output reg flag);
  reg [7:0] cnt;
  always @(posedge ca or negedge rst_n) begin
    if (!rst_n) cnt <= 8'd0; else if (e) cnt <= cnt + 8'd1;
  end
  always @(posedge cb or negedge rst_n) begin
    if (!rst_n) flag <= 1'b0; else flag <= (cnt == 8'd99);
  end
endmodule
"""

SYNCED = """
module m(input ca, input cb, input rst_n, input e, output reg flag);
  reg [7:0] cnt, cnt_gray, meta, sync;
  always @(posedge ca or negedge rst_n) begin
    if (!rst_n) begin cnt <= 8'd0; cnt_gray <= 8'd0; end
    else if (e) begin cnt <= cnt + 8'd1; cnt_gray <= (cnt+8'd1) ^ ((cnt+8'd1) >> 1); end
  end
  always @(posedge cb or negedge rst_n) begin
    if (!rst_n) begin meta <= 8'd0; sync <= 8'd0; flag <= 1'b0; end
    else begin meta <= cnt_gray; sync <= meta; flag <= (sync == 8'd99); end
  end
endmodule
"""

SINGLE_CLOCK = """
module m(input clk, input rst_n, input e, output reg flag);
  reg [7:0] cnt;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) cnt <= 8'd0; else if (e) cnt <= cnt + 8'd1;
  end
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) flag <= 1'b0; else flag <= (cnt == 8'd99);
  end
endmodule
"""


def test_unsynchronised_crossing_is_an_error():
    findings, examined = _audit(UNSYNCED)
    assert examined == 1
    assert "CDC_REG_NO_SYNC" in _rules(findings, "ERROR")


def test_synchronised_crossing_is_clean():
    """NEGATIVE CONTROL — the same design done correctly must not fire."""
    findings, examined = _audit(SYNCED)
    assert examined == 1, "the correct design must still be examined, not skipped"
    assert _rules(findings, "ERROR") == []


def test_single_clock_design_is_skipped_by_construction():
    """A one-clock module has no crossing to make; it must never be examined."""
    findings, examined = _audit(SINGLE_CLOCK)
    assert examined == 0
    assert findings == []


# --------------------------------------------------------------------------
# A crossing hidden behind a continuous assign is still a crossing.
# --------------------------------------------------------------------------
COMB_PATH = """
module m(input ca, input cb, input rst_n, input go, output reg done);
  reg [3:0] st;
  wire last = (st == 4'd9);
  always @(posedge ca or negedge rst_n) begin
    if (!rst_n) st <= 4'd0; else if (go) st <= st + 4'd1;
  end
  always @(posedge cb or negedge rst_n) begin
    if (!rst_n) done <= 1'b0; else done <= last;
  end
endmodule
"""


def test_combinational_path_between_domains_is_caught():
    findings, _ = _audit(COMB_PATH)
    assert "CDC_REG_NO_SYNC" in _rules(findings, "ERROR")
    assert any(f.evidence.get("register") == "st" for f in findings)


# --------------------------------------------------------------------------
# False-positive controls taken from real reference CDC code. Each of these
# was an actual false positive during development; they are pinned so the
# gate cannot regress into flagging correct designs.
# --------------------------------------------------------------------------
INSTANTIATED_SYNC = """
module m(input ca, input cb, input rst_n, input p, output reg q);
  reg lvl; wire lvl_s;
  always @(posedge ca or negedge rst_n) begin
    if (!rst_n) lvl <= 1'b0; else lvl <= lvl ^ p;
  end
  sync2 u_s (.d_i(lvl), .clk_i(cb), .rst_ni(rst_n), .q_o(lvl_s));
  always @(posedge cb or negedge rst_n) begin
    if (!rst_n) q <= 1'b0; else q <= lvl_s;
  end
endmodule
"""

DUAL_PORT_MEM = """
module m(input ca, input cb, input we, input [3:0] wa, input [3:0] ra,
         input [7:0] wd, output reg [7:0] rd);
  reg [7:0] mem [0:15];
  always @(posedge ca) begin
    if (we) mem[wa] <= wd;
  end
  always @(posedge cb) begin
    rd <= mem[ra];
  end
endmodule
"""

RESET_TERM_ONLY = """
module m(input ca, input cb, input rst_n, input p, output reg dpulse);
  reg dlevel;
  wire eff_rst_n = rst_n && dpulse;
  reg src_q;
  always @(posedge cb or negedge rst_n) begin
    if (!rst_n) dpulse <= 1'b0; else dpulse <= p;
  end
  always @(posedge ca or negedge eff_rst_n) begin
    if (!eff_rst_n) src_q <= 1'b0; else src_q <= p;
  end
endmodule
"""


def test_synchroniser_instantiated_as_a_submodule_is_not_flagged():
    """The synchroniser is a cell, not an inline flop chain — must stay green."""
    findings, examined = _audit(INSTANTIATED_SYNC)
    assert examined == 1
    assert _rules(findings, "ERROR") == []


def test_dual_port_memory_array_is_not_a_flop_crossing():
    findings, _ = _audit(DUAL_PORT_MEM)
    assert _rules(findings, "ERROR") == []


def test_signal_reaching_a_domain_only_through_its_reset_term_is_not_data():
    """A reset-network crossing is an RDC concern, not this gate's."""
    findings, _ = _audit(RESET_TERM_ONLY)
    assert _rules(findings, "ERROR") == []


# --------------------------------------------------------------------------
# Severity tiering.
# --------------------------------------------------------------------------
MULTIBIT_NO_GRAY = """
module m(input ca, input cb, input rst_n, input t, output reg [7:0] snap);
  reg [7:0] lvl, meta, sync;
  always @(posedge ca or negedge rst_n) begin
    if (!rst_n) lvl <= 8'd0; else if (t) lvl <= lvl + 8'd1;
  end
  always @(posedge cb or negedge rst_n) begin
    if (!rst_n) begin meta <= 8'd0; sync <= 8'd0; snap <= 8'd0; end
    else begin meta <= lvl; sync <= meta; snap <= sync; end
  end
endmodule
"""


def test_multibit_without_gray_is_a_warning_not_an_error():
    findings, _ = _audit(MULTIBIT_NO_GRAY)
    assert _rules(findings, "ERROR") == []
    assert "CDC_MULTIBIT_NO_GRAY" in _rules(findings, "WARN")


def test_strict_mode_promotes_warnings(tmp_path):
    f = tmp_path / "m.v"
    f.write_text(MULTIBIT_NO_GRAY)
    assert C.audit(paths=[str(f)], strict=False).passed is True
    assert C.audit(paths=[str(f)], strict=True).passed is False


# --------------------------------------------------------------------------
# Evidence + degrade-loudly.
# --------------------------------------------------------------------------
def test_finding_carries_the_evidence_it_judged_on(tmp_path):
    f = tmp_path / "m.v"
    f.write_text(UNSYNCED)
    res = C.audit(paths=[str(f)])
    ev = [x.evidence for x in res.findings if x.rule == "CDC_REG_NO_SYNC"][0]
    for key in ("register", "from_domain", "to_domain", "clock_domains"):
        assert key in ev, f"verdict must attach {key} so it can be cross-checked"
    assert ev["from_domain"] != ev["to_domain"]


def test_empty_scan_is_reported_as_no_input_not_as_pass(tmp_path):
    """An empty scan must not read as a green CDC verdict."""
    res = C.audit(project_dir=str(tmp_path))
    assert res.summary["no_input"] is True


def test_parameterised_width_is_not_reported_as_a_bit_count():
    assert C.width_text(-1) == "parameterised-width"
    assert C.width_text(8) == "8-bit"


@pytest.mark.parametrize("src", [UNSYNCED, SYNCED, SINGLE_CLOCK, COMB_PATH,
                                 INSTANTIATED_SYNC, DUAL_PORT_MEM,
                                 RESET_TERM_ONLY, MULTIBIT_NO_GRAY])
def test_no_crash_on_any_fixture(src):
    _audit(src)
