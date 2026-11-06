"""vibe-ic#2112 — the DRC summary must ATTRIBUTE die-level deck rules.

MEASURED, lane cz2112 on 8HD-6, pinned EDA image 0.3.48, gf180mcuD (an open
PDK), the `subservient` layout of the rbsub4 front-door run. The SAME routed
DEF, streamed and grid-snapped by the flow's own scripts, then run through the
PDK's own sign-off deck twice:

    a die seal ring stamped in   1,359,528 violations   GR.4 1,299,340
    no ring                              5 violations   GR.*         0

So on that delivery the sign-off DRC total was not a statement about the
layout: 97.5% of it was three rules of ONE deck file, and those three rules are
gated on the die-level marker layer the ring's generator drew over the die.

`die_finishing_gen._hardmacro_skip` is what stops the ring being generated.
This module is the disclosure half: whenever such a rule fires anyway on a
HARDMACRO delivery, the DRC step's summary says so instead of folding the count
into the design's number.

WHICH RULES ARE DIE-LEVEL IS READ OUT OF THE PDK'S OWN DECK, never listed here.
The two deck fragments below are verbatim from that image, and they are what
pins the two link shapes the module accepts.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import _tapeout_declaration as TD  # noqa: E402
import _owner_declared as _OD                              # noqa: E402
import die_level_deck_rule_attribution as A  # noqa: E402

# Verbatim, `libs.tech/klayout/tech/drc/generic_layers.rb` + `rule_decks/
# guard_ring.rb` in the pinned image, trimmed to the lines that matter.
_DECK = (
    A.FILE_SEP + "/deck/generic_layers.rb\n"
    "      extract_single_layer_from_design.call(:guard_ring_mk, 167, 5)\n"
    "      extract_single_layer_from_design.call(:comp, 22, 0)\n"
    + A.FILE_SEP + "/deck/rule_decks/guard_ring.rb\n"
    "  guard_ring_comp = comp.interacting(guard_ring_mk)\n"
    "\n"
    "  # Rule GR.2: Min GUARD_RING_MK space to prime die COMP: 10\n"
    "  gr2_l1 = comp.separation(guard_ring_mk, 10.um)\n"
    "  gr2_l1.output('GR.2', 'GR.2 : ...')\n"
    "\n"
    "  # Rule GR.4: Minimum metal-n width (n= 1 to 6): 12\n"
    "    gr4_l1 = metal.not_outside(guard_ring_mk).width(12.um)\n"
    "    gr4_l1.output('GR.4', 'GR.4 : ...')\n"
    "\n"
    "  # Rule GR.99: a rule of the same FILE that names no marker\n"
    "  gr99_l1 = comp.width(1.um)\n"
    + A.FILE_SEP + "/deck/rule_decks/metal.rb\n"
    "  # Rule M1.2b: min metal1 spacing\n"
    "  m12b = metal1.space(0.23.um)\n"
)

# The second spelling a deck may use to declare the same layer.
_DECK_ASSIGNMENT = (
    A.FILE_SEP + "/deck/layers.drc\n"
    "guard_ring_mk = input(167, 5)\n"
    + A.FILE_SEP + "/deck/rules.drc\n"
    "# Rule GR.4: Minimum metal-n width\n"
    "metal.not_outside(guard_ring_mk).width(12.um).output('GR.4')\n"
)


# --------------------------------------------------------------------------- #
# link 2 — the deck's own name for a layer
# --------------------------------------------------------------------------- #
def test_the_symbol_spelling_is_read():
    got, why = A.marker_identifiers(_DECK, 167, 5)
    assert got == {"guard_ring_mk"}
    assert why is None


def test_the_assignment_spelling_is_read():
    got, why = A.marker_identifiers(_DECK_ASSIGNMENT, 167, 5)
    assert got == {"guard_ring_mk"}
    assert why is None


def test_a_layer_the_deck_never_declares_is_NOT_MEASURED_not_empty():
    """THE OTHER DIRECTION, and it is the one that matters: a guessed
    identifier silently attributes the wrong rules, so an absent declaration
    must produce a reason rather than a fall-back name."""
    got, why = A.marker_identifiers(_DECK, 998, 7)
    assert got == set()
    assert why and "998/7" in why


def test_a_different_layer_of_the_same_deck_is_a_different_name():
    got, _ = A.marker_identifiers(_DECK, 22, 0)
    assert got == {"comp"}


# --------------------------------------------------------------------------- #
# link 3 — the rules gated on it
# --------------------------------------------------------------------------- #
def test_only_the_blocks_that_reference_the_marker_are_attributed():
    fam = A.rules_gated_on(_DECK, {"guard_ring_mk"})
    assert set(fam) == {"GR.2", "GR.4"}
    # GR.99 sits in the SAME FILE and names no marker. Attributing by file
    # would have taken it; attributing by BLOCK does not.
    assert "GR.99" not in fam
    assert "M1.2b" not in fam


def test_the_rule_is_attributed_to_the_deck_file_it_came_from():
    fam = A.rules_gated_on(_DECK, {"guard_ring_mk"})
    assert fam["GR.4"].endswith("guard_ring.rb")


def test_a_block_does_not_bleed_past_its_own_file():
    """`# Rule GR.99` is the LAST block of its file and names no marker; the
    next file's first line must not be read as part of it."""
    fam = A.rules_gated_on(
        _DECK + A.FILE_SEP + "/deck/x.rb\nguard_ring_mk\n", {"guard_ring_mk"})
    assert "GR.99" not in fam


