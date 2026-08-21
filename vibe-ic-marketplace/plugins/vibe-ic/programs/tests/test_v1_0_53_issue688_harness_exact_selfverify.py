#!/usr/bin/env python3
"""ORGANIC #688 — blind RTL self-verify must match the HARNESS-EXACT toolchain.

A blind RTL-authoring agent that self-verifies with a HOST toolchain by
compiling RTL+testbench TOGETHER diverges from the scorer, which (a) pins a
specific tool version (icarus 13 / verilator 5.038), (b) compiles the RTL
ALONE under the harness top flag `-s <module>` (full `-o` codegen, not a
`-t null` elaborate), and (c) runs a lint gate. Three fail classes slip
through host-only / RTL+TB-together self-check:

  1. ELAB-only       — elaborates but fails full codegen;
  2. standalone-top  — compiles WITH a TB but not ALONE under `-s <module>`
                       (depends on a TB-only signal / top-name mismatch);
  3. lint            — code the scorer's lint gate rejects.

`harness_exact_selfverify.py` runs gate A (standalone `-s <top>` -o codegen)
+ gate B (verilator --lint-only -Wall) deterministically + runs a provided
functional TB (gate C, AI-authored from prompt examples). It is the SOLE
EMIT PATH (gate-as-sole-emit-path, ORGANIC #529).

POSITIVE: clean RTL → PASS + emit; a standalone-top failure (compiles WITH a
TB, fails ALONE) → BLOCK; a codegen-failing RTL → BLOCK; a lint-dirty RTL →
BLOCK; a wrong-functional RTL with a passing-on-correct TB → BLOCK.

§4.05 NO-LEAK: clean RTL is NOT falsely blocked (incl. a filename-vs-module
mismatch, which is a scratch-name artifact the scorer never sees); the gate
does NOT claim to catch spec-interpretation mismatches; a tool-version skew is
DISCLOSED not silently passed; an absent tool is disclosed/skipped (or hard-
refused under --require-tools), never faked.

Live-tool portions gate on shutil.which.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))
import harness_exact_selfverify as H  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None
_HAS_VERILATOR = shutil.which("verilator") is not None
_HAS_VVP = shutil.which("vvp") is not None
_HAS_AB = _HAS_IVERILOG and _HAS_VERILATOR        # gates A + B
_HAS_ABC = _HAS_AB and _HAS_VVP                   # + gate C


# ── fixtures ────────────────────────────────────────────────────────────
CLEAN_ADDER = """\
module adder(input [7:0] a, input [7:0] b, output [8:0] sum);
  assign sum = a + b;
endmodule
"""

# Standalone-top fail (class 2): compiles WITH a TB (the TB defines the
# helper) but FAILS alone under `-s dut_needs_tb` — the exact host-together
# vs scorer-alone divergence #688 describes.
DUT_NEEDS_TB = """\
module dut_needs_tb(input clk, input [3:0] a, output [3:0] y);
  helper_only_in_tb u_h(.clk(clk), .a(a), .y(y));
endmodule
"""

# Codegen-failing RTL (full `-o` rejects it — proves gate A is codegen, not a
# `-t null` elaborate): whole-array assignment is an iverilog codegen `sorry:`.
CODEGEN_FAIL = """\
module cgfail(input clk, output reg [7:0] y);
  reg [7:0] mem  [0:3];
  reg [7:0] mem2 [0:3];
  always @(posedge clk) begin
    mem2 = mem;
    y <= mem2[0];
  end
endmodule
"""

# Lint-dirty RTL: a width truncation verilator -Wall flags (WIDTHTRUNC), but
# which compiles fine under iverilog (so ONLY gate B catches it).
LINT_DIRTY = """\
module wtmod(input [7:0] a, output [3:0] y);
  assign y = a;
endmodule
"""

# Wrong-functional RTL (subtracts instead of adds) — used with a TB whose
# golden vectors come from a worked example (3+4=7); gate C must BLOCK it.
WRONG_ADDER = """\
module adder(input [7:0] a, input [7:0] b, output [8:0] sum);
  assign sum = a - b;
