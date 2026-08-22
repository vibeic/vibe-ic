#!/usr/bin/env python3
"""ORGANIC #309 — a signal net on a hard-macro POWER pin aborts ALL detailed
routing.

A macro declares a pin `USE POWER` in its OWN LEF. RTL ties it, synthesis
inserts a TIEHI/TIELO to drive it, and a SIGNAL net lands on a POWER terminal.
TritonRoute does not skip that net — it aborts detailed routing entirely.
Measured: 3278 signal nets, ZERO routed; LVS and STA unreachable; the GDS a
placed-but-unrouted shell; the same cause across six plugin versions, surfacing
only as a causally-opaque DRT-0307 five steps downstream.

The information exists in Phase 1 (the LEF says USE POWER) but never reached
the power-intent layer the back end consumes. The completeness model asked
"does this token appear in ANY layer" and the pin name does appear in a
descriptive datasheet layer — so it scored as captured. It measured the thing
next to it.

ONE decision module, imported by BOTH phases, so the Phase-1 warning and the
Phase-3 block cannot drift apart.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import hardmacro_supply_intent as H  # noqa: E402

_LEF = """
MACRO OTP_128X8
  PIN VDD
    DIRECTION INOUT ; USE POWER ;
  END VDD
  PIN VSS
    DIRECTION INOUT ; USE GROUND ;
  END VSS
  PIN VPP
    DIRECTION INOUT ; USE POWER ;
  END VPP
  PIN D0
    DIRECTION INPUT ; USE SIGNAL ;
  END D0
