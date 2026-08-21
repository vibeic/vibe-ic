"""Regression: the fill engine's keep-out comes from the DECK'S OWN RULE.

`metal_fill.py` has carried two keep-out forms since it got one, and its own
docstring says which is which:

    keepout_layers   "... the exact form when the PDK ships a marker for the
                      band ... because it follows the ring the generator
                      actually drew instead of assuming where it went."
    keepout_edge_um  "... the `fill_all.rb` form, for a PDK that ships no
                      marker."

Only the fallback was ever populated: nothing in the tree wrote
`keepout_layers`. The band was read out of the PDK's fill script
(`space_to_scribe_line`) and claimed whenever the DESIGN declared a shuttle
slot. That is correct only while three separate things coincide — the marked
structure is flush with the layout's own bbox, the fill script's margin equals
the marker's width plus the deck's clearance for it, and the structure is
actually PRESENT on the layout. On the PDK where it was measured all three hold
by coincidence; none of them is a contract, and the third comes apart in
practice, because whether a seal ring is on the layout is a fact about the
ARTEFACT while "declares a slot" is a fact about the DESIGN.

`parse_metal_keepout_layers` reads the rule instead. Every fixture here is
SYNTHETIC with arbitrary layer numbers and invented layer names: the point is
that the derivation is a pure function of the deck TEXT, with no PDK, vendor or
chip literal in the logic.

THE NEGATIVE ARM IS THE POINT. A deck switches a rule off by commenting it out,
and a parser that cannot tell a live rule from a dead one would "derive" a
keep-out the PDK does not enforce — which, for a base layer, subtracts most of
the die from the fillable area. So every positive case below is paired with the
same text commented out, which must yield nothing.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import metal_fill_config_gen as G  # noqa: E402

# Two routing metals, one marker layer, one base layer. Arbitrary numbers.
_ROUTING = {"metal1": (61, 0), "metal2": (62, 0)}
_LAYER_TABLE = """\
extract_single_layer_from_design.call(:metal1_drawn, 61, 0)
extract_single_layer_from_design.call(:metal1_dummy, 61, 7)
extract_single_layer_from_design.call(:metal2_drawn, 62, 0)
extract_single_layer_from_design.call(:metal2_dummy, 62, 7)
extract_single_layer_from_design.call(:ringband_mk, 191, 5)
extract_single_layer_from_design.call(:otherstruct_mk, 193, 2)
extract_single_layer_from_design.call(:baselayer, 30, 0)
"""


def _ko(rules, prefix="Metal"):
    return G.parse_metal_keepout_layers(_LAYER_TABLE + rules, prefix, _ROUTING)


# ---------------------------------------------------------------- the rule --

def test_a_live_separation_rule_against_metal_becomes_a_keepout():
    ko = _ko("  gr = metal.separation(ringband_mk, 10.um)\n")
    assert ko == [[191, 5, 10.0]], ko


def test_the_same_rule_commented_out_yields_nothing():
    """THE NEGATIVE ARM. Without this the positive test above proves only that
    the string appears in the file, not that the rule is in force."""
    ko = _ko("  #  gr = metal.separation(ringband_mk, 10.um)\n")
    assert ko == [], ko


def test_a_trailing_comment_does_not_swallow_the_live_rule_before_it():
    ko = _ko("  gr = metal.separation(ringband_mk, 10.um)  # GR.2\n")
    assert ko == [[191, 5, 10.0]], ko


def test_a_hash_inside_a_quoted_label_is_not_a_comment():
    """A live rule's own output label legitimately contains `#`. Cutting there
    would truncate the line and lose whatever followed on it."""
    text = ('  dm = metal_dummy.separation(otherstruct_mk, 6.um, euclidian)\n'
            '  dm.output("DM#{idx}.8", "clearance")\n'
            '  gr = metal.separation(ringband_mk, 10.um)\n')
    assert _ko(text) == [[193, 2, 6.0], [191, 5, 10.0]], _ko(text)


# ------------------------------------------------------- what is NOT a keep-out --

def test_metal_to_metal_separation_is_not_a_keepout_region():
    """Dummy-to-circuit-metal spacing is the per-layer `space_to_metal` this
    same config already carries. Re-expressing it as a keep-out REGION would
    subtract every wire on the die from the fillable area."""
    assert _ko("  dm3 = metal_dummy.separation(metal1_drawn, 2.um, euclidian)\n") == []
    assert _ko("  dm3 = metal_dummy.separation(metal2_dummy, 2.um, euclidian)\n") == []


def test_a_separation_rule_whose_left_side_is_not_metal_is_not_adopted():
    """A poly or diffusion clearance is not the metal fill's to apply."""
    assert _ko("  gr = poly2.separation(ringband_mk, 10.um)\n") == []
    assert _ko("  gr = comp.separation(ringband_mk, 10.um)\n") == []


def test_a_layer_the_deck_names_no_gds_number_for_is_refused_not_guessed():
    assert _ko("  gr = metal.separation(undeclared_mk, 10.um)\n") == []


def test_a_zero_clearance_is_not_a_keepout():
    assert _ko("  gr = metal.separation(ringband_mk, 0.um)\n") == []


# ------------------------------------------------------------ several rules --

def test_the_largest_clearance_wins_when_one_layer_is_named_twice():
    ko = _ko("  a = metal.separation(ringband_mk, 6.um)\n"
             "  b = metal.separation(ringband_mk, 10.um)\n")
    assert ko == [[191, 5, 10.0]], ko


def test_every_named_structure_is_kept_out_of_not_only_the_first():
    ko = _ko("  a = metal_dummy.separation(otherstruct_mk, 6.um, euclidian)\n"
             "  b = metal.separation(ringband_mk, 10.um)\n")
    assert sorted(ko) == [[191, 5, 10.0], [193, 2, 6.0]], ko


# ------------------------------------------------- what the config carries --

_LAYERMAP = """\
Metal1  NET,SPNET,PIN,VIA 61 0
Metal2  NET,SPNET,PIN,VIA 62 0
"""
_TECHLEF = """\
MANUFACTURINGGRID 0.010 ;
LAYER Metal1
    TYPE ROUTING ;
    WIDTH 0.20 ;
    SPACING 0.20 ;
END Metal1
LAYER Metal2
    TYPE ROUTING ;
    WIDTH 0.24 ;
    SPACING 0.24 ;
END Metal2
"""
_DECK_TAIL = """
if (metal1.area / chip_area) * 100 < 33
  extent.output('M1.4', 'coverage')
end
"""


def _cfg(rules):
    return G.build_metal_fill_config(
        _LAYERMAP, _TECHLEF, _LAYER_TABLE + rules + _DECK_TAIL,
        metal_prefix="Metal")


def test_the_config_carries_the_derived_keepout_and_names_it():
    cfg = _cfg("  gr = metal.separation(ringband_mk, 10.um)\n")
    assert cfg["keepout_layers"] == [[191, 5, 10.0]]
    assert cfg["_derivation"]["keepout_layers_derived"] == 1
    # Named, so a reader can check the derivation against the RULE rather than
    # against a layer number.
    assert cfg["_derivation"]["keepout_layer_names"] == ["ringband_mk"]


def test_the_key_is_emitted_even_when_the_deck_states_no_rule():
    """`[]` and an absent key read the same to a consumer, and only one of them
    means "asked, and this deck states none"."""
    cfg = _cfg("")
    assert "keepout_layers" in cfg
    assert cfg["keepout_layers"] == []
    assert cfg["_derivation"]["keepout_layers_derived"] == 0
