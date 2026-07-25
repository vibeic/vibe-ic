"""Tests for ip_integration_check — the Phase-1/pre-floorplan hard-macro IP
integration gate.

Focus of THIS suite: the macro-supply-pin power-intent COVERAGE check added so
that every hard-macro POWER/GROUND pin (from the macro's own LEF) is ACCOUNTED
for in L21_POWER_INTENT — bound to a declared rail, name-matches a declared rail,
or is an acknowledged integration gap. An unaccounted pin becomes a NAMED review
finding (IP_MACRO_SUPPLY_UNDECLARED) so the requirement flows into L21 instead of
surfacing five steps later as a mid-route abort.

NEGATIVE CONTROL (bidirectional): with the defect present (a supply pin no rail
matches and L21 does not declare) the named finding FIRES; once the design
declares that pin (rail binding OR integration gap) the finding DISAPPEARS. The
review finding is non-blocking (rc stays 0) so it never regresses a design whose
supplies are fine — it only surfaces the gap.

All fixtures are synthetic + neutral (no real design / PDK / pin-name literal).
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import ip_integration_check as IC  # noqa: E402


# A neutral hard macro: two supply pins whose names match the design's rails
# (P_CORE / G_CORE) and one dedicated programming supply the design carries no
# rail for (P_PROG) — the neutral analogue of the real routing-crash defect.
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
END NEUTRAL_MACRO
END LIBRARY
"""


def _mk_project(tmp_path: Path, l21_fields: dict) -> Path:
    proj = tmp_path / "proj"
    macro = proj / "input" / "pdk_local" / "neutral"
    macro.mkdir(parents=True)
    (macro / "neutral.lef").write_text(NEUTRAL_LEF)
    # full handoff set so IP_FILESET_INCOMPLETE (ERROR) does not fire and we
    # isolate the supply-coverage review rule.
    (macro / "neutral.gds").write_text("# gds\n")
    (macro / "neutral_tt.lib").write_text("library(neutral){ }\n")
    (macro / "neutral.v").write_text("module NEUTRAL_MACRO(); endmodule\n")
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L21_POWER_INTENT.json").write_text(json.dumps(
        {"doc_id": "L21", "fields": l21_fields}))
    return proj


# Rails the design declares as power domains — P_CORE/G_CORE match the macro's
# core supplies by name; P_PROG matches nothing.
_RAILS_DECL = {"power_domains": [
    {"name": "PD_CORE", "supply": "P_CORE"},
    {"name": "PD_GND", "supply": "G_CORE"}]}


def _rules(rep):
    return [f["rule"] for f in rep.get("findings", [])]


class TestSupplyCoverageNegativeControl:
    def test_undeclared_pin_fires_named_finding(self, tmp_path):
        proj = _mk_project(tmp_path, _RAILS_DECL)
        rep = IC.audit(proj)
        und = [f for f in rep["findings"]
               if f["rule"] == "IP_MACRO_SUPPLY_UNDECLARED"]
        assert len(und) == 1
        # the finding NAMES the macro + pin (chip-AGNOSTIC, from the LEF).
        assert "NEUTRAL_MACRO" in und[0]["message"]
        assert "P_PROG" in und[0]["message"]
        # non-blocking: it is a review, not a hard fail.
        assert und[0]["severity"] == "WARNING"
        assert rep["rc"] == 0

    def test_declaring_a_gap_clears_the_finding(self, tmp_path):
        fields = dict(_RAILS_DECL)
        fields["hard_macro_supplies"] = [
            {"master": "NEUTRAL_MACRO", "pin": "P_PROG",
             "integration_gap": True, "reason": "board-supplied HV rail"}]
        proj = _mk_project(tmp_path, fields)
        rep = IC.audit(proj)
        assert "IP_MACRO_SUPPLY_UNDECLARED" not in _rules(rep)

    def test_declaring_a_rail_binding_clears_the_finding(self, tmp_path):
        fields = {"power_domains": _RAILS_DECL["power_domains"] + [
            {"name": "PD_IO", "supply": "P_IO"}],
            "hard_macro_supplies": [
                {"master": "NEUTRAL_MACRO", "pin": "P_PROG", "rail": "P_IO"}]}
        proj = _mk_project(tmp_path, fields)
        rep = IC.audit(proj)
        assert "IP_MACRO_SUPPLY_UNDECLARED" not in _rules(rep)

    def test_phantom_rail_binding_is_flagged(self, tmp_path):
        fields = dict(_RAILS_DECL)
        fields["hard_macro_supplies"] = [
            {"master": "NEUTRAL_MACRO", "pin": "P_PROG", "rail": "PHANTOM"}]
        proj = _mk_project(tmp_path, fields)
        rep = IC.audit(proj)
        rules = _rules(rep)
        # a mapping to a rail the design does not declare is surfaced under a
        # MORE-SPECIFIC rule (anti-cheat: declaring a phantom rail does not
        # silence the gap, it just re-surfaces it as a broken mapping — the pin
        # is still not covered).
        assert "IP_MACRO_SUPPLY_RAIL_UNDECLARED" in rules
        assert "IP_MACRO_SUPPLY_UNDECLARED" not in rules
        assert rep["rc"] == 0

    def test_all_pins_name_match_no_finding(self, tmp_path):
        # A design that declares all three as rails (incl. P_PROG) is fully
        # covered by name-match -> no supply-coverage finding at all.
        fields = {"power_domains": [
            {"name": "a", "supply": "P_CORE"},
            {"name": "b", "supply": "G_CORE"},
            {"name": "c", "supply": "P_PROG"}]}
        proj = _mk_project(tmp_path, fields)
        rep = IC.audit(proj)
        assert "IP_MACRO_SUPPLY_UNDECLARED" not in _rules(rep)


class TestNoMacrosStillSkips:
    def test_empty_project_skips(self, tmp_path):
        proj = tmp_path / "empty"
        (proj / "input").mkdir(parents=True)
        rep = IC.audit(proj)
        assert rep["verdict"] == "SKIP" and rep["rc"] == 2
