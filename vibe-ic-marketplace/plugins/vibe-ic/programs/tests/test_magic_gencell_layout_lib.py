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


def test_rlabels_follow_the_files_own_magscale():
    # THE CORRECTED LAW, and the arm that catches the old one. An rlabel is
    # in the FILE's units like every other coordinate, so the SAME line
    # decodes DIFFERENTLY in the two kinds of file — which is the opposite
    # of what this test used to assert. Magic's own streamed GDS settled it:
    # a header-less ihp-sg13g2 cap child's `rlabel metal5 510 ...` is at
    # 5.10 um = 510 lambda, not 255, and 255 is the middle of the top plate
    # the label is NOT on. The `magscale 1 2` arm is unchanged, which is why
    # the old halving looked measured.
    lbl = "rlabel metal2 100 200 100 200 0 D\n"
    scaled = M.parse_rlabels(MAG_SCALED + lbl)[0]
    plain = M.parse_rlabels(MAG_PLAIN + lbl)[0]
    assert (scaled["x"], scaled["y"]) == (50, 100)
    assert (plain["x"], plain["y"]) == (100, 200)
    assert M.mag_scale(MAG_PLAIN) == (1, 1)


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


# ── LAW #25: contact-enclosure repair of a vendor gencell ─────────────────
#
# The reduction: the PDK's own Magic rppd gencell caps each resistor head
# contact with a metal1 pad short of the deck's CntB.h1 enclosure by half
# (0.025 um against 0.05), identically for every w/l probed, and the two
# campaign blocks shipped 6 sign-off DRC violations because of it.

# contact 0..10 x 0..10; metal covers it with 10 on three sides and 5 on top
_C = [(0, 0, 10, 10)]
_M = [(-10, -10, 20, 10), (-10, 10, 20, 15)]


def test_enclosure_patch_only_on_the_short_side():
    patches, refused = M.contact_enclosure_patches(_C, _M + _C, 10)
    assert refused == []
    assert patches == [(-10, 10, 20, 20)]
    # and the repaired picture needs no second patch
    again, _ = M.contact_enclosure_patches(_C, _M + _C + patches, 10)
    assert again == []


def test_enclosure_patch_refused_when_it_would_break_spacing():
    # a foreign island 6 above the short side: patching to 10 leaves a 4 gap
    foreign = [(-10, 21, 20, 30)]
    patches, refused = M.contact_enclosure_patches(
        _C, _M + _C + foreign, 10, min_space=18)
    assert patches == []
    assert refused == [(-10, 10, 20, 20)]


def test_enclosure_patch_not_refused_by_its_own_island():
    # the pad the band EXTENDS is 0 away from it — same island, it merges.
    # Refusing on that (the first spacing-aware attempt did) repairs nothing.
    patches, refused = M.contact_enclosure_patches(
        _C, _M + _C, 10, min_space=18)
    assert patches == [(-10, 10, 20, 20)]
    assert refused == []


_MAG_SHORT = """magic
tech t
magscale 1 2
timestamp 1
<< polycont >>
rect 0 0 10 10
<< metal1 >>
rect -10 -10 20 10
rect -10 10 20 15
<< end >>
"""


def test_repair_mag_appends_into_the_metal_section():
    out, n = M.repair_mag_contact_enclosure(_MAG_SHORT, "polycont",
                                            "metal1", 10)
    assert n == 1
    body = out.split("<< metal1 >>")[1]
    assert "rect -10 10 20 20" in body
    # idempotent: a repaired file needs no second pass
    _out2, n2 = M.repair_mag_contact_enclosure(out, "polycont",
                                               "metal1", 10)
    assert n2 == 0


def test_repair_mag_is_a_no_op_without_contacts():
    text = "magic\n<< metal1 >>\nrect 0 0 1 1\n<< end >>\n"
    out, n = M.repair_mag_contact_enclosure(text, "polycont", "metal1", 10)
    assert (out, n) == (text, 0)


def test_implicit_metal_sections_sees_the_contact_types():
    text = ("magic\n<< pwell >>\n<< ndiffc >>\n<< psubdiffcont >>\n"
            "<< polycont >>\n<< metal1 >>\n<< via1 >>\n<< metal2 >>\n"
            "<< labels >>\n<< end >>\n")
    got = M.implicit_metal_sections(text, "metal1")
    assert got[0] == "metal1"
    for name in ("ndiffc", "psubdiffcont", "polycont", "via1"):
        assert name in got
    for name in ("pwell", "metal2", "labels", "end"):
        assert name not in got


def test_repair_reads_the_guard_ring_through_the_implicit_sections():
    # the neighbour that must refuse the patch lives in psubdiffcont, which
    # a metal1-only reader cannot see (measured: 30 notch violations).
    text = """magic
tech t
<< polycont >>
rect 0 0 10 10
<< psubdiffcont >>
rect -10 21 20 30
<< metal1 >>
rect -10 -10 20 10
rect -10 10 20 15
<< end >>
"""
    _out, n = M.repair_mag_contact_enclosure(text, "polycont", "metal1",
                                             10, 18)
    assert n == 0
    # blind to that section, the same call paints the violation
    _out2, n2 = M.repair_mag_contact_enclosure(
        text, "polycont", "metal1", 10, 18, metal_sections=["metal1"])
    assert n2 == 1


# ── LAW #26: the manifest audit also has to ask about SPACE ───────────────

def test_spacing_audit_finds_the_sub_minimum_gap_the_overlap_audit_misses():
    man = [{"net": "a", "layer": "metal2", "box": [0, 0, 100, 10]},
           {"net": "b", "layer": "metal2", "box": [0, 20, 100, 30]}]
    assert M.cross_net_overlaps(man) == []
    hits = M.cross_net_spacing_violations(man, {"metal2": 21})
    assert len(hits) == 1 and hits[0][3] == 10


def test_spacing_audit_is_silent_at_the_rule_and_on_other_layers():
    man = [{"net": "a", "layer": "metal2", "box": [0, 0, 100, 10]},
           {"net": "b", "layer": "metal2", "box": [0, 31, 100, 40]}]
    assert M.cross_net_spacing_violations(man, {"metal2": 21}) == []
    assert M.cross_net_spacing_violations(man, {"metal3": 21}) == []


def test_spacing_audit_leaves_touching_pairs_to_the_overlap_audit():
    man = [{"net": "a", "layer": "metal2", "box": [0, 0, 100, 10]},
           {"net": "b", "layer": "metal2", "box": [0, 10, 100, 20]}]
    assert M.cross_net_spacing_violations(man, {"metal2": 21}) == []
    assert len(M.cross_net_overlaps(man)) == 0  # edge touch, not an overlap
