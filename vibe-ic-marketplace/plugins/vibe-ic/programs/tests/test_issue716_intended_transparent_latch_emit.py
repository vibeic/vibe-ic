#!/usr/bin/env python3
"""ORGANIC #716 — EMIT-GATE FALSE-BLOCK on an INTENDED transparent latch.

The harness_exact_selfverify gate B (`verilator --lint-only -Wall`) is the SOLE
EMIT PATH (gate-as-sole-emit-path). On VerilogEval-v2 Prob145_circuit8 it
HARD-BLOCKED a functionally-correct design

    always @(*) if (clock) p = a;     // intended transparent (level) latch
    always @(negedge clock) q <= p;

because verilator emits `%Warning-LATCH: Latch inferred for signal 'p'`. That
design PASSES the hidden VerilogEval TB 0 mismatches / 240 samples, and the
real scorer runs ONLY iverilog+vvp (it NEVER lints), so the LATCH block was a
PURE FALSE-BLOCK: it silently dropped a correct submission and lowered pass@1.

A transparent latch is the CORRECT answer for a level-sensitive / sequential
spec. So gate B now DOWNGRADES (allows) a `%Warning-LATCH` IFF it comes from a
CLEAN single clock-guarded transparent-latch idiom (one `if(<clk>) sig = ...;`,
no else / else-if / case, sig assigned once). It STILL BLOCKS the genuine
ACCIDENTAL-latch bug shapes the hidden TB would catch:

  * a NON-clock data-enable guard  (`if (en) y = d;`)  — forgot the else in
    logic meant to be a pure combinational function;
  * a multi-arm `if/else-if` (or `case`) that forgot a branch;
  * `%Warning-CASEINCOMPLETE` (a case missing its default).

§4.05 NEGATIVE NO-LEAK is load-bearing here: this file builds BOTH the intended
latch (must now EMIT) AND three accidental latches (must STILL BLOCK), plus
reconfirms the existing width-truncation block is untouched.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))
import harness_exact_selfverify as H  # noqa: E402

_HAS_VERILATOR = shutil.which("verilator") is not None
_HAS_AB = shutil.which("iverilog") is not None and _HAS_VERILATOR


# ── fixtures ─────────────────────────────────────────────────────────────
# POSITIVE: the intended transparent latch (the exact Prob145_circuit8 idiom).
INTENDED_LATCH = """\
module TopModule (
  input  clock,
  input  a,
  output reg p,
  output reg q
);
  always @(*)
    if (clock) p = a;          // intended transparent latch (follows a hi)
  always @(negedge clock)
    q <= p;
  initial q = 0;
endmodule
"""

# POSITIVE variant: a `clk`-named guard, single-statement begin..end.
INTENDED_LATCH_CLK = """\
module TopModule (
  input  clk,
  input  d,
  output reg y
);
  always @(*) begin
    if (clk) y = d;
  end
endmodule
"""

# NEGATIVE 1 (accidental): a NON-clock data-enable guard, no else — `y` is
# meant to be a pure combinational function of (en, d) but forgets the else.
ACCIDENTAL_DATAEN = """\
module TopModule (
  input  en,
  input  d,
  output reg y
);
  always @(*) begin
    if (en) y = d;
  end