def test_no_identifier_attributes_nothing():
    assert A.rules_gated_on(_DECK, set()) == {}
    assert A.rules_gated_on(_DECK, {""}) == {}


# --------------------------------------------------------------------------- #
# link 1 — which layers a ring INTRODUCED
# --------------------------------------------------------------------------- #
_RING = {"seal_ring": {"state": "PASS", "ring_check": {"added_geometry": [
    {"layer": "33/0", "polygons": 14308, "new_layer": False},
    {"layer": "37/0", "polygons": 1, "new_layer": True},
    {"layer": "167/5", "polygons": 1, "new_layer": True},
]}}}


def test_only_the_layers_the_ring_introduced_are_markers():
    got, why = A.marker_layers_from_die_finishing(_RING)
    assert got == [(37, 0), (167, 5)]
    assert why is None


def test_a_report_with_no_ring_check_is_NOT_MEASURED():
    got, why = A.marker_layers_from_die_finishing(
        {"seal_ring": {"state": "DISCLOSED_SKIP"}})
    assert got == []
    assert why and "added_geometry" in why


# --------------------------------------------------------------------------- #
# the split, and the sentence
# --------------------------------------------------------------------------- #
_PER_RULE = {"GR.4": 1299340, "GR.2": 24652, "GR.6": 1022, "PL.6": 7205,
             "CO.10": 4250}
_FAM = {"GR.4": "guard_ring.rb", "GR.2": "guard_ring.rb",
        "GR.6": "guard_ring.rb"}


def test_a_hardmacro_with_die_level_rules_is_attributed():
    rec = A.attribute(_PER_RULE, _FAM, "HARDMACRO", "PASS", [(167, 5)], {})
    assert rec["verdict"] == "DIE_LEVEL_RULES_ON_A_HARDMACRO"
    assert rec["die_level_rule_violations"] == 1325014
    assert rec["other_violations"] == 11455
    assert rec["total"] == 1336469
    line = A.summarize(rec)
    assert "DIE-LEVEL DECK RULES ON A HARDMACRO DELIVERY" in line
    assert "167/5" in line


def test_a_die_with_the_same_rules_is_NOT_attributed():
    """THE OTHER DIRECTION. A die owns its ring and its die-level markers; the
    same counts on a die are the die's own DRC and must not be re-labelled."""
    rec = A.attribute(_PER_RULE, _FAM, "DIE", "PASS", [(167, 5)], {})
    assert rec["verdict"] == "NOTHING_TO_ATTRIBUTE"
    # The split is still REPORTED — only the verdict differs.
    assert rec["die_level_rule_violations"] == 1325014
    # And the SENTENCE says which of the two "nothing to attribute" states
    # this is: die-level rules fired, on a delivery entitled to them.
    line = A.summarize(rec)
    assert "no die-level deck rule fired" not in line
    assert "a die owns its seal ring" in line


def test_a_hardmacro_with_no_die_level_violation_attributes_nothing():
    rec = A.attribute({"PL.6": 7205}, _FAM, "HARDMACRO", "DISCLOSED_SKIP",
                      [], {})
    assert rec["verdict"] == "NOTHING_TO_ATTRIBUTE"
    assert rec["die_level_rule_violations"] == 0
    assert "no die-level deck rule fired" in A.summarize(rec)


def test_no_verdict_is_taken_and_nothing_is_waived():
    rec = A.attribute(_PER_RULE, _FAM, "HARDMACRO", "PASS", [(167, 5)], {})
    assert "PASS" not in {rec["verdict"]}
    assert "waiver" not in json.dumps(rec).lower()
    assert "exempt" not in json.dumps(rec).lower()


def test_a_not_measured_link_is_said_even_when_nothing_is_attributed():
    """"no die-level rule fired" and "I could not tell which rules are
    die-level" must never arrive wearing the same sentence."""
    rec = A.attribute({"PL.6": 7205}, {}, "HARDMACRO", "PASS", [(167, 5)],
                      {"die_level_rules": "no deck sources were supplied"})
    line = A.summarize(rec)
    assert "NOT_MEASURED" in line
    assert "no deck sources were supplied" in line


