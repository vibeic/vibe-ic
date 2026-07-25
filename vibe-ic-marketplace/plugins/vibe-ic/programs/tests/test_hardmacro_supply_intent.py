"""Unit + negative-control tests for hardmacro_supply_intent (shared module).

The module is the ONE chip-AGNOSTIC place that decides, for a hard macro's own
LEF-typed supply pin, whether the design's power intent (L21) ACCOUNTS for it:
bind-to-declared-rail, acknowledged-integration-gap, implicit name-match, a
dangling mapping (anti-cheat), or wholly undeclared. Phase 1 (ip_integration_check)
and Phase 3 (phase3_one_shot_runner) both consume it so what Phase 1 verifies is
exactly what Phase 3 honors.

Every fixture is SYNTHETIC with neutral names (no real design / PDK / vendor
literal, no real pin-name literal). The made-up macro declares two supply pins
whose names could match a design rail (P_CORE / G_CORE) and one dedicated supply
the design carries no rail for (P_PROG) — the neutral analogue of the real defect.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import hardmacro_supply_intent as H  # noqa: E402


NEUTRAL_LEF = """VERSION 5.8 ;
MACRO NEUTRAL_MACRO
  CLASS BLOCK ;
  SIZE 20 BY 20 ;
  PIN P_CORE
    DIRECTION INOUT ;
    USE POWER ;
  END P_CORE
  PIN G_CORE
    DIRECTION INOUT ;
    USE GROUND ;
  END G_CORE
  PIN P_PROG
    DIRECTION INPUT ;
    USE POWER ;
    SHAPE FEEDTHRU ;
  END P_PROG
  PIN A
    DIRECTION INPUT ;
    USE SIGNAL ;
  END A
