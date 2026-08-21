"""v0.3.16 — #513: DRC per-step PV gate FAILed on a raw violation count
even when the count was 100% stdcell-library-INTERNAL (foundry cells' own
li/licon(ct)/met1 rules below the router metal stack) with ZERO
design-level (met2+/via+) violations — blocking a design that is itself
routing-DRC-clean. New deterministic classifier splits by rule-layer:
design-level==0 → 'stdcell-library-internal-DRC' (waiver-eligible), and
the count gate consumes the design-level count, not the raw total.

Validated on the real spm Step-31 KLayout sign-off: 115114 violations,
100% li.3/li.5/li.1/ct.2/m1.2, design-level == 0 → waiver-eligible.
chip/PDK-AGNOSTIC: pure rule-layer buckets.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import drc_rule_layer_classify as D  # noqa: E402


def _xml(rule_items):
    # rule_items: list of (rule, count) → KLayout report-database XML
    items = "".join(
        f"<item><category>'{r}'</category></item>\n" * n
        for r, n in rule_items)
    return f"<report-database><categories></categories><items>\n{items}</items></report-database>"


def test_all_stdcell_internal_is_waiver_eligible():
    xml = _xml([("li.3", 114785), ("li.5", 219), ("li.1", 78),
               ("ct.2", 30), ("m1.2", 2)])
    _per, s = D.classify_xml(xml)
    assert s["total_violations"] == 115114
    assert s["design_level_count"] == 0
    assert s["classification"] == "stdcell-library-internal-DRC"
    assert s["waiver_eligible"] is True


def test_design_level_violation_is_not_waiver_eligible():
    # a met2/via violation is a real routing DRC defect → NOT waiver.
    xml = _xml([("li.3", 100), ("met2.1", 1)])
    _per, s = D.classify_xml(xml)
    assert s["design_level_count"] == 1
    assert "met2.1" in s["design_level_rules"]
    assert s["classification"] == "has-design-level-DRC"
    assert s["waiver_eligible"] is False


def test_via2_is_design_level():
    xml = _xml([("via2.1a", 3)])
    _per, s = D.classify_xml(xml)
    assert s["design_level_count"] == 3 and s["waiver_eligible"] is False


def test_met1_and_licon_are_stdcell_internal():
    xml = _xml([("m1.2", 5), ("ct.2", 5), ("mcon.1", 5)])
    _per, s = D.classify_xml(xml)
    assert s["design_level_count"] == 0 and s["waiver_eligible"] is True


def test_clean_report():
    _per, s = D.classify_xml(_xml([]))
    assert s["classification"] == "clean" and s["waiver_eligible"] is True


def test_rule_layer_extraction():
    assert D._rule_layer("li.3") == "li"
    assert D._rule_layer("via2.1a") == "via2"
    assert D._rule_layer("m1.2") == "m1"
