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

import hashlib
import importlib
import json
from types import SimpleNamespace

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path
import pytest

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
    # A remote rectangle on the same net is still a separate polygon for
    # spacing; only a rectangle that actually joins the existing paint is
    # exempt from the inter-polygon spacing rule.
    assert sites.clear((60, 0, 95, 40), ["metal2"], None, "other") is False
    assert sites.clear((95, 0, 120, 40), ["metal2"], None, "other") is True


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


# ── 7. the PDK's own layer table, not the section's spelling ────────────
#
# MEASURED, u_hawaii_adc / ihp-sg13g2 / image 0.3.46, both blocks through the
# real producer:
#
#                     drawn shorts   magic MIM.i "Via4 cannot contact MiM cap
#                     (union-find)    bottom plate"   magic LAYOUT-class rc
#   ldo          base       1                 0              0
#   ldo          fix        0                 0              0
#   delta_sigma  base      12                 8              1
#   delta_sigma  fix        0                 0              0
#
# and the KLayout per-block sign-off deck reports 0 violations over the same
# 560 rules on both blocks on both sides.

# The three sections a magic technology file needs to answer "what is this
# type?", in the shape a magic PDK ships them. Real names from an open PDK.
TECH = """
planes
  metal4,m4
  metal5,m5
  cap1,c1
  metal6,m6
end

types
  metal4 metal4,m4,met4
  metal4 via4,v4
  metal5 metal5,m5,met5
 -metal5 m5fill
  cap1 mimcap,mim,capm
  cap1 mimcapcontact,mimcapc,mimcc,capmc
  metal6 metal6,m6,met6
end

contact
  via4   metal4 metal5
  mimcc  mimcap metal6
  stackable
end
"""

# The gencell child a MiM capacitor comes back as: ONE metal5 rectangle for
# the bottom plate covering the whole device, a cap-plate ring, a contact
# square in the middle, and the two terminal labels. No `magscale` header —
# this kind of child ships without one, which is the other half of the
# defect below.
CAP_CHILD = """magic
tech pdktech
timestamp 1
<< metal5 >>
rect -560 -560 560 560
<< mimcap >>
rect -500 480 500 500
rect -500 -480 -480 480
rect 480 -480 500 480
rect -500 -500 500 -480
<< mimcapcontact >>
rect -480 -480 480 480
<< labels >>
rlabel mimcapcontact 0 0 0 0 0 C1
port 1 nsew
rlabel metal5 510 0 510 0 0 C2
port 2 nsew
<< properties >>
string FIXED_BBOX -560 -560 560 560
<< end >>
"""


def _table():
    return A5L.layer_identity(TECH, "/pdk/x.tech")


def test_g_the_table_answers_what_a_type_is():
    li = _table()
    # a contact IS its two residues, so it carries the HIGHER conductor
    assert li.level("mimcapcontact") == 6
    assert li.conductor_planes("mimcapcontact") == ["cap1", "metal6"]
    # the alias the contact section spells it with resolves to the same type
    assert li.level("mimcc") == 6
    # the cap plate itself is on no plane this generator routes on
    assert li.level("mimcap") is None
    # a NON-CONNECTING type (`-plane` in the file) is not a conductor at all
    assert li.conductor_planes("m5fill") == []
    # and a type the file does not declare is UNKNOWN, never defaulted
    assert not li.knows("nosuchlayer")
    assert li.level("nosuchlayer") is None


def test_g_a_named_metal_section_is_unchanged_by_the_table():
    """THE CONTROL. A PDK that does spell its conductors `metalN` / `viaN`
    gets the same answer from the table as from the names, which is why the
    repair is a generalisation and not a change of behaviour."""
    li = _table()
    for name, want in (("metal4", 4), ("metal5", 5), ("via4", 5)):
        assert li.level(name) == want
    assert A5E.carried_planes("via4") == ["via4", "metal4", "metal5"]
    assert A5E.carried_planes("via4", li) == ["via4", "metal4", "metal5"]
    assert A5E.carried_planes("metal5") == A5E.carried_planes("metal5", li)


def test_g_both_cap_terminals_read_as_one_plane_without_the_table():
    """RED. This is the defect, reproduced on the PDK's own gencell output:
    with no layer table the top-plate label on `mimcapcontact` matches
    neither `metalN` nor `viaN`, so the only section covering it that DOES
    is the metal5 the BOTTOM plate occupies, and both terminals come back on
    metal5. The emitter then drops a via stack for each onto one plate."""
    cell = A5E.parse_cell(CAP_CHILD)
    levels = {lab["name"]: lab["level"] for lab in cell["labels"]}
    assert levels == {"C1": 5, "C2": 5}
    # and the contact's 960x960 conductor is registered as metal1 — the
    # `cont`-in-the-name guess — so nothing sees a metal6 plate at all
    planes = A5E.device_planes(cell)
    assert "metal6" not in planes
    assert "metal1" in planes


