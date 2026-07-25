#!/usr/bin/env python3
"""Smoke tests for l17_channel_catalog_consumer_contract_check (layergate-6).

NEGATIVE CONTROL IS THE POINT. Every rail is asserted in BOTH directions on the
same rail: a deliberately-gutted layer FAILS, a well-formed one PASSES.

All fixtures are SYNTHESIZED neutral data. No real design's files are copied
and no design/PDK/vendor/protocol name appears.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "l17_channel_catalog_consumer_contract_check.py")


def _run(project: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project), *extra],
        capture_output=True, text=True)


def _cats(cp: subprocess.CompletedProcess) -> set[str]:
    return {f["category"] for f in json.loads(cp.stdout)["findings"]}


# ---------------------------------------------------------------------------
# Fixture builders — synthesized, neutral
# ---------------------------------------------------------------------------
def _mk(tmp: Path, l17: dict, *, l9: dict | None = None,
        clocked: bool = True) -> Path:
    proj = tmp / "run"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    if l9 is None:
        l9 = {"top_module": "widget_top", "ports": [
            {"name": "core_clk", "direction": "input", "width": 1},
            {"name": "core_rst_n", "direction": "input", "width": 1},
            {"name": "result_valid", "direction": "output", "width": 1}]}
    if clocked:
        l9.setdefault("clock_domains", [{"name": "core_clk"}])
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps(l17))
    return proj


_WELL_FORMED = {
    "extraction_status": "EXTRACTED",
    "extraction_evidence": [{"line": 40, "quote": "…"}],
    "fields": {
        "channels": [
            {"name": "load_port", "direction_master": "Master",
             "purpose": "carries the operand into the datapath"},
            {"name": "result_port", "direction_master": "Slave",
             "purpose": "carries the computed result out"},
        ],
        "global_signals": [
            {"name": "core_clk", "direction": "input", "purpose": "clock"},
            {"name": "core_rst_n", "direction": "input", "purpose": "reset"},
        ],
        "handshake_pairs": {
            "load_port": {"valid": "load_port", "ready": "result_port"}},
        "dependency_graph": {
            "rule": "the load handshake precedes the result handshake"},
    },
}

# The observed hazard: the producer says it extracted NOTHING, the catalog is
# empty, yet narrative prose asserts handshake facts about signals from some
# other design. Every non-empty heuristic reads this as POPULATED.
_TEMPLATE_LEAK = {
    "extraction_status": "EXTRACTION_FOUND_NOTHING",
    "fields": {
        "channels": [], "global_signals": [],
        "channel_counts": {"channels": 0, "signals_per_channel": {}},
        "handshake_pairs": {},
        "dependency_graph": {
            "common_rule": "VALID once asserted MUST remain asserted until "
                           "READY also asserted on the same cycle",
            "read_rule": "FOO_VALID precedes BAR_VALID; BAR_VALID stays "
                         "asserted until FOO_READY accepted"},
    },
}


# ---------------------------------------------------------------------------
# RAIL: template content the producer never extracted. NEGATIVE CONTROL PAIR.
# ---------------------------------------------------------------------------
def test_NEGATIVE_template_without_extraction(tmp_path):
    """GUTTED: status=found-nothing + empty catalog + narrative => FAIL."""
    r = _run(_mk(tmp_path, _TEMPLATE_LEAK))
    assert r.returncode == 1, r.stdout
    assert "TEMPLATE_WITHOUT_EXTRACTION" in _cats(r)


def test_POSITIVE_well_formed_catalog_passes(tmp_path):
    """WELL-FORMED: narrative backed by a real catalog => PASS."""
    r = _run(_mk(tmp_path, _WELL_FORMED))
    assert r.returncode == 0, r.stdout
    assert json.loads(r.stdout)["summary"]["error_count"] == 0


def test_POSITIVE_honest_empty_layer_passes(tmp_path):
    """An empty catalog that asserts NOTHING is truthful and must PASS."""
    r = _run(_mk(tmp_path, {"extraction_status": "EXTRACTION_FOUND_NOTHING",
                            "fields": {"channels": [], "global_signals": [],
                                       "dependency_graph": {},
                                       "handshake_pairs": {}}}))
    assert r.returncode == 0, r.stdout
    assert "TEMPLATE_WITHOUT_EXTRACTION" not in _cats(r)


# ---------------------------------------------------------------------------
# RAIL: structured narrative naming an undeclared signal. NEGATIVE PAIR.
# ---------------------------------------------------------------------------
def test_NEGATIVE_handshake_pair_names_undeclared_signal(tmp_path):
    gutted = json.loads(json.dumps(_WELL_FORMED))
    gutted["fields"]["handshake_pairs"] = {
        "ghost": {"valid": "not_a_signal_here", "ready": "nor_this_one"}}
    r = _run(_mk(tmp_path, gutted))
    assert r.returncode == 1, r.stdout
    assert "NARRATIVE_NAMES_UNDECLARED_SIGNAL" in _cats(r)


def test_POSITIVE_handshake_pair_over_declared_signals(tmp_path):
    r = _run(_mk(tmp_path, _WELL_FORMED))
    assert "NARRATIVE_NAMES_UNDECLARED_SIGNAL" not in _cats(r), r.stdout


# ---------------------------------------------------------------------------
# RAIL: consumer port derivation. NEGATIVE CONTROL PAIRS.
# ---------------------------------------------------------------------------
def test_NEGATIVE_channel_silently_dropped_by_consumer(tmp_path):
    """A channel with an unsanitizable name contributes zero ports."""
    gutted = json.loads(json.dumps(_WELL_FORMED))
    gutted["fields"]["channels"].append(
        {"name": "  ", "direction_master": "Master", "purpose": "ghost"})
    r = _run(_mk(tmp_path, gutted))
    assert r.returncode == 1, r.stdout
    assert "CHANNEL_NOT_PORT_DERIVABLE" in _cats(r)


def test_NEGATIVE_channel_direction_silently_becomes_inout(tmp_path):
    """No direction key the consumer reads => a bidirectional top port."""
    gutted = json.loads(json.dumps(_WELL_FORMED))
    gutted["fields"]["channels"][0].pop("direction_master")
    r = _run(_mk(tmp_path, gutted))
    assert r.returncode == 1, r.stdout
    assert "CHANNEL_DIRECTION_SILENTLY_INOUT" in _cats(r)


def test_NEGATIVE_channel_group_collapses_to_one_port(tmp_path):
    """GUTTED: a channel that is a GROUP of member signals emits only the
    group name, so every member silently vanishes from the interface."""
    gutted = json.loads(json.dumps(_WELL_FORMED))
    gutted["fields"]["channels"] = [{
        "name": "bus_group", "direction_majority": "Master",
        "purpose": "a channel group carrying its member rows",
        "signals": [{"name": "bus_addr", "direction": "Master",
                     "semantics": "address"},
                    {"name": "bus_data", "direction": "Master",
                     "semantics": "payload"},
                    {"name": "bus_ack", "direction": "Slave",
                     "semantics": "acknowledge"}]}]
    gutted["fields"]["handshake_pairs"] = {}
    r = _run(_mk(tmp_path, gutted))
    assert r.returncode == 1, r.stdout
    assert "CHANNEL_GROUP_COLLAPSED_TO_ONE_PORT" in _cats(r)
    ev = [f for f in json.loads(r.stdout)["findings"]
          if f["category"] == "CHANNEL_GROUP_COLLAPSED_TO_ONE_PORT"][0]
    assert ev["evidence"]["collapsed"][0]["declared_member_signals"] == 3
    assert ev["evidence"]["collapsed"][0]["ports_contributed"] == 1


def test_POSITIVE_flat_channels_do_not_collapse(tmp_path):
    """WELL-FORMED: one channel per signal, nothing to lose => PASS."""
    r = _run(_mk(tmp_path, _WELL_FORMED))
    assert "CHANNEL_GROUP_COLLAPSED_TO_ONE_PORT" not in _cats(r), r.stdout


def test_POSITIVE_every_channel_derives_a_directed_port(tmp_path):
    r = _run(_mk(tmp_path, _WELL_FORMED))
    cats = _cats(r)
    assert "CHANNEL_NOT_PORT_DERIVABLE" not in cats
    assert "CHANNEL_DIRECTION_SILENTLY_INOUT" not in cats


# ---------------------------------------------------------------------------
# RAIL: clock reachability. NEGATIVE CONTROL PAIR.
#
# derive_signals AUTO-ADDS a "clk" stub, so "did a clock come out?" can never
# fail. The rail therefore tests whether the emitted clock was DECLARED by the
# layers the consumer reads, or INVENTED to fill the hole.
# ---------------------------------------------------------------------------
def test_NEGATIVE_clock_port_synthesised_because_no_layer_declares_it(tmp_path):
    """GUTTED: design declares a clock domain; L17 and L9 declare no clock
    PORT => the consumer fabricates one => FAIL."""
    l9 = {"top_module": "widget_top",
          "ports": [{"name": "data_out", "direction": "output", "width": 1}],
          "clock_domains": [{"name": "core_clk"}]}
    l17 = {"extraction_status": "EXTRACTED",
           "fields": {"channels": [
               {"name": "data_out", "direction_master": "Slave",
                "purpose": "result"}],
               "global_signals": []}}
    r = _run(_mk(tmp_path, l17, l9=l9))
    assert r.returncode == 1, r.stdout
    assert "CLOCK_PORT_SYNTHESISED_BY_CONSUMER" in _cats(r)
    rep = json.loads(r.stdout)
    assert "clk" in rep["info"]["ports_synthesised_by_consumer"]


def test_POSITIVE_declared_clock_is_not_flagged(tmp_path):
    """WELL-FORMED: L17 declares the clock the design says it has => PASS."""
    r = _run(_mk(tmp_path, _WELL_FORMED))
    assert "CLOCK_PORT_SYNTHESISED_BY_CONSUMER" not in _cats(r), r.stdout


def test_combinational_design_is_not_asked_for_a_clock(tmp_path):
    """No FP on a design whose own L-docs declare nothing sequential."""
    l9 = {"top_module": "widget_top",
          "ports": [{"name": "a_in", "direction": "input", "width": 1},
                    {"name": "y_out", "direction": "output", "width": 1}]}
    l17 = {"extraction_status": "EXTRACTED",
           "fields": {"channels": [{"name": "a_in",
                                    "direction_master": "Master",
                                    "purpose": "operand"}],
                      "global_signals": []}}
    r = _run(_mk(tmp_path, l17, l9=l9, clocked=False))
    assert "CLOCK_PORT_SYNTHESISED_BY_CONSUMER" not in _cats(r), r.stdout


# ---------------------------------------------------------------------------
# Modes, applicability, generality
# ---------------------------------------------------------------------------
def test_advisory_flag_downgrades_a_real_failure(tmp_path):
    proj = _mk(tmp_path, _TEMPLATE_LEAK)
    blocking, advisory = _run(proj), _run(proj, "--advisory")
    assert blocking.returncode == 1 and advisory.returncode == 0
    assert _cats(blocking) == _cats(advisory)


def test_skips_cleanly_when_layer_absent(tmp_path):
    proj = tmp_path / "empty"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    assert _run(proj).returncode == 2


def test_the_gate_actually_imported_the_consumer(tmp_path):
    """The gate's whole claim is that it runs the CONSUMER'S derivation."""
    rep = json.loads(_run(_mk(tmp_path, _WELL_FORMED)).stdout)
    assert rep["info"]["consumer_import"] == "phase2_scaffold_gen"


def test_no_design_or_vendor_literal_in_the_gate():
    src = PROG.read_text()
    body = src.split('"""', 2)[-1]
    banned = ("sky130", "gf180", "ihp-sg13", "nangate", "ibex", "AXI",
              "ARVALID", "ACLK", "VDD", "VSS", "spm", "subservient")
    for tok in banned:
        assert tok not in body, f"design/PDK literal {tok!r} leaked into gate"
