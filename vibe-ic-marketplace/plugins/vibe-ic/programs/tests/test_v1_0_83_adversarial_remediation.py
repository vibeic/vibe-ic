"""Step-2.7 adversarial-review remediation guards for the v1.0.83 batch.

The pre-push adversarial review of #751/#752/#753/#756 reproduced four §4.05
LEAKS — a relaxation/drop that now MASKS a genuine defect (a defective design
passing --strict / a real under-reduction escaping BLOCK). Each is remediated
and pinned here so it can never regress.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import _specrtl_common as S          # noqa: E402
import iface_conformance_v2 as I     # noqa: E402
import ppa_area_threshold_check as P  # noqa: E402

_SPEC_COV = _PROGRAMS / "spec_coverage_check.py"


# ── #751 — _NL_PORT must keep a described port bullet (HIGH: end-anchor dropped
#    every described bullet → whole coverage set collapsed → any TB passed) ────
def test_751_described_port_bullets_kept():
    for bullet, name in (("- input clk system clock", "clk"),
                         ("- input d (8 bits) data bus", "d"),
                         ("- output q result output", "q"),
                         ("- input rst_n\r", "rst_n")):  # CRLF tolerated
        ports = S._parse_nl_ports(bullet)
        assert [p.name for p in ports] == [name], (bullet, ports)


def test_751_prose_bullets_still_rejected():
    for bullet in ("- Input ports:", "- Output latency is 1 clock cycle.",
                   "- Output all zeros (zero)", "- Input coefficients [1,2]"):
        assert S._parse_nl_ports(bullet) == [], bullet


# ── #752 — an RTL that OMITS a spec port must still BLOCK under --strict (HIGH:
#    the phantom-port DROP masked a real missing port) ─────────────────────────
def test_752_rtl_omitting_spec_port_still_blocks(tmp_path):
    (tmp_path / "spec.txt").write_text(
        "- input clk\n- input data_in\n- output data_out\n")
    (tmp_path / "dut.sv").write_text("module dut(input clk);\nendmodule\n")
    (tmp_path / "tb.sv").write_text(
        "module tb; reg clk; initial clk=0; endmodule\n")
    cp = subprocess.run(
        [sys.executable, str(_SPEC_COV), "--spec", str(tmp_path / "spec.txt"),
         "--rtl", str(tmp_path / "dut.sv"), "--tb", str(tmp_path / "tb.sv"),
         "--strict"], capture_output=True, text=True)
    assert cp.returncode == 1, (cp.returncode, cp.stdout)
    assert "data_in" in cp.stdout and "data_out" in cp.stdout


# ── #753 — a prose-declared directional port must NOT be masked by an unrelated
#    helper block's same-named internal reg (MEDIUM, blocking under --strict) ──
def test_753_prose_directional_port_not_masked_by_helper_internal():
    prompt = ("The module foo has an input `data_valid`.\n\n"
              "```\nmodule helper(input clk); reg data_valid; endmodule\n```\n")
    rtl = "module foo(input clk, output q); endmodule"
    findings = I.check_conformance("cvdp_x", prompt, rtl)
    blob = " ".join(getattr(f, "message", str(f)) for f in findings)
    assert "data_valid" in blob and "MISSING-PORT" in blob


# ── #756 — a 'both' clause with a per-metric REAL under-reduction must BLOCK,
#    matching legacy decide() (MEDIUM: the min()-collapse downgraded BLOCK →
#    NOT_APPLICABLE). ORGANIC #769 RE-ANCHOR: a metric whose GENERIC reduction
#    meets the bar now PASSES (the scorer measures the GENERIC count), and a
#    no-reference real-but-insufficient generic delta is advisory NOT_APPLICABLE
#    (#768 fail-safe). The surviving hard per-metric no-leak is a GROWN metric —
#    pin BOTH decide_clauses and decide on it so the parity this test guards
#    holds. ──────────────────────────────────────────────────────────────────
def test_756_both_clause_per_metric_grown_blocks():
    clauses, comb = P.parse_threshold_clauses_from_prompt(
        "reduce the total area by 10%")
    assert clauses == [(10.0, "both")] and comb == "and"
    # cells GREW (negative mapped) → a real per-metric regression; wires clears
    # on its generic count. The 'both' clause must BLOCK on the grown cells.
    new = P.decide_clauses(-4.0, 5.0, clauses, comb,
                           cells_red_generic=3.0, wires_red_generic=20.0)[0]
    legacy = P.decide(-4.0, 5.0, 10.0, "both",
                      cells_red_generic=3.0, wires_red_generic=20.0)[0]
    assert new == "BLOCK", new
    assert new == legacy


def test_756_disjunctive_and_grown_and_nearminimal_preserved():
    # disjunctive cells-8% branch met → PASS
    assert P.decide_clauses(10.0, 5.0, [(12, "wires"), (8, "cells")], "or",
                            cells_red_generic=18, wires_red_generic=18)[0] == "PASS"
    # a grown metric under OR → still BLOCK
    assert P.decide_clauses(-5.0, 3.0, [(12, "wires"), (8, "cells")], "or",
                            cells_red_generic=18, wires_red_generic=18)[0] == "BLOCK"
    # a 'both' clause genuinely near-minimal (generic also sub-threshold) → N/A
    assert P.decide_clauses(4.0, 5.0, [(10.0, "both")], "and",
                            cells_red_generic=5.0, wires_red_generic=5.0)[0] == "NOT_APPLICABLE"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