# --------------------------------------------------------------------------- #
# end to end
# --------------------------------------------------------------------------- #
def _project(tmp_path, deliverable, die_finishing):
    d = tmp_path / TD.DECLARATION_REL
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text(json.dumps(_OD.attest(
        {"schema": TD.SCHEMA, "answers": {"deliverable": deliverable}})))
    r = tmp_path / "reports" / "phase3" / "die_finishing.json"
    r.parent.mkdir(parents=True, exist_ok=True)
    r.write_text(json.dumps(die_finishing))
    return tmp_path


def test_end_to_end_on_a_hardmacro_that_got_a_ring(tmp_path):
    proj = _project(tmp_path, TD.DELIVERABLE_HARDMACRO, _RING)
    rec = A.run(proj, _PER_RULE, _DECK)
    assert rec["verdict"] == "DIE_LEVEL_RULES_ON_A_HARDMACRO"
    assert rec["die_level_marker_layers"] == ["37/0", "167/5"]
    assert set(rec["die_level_rules"]) == {"GR.4", "GR.2"}
    # EVERY LINK OF THE MARKER FAMILY WAS MADE — which is what this line has
    # always been about. It used to say `== {}`, and vibe-ic#2148 added a
    # SECOND family (die-level DENSITY) with links of its own; this fixture
    # supplies none of that family's inputs, so those links are honestly
    # NOT_MEASURED and the empty-dict form stopped meaning what it said.
    # Naming the marker family's keys keeps the assertion falsifiable in the
    # direction it was written for, and the density family's keys are asserted
    # PRESENT below so the count of facts pinned here goes up, not down.
    for _k in ("deliverable", "die_level_marker_layers", "die_level_rules"):
        assert _k not in rec["not_measured"], rec["not_measured"].get(_k)
    for _k in ("die_level_density_rules", "fill_report", "violation_shapes"):
        assert _k in rec["not_measured"] and rec["not_measured"][_k]


def test_end_to_end_on_the_same_tree_declared_a_die(tmp_path):
    proj = _project(tmp_path, TD.DELIVERABLE_DIE, _RING)
    rec = A.run(proj, _PER_RULE, _DECK)
    assert rec["verdict"] == "NOTHING_TO_ATTRIBUTE"


def test_end_to_end_without_deck_sources_says_so(tmp_path):
    proj = _project(tmp_path, TD.DELIVERABLE_HARDMACRO, _RING)
    rec = A.run(proj, _PER_RULE, None)
    assert rec["die_level_rules"] == {}
    assert "die_level_rules" in rec["not_measured"]
    assert "NOT_MEASURED" in A.summarize(rec)


def test_an_absent_declaration_is_NOT_MEASURED_not_a_die(tmp_path):
    r = tmp_path / "reports" / "phase3" / "die_finishing.json"
    r.parent.mkdir(parents=True, exist_ok=True)
    r.write_text(json.dumps(_RING))
    rec = A.run(tmp_path, _PER_RULE, _DECK)
    assert rec["deliverable"] == A.NOT_MEASURED
    assert "deliverable" in rec["not_measured"]
    assert rec["verdict"] == "NOTHING_TO_ATTRIBUTE"


def test_the_cli_exit_code_says_which_way_it_went(tmp_path):
    proj = _project(tmp_path, TD.DELIVERABLE_HARDMACRO, _RING)
    pr = tmp_path / "per_rule.json"
    pr.write_text(json.dumps(_PER_RULE))
    ds = tmp_path / "deck.txt"
    ds.write_text(_DECK)
    out = tmp_path / "out.json"
    assert A.main([str(proj), "--per-rule", str(pr), "--deck-sources",
                   str(ds), "--json", str(out)]) == 1
    assert json.loads(out.read_text())["verdict"] == \
        "DIE_LEVEL_RULES_ON_A_HARDMACRO"
    proj2 = _project(tmp_path / "d", TD.DELIVERABLE_DIE, _RING)
    assert A.main([str(proj2), "--per-rule", str(pr), "--deck-sources",
                   str(ds)]) == 0


def test_the_cli_refuses_an_unreadable_per_rule(tmp_path):
    proj = _project(tmp_path, TD.DELIVERABLE_HARDMACRO, _RING)
    assert A.main([str(proj), "--per-rule", str(tmp_path / "nope.json")]) == 2


# --------------------------------------------------------------------------- #
# the collector in the runner — the link that hands this module the deck
# --------------------------------------------------------------------------- #
class _Pdk:
    def __init__(self, deck):
        self.drc_deck = deck


def _runner():
    import importlib
    return importlib.import_module("phase3_one_shot_runner")