def test_g_the_table_separates_the_two_cap_terminals():
    """GREEN, on the same bytes."""
    cell = A5E.parse_cell(CAP_CHILD, _table())
    levels = {lab["name"]: lab["level"] for lab in cell["labels"]}
    assert levels == {"C1": 6, "C2": 5}
    planes = A5E.device_planes(cell)
    assert planes["metal6"] == [(-480, -480, 480, 480)]
    assert planes["metal5"] == [(-560, -560, 560, 560)]
    assert "metal1" not in planes


def test_g_reading_the_section_name_again_re_reddens_the_cap(monkeypatch):
    """MUTATION. Put the name-reading answer back INSIDE the table — the one
    line the repair is — and exactly the MiM case returns; the named-metal
    control does not move."""
    li = _table()
    monkeypatch.setattr(li, "knows", lambda name: False)
    cell = A5E.parse_cell(CAP_CHILD, li)
    levels = {lab["name"]: lab["level"] for lab in cell["labels"]}
    assert levels == {"C1": 5, "C2": 5}, (
        "the mutation must restore the defect, or the table is not what is "
        "answering the question")


def test_g_the_cap_terminals_are_where_the_streamed_gds_puts_them():
    """The second half of the same defect, and the reason the table alone
    was not enough. A header-less `.mag` states its rlabel coordinates in the
    FILE's units; halving them put this cap's BOTTOM-plate terminal at 255 —
    the dead centre of the TOP plate — instead of 510, just outside it.
    Magic's own streamed GDS for this child puts C2 at 5.10 um, and this
    child is drawn at 100 lambda per micron."""
    cell = A5E.parse_cell(CAP_CHILD, _table())
    xs = {lab["name"]: lab["x"] for lab in cell["labels"]}
    assert xs == {"C1": 0, "C2": 510}
    top = [r for r in cell["sections"]["mimcapcontact"]][0]
    assert not (top[0] <= xs["C2"] <= top[2]), (
        "the bottom-plate terminal must not land inside the top plate")


# ── 8. a drawn short is BLOCKING ────────────────────────────────────────
def test_h_a_drawn_short_is_a_blocking_deviation():
    """The short audit's finding is the one deviation that is not a
    clearance prediction, so it is the one that changes the exit code."""
    plan = A5E.Plan()
    plan.paint("vg", "metal5", 0, 0, 40, 40)
    plan.paint("vout", "metal5", 200, 0, 240, 40)
    plan.device_shapes.append(
        {"net": "<device cc>", "layer": "metal5", "box": (-50, -50, 300, 90)})
    geo = _geo()
    A5E.clearance_deviations(plan, geo, [])
    blocking = A5E.blocking_shorts(plan.deviations)
    assert len(blocking) == 1, plan.deviations
    assert "ONE conductor" in blocking[0]["detail"]
    assert "<device cc>" in blocking[0]["detail"], (
        "the blocking record must carry the witness path, not just a verdict")


def test_h2_nets_that_are_genuinely_apart_block_nothing():
    """THE ANTI-CHEAT ARM. Same fixture, same deck, the device rectangle
    short of the second net: no short, nothing blocking, and every other
    deviation the run produces is untouched."""
    plan = A5E.Plan()
    plan.paint("vg", "metal5", 0, 0, 40, 40)
    plan.paint("vout", "metal5", 200, 0, 240, 40)
    plan.device_shapes.append(
        {"net": "<device cc>", "layer": "metal5", "box": (-50, -50, 60, 90)})
    geo = _geo()
    A5E.clearance_deviations(plan, geo, [])
    assert A5E.blocking_shorts(plan.deviations) == []


# ── 9. which terminal is the one outside the sequence ───────────────────
#
# MEASURED on u_hawaii_adc (ihp-sg13g2, image 0.3.46), per-block LVS through
# the PDK's own KLayout runset:
#
#                          extracted nets   devices   merged nets   LVS
#   ldo          netlist          9            11          -         -
#   ldo          before           6            10          1      mismatch
#   ldo          after            9            11          0      match
#   delta_sigma  netlist        122           294          -         -
#   delta_sigma  before         119           294          1      mismatch
#   delta_sigma  after          122           294          0      mismatch
#
# The one merged net carried a block-spanning substrate polygon and, on
# `ldo`, 20 device terminals — exactly |vin| + |vout| + |vss| of the source.

