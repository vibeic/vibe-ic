#!/usr/bin/env python3
"""ORGANIC #297 CASE A — global routing bought routability by stripping the
non-default rule off CLOCK nets, and the flow disclosed it in NO outcome.

Field evidence (sky130A):
  * ibex          — made the trade, STILL lost to congestion (GRT-0116),
                    FAILed with only `rc=1 log_tail=<2000 chars>`
  * opentitan_aes — made the same trade, routing SUCCEEDED, the whole run went
                    GREEN, and two clock nets were routed at DEFAULT
                    width/spacing with nobody told

The second is the dangerous half: a green run is exactly when nobody re-reads
the log, so an undisclosed clock-quality trade ships as a clean result.

DISCLOSURE-ONLY (§4.05): the verdict tier is unchanged. A trade is not
automatically wrong — it is automatically something a human must be told about.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import route_congestion_trade_disclosure as R  # noqa: E402

# THE REAL OpenROAD message. The first version of this file used a fixture I
# invented ("Net <n> has a non-default rule that was removed"), which made the
# suite green while the parser returned the net name "Disabled" on every real
# run. Fixtures must be the tool's ACTUAL output.
_TRADE = ("[WARNING GRT-0273] Disabled NDR (to reduce congestion) "
          "for net: {net}\n")
# The alternative spelling is still accepted, so an upstream reword degrades to
# the generic form rather than silently yielding a junk token.
_TRADE_ALT = ("[WARNING GRT-0273] Net {net} has a non-default rule that was "
              "removed to allow routing.\n")


def _project(tmp_path, log: str, sdc: str = "") -> Path:
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "pnr.log").write_text(log)
    if sdc:
        (pnr / "constraints.sdc").write_text(sdc)
    return tmp_path


def test_297_green_run_still_discloses_the_clock_trade(tmp_path):
    """THE dangerous half: routing SUCCEEDED, so nobody re-reads the log."""
    log = (_TRADE.format(net="clk_i") + _TRADE.format(net="clk_i_gated")
           + "[INFO DRT-0199] Detailed routing completed. 0 violations.\n")
    sdc = ("create_clock -name clk -period 10 [get_ports clk_i]\n"
           "create_generated_clock -name clk_i_gated -source [get_ports clk_i] "
           "[get_pins gate/Q]\n")
    rep = R.audit(_project(tmp_path, log, sdc))
    assert rep["disclosed"] is True
    assert rep["trades"] == ["clk_i", "clk_i_gated"]
    assert sorted(rep["clock_trades"]) == ["clk_i", "clk_i_gated"]
    assert rep["congestion_aborted"] is False       # the run passed


def test_297_generated_clock_is_classified_too(tmp_path):
    """A gated/divided clock is declared by create_generated_clock, not
    create_clock. Reading only the latter under-reports: measured 2 clock nets
    traded, only 1 classified."""
    sdc_plain = "create_clock -name clk -period 10 [get_ports clk_i]\n"
    log = _TRADE.format(net="clk_i") + _TRADE.format(net="clk_i_gated")
    only_create = R.audit(_project(tmp_path, log, sdc_plain))
    assert only_create["clock_trades"] == ["clk_i"]      # the under-report
    sdc_full = sdc_plain + ("create_generated_clock -name clk_i_gated "
                            "-source [get_ports clk_i] [get_pins g/Q]\n")
    both = R.audit(_project(tmp_path, log, sdc_full))
    assert sorted(both["clock_trades"]) == ["clk_i", "clk_i_gated"]


def test_297_failed_run_discloses_trade_and_the_abort(tmp_path):
    """ibex: traded and STILL lost. Both facts must survive."""
    log = _TRADE.format(net="clk_i") + "[ERROR GRT-0116] congestion.\n"
    rep = R.audit(_project(
        tmp_path, log, "create_clock -name clk -period 10 [get_ports clk_i]\n"))
    assert rep["clock_trades"] == ["clk_i"]
    assert rep["congestion_aborted"] is True


def test_297_clean_run_reports_nothing(tmp_path):
    """No false disclosure — silence must stay correct when it IS correct."""
    rep = R.audit(_project(tmp_path, "[INFO GRT-0018] wirelength 999\n"))
    assert rep["disclosed"] is False and rep["trades"] == []
    assert rep["congestion_aborted"] is False


def test_297_no_clock_evidence_is_flagged_not_guessed(tmp_path):
    """Without SDC evidence the classifier must NOT guess from the name — it
    must say so, so the reader treats every trade as potentially a clock."""
    rep = R.audit(_project(tmp_path, _TRADE.format(net="clk_i")))
    assert rep["trades"] == ["clk_i"]
    assert rep["clock_evidence_available"] is False
    assert rep["clock_trades"] == []


def test_297_trade_is_persisted_as_an_artefact(tmp_path):
    """A line in a log nobody reads is not disclosure."""
    proj = _project(tmp_path, _TRADE.format(net="clk_i"),
                    "create_clock -name clk -period 10 [get_ports clk_i]\n")
    R.write_report(proj, R.audit(proj))
    out = proj / "reports" / "route_congestion_trades.json"
    assert out.is_file()
    assert json.loads(out.read_text())["clock_trades"] == ["clk_i"]


def test_297_duplicate_warnings_are_deduplicated(tmp_path):
    log = _TRADE.format(net="clk_i") * 5
    assert R.audit(_project(tmp_path, log))["trades"] == ["clk_i"]


def test_297_anchored_on_the_message_id(tmp_path):
    """Anchoring on GRT-0273 rather than the prose means an upstream wording
    change cannot silently disable the disclosure."""
    log = "[WARNING GRT-0273] Net foo_net wording changed upstream entirely\n"
    assert R.audit(_project(tmp_path, log))["trades"] == ["foo_net"]


def test_297_real_openroad_wording_is_what_ships(tmp_path):
    """REGRESSION for a defect of my own, shipped in v1.5.83.

    The parser was written against a fixture I invented. OpenROAD's real
    message is `Disabled NDR (to reduce congestion) for net: <n>`, against
    which the old pattern returned the net name "Disabled" — reporting a trade
    on a net that does not exist while MISSING the real one, on every real run.
    Green tests, because they fed the invented wording back to themselves.
    """
    log = _TRADE.format(net="clknet_0_clk_regs") + _TRADE.format(net="clk_regs")
    rep = R.audit(_project(tmp_path, log))
    assert rep["trades"] == ["clknet_0_clk_regs", "clk_regs"], rep["trades"]
    assert "Disabled" not in rep["trades"], (
        "the message VERB must never be reported as the net it names")


def test_297_alternative_wording_still_parses(tmp_path):
    rep = R.audit(_project(tmp_path, _TRADE_ALT.format(net="clk_i")))
    assert rep["trades"] == ["clk_i"]


def test_297_both_spellings_in_one_log(tmp_path):
    log = _TRADE.format(net="clknet_0") + _TRADE_ALT.format(net="clk_i")
    assert set(R.audit(_project(tmp_path, log))["trades"]) == {"clknet_0", "clk_i"}