END NEUTRAL_MACRO
END LIBRARY
"""


class TestParseMacroSupplyPins:
    def test_only_power_ground(self):
        pins = H.parse_macro_supply_pins(NEUTRAL_LEF)
        assert set(pins) == {"NEUTRAL_MACRO"}
        assert sorted(pins["NEUTRAL_MACRO"]) == [
            ("G_CORE", "GROUND"), ("P_CORE", "POWER"), ("P_PROG", "POWER")]

    def test_signal_excluded(self):
        pins = H.parse_macro_supply_pins(NEUTRAL_LEF)
        assert "A" not in {p for p, _ in pins["NEUTRAL_MACRO"]}

    def test_empty(self):
        assert H.parse_macro_supply_pins("VERSION 5.8 ;\n") == {}


class TestParseDeclaredSupplyMap:
    def test_rail_and_gap_entries(self):
        l21 = {"fields": {"hard_macro_supplies": [
            {"master": "NEUTRAL_MACRO", "pin": "P_PROG", "rail": "P_IO"},
            {"master": "NEUTRAL_MACRO", "pin": "G_CORE",
             "integration_gap": True, "reason": "board-supplied"},
        ]}}
        m = H.parse_declared_supply_map(l21)
        assert m[("NEUTRAL_MACRO", "P_PROG")] == {"rail": "P_IO"}
        assert m[("NEUTRAL_MACRO", "G_CORE")]["gap"] is True

    def test_flat_fields_accepted(self):
        l21 = {"hard_macro_supplies": [
            {"master": "M", "pin": "P", "rail": "R"}]}
        assert H.parse_declared_supply_map(l21) == {("M", "P"): {"rail": "R"}}

    def test_absent_is_empty(self):
        assert H.parse_declared_supply_map({"fields": {}}) == {}
        assert H.parse_declared_supply_map({}) == {}

    def test_malformed_skipped(self):
        l21 = {"fields": {"hard_macro_supplies": [
            {"pin": "P"}, {"master": "M"}, "junk", 3,
            {"master": "M", "pin": "P", "rail": "R"}]}}
        assert H.parse_declared_supply_map(l21) == {("M", "P"): {"rail": "R"}}


class TestDeclaredSupplyRails:
    def test_power_domains_supplies(self):
        l21 = {"fields": {"power_domains": [
            {"name": "PD_TOP", "supply": "P_CORE"},
            {"name": "PD_IO", "supply": "P_IO"}]}}
        assert H.declared_supply_rails(l21) == {"P_CORE", "P_IO"}

    def test_dangling_map_rail_not_counted_as_declared(self):
        # A hard_macro_supplies rail is NOT itself a declared supply — only
        # power_domains supplies are. This is the anti-cheat: a design cannot
        # invent coverage by naming a phantom rail in the map.
        l21 = {"fields": {"hard_macro_supplies": [
            {"master": "M", "pin": "P", "rail": "PHANTOM"}]}}
        assert H.declared_supply_rails(l21) == set()

    def test_empty(self):
        assert H.declared_supply_rails({}) == set()


class TestClassifyMacroSupplyPin:
    RAILS = {"P_CORE", "G_CORE"}

    def test_name_match_is_covered(self):
        assert H.classify_macro_supply_pin(
            "NEUTRAL_MACRO", "P_CORE", "POWER", self.RAILS, {}) == \
            "rail_name_match"

    def test_declared_rail_binding(self):
        m = {("NEUTRAL_MACRO", "P_PROG"): {"rail": "P_CORE"}}
        assert H.classify_macro_supply_pin(
            "NEUTRAL_MACRO", "P_PROG", "POWER", self.RAILS, m) == \
            "declared_rail"

    def test_declared_gap(self):
        m = {("NEUTRAL_MACRO", "P_PROG"): {"gap": True}}
        assert H.classify_macro_supply_pin(
            "NEUTRAL_MACRO", "P_PROG", "POWER", self.RAILS, m) == \
            "declared_gap"

    def test_rail_undeclared_is_anti_cheat(self):
        # Map points at a rail the design does NOT declare -> not covered.
        m = {("NEUTRAL_MACRO", "P_PROG"): {"rail": "PHANTOM"}}
        assert H.classify_macro_supply_pin(
            "NEUTRAL_MACRO", "P_PROG", "POWER", self.RAILS, m) == \
            "rail_undeclared"

    def test_undeclared(self):
        assert H.classify_macro_supply_pin(
            "NEUTRAL_MACRO", "P_PROG", "POWER", self.RAILS, {}) == \
            "undeclared"


class TestCoverageFindings:
    def test_defect_pin_is_undeclared_others_covered(self):
        # RAILS name-match P_CORE/G_CORE; P_PROG has no rail, no map -> the one
        # undeclared finding (the neutral analogue of the routing-crash defect).
        rails = {"P_CORE", "G_CORE"}
        rep = H.coverage_findings(
            [NEUTRAL_LEF], rails, declared_map={})
        undby = {(f["master"], f["pin"]) for f in rep["undeclared"]}
        assert undby == {("NEUTRAL_MACRO", "P_PROG")}
        assert rep["covered_count"] == 2

    def test_declared_gap_clears_the_finding(self):
        rails = {"P_CORE", "G_CORE"}
        m = {("NEUTRAL_MACRO", "P_PROG"): {"gap": True, "reason": "x"}}
        rep = H.coverage_findings([NEUTRAL_LEF], rails, declared_map=m)
        assert rep["undeclared"] == []
        assert any(g["pin"] == "P_PROG" for g in rep["declared_gaps"])

    def test_declared_rail_clears_the_finding(self):
        rails = {"P_CORE", "G_CORE", "P_IO"}
        m = {("NEUTRAL_MACRO", "P_PROG"): {"rail": "P_IO"}}
        rep = H.coverage_findings([NEUTRAL_LEF], rails, declared_map=m)
        assert rep["undeclared"] == []

    def test_dangling_map_rail_is_flagged_not_covered(self):
        rails = {"P_CORE", "G_CORE"}
        m = {("NEUTRAL_MACRO", "P_PROG"): {"rail": "PHANTOM"}}
        rep = H.coverage_findings([NEUTRAL_LEF], rails, declared_map=m)
        assert [f["pin"] for f in rep["rail_undeclared"]] == ["P_PROG"]
        assert rep["undeclared"] == []

    def test_no_macro_pins_is_vacuous(self):
        rep = H.coverage_findings(["VERSION 5.8 ;\n"], set(), declared_map={})
        assert rep["undeclared"] == [] and rep["covered_count"] == 0
        assert rep["total_pins"] == 0
