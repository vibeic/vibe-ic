#!/usr/bin/env python3
"""ORGANIC #770 round-2 — Part B: rtl_hygiene_lint.py provenance/advisory layer.

The reopen (#770 round-2, Part B) found 5 residual prose-FPs in
rtl_hygiene_lint.py that STILL hard-block (rc=1) correct, compilable,
spec-faithful RTL because the rtl_hygiene WARNs were not routed through the
shared provenance/confidence layer (programs/_provenance.py) and 2 rules
over-fire structurally. This test reproduces each residual FP, asserts it now
flips to ADVISORY / PASS (rc=0), and pins the §4.05 NO-LEAK boundary: every
STRUCTURAL negative still hard-BLOCKs (rc=1).

The 4 FP shapes (named structural shapes from the digest):
  1. unread-reg on a CDC write-domain double-flop SYNCHRONIZER stage with no
     reader in this submodule (async_filo_0001 `wq2_rptr`).
  2. reset-boundary-residual-enable — an UNCORROBORATED level-enable heuristic
     (axi_tap_0001 `awvalid_q`/`wvalid_q`; axi_tap_0009 adds `timeout_flag_q`).
  3. case-no-default on a fully-enumerated SYMBOLIC-LOCALPARAM FSM
     (binary_search_tree_sorting_0001 `top_state`).
  4. multidriven-register on an INTEGER FOR-LOOP INDEX `i` reused across two
     always blocks (axis_mux_0001 `i`).

§4.05 NO-LEAK (must STILL hard-block, rc=1):
  - a genuinely multi-driven DATA register across two real always blocks;
  - a non-fully-enumerated symbolic case with no default (missing a state);
  - a truly dead/unread reg written with COMPUTED logic (not a sync flop);
  - a genuine DATA reg named like a loop index but never used as one.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "rtl_hygiene_lint.py"
assert PROG.exists()


def _run(args):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True)


def _lint(tmp_path, sv, name="dut.sv", severity="INFO"):
    """Write `sv`, lint at the given severity, return (proc, findings-list)."""
    f = tmp_path / name
    f.write_text(sv)
    jpath = tmp_path / "out.json"
    proc = subprocess.run(
        [sys.executable, str(PROG), "--severity", severity,
         "--json", str(jpath), str(f)],
        capture_output=True, text=True)
    findings = json.loads(jpath.read_text()) if jpath.exists() else []
    return proc, findings


def _by_rule(findings, rule):
    return [f for f in findings if f["rule"] == rule]


# ===========================================================================
# FP fixtures (the named structural shapes) — now flip to ADVISORY / PASS.
# ===========================================================================

# FP1 — async_filo_0001 `wq2_rptr`: a CDC write-domain double-flop synchronizer
# stage. `wq2_rptr` is reset to 0, then COPIES `wq1_rptr` straight through; its
# reader (the full-flag comparison) lives in a SIBLING module / other domain.
FP1_SYNC_PASSTHROUGH = """
module async_filo_wptr(
    input  wclk, input rclk, input wrst_n,
    input  [3:0] rptr_in,
    output reg [3:0] waddr
);
    reg [3:0] wbin;
    reg [3:0] rptr_gray;
    reg [3:0] wq1_rptr;
    reg [3:0] wq2_rptr;
    // read-clock domain: register the read pointer
    always @(posedge rclk or negedge wrst_n) begin
        if (!wrst_n) rptr_gray <= 4'd0;
        else         rptr_gray <= rptr_in;
    end
    // write-clock domain: 2-flop CDC synchroniser of the rclk-domain pointer.
    // wq2_rptr is the synchronised pointer; it has no reader in this submodule
    // (the unread-reg heuristic fires) but it is a genuine CDC synchronizer.
    always @(posedge wclk or negedge wrst_n) begin
        if (!wrst_n) begin
            wq1_rptr <= 4'd0;
            wq2_rptr <= 4'd0;
        end else begin
            wq1_rptr <= rptr_gray;
            wq2_rptr <= wq1_rptr;
        end
    end
    always @(posedge wclk or negedge wrst_n) begin
        if (!wrst_n) wbin <= 4'd0;
        else         wbin <= wbin + 1'b1;
    end
    always @(*) waddr = wbin;
