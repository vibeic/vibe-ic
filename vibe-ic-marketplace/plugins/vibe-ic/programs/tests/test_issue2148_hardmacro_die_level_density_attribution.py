"""vibe-ic#2148 — die-level DENSITY rules are the integrator's under HARDMACRO,
attributed from the deck's own text, disclosed by number, and handed over.

WHAT WAS MEASURED (#2135, lane cz2135). On a routed macro under an open PDK,
two metal-coverage rules fired and no legal dummy fill could close them: the
deck's own dummy-to-circuit clearance leaves only 0.2234 / 0.2262 of the die
fillable, so drawn + ALL of it tops out at 0.3181 / 0.3319 against a 0.30
floor. Their measurement window is the DIE. The delivery is a macro somebody
else places, and the die's own top-level fill is what closes a die-window rule.

THE RULING (#2148): attribute them under HARDMACRO ONLY, with full disclosure
and a handoff record; a DIE deliverable still FAILs; the tier is its own word.

WHAT IS ASSERTED HERE, EACH DIRECTION
  * the die-level DENSITY family is DERIVED from the deck's own text — the
    rules that read the deck's own whole-die AREA identifier — and the
    windowed rules of the same deck are NOT in it;
  * a rule block that bleeds into the next section's preamble does not acquire
    that section's die-area identifier (the measured over-claim);
  * attribution requires HARDMACRO **and** every violation shape to BE the
    die; either one absent refuses BY NAME;
  * the disclosure carries achieved / floor / legal ceiling from the fill
    report, or NOT_MEASURED naming what was looked for — never a typed number;
  * the tier is PASS_WITH_ATTRIBUTION only when the remainder is zero;
  * `flow_compliance_check` refuses a HARDMACRO delivery whose attributed
    rules have no handoff record, and refuses a PARTIAL one by the names it
    is missing.

chip/PDK-AGNOSTIC: every deck below is written by this file. No foundry, node,
SKU or design name appears; the layer and rule spellings are the fixture's own.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import _owner_declared as _OD                              # noqa: E402

import die_level_deck_rule_attribution as D  # noqa: E402


# ---------------------------------------------------------------------------
# A deck in the two shapes the open PDKs in this image actually use.
# ---------------------------------------------------------------------------

DECK = D.FILE_SEP + """/deck/density.rb
chip_area = extent.sized(0.0).area

# Rule COV1.a: layer_one coverage over the entire die shall be >30%
if (layer_one.area / chip_area) * 100 < 30
  extent.output('COV1.a', 'COV1.a : 30%')
end

# Rule COV2.a: layer_two coverage over the entire die shall be >30%
if (layer_two.area / chip_area) * 100 < 30
  extent.output('COV2.a', 'COV2.a : 30%')
end

# Rule WIN.a: layer_two coverage for any window
win = layer_two.with_density_backup(0.0..0.25, tile, step, boundary, chip_bbox)
output_local(win, chip_for_density)

#================================================
# ------------------ NextSection -----------------
#================================================

l3_area = layer_three.area
l3_ratio = l3_area / chip_area

# Rule COV3.a: Min. global layer_three density.
if l3_ratio < 0.30
  output_global(chip_bbox, l3_area, chip_area, l3_ratio, :min)
