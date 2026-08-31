"""Tests for magic_gencell_layout_lib — every case is a reduction of a
measured u_hawaii_adc failure (LAWS #22-#24 + the manifest audit + the
comparison-grid rule), so a regression here re-opens a real silicon defect."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import magic_gencell_layout_lib as M


# ── LAW #22 ───────────────────────────────────────────────────────────────

MAG_SCALED = """magic
tech ihp-sg13g2
magscale 1 2
timestamp 1
use /x/cap  cc
timestamp 1
transform 1 0 4518 0 1 31412
box -920 -920 920 920
"""

MAG_PLAIN = """magic
tech ihp-sg13g2
timestamp 1
use /x/dev  mp
timestamp 1
transform 1 0 4518 0 1 31412
box -920 -920 920 920
"""


def test_magscale_read_per_file():
    assert M.mag_scale(MAG_SCALED) == (1, 2)
    assert M.mag_scale(MAG_PLAIN) == (1, 1)


def test_use_transforms_halved_only_under_magscale():
    # the measured defect: reading 4518 as lambda in a magscale 1 2 file
    # doubled every origin (wiring painted off-die, 51 one-pin nets)
    assert M.parse_use_transforms(MAG_SCALED)["cc"] == (2259, 15706)
    assert M.parse_use_transforms(MAG_PLAIN)["mp"] == (4518, 31412)


def test_half_lambda_survives_as_float():
    txt = MAG_SCALED.replace("4518", "4519")
    x, _y = M.parse_use_transforms(txt)["cc"]
    assert x == 2259.5


def test_rlabels_always_internal():
    # same rlabel line must decode identically in both file kinds
    lbl = "rlabel metal2 100 200 100 200 0 D\n"
    for base in (MAG_SCALED, MAG_PLAIN):
        out = M.parse_rlabels(base + lbl)
        assert out[0]["x"] == 50 and out[0]["y"] == 100


# ── LAW #23 ───────────────────────────────────────────────────────────────

def test_tied_taps_staggered_strictly_ascending():
    # D and S of one MOS share a y -> co-linear rungs shorted 28 pairs
    taps = [("d", 100, 500.0), ("s", 144, 500.0), ("g", 122, 620.0)]
    out = M.stagger_ladder_taps(taps, col_top=1000)
    ys = [t[2] for t in out]
    assert ys == sorted(ys)
    assert all(b - a >= 51 for a, b in zip(ys, ys[1:]))
    # order by original y is preserved for the tied pair
    assert [t[0] for t in out] == ["d", "s", "g"]


def test_stagger_never_reorders():
    # raising a tie must not push it past a later tap's rank
    taps = [("a", 0, 100.0), ("b", 10, 100.0), ("c", 20, 130.0)]
    out = M.stagger_ladder_taps(taps, col_top=10_000)
    assert [t[0] for t in out] == ["a", "b", "c"]
    ys = [t[2] for t in out]
    assert all(b - a >= 51 for a, b in zip(ys, ys[1:]))


def test_descent_avoids_foreign_tap_in_span():
    # measured: a blind descent walked through a tap pad two rows below
    x = M.allocate_descent(prefer=2500, last_descent=2440, net="n1",
                           y_span=(-3200, 16593),
                           obstacles=[("nd1", 2515, 6559)],
                           lanes=[2440])
    assert abs(x - 2515) >= 60


def test_descent_ignores_own_net_and_stays_ascending():
    x = M.allocate_descent(prefer=2500, last_descent=2440, net="nd1",
                           y_span=(0, 100),
                           obstacles=[("nd1", 2515, 50)],
                           lanes=[2440])
    assert x >= 2500


# ── LAW #24 ───────────────────────────────────────────────────────────────

def test_cap_exits_clear_of_own_plate():
    plate = (10740, 14000, 11660, 14920)
    top_x, bot_x = M.cap_plate_exits(plate)
    assert top_x < plate[0] and bot_x > plate[2]
    # the measured shorts: a fixed -900 offset put the top stack INSIDE
    assert not (plate[0] <= top_x <= plate[2])


# ── manifest audit ────────────────────────────────────────────────────────

def test_cross_net_overlap_found_and_crossing_ignored():
    man = [
        {"net": "a", "layer": "metal3", "box": [0, 0, 100, 30]},
        {"net": "b", "layer": "metal3", "box": [50, 10, 150, 40]},   # short
        {"net": "c", "layer": "metal2", "box": [60, -50, 90, 80]},   # cross
    ]
    hits = M.cross_net_overlaps(man)
    nets = {frozenset((h[0], h[3])) for h in hits}
    assert frozenset(("a", "b")) in nets
    # m2 under m3 with no via is a legal crossing, not a short
    assert frozenset(("a", "c")) not in nets
    assert frozenset(("b", "c")) not in nets


def test_via_links_both_metals():
    man = [
        {"net": "a", "layer": "via2", "box": [0, 0, 20, 20]},
        {"net": "b", "layer": "metal2", "box": [10, 10, 40, 40]},
    ]
    assert M.cross_net_overlaps(man)


def test_same_net_never_reported():
    man = [
        {"net": "a", "layer": "metal2", "box": [0, 0, 100, 30]},
        {"net": "a", "layer": "metal2", "box": [50, 10, 150, 40]},
    ]
    assert M.cross_net_overlaps(man) == []


# ── comparison grid ───────────────────────────────────────────────────────

def test_grid_snap_only_touches_w_l():
    line = "Rr1 vout vfb vss rppd w=0.5u l=76.8049u m=1"
    out = M.grid_snap_spice_params(line)
    assert "l=76.8u" in out and "w=0.5u" in out and "m=1" in out


def test_grid_snap_is_identity_on_grid():
    line = "Mx d g s b nmos w=7.83u l=1u"
    assert M.grid_snap_spice_params(line) == line