endmodule
"""


def test_fp1_unread_sync_passthrough_is_advisory(tmp_path):
    proc, findings = _lint(tmp_path, FP1_SYNC_PASSTHROUGH)
    hits = _by_rule(findings, "unread-reg")
    # `wq2_rptr` is still DETECTED (it has no reader here) but as ADVISORY only.
    wq2 = [h for h in hits if h["symbol"] == "wq2_rptr"]
    assert wq2, f"expected wq2_rptr to be detected (advisory); got {findings}"
    assert all(h["block_eligible"] is False for h in wq2)
    assert all(h["severity"] == "INFO" for h in wq2)
    assert all("ORGANIC #770" in h["advisory_note"] for h in wq2)
    # the FP no longer hard-blocks
    assert proc.returncode == 0


# FP2 — axi_tap_0001 / axi_tap_0009: an UNCORROBORATED level-enable heuristic.
FP2_AXI_TAP = """
module axi_tap(
    input  aclk, input aresetn,
    input  awvalid, input awready,
    input  wvalid,  input wready,
    input  to_tick,
    output reg awvalid_q, output reg wvalid_q, output reg timeout_flag_q
);
    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) awvalid_q <= 1'b0;
        else if (awvalid) awvalid_q <= awready;
    end
    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) wvalid_q <= 1'b0;
        else if (wvalid) wvalid_q <= wready;
    end
    always @(posedge aclk or negedge aresetn) begin
        if (!aresetn) timeout_flag_q <= 1'b0;
        else if (to_tick) timeout_flag_q <= 1'b1;
    end
endmodule
"""


def test_fp2_reset_boundary_residual_enable_is_advisory(tmp_path):
    proc, findings = _lint(tmp_path, FP2_AXI_TAP)
    hits = _by_rule(findings, "reset-boundary-residual-enable")
    assert hits, f"expected the rule to be detected (advisory); got {findings}"
    syms = {h["symbol"] for h in hits}
    # all three axi_tap_0009 registers are picked up
    assert {"awvalid_q", "wvalid_q", "timeout_flag_q"} <= syms
    assert all(h["block_eligible"] is False for h in hits)
    assert all(h["severity"] == "INFO" for h in hits)
    # the FP no longer hard-blocks
    assert proc.returncode == 0


# FP3 — binary_search_tree_sorting_0001 `top_state`: a fully-enumerated FSM whose
# labels are all state-localparams of known value covering the 2-bit selector.
FP3_SYMBOLIC_FSM = """
module binary_search_tree_sorting(
    input clk, input rst_n, input start,
    output reg done
);
    localparam [1:0] S_IDLE  = 2'd0;
    localparam [1:0] S_BUILD = 2'd1;
    localparam [1:0] S_SORT  = 2'd2;
    localparam [1:0] S_DONE  = 2'd3;
    reg [1:0] top_state;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) top_state <= S_IDLE;
        else begin
            case (top_state)
                S_IDLE:  top_state <= start ? S_BUILD : S_IDLE;
                S_BUILD: top_state <= S_SORT;
                S_SORT:  top_state <= S_DONE;
                S_DONE:  top_state <= S_IDLE;
            endcase
        end
    end
    always @(*) done = (top_state == S_DONE);
endmodule
"""


def test_fp3_symbolic_localparam_case_is_exhaustive(tmp_path):
    proc, findings = _lint(tmp_path, FP3_SYMBOLIC_FSM)
    # a fully-enumerated symbolic-localparam case is recognised as exhaustive →
    # NO case-no-default finding at all.
    assert not _by_rule(findings, "case-no-default"), (
        f"fully-enumerated symbolic FSM must be exhaustive; got {findings}")
    assert proc.returncode == 0


# FP4 — axis_mux_0001 `i`: an integer for-loop index reused across two clocked
# always blocks (the multidriven rule's different-clocking firing path).
FP4_LOOP_INDEX = """
module axis_mux(
    input  aclk, input bclk, input rst_n,
    input  [1:0] sel, input [31:0] in0, input [31:0] in1,
    output reg [31:0] aout, output reg [31:0] bout
);
    integer i;
    always @(posedge aclk or negedge rst_n) begin
        if (!rst_n) aout <= 32'd0;
        else for (i = 0; i < 2; i = i + 1) aout <= aout | (sel[i] ? in1 : in0);
    end
    always @(posedge bclk or negedge rst_n) begin
        if (!rst_n) bout <= 32'd0;
        else for (i = 0; i < 2; i = i + 1) bout <= bout | (sel[i] ? in1 : in0);
    end
