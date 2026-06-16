#!/usr/bin/env python3
"""ORGANIC #770 [P1 SYSTEMIC] — shared provenance/confidence layer.

50 of 57 round5-7 false-positives shared ONE meta-pattern: under `--strict`
(sole-emit hard-BLOCK) a gate hard-blocked correct, spec-faithful RTL on a
checklist-item / finding derived from a PROSE-HEURISTIC (free-prose regex) that
the correct RTL either contradicts or has no such thing. The fix tags every
BLOCK-eligible finding STRUCTURAL vs PROSE_HEURISTIC and lets `--strict` block
only on trustworthy evidence:

    BLOCK-eligible ⇔ STRUCTURAL OR (PROSE_HEURISTIC AND corroborated_by_rtl)
    ADVISORY       ⇔ PROSE_HEURISTIC AND (contradicted_by_rtl OR
                                          no_structural_corroboration)

§4.05 NO-LEAK boundary (the load-bearing half): EVERY structural negative still
blocks — a port missing from a real markdown table / given-code header; a prose
behavioral requirement the RTL STRUCTURALLY CORROBORATES; any finding when no RTL
is supplied to judge (no-leak biased UNKNOWN keeps the block).

chip-AGNOSTIC: provenance vocabulary + decision rule only; no chip/vendor/SKU.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import _provenance as P  # noqa: E402
import iface_conformance_v2 as IF  # noqa: E402

_SPEC_COV = _PROGRAMS / "spec_coverage_check.py"
_IFACE = _PROGRAMS / "iface_conformance_v2.py"
_TB_BARE = "module tb; reg clk; initial clk=0; endmodule\n"


# ── the pure decision rule ───────────────────────────────────────────────────
def test_770_block_rule_structural_always_blocks():
    assert P.is_block_eligible(P.STRUCTURAL, P.CONTRADICTED) is True
    assert P.is_block_eligible(P.STRUCTURAL, None) is True


def test_770_block_rule_prose_downgrades_only_on_contradiction_or_absence():
    assert P.is_block_eligible(P.PROSE_HEURISTIC, P.CORROBORATED) is True
    assert P.is_block_eligible(P.PROSE_HEURISTIC, P.UNKNOWN) is True  # no-leak bias
    assert P.is_block_eligible(P.PROSE_HEURISTIC, P.CONTRADICTED) is False
    assert P.is_block_eligible(P.PROSE_HEURISTIC, P.NO_CORROBORATION) is False


def test_770_corroboration_helpers():
    assert P.corroborate_port_presence("clk", {"clk", "d"}) == P.CORROBORATED
    assert P.corroborate_port_presence("and", {"clk", "d"}) == P.CONTRADICTED
    assert P.corroborate_port_presence("clk", None) == P.UNKNOWN
    assert P.corroborate_direction("input", "input") == P.CORROBORATED
    assert P.corroborate_direction("input", "output") == P.CONTRADICTED
    assert P.corroborate_direction("input", None) == P.UNKNOWN
    assert P.corroborate_structural_feature(True) == P.CORROBORATED
    assert P.corroborate_structural_feature(False) == P.CONTRADICTED
    assert P.corroborate_structural_feature(None) == P.UNKNOWN


# ── iface: prose direction contradicted by RTL → advisory ────────────────────
def test_770_iface_prose_direction_contradicted_is_advisory():
    fs = IF.check_conformance(
        None, "There is an input `foo` signal.",
        "module m(output foo, input clk); endmodule")
    assert len(fs) == 1 and fs[0].kind == "PORT-DIRECTION"
    assert fs[0].block_eligible is False


def test_770_iface_table_direction_contradicted_still_blocks():
    fs = IF.check_conformance(
        None, "| Signal | Direction |\n|---|---|\n| `foo` | input |\n",
        "module m(output foo, input clk); endmodule")
    assert len(fs) == 1 and fs[0].kind == "PORT-DIRECTION"
    assert fs[0].block_eligible is True   # STRUCTURAL table → BLOCK


# ── spec_coverage end-state via the real program ─────────────────────────────
def _speccov(tmp_path, spec, tb=_TB_BARE, rtl=None):
    (tmp_path / "spec.md").write_text(spec)
    (tmp_path / "tb.sv").write_text(tb)
    cmd = [sys.executable, str(_SPEC_COV), "--spec", str(tmp_path / "spec.md"),
           "--tb", str(tmp_path / "tb.sv"), "--strict"]
    if rtl is not None:
        (tmp_path / "rtl.sv").write_text(rtl)
        cmd += ["--rtl", str(tmp_path / "rtl.sv")]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_770_speccov_latency_on_combinational_is_advisory(tmp_path):
    r = _speccov(
        tmp_path,
        "# Adder\nThe output is registered with a one clock cycle latency.\n",
        rtl="module dut(input [3:0] a, input [3:0] b, output [4:0] sum);\n"
            " assign sum = a + b;\nendmodule\n")
    assert r.returncode == 0, r.stdout
    assert "ADVISORY" in r.stdout


def test_770_noleak_speccov_latency_on_registered_still_blocks(tmp_path):
    r = _speccov(
        tmp_path,
        "# Acc\nThe output is registered with a one clock cycle latency.\n",
        rtl="module dut(input clk, input [3:0] a, output reg [4:0] sum);\n"
            " always @(posedge clk) sum <= a;\nendmodule\n")
    assert r.returncode == 1, r.stdout


def test_770_noleak_speccov_no_rtl_keeps_blocking(tmp_path):
    # no --rtl → corroboration UNKNOWN → no downgrade → historical block kept.
    r = _speccov(
        tmp_path,
        "# Adder\nThe output is registered with a one clock cycle latency.\n")
    assert r.returncode == 1, r.stdout


def test_770_speccov_reset_on_pure_comb_is_advisory(tmp_path):
    r = _speccov(
        tmp_path, "# Mux\nOn reset the output clears to zero.\n",
        rtl="module dut(input [1:0] sel, output reg o);\n"
            " always @(*) o = sel[0];\nendmodule\n")
    assert r.returncode == 0, r.stdout
    assert "ADVISORY" in r.stdout


def test_770_noleak_speccov_reset_with_real_reset_port_still_blocks(tmp_path):
    r = _speccov(
        tmp_path, "# Reg\nOn reset the output clears to zero.\n",
        rtl="module dut(input clk, input rst_n, output reg o);\n"
            " always @(posedge clk) if(!rst_n) o<=0; else o<=1;\nendmodule\n")
    assert r.returncode == 1, r.stdout


# ── §4.05 NO-LEAK: the phantom 'and' is fixed AT EXTRACTION, and a genuine
#    missing port still blocks (the #752 invariant the provenance layer must
#    NOT re-break) ───────────────────────────────────────────────────────────
def test_770_phantom_conjunction_not_a_port():
    import _specrtl_common as S
    got = [p.name for p in S._parse_nl_ports(
        "- Input and output AXI Stream signals adhere to the protocol.")]
    assert got == [], got


def test_770_noleak_genuine_missing_port_still_blocks(tmp_path):
    # the #752 invariant — an RTL that omits a real spec port still BLOCKs.
    r = _speccov(
        tmp_path, "- input clk\n- input data_in\n- output data_out\n",
        rtl="module dut(input clk);\nendmodule\n")
    assert r.returncode == 1, r.stdout


# ── Step-2.7 adversarial-review remediation (3 reproduced HIGH §4.05 findings) ─
def test_770_review_noleak_table_sourced_latency_still_blocks(tmp_path):
    """Step-2.7 finding #1: a behavioral requirement STATED IN A MARKDOWN TABLE
    is STRUCTURAL — it must keep its block even when the RTL appears to
    contradict it (a pure-combinational RTL). Provenance is by SOURCE (table),
    not by KIND. (Pre-remediation this was wrongly downgraded to advisory.)"""
    (tmp_path / "spec.md").write_text(
        "# Adder\n\n| Requirement | Details |\n|---|---|\n"
        "| Output latency | 1 clock cycle |\n")
    (tmp_path / "rtl.sv").write_text(
        "module adder(input [3:0] a, input [3:0] b, output [4:0] sum);\n"
        " assign sum = a + b;\nendmodule\n")
    (tmp_path / "tb.sv").write_text(
        "module tb; reg [3:0] a,b; wire [4:0] sum; adder u(a,b,sum);\n"
        " initial begin a=1;b=2;#1;$finish; end endmodule\n")
    r = subprocess.run(
        [sys.executable, str(_SPEC_COV), "--spec", str(tmp_path / "spec.md"),
         "--rtl", str(tmp_path / "rtl.sv"), "--tb", str(tmp_path / "tb.sv"),
         "--strict"], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout
    assert "ADVISORY" not in r.stdout


def test_770_review_single_letter_port_with_width_anchor_kept():
    """Step-2.7 finding #2: a single-letter / function-word port name carrying a
    `(N bits)` width anchor is a REAL port — the #770 conjunction filter must NOT
    drop it (it only drops a bare conjunction scraped from a prose sentence)."""
    import _specrtl_common as S
    assert [p.name for p in S._parse_nl_ports("- input a (8 bits)")] == ["a"]
    assert [p.name for p in S._parse_nl_ports("- input an (4 bits)")] == ["an"]
    # the conjunction phantom WITHOUT a width anchor is still dropped.
    assert S._parse_nl_ports(
        "- Input and output AXI Stream signals adhere to ...") == []


def test_770_review_nl_ports_preserves_duplicates():
    """Step-2.7 finding #3: `_parse_nl_ports` must return EVERY bullet (incl. a
    duplicate name) so spec_self_consistency_check can flag the duplicate-port
    error — no name-dedup inside the parser."""
    import _specrtl_common as S
    got = [p.name for p in S._parse_nl_ports(
        "- input clk\n- output q\n- output q")]
    assert got == ["clk", "q", "q"], got


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