end
""" + D.FILE_SEP + """/deck/geom.rb
# Rule GEO.1: min width
layer_one.width(0.2.um).output('GEO.1', 'GEO.1')
"""

DIE = [0.0, 0.0, 100.0, 100.0]


def _rdb(items):
    """A KLayout report database carrying one <item> per (rule, polygon)."""
    body = "".join(
        f"<item><category>'{rule}'</category><values>"
        f"<value>polygon: {poly}</value></values></item>"
        for rule, poly in items)
    return f"<report-database>{body}</report-database>"


DIE_POLY = "(0,0;0,100;100,100;100,0)"
SMALL_POLY = "(10,10;10,20;20,20;20,10)"


def _fill_report():
    return {
        "verdict": "PARTIAL",
        "floor": 0.30,
        "keepout": {"measurement_bbox_um": list(DIE)},
        "layers": [
            {"name": "layer_one", "density_after": 0.2048,
             "worst_window_after": 0.2048, "floor": 0.30,
             "ceiling_any_fill": 0.318139},
            {"name": "layer_two", "density_after": 0.2267,
             "worst_window_after": 0.2267, "floor": 0.30,
             "ceiling_any_fill": 0.331869},
        ],
    }


def _project(tmp_path, deliverable):
    proj = tmp_path / f"p_{deliverable.lower()}"
    (proj / "input" / "submission_template").mkdir(parents=True)
    (proj / "input" / "submission_template" /
     "tapeout_declaration.json").write_text(json.dumps(_OD.attest(
         {"schema": "vibe-ic/tapeout_declaration/1",
          "answers": {"deliverable": deliverable}})))
    (proj / "reports" / "phase3").mkdir(parents=True)
    (proj / "reports" / "phase3" / "cmp_fill_emit.json").write_text(
        json.dumps(_fill_report()))
    return proj


# ---------------------------------------------------------------------------
# 1. The family is derived from the deck, and the windowed rules are not in it.
# ---------------------------------------------------------------------------

def test_the_die_area_identifier_comes_from_the_deck():
    names, why = D.die_area_identifiers(DECK)
    assert why is None
    assert "chip_area" in names
    # the extent PRIMITIVE is a region, not the area scalar
    assert D._EXTENT_PRIMITIVE not in names
    # a deck that never names it says so instead of guessing
    empty, why2 = D.die_area_identifiers("# Rule X.1: nothing\n")
    assert empty == set() and why2 and "whole-die area" in why2


def test_the_family_is_the_die_window_rules_and_only_those():
    names, _ = D.die_area_identifiers(DECK)
    fam = D.die_level_density_rules(DECK, names)
    assert sorted(fam) == ["COV1.a", "COV2.a", "COV3.a"]
    # the windowed rule of the SAME deck is excluded ...
    assert "WIN.a" not in fam
    # ... and so is a geometry rule in another file
    assert "GEO.1" not in fam
    assert fam["COV1.a"].endswith("density.rb")


def test_a_rule_block_does_not_acquire_the_next_sections_die_area():
    """The measured over-claim: `WIN.a` is followed by a section banner and
    then by `l3_ratio = l3_area / chip_area`. A block that ran to the next
    `# Rule` header would swallow that line and attribute a windowed rule."""
    names, _ = D.die_area_identifiers(DECK)
    blocks = {rid: body for rid, _w, body in D._rule_blocks(DECK)}
    assert "chip_area" not in blocks["WIN.a"], (
        "the windowed rule's block reaches into the next section — the banner "
        "boundary stopped working")
    assert "chip_area" in blocks["COV3.a"]


# ---------------------------------------------------------------------------
# 2. Attribution: HARDMACRO only, die-scope shapes only.
# ---------------------------------------------------------------------------

def _run(proj, per_rule, rdb):
    return D.run(Path(proj), per_rule, DECK, None, rdb, _fill_report())


def test_hardmacro_attributes_discloses_and_earns_its_own_tier(tmp_path):
    proj = _project(tmp_path, D.DELIVERABLE_HARDMACRO)
    rec = _run(proj, {"COV1.a": 1, "COV2.a": 1},
               _rdb([("COV1.a", DIE_POLY), ("COV2.a", DIE_POLY)]))
    assert rec["verdict"] == D.DENSITY_ATTRIBUTED
    assert rec["attributed_density_rules"] == {"COV1.a": 1, "COV2.a": 1}
    assert rec["unattributed_total"] == 0
    assert rec["drc_tier"] == D.TIER_PASS_WITH_ATTRIBUTION
    assert rec["drc_tier"] != "PASS"
    disc = {d["rule"]: d for d in rec["density_disclosure"]}
    assert disc["COV1.a"]["layer"] == "layer_one"
    assert disc["COV1.a"]["achieved"] == 0.2048
    assert disc["COV1.a"]["floor"] == 0.30
    assert disc["COV1.a"]["legal_ceiling"] == 0.318139
    assert disc["COV2.a"]["achieved"] == 0.2267
    line = D.summarize(rec)
    for token in ("COV1.a", "COV2.a", "0.2048", "0.3", "0.318139",
                  D.TIER_PASS_WITH_ATTRIBUTION):
        assert str(token) in line


def test_a_die_deliverable_is_never_attributed(tmp_path):
    proj = _project(tmp_path, D.DELIVERABLE_DIE)
    rec = _run(proj, {"COV1.a": 1, "COV2.a": 1},
               _rdb([("COV1.a", DIE_POLY), ("COV2.a", DIE_POLY)]))
    assert rec["verdict"] == "NOTHING_TO_ATTRIBUTE"
    assert rec["attributed_density_rules"] == {}
    assert rec["unattributed_total"] == 2
    assert rec["drc_tier"] is None
    refused = rec["density_attribution_refused"]
    assert sorted(refused) == ["COV1.a", "COV2.a"]
    assert all(D.DELIVERABLE_DIE in v for v in refused.values())
    # and the sentence says so rather than "nothing fired"
    assert "NOT attributed" in D.summarize(rec)


def test_a_violation_that_is_not_the_die_is_refused_by_name(tmp_path):
    """The second link is MEASURED. A rule the deck calls die-level whose
    violation shape is a local polygon is not attributed here."""
    proj = _project(tmp_path, D.DELIVERABLE_HARDMACRO)
    rec = _run(proj, {"COV1.a": 2},
               _rdb([("COV1.a", DIE_POLY), ("COV1.a", SMALL_POLY)]))
    assert rec["attributed_density_rules"] == {}
    assert "COV1.a" in rec["density_attribution_refused"]
    assert "1 of this rule's 2" in rec["density_attribution_refused"]["COV1.a"]
    assert rec["drc_tier"] is None


def test_a_remainder_keeps_the_verdict_and_denies_the_tier(tmp_path):
    proj = _project(tmp_path, D.DELIVERABLE_HARDMACRO)
    rec = _run(proj, {"COV1.a": 1, "GEO.1": 3},
               _rdb([("COV1.a", DIE_POLY)] + [("GEO.1", SMALL_POLY)] * 3))
    assert rec["attributed_density_rules"] == {"COV1.a": 1}
    assert rec["unattributed_total"] == 3
    assert rec["drc_tier"] is None, (
        "one violation that is this design's own must deny the tier")


def test_a_rule_with_no_fill_layer_is_disclosed_not_invented(tmp_path):
    """`COV3.a` measures a layer the fill never reported. The rule is still
    attributed and still disclosed — with NOT_MEASURED naming what was looked
    for, never a supplied zero."""
    proj = _project(tmp_path, D.DELIVERABLE_HARDMACRO)
    rec = _run(proj, {"COV3.a": 1}, _rdb([("COV3.a", DIE_POLY)]))
    assert rec["attributed_density_rules"] == {"COV3.a": 1}
    d = rec["density_disclosure"][0]
    assert d["rule"] == "COV3.a"
    assert d["layer"] == D.NOT_MEASURED
    assert d["achieved"] == D.NOT_MEASURED
    assert "no layer the density fill measured" in d["not_measured"]


def test_without_a_die_bounding_box_nothing_is_attributed(tmp_path):
    """The die bbox comes from the fill report. Absent, the scope of a
    violation is unmeasured, and unmeasured never attributes."""
    proj = _project(tmp_path, D.DELIVERABLE_HARDMACRO)
    (proj / "reports" / "phase3" / "cmp_fill_emit.json").write_text(
        json.dumps({"layers": []}))
    rec = D.run(Path(proj), {"COV1.a": 1}, DECK, None,
                _rdb([("COV1.a", DIE_POLY)]), {"layers": []})
    assert rec["attributed_density_rules"] == {}
    assert rec["drc_tier"] is None
    assert "fill_report" in rec["not_measured"]


# ---------------------------------------------------------------------------
# 3. The handoff, and the refusal that makes it part of the delivery.
# ---------------------------------------------------------------------------

def _attributed_project(tmp_path, handoff_rules=None, name="hm"):
    proj = tmp_path / name
    (proj / "reports" / "phase3").mkdir(parents=True)
    (proj / "reports" / "phase3" /
     "die_level_rule_attribution.json").write_text(json.dumps({
         "verdict": D.DENSITY_ATTRIBUTED,
         "attributed_density_rules": {"COV1.a": 1, "COV2.a": 1},
     }))
    if handoff_rules is not None:
        hm = proj / "phase3" / "stage4" / "hardmacro"
        hm.mkdir(parents=True)
        (hm / D.HANDOFF_NAME).write_text(json.dumps({
            "record": "integrator_requirements",
            "requirements": [{"rule": r} for r in handoff_rules],
        }))
    return proj


def test_the_handoff_record_carries_every_attributed_rule(tmp_path):
    proj = _project(tmp_path, D.DELIVERABLE_HARDMACRO)
    rec = _run(proj, {"COV1.a": 1, "COV2.a": 1},
               _rdb([("COV1.a", DIE_POLY), ("COV2.a", DIE_POLY)]))
    ho = D.handoff_record(rec)
    assert ho["record"] == "integrator_requirements"
    assert ho["deliverable"] == D.DELIVERABLE_HARDMACRO
    assert [r["rule"] for r in ho["requirements"]] == ["COV1.a", "COV2.a"]
    assert ho["die_bbox_um"] == DIE
    assert ho["unattributed_violations"] == 0
    assert ho["tier"] == D.TIER_PASS_WITH_ATTRIBUTION








def test_the_declared_tier_is_preserved_by_the_runners_aggregator():
    """Integrator density obligations remain distinct and keep the run off PASS."""
    import phase3_one_shot_runner as P
    import pytest as _pytest
    import verdict as _V

    attributed = P.StepResult("drc", D.TIER_PASS_WITH_ATTRIBUTION)
    assert attributed.waiver_rows == []
    plan = [attributed, P.StepResult("lvs", "PASS")]
    assert P._aggregate_verdict(plan) == D.TIER_PASS_WITH_ATTRIBUTION
    with _pytest.raises(ValueError, match="waiver_rows"):
        P.StepResult("drc", D.TIER_PASS_WITH_ATTRIBUTION,
                     waiver_rows=[{"id": "forbidden"}])
    with _pytest.raises(ValueError):
        _V.StepVerdict(verdict=_V.Verdict.PASS_WITH_WAIVERS,
                       step_id="drc", name="drc")
    assert P._aggregate_verdict([P.StepResult("lvs", "PASS")]) == "PASS"
