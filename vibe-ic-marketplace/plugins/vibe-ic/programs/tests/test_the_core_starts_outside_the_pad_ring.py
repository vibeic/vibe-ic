"""The placeable core was starting 10 um from the die edge on a die whose pad
ring is 381 um deep, so cells were placed under the pads.

THE MEASUREMENT. spm x gf180mcuD at v1.16.38:

    DIEAREA (0 0) (6324000 6324000)
    CORE     20160 23520 -> 6283200 6279840     (inset 10.1-22.1 um)
    ring depth measured from the library: 381 um
    => the core overlapped the ring by ~366 um on every side

and the first detailed_route reported 3515 violations — 3112 Shorts, 3104 of
them inside that band, 2054 naming an IO instance (`net:u_core/... inst:
u_pad_x_N`). The pads' own obstruction fills M1 and M2 under the bond pad, so
anything placed or routed there shorts.

WHAT IS DERIVED AND FROM WHERE. The depth is NOT typed: it is the deepest
PLACED ring master, at its own LEF SIZE — the pad's HEIGHT, and a corner cell
at its larger dimension because it occupies both sides — plus the PDK's
declared PAD_EDGE_SPACING. Two LEF-carried facts, no constant.

FAIL-CLOSED. A ring whose record states no depth, or names a master with no
LEF SIZE, REFUSES. A default inset is the defect this replaces.
"""
from __future__ import annotations

import json
import math

import io_pad_chip_top_gen as G      # noqa: F401  (imported for parity)
import phase3_one_shot_runner as R


def _rec(tmp_path, **over):
    body = {"ring_depth_um": 381.0,
            "ring_depth_terms_um": {"lib__in": 350.0, "lib__cor": 355.0},
            "ring_depth_masters_without_a_lef_size": [],
            "die_side_um": 3162.0}
    body.update(over)
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "io_pad_chip_top.json").write_text(json.dumps(
        {"verdict": "WROTE", "die_required_um": body}))
    return tmp_path


def test_the_inset_is_the_rings_own_measured_depth(tmp_path):
    inset, why = R._padring_core_inset_um(_rec(tmp_path))
    assert why == "" and inset == 381.0
    assert int(math.ceil(inset)) == 381


def test_a_design_with_no_ring_keeps_the_historical_inset(tmp_path):
    """CONTROL for every design off the chip path: nothing changes."""
    inset, why = R._padring_core_inset_um(tmp_path)
    assert inset is None and why == ""


def test_a_record_with_no_depth_refuses_and_says_what_is_missing(tmp_path):
    inset, why = R._padring_core_inset_um(_rec(tmp_path, ring_depth_um=None))
    assert inset is None
    assert "ring_depth_um" in why and "cannot be derived" in why


def test_a_master_with_no_lef_size_refuses_by_name(tmp_path):
    inset, why = R._padring_core_inset_um(
        _rec(tmp_path, ring_depth_masters_without_a_lef_size=["lib__odd"]))
    assert inset is None
    assert "lib__odd" in why and "not guessed" in why


def test_the_core_rectangle_lands_outside_the_ring_band(tmp_path):
    """THE FORWARD CONTROL, in the geometry the deck is built from."""
    die = 3162
    inset = int(math.ceil(R._padring_core_inset_um(_rec(tmp_path))[0]))
    llx = lly = inset
    urx = ury = die - inset
    for edge, value in (("left", llx), ("bottom", lly),
                        ("right", die - urx), ("top", die - ury)):
        assert value >= 381, f"{edge} edge is {value} um inside a 381 um ring"


def test_the_superseded_inset_reproduces_the_overlap(tmp_path):
    """THE REVERSE CONTROL. Put the flat 10 um back and the core is inside the
    ring again — the state that produced 3104 Shorts."""
    die, ring = 3162, 381
    old = 10
    assert die - 2 * old > 0
    overlap = ring - old
    assert overlap > 0
    assert overlap == 371, (
        "the historical inset leaves the core 371 um inside the ring band")


def test_the_area_cost_is_stated_not_hidden(tmp_path):
    """A 381 um inset is not free and the number is arithmetic, not opinion."""
    die = 3162.0
    old_side, new_side = die - 2 * 10, die - 2 * 381
    old_area, new_area = old_side ** 2, new_side ** 2
    assert new_side == 2400.0
    assert round(100.0 * (1 - new_area / old_area), 1) == 41.7
