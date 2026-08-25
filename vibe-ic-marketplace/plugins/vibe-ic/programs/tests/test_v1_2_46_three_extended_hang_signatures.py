#!/usr/bin/env python3
r"""v1.2.46 — three WEAK hang-heuristic extensions (ADVISORY ONLY, §4.05 no-leak).

v1.2.45 pinned STRONG (combinational self-loop, forever-in-@*) and WEAK
(dead-signal) heuristics. The 6 file-named hang subjects in the CVDP run
(mem_allocator / manchester_enc / ir_receiver / fifo_async / Attenuator /
axi_alu) HANG by cocotb watchdog but trip NEITHER tier — 0/6 fire on STRONG,
0/6 fire on WEAK (dead-signal alone). The 2026-06-26 RCA pinned the
real-cause deep split:

  1. fifo_async: gray-code next-cycle comparator (`full`/`empty` compared
     against `_next` instead of registered gray) → cycle-off-by-one and
     infinite-write-loop in cocotb tail.
  2. ir_receiver: handshake `valid` pulse-1-cycle (`ir_frame_valid <= 1`
     in finish state without a latched holding-1 frame) → cocotb
     `await RisingEdge(ir_frame_valid)` hangs under watcher clock-gate.
  3. axi_alu: module-port-list ↔ test runner's `dut.<port>` access
     mismatch (`axi_awlen_i` referenced by test but missing in RTL
     module decl) → cocotb `init_dut(dut.axi_awlen_i)` raises
     AttributeError → process death under watchdog.

v1.2.46 extends the heuristic set by 3 NEW WEAK signatures:

   _gray_code_next_cycle_signatures      — fifo_async class
   _handshake_one_cycle_pulse_signatures — ir_receiver class
   _port_mismatch_signatures             — axi_alu class

Invariants preserved (§4.05 no-leak):
  (a) All 3 NEW signatures contribute to `signatures` only; they DO NOT
      lift `predicted_hang` to True.
  (b) `predicted_hang = True` is held strictly STRONG (combinational
      self-loop, forever-in-@*).
  (c) cvdp_gate.py audit narrative lists the 3 new WEAK signals as
      advisory-only — never flips pass verdict.

Run:  python3 -m py_compile programs/tests/test_v1_2_46_three_extended_hang_signatures.py
-or-  python3 -m pytest -q programs/tests/test_v1_2_46_three_extended_hang_signatures.py
"""
import os
import sys
from _hostpaths import repo_path_opt  # noqa: E402

PLUGIN_BENCH = str(repo_path_opt("vibe-ic-marketplace/plugins/vibe-ic/benchmark"))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(TESTS_DIR)


def _load():
    sys.path.insert(0, PLUGIN_BENCH)
    import sim_hang_detect as H   # noqa: E402
    import cvdp_gate as G          # noqa: E402
    return H, G


# ── (1) gray-code next-cycle comparator WEAK signature fires ─────────────────────
def test_gray_code_next_cycle_comparator_signature_fires():
    """`full = (w_gray_next == { ... })` ships a WEAK signature; it MUST
    NOT lift `predicted_hang` to True (§4.05 no-leak)."""
    H, G, *_ = _load()
    code = (
        "module fifo_async(\n"
        "  input  logic [3:0] w_gray, r_gray,\n"
        "  output logic full, empty);\n"
        "  assign full  = (w_gray_next == {~r_gray_sync[3:3-1], r_gray_sync[3-2:0]});\n"
        "  assign empty = (r_gray_next == w_gray_sync2);\n"
        "endmodule\n"
    )
    ok, why, sigs = H.predict_hang(code)
    assert sigs, f"expected ≥1 WEAK signature, got {sigs!r}"
    assert any('gray-code' in s or 'next-cycle' in s for s in sigs), \
        f"expected gray-code WEAK signature, got {sigs!r}"
    assert ok is False, "WEAK must NOT lift predicted_hang to True"