# The PDK's own resistor child: a substrate guard ring, a poly body, and the
# three labels in the order the `.mag` lists them — B FIRST, which is not the
# order SPICE calls it in. Trimmed to the sections this question needs.
RES_CHILD = """magic
tech pdktech
magscale 1 2
timestamp 1
<< pwell >>
rect -254 -6290 254 6290
<< psubdiff >>
rect -192 6182 192 6228
rect -192 -6136 -178 6136
rect 178 -6136 192 6136
rect -192 -6228 192 -6182
<< psubdiffcont >>
rect -100 6182 100 6214
rect -178 -6136 -146 6136
rect 146 -6136 178 6136
rect -100 -6214 100 -6182
<< polycont >>
rect -36 6040 36 6072
rect -36 -6072 36 -6040
<< ppolyres >>
rect -50 -6000 50 6000
<< labels >>
rlabel psubdiffcont 0 -6198 0 -6198 0 B
port 1 nsew
rlabel polycont 0 6056 0 6056 0 R1
port 2 nsew
rlabel polycont 0 -6056 0 -6056 0 R2
port 3 nsew
<< properties >>
string FIXED_BBOX -162 -6198 162 6198
<< end >>
"""


def _map(child, nets, cls):
    cell = A5E.parse_cell(child, _table())
    dev = {"name": "x", "model": "m", "pars": {}, "nets": nets, "class": cls}
    tmap, ring, unmapped = A5E.terminal_map(dev, cell)
    return ({net: sorted(l["name"] for l in labs)
             for net, labs in tmap.items()}, ring, unmapped)


def test_i_the_ring_layer_is_not_found_on_the_pdks_own_resistor():
    """`ring_layer_of` answers NONE here, and since vibe-ic#2129 it answers
    it for a REASON THIS FIXTURE STATES rather than by a geometric accident.

    The ring in `RES_CHILD` is real and four bars wide. The rule that used to
    reject it — "does this layer cover 90% of the CELL bounding box?" — was
    rejecting it because the WELL rectangle it sits in is wider than it is,
    which is a property of every gencell child of every PDK and is why the
    bulk-tap search never ran on real silicon (#2129).

    The resolver now asks the technology file which drawn types could be a
    body connection AT ALL before geometry gets a say, and `TECH` above
    declares only metals, a via and a cap plate — no diffusion, no contact to
    one. So there is no candidate here, and the answer is None because
    nothing in the table says otherwise. That is the resolver declining to
    guess from a layer NAME, which is the arm this file now contributes; a
    fixture whose table DOES declare the diffusion contacts resolves the ring
    (`test_issue2129_bulk_tap_ring_resolver.py`)."""
    cell = A5E.parse_cell(RES_CHILD, _table())
    assert A5E.body_contact_layers(cell) == [], (
        "this file's TECH declares no contact to a non-routing plane, so the "
        "PDK offers no candidate and the None below is that, not geometry")
    assert A5E.ring_layer_of(cell) is None
    assert [l["name"] for l in cell["labels"]] == ["B", "R1", "R2"], (
        "and the gencell lists the substrate tap FIRST, which is not the "
        "order SPICE calls the device in")


def test_i_the_substrate_tap_goes_to_the_trailing_net():
    """GREEN. `xr1 vout vfb vss` — B is the tap, and SPICE puts it last."""
    got, ring, unmapped = _map(RES_CHILD, ["vout", "vfb", "vss"], "resistor")
    assert got == {"vss": ["B"], "vout": ["R1"], "vfb": ["R2"]}
    assert unmapped == []


def test_i_an_all_ordinal_gencell_is_untouched():
    """THE CONTROL. Every label numbered — the capacitor — so there is no
    label outside the sequence and the file order stands, exactly as before.
    This is the arm that says the rule fires on a PROPERTY, not on a class."""
    got, _ring, unmapped = _map(CAP_CHILD, ["vg", "vout"], "capacitor")
    assert got == {"vg": ["C1"], "vout": ["C2"]}
    assert unmapped == []


def test_i_a_mosfet_is_matched_by_letter_and_never_reaches_this_rule():
    """The second control: a device the PDK classifies as a mosfet is mapped
    by the SPICE terminal letters, whatever order its labels are listed in."""
    mos = RES_CHILD.replace("0 B\n", "0 B\n").replace(
        "0 R1\n", "0 D\n").replace("0 R2\n", "0 S\n")
    got, _ring, unmapped = _map(mos, ["d", "g", "s", "b"], "mosfet")
    assert got == {"d": ["D"], "s": ["S"], "b": ["B"]}
    assert unmapped == ["G->g"], (
        "an absent label is named as unmapped, never silently dropped")