endmodule
"""


def test_fp4_loop_index_not_multidriven(tmp_path):
    proc, findings = _lint(tmp_path, FP4_LOOP_INDEX)
    multi = _by_rule(findings, "multidriven-register")
    assert not any(h["symbol"] == "i" for h in multi), (
        f"loop-index `i` must not false-fire as multidriven; got {findings}")
    assert proc.returncode == 0


def test_fp4_genvar_loop_not_multidriven(tmp_path):
    # a genvar used as a generate-for control variable is excluded too.
    sv = """
module gen_top(input clk, input [3:0] d, output [3:0] q);
    genvar g;
    reg [3:0] r;
    generate
      for (g = 0; g < 4; g = g + 1) begin : b
        always @(posedge clk) r[g] <= d[g];
      end
    endgenerate
    assign q = r;
endmodule
"""
    proc, findings = _lint(tmp_path, sv, name="gen.sv")
    assert not any(h["symbol"] == "g"
                   for h in _by_rule(findings, "multidriven-register"))
    assert proc.returncode == 0


# ===========================================================================
# §4.05 NO-LEAK — every STRUCTURAL negative STILL hard-BLOCKs (rc=1).
# ===========================================================================

# NL1 — a genuinely multi-driven DATA register across two real always blocks.
NL1_MULTIDRIVEN_DATA = """
module dual_writer(
    input  aclk, input bclk, input rst_n,
    input  [7:0] a_in, input [7:0] b_in,
    output reg [7:0] shared_q
);
    always @(posedge aclk or negedge rst_n) begin
        if (!rst_n) shared_q <= 8'd0;
        else        shared_q <= a_in;
    end
    always @(posedge bclk or negedge rst_n) begin
        if (!rst_n) shared_q <= 8'd0;
        else        shared_q <= b_in;
    end
endmodule
"""


def test_noleak_genuine_multidriven_data_still_blocks(tmp_path):
    proc, findings = _lint(tmp_path, NL1_MULTIDRIVEN_DATA, severity="WARN")
    hits = _by_rule(findings, "multidriven-register")
    assert any(h["symbol"] == "shared_q" and h["severity"] == "WARN"
               and h["block_eligible"] is True for h in hits), (
        f"a real multi-driven DATA register must still hard-block; got {findings}")
    assert proc.returncode == 1


# NL2 — a non-fully-enumerated symbolic case with no default (missing S_SORT).
NL2_PARTIAL_SYMBOLIC_CASE = """
module partial_fsm(
    input clk, input rst_n, input start,
    output reg done
);
    localparam [1:0] S_IDLE  = 2'd0;
    localparam [1:0] S_BUILD = 2'd1;
    localparam [1:0] S_DONE  = 2'd3;
    reg [1:0] top_state;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) top_state <= S_IDLE;
        else begin
            case (top_state)
                S_IDLE:  top_state <= start ? S_BUILD : S_IDLE;
                S_BUILD: top_state <= S_DONE;
                S_DONE:  top_state <= S_IDLE;
            endcase
        end
    end
    always @(*) done = (top_state == S_DONE);
endmodule
"""


# ORGANIC #770 r4 — NL2 is a CLOCKED (sequential) FSM. A partial case in a
# clocked block cannot infer a LATCH (the state reg HOLDS on an unlisted code),
# so it is now ADVISORY, not a hard block. The §4.05 no-leak moves to the
# COMBINATIONAL partial case below, which DOES risk a latch and STILL hard-WARNs.
NL2_PARTIAL_COMBINATIONAL_CASE = """
module partial_comb(input [1:0] sel, output reg [3:0] o);
    localparam [1:0] A = 2'd0, B = 2'd1, C = 2'd3;
    always @(*) begin
        case (sel)
            A: o = 4'd0;
            B: o = 4'd1;
            C: o = 4'd2;
        endcase
    end