endmodule
"""

# NEGATIVE 2 (accidental): a multi-arm if/else-if that forgot the last path.
ACCIDENTAL_MULTIARM = """\
module TopModule (
  input  [1:0] sel,
  input  a, b,
  output reg y
);
  always @(*) begin
    if (sel == 2'b00) y = a;
    else if (sel == 2'b01) y = b;
    // forgot 2'b10 / 2'b11  -> accidental latch
  end
endmodule
"""

# NEGATIVE 3 (accidental): a combinational case missing its default.
ACCIDENTAL_CASE = """\
module TopModule (
  input  [1:0] sel,
  input  a, b, c,
  output reg y
);
  always @(*) begin
    case (sel)
      2'b00: y = a;
      2'b01: y = b;
      2'b10: y = c;
    endcase
  end
endmodule
"""

# control: a width truncation verilator -Wall flags (WIDTHTRUNC). The latch
# downgrade must NOT widen the allow-list — this must STILL BLOCK.
WIDTH_TRUNC = """\
module wtmod(input [7:0] a, output [3:0] y);
  assign y = a;
endmodule
"""


def _write(tmp_path, name, body):
    f = tmp_path / name
    f.write_text(body)
    return f


def _gate(rep, name):
    for g in rep["gates"]:
        if g["gate"] == name:
            return g
    return None


# ── unit: the discriminator in isolation (no tool needed) ────────────────
def test_discriminator_allows_clock_guarded_latch():
    assert H._is_intended_transparent_latch(INTENDED_LATCH, "p") is True
    assert H._is_intended_transparent_latch(INTENDED_LATCH_CLK, "y") is True


def test_discriminator_blocks_accidental_shapes():
    # data-enable guard is NOT a clock → not intended
    assert H._is_intended_transparent_latch(ACCIDENTAL_DATAEN, "y") is False
    # multi-arm branch that forgot a path → not intended
    assert H._is_intended_transparent_latch(ACCIDENTAL_MULTIARM, "y") is False
    # case shape → not intended
    assert H._is_intended_transparent_latch(ACCIDENTAL_CASE, "y") is False


def test_discriminator_blocks_multi_assign_in_block():
    code = ("module M(input clk, input a, output reg p);\n"
            "  always @(*) begin if (clk) p = a; p = ~p; end\nendmodule")
    assert H._is_intended_transparent_latch(code, "p") is False


# ── POSITIVE: intended transparent latch now EMITs (the #716 false-block) ─
@pytest.mark.skipif(not _HAS_AB, reason="iverilog+verilator required")
def test_intended_transparent_latch_emits(tmp_path):
    rtl = _write(tmp_path, "TopModule.sv", INTENDED_LATCH)
    rep = H.selfverify(rtl, "TopModule")
    gb = _gate(rep, "B_verilator_lint")
    assert gb["verdict"] == "PASS", \
        "an intended clock-guarded transparent latch must NOT false-block"
    assert "transparent latch" in gb["reason"]
    assert rep["emit"] is True
    # gate-as-sole-emit-path: the artifact is actually written on PASS
    out = tmp_path / "emitted.sv"
    rc = H.main(["--rtl", str(rtl), "--top", "TopModule", "--emit", str(out)])
    assert rc == 0 and out.is_file()


@pytest.mark.skipif(not _HAS_AB, reason="iverilog+verilator required")
def test_intended_transparent_latch_clk_guard_emits(tmp_path):
    rtl = _write(tmp_path, "TopModule.sv", INTENDED_LATCH_CLK)
    rep = H.selfverify(rtl, "TopModule")
    assert _gate(rep, "B_verilator_lint")["verdict"] == "PASS"
    assert rep["emit"] is True


# ── NEGATIVE NO-LEAK: accidental latches STILL BLOCK ─────────────────────
@pytest.mark.skipif(not _HAS_AB, reason="iverilog+verilator required")
def test_accidental_dataenable_latch_still_blocks(tmp_path):
    rtl = _write(tmp_path, "TopModule.sv", ACCIDENTAL_DATAEN)
    rep = H.selfverify(rtl, "TopModule")
    assert _gate(rep, "B_verilator_lint")["verdict"] == "BLOCK", \
        "a NON-clock data-enable latch (forgot else) must STILL block"
    assert rep["emit"] is False


@pytest.mark.skipif(not _HAS_AB, reason="iverilog+verilator required")
def test_accidental_multiarm_latch_still_blocks(tmp_path):
    rtl = _write(tmp_path, "TopModule.sv", ACCIDENTAL_MULTIARM)
    rep = H.selfverify(rtl, "TopModule")
    assert _gate(rep, "B_verilator_lint")["verdict"] == "BLOCK", \
        "a multi-arm if/else-if that forgot a branch must STILL block"
    assert rep["emit"] is False


@pytest.mark.skipif(not _HAS_AB, reason="iverilog+verilator required")
def test_accidental_case_missing_default_still_blocks(tmp_path):
    rtl = _write(tmp_path, "TopModule.sv", ACCIDENTAL_CASE)
    rep = H.selfverify(rtl, "TopModule")
    gb = _gate(rep, "B_verilator_lint")
    assert gb["verdict"] == "BLOCK", \
        "a combinational case missing its default must STILL block"
    assert "CASEINCOMPLETE" in gb["reason"] or "LATCH" in gb["reason"]
    assert rep["emit"] is False


@pytest.mark.skipif(not _HAS_AB, reason="iverilog+verilator required")
def test_width_truncation_unaffected_still_blocks(tmp_path):
    """The latch downgrade must not widen the allow-list: an unrelated
    substantive finding (WIDTHTRUNC) still blocks."""
    rtl = _write(tmp_path, "wtmod.sv", WIDTH_TRUNC)
    rep = H.selfverify(rtl, "wtmod")
    assert _gate(rep, "B_verilator_lint")["verdict"] == "BLOCK"
    assert rep["emit"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
