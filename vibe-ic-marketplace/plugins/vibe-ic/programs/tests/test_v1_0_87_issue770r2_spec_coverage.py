#!/usr/bin/env python3
"""ORGANIC #770 round-2 — Part A: spec_coverage_check.py residual prose-FPs.

The #770 provenance/confidence layer (`_provenance.py`: STRUCTURAL always blocks;
PROSE_HEURISTIC blocks only if CORROBORATED or UNKNOWN; ADVISORY iff
CONTRADICTED/NO_CORROBORATION) is CORRECT — this round COMPLETES it in
spec_coverage_check.py for the 3 residual false-positives the field-agent reopen
identified, without leaking the §4.05 no-leak boundary.

Root cause 1 — corroboration was computed only for `reset`/`latency`. The
`handshake` and `enum_set` prose kinds were tagged PROSE_HEURISTIC but left
corr=UNKNOWN, so the no-leak bias kept them blocking even when the TB/RTL
structurally contradicts them:
  * handshake (axis_joiner_0001) — the TB structurally TOGGLES the concrete
    `m_tready`/`s_tvalid` handshake signals (backpressure) but never spells the
    noun 'handshake'; now the handshake item is covered by the toggle stimulus.
  * enum_set (configurable_digital_low_pass_filter_0001) — a single-signal packed
    CONCATENATION literal `data_in = {6'b001100, 6'b110011, ...}` is ONE value of
    ONE signal, not an enumerated value set whose members must each be 'handled';
    now CONTRADICTED → advisory.

Root cause 2 — Step-2.7 markdown-table latency promotion over-promoted: it
promoted `latency` to STRUCTURAL whenever `_LATENCY_RE` matched ANY table cell,
including an `Internal Signals` helper row ('Registered version of the sel
signal') — re-blocking a pure-combinational design (axis_mux_0001). The
promotion is now scoped to OUTPUT-TIMING table rows only.

§4.05 NO-LEAK (load-bearing half) — EVERY structural negative still hard-BLOCKs:
  * a handshake the RTL corroborates but the TB never toggles → BLOCK
  * a handshake with no RTL to judge (UNKNOWN) → BLOCK
  * a GENUINE enumerated VALUE set the TB leaves uncovered → BLOCK
  * a GENUINE `| Output latency | 1 clock cycle |` output-timing table row on a
    combinational RTL → STRUCTURAL → BLOCK
  * a registered design's latency the TB never covers → BLOCK
  * the #752 genuine-missing-port invariant → BLOCK
  * a table-sourced signedness (16qam-class) → BLOCK

chip-AGNOSTIC: pure valid/ready signal-naming + concatenation-assignment +
output-timing GFM grammar; no chip / vendor / SKU literal.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import spec_coverage_check as SC  # noqa: E402

_SPEC_COV = _PROGRAMS / "spec_coverage_check.py"
_TB_BARE = "module tb; reg clk=0; reg [7:0] c; initial begin c=0; #5; $finish; end endmodule\n"


def _run(tmp_path, spec, tb=_TB_BARE, rtl=None, strict=True):
    (tmp_path / "spec.md").write_text(spec)
    (tmp_path / "tb.sv").write_text(tb)
    cmd = [sys.executable, str(_SPEC_COV), "--spec", str(tmp_path / "spec.md"),
           "--tb", str(tmp_path / "tb.sv")]
    if rtl is not None:
        (tmp_path / "rtl.sv").write_text(rtl)
        cmd += ["--rtl", str(tmp_path / "rtl.sv")]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


# ── faithful fixtures (the three reopened FPs) ───────────────────────────────
_AXIS_JOINER_SPEC = (
    "# AXI-Stream Joiner\n\n"
    "The module joins two AXI-Stream inputs. It follows the standard valid/ready\n"
    "handshake protocol with backpressure on the master interface.\n")
_AXIS_JOINER_RTL = (
    "module axis_joiner(input wire clk, input wire s_tvalid, output wire s_tready,\n"
    " input wire [7:0] s_tdata, output wire m_tvalid, input wire m_tready,\n"
    " output wire [7:0] m_tdata);\n"
    " assign s_tready = m_tready; assign m_tvalid = s_tvalid;\n"
    " assign m_tdata = s_tdata;\nendmodule\n")
_AXIS_JOINER_TB_TOGGLES = (
    "module tb;\n reg clk=0; reg s_tvalid; reg [7:0] s_tdata; reg m_tready;\n"
    " wire s_tready, m_tvalid; wire [7:0] m_tdata;\n"
    " axis_joiner u(.clk(clk),.s_tvalid(s_tvalid),.s_tready(s_tready),\n"
    "   .s_tdata(s_tdata),.m_tvalid(m_tvalid),.m_tready(m_tready),.m_tdata(m_tdata));\n"
    " initial begin s_tvalid=1; s_tdata=8'hA5;\n"
    "   m_tready=1; #5; m_tready=0; #5; m_tready=1; #5; $finish; end\nendmodule\n")

_LPF_SPEC = (
    "# Configurable Digital Low-Pass Filter\n\n"
    "The coefficient bank is loaded as a packed value:\n"
    "data_in = {6'b001100, 6'b110011, 6'b010101, 6'b101010}\n\n"
    "The filter applies these coefficients to the input stream.\n")
_LPF_RTL = (
    "module clpf(input clk, input [23:0] data_in, output reg [15:0] y);\n"
    " always @(posedge clk) y <= data_in[15:0];\nendmodule\n")
_LPF_TB = (
    "module tb;\n reg clk=0; reg [23:0] data_in; wire [15:0] y;\n"
    " clpf u(.clk(clk),.data_in(data_in),.y(y));\n"
    " initial begin data_in=24'h0F0F0F; #5; data_in=24'hA5A5A5; #5; $finish; end\n"
    "endmodule\n")

_MUX_SPEC = (
    "# AXI-Stream Mux\n\n"
    "A combinational multiplexer that selects one of N input streams.\n\n"
    "## Internal Signals\n\n"
    "| Signal | Description |\n|---|---|\n"
    "| sel_r | Registered version of the sel signal |\n"
    "| out_mux | Combinational mux output |\n")
_MUX_RTL = (
    "module axis_mux(input [1:0] sel, input [7:0] in0, input [7:0] in1,\n"
    " output reg [7:0] out);\n reg [7:0] tmp;\n"
    " always @(*) tmp = (sel[0]) ? in1 : in0;\n always @(*) out = tmp;\nendmodule\n")
_MUX_TB = (
    "module tb;\n reg [1:0] sel; reg [7:0] in0,in1; wire [7:0] out;\n"
    " axis_mux u(.sel(sel),.in0(in0),.in1(in1),.out(out));\n"
    " initial begin sel=0; in0=8'h11; in1=8'h22; #5; sel=1; #5; $finish; end\n"
    "endmodule\n")


# ─────────────────────────────────────────────────────────────────────────────
# FP-NOW-PASSES (the 3 reopened residual prose-FPs flip to PASS / advisory rc=0)
# ─────────────────────────────────────────────────────────────────────────────
def test_770r2_fp_axis_joiner_handshake_toggle_passes(tmp_path):
    """axis_joiner_0001 — the TB toggles m_tready (backpressure) but never spells
    'handshake'; the handshake item is now COVERED by the toggle stimulus."""
    r = _run(tmp_path, _AXIS_JOINER_SPEC, tb=_AXIS_JOINER_TB_TOGGLES,
             rtl=_AXIS_JOINER_RTL)
    assert r.returncode == 0, r.stdout
    assert "[STRICT/sole-emit] BLOCK" not in r.stdout


def test_770r2_fp_low_pass_filter_concat_enum_is_advisory(tmp_path):
    """configurable_digital_low_pass_filter_0001 — a single-signal packed
    CONCATENATION literal is not an enumerated value set → advisory, not block."""
    r = _run(tmp_path, _LPF_SPEC, tb=_LPF_TB, rtl=_LPF_RTL)
    assert r.returncode == 0, r.stdout
    assert "ADVISORY" in r.stdout


def test_770r2_fp_axis_mux_internal_signal_latency_is_advisory(tmp_path):
    """axis_mux_0001 — 'Registered' in an Internal-Signals helper row must NOT
    promote latency to STRUCTURAL; on pure-combinational RTL it downgrades."""
    r = _run(tmp_path, _MUX_SPEC, tb=_MUX_TB, rtl=_MUX_RTL)
    assert r.returncode == 0, r.stdout
    assert "ADVISORY" in r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# §4.05 NO-LEAK — the structurally near-identical negatives STILL hard-BLOCK
# ─────────────────────────────────────────────────────────────────────────────
def test_770r2_noleak_handshake_rtl_corroborated_no_tb_toggle_blocks(tmp_path):
    """RTL HAS handshake ports (corroborated) but the TB never TOGGLES a
    handshake signal high+low → a genuine coverage gap → STILL BLOCK."""
    tb_no_toggle = (
        "module tb;\n reg clk=0; reg s_tvalid; reg [7:0] s_tdata; reg m_tready;\n"
        " wire s_tready, m_tvalid; wire [7:0] m_tdata;\n"
        " axis_joiner u(.clk(clk),.s_tvalid(s_tvalid),.s_tready(s_tready),\n"
        "   .s_tdata(s_tdata),.m_tvalid(m_tvalid),.m_tready(m_tready),.m_tdata(m_tdata));\n"
        " reg [7:0] cnt;\n"
        " initial begin s_tvalid=1; s_tdata=8'hA5; m_tready=1; cnt=8'h00;\n"
        "   #5; $finish; end\nendmodule\n")
    r = _run(tmp_path, _AXIS_JOINER_SPEC, tb=tb_no_toggle, rtl=_AXIS_JOINER_RTL)
    assert r.returncode == 1, r.stdout


def test_770r2_noleak_handshake_no_rtl_unknown_keeps_block(tmp_path):
    """No --rtl → handshake corroboration UNKNOWN → no-leak bias keeps the block.
    The TB names nothing handshake-shaped and toggles no handshake signal."""
    r = _run(tmp_path, _AXIS_JOINER_SPEC, tb=_TB_BARE, rtl=None)
    assert r.returncode == 1, r.stdout


def test_770r2_noleak_genuine_value_enum_uncovered_blocks(tmp_path):
    """A GENUINE enumerated VALUE set {0xA1,0xB2,0xC3} (set-context, NOT a
    single-signal concat assignment) left uncovered → STRUCTURAL → STILL BLOCK.
    Only the concatenation literal is downgraded — this value set is not."""
    spec = ("# Opcode decoder\n"
            "The opcode must be one of {0xA1, 0xB2, 0xC3}; each opcode is "
            "handled distinctly.\n")
    rtl = ("module dec(input [7:0] opcode, output reg [3:0] o);\n"
           " always @(*) case(opcode) 8'hA1:o=1; 8'hB2:o=2; 8'hC3:o=3;\n"
           "   default:o=0; endcase\nendmodule\n")
    tb = ("module tb;\n reg [7:0] opcode; wire [3:0] o; dec u(.opcode(opcode),.o(o));\n"
          " initial begin opcode=8'h00; opcode=8'h11; $finish; end\nendmodule\n")
    r = _run(tmp_path, spec, tb=tb, rtl=rtl)
    assert r.returncode == 1, r.stdout
    # it must STILL be a hard block, not an advisory downgrade.
    assert "[STRICT/sole-emit] BLOCK" in r.stdout


def test_770r2_noleak_genuine_output_timing_table_latency_blocks(tmp_path):
    """A GENUINE `| Output latency | 1 clock cycle |` OUTPUT-TIMING table row on a
    pure-combinational RTL is STRUCTURAL (table-sourced) → STILL BLOCK. The
    promotion scoping must not regress the legitimate table-sourced block."""
    spec = ("# Adder\n\n| Requirement | Details |\n|---|---|\n"
            "| Output latency | 1 clock cycle |\n")
    rtl = ("module adder(input [3:0] a, input [3:0] b, output [4:0] sum);\n"
           " assign sum = a + b;\nendmodule\n")
    tb = ("module tb; reg [3:0] a,b; wire [4:0] sum; adder u(a,b,sum);\n"
          " initial begin a=1;b=2;#1;$finish; end endmodule\n")
    r = _run(tmp_path, spec, tb=tb, rtl=rtl)
    assert r.returncode == 1, r.stdout
    assert "ADVISORY" not in r.stdout


def test_770r2_noleak_registered_latency_uncovered_blocks(tmp_path):
    """A registered (clocked) design whose latency the TB never covers → the
    prose latency is CORROBORATED by the clocked RTL → STILL BLOCK."""
    spec = "# Acc\nThe output is registered with a one clock cycle latency.\n"
    rtl = ("module dut(input clk, input [3:0] a, output reg [4:0] sum);\n"
           " always @(posedge clk) sum <= a;\nendmodule\n")
    r = _run(tmp_path, spec, tb=_TB_BARE, rtl=rtl)
    assert r.returncode == 1, r.stdout


def test_770r2_noleak_missing_port_752_invariant_blocks(tmp_path):
    """#752 invariant — an RTL that OMITS a real spec port → STILL BLOCK (the
    provenance completion must not re-break the genuine-missing-port guard)."""
    spec = "- input clk\n- input data_in\n- output data_out\n"
    rtl = "module dut(input clk);\nendmodule\n"
    r = _run(tmp_path, spec, tb=_TB_BARE, rtl=rtl)
    assert r.returncode == 1, r.stdout


def test_770r2_noleak_table_sourced_signedness_blocks(tmp_path):
    """The 16qam-class table-sourced signedness is a LEGITIMATE block — only
    latency promotion was scoped; signedness table-promotion is untouched."""
    spec = ("# 16-QAM mapper\n\n| Parameter | Value |\n|---|---|\n"
            "| Input data | signed |\n")
    rtl = ("module qam(input signed [7:0] din, output reg [7:0] iout);\n"
           " always @(*) iout = din;\nendmodule\n")
    r = _run(tmp_path, spec, tb=_TB_BARE, rtl=rtl)
    assert r.returncode == 1, r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# unit coverage of the new deterministic helpers (chip-AGNOSTIC primitives)
# ─────────────────────────────────────────────────────────────────────────────
def test_770r2_tb_exercises_handshake_region_toggle_detected():
    tb = "m_tready = 1; #5; m_tready = 0; #5; m_tready = 1;"
    assert SC._tb_exercises_handshake_region(tb) is True
    # a single-polarity drive (no toggle) is NOT a handshake exchange.
    assert SC._tb_exercises_handshake_region("m_tready = 1; s_tvalid = 1;") is False
    # a non-handshake signal toggling does not count.
    assert SC._tb_exercises_handshake_region("count = 1; #5; count = 0;") is False


def test_770r2_single_signal_concat_assignment_detected():
    import re
    spec = "data_in = {6'b001100, 6'b110011, 6'b010101}"
    m = SC._ENUM_SET_RE.search(spec)
    assert SC._is_single_signal_concat_assignment(spec, m) is True
    # a set-context enum (NOT an assignment RHS) is NOT a concat literal.
    spec2 = "opcode is one of {0xA1, 0xB2, 0xC3}"
    m2 = SC._ENUM_SET_RE.search(spec2)
    assert SC._is_single_signal_concat_assignment(spec2, m2) is False
    # a comma-joined sibling (part of a larger list) is not a single-signal RHS.
    spec3 = "x, {a, b, c}"
    m3 = SC._ENUM_SET_RE.search(spec3)
    assert SC._is_single_signal_concat_assignment(spec3, m3) is False


def test_770r2_output_timing_table_text_scopes_to_timing_rows():
    # an Internal-Signals helper table whose Description says 'Registered ...'
    # is NOT output-timing → excluded from the promotion source.
    helper = ("| Signal | Description |\n|---|---|\n"
              "| sel_r | Registered version of the sel signal |\n")
    assert "Registered" not in SC._output_timing_table_text(helper)
    # a genuine output-latency row IS included.
    timing = ("| Requirement | Details |\n|---|---|\n"
              "| Output latency | 1 clock cycle |\n")
    assert "1 clock cycle" in SC._output_timing_table_text(timing)


# ─────────────────────────────────────────────────────────────────────────────
# #478 END-STATE — direct-write a tmp artifact, invoke the REAL program via
# subprocess, assert the returncode end-state (rc transition is real, not mocked)
# ─────────────────────────────────────────────────────────────────────────────
def test_770r2_478_endstate_fp_flips_and_noleak_holds(tmp_path):
    """#478 end-state: write real artifacts to tmp_path, run the real program
    twice via subprocess — the reopened FP flips to rc=0 while the boundary-outside
    negative (TB that never toggles the handshake) still rc=1 BLOCKs."""
    (tmp_path / "spec.md").write_text(_AXIS_JOINER_SPEC)
    (tmp_path / "rtl.sv").write_text(_AXIS_JOINER_RTL)
    (tmp_path / "tb_toggle.sv").write_text(_AXIS_JOINER_TB_TOGGLES)
    (tmp_path / "tb_flat.sv").write_text(
        "module tb;\n reg clk=0; reg s_tvalid; reg m_tready; reg [7:0] cnt;\n"
        " initial begin s_tvalid=1; m_tready=1; cnt=8'h00; #5; $finish; end\n"
        "endmodule\n")

    def _invoke(tb_name):
        return subprocess.run(
            [sys.executable, str(_SPEC_COV),
             "--spec", str(tmp_path / "spec.md"),
             "--rtl", str(tmp_path / "rtl.sv"),
             "--tb", str(tmp_path / tb_name),
             "--strict"],
            capture_output=True, text=True)

    fp = _invoke("tb_toggle.sv")
    assert fp.returncode == 0, fp.stdout          # FP flips to PASS

    leak = _invoke("tb_flat.sv")
    assert leak.returncode == 1, leak.stdout      # §4.05 negative still BLOCKs


# ── Step-2.7 adversarial-review remediation (3 reproduced §4.05 findings) ─────
def test_770r2_review_enum_value_set_with_vocabulary_still_blocks(tmp_path):
    """Finding #1: a value-SET written compactly as `NAME = {v1, v2, ...}` with
    enumeration vocabulary ('discrete calibrated levels; any other value is
    reserved') is NOT a packed-concat literal — uncovered, it must STILL BLOCK."""
    spec = ("# Cfg\nThe gain field accepts only the following discrete calibrated "
            "levels; any other value is reserved. GAIN_LEVELS = {8'h10, 8'h20, "
            "8'h40, 8'h80}.\n")
    rtl = ("module cfg(input [7:0] g, output reg ok); "
           "always @(*) ok = (g==8'h10); endmodule\n")
    r = _run(tmp_path, spec, tb=_TB_BARE, rtl=rtl)
    assert r.returncode == 1, r.stdout


def test_770r2_review_handshake_decoy_toggle_does_not_satisfy(tmp_path):
    """Finding #2: a TB that toggles only a decoy local control reg
    (internal_req) and HOLDS the real valid/ready ports must STILL gap the
    handshake item (the toggled signal must be a DUT valid/ready port)."""
    spec = "# Axi\nStandard valid/ready handshake with backpressure on the stream.\n"
    rtl = ("module axis(input clk, input s_tvalid, output s_tready, "
           "output m_tvalid, input m_tready); endmodule\n")
    tb = ("module tb; reg clk, s_tvalid, m_tready, internal_req;\n"
          "axis u(.clk(clk), .s_tvalid(s_tvalid), .s_tready(), .m_tvalid(), "
          ".m_tready(m_tready));\n"
          "initial begin s_tvalid=1; m_tready=1; internal_req=1; #1; "
          "internal_req=0; #1; $finish; end endmodule\n")
    r = _run(tmp_path, spec, tb=tb, rtl=rtl)
    assert r.returncode == 1, r.stdout


def test_770r2_review_value_cell_latency_on_comb_still_blocks(tmp_path):
    """Finding #3: a latency stated in a Details VALUE cell (not the key cell)
    on a pure-combinational RTL is a real forgot-to-register bug — STILL BLOCK."""
    spec = ("# Acc\n\n| Signal | Description |\n|---|---|\n"
            "| acc_out | Registered output, 2 clock cycle latency from input |\n")
    rtl = "module acc(input [3:0] a, output [3:0] acc_out); assign acc_out=a; endmodule\n"
    tb = ("module tb; reg [3:0] a; wire [3:0] acc_out; acc u(a,acc_out);\n"
          "initial begin a=1;#1;$finish; end endmodule\n")
    r = _run(tmp_path, spec, tb=tb, rtl=rtl)
    assert r.returncode == 1, r.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
