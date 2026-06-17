#!/usr/bin/env python3
"""Regression for ORGANIC #811 round-16 — the latency clear-control family
false-TIMEOUT on `cvdp_copilot_signed_adder_0001` (the SECOND FP in this family
in consecutive CVDP convergence rounds).

Two compounding root causes in `programs/latency_conformance_check.py`, both fixed
SYSTEMICALLY (chip-AGNOSTIC):

  (1) NAME-PREFIX ASYMMETRY — `_looks_like_clear`/`_looks_like_setreset_bit`
      matched only the BARE token, UNLIKE `_is_clock` which strips a directional
      prefix. So `i_clear` was NOT recognised as a clear, fell into the
      all-ones-pinned `others`, was pinned ACTIVE → permanent FSM flush →
      `o_ready` (asserted only in OUTPUT) never asserts → false LATENCY-TIMEOUT.
      FIX: strip a leading `i_`/`o_`/`io_`/`in_`/`out_` prefix before the
      exact-token match, mirroring `_is_clock`.

  (2) STRUCTURAL-DETECTOR LOCALPARAM GAP — the round-15 structural clear detector
      required a literal const-ZERO branch, so `if (i_clear) state <= IDLE;`
      (IDLE a localparam) was not recognised. FIX: resolve the localparam and
      treat `if(S) state<=IDLE` as a clear iff IDLE's value == the value `state`
      takes in the ASYNC-RESET branch (and never for a NON-reset state localparam).

POSITIVE: the i_clear-shape FSM flush no longer false-TIMEOUTs (rc=0). A
directional-prefixed clear with a constant-literal clear (the name path,
independent of the structural path) is also covered. The positive MUST fail on
shipped v1.1.16 (rc=1 TIMEOUT) and pass on patched (rc=0 PASS).

§4.05 NEGATIVES (guard-relaxing, LOAD-BEARING):
  (a) a genuine TIMEOUT (output truly never asserts, no clear) still rc=1;
  (b) a genuine MISMATCH (measured != expected) still rc=1;
  (c) an ordinary enable input (`i_enable`→`enable`) is NOT misclassified as a
      clear, stays pinned all-ones (latency still measured) — rc=0 at its real
      latency (held inactive it would TIMEOUT);
  (d) a control that jams the FSM into a NON-reset state localparam
      (`if(S) state<=RUN`) is NOT treated as a clear — still rc=1.

Self-contained: locates the program via `Path(__file__).resolve().parent.parent`
with a `VIBE_PROGRAMS` env override; inline RTL fixtures; skips if iverilog/vvp
is unavailable. Run with `python3 -m pytest`.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ── locate the program under test ────────────────────────────────────────────
_PROGRAMS = Path(
    os.environ.get("VIBE_PROGRAMS",
                   str(Path(__file__).resolve().parent.parent))).resolve()
_GATE = _PROGRAMS / "latency_conformance_check.py"

_HAVE_TOOLS = bool(
    __import__("shutil").which("iverilog") and __import__("shutil").which("vvp"))

pytestmark = [
    pytest.mark.skipif(not _GATE.is_file(),
                       reason=f"latency_conformance_check.py not found at {_GATE}"),
    pytest.mark.skipif(not _HAVE_TOOLS,
                       reason="iverilog/vvp unavailable"),
]


# ── inline RTL fixtures ───────────────────────────────────────────────────────
# The motivating design: a 4-state FSM with async active-low reset and an
# `i_clear` that flushes the FSM to IDLE (IDLE a localparam). o_ready asserts
# only in OUTPUT, 4 posedges after i_start.
RTL_SIGNED_ADDER = r"""
module signedadder #(parameter DATA_WIDTH = 8)(
    input                       i_clk,
    input                       i_rst_n,
    input                       i_start,
    input                       i_enable,
    input                       i_mode,
    input                       i_clear,
    input  [DATA_WIDTH-1:0]     i_operand_a,
    input  [DATA_WIDTH-1:0]     i_operand_b,
    output reg [DATA_WIDTH-1:0] o_resultant_sum,
    output reg                  o_overflow,
    output reg                  o_ready,
    output reg [1:0]            o_status
);
    localparam [1:0] IDLE=2'b00, LOAD=2'b01, COMPUTE=2'b10, OUTPUT=2'b11;
    reg [1:0] state;
    reg [DATA_WIDTH-1:0] reg_a, reg_b;
    reg reg_mode;
    wire [DATA_WIDTH-1:0] sum_w = reg_mode ? (reg_a - reg_b) : (reg_a + reg_b);
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            state<=IDLE; o_status<=IDLE; o_resultant_sum<={DATA_WIDTH{1'b0}};
            o_overflow<=1'b0; o_ready<=1'b0;
            reg_a<={DATA_WIDTH{1'b0}}; reg_b<={DATA_WIDTH{1'b0}}; reg_mode<=1'b0;
        end else if (i_clear) begin
            state<=IDLE; o_status<=IDLE; o_resultant_sum<={DATA_WIDTH{1'b0}};
            o_overflow<=1'b0; o_ready<=1'b0;
        end else begin
            case (state)
                IDLE: begin o_ready<=1'b0;
                    if (i_enable && i_start) begin state<=LOAD; o_status<=LOAD; end
                    else begin state<=IDLE; o_status<=IDLE; end
                end
                LOAD: begin reg_a<=i_operand_a; reg_b<=i_operand_b; reg_mode<=i_mode;
                    state<=COMPUTE; o_status<=COMPUTE; end
                COMPUTE: begin o_resultant_sum<=sum_w; state<=OUTPUT; o_status<=OUTPUT; end
                OUTPUT: begin o_ready<=1'b1; state<=IDLE; o_status<=IDLE; end
                default: begin state<=IDLE; o_status<=IDLE; end
            endcase
        end
    end
endmodule
"""

# Name-path-only fixture: a directional-prefixed clear with a CONSTANT-LITERAL
# clear branch (no localparam). Recognised purely via the name prefix-strip
# (`i_clear`→`clear`), independent of the localparam structural path.
RTL_PREFIX_NAME_CLEAR = r"""
module prefixclr (
    input            i_clk,
    input            i_rst_n,
    input            i_start,
    input            i_clear,
    output reg       o_ready
);
    reg [2:0] cnt; reg run;
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n)      begin cnt<=3'b0; run<=1'b0; o_ready<=1'b0; end
        else if (i_clear)  begin cnt<=3'b0; run<=1'b0; o_ready<=1'b0; end  // const-literal clear
        else if (i_start)  begin run<=1'b1; cnt<=3'b0; o_ready<=1'b0; end
        else if (run) begin
            cnt <= cnt + 3'b1;
            if (cnt == 3'd3) begin o_ready<=1'b1; run<=1'b0; end
        end
    end
endmodule
"""

# (a) genuine TIMEOUT — o_done wired to constant 0, no clear control.
RTL_A_TIMEOUT = r"""
module gt_timeout (
    input        i_clk,
    input        i_rst_n,
    input        i_start,
    input  [7:0] i_data,
    output reg   o_done
);
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) o_done <= 1'b0;
        else          o_done <= 1'b0;
    end
endmodule
"""

# (b) genuine MISMATCH — asserts at a real latency that != --expect.
RTL_B_MISMATCH = r"""
module mm_mismatch (
    input        i_clk,
    input        i_rst_n,
    input        i_start,
    input  [7:0] i_data,
    output reg   o_ready
);
    reg [2:0] cnt; reg run;
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n)     begin cnt<=0; run<=0; o_ready<=0; end
        else if (i_start) begin run<=1; cnt<=0; o_ready<=0; end
        else if (run) begin
            cnt <= cnt + 1;
            if (cnt == 3'd2) begin o_ready<=1; run<=0; end
        end
    end
endmodule
"""

# (c) ordinary enable input — must NOT be misclassified as a clear; held ACTIVE
# (all-ones) so the gated design measures its real latency.
RTL_C_ENABLE = r"""
module en_keep (
    input        i_clk,
    input        i_rst_n,
    input        i_start,
    input        i_enable,
    input  [7:0] i_data,
    output reg   o_ready
);
    reg [2:0] cnt; reg run;
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n)                   begin cnt<=0; run<=0; o_ready<=0; end
        else if (i_enable && i_start)   begin run<=1; cnt<=0; o_ready<=0; end
        else if (run) begin
            cnt <= cnt + 1;
            if (cnt == 3'd3) begin o_ready<=1; run<=0; end
        end
    end
endmodule
"""

# (d) control that jams the FSM into a NON-reset state localparam (RUN != IDLE
# reset value). `i_complete` passes the clear-equiv NAME gate, but the
# localparam-resolve must compare against the async-reset value and REJECT it.
RTL_D_NONRESET_JAM = r"""
module nonreset_jam (
    input        i_clk,
    input        i_rst_n,
    input        i_start,
    input        i_complete,
    input  [7:0] i_data,
    output reg   o_ready
);
    localparam [1:0] IDLE=2'b00, RUN=2'b01, DONE=2'b10;
    reg [1:0] state;
    always @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n)          begin state<=IDLE; o_ready<=1'b0; end
        else if (i_complete)   begin state<=RUN;  o_ready<=1'b0; end  // NON-reset state
        else begin
            case (state)
                IDLE: if (i_start) state<=RUN;
                RUN:  state<=DONE;
                DONE: begin o_ready<=1'b1; state<=IDLE; end
            endcase
        end
    end
endmodule
"""


def _run_gate(rtl_text, *cli):
    """Write `rtl_text` to a temp .sv, run the gate, return (rc, report dict)."""
    with tempfile.TemporaryDirectory() as d:
        rtl = Path(d) / "dut.sv"
        rtl.write_text(rtl_text)
        jpath = Path(d) / "report.json"
        proc = subprocess.run(
            [sys.executable, str(_GATE), "--rtl", str(rtl),
             "--json", str(jpath), *cli],
            capture_output=True, text=True)
        report = json.loads(jpath.read_text()) if jpath.is_file() else {}
        return proc.returncode, report


# ── POSITIVE — the FP must now PASS (and fail on shipped) ─────────────────────
def test_positive_signed_adder_localparam_clear_no_longer_false_timeout():
    """The motivating FP: `i_clear` (localparam-IDLE flush) must be recognised
    and held inactive so o_ready asserts at the spec latency 4. On shipped
    v1.1.16 this is a false rc=1 TIMEOUT; patched is rc=0 PASS measured==4."""
    rc, rep = _run_gate(
        RTL_SIGNED_ADDER, "--top", "signedadder", "--event", "i_start",
        "--output", "o_ready", "--expect", "4",
        "--reset", "i_rst_n", "--reset-active-low")
    assert rc == 0, (
        f"expected rc=0 PASS, got rc={rc} verdict={rep.get('verdict')} "
        f"(this case FAILS on shipped v1.1.16 — the regression target)")
    assert rep.get("verdict") == "PASS"
    assert rep.get("measured_latency") == 4
    # i_clear must have been held inactive (in resets, not pinned all-ones).
    assert "i_clear" in (rep.get("resets") or [])


def test_positive_name_path_prefixed_clear_const_literal():
    """The NAME path independently: a directional-prefixed `i_clear` whose clear
    branch uses CONSTANT LITERALS (no localparam) must be recognised by the
    prefix-strip alone and held inactive → rc=0."""
    rc, rep = _run_gate(
        RTL_PREFIX_NAME_CLEAR, "--top", "prefixclr", "--event", "i_start",
        "--output", "o_ready", "--expect", "5",
        "--reset", "i_rst_n", "--reset-active-low")
    assert rc == 0, f"rc={rc} verdict={rep.get('verdict')}"
    assert rep.get("verdict") == "PASS"
    assert "i_clear" in (rep.get("resets") or [])


# ── §4.05 NEGATIVES — must stay rc-identical to shipped ───────────────────────
def test_negative_a_genuine_timeout_still_blocks():
    rc, rep = _run_gate(
        RTL_A_TIMEOUT, "--top", "gt_timeout", "--event", "i_start",
        "--output", "o_done", "--expect", "2",
        "--reset", "i_rst_n", "--reset-active-low")
    assert rc == 1 and rep.get("verdict") == "TIMEOUT"


def test_negative_b_genuine_mismatch_still_blocks():
    rc, rep = _run_gate(
        RTL_B_MISMATCH, "--top", "mm_mismatch", "--event", "i_start",
        "--output", "o_ready", "--expect", "7",
        "--reset", "i_rst_n", "--reset-active-low")
    assert rc == 1 and rep.get("verdict") == "MISMATCH"


def test_negative_c_enable_not_misclassified_as_clear():
    """`i_enable` (→`enable` after prefix-strip) must NOT be in the clear
    allowlist — it stays pinned all-ones (ACTIVE). The design then measures its
    real latency (5). Held inactive it would TIMEOUT, so a PASS here proves the
    enable was kept active (no misclassification)."""
    rc, rep = _run_gate(
        RTL_C_ENABLE, "--top", "en_keep", "--event", "i_start",
        "--output", "o_ready", "--expect", "5",
        "--reset", "i_rst_n", "--reset-active-low")
    assert rc == 0 and rep.get("verdict") == "PASS", (
        f"rc={rc} verdict={rep.get('verdict')} — i_enable must stay ACTIVE")
    assert "i_enable" in (rep.get("other_inputs_held_constant") or []), (
        "i_enable must remain in the all-ones-pinned others, NOT be held inactive")
    assert "i_enable" not in (rep.get("resets") or [])


def test_negative_d_nonreset_state_localparam_not_a_clear():
    """A control that jams the FSM into a NON-reset state localparam (RUN, value
    1, != IDLE reset value 0) must NOT be treated as a clear — the genuine
    permanent-jam TIMEOUT must still hard-block (rc=1), NOT be relaxed."""
    rc, rep = _run_gate(
        RTL_D_NONRESET_JAM, "--top", "nonreset_jam", "--event", "i_start",
        "--output", "o_ready", "--expect", "4",
        "--reset", "i_rst_n", "--reset-active-low")
    assert rc == 1, (
        f"expected rc=1 (jam not relaxed), got rc={rc} "
        f"verdict={rep.get('verdict')} cands={rep.get('structural_clear_equiv_candidates')}")
    # i_complete must NOT appear as a structural clear-equivalent candidate.
    assert "i_complete" not in (rep.get("structural_clear_equiv_candidates") or {})


# ── unit-level: the two fixed classifiers (no sim) ───────────────────────────
def _import_gate():
    import importlib.util
    sys.path.insert(0, str(_PROGRAMS))
    spec = importlib.util.spec_from_file_location("lcc_under_test", _GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_unit_name_prefix_strip_clear():
    L = _import_gate()
    for n in ("clear", "i_clear", "o_clear", "i_clr", "i_flush",
              "io_clear", "in_clear", "out_clr"):
        assert L._looks_like_clear(n), n
    # ordinary data/enable must NOT be a clear after prefix-strip.
    for n in ("i_enable", "enable", "i_data", "i_mode", "i_operand_a"):
        assert not L._looks_like_clear(n), n


def test_unit_localparam_resolved_structural_clear():
    L = _import_gate()
    sc = {"i_rst_n", "i_start", "i_enable", "i_mode", "i_clear"}
    cands = L.detect_structural_clear_equiv(RTL_SIGNED_ADDER, "signedadder", sc)
    assert cands.get("i_clear") is False  # active-HIGH clear → held LOW
    # the NON-reset jam control must NOT be detected.
    dc = L.detect_structural_clear_equiv(
        RTL_D_NONRESET_JAM, "nonreset_jam",
        {"i_rst_n", "i_start", "i_complete"})
    assert "i_complete" not in dc


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