# ── (2) handshake-valid one-cycle-pulse WEAK signature fires ─────────────────────
def test_handshake_one_cycle_pulse_signature_fires():
    """`valid <= 1; ... (80 lines later, in next-state) valid <= 0;` for the
    SAME signal ships a WEAK signature; MUST NOT lift predicted_hang."""
    H, *_ = _load()
    # We deliberately write the 0-reset far enough away (>5 lines) to cross
    # the line window the heuristic uses. The ''='' (any same-signal match)
    # within 80 lines is what trips the heuristic.
    code = "\n".join([
        "module ir_receiver(",
        "  input  logic clk, input  logic rst_n,",
        "  output logic ir_frame_valid);",
        "  typedef enum logic [1:0] {IDLE, FINISH, DONE} state_t;",
        "  state_t state, next_state;",
        "  always_ff @(posedge clk or negedge rst_n) begin",
        "    if (!rst_n) state <= IDLE;",
        "    else        state <= next_state;",
        "  end",
        "  always_comb begin",
        "    next_state = IDLE;",
        "    ir_frame_valid = 1'b0;",  # default-low
        "    case (state)",
        "      FINISH: begin",
        "        ir_frame_valid <= 1'b1;  # path-A: set to 1",
        "        next_state = DONE;",
        "      end",
        "      DONE: begin",
        "        next_state = IDLE;",
        "      end",
        "    endcase",
        "    case (next_state)",
        "      IDLE: ir_frame_valid <= 1'b0;",  # immediate reset to 0
        "      default: ;",
        "    endcase",
        "  end",
        "endmodule",
    ])
    ok, why, sigs = H.predict_hang(code)
    assert sigs, f"expected ≥1 WEAK signature, got {sigs!r}"
    assert any('pulse-1-cycle' in s or 'ir_frame_valid' in s for s in sigs), \
        f"expected handshake-pulse WEAK signature, got {sigs!r}"
    # NO STRONG trip — pulse is WEAK unless the structure is also a forever-loop or self-oscillator.
    assert ok is False, \
        f"pulse-1-cycle alone MUST NOT lift predicted_hang (got {ok=})"


# ── (3) module port-list ↔ expected-port-set mismatch WEAK signature fires ─────────────────────
def test_port_mismatch_signature_fires_only_when_expected_ports_supplied():
    H, *_ = _load()
    code = (
        "module axi_alu(\n"
        "  input  logic clk,\n"
        "  input  logic [3:0] a, b,\n"
        "  output logic [3:0] y);\n"
        "  always_ff @(posedge clk) y <= a + b;\n"
        "endmodule\n"
    )
    # Without expected_ports (the default `predict_hang` caller path), the
    # port-mismatch heuristic returns no signature — we do NOT fire on
    # bare one-sided evidence (would leak against any missing-port design).
    ok_default, _why_default, sigs_default = H.predict_hang(code)
    assert not any('port-list' in s for s in sigs_default), \
        f"predict_hang() (no expected_ports) MUST NOT fire port-mismatch, " \
        f"got {sigs_default!r}"
    # With expected_ports, fire:
    ok, _why, sigs = H.predict_hang_extended(
        code, expected_ports=['axi_awlen_i', 'axi_awburst_i'])
    assert any('port-list' in s and 'axi_awlen_i' in s for s in sigs), \
        f"predict_hang_extended() with missing-port MUST fire port-mismatch, " \
        f"got {sigs!r}"
    assert ok is False, \
        f"port-mismatch WEAK alone MUST NOT lift predicted_hang (got {ok=})"