# ── 10. the PDK states two ends and only one was read ───────────────────
#
# MEASURED (u_hawaii_adc / ihp-sg13g2 / image 0.3.46). The KLayout LVS
# cross-reference for `delta_sigma`, after v1.17.88 had taken its drawn
# shorts to 0 and its connectivity to 122/122 nets and 294/294 devices:
#
#     device pairs   286 Match, 8 MatchWithWarning
#     net pairs      111 Match, 11 Mismatch
#     pin pairs        7 Match
#
# Every one of the 8 warned devices is a `cap_cmim` differing in `l` ALONE —
# layout 30.0 um against a schematic 34.75 / 60.0 / 138.98 / 188.72 (x2) /
# 245.34 / 629.08 (x2) — and the 11 mismatched nets are EXACTLY the nets
# those 8 capacitors sit on. Twelve netlist capacitors had collapsed into TWO
# drawn cells. The cause is one unread pair of numbers: the gencell states
# `lmax 30.0 wmax 30.0` in the same `_defaults` proc as `lmin`/`wmin`, and a
# magic gencell asked for more does not refuse — it CLAMPS and draws.
#
# This also answers, by measurement, whether the mismatch was downstream of
# the dead bulk-tap subsystem: it was not. All 286 plain-Match devices
# include every MOS, and every bulk terminal is on the same net on both
# sides.

CAP_TCL = """
proc pdkns::xx_cap_defaults {} {
    return {w 10 l 10 nx 1 ny 1 lmin 2.00 wmin 2.00 lmax 30.0 wmax 30.0 \\
\t\tclass capacitor doports 1}
}
proc pdkns::xx_res_defaults {} {
    return {w 0.5 l 2.0 wmin 0.50 lmin 0.50 class resistor doports 1}
}
"""


def _facts_with_maxima():
    f = A5E.PdkFacts()
    f.gencells = A5L.gencell_defaults(CAP_TCL, "/pdk/x-cap.tcl")
    return f


def test_j_the_gencell_states_both_ends_and_both_are_read():
    rec = A5L.gencell_defaults(CAP_TCL, "/pdk/x-cap.tcl")["xx_cap"]
    assert (rec["lmin"], rec["wmin"]) == (2.0, 2.0)
    assert (rec["lmax"], rec["wmax"]) == (30.0, 30.0)
    # AND A MAXIMUM THE PDK DOES NOT STATE IS ABSENT, never a default: the
    # resistor block above states neither, and nothing is checked against it.
    res = A5L.gencell_defaults(CAP_TCL, "/pdk/x-cap.tcl")["xx_res"]
    assert res["lmax"] is None and res["wmax"] is None


def test_j_a_device_above_the_stated_maximum_is_named_with_the_rule_and_file():
    facts = _facts_with_maxima()
    devs = [{"name": "ci1", "model": "xx_cap", "nets": [], "pars": {"w": 10.0, "l": 629.081}},
            {"name": "caz", "model": "xx_cap", "nets": [], "pars": {"w": 10.0, "l": 34.7452}}]
    hits = A5E.over_maxima(devs, facts)
    assert [h["device"] for h in hits] == ["ci1", "caz"]
    assert hits[0]["parameter"] == "l"
    assert hits[0]["pdk_maximum_um"] == 30.0
    assert hits[0]["requested_um"] == 629.081
    assert "/pdk/x-cap.tcl" in hits[0]["detail"], (
        "the record must name the FILE that stated the maximum")
    assert "CLAMPS" in hits[0]["detail"], (
        "and must say what the gencell actually does, which is not refuse")


def test_j_at_and_below_the_maximum_nothing_is_named():
    """THE CONTROL. The same devices, the same deck, sizes the PDK permits."""
    facts = _facts_with_maxima()
    devs = [{"name": "cs1", "model": "xx_cap", "nets": [], "pars": {"w": 10.0, "l": 3.47452}},
            {"name": "cedge", "model": "xx_cap", "nets": [], "pars": {"w": 30.0, "l": 30.0}}]
    assert A5E.over_maxima(devs, facts) == []


def test_j_a_model_with_no_stated_maximum_is_not_checked_against_one():
    """ABSENT is not zero and not infinity: a maximum the PDK does not state
    is one this program has nothing to say about."""
    facts = _facts_with_maxima()
    devs = [{"name": "r1", "model": "xx_res", "nets": [],
             "pars": {"w": 0.5, "l": 9999.0}}]
    assert A5E.over_maxima(devs, facts) == []


