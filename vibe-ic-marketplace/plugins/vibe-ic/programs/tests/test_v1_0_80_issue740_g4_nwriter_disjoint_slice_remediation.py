#!/usr/bin/env python3
"""ORGANIC #740 G4 — REMEDIATION of a reproduced adversarial-review MEDIUM.

FINDING (reproduced): `rule_multidriven_register`'s disjoint-bit-slice exemption
was HARDCODED to `if len(idxs) == 2:`, so a LEGAL register split across 3+ always
blocks — each driving a DISTINCT bit-slice — falsely WARNed (and `--severity
WARN` exits 1), while `verilator -Wall` reports 0 MULTIDRIVEN. The 2-block analog
was already correctly silent.

  REPRO (reviewer's EXACT failing input), caseE.sv:
    module m(input clk,input rst,output reg [5:0] q);
    always @(posedge clk) if(rst) q[1:0]<=2'b00;
    always @(posedge clk) q[3:2]<=2'b10;
    always @(posedge clk) q[5:4]<=2'b11;
    endmodule
  BEFORE: WARN "register q is driven from 3 always blocks", EXIT=1.
  AFTER : silent, EXIT=0 (matches `verilator -Wall` = 0 MULTIDRIVEN).

FIX: generalise the disjoint-slice exemption to N writers — exempt when ALL
writer bit-slices for a target are PAIRWISE-DISJOINT (no two blocks write
overlapping bits), regardless of block count (2, 3, …), via
`_all_slices_pairwise_disjoint`. The genuine multidriven WARN is preserved: the
acceptance shape (same reg reset-cleared in one block AND written UNCONDITIONALLY
in another under the same clock — those OVERLAP on the WHOLE reg) STILL fires.

chip-AGNOSTIC: pure SV structure parse. No chip / vendor / SKU literal (enforced
by programs/source_chip_agnostic_check.py).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

import rtl_hygiene_lint as HY  # noqa: E402

G4_PROG = PROGRAMS / "rtl_hygiene_lint.py"

# The reviewer's EXACT failing input.
CASE_E = (
    "module m(input clk,input rst,output reg [5:0] q);\n"
    "always @(posedge clk) if(rst) q[1:0]<=2'b00;\n"
    "always @(posedge clk) q[3:2]<=2'b10;\n"
    "always @(posedge clk) q[5:4]<=2'b11;\n"
    "endmodule\n"
)

# The original fix's motivating case (the #740 G4 acceptance): a reg reset-cleared
# in one block AND written UNCONDITIONALLY full-width in another under the same
# clock — the writes OVERLAP (whole reg) so this MUST STILL fire.
OVERLAP_MD = (
    "module m(input clk,input rst,output reg [7:0] mem0);\n"
    "always @(posedge clk) if(rst) mem0<=8'b0;\n"
    "always @(posedge clk) mem0<=mem0+1;\n"
    "endmodule\n"
)


def _run_lint_warn(tmp_path, rtl: str, name: str = "d.sv"):
    p = tmp_path / name
    p.write_text(rtl)
    return subprocess.run(
        [sys.executable, str(G4_PROG), "--severity", "WARN", str(p)],
        capture_output=True, text=True, timeout=60)


# ───────────────────────── REMEDIATION: caseE silent ────────────────────────
def test_caseE_three_block_disjoint_slices_is_silent_cli(tmp_path):
    """REMEDIATION END-STATE: the reviewer's 3-block disjoint-slice register is
    SILENT (no multidriven WARN) and `--severity WARN` exits 0."""
    r = _run_lint_warn(tmp_path, CASE_E, "caseE.sv")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "multidriven-register" not in r.stdout


def test_caseE_three_block_disjoint_slices_no_finding_pure(tmp_path):
    """PURE: rule_multidriven_register emits NO multidriven finding for the
    3-block disjoint-slice split."""
    fs = HY.rule_multidriven_register(HY.strip_comments(CASE_E), "caseE.sv")
    assert [f for f in fs if f.rule == "multidriven-register"] == []


def test_n_writer_pairwise_disjoint_helper_pure():
    """The generalised helper: ALL writer slice-sets pairwise-disjoint → exempt
    for any N; a whole-reg ('') or an overlapping slice in ANY block breaks it;
    fewer than 2 sets is not a multidriven situation."""
    f = HY._all_slices_pairwise_disjoint
    # 3 disjoint single-slice writers
    assert f([{"[1:0]"}, {"[3:2]"}, {"[5:4]"}]) is True
    # 4 disjoint writers
    assert f([{"[1:0]"}, {"[3:2]"}, {"[5:4]"}, {"[7:6]"}]) is True
    # one whole-reg write ('') anywhere → NOT disjoint
    assert f([{"[1:0]"}, {"[3:2]"}, {""}]) is False
    # two blocks share a slice string → NOT disjoint
    assert f([{"[1:0]"}, {"[1:0]"}, {"[5:4]"}]) is False
    # fewer than 2 sets → not a multidriven situation
    assert f([{"[1:0]"}]) is False
    assert f([]) is False
    # an empty slice-set in any block → NOT disjoint (conservative)
    assert f([{"[1:0]"}, set()]) is False


@pytest.mark.skipif(shutil.which("verilator") is None,
                    reason="verilator not on PATH")
def test_caseE_verilator_ground_truth_zero_multidriven(tmp_path):
    """GROUND-TRUTH (shutil.which-guarded): `verilator -Wall` reports 0
    MULTIDRIVEN on the 3-block disjoint-slice register — so our SILENT verdict
    matches the external oracle."""
    p = tmp_path / "caseE.sv"
    p.write_text(CASE_E)
    out = subprocess.run(
        ["verilator", "--lint-only", "-Wall", str(p)],
        capture_output=True, text=True, timeout=60)
    assert "MULTIDRIVEN" not in (out.stdout + out.stderr)


# ──────────────── GUARD: original motivating cases still work ────────────────
def test_guard_overlap_full_reg_still_warns_cli(tmp_path):
    """The original fix's motivating case (acceptance shape: reset-clear block +
    unconditional full-width datapath block, same clock — OVERLAP) STILL WARNs
    and exits 1. The remediation must NOT regress it."""
    r = _run_lint_warn(tmp_path, OVERLAP_MD, "md.sv")
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "multidriven-register" in r.stdout
    assert "mem0" in r.stdout
    assert "multidriven" in r.stdout.lower()


def test_guard_overlap_full_reg_still_warns_pure():
    """PURE guard for the motivating overlap case."""
    fs = HY.rule_multidriven_register(HY.strip_comments(OVERLAP_MD), "md.sv")
    md = [f for f in fs if f.rule == "multidriven-register"]
    assert md and md[0].symbol == "mem0" and md[0].severity == "WARN"


def test_guard_two_block_disjoint_still_silent_pure():
    """The 2-block disjoint analog (the case that was ALREADY correct) stays
    silent under the generalised exemption."""
    rtl = (
        "module m(input clk,input rst,output reg [5:0] q);\n"
        "always @(posedge clk) if(rst) q[1:0]<=2'b00;\n"
        "always @(posedge clk) q[3:2]<=2'b10;\n"
        "endmodule\n"
    )
    fs = HY.rule_multidriven_register(HY.strip_comments(rtl), "d.sv")
    assert [f for f in fs if f.rule == "multidriven-register"] == []


def test_guard_three_block_with_an_overlap_still_warns_pure():
    """A 3-block split where TWO blocks write OVERLAPPING (whole-reg) bits is NOT
    pairwise-disjoint → the genuine multidriven WARN still fires (no false
    exemption from the generalisation)."""
    rtl = (
        "module m(input clk,input rst,output reg [5:0] q);\n"
        "always @(posedge clk) if(rst) q<=6'b0;\n"          # whole-reg clear
        "always @(posedge clk) q<=q+1;\n"                   # whole-reg datapath
        "always @(posedge clk) if(rst) q[5:4]<=2'b11;\n"
        "endmodule\n"
    )
    fs = HY.rule_multidriven_register(HY.strip_comments(rtl), "d.sv")
    md = [f for f in fs if f.rule == "multidriven-register"]
    assert md and md[0].symbol == "q" and md[0].severity == "WARN"


def test_guard_different_clock_domains_still_warns_pure():
    """A reg driven from two DIFFERENT whole-reg clock domains is still the
    genuine multidriven WARN (the generalised disjoint-slice exemption never
    fires here — both writers are whole-reg, not disjoint slices)."""
    rtl = (
        "module m(input clk_a, input clk_b, output reg q);\n"
        "  always @(posedge clk_a) q<=1'b1;\n"
        "  always @(posedge clk_b) q<=1'b0;\n"
        "endmodule\n"
    )
    fs = HY.rule_multidriven_register(HY.strip_comments(rtl), "d.sv")
    assert any(f.symbol == "q" and "DIFFERENT clocking" in f.message for f in fs)


# ─────────────────────────── chip-AGNOSTIC source guard ─────────────────────
def test_chip_agnostic_source():
    guard = PROGRAMS / "source_chip_agnostic_check.py"
    r = subprocess.run([sys.executable, str(guard), str(PLUGIN)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