endmodule
"""


def test_770r4_clocked_partial_case_is_advisory(tmp_path):
    """ORGANIC #770 r4 RE-ANCHOR: a partial case inside a CLOCKED always block is
    ADVISORY (no latch can be inferred — the state reg holds), reported but NOT a
    hard block."""
    proc, findings = _lint(tmp_path, NL2_PARTIAL_SYMBOLIC_CASE, severity="INFO")
    hits = _by_rule(findings, "case-no-default")
    assert hits and all(h["block_eligible"] is False for h in hits), findings


def test_noleak_partial_combinational_case_still_blocks(tmp_path):
    """§4.05 NO-LEAK: a partial case in a COMBINATIONAL `always @(*)` DOES risk a
    latch → still WARNs/block-eligible (rc 1)."""
    proc, findings = _lint(tmp_path, NL2_PARTIAL_COMBINATIONAL_CASE,
                           severity="WARN")
    hits = _by_rule(findings, "case-no-default")
    assert any(h["severity"] == "WARN" and h["block_eligible"] is True
               for h in hits), (
        f"a combinational non-exhaustive case must still WARN/block; got {findings}")
    assert proc.returncode == 1


# NL3 — a truly dead reg written with COMPUTED logic (NOT a sync pass-through).
NL3_DEAD_COMPUTED_REG = """
module dead_logic(
    input clk, input rst_n,
    input [7:0] a, input [7:0] b,
    output reg [7:0] y
);
    reg [7:0] scratch;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) scratch <= 8'd0;
        else        scratch <= a & b;
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) y <= 8'd0;
        else        y <= a + b;
    end
endmodule
"""


def test_noleak_dead_computed_reg_still_blocks(tmp_path):
    proc, findings = _lint(tmp_path, NL3_DEAD_COMPUTED_REG, severity="WARN")
    hits = _by_rule(findings, "unread-reg")
    assert any(h["symbol"] == "scratch" and h["severity"] == "WARN"
               and h["block_eligible"] is True for h in hits), (
        f"a truly dead computed-logic reg must still WARN/block; got {findings}")
    assert proc.returncode == 1


# NL4 — a DATA reg literally named like a loop index `i` but NEVER used as a
# loop control variable: it is a genuine multi-driven register and must block.
NL4_DATA_REG_NAMED_I = """
module data_named_i(
    input aclk, input bclk, input rst_n,
    input [7:0] x, input [7:0] z,
    output reg [7:0] i
);
    always @(posedge aclk or negedge rst_n) begin
        if (!rst_n) i <= 8'd0;
        else        i <= x;
    end
    always @(posedge bclk or negedge rst_n) begin
        if (!rst_n) i <= 8'd0;
        else        i <= z;
    end
endmodule
"""


def test_noleak_data_reg_named_i_still_blocks(tmp_path):
    proc, findings = _lint(tmp_path, NL4_DATA_REG_NAMED_I, severity="WARN")
    hits = _by_rule(findings, "multidriven-register")
    assert any(h["symbol"] == "i" and h["block_eligible"] is True for h in hits), (
        f"a real multi-driven DATA reg named `i` must still block; got {findings}")
    assert proc.returncode == 1


# A sync-passthrough that IS read anywhere produces NO finding at all (sanity:
# the downgrade path only triggers on the no-reader case).
def test_sync_passthrough_with_reader_no_finding(tmp_path):
    sv = """
module synced(input clk, input rst_n, input [3:0] d, output reg [3:0] o);
    reg [3:0] q1;
    reg [3:0] q2;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin q1 <= 0; q2 <= 0; end
        else begin q1 <= d; q2 <= q1; end
    end
    always @(*) o = q2;   // q2 IS read here