def test_j_a_clamped_device_is_blocking_and_a_short_still_is():
    devs = [{"quantity": A5E.OVER_MAXIMUM_QUANTITY, "detail": "x"},
            {"quantity": A5E.SHORT_QUANTITY, "detail": "y"},
            {"quantity": "metal2_space_to_device_lambda", "detail": "z"}]
    got = [d["quantity"] for d in A5E.blocking_deviations(devs)]
    assert got == [A5E.OVER_MAXIMUM_QUANTITY, A5E.SHORT_QUANTITY]
    # the older, narrower reader still answers about shorts only
    assert [d["quantity"] for d in A5E.blocking_shorts(devs)] == [A5E.SHORT_QUANTITY]


# Public authority excerpts from IHP-Open-PDK main on 2026-10-26.
# Full-file identities:
#   sg13g2_tech_default.json 07930b016cdffe14c2cb82b47fbec193643347607db6d44aa1abfdece056cd2f
#   beol/5_17_metaln.drc    0023b4dfc61eb71e14d2d4b3b003078d3f8121c732445ad80a9bca187279fb6e
# The excerpts retain the complete declarations and executable predicates
# consumed here; unrelated rules are deliberately not made into a test PDK.
PUBLIC_WIDTH_PRL_CONFIG = json.dumps({"drc_rules": {
    "Mn_e": 0.24, "Mn_e_w": 0.39, "Mn_e_cr": 1.0,
    "Mn_f": 0.6, "Mn_f_w": 10.0, "Mn_f_cr": 10.0,
}})
PUBLIC_WIDTH_PRL_DECK = """
mets_lay = [metal2_drw, metal3_drw, metal4_drw, metal5_drw]
mn_e_value = drc_rules['Mn_e'].to_f
mn_e_width = drc_rules['Mn_e_w'].to_f / 2
mn_e_length = drc_rules['Mn_e_cr'].to_f
mn_e_l1 = met_lay.sized(-1 * mn_e_width.um).sized(mn_e_width.um)
mn_e_l = met_lay.sep(mn_e_l1, mn_e_value.um, projection_limits(mn_e_length.um + 0.001.um, nil))
mn_f_value = drc_rules['Mn_f'].to_f
mn_f_width = drc_rules['Mn_f_w'].to_f / 2
mn_f_length = drc_rules['Mn_f_cr'].to_f
mn_f_l1 = met_lay.sized(-1 * mn_f_width.um).sized(mn_f_width.um)
mn_f_l = met_lay.sep(mn_f_l1, mn_f_value.um, projection_limits(mn_f_length.um + 0.001.um, nil))
"""


def _width_prl_geo():
    rules = A5L.deck_rules(SURROUND_TECH)
    rules["metal_width_spacing_um"] = {3: [
        {"source_rule": "Mn_e", "spacing_um": 0.24,
         "width_gt_um": 0.39, "parallel_gt_um": 1.0},
        {"source_rule": "Mn_f", "spacing_um": 0.6,
         "width_gt_um": 10.0, "parallel_gt_um": 10.0},
    ]}
    return A5E.Geo(rules, 0.21, 100, 0.30, 0.15)


def test_k_width_prl_rules_reach_the_existing_site_clearance_consumer():
    geo = _width_prl_geo()
    # Wide, 2um-parallel rectangles with a 0.22um gap clear the ordinary
    # 0.21um floor but violate Mn_e's source-declared 0.24um conditional.
    sites = A5E.Sites([
        {"net": "other", "layer": "metal3", "box": (82, 0, 142, 200)},
    ], geo)
    assert sites.clear((0, 0, 60, 200), ["metal3"], None, "mine") is False
    # The conditional distance itself is legal: spacing is a strict floor.
    boundary = A5E.Sites([
        {"net": "other", "layer": "metal3", "box": (84, 0, 144, 200)},
    ], geo)
    assert boundary.clear((0, 0, 60, 200), ["metal3"], None, "mine") is True
    # The public predicate says wider/more-than. Equality on either input
    # keeps the old unconditional floor, as does a genuinely narrow wire.
    width_equal = A5E.Sites([
        {"net": "other", "layer": "metal3", "box": (61, 0, 100, 200)},
    ], geo)
    assert width_equal.clear((0, 0, 39, 200), ["metal3"], None, "mine") is True
    prl_equal = A5E.Sites([
        {"net": "other", "layer": "metal3", "box": (82, 0, 142, 100)},
    ], geo)
    assert prl_equal.clear((0, 0, 60, 100), ["metal3"], None, "mine") is True
    assert geo.metal_space("metal3", (0, 0, 30, 2000),
                           (51, 0, 81, 2000)) == 21


