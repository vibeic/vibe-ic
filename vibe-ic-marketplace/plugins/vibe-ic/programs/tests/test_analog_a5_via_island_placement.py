"""The via island is PLACED, and the device it stands next to is read whole.

MEASURED, on `u_hawaii_adc`'s two analog blocks, image 0.3.46, the PDK's own
KLayout sign-off deck (ihp-sg13g2, 560 rules graded), 2026-09-06:

    delta_sigma   2780 violations   M2.b 1504  M3.b 654  V1.b 326  M1.b 296
    ldo            264 violations   M2.b  210  V1.b  42  M1.b  12

Two controls on the same GDS with the same deck settle who owns them:

  * every top-level rectangle the flow painted REMOVED, the gencells left
    exactly where the emitter placed them → 0 violations, 560 rules graded,
    on BOTH blocks. Nothing is the PDK's cell and nothing is the placement.
  * every gencell instance removed, the flow's own paint left → 802 on
    delta_sigma, 0 on ldo. The rest (1978 / 264) is the flow's paint against
    the device's.

All 2242 routing-against-device violations have a VIA ISLAND as one of their
two edges, and every violation of both blocks is a minimum-SPACING rule on a
layer this emitter routes on. Five separate defects put them there, and each
arm below fails against the code as it stood before its own fix.
"""
from __future__ import annotations

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path

import analog_a5_layout_emit as A5E
import analog_a5_pdk_device_limits as A5L


# A magic DRC deck states the two via surrounds as two rules with two
# PRESENCE words. This is the shape, verbatim from a real open PDK.
SURROUND_TECH = """
 width  m1  180  "Metal1 width < 0.18um (M1.a)"
 spacing m1 m1 180 touching_ok "Metal1 spacing < 0.18um (M1.b)"
 spacing allm2 allm2 210 touching_ok "Metal2 spacing < 0.21um (M2.b)"
 area allm2 144000 200 "Metal2 minimum area < 0.144um^2 (M2.d)"
 width v1/m1 200 "Via1 width < 0.2um (V1.a)"
 spacing v1 v1 210 touching_ok "Via1 spacing < 0.21um (V1.b)"
 surround v1/m1 *m1,rm1 5 absence_illegal \\
\t"Metal1 overlap of Via1 < 0.005um (V1.c)"
 surround v1/m1 *m1,rm1 45 directional \\
\t"Metal1 overlap of Via1 < 0.045um in one direction (V1.c1)"
 surround v1/m2 *m2,rm2 45 directional \\
\t"Metal2 overlap of Via1 < 0.045um in one direction (M2.c1)"
"""


def _geo():
    return A5E.Geo(A5L.deck_rules(SURROUND_TECH), 0.18, 100, 0.30, 0.15)


# ── 1. the two surrounds are two rules ──────────────────────────────────
def test_a_directional_surround_is_not_the_all_around_one():
    """`max()` over both, applied on every side, is a DIFFERENT rule.

    Before: `via_surround_um[(1,1)]` was 0.045 — the larger of an all-around
    0.005 and a directional 0.045 — so every island was square at nine times
    the distance the deck asks for on a side.
    """
    d = A5L.deck_rules(SURROUND_TECH)
    assert d["via_surround_um"][(1, 1)] == 0.005
    assert d["via_surround_dir_um"][(1, 1)] == 0.045
    assert (1, 2) not in d["via_surround_um"]
    assert d["via_surround_dir_um"][(1, 2)] == 0.045


def test_a2_the_island_is_anisotropic_and_meets_the_area_rule():
    g = _geo()
    short, long_ = g.short_half[1], g.long_half[1]
    assert short < long_, "an island built from two different rules is not square"
    # the all-around surround, rounded up, on the short side
    assert short == g.via_pad[1] + 1
    # the area rule met by LENGTHENING, not by growing both sides:
    # 0.144 um^2 on a 100 lambda/um grid is 1440 lambda^2
    assert A5L.deck_rules(SURROUND_TECH)["metal_area_um2"][2] == 0.144
    assert 4 * short * long_ >= 1440


# ── 2. a device rectangle is rounded OUTWARD ────────────────────────────
HALF_GRID_CHILD = """magic
tech pdktech
magscale 1 2
timestamp 1
<< metal1 >>
rect -101 -101 101 101
<< labels >>
rlabel metal1 0 0 0 0 0 D
port 1 nsew
<< end >>
"""


def test_b_a_half_lambda_device_edge_rounds_away_from_the_router():
    """`int()` pulls both edges toward zero: the obstacle SHRINKS.

    Measured after the placer was already clearing everything it could see:
    30 M2.b left on one block, every one at 0.205 um against a 0.21 um rule
    — one half lambda, and the placer had computed 0.21 and was satisfied.
    """
    cell = A5E.parse_cell(HALF_GRID_CHILD)
    r = cell["sections"]["metal1"][0]
    assert r == (-51, -51, 51, 51), (
        "a half-lambda edge must move OUT (floor the low side, ceil the "
        "high side); toward zero it would read (-50, -50, 50, 50)")


# ── 3. a contact tile carries metal the metal section does not show ─────
def test_c_a_via_tile_is_also_the_two_metals_it_joins():
    assert A5E.carried_planes("via1") == ["via1", "metal1", "metal2"]
    assert A5E.carried_planes("via2") == ["via2", "metal2", "metal3"]
    assert "metal1" in A5E.carried_planes("psubdiffcont")
    assert "metal1" in A5E.carried_planes("ndiffc")
    assert A5E.carried_planes("metal2") == ["metal2"]