# ── (4) clean module: no false flag across WEAK heuristics ─────────────────────
def test_clean_module_does_not_fire_any_weak_signature():
    """A well-written counter `i <- i+1` ships ZERO WEAK signatures: no
    gray-code suspicious compare, no pulse-1-cycle handshake, no missing
    ports. The §4.05 no-leak goal is to keep the heuristic CAREFUL."""
    H, *_ = _load()
    code = (
        "module counter(\n"
        "  input  logic clk, input  logic rst_n, input  logic en,\n"
        "  output logic [7:0] cnt);\n"
        "  always_ff @(posedge clk or negedge rst_n) begin\n"
        "    if (!rst_n) cnt <= 8'h00;\n"
        "    else if (en) cnt <= cnt + 8'h01;\n"
        "  end\n"
        "endmodule\n"
    )
    ok, why, sigs = H.predict_hang(code)
    assert ok is False, f"clean counter must not be flagged STRONG: {why=}"
    # No WEAK signatures either: nothing in the heuristic's reach fires.
    assert not any('WEAK' in s for s in sigs), \
        f"clean counter must not produce any WEAK signature, got {sigs!r}"


# ── (5) regression-guard: predicted_hang is STILL STRONG-only ─────────────────
def test_predicted_hang_still_strong_only_across_new_signals():
    """The combined module with ONE WEAK signal AND NO STRONG signal MUST
    return predicted_hang=False. The STRONG lift remains strictly
    combinational self-loop OR forever-in-@*."""
    H, *_ = _load()
    # Construct a gray-next-comparator mixed with the dead-signal cluster
    # (no combinational self-loop and no forever-loop, so NO STRONG):
    code = (
        "module mixed_weak(input  logic [3:0] w_gray, r_gray,\n"
        "                  output logic full, empty);\n"
        "  assign full  = (w_gray_next == {~r_gray_sync[3:3-1], r_gray_sync[3-2:0]});\n"
        "  assign empty = (r_gray_next == w_gray_sync2);\n"
        "  always_comb begin\n"
        "    case (state)\n"
        "      FINISH: ir_frame_valid <= 1'b1; ir_frame_valid <= 1'b0;\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"
    )
    ok, _why, sigs = H.predict_hang(code)
    assert ok is False, f"WEAK-only module must NOT lift predicted_hang: {ok=}"
    assert sigs, f"signatures must still surface the WEAK, got {sigs!r}"


# ── (6) AST no-leak gate: cvdp_gate.py does NOT flip pass on hang_predicted ─────────────────
def test_cvdp_gate_no_flips_pass_on_hang_predicted():
    """§4.05 no-leak invariant: the v1.2.45 gate that records
    `entry["hang_predicted"]`/`["hang_reason"]`/`["hang_signatures"]`
    does NOT write any rule that flips `entry["pass"] = ...hang_predicted...RHS...`.
    Even after v1.2.46 adds 3 NEW WEAK heuristics, the gate must STAY
    advisory-only — never BLOCK on `predicted_hang`"""
    H, G, *_ = _load()
    gate_src = G.__file__
    with open(gate_src, "r", encoding="utf-8", errors="replace") as f:
        src = f.read()
    # Look for the rule-pair shape:
    #   line assigning entry["pass"] (or .get("pass")) to anything that
    #   has hang_predicted or hang_reason or hang_signatures on the RHS.
    # If such assignment exists, FAIL. Otherwise PASS.
    #
    # We do a regex search for `pass` near hang_predicted on the same line:
    bad = []
    lines = src.splitlines()
    for ln in lines:
        # Skip comments / docstrings (heuristic; not perfect).
        code_core = ln.split("//", 1)[0]
        # Ragged pattern: any assignment-style line where `pass` appears
        # on LHS AND `hang_predicted` / `hang_reason` / `hang_signatures`
        # appears on RHS — i.e. SAME line has BOTH.
        if "hang_predicted" in code_core or "hang_reason" in code_core \
                or "hang_signatures" in code_core:
            # If on the SAME line a `pass` identifier exists too, that's a leak.
            if "pass" in code_core:
                bad.append(ln.strip())
    # Also a stricter scan: in `entry[...]` ops the same `entry["pass"]` appears on both sides.
    assert not bad, (
        "must NOT have any rule where `pass` and `hang_*` appear on the same "
        "LHS-RHS line (§4.05 no-leak):\n  " + "\n  ".join(bad[:5]))