def test_k_public_authority_is_parsed_and_changed_predicates_are_refused():
    rules = A5E._parse_width_prl_rules(
        PUBLIC_WIDTH_PRL_CONFIG, PUBLIC_WIDTH_PRL_DECK)
    assert sorted(rules) == [2, 3, 4, 5]
    assert rules[3][0] == {
        "source_rule": "Mn_e", "spacing_um": 0.24,
        "width_gt_um": 0.39, "parallel_gt_um": 1.0,
    }
    with pytest.raises(ValueError, match="unsupported native width/parallel predicate"):
        A5E._parse_width_prl_rules(
            PUBLIC_WIDTH_PRL_CONFIG,
            PUBLIC_WIDTH_PRL_DECK.replace("projection_limits", "changed_predicate"))
    with pytest.raises(ValueError, match="absent or invalid"):
        A5E._parse_width_prl_rules(json.dumps({"drc_rules": {}}),
                                  PUBLIC_WIDTH_PRL_DECK)


def test_l_public_result_binding_is_single_definition():
    rules = A5E._parse_width_prl_rules(
        PUBLIC_WIDTH_PRL_CONFIG, PUBLIC_WIDTH_PRL_DECK)
    assert rules[3][0] == {
        "source_rule": "Mn_e", "spacing_um": 0.24,
        "width_gt_um": 0.39, "parallel_gt_um": 1.0,
    }
    changed = PUBLIC_WIDTH_PRL_DECK + "\nmn_e_l = met_lay\n"
    accepted, observed = True, None
    try:
        observed = A5E._parse_width_prl_rules(PUBLIC_WIDTH_PRL_CONFIG, changed)
    except ValueError as exc:
        accepted, observed = False, str(exc)
    assert accepted is False, (
        f"changed native authority was accepted with rules={observed}")
    assert "reassigned: Mn_e" in observed