VIA_ONLY_CHILD = """magic
tech pdktech
magscale 1 1
timestamp 1
<< via1 >>
rect 0 0 30 30
<< labels >>
rlabel via1 15 15 15 15 0 D
port 1 nsew
<< end >>
"""


def test_c2_the_device_plane_model_holds_the_metal_a_via_generates():
    planes = A5E.device_planes(A5E.parse_cell(VIA_ONLY_CHILD))
    assert (0, 0, 30, 30) in planes["metal2"], (
        "the GDS a via1 tile writes carries metal2; a reader that takes "
        "<< metal2 >> at face value cannot see it")
    assert (0, 0, 30, 30) in planes["metal1"]


# ── 4. spacing is a POLYGON question, not a conductor question ──────────
def test_d_a_conductor_is_exempt_only_on_the_layer_it_merges_on():
    """Skipping a whole conductor because the island touched it SOMEWHERE
    is how an island lands two lambda from its own terminal's other metal.
    """
    geo = _geo()
    rows = [
        # the terminal's own metal1 — the island will sit on this one
        {"net": "<device d0>", "layer": "metal1", "comp": ("d0", 1),
         "lcomp": ("d0", "metal1", 1), "box": (0, 0, 100, 100)},
        # the SAME conductor's metal2, a separate polygon, 2 lambda above
        {"net": "<device d0>", "layer": "metal2", "comp": ("d0", 1),
         "lcomp": ("d0", "metal2", 2), "box": (0, 102, 100, 140)},
    ]
    sites = A5E.Sites(rows, geo)
    box = (20, 20, 60, 100)          # on metal1 AND metal2, 2 lambda below
    assert sites.clear(box, ["metal1"], ("d0", 1)) is True
    assert sites.clear(box, ["metal2"], ("d0", 1)) is False, (
        "on metal2 the island does not merge with that polygon, so the "
        "deck's spacing rule applies to it like any stranger's")


def test_d2_the_emitters_own_paint_is_an_obstacle_too():
    geo = _geo()
    sites = A5E.Sites([], geo)
    sites.add({"net": "other", "layer": "metal2", "box": (100, 0, 140, 40)})
    assert sites.clear((0, 0, 40, 40), ["metal2"], None, "mine") is True
    assert sites.clear((60, 0, 95, 40), ["metal2"], None, "mine") is False, (
        "an island placed clear of every device and into the island of the "
        "terminal next door has not been placed either")
    # its own net is one conductor here
    assert sites.clear((60, 0, 95, 40), ["metal2"], None, "other") is True


# ── 5. the escape pitch is built from the WIDEST thing painted ──────────
def test_e_the_escape_pitch_clears_an_island_not_only_a_wire():
    """Wire-width-plus-space left 20 lambda against a 21 lambda rule
    wherever the neighbour at the next escape height was an island."""
    geo = _geo()
    wire_pitch = max(geo.wire[k] + geo.metal_space(f"metal{k}") for k in (2, 3))
    island_pitch = max(max(geo.wire[k], 2 * geo.long_half[k])
                       + geo.metal_space(f"metal{k}") for k in (2, 3))
    assert island_pitch > wire_pitch
    # an island at one height and a wire at the next must not be closer than
    # the deck's spacing
    gap = island_pitch - geo.long_half[3] - geo.wire[3] // 2
    assert gap >= geo.metal_space("metal3")


# ── 6. a short needs a PATH, not a touching pair ────────────────────────
def test_f_the_short_audit_is_transitive_and_sees_the_devices():
    """The pairwise scan over the routing manifest cannot see this shape.

    MEASURED on u_hawaii_adc: the sign-off LVS reported `mismatch` on both
    analog blocks — five schematic nets extracting as ONE — and A5's own
    record said the layout was clean. The path is three rectangles long and
    the middle one is a DEVICE's: our metal5 island on one net, the MiM
    capacitor's own metal5 plate, our metal5 island on the other. No PAIR in
    it is two routing rectangles of different nets.

    12 such shorts on delta_sigma and 1 on ldo, every one of them a MiM
    capacitor whose two terminal labels both resolve to the plane its BOTTOM
    plate occupies — `metal_level_at` recognises a conductor only when its
    section is named `metalN`/`viaN`, and this PDK delivers the TOP plate on
    `mimcapcontact`.
    """
    plan = A5E.Plan()
    plan.paint("vg", "metal5", 0, 0, 40, 40)
    plan.paint("vout", "metal5", 200, 0, 240, 40)
    # the device plate that joins them — nothing this emitter painted
    plan.device_shapes.append(
        {"net": "<device cc>", "layer": "metal5", "box": (-50, -50, 300, 90)})

    import magic_gencell_layout_lib as _gl
    assert _gl.cross_net_overlaps(plan.shapes) == [], (
        "the pairwise scan over the routing manifest sees nothing here — "
        "which is exactly why it reported a clean sheet on a shorted block")

    shorts = A5E.net_shorts(plan)
    assert len(shorts) == 1, shorts
    assert set(shorts[0]["nets"]) == {"vg", "vout"}
    path = shorts[0]["path"]
    assert len(path) == 3, path
    assert path[1]["net"].startswith("<device "), (
        "the witness must NAME the device rectangle in the middle; a reader "
        "told only that two nets are one has been told the symptom")


def test_f2_two_nets_that_are_genuinely_apart_are_not_reported():
    """A check that cannot pass is not a check either."""
    plan = A5E.Plan()
    plan.paint("vg", "metal5", 0, 0, 40, 40)
    plan.paint("vout", "metal5", 200, 0, 240, 40)
    plan.device_shapes.append(
        {"net": "<device cc>", "layer": "metal5", "box": (-50, -50, 60, 90)})
    assert A5E.net_shorts(plan) == []
