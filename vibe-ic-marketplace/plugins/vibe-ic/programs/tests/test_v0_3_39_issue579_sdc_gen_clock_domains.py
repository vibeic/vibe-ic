"""ORGANIC #579 — sdc_gen read ONLY the legacy top-level ``clock_mhz``
key; the staged-SDC ingest (#554) records the clock contract as
``L8.clock_domains[]`` (freq_mhz/period_ns) with top-level clock_mhz left
null, so on every staged-SDC project the generator fell back to the
50 MHz default and emitted ``create_clock -period 20`` while the sibling
checker (#577) read the real 10 ns period — a permanent
FPGA_SDC_PERIOD_MISMATCH structural-gate FAIL on fully consistent inputs.

Fix: sdc_gen's period resolution consults (1) explicit clock_mhz,
(2) L8.clock_domains[] via _clock_mhz_from_l8_domains (primary/master
record preferred; freq_mhz → period_ns → freq_hz), (3) the staged SDC
files via the shared sdc_constraints module (#556 r2 precedent), and only
then (4) the per-class/board default.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import sdc_gen as G  # noqa: E402
import fpga_sdc_clock_constraint_check as FC  # noqa: E402


def _project(tmp_path: Path, l8: dict) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_module_pins": [
            {"name": "clk", "mode": "input"},
            {"name": "rst_n", "mode": "input"},
            {"name": "dout", "mode": "output"},
        ],
    }))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "chip_top.v").write_text(
        "module chip_top(input wire clk, input wire rst_n,\n"
        "                output reg dout);\n"
        "  always @(posedge clk or negedge rst_n)\n"
        "    if (!rst_n) dout <= 1'b0; else dout <= 1'b1;\n"
        "endmodule\n"
    )
    return tmp_path


# The issue's exact L8 shape: clock_domains carries 10 ns, clock_mhz null.
_L8_STAGED_INGEST = {
    "clock_mhz": None,
    "no_clock_mhz_in_input": True,
    "clock_domains": [
        {"name": "core_clock", "source_pin": "clk",
         "domain_kind": "primary", "role": "master",
         "freq_mhz": 100.0, "freq_hz": 100000000, "period_ns": 10.0},
    ],
}


# ── helper resolution order ─────────────────────────────────────────────────

def test_clock_mhz_from_domains_primary_record():
    assert G._clock_mhz_from_l8_domains(_L8_STAGED_INGEST) == 100.0


def test_clock_mhz_from_domains_period_ns_only():
    l8 = {"clock_domains": [
        {"domain_kind": "primary", "period_ns": 8.0,
         "freq_mhz": None, "freq_hz": None}]}
    assert G._clock_mhz_from_l8_domains(l8) == 125.0


def test_clock_mhz_from_domains_prefers_primary_over_first():
    l8 = {"clock_domains": [
        {"name": "aux", "freq_mhz": 25.0},
        {"name": "core", "domain_kind": "primary", "freq_mhz": 100.0},
    ]}
    assert G._clock_mhz_from_l8_domains(l8) == 100.0


def test_clock_mhz_from_domains_none_without_records():
    assert G._clock_mhz_from_l8_domains({}) is None
    assert G._clock_mhz_from_l8_domains({"clock_domains": []}) is None


# ── the issue's exact 現象 end-state: emitted SDC must carry 10 ns ──────────

def test_sdc_gen_emits_clock_domains_period(tmp_path):
    """Staged-ingest L8 (clock_mhz null, clock_domains 10 ns) → emitted
    create_clock period must be 10, not the 20 ns default."""
    proj = _project(tmp_path, _L8_STAGED_INGEST)
    rc = G.main([str(proj)])
    assert rc == 0
    sdc_files = list((proj / "phase2" / "stage1" / "fpga").glob("*.sdc"))
    assert len(sdc_files) == 1
    text = sdc_files[0].read_text()
    assert "-period 10 " in text, text


def test_sdc_gen_then_checker_consistent(tmp_path):
    """The full reopened gate chain: generator output + checker must agree
    (pre-fix: generator 20 ns vs checker 10 ns → FPGA_SDC_PERIOD_MISMATCH)."""
    proj = _project(tmp_path, _L8_STAGED_INGEST)
    assert G.main([str(proj)]) == 0
    verdict, msgs = FC.audit(proj)
    assert verdict == "PASS", msgs
    assert not any("FPGA_SDC_PERIOD_MISMATCH" in m for m in msgs)


def test_sdc_gen_staged_sdc_fallback_when_no_domains(tmp_path):
    """No clock_domains but staged input/constraints SDC → shared
    sdc_constraints module supplies the period."""
    proj = _project(tmp_path, {"clock_mhz": None})
    cdir = proj / "input" / "constraints"
    cdir.mkdir(parents=True)
    (cdir / "constraint.sdc").write_text(
        "create_clock -name clk -period 12.5 [get_ports clk]\n")
    assert G.main([str(proj)]) == 0
    text = next((proj / "phase2" / "stage1" / "fpga").glob("*.sdc")).read_text()
    assert "-period 12.5 " in text, text


# ── regressions: explicit clock_mhz still wins; default preserved ───────────

def test_explicit_clock_mhz_still_wins(tmp_path):
    l8 = dict(_L8_STAGED_INGEST)
    l8["clock_mhz"] = 25
    proj = _project(tmp_path, l8)
    assert G.main([str(proj)]) == 0
    text = next((proj / "phase2" / "stage1" / "fpga").glob("*.sdc")).read_text()
    assert "-period 40 " in text, text


def test_default_50mhz_without_any_clock_source(tmp_path):
    proj = _project(tmp_path, {"clock_mhz": None})
    assert G.main([str(proj)]) == 0
    text = next((proj / "phase2" / "stage1" / "fpga").glob("*.sdc")).read_text()
    assert "-period 20 " in text, text