endmodule
"""

TB_ADDER = """\
module tb;
  reg [7:0] a, b; wire [8:0] sum;
  adder dut(.a(a), .b(b), .sum(sum));
  initial begin
    a = 8'd3; b = 8'd4; #1;
    if (sum !== 9'd7) begin $display("Mismatches: 1 in 1"); $finish; end
    $display("Mismatches: 0 in 1"); $finish;
  end
endmodule
"""


def _write(tmp_path, name, body):
    f = tmp_path / name
    f.write_text(body)
    return f


def _gate(report, name):
    for g in report["gates"]:
        if g["gate"] == name:
            return g
    return None


# ── POSITIVE: clean RTL passes the deterministic gates and emits ─────────
@pytest.mark.skipif(not _HAS_AB, reason="iverilog+verilator required")
def test_clean_rtl_passes_and_emits(tmp_path):
    rtl = _write(tmp_path, "adder.sv", CLEAN_ADDER)
    rep = H.selfverify(rtl, "adder")
    assert _gate(rep, "A_standalone_compile")["verdict"] == "PASS"
    assert _gate(rep, "B_verilator_lint")["verdict"] == "PASS"
    assert rep["emit"] is True
    # gate-as-sole-emit-path: the artifact is written BY THE GATE on PASS
    out = tmp_path / "emitted.sv"
    rc = H.main(["--rtl", str(rtl), "--top", "adder", "--emit", str(out)])
    assert rc == 0
    assert out.is_file()
    assert "module adder" in out.read_text()


@pytest.mark.skipif(not _HAS_AB, reason="iverilog+verilator required")
def test_gate_a_uses_full_codegen_not_elaborate(tmp_path):
    """Gate A's documented flags are `-o sim.vvp -s <top>` (full codegen),
    NEVER a `-t null` elaborate — the whole point of #688 fail class 1."""
    rtl = _write(tmp_path, "adder.sv", CLEAN_ADDER)
    rep = H.selfverify(rtl, "adder")
    flags = _gate(rep, "A_standalone_compile")["flags"]
    assert "-o" in flags and "-s adder" in flags
    assert "-t null" not in flags
    assert _gate(rep, "A_standalone_compile")["deterministic"] is True
    assert _gate(rep, "B_verilator_lint")["deterministic"] is True


# ── BLOCK class 2: standalone-top failure (compiles WITH a TB, fails alone)
@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog required")
def test_standalone_top_failure_blocks_emit(tmp_path):
    rtl = _write(tmp_path, "dut_needs_tb.sv", DUT_NEEDS_TB)
    rep = H.selfverify(rtl, "dut_needs_tb")
    assert _gate(rep, "A_standalone_compile")["verdict"] == "BLOCK"
    assert rep["emit"] is False
    # and the gate's CLI blocks (exit 1) — no emit file produced
    out = tmp_path / "should_not_emit.sv"
    rc = H.main(["--rtl", str(rtl), "--top", "dut_needs_tb",
                 "--emit", str(out)])
    assert rc == 1
    assert not out.is_file()


def test_standalone_top_failure_compiles_WITH_tb(tmp_path):
    """Confirm the fixture's premise: it DOES compile when the TB (which
    defines the helper) is linked — i.e. a host-together self-check would
    have falsely PASSED it. Pure structural fixture self-test (no tool)."""
    rtl = _write(tmp_path, "dut_needs_tb.sv", DUT_NEEDS_TB)
    # the RTL alone cannot resolve `helper_only_in_tb`
    assert "helper_only_in_tb" in rtl.read_text()
    assert "module helper_only_in_tb" not in rtl.read_text()


# ── BLOCK class 1 proxy: full-codegen-failing RTL ───────────────────────
@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog required")
def test_codegen_failing_rtl_blocks_emit(tmp_path):
    rtl = _write(tmp_path, "cgfail.sv", CODEGEN_FAIL)
    rep = H.selfverify(rtl, "cgfail")
    assert _gate(rep, "A_standalone_compile")["verdict"] == "BLOCK"
    assert rep["emit"] is False


# ── BLOCK class 3: lint-dirty RTL ───────────────────────────────────────
@pytest.mark.skipif(not _HAS_AB, reason="iverilog+verilator required")
def test_lint_dirty_rtl_blocks_emit(tmp_path):
    rtl = _write(tmp_path, "wtmod.sv", LINT_DIRTY)
    rep = H.selfverify(rtl, "wtmod")
    # gate A (compile) passes; ONLY gate B (lint) catches the width truncation
    assert _gate(rep, "A_standalone_compile")["verdict"] == "PASS"
    assert _gate(rep, "B_verilator_lint")["verdict"] == "BLOCK"
    assert "B_verilator_lint" in rep["blocking_gates"]
    assert rep["emit"] is False


# ── gate C: AI-authored functional TB, program RUNS only ────────────────
@pytest.mark.skipif(not _HAS_ABC, reason="iverilog+verilator+vvp required")
def test_functional_tb_pass(tmp_path):
    rtl = _write(tmp_path, "adder.sv", CLEAN_ADDER)
    tb = _write(tmp_path, "tb.sv", TB_ADDER)
    rep = H.selfverify(rtl, "adder", tb_path=tb)
    assert _gate(rep, "C_functional_tb")["verdict"] == "PASS"
    assert rep["emit"] is True


@pytest.mark.skipif(not _HAS_ABC, reason="iverilog+verilator+vvp required")
def test_functional_tb_fail_blocks_emit(tmp_path):
    rtl = _write(tmp_path, "adder.sv", WRONG_ADDER)
    tb = _write(tmp_path, "tb.sv", TB_ADDER)
    rep = H.selfverify(rtl, "adder", tb_path=tb)
    assert _gate(rep, "C_functional_tb")["verdict"] == "BLOCK"
    assert rep["emit"] is False


def test_gate_c_is_not_deterministic_and_tb_authored_by_ai(tmp_path):
    """The honest boundary: gate C is AI-authored (prompt examples); the
    program only RUNS it. No tool needed for this structural assertion."""
    rtl = _write(tmp_path, "adder.sv", CLEAN_ADDER)
    # no --tb → gate C must be SKIP (never silently passed)
    rep = H.selfverify(rtl, "adder", tb_path=None)
    gc = _gate(rep, "C_functional_tb")
    assert gc["deterministic"] is False
    assert "AI" in gc["tb_authored_by"]
    assert gc["verdict"] == "SKIP"
    assert "not silently passed" in gc["reason"]


# ── §4.05 NO-LEAK ───────────────────────────────────────────────────────
@pytest.mark.skipif(not _HAS_AB, reason="iverilog+verilator required")
def test_noleak_clean_rtl_not_falsely_blocked(tmp_path):
    """A clean module saved under a scratch FILENAME that differs from the
    module name must NOT be blocked: DECLFILENAME is a scratch-name artifact
    the scorer (which saves `<top>.sv`) never sees."""
    # file named 'scratch_draft.sv', module named 'adder'
    rtl = _write(tmp_path, "scratch_draft.sv", CLEAN_ADDER)
    rep = H.selfverify(rtl, "adder")
    assert _gate(rep, "B_verilator_lint")["verdict"] == "PASS", \
        "filename-vs-module mismatch must not false-block (scorer saves <top>.sv)"
    assert rep["emit"] is True


# Passthrough with an intentionally-unused but spec-REQUIRED port (the hidden
# TB still binds clk). verilator -Wall flags UNUSEDSIGNAL — but this is correct,
# scorer-PASSING RTL, so gate B must NOT block it.
UNUSED_REQUIRED_PORT = """\
module TopModule(input clk, input in, output out);
  assign out = in;
endmodule
"""


@pytest.mark.skipif(not _HAS_AB, reason="iverilog+verilator required")
def test_noleak_intentionally_unused_required_port_not_blocked(tmp_path):
    """A spec-REQUIRED but logically-unused port (verilator -Wall
    UNUSEDSIGNAL) is correct RTL the scorer PASSes — gate B must not block."""
    rtl = _write(tmp_path, "scratch.sv", UNUSED_REQUIRED_PORT)
    rep = H.selfverify(rtl, "TopModule")
    assert _gate(rep, "B_verilator_lint")["verdict"] == "PASS", \
        "an intentionally-unused required port (UNUSEDSIGNAL) must not block"
    assert rep["emit"] is True


def test_noleak_does_not_claim_spec_interpretation(tmp_path):
    """The gate must NEVER claim to catch spec-interpretation mismatches."""
    rtl = _write(tmp_path, "adder.sv", CLEAN_ADDER)
    rep = H.selfverify(rtl, "adder")
    assert rep["detects_spec_interpretation"] is False


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog required")
def test_noleak_version_skew_disclosed_not_silently_passed(tmp_path):
    """When the host tool version differs from the scorer's, the skew is
    DISCLOSED in the report (and the run still proceeds) — never hidden."""
    rtl = _write(tmp_path, "adder.sv", CLEAN_ADDER)
    rep = H.selfverify(rtl, "adder")
    disc = rep["version_disclosure"]
    assert disc["scorer_iverilog_major"] == "13"
    assert disc["scorer_verilator_version"] == "5.038"
    # the disclosure structure is always present; if the host differs from the
    # scorer pin, the skew list is non-empty and names it.
    import re
    m = re.search(r"version\s+(\d+)", disc["host_iverilog"], re.IGNORECASE)
    if m and m.group(1) != "13":
        assert any("iverilog" in s for s in disc["skew"]), \
            "an iverilog version skew must be disclosed"


def test_noleak_absent_tool_skips_not_fakes(monkeypatch, tmp_path):
    """An absent tool is DISCLOSED + SKIPped (default), never faked as PASS —
    and under --require-tools it hard-refuses (exit 2)."""
    rtl = _write(tmp_path, "adder.sv", CLEAN_ADDER)

    def _which_none(name):
        return None
    monkeypatch.setattr(H.shutil, "which", _which_none)

    # default: gate A/B report SKIP (tool absent), with disclosure
    rep = H.selfverify(rtl, "adder")
    ga = _gate(rep, "A_standalone_compile")
    gb = _gate(rep, "B_verilator_lint")
    assert ga["verdict"] == "SKIP" and "absent" in ga["reason"]
    assert gb["verdict"] == "SKIP" and "absent" in gb["reason"]
    # SKIP does not block emit, but it is NOT a silent pass — the reason
    # explicitly discloses the tool was absent.
    assert "not silently passed" in ga["reason"]

    # --require-tools: absent tool → ERROR verdict + hard refuse (exit 2)
    rep2 = H.selfverify(rtl, "adder", require_tools=True)
    assert _gate(rep2, "A_standalone_compile")["verdict"] == "ERROR"
    rc = H.main(["--rtl", str(rtl), "--top", "adder", "--require-tools"])
    assert rc == 2


# ── resolve_top: harness-exact top semantics ────────────────────────────
def test_resolve_top_requested_not_declared_is_a_failure():
    """A requested top that the RTL does NOT declare is a standalone-top fail
    (the scorer's `-s <top>` would fail) — resolve_top returns an error."""
    top, why = H.resolve_top(CLEAN_ADDER, "nonexistent_top")
    assert top is None
    assert "standalone-top" in why or "not declared" in why


def test_resolve_top_sole_module():
    top, why = H.resolve_top(CLEAN_ADDER, None)
    assert top == "adder"


def test_resolve_top_requested_and_declared():
    top, why = H.resolve_top(CLEAN_ADDER, "adder")
    assert top == "adder"


def test_module_names_ignores_comments():
    code = "/* module fake_in_comment */\nmodule real_mod(input a); endmodule"
    assert H.module_names(code) == ["real_mod"]


# ── tb verdict parsing ──────────────────────────────────────────────────
def test_tb_verdict_mismatch_summary():
    ok, why = H._tb_verdict("Mismatches: 0 in 16\n")
    assert ok is True
    ok2, _ = H._tb_verdict("Mismatches: 3 in 16\n")
    assert ok2 is False


def test_tb_verdict_no_line_is_inconclusive():
    ok, why = H._tb_verdict("simulation finished\n")
    assert ok is None
    assert "no recognised" in why


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
