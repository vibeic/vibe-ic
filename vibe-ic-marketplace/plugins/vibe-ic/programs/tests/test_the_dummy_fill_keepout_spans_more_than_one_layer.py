"""A dummy-metal keep-out that could only see the layer it wrote to.

`_GDS_DUMMY_FILL_PY` built its keep-out from
`pya.Region(tc.begin_shapes_rec(li))` — shapes on **the one layer it writes**.
That is expressible only where dummy metal shares a layer with circuit metal.

MEASURED (2026-09-02/03, 8HD-4, `subservient` x `gf180mcuD`, image
`sha256:190b37be3407…`, PDK tree sha256 `8342c17b…`). This PDK maps
`metal2_dummy` to GDS `36/4` and `metal2_drawn` to `36/0`
(`generic_layers.rb`) and requires 2 um between them
(`rule_decks/dummy_metal.rb`: `metal_dummy.separation(metal_drawn, 2.um)`).
Tiles aimed at `36/0` are therefore CIRCUIT metal inside 2 um of the dummy the
streamout already placed, and the deck answered:

    keep-out              tiles   deck result
    single layer, 0.65um  35215   DM2.3=31557 DM3.3=34113   65 670
    single layer, 2.0um   11027   M2.4=1 DM2.3=14263 ...    30 518
    single layer, 3.0um    8515   M2.4=1 M3.4=1 DM ...      25 249
    MULTI-LAYER (this)      1424   M2.4=1 M3.4=1                 2

The violation count tracks the tile count, which is the proof it is the tiles
and not the design.

chip/PDK-AGNOSTIC: deck grammar only; every number asserted below is parsed out
of the fixture, never written into the program.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import pdk_dummy_fill_spec as pds  # noqa: E402
import phase3_one_shot_runner as p3  # noqa: E402

DECK = Path(__file__).resolve().parent / "fixtures" / "pdk_dummy_fill"


@pytest.fixture(scope="module")
def spec():
    s = pds.derive(DECK)
    assert s is not None, "the fixture is the real deck's own grammar"
    return s


def test_the_write_layer_is_the_pdk_dummy_layer_not_the_drawn_one(spec):
    """THE CONTROL, on a VALUE. Aiming at the drawn layer is what produced
    65 670 violations; the spec must name the dummy datatype."""
    lvl2 = spec["levels"]["2"]
    assert lvl2["write_gds"] == "36/4", (
        "dummy tiles must be written on the PDK's dummy datatype; "
        f"got {lvl2['write_gds']!r} (the drawn layer is {lvl2['drawn_gds']!r})")
    assert lvl2["drawn_gds"] == "36/0"


def test_the_keepout_is_a_SET_and_carries_the_deck_s_own_spacings(spec):
    """The defect was a keep-out of size one. Every entry, and its distance,
    comes from a rule in the deck."""
    avoid = {a["gds"]: a["space_um"] for a in spec["levels"]["2"]["avoid"]}
    assert len(avoid) > 1, "a single-layer keep-out is the defect"
    assert avoid["36/0"] == 2.0      # DM.3  dummy-to-circuit
    assert avoid["36/4"] == 0.98     # DM.2b dummy-to-dummy


def test_the_density_subject_is_read_not_assumed(spec):
    """Filling the dummy layer only helps if the density rule counts it.
    `metal2 = metal2_drawn + metal2_dummy` in this deck, and the spec says so;
    a PDK where it does not must not be filled on that layer."""
    assert spec["density_subject_includes_dummy"] is True
    assert set(spec["levels"]["2"]["coverage_counts"]) == {"36/0", "36/4"}
    assert spec["levels"]["2"]["coverage_target_pct"] == 30.0


def test_it_fails_closed_on_a_deck_it_cannot_read(tmp_path):
    """FAIL-CLOSED is the load-bearing property: a fill placed on a guess is
    metal on a mask that the deck we failed to read would have caught."""
    (tmp_path / "rule_decks").mkdir()
    for rel in ("generic_layers.rb", "rule_decks/dummy_metal.rb",
                "rule_decks/density.rb"):
        (tmp_path / rel).write_text("# nothing this parser understands\n")
    assert pds.derive(tmp_path) is None
    assert pds.derive(tmp_path / "does-not-exist") is None


def test_a_commented_out_rule_is_not_read_as_live(spec):
    """The deck keeps disabled rules as comments (DM.4/5/6/7 here). Reading one
    as live would keep tiles out of space the foundry allows."""
    avoid = {a["gds"] for a in spec["levels"]["2"]["avoid"]}
    # DM.4_DM.6 would have added the NEXT metal layer at 1 um; it is commented.
    assert "42/0" not in avoid


def test_a_commented_out_density_registration_is_not_read_as_live(tmp_path):
    """THE SAME RULE, ON THE ONE MATCH THAT DID NOT CONSULT IT.

    `_RE_RESULT_IS_SUM` decides whether filling the dummy layer can move the
    density number AT ALL — `derive`'s own comment says a deck that does not
    sum drawn+dummy "must say so rather than emit a spec that cannot work".
    It was the single match in this function that did not go through
    `_commented`, so a deck whose `register_layer(names[:metal_result]) {
    drawn + dummy }` is COMMENTED OUT still reported the subject as summed and
    the spec claimed a coverage target it cannot reach.

    Built by commenting out that ONE line of the real fixture deck: the only
    variable between this reading and `test_the_density_subject_is_read_not_
    assumed` above (which reads True on the same deck) is the `#`.
    """
    import shutil
    src = DECK
    dst = tmp_path / "deck"
    shutil.copytree(src, dst)
    lay = dst / "generic_layers.rb"
    txt = lay.read_text()
    hit = [ln for ln in txt.splitlines()
           if pds._RE_RESULT_IS_SUM.search(ln)]
    assert len(hit) == 1, f"fixture must carry exactly one registration: {hit}"
    lay.write_text(txt.replace(hit[0], "        # " + hit[0].strip()))
    # the line is still THERE and still matches the pattern — only commented
    assert pds._RE_RESULT_IS_SUM.search(lay.read_text())
    spec = pds.derive(dst)
    assert spec is not None, "commenting one rule must not break the parse"
    assert spec["density_subject_includes_dummy"] is False, (
        "a commented-out result registration was read as a live one")


def test_the_emitted_fill_script_enforces_the_grid_pitch():
    """`placed.sized(gap)` only keeps a LATER tile off an earlier one; tiles
    from one grid pass are `pitch - tile` apart regardless. MEASURED: pitch 1.9
    with tile 1.2 leaves 0.7 um against a 0.98 um rule and the deck answered
    683 + 595. The emitted script must raise the pitch to the rule."""
    src = p3._GDS_DUMMY_FILL_PY
    assert "if gap > 0 and pitch - tile < gap:" in src
    assert "pitch = tile + gap" in src


def test_the_legacy_single_layer_spec_still_describes_the_old_behaviour():
    """Nothing that ships the older spec shape may change: it is translated to
    a one-entry keep-out at its own margin, which is what it always did."""
    src = p3._GDS_DUMMY_FILL_PY
    assert 'levels = spec.get("levels")' in src
    assert '"space_um": l.get("margin_um", 0.65)' in src
    assert '"coverage_counts": [l["gds"]]' in src
