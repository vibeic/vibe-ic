"""ORGANIC #577 — fpga_sdc_clock_constraint_check did not recognize the
canonical L8 key `clock_mhz` its sibling generator (sdc_gen.py:
period_ns = 1000 / L8.clock_mhz) emits, so on canonical projects the RTL
period resolved to None and Rule 3 (SDC-vs-RTL period mismatch) silently
never fired — a 100% period mismatch passed with a bare PASS line.
Also: in the PLL/generated-clock WARN path the final summary still
claimed "matches" while the WARN above reported the mismatch.

Fixes: _FREQ_SYNONYMS_MHZ (clock_mhz et al., value → 1000/MHz ns) and a
pll_mismatch_warned flag that rewords the summary to "mismatch under PLL
topology (advisory)".
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import fpga_sdc_clock_constraint_check as FC  # noqa: E402


def _project(tmp_path, sdc_text: str, l8: dict) -> Path:
    (tmp_path / "phase2" / "stage1" / "fpga").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "fpga" / "top.sdc").write_text(sdc_text)
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "top.v").write_text(
        "module top(input wire clk, input wire d, output reg q);\n"
        "  always @(posedge clk) q <= d;\nendmodule\n"
    )
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    (tmp_path / "phase1" / "generated_docs" / "L8_RTL_CONSTANTS.json").write_text(
        json.dumps(l8)
    )
    return tmp_path


# ── (a) clock_mhz synonym: Rule 3 must fire on canonical projects ───────────

def test_find_rtl_clock_period_resolves_clock_mhz(tmp_path):
    proj = _project(tmp_path,
                    "create_clock -name clk -period 10.0 [get_ports clk]\n",
                    {"clock_mhz": 100})
    assert FC.find_rtl_clock_period_ns(proj) == 10.0


def test_rule3_fires_on_clock_mhz_only_l8_doc(tmp_path):
    """The issue's exact shape: L8 carries only clock_mhz; SDC period is
    100% off (20 ns vs 10 ns RTL) → Rule 3 must FAIL, not bare-PASS."""
    proj = _project(tmp_path,
                    "create_clock -name clk -period 20.0 [get_ports clk]\n",
                    {"clock_mhz": 100})
    verdict, msgs = FC.audit(proj)
    assert verdict == "FAIL"
    assert any("FPGA_SDC_PERIOD_MISMATCH" in m for m in msgs)


def test_rule3_passes_when_clock_mhz_consistent(tmp_path):
    proj = _project(tmp_path,
                    "create_clock -name clk -period 10.0 [get_ports clk]\n",
                    {"clock_mhz": 100})
    verdict, msgs = FC.audit(proj)
    assert verdict == "PASS"
    assert any("matches" in m for m in msgs)


# ── (b) PLL WARN path must not claim a match in the summary ────────────────

def test_pll_warn_summary_does_not_claim_match(tmp_path):
    sdc = (
        "create_clock -name board_clk -period 20.0 [get_ports clk]\n"
        "create_generated_clock -name pll_clk -source [get_ports clk] "
        "-multiply_by 2 [get_pins pll|outclk]\n"
    )
    proj = _project(tmp_path, sdc, {"clock_mhz": 100})
    verdict, msgs = FC.audit(proj)
    assert verdict == "PASS"
    assert any("FPGA_SDC_PERIOD_BOARD_MISMATCH" in m for m in msgs)
    summary = msgs[-1]
    assert "matches" not in summary
    assert "advisory" in summary


def test_summary_still_claims_match_without_mismatch(tmp_path):
    sdc = (
        "create_clock -name board_clk -period 10.0 [get_ports clk]\n"
        "create_generated_clock -name pll_clk -source [get_ports clk] "
        "-multiply_by 2 [get_pins pll|outclk]\n"
    )
    proj = _project(tmp_path, sdc, {"clock_mhz": 100})
    verdict, msgs = FC.audit(proj)
    assert verdict == "PASS"
    assert "matches" in msgs[-1]


# ── regression: pre-existing synonyms keep working ──────────────────────────

def test_clock_period_ns_synonym_still_works(tmp_path):
    proj = _project(tmp_path,
                    "create_clock -name clk -period 10.0 [get_ports clk]\n",
                    {"CLOCK_PERIOD_NS": 10})
    assert FC.find_rtl_clock_period_ns(proj) == 10.0