END OTP_128X8
"""

_RAILS = {"fields": {"power_rails": [{"rail": "VDD / core supply (1.8 V)"},
                                     {"rail": "VSS"}]}}


def test_309_lef_pg_pins_are_extracted_signal_pins_are_not():
    pins = H.lef_pg_pins(_LEF)
    assert {(p["pin"], p["use"]) for p in pins} == {
        ("VDD", "POWER"), ("VSS", "GROUND"), ("VPP", "POWER")}
    assert all(p["pin"] != "D0" for p in pins), "a SIGNAL pin is not a supply"
    assert all(p["master"] == "OTP_128X8" for p in pins)


def test_309_the_gap_is_found_and_the_bindable_pins_are_bound():
    """The whole point: bind what CAN be bound, block only on what cannot."""
    rep = H.assess([_LEF], _RAILS)
    assert {p["pin"] for p in rep["accounted"]} == {"VDD", "VSS"}
    assert {p["pin"] for p in rep["gaps"]} == {"VPP"}


def test_309_anticheat_a_ghost_rail_does_not_buy_coverage():
    """LOAD-BEARING. Without this a design manufactures coverage by naming a
    rail that exists only inside the mapping — 100% coverage against rails that
    do not exist."""
    l21 = {"fields": {
        "power_rails": [{"rail": "VDD / core supply (1.8 V)"}],
        "hard_macro_supplies": [{"master": "OTP_128X8", "pin": "VPP",
                                 "rail": "VPP_GHOST_RAIL"}]}}
    rep = H.assess([_LEF], l21)
    vpp = next(p for p in rep["pins"] if p["pin"] == "VPP")
    assert vpp["status"] == "rail_undeclared"
    assert vpp not in rep["accounted"]
    assert vpp in rep["gaps"]


def test_309_a_mapping_to_an_independently_declared_rail_counts():
    l21 = {"fields": {
        "power_rails": [{"rail": "VDD / core supply (1.8 V)"}, {"rail": "VPP_PROG"},
                        {"rail": "VSS"}],
        "hard_macro_supplies": [{"master": "OTP_128X8", "pin": "VPP",
                                 "rail": "VPP_PROG"}]}}
    rep = H.assess([_LEF], l21)
    assert rep["gaps"] == []
    assert next(p for p in rep["pins"] if p["pin"] == "VPP")["status"] == "declared_rail"


def test_309_an_owned_integration_gap_is_disclosure_not_silence():
    l21 = {"fields": {
        "power_rails": [{"rail": "VDD / core supply (1.8 V)"}, {"rail": "VSS"}],
        "hard_macro_supplies": [{"master": "OTP_128X8", "pin": "VPP",
                                 "integration_gap": True}]}}
    rep = H.assess([_LEF], l21)
    assert rep["gaps"] == []
    assert next(p for p in rep["pins"] if p["pin"] == "VPP")["status"] == "declared_gap"


def test_309_rail_name_match_is_whole_token_both_directions():
    """A mis-bound rail is WORSE than a reported gap. Splitting rail names on
    the underscore made `AVDD_REF / analog reference` yield the token `AVDD`,
    so pin AVDD wrongly matched it while pin AVDD_REF matched NOTHING — both
    directions wrong. Caught by this test during development."""
    rails = ["AVDD_REF / analog reference", "VSS", "VDD / core supply (1.8 V)"]
    assert H._rail_token_match("AVDD_REF", rails) == "AVDD_REF / analog reference"
    assert H._rail_token_match("VDD", rails) == "VDD / core supply (1.8 V)"
    assert H._rail_token_match("AVDD", rails) is None
    assert H._rail_token_match("VSSA", rails) is None
    assert H._rail_token_match("REF", rails) is None


def test_309_no_macro_lefs_is_not_a_gap():
    """A design with no hard macros must not be blocked by a macro rule."""
    rep = H.assess([], _RAILS)
    assert rep["pins"] == [] and rep["gaps"] == []


def test_309_phase3_blocks_before_routing(tmp_path):
    """Phase 3 must BLOCK — #306 measured that 62 of 72 gates can only describe
    a run afterwards, and a gate that cannot stop this one lets a 20-minute run
    emit an empty shell."""
    import phase3_one_shot_runner as p3
    lef = tmp_path / "otp.lef"
    lef.write_text(_LEF)
    gd = tmp_path / "generated_docs"
    gd.mkdir()
    (gd / "L21_POWER_INTENT.json").write_text(json.dumps(_RAILS))

    class _Pdk:
        macro_lefs = [str(lef)]

    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk())
    assert d is not None and d["blocking"] is True
    assert {g["pin"] for g in d["bound"]} == {"VDD", "VSS"}
    assert {g["pin"] for g in d["gaps"]} == {"VPP"}
    assert "DRT-0307" in d["message"] and "OTP_128X8/VPP" in d["message"]


def test_309_phase3_does_not_block_when_everything_is_accounted(tmp_path):
    """No false block: a fully-declared design must route."""
    import phase3_one_shot_runner as p3
    lef = tmp_path / "otp.lef"
    lef.write_text(_LEF)
    gd = tmp_path / "generated_docs"
    gd.mkdir()
    (gd / "L21_POWER_INTENT.json").write_text(json.dumps({"fields": {
        "power_rails": [{"rail": "VDD / core supply (1.8 V)"}, {"rail": "VSS"},
                        {"rail": "VPP_PROG"}],
        "hard_macro_supplies": [{"master": "OTP_128X8", "pin": "VPP",
                                 "rail": "VPP_PROG"}]}}))

    class _Pdk:
        macro_lefs = [str(lef)]

    d = p3._macro_supply_preroute_decision(tmp_path, _Pdk())
    assert d is not None and d["blocking"] is False


def test_309_both_phases_share_one_decision_module():
    """Two copies of this judgement would drift, and a drifting supply rule is
    how the pin got lost. Both phases must IMPORT the module."""
    p3 = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    p1 = (_PROGRAMS / "ip_integration_check.py").read_text()
    assert "import hardmacro_supply_intent" in p3
    assert "import hardmacro_supply_intent" in p1


def test_309_phase1_warns_without_blocking(tmp_path):
    """Phase 1 must make the requirement flow into the power-intent layer NOW,
    without failing the run — Phase 3 is where it blocks."""
    import ip_integration_check as ip
    v = tmp_path / "input" / "pdk_local" / "vendor"
    v.mkdir(parents=True)
    (v / "otp.lef").write_text(_LEF)
    (v / "otp.lib").write_text("library (otp) { cell (OTP_128X8) { area : 1.0; } }")
    (v / "otp.gds").write_text("HEADER")
    (v / "otp.v").write_text("module OTP_128X8(); endmodule")
    gd = tmp_path / "generated_docs"
    gd.mkdir()
    (gd / "L21_POWER_INTENT.json").write_text(json.dumps(_RAILS))
    rep = ip.audit(tmp_path)
    rules = [f["rule"] for f in rep["findings"]]
    assert "IP_MACRO_SUPPLY_UNDECLARED" in rules
    sev = next(f["severity"] for f in rep["findings"]
               if f["rule"] == "IP_MACRO_SUPPLY_UNDECLARED")
    assert sev == "WARNING"
    assert rep["verdict"] != "FAIL"


# ── #348: the escape hatch had no producer ───────────────────────────────────
# #309 shipped a correct escape hatch — a design may declare a rail and clear
# the gate — but `declared_rails` reads `L21.fields.power_rails` /
# `power_domains[]`, and across the real IC designs in this repo those
# structured fields are empty (measured: 3 of 30 usable). So every macro PG pin
# fell to `undeclared` and a correctly-integrated design had NO legitimate way
# through: the hatch existed and the door was locked.
#
# The rail names DO exist in L21 — in prose fields, not the structured ones the
# consumer reads. That is the producer/consumer split #309 itself was written
# to fix, reproduced inside its own fix.

_DEF_WITH_PDN = """VERSION 5.8 ;
DESIGN x ;
SPECIALNETS 2 ;
    - VGND ( _1_ VNB ) ( _2_ VNB )
      + ROUTED met1 800 + SHAPE FOLLOWPIN ( 0 0 ) ( 100 0 ) ;
    - VPWR ( _1_ VPB ) ( _2_ VPB )
      + ROUTED met1 800 + SHAPE FOLLOWPIN ( 0 10 ) ( 100 10 ) ;
