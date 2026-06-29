"""spec_complete_extract — the GENERAL additive prose-fact extractors.

Three pure readers added so a blind run carries more of the STATED contract into
authoring (never gating): the explicit latency contract (#705 yard-stick), the
literally-named port/signal list, and the clock→domain binding map. Each test
proves a representative-prose PASS and an absent/ambiguous None (§4.05 no-fabricate),
plus that the facts surface additively through `assess_spec`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import spec_complete_extract as E  # noqa: E402


# ── (1) explicit latency contract ────────────────────────────────────────
def test_latency_contract_total_and_steps():
    prompt = (
        "The pipeline registers the inputs, then computes, then asserts the "
        "result. Total latency = WIDTH + 2 cycles: 1 cycle to register the "
        "inputs, WIDTH cycles in the COMPUTE state, and 1 cycle to assert the "
        "output.")
    c = E.extract_latency_contract(prompt)
    assert c is not None
    assert c["total_expr"] == "WIDTH + 2"
    pairs = {(s["cycles"], s["desc"].lower()) for s in c["steps"]}
    assert ("1", "register the inputs") in pairs
    assert ("WIDTH", "in the compute state") in pairs or any(
        s["cycles"] == "WIDTH" for s in c["steps"])
    assert ("1", "assert the output") in pairs


def test_latency_contract_numeric_total_only():
    c = E.extract_latency_contract(
        "The block introduces a total latency of 3 clock cycles.")
    assert c is not None and c["total_expr"] == "3"


def test_latency_contract_absent_is_none():
    # no latency framing, and a lone "few cycles" is not an exact step
    assert E.extract_latency_contract(
        "Design a combinational adder. It settles after a few cycles.") is None
    assert E.extract_latency_contract("") is None


def test_latency_contract_contradictory_total_is_ambiguous():
    # two different stated totals -> total_expr None, but steps may still surface
    c = E.extract_latency_contract(
        "Total latency = 3 cycles. Elsewhere the total latency is 5 cycles.")
    # contradictory totals collapse to None; with no steps the whole thing is None
    assert c is None or c["total_expr"] is None


# ── (2) port / signal names from a table or bullet list ──────────────────
def test_port_signals_from_table():
    prompt = (
        "## Signals\n"
        "| Signal | Direction | Width | Description |\n"
        "|--------|-----------|-------|-------------|\n"
        "| s_ready | output | 1 | handshake ready |\n"
        "| s_data  | input  | 8 | payload byte |\n")
    out = E.extract_port_signals(prompt)
    assert out is not None
    by = {p["name"]: p for p in out["ports"]}
    assert by["s_ready"]["dir"] == "output" and by["s_ready"]["width"] == 1
    assert by["s_data"]["dir"] == "input" and by["s_data"]["width"] == 8


def test_port_signals_from_backticked_bullets():
    prompt = (
        "- `clk_i`: Clock for the Wishbone side.\n"
        "- `s_ready` (output): asserted when the sink can accept.\n"
        "- `[7:0] s_data`: the payload byte, synchronous to clk_i.\n"
        "- Note: this bullet is prose, not a port.\n")
    out = E.extract_port_signals(prompt)
    assert out is not None
    names = {p["name"] for p in out["ports"]}
    assert {"clk_i", "s_ready", "s_data"} <= names
    assert "Note" not in names  # ordinary prose bullet ignored
    by = {p["name"]: p for p in out["ports"]}
    assert by["s_ready"]["dir"] == "output"
    assert by["s_data"].get("width") == 7  # from the [7:0] prefix (hi index)
    assert by["s_data"].get("clock") == "clk_i"  # clock-domain binding surfaced


def test_port_signals_absent_is_none():
    assert E.extract_port_signals(
        "This design has some ports and reads data, but names none of them.") is None
    assert E.extract_port_signals("") is None


# ── (3) clock-domain binding ─────────────────────────────────────────────
def test_clock_domains_colon_bullets():
    prompt = (
        "- `clk_i`: Wishbone\n"
        "- `hclk`: AHB clock\n"
        "- `clk_i`: Clock for the Wishbone side (ignored — first binding wins)\n")
    out = E.extract_clock_domains(prompt)
    assert out is not None
    assert out["clk_i"] == "Wishbone"
    assert out["hclk"] == "AHB"


def test_clock_domains_clock_for_phrase():
    out = E.extract_clock_domains("- `pclk`: Clock for the APB side.")
    assert out == {"pclk": "APB"}


def test_clock_domains_absent_and_freq_only_is_none():
    # a free-running clock with only a frequency is NOT a domain binding
    assert E.extract_clock_domains(
        "- `clk`: free-running clock at 100 MHz") is None
    assert E.extract_clock_domains("Design a UART with one clock.") is None
    assert E.extract_clock_domains("") is None


# ── additive surfacing through assess_spec (no regression to verdict) ─────
def test_assess_spec_surfaces_facts_additively():
    prompt = (
        "Two-clock bridge. Total latency = 2 cycles.\n"
        "- `clk_i`: Wishbone\n"
        "- `hclk`: AHB\n"
        "| Signal | Direction | Width |\n"
        "|--------|-----------|-------|\n"
        "| dat_o | output | 32 |\n")
    spec = E.assess_spec(prompt, inputs=["clk_i", "hclk"], outputs=["dat_o"],
                         module_name="bridge")
    assert spec["latency_contract"]["total_expr"] == "2"
    assert spec["clock_domains"] == {"clk_i": "Wishbone", "hclk": "AHB"}
    assert any(p["name"] == "dat_o" for p in spec["port_signals"]["ports"])
    # the additive keys never disturb the completeness verdict
    assert spec["completeness"] in ("COMPLETE", "INCOMPLETE_EXTRACTION_GAP",
                                    "INCOMPLETE_SPEC_ABSENT")


def test_assess_spec_facts_none_when_absent():
    spec = E.assess_spec("Plain prose, no ports.", inputs=[], outputs=[])
    assert spec["latency_contract"] is None
    assert spec["port_signals"] is None
    assert spec["clock_domains"] is None