endmodule
"""
    proc, findings = _lint(tmp_path, sv, name="synced.sv")
    assert not _by_rule(findings, "unread-reg")
    assert proc.returncode == 0


# ===========================================================================
# #478 END-STATE — DIRECT-write a tmp_path artifact and invoke the real program
# via subprocess with a returncode assert (both an FP→PASS and a no-leak→BLOCK).
# ===========================================================================

def test_478_endstate_fp_passes(tmp_path):
    """A directly-written FP artifact lints to rc=0 via the real program."""
    art = tmp_path / "fp_artifact.sv"
    art.write_text(FP4_LOOP_INDEX)
    r = _run([str(art)])
    assert r.returncode == 0, (
        f"FP artifact must not hard-block; stdout={r.stdout}")


def test_478_endstate_structural_negative_blocks(tmp_path):
    """A directly-written STRUCTURAL-negative artifact lints to rc=1."""
    art = tmp_path / "noleak_artifact.sv"
    art.write_text(NL1_MULTIDRIVEN_DATA)
    r = _run([str(art)])
    assert r.returncode == 1, (
        f"structural negative must still hard-block; stdout={r.stdout}")


# ── Step-2.7 adversarial-review remediation (reproduced §4.05 findings) ──────
_MD_INTEGER_RACE = """
module m(input clk1, input clk2, output reg [31:0] o);
  integer acc;
  always @(posedge clk1) acc <= acc + 1;
  always @(posedge clk2) acc <= acc - 1;
  always @(*) o = acc;
endmodule
"""

_MD_LOOP_INDEX = """
module m(input [3:0] a, input [3:0] b, output reg [3:0] x, output reg [3:0] y);
  integer i;
  always @(*) begin x = 0; for (i=0;i<4;i=i+1) x = x ^ a[i]; end
  always @(*) begin y = 0; for (i=0;i<4;i=i+1) y = y ^ b[i]; end
endmodule
"""

_DEAD_SAME_DOMAIN_COPY = """
module m(input clk, input d, output reg o);
  reg q1, q2;
  always @(posedge clk) q1 <= d;
  always @(posedge clk) q2 <= q1;
  always @(*) o = q1;
endmodule
"""


def test_770r2_review_integer_accumulator_race_still_warns(tmp_path):
    """Finding #4 §4.05: an `integer acc` written by NBA in two DIFFERENT clock
    domains is a genuine multi-driven STATE race — `integer` is the canonical
    accumulator idiom, so it must STILL WARN (not be excluded as a loop index)."""
    _proc, findings = _lint(tmp_path, _MD_INTEGER_RACE, severity="WARN")
    md = [f for f in _by_rule(findings, "multidriven-register")
          if f["symbol"] == "acc"]
    assert md, f"integer accumulator race must still WARN; got {findings}"


def test_770r2_review_pure_loop_index_not_multidriven(tmp_path):
    """Finding #4 new-path: an `integer i` used ONLY as a for-loop control var in
    two comb blocks (no clocked NBA write) is NOT a multi-driven register."""
    _proc, findings = _lint(tmp_path, _MD_LOOP_INDEX, severity="WARN")
    md = [f for f in _by_rule(findings, "multidriven-register")
          if f["symbol"] == "i"]
    assert not md, f"loop index `i` must not WARN multidriven; got {md}"


def test_770r2_review_dead_same_domain_copy_still_warns(tmp_path):
    """Finding #7 §4.05: a `q2 <= q1` copy in the SAME single clock domain whose
    q2 is read NOWHERE is just a dead reg (not a CDC synchronizer) → still WARNs
    unread-reg, block-eligible."""
    _proc, findings = _lint(tmp_path, _DEAD_SAME_DOMAIN_COPY, severity="WARN")
    ur = [f for f in _by_rule(findings, "unread-reg") if f["symbol"] == "q2"]
    assert ur, f"dead same-domain copy q2 must still WARN; got {findings}"
    assert all(f.get("block_eligible", True) for f in ur), ur


def test_770r2_review_sync_passthrough_helper_distinguishes_cdc():
    """Finding #7 direct: the sync-passthrough classifier downgrades a real CDC
    2-flop (different-domain source) but NOT a same-domain dead copy."""
    import rtl_hygiene_lint as R
    assert R._is_sync_passthrough_reg(_DEAD_SAME_DOMAIN_COPY, "q2") is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