END SPECIALNETS
END DESIGN
"""

_LEF_PDN = """
MACRO SRAM_1K
  PIN VPWR
    DIRECTION INOUT ; USE POWER ;
  END VPWR
  PIN VGND
    DIRECTION INOUT ; USE GROUND ;
  END VGND
  PIN VPP_PROG
    DIRECTION INOUT ; USE POWER ;
  END VPP_PROG
END SRAM_1K
"""

# The shape 27 of 30 real designs actually have: structured fields EMPTY.
_L21_REAL_SHAPE = {"fields": {"power_domains": [], "isolation_cells": [],
                              "power_domains_summary": "VPWR/VGND core rails"}}


def _pdn_project(tmp_path, def_text=_DEF_WITH_PDN):
    d = tmp_path / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True, exist_ok=True)
    (d / "routed.def").write_text(def_text)
    return tmp_path


def test_348_measured_rails_reads_what_the_pdn_actually_built(tmp_path):
    assert H.measured_rails(_pdn_project(tmp_path)) == ["VGND", "VPWR"]


def test_348_no_def_yields_no_measured_rails(tmp_path):
    """Phase 1 has no DEF — it must degrade to the declared fields, not crash
    and not invent rails."""
    assert H.measured_rails(tmp_path) == []


def test_348_the_locked_door_reproduced_then_opened(tmp_path):
    """BOTH directions on one fixture, which is the whole point: with the real
    (empty) L21 shape every pin is blocked; with the measured rails the two
    built rails clear and only the genuinely unbuilt one still blocks."""
    proj = _pdn_project(tmp_path)
    locked = H.assess([_LEF_PDN], _L21_REAL_SHAPE)
    assert {g["pin"] for g in locked["gaps"]} == {"VPWR", "VGND", "VPP_PROG"}, (
        "the locked-door state must reproduce, or the fix proves nothing")
    opened = H.assess([_LEF_PDN], _L21_REAL_SHAPE,
                      extra_rails=H.measured_rails(proj))
    assert {g["pin"] for g in opened["gaps"]} == {"VPP_PROG"}


def test_348_anticheat_survives_measured_rails(tmp_path):
    """A mapping to a rail the PDN did NOT build, and L21 does not declare,
    must still be rail_undeclared. Widening the evidence must not widen the
    cheat surface."""
    proj = _pdn_project(tmp_path)
    l21 = {"fields": {"power_domains": [], "hard_macro_supplies": [
        {"master": "SRAM_1K", "pin": "VPP_PROG", "rail": "VPP_GHOST"}]}}
    rep = H.assess([_LEF_PDN], l21, extra_rails=H.measured_rails(proj))
    vpp = next(p for p in rep["pins"] if p["pin"] == "VPP_PROG")
    assert vpp["status"] == "rail_undeclared"
    assert vpp in rep["gaps"]


def test_348_mapping_to_a_really_built_rail_is_accepted(tmp_path):
    proj = _pdn_project(tmp_path)
    l21 = {"fields": {"power_domains": [], "hard_macro_supplies": [
        {"master": "SRAM_1K", "pin": "VPP_PROG", "rail": "VPWR"}]}}
    rep = H.assess([_LEF_PDN], l21, extra_rails=H.measured_rails(proj))
    assert rep["gaps"] == []
    assert next(p for p in rep["pins"]
                if p["pin"] == "VPP_PROG")["status"] == "declared_rail"


def test_348_a_def_without_specialnets_yields_nothing(tmp_path):
    """A pre-PDN floorplan DEF must not be read as evidence of rails."""
    proj = _pdn_project(tmp_path, "VERSION 5.8 ;\nDESIGN x ;\nEND DESIGN\n")
    assert H.measured_rails(proj) == []


def test_348_phase3_passes_measured_rails_through(tmp_path):
    """Wiring pin: the Phase-3 decision must actually consult the DEF, or the
    fix exists in the library and not in the flow."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    i = src.index("def _macro_supply_preroute_decision")
    j = src.find("\ndef ", i + 1)          # the function's real extent —
    window = src[i:j if j > 0 else None]   # a char-count window rots (#329)
    assert "measured_rails" in window and "extra_rails" in window