def test_k_missing_or_stale_runtime_authority_refuses_instead_of_guessing():
    config_path = "/pdk/libs.tech/klayout/tech/drc/rule_decks/sg13g2_tech_default.json"
    deck_path = "/pdk/libs.tech/klayout/tech/drc/rule_decks/beol/5_17_metaln.drc"

    class PayloadStage:
        def __init__(self, payload):
            self.payload = payload

        def sh(self, _command, timeout=120):
            return 0, json.dumps(self.payload), ""

    def item(text):
        return {"text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}

    valid = {config_path: item(PUBLIC_WIDTH_PRL_CONFIG),
             deck_path: item(PUBLIC_WIDTH_PRL_DECK)}
    got = A5E._read_width_prl_rules(PayloadStage(valid), "/pdk/libs.tech/magic/pdk.tech")
    assert got["status"] == "READ"
    missing = A5E._read_width_prl_rules(
        PayloadStage({config_path: item(PUBLIC_WIDTH_PRL_CONFIG)}),
        "/pdk/libs.tech/magic/pdk.tech")
    assert missing["status"] == "REFUSED" and "exactly one" in missing["detail"]
    stale = json.loads(json.dumps(valid))
    stale[deck_path]["sha256"] = "0" * 64
    refused = A5E._read_width_prl_rules(
        PayloadStage(stale), "/pdk/libs.tech/magic/pdk.tech")
    assert refused["status"] == "REFUSED" and "hash" in refused["detail"]


def test_k_read_pdk_propagates_conditional_authority_refusal(monkeypatch):
    monkeypatch.setattr(A5E, "_read_width_prl_rules", lambda *_args: {
        "status": "REFUSED", "rules": {}, "sources": {},
        "detail": "changed public predicate",
    })
    fixtures = importlib.import_module("test_analog_a5_layout_emit")
    facts, reason = A5E.read_pdk(
        fixtures.FakeStage(), "/pdk", "x",
        "/pdk/x-fet.tcl", "/pdk/x-drc.tech")
    assert facts is None
    assert "ENV_UNAVAILABLE" in reason
    assert "changed public predicate" in reason


def _compact_geo():
    rules = {
        "metal_space_um": {n: .21 for n in range(1, 8)},
        "metal_width_um": {n: .2 for n in range(1, 8)},
        "metal_area_um2": {2: .144, 3: .144},
        "via_width_um": {n: .2 for n in range(1, 7)},
        "via_space_um": {n: .21 for n in range(1, 7)},
        "via_surround_um": {},
        "via_surround_dir_um": {(2, 2): .045, (2, 3): .045},
        "metal_width_spacing_um": {},
    }
    return A5E.Geo(rules, .21, 100, .6, .35)


def _compact_groups():
    return [
        {"net": "drain", "y": 0, "escape_y": 0, "strapped": False,
         "labels": [{"x": -44, "y": 0, "level": 2}]},
        {"net": "source", "y": 0, "escape_y": 0, "strapped": False,
         "labels": [{"x": 44, "y": 0, "level": 2}]},
        {"net": "gate", "y": 222, "escape_y": 222, "strapped": False,
         "labels": [{"x": 0, "y": 222, "level": 2}]},
    ]


def test_l_compact_access_uses_source_width_and_records_external_flare():
    geo = _compact_geo()
    groups = _compact_groups()
    assert A5E._terminal_access_width(groups[0], groups, geo) == 20
    assert A5E._collect_close_plain_rows(groups, (-141, -305, 141, 305), geo)
    plan = A5E.Plan()
    dev = {"origin": (0, 0), "bbox": (-141, -305, 141, 305),
           "dev": {"name": "unit"}}
    group = dict(groups[0], access_width=20)
    A5E._paint_terminal_stub(plan, group, dev, -44, 0, -600, geo)
    record = plan.access_necks[0]
    assert record["requested_width_um"] == pytest.approx(.6)
    assert record["actual_width_um"] == pytest.approx(.2)
    assert record["source_minimum_width_um"] == pytest.approx(.2)
    assert plan.shapes[-1]["box"][3] <= -305 - geo.spacing_reach("metal3")


def test_m_compact_access_refuses_missing_width_authority():
    geo = _compact_geo()
    del geo.rules["metal_width_um"][3]
    groups = _compact_groups()
    with pytest.raises(A5E.Refusal, match="declares no metal3 minimum width"):
        A5E._terminal_access_width(groups[0], groups, geo)
    geo = _compact_geo()
    plan = A5E.Plan()
    dev = {"origin": (0, 0), "bbox": (-141, -305, 141, 305),
           "dev": {"name": "unit"}}
    with pytest.raises(A5E.Refusal, match="unsafe metal3 terminal neck width"):
        A5E._paint_terminal_stub(
            plan, dict(groups[0], access_width=19), dev, -44, 0, -600, geo)


def test_n_compact_access_refuses_a_colliding_fallback(monkeypatch):
    geo = _compact_geo()
    sites = A5E.Sites([], geo)
    monkeypatch.setattr(sites, "clear", lambda *args, **kwargs: False)
    monkeypatch.setattr(A5E, "_island_candidates", lambda span: iter([(0, 0)]))
    with pytest.raises(A5E.Refusal, match="colliding fallback island"):
        A5E._via_stack(A5E.Plan(), "drain", 0, 0, 2, geo, sites=sites,
                      compact_terminal=True)


def test_o_body_exit_selection_checks_the_emitted_jog(monkeypatch):
    geo = _compact_geo()
    sites = A5E.Sites([], geo)
    sites.add({"net": "other", "layer": "metal3",
               "box": (-150, -50, -130, 50)})
    monkeypatch.setattr(A5E, "_island_candidates",
                        lambda span: iter([(0, 0), (-240, 0)]))
    plan = A5E.Plan()
    assert A5E._via_stack(plan, "body", 0, 0, 2, geo, sites=sites,
                         exit_path=(-500, 0, 30)) == (-240, 0)
    assert not plan.deviations


def test_p_build_plan_consumes_compact_access_without_short(monkeypatch):
    dev = {"name": "unit", "model": "native_mos", "class": "mosfet",
           "nets": ["drain", "gate", "source", "body"],
           "pars": {"w": .5, "l": .5, "m": 1}}
    cell = A5E.parse_cell("""magic
magscale 1 1
<< metal1 >>
rect -120 -94 120 -74
rect -120 74 120 94
rect -120 -74 -100 74
rect 100 -74 120 74
<< metal2 >>
rect -54 -22 -34 22
rect 34 -22 54 22
rect -14 32 14 62
<< labels >>
rlabel metal2 -44 0 -44 0 0 D
rlabel metal2 44 0 44 0 0 S
rlabel metal2 0 47 0 47 0 G
rlabel metal1 0 -84 0 -84 0 B
<< end >>
""")
    cell.update(bbox=(-141, -130, 141, 130), delta=(141, 130))
    facts = SimpleNamespace(layers=None, gencells={"native_mos": {
        "namespace": "provider", "params": ["w", "l", "m", "guard"]}})
    monkeypatch.setattr(A5E, "ring_layer_of", lambda _cell: "metal1")
    monkeypatch.setattr(A5E, "body_tap_direct_m1_layer", lambda *_args: "metal1")
    monkeypatch.setattr(A5E, "choose_tap", lambda *_args: (-80, -84, 100, False))
    plan = A5E.build_plan([dev], dev["nets"],
                          {A5E.config_key(dev): cell}, facts,
                          _compact_geo(), 0)
    assert plan.access_necks
    assert all(r["source_minimum_width_um"] == pytest.approx(.2)
               for r in plan.access_necks)
    shapes = [r for r in plan.shapes if r["layer"] in ("metal2", "metal3")]
    violations = []
    for i, left in enumerate(shapes):
        for right in shapes[i + 1:]:
            if left["net"] == right["net"] or left["layer"] != right["layer"]:
                continue
            a, b = left["box"], right["box"]
            dx = max(a[0] - b[2], b[0] - a[2], 0)
            dy = max(a[1] - b[3], b[1] - a[3], 0)
            spacing = _compact_geo().metal_space(left["layer"], a, b)
            if dx < spacing and dy < spacing:
                violations.append((left, right, dx, dy))
    assert not violations


def test_q_compact_reduced_island_must_meet_joined_metal_area(monkeypatch):
    geo = _compact_geo()
    row = {"net": "<device unit>", "layer": "metal2",
           "box": (-10, -22, 10, 22), "comp": ("unit", 1),
           "lcomp": ("unit", "metal2", 1)}
    sites = A5E.Sites([row], geo)
    monkeypatch.setattr(
        sites, "clear",
        lambda box, *args: box[2] - box[0] == box[3] - box[1] == 22)
    plan = A5E.Plan()
    A5E._via_stack(plan, "signal", 0, 0, 2, geo, sites=sites,
                  friendly=("unit", 1))
    assert any(d["quantity"] == "via_island_clearance_lambda"
               for d in plan.deviations)


def test_multifinger_singleton_escape_stays_clear_of_collected_drains(monkeypatch):
    dev = {"name": "unit", "model": "native_mos", "class": "mosfet",
           "nets": ["drain", "gate", "source", "body"],
           "pars": {"w": 16, "l": .5, "ng": 2}}
    cell = A5E.parse_cell("""magic
magscale 1 1
<< metal1 >>
rect -139 -459 139 -439
rect -139 439 139 459
rect -139 -439 -119 439
rect 119 -439 139 439
<< metal2 >>
rect -98 -22 -78 22
rect 78 -22 98 22
rect -10 -22 10 22
rect -54 407 -34 437
rect 34 407 54 437
<< labels >>
rlabel metal2 -88 0 -88 0 0 D0
rlabel metal2 88 0 88 0 0 D1
rlabel metal2 0 0 0 0 0 S1
rlabel metal2 -44 422 -44 422 0 G0
rlabel metal2 44 422 44 422 0 G1
rlabel metal1 -129 -449 -129 -449 0 B
<< end >>
""")
    cell.update(bbox=(-139, -459, 139, 459), delta=(139, 459))
    facts = SimpleNamespace(layers=None, gencells={"native_mos": {
        "namespace": "provider", "params": ["w", "l", "m", "ng", "guard"]}})
    monkeypatch.setattr(A5E, "ring_layer_of", lambda _cell: "metal1")
    monkeypatch.setattr(A5E, "body_tap_direct_m1_layer", lambda *_args: "metal1")
    monkeypatch.setattr(A5E, "choose_tap", lambda *_args: (-129, -449, 100, True))
    rules = _compact_geo().rules
    geo = A5E.Geo(rules, .21, 100, .3, .15)
    plan = A5E.build_plan([dev], dev["nets"],
                          {A5E.config_key(dev): cell}, facts, geo, 0)
    assert not A5E.net_shorts(plan)


def test_all_collected_multifinger_rows_leave_the_device_outward():
    rules = _compact_geo().rules
    rules['metal_width_um'][3] = .24
    geo = A5E.Geo(rules, .21, 100, .3, .15)
    bbox = (-229, -505, 229, 505)
    groups = [
        {'net': 'drain', 'y': 0, 'escape_y': 574, 'strapped': True,
         'labels': [{'x': x, 'y': 0, 'level': 2} for x in (-132, 44)]},
        {'net': 'source', 'y': 0, 'escape_y': -643, 'strapped': True,
         'labels': [{'x': x, 'y': 0, 'level': 2} for x in (-44, 132)]},
        {'net': 'gate', 'y': 422, 'escape_y': -574, 'strapped': True,
         'labels': [{'x': x, 'y': 422, 'level': 2} for x in (-88, 0, 88)]},
    ]
    assert A5E._collect_close_plain_rows(groups, bbox, geo)
    assert groups[2]['escape_y'] > bbox[3]
    assert all(group['escape_y'] < bbox[1] for group in groups[:2])
    assert abs(groups[0]['escape_y'] - groups[1]['escape_y']) >= geo.pitch()
