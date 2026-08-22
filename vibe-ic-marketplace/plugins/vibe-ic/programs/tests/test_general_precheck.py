#!/usr/bin/env python3
"""The general tape-out precheck — the route with no operator to refuse it.

WHAT THIS FILE PINS
-------------------
G1  the GDSII reader reports what is IN the stream: database unit, top cells,
    a FLATTENED bounding box with SREF/AREF transforms applied, and exact
    zero-area polygons. Every fixture below is a REAL GDSII byte stream this
    file writes; nothing here is mocked, because a reader tested against a mock
    is a reader tested against our own idea of the format.
G2  THE ORIGIN CHECK DISCRIMINATES, in BOTH directions. The same bytes PASS as
    a HARDMACRO and FAIL as a DIE, and a die drawn at the origin passes while
    one drawn off it fails. A check that cannot fail proves nothing, and one
    that fails on everything proves just as little.
G3  the origin defect is caught in its REAL published shape — geometry pulled
    off the origin not by the top cell's own polygons but by origin-CENTRED
    cells placed at y=0, which is what `u_hawaii_adc`'s streamed `ldo.gds`
    does. Reading only the top cell's own XY records would have reported an
    origin that was fine.
G4  every unanswered declaration question produces NOT_DETERMINED at the check
    that needed it, naming the question — never a pass, and never a default.
G5  a zero-polygon layout is NOT a clean one. The denominator is the only thing
    that tells "0 violations out of 9976" from "0 violations out of 0".
G6  DELEGATION reports the delegate's rc and never re-derives its rule. rc 2 is
    NOT_DETERMINED, not the repo-wide `VACUOUS_PASS`.
G7  the two OPERATOR-SPECIFIC ladder steps are excluded and NAMED, so a reader
    comparing this report against the shuttle one can see the difference is
    deliberate.
G8  the three router files are mutually exclusive, the OPERATOR's answer wins,
    and a tree carrying two at once is REFUSED rather than resolved.
G9  the declaration refuses MALFORMED and passes UNANSWERED — the distinction
    the whole design rests on.
"""
import json
import struct
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _gds_geometry as GEOM              # noqa: E402
import _tapeout_declaration as TD         # noqa: E402
import general_precheck as GP             # noqa: E402
import tapeout_declaration_check as TDC   # noqa: E402
import tapeout_declaration_gen as TDG     # noqa: E402


# --------------------------------------------------------------------------- #
# A minimal GDSII WRITER, so every fixture is a real stream.
#
# The reader under test must not be fed a dict that we also built. It is fed
# bytes in the format, produced by an independent encoder written from the
# record layout — which is the only way a round-trip proves anything about the
# decoder.
# --------------------------------------------------------------------------- #
def _rec(rtype: int, dtype: int, payload: bytes = b"") -> bytes:
    if len(payload) % 2:
        payload += b"\x00"
    return struct.pack(">HBB", len(payload) + 4, rtype, dtype) + payload


def _real8(value: float) -> bytes:
    """GDSII excess-64 base-16 real. Written, not copied from the reader."""
    if value == 0:
        return b"\x00" * 8
    sign = 0x80 if value < 0 else 0x00
    value = abs(value)
    exponent = 0
    while value >= 1.0:
        value /= 16.0
        exponent += 1
    while value < 1.0 / 16.0:
        value *= 16.0
        exponent -= 1
    mantissa = int(round(value * (1 << 56)))
    if mantissa >= (1 << 56):                       # rounded up past the top
        mantissa >>= 4
        exponent += 1
    return bytes([sign | (exponent + 64)]) + mantissa.to_bytes(7, "big")


def _ascii(text: str) -> bytes:
    raw = text.encode("ascii")
    return raw + (b"\x00" if len(raw) % 2 else b"")


def _xy(points) -> bytes:
    flat = []
    for x, y in points:
        flat += [int(x), int(y)]
    return struct.pack(f">{len(flat)}i", *flat)


def write_gds(path: Path, cells, dbu_meters: float = 1e-9,
              user_per_dbu: float = 1e-3) -> Path:
    """`cells` = {name: {"boundaries": [(layer, dt, [(x,y), ...])],
                         "srefs": [(name, x, y)]}} in database units."""
    out = bytearray()
    out += _rec(0x00, 0x02, struct.pack(">h", 600))              # HEADER
    out += _rec(0x01, 0x02, struct.pack(">12h", *([0] * 12)))    # BGNLIB
    out += _rec(0x02, 0x06, _ascii("TESTLIB"))                   # LIBNAME
    out += _rec(0x03, 0x05, _real8(user_per_dbu) + _real8(dbu_meters))
    for name, body in cells.items():
        out += _rec(0x05, 0x02, struct.pack(">12h", *([0] * 12)))  # BGNSTR
        out += _rec(0x06, 0x06, _ascii(name))                     # STRNAME
        for layer, dtype, pts in body.get("boundaries", ()):
            out += _rec(0x08, 0x00)                               # BOUNDARY
            out += _rec(0x0D, 0x02, struct.pack(">h", layer))     # LAYER
            out += _rec(0x0E, 0x02, struct.pack(">h", dtype))     # DATATYPE
            out += _rec(0x10, 0x03, _xy(pts))                     # XY
            out += _rec(0x11, 0x00)                               # ENDEL
        for sname, x, y in body.get("srefs", ()):
            out += _rec(0x0A, 0x00)                               # SREF
            out += _rec(0x12, 0x06, _ascii(sname))                # SNAME
            out += _rec(0x10, 0x03, _xy([(x, y)]))                # XY
            out += _rec(0x11, 0x00)                               # ENDEL
        out += _rec(0x07, 0x00)                                   # ENDSTR
    out += _rec(0x04, 0x00)                                       # ENDLIB
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def _die_at_origin(path: Path, w=100_000, h=80_000) -> Path:
    """A well-formed die: one top cell, lower-left exactly at (0,0)."""
    return write_gds(path, {"chip_top": {
        "boundaries": [(67, 20, _rect(0, 0, w, h))]}})


def _die_off_origin_via_children(path: Path) -> Path:
    """G3 — the REAL published shape of the defect.

    The top cell's own geometry sits in the first quadrant. The negative extent
    comes entirely from a child cell that is ORIGIN-CENTRED by its generator's
    convention and is placed at y=0 — exactly what `u_hawaii_adc`'s streamed
    `ldo.gds` does, where a 446.61 um resistor centred on its own origin drags
    the flattened box to y = -223.305 um.

    A reader that looked only at the top cell's own XY records would report a
    lower-left of (0, 0) here and see nothing wrong.
    """
    return write_gds(path, {
        "dev_centred": {"boundaries": [(67, 20, _rect(-1480, -223_305,
                                                      1480, 223_305))]},
        "chip_top": {
            "boundaries": [(67, 20, _rect(0, 0, 100_000, 80_000))],
            "srefs": [("dev_centred", 307_975, 0)]},
    })


# --------------------------------------------------------------------------- #
# G1 — the reader reports what is in the stream
# --------------------------------------------------------------------------- #
def test_g1_reader_reports_units_tops_and_bbox(tmp_path):
    gds = _die_at_origin(tmp_path / "chip_top.gds")
    lay = GEOM.read_layout(gds)
    assert lay.dbu_um == pytest.approx(0.001)
    assert lay.top_cells() == ["chip_top"]
    doc = GEOM.summarise(lay)
    assert doc["bbox_dbu"] == [0, 0, 100_000, 80_000]
    assert doc["bbox_um"] == pytest.approx([0.0, 0.0, 100.0, 80.0])
    assert doc["width_um"] == pytest.approx(100.0)
    assert doc["polygon_count"] == 1
    assert doc["zero_area_polygon_count"] == 0


def test_g1_reader_refuses_a_file_that_is_not_gdsii(tmp_path):
    bad = tmp_path / "not.gds"
    bad.write_bytes(b"this is not a GDSII stream at all, not even close")
    with pytest.raises(GEOM.GdsError):
        GEOM.read_layout(bad)


def test_g1_reader_refuses_oasis_rather_than_half_parsing_it(tmp_path):
    oas = tmp_path / "chip.oas"
    oas.write_bytes(b"%SEMI-OASIS\r\n")
    with pytest.raises(GEOM.GdsError) as exc:
        GEOM.read_layout(oas)
    # An empty, clean-looking result from a half-parsed container is the exact
    # failure this refusal exists to prevent, so the reason has to say so.
    assert "OASIS" in str(exc.value)


def test_g1_bbox_resolves_a_reference_and_is_not_the_top_cells_own_extent(tmp_path):
    gds = _die_off_origin_via_children(tmp_path / "chip_top.gds")
    lay = GEOM.read_layout(gds)
    own = [p for e in lay.cells["chip_top"].own_area_elements() for p in e.xy]
    assert min(y for _x, y in own) == 0            # the top cell alone is fine
    doc = GEOM.summarise(lay)
    assert doc["bbox_dbu"][1] == pytest.approx(-223_305)   # the child is not


def test_g1_a_reference_cycle_is_a_datum_not_a_crash(tmp_path):
    gds = write_gds(tmp_path / "loop.gds", {
        "a": {"boundaries": [(67, 20, _rect(0, 0, 10, 10))],
              "srefs": [("b", 0, 0)]},
        "b": {"srefs": [("a", 0, 0)]},
    })
    lay = GEOM.read_layout(gds)
    res = GEOM.flattened_bbox(lay, "a")
    assert res.cycles, "a self-referential hierarchy must be REPORTED"
    assert res.complete is False


# --------------------------------------------------------------------------- #
# G2 / G3 — THE ORIGIN CHECK, in both directions
# --------------------------------------------------------------------------- #
def _project(tmp_path: Path, gds_maker, answers: dict) -> Path:
    proj = tmp_path / "proj"
    gds_maker(proj / "phase3" / "stage4" / "gds" / "chip_top.gds")
    doc, ignored = TD.merge_answers(TD.blank_declaration(), answers)
    assert not ignored, f"test wrote an unknown answer key: {ignored}"
    p = proj / TD.DECLARATION_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2))
    return proj


def _step(rep, step_id):
    return next(s for s in rep.steps if s.step_id == step_id)


_NEVER_RAN = lambda cmd, timeout: (2, "", "no tool here")   # noqa: E731


def test_g2_a_die_drawn_at_the_origin_passes_checksize(tmp_path):
    proj = _project(tmp_path, _die_at_origin, {
        "deliverable": "DIE", "top_cell": "chip_top",
        "die_origin_um": [0, 0], "die_area_um": [0, 0, 100.0, 80.0],
        "database_unit_um": 0.001})
    rep = GP.evaluate(proj, runner=_NEVER_RAN)
    assert _step(rep, "KLayout.CheckSize").verdict == GP.PASS


def test_g2_the_same_die_drawn_off_the_origin_fails_checksize(tmp_path):
    proj = _project(tmp_path, _die_off_origin_via_children, {
        "deliverable": "DIE", "top_cell": "chip_top",
        "die_origin_um": [0, 0], "database_unit_um": 0.001})
    rep = GP.evaluate(proj, runner=_NEVER_RAN)
    ev = _step(rep, "KLayout.CheckSize")
    assert ev.verdict == GP.FAIL
    assert "-223.305" in ev.evidence
    assert rep.verdict == GP.FAIL


def test_g2_the_same_bytes_pass_as_a_hardmacro_and_fail_as_a_die(tmp_path):
    """The one comparison that shows the check is not a filter on the file.

    This is the published `u_hawaii_adc` case in miniature: the streamed
    `ldo.gds` is byte-identical to the analog hardmacro's own GDS, and its LEF
    DECLARES the offset (`ORIGIN 4.500 223.305 ; SIZE 332.580 BY 463.415`),
    matching the measured box to the micron. Legal for a macro. Not legal for a
    die. What differs is the DECLARATION, and so is the verdict.
    """
    as_die = _project(tmp_path / "d", _die_off_origin_via_children, {
        "deliverable": "DIE", "top_cell": "chip_top",
        "die_origin_um": [0, 0], "database_unit_um": 0.001})
    as_macro = _project(tmp_path / "m", _die_off_origin_via_children, {
        "deliverable": "HARDMACRO", "top_cell": "chip_top",
        "database_unit_um": 0.001})
    die_gds = (as_die / "phase3/stage4/gds/chip_top.gds").read_bytes()
    macro_gds = (as_macro / "phase3/stage4/gds/chip_top.gds").read_bytes()
    assert die_gds == macro_gds, "the two fixtures must be the same bytes"

    assert _step(GP.evaluate(as_die, runner=_NEVER_RAN),
                 "KLayout.CheckSize").verdict == GP.FAIL
    assert _step(GP.evaluate(as_macro, runner=_NEVER_RAN),
                 "KLayout.CheckSize").verdict == GP.PASS


def test_g2_a_declared_die_size_that_does_not_match_is_refused(tmp_path):
    proj = _project(tmp_path, _die_at_origin, {
        "deliverable": "DIE", "top_cell": "chip_top",
        "die_origin_um": [0, 0], "die_area_um": [0, 0, 999.0, 999.0],
        "database_unit_um": 0.001})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN), "KLayout.CheckSize")
    assert ev.verdict == GP.FAIL
    assert "999" in ev.evidence


def test_g2_the_top_cell_name_is_compared_against_the_declaration(tmp_path):
    proj = _project(tmp_path, _die_at_origin, {
        "deliverable": "DIE", "top_cell": "some_other_name",
        "die_origin_um": [0, 0], "database_unit_um": 0.001})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN), "KLayout.CheckTopLevel")
    assert ev.verdict == GP.FAIL
    assert "some_other_name" in ev.evidence


def test_g2_two_top_level_cells_are_refused(tmp_path):
    proj = tmp_path / "proj"
    write_gds(proj / "phase3/stage4/gds/chip_top.gds", {
        "chip_top": {"boundaries": [(67, 20, _rect(0, 0, 100, 100))]},
        "orphan": {"boundaries": [(67, 20, _rect(0, 0, 10, 10))]},
    })
    doc, _ = TD.merge_answers(TD.blank_declaration(),
                              {"deliverable": "DIE", "top_cell": "chip_top"})
    p = proj / TD.DECLARATION_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc))
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN), "KLayout.CheckTopLevel")
    assert ev.verdict == GP.FAIL
    assert "2 top-level cell" in ev.evidence


# --------------------------------------------------------------------------- #
# G4 — an unanswered question is NOT_DETERMINED at the check that needed it
# --------------------------------------------------------------------------- #
def test_g4_no_declaration_at_all_is_not_determined_never_a_pass(tmp_path):
    proj = tmp_path / "proj"
    _die_at_origin(proj / "phase3/stage4/gds/chip_top.gds")
    rep = GP.evaluate(proj, runner=_NEVER_RAN)
    assert rep.verdict == GP.NOT_DETERMINED
    assert _step(rep, "KLayout.CheckSize").verdict == GP.NOT_DETERMINED
    assert rep.declaration_present is False
    # It must name WHICH answer it went without, not just that it went without.
    assert "deliverable" in _step(rep, "KLayout.CheckSize").evidence


def test_g4_an_undeclared_deliverable_concludes_nothing_about_the_origin(tmp_path):
    proj = _project(tmp_path, _die_off_origin_via_children,
                    {"top_cell": "chip_top", "database_unit_um": 0.001})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN), "KLayout.CheckSize")
    assert ev.verdict == GP.NOT_DETERMINED
    assert "HARDMACRO" in ev.evidence and "DIE" in ev.evidence


def test_g4_a_wrong_database_unit_is_a_refusal(tmp_path):
    proj = _project(tmp_path, _die_at_origin, {
        "deliverable": "DIE", "top_cell": "chip_top",
        "die_origin_um": [0, 0], "database_unit_um": 0.005})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN), "General.DatabaseUnit")
    assert ev.verdict == GP.FAIL
    assert "wrong grid" in ev.evidence


def test_g4_forbidden_layers_needs_a_declaration_and_then_bites(tmp_path):
    silent = _project(tmp_path / "a", _die_at_origin,
                      {"deliverable": "DIE", "top_cell": "chip_top"})
    ev = _step(GP.evaluate(silent, runner=_NEVER_RAN),
               "General.ForbiddenLayers")
    assert ev.verdict == GP.NOT_DETERMINED

    banned = _project(tmp_path / "b", _die_at_origin,
                      {"deliverable": "DIE", "top_cell": "chip_top",
                       "forbidden_layers": ["67/20"]})
    ev = _step(GP.evaluate(banned, runner=_NEVER_RAN),
               "General.ForbiddenLayers")
    assert ev.verdict == GP.FAIL and "67/20" in ev.evidence


# --------------------------------------------------------------------------- #
# G5 — the denominator
# --------------------------------------------------------------------------- #
def test_g5_zero_violations_over_zero_polygons_is_not_a_pass(tmp_path):
    proj = tmp_path / "proj"
    write_gds(proj / "phase3/stage4/gds/chip_top.gds", {"chip_top": {}})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN),
               "Checker.KLayoutZeroAreaPolygons")
    assert ev.verdict == GP.NOT_DETERMINED
    assert "0 polygons" in ev.evidence


def test_g5_a_degenerate_polygon_is_found_exactly(tmp_path):
    proj = tmp_path / "proj"
    write_gds(proj / "phase3/stage4/gds/chip_top.gds", {"chip_top": {
        "boundaries": [
            (67, 20, _rect(0, 0, 100, 100)),          # real
            (67, 20, [(0, 0), (50, 0), (100, 0), (0, 0)]),   # collinear
        ]}})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN),
               "Checker.KLayoutZeroAreaPolygons")
    assert ev.verdict == GP.FAIL
    assert ev.measured["zero_area_polygon_count"] == 1
    assert ev.measured["polygon_count"] == 2       # the denominator is stated


def test_g5_the_summary_line_always_states_the_denominator(tmp_path):
    proj = _project(tmp_path, _die_at_origin,
                    {"deliverable": "DIE", "top_cell": "chip_top"})
    line = GP.evaluate(proj, runner=_NEVER_RAN).summary_line()
    for token in ("layouts_found=", "ladder_steps_required=",
                  "steps_with_evidence=", "declaration_answered="):
        assert token in line


def test_g5_a_project_with_no_layout_refuses_over_the_empty_set(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    rep = GP.evaluate(proj, runner=_NEVER_RAN)
    assert rep.verdict == GP.NOT_DETERMINED
    assert rep.layouts_found == 0
    assert len(rep.undetermined_steps) == len(GP.LADDER)


# --------------------------------------------------------------------------- #
# G6 — delegation reports the delegate's rc, and never re-derives its rule
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rc,expected", [
    (0, GP.PASS),
    (1, GP.FAIL),
    (2, GP.NOT_DETERMINED),      # NOT the repo-wide VACUOUS_PASS
    (124, GP.NOT_DETERMINED),
])
def test_g6_delegated_rc_maps_to_the_verdict(tmp_path, rc, expected):
    proj = _project(tmp_path, _die_at_origin,
                    {"deliverable": "DIE", "top_cell": "chip_top"})
    rep = GP.evaluate(proj, runner=lambda cmd, t: (rc, "out", "err"))
    assert _step(rep, "Checker.MagicDRC").verdict == expected


def test_g6_no_rule_deck_literal_lives_in_this_program():
    """The delegated half must contain no rule of its own.

    A density window, an antenna ratio or a DRC spacing copied in here would be
    OURS — editable, and able to drift into passing — which is the exact
    property that makes the operator's container stronger than anything we
    write. So the source is checked for the shape of such a constant.
    """
    text = (PROGRAMS / "general_precheck.py").read_text()
    for banned in ("min_density", "max_density", "antenna_ratio",
                   "MIN_DENSITY", "MAX_DENSITY", "spacing_um"):
        assert banned not in text, f"a PDK rule leaked into the assembly: {banned}"


def test_g6_a_missing_delegate_is_not_determined_not_a_pass(tmp_path):
    proj = _project(tmp_path, _die_at_origin,
                    {"deliverable": "DIE", "top_cell": "chip_top"})
    rep = GP.evaluate(proj, runner=_NEVER_RAN, programs_dir=tmp_path / "empty")
    ev = _step(rep, "Checker.KLayoutDRC")
    assert ev.verdict == GP.NOT_DETERMINED
    assert "does not exist" in ev.evidence


def test_g6_a_seal_ring_declared_away_is_not_checked_and_says_so(tmp_path):
    proj = _project(tmp_path, _die_at_origin,
                    {"deliverable": "DIE", "top_cell": "chip_top",
                     "seal_ring_required": False})
    ev = _step(GP.evaluate(proj, runner=_NEVER_RAN), "General.SealRing")
    assert ev.verdict == GP.NOT_DETERMINED
    assert "not the same as checked-and-clean" in ev.evidence


# --------------------------------------------------------------------------- #
# G7 — the operator-specific steps are excluded and NAMED
# --------------------------------------------------------------------------- #
def test_g7_the_two_operator_specific_steps_are_out_and_named(tmp_path):
    proj = _project(tmp_path, _die_at_origin,
                    {"deliverable": "DIE", "top_cell": "chip_top"})
    rep = GP.evaluate(proj, runner=_NEVER_RAN)
    ids = {s.step_id for s in rep.steps}
    assert "KLayout.CheckPadMask" not in ids
    assert "KLayout.GenerateID" not in ids
    excluded = {e["step_id"] for e in rep.operator_specific_excluded}
    assert excluded == {"KLayout.CheckPadMask", "KLayout.GenerateID"}
    for e in rep.operator_specific_excluded:
        assert len(e["reason"]) > 60, "a silent exclusion is the defect"


def test_g7_this_route_does_not_weaken_the_shuttle_route():
    """37.5ic's verdict must stay the one we did not write.

    The general precheck must not be reachable from a project that has an
    operator template: `route_of` gives the OPERATOR's answer priority over
    anything the design declares about itself.
    """
    doc, _ = TD.merge_answers(TD.blank_declaration(), {"deliverable": "DIE"})
    assert TD.route_of(doc, has_slots=True) == TD.ROUTE_SHUTTLE
    assert TD.route_of(doc, has_slots=False) == TD.ROUTE_SELF_TAPEOUT


# --------------------------------------------------------------------------- #
# G8 — the three routes
# --------------------------------------------------------------------------- #
def test_g8_no_answers_writes_a_blank_declaration_and_routes_nowhere(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    assert TDG.main([str(proj)]) == 0
    doc = json.loads((proj / TD.DECLARATION_REL).read_text())
    assert set(doc["answers"].values()) == {TD.NOT_DETERMINED}
    assert not (proj / TD.SELF_TAPEOUT_REL).exists()
    assert TDC.main([str(proj)]) == 0        # unanswered is not malformed


def test_g8_declaring_a_die_selects_the_self_tapeout_route(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    ans = proj / "answers.json"
    ans.write_text(json.dumps({"deliverable": "DIE", "top_cell": "chip_top"}))
    assert TDG.main([str(proj), "--answers", str(ans)]) == 0
    assert (proj / TD.SELF_TAPEOUT_REL).is_file()
    assert TDC.main([str(proj)]) == 0


def test_g8_two_router_files_at_once_are_refused_not_resolved(tmp_path):
    import _submission_template as ST
    proj = tmp_path / "proj"
    (proj / "input/submission_template").mkdir(parents=True)
    ans = proj / "answers.json"
    ans.write_text(json.dumps({"deliverable": "DIE"}))
    TDG.main([str(proj), "--answers", str(ans)])       # writes SELF_TAPEOUT
    # A NO_TEMPLATE.txt this flow did NOT write appears beside it. The tree now
    # selects two terminals at once, and `files_exist` cannot express "and not".
    (proj / ST.NO_TEMPLATE_REL).write_text("# not ours\nsomething\n")
    res = TDC.evaluate(proj)
    assert res["verdict"] == "FAIL"
    assert any(r["rule"] == TDC.RULE_ROUTER_CONTRADICTION
               for r in res["refusals"])
    # REFUSED, never resolved: the evidence of how the tree got here stays.
    assert (proj / ST.NO_TEMPLATE_REL).is_file()
    assert (proj / TD.SELF_TAPEOUT_REL).is_file()


def test_g8_a_die_retires_only_a_marker_this_flow_itself_wrote(tmp_path):
    import _submission_template as ST
    proj = tmp_path / "proj"
    (proj / "input/submission_template").mkdir(parents=True)
    (proj / ST.NO_TEMPLATE_REL).write_text(ST.NO_TEMPLATE_MARKER + "\nstale\n")
    ans = proj / "answers.json"
    ans.write_text(json.dumps({"deliverable": "DIE"}))
    TDG.main([str(proj), "--answers", str(ans)])
    assert not (proj / ST.NO_TEMPLATE_REL).exists()   # ours, retired

    (proj / ST.NO_TEMPLATE_REL).write_text("# somebody else\n")
    TDG.main([str(proj), "--answers", str(ans)])
    assert (proj / ST.NO_TEMPLATE_REL).is_file()      # theirs, untouched


# --------------------------------------------------------------------------- #
# G9 — the declaration: 18 questions, malformed refused, unanswered passed
# --------------------------------------------------------------------------- #
def test_g9_there_are_exactly_eighteen_questions_in_three_sections():
    assert len(TD.QUESTIONS) == 18
    assert TD.SECTION_COUNTS == {"2A_die_size": 7, "2B_pad_ring": 8,
                                 "2C_seal_ring": 3}
    audit = TD.audit(TD.blank_declaration())
    assert audit["questions_total"] == 18
    assert audit["answered"] == 0 and audit["unanswered"] == 18


def test_g9_a_blank_declaration_holds_no_value_that_is_not_the_sentinel():
    """The one property a default could hide behind. Checked exhaustively."""
    doc = TD.blank_declaration()
    for key, value in doc["answers"].items():
        assert value == TD.NOT_DETERMINED, f"{key} was defaulted to {value!r}"
    assert doc[TD.FORBIDDEN_LAYERS_KEY] == TD.NOT_DETERMINED
    assert TD.validate(doc) == [], "a blank declaration is not malformed"


def test_g9_the_sentinel_cannot_be_used_to_answer_a_question():
    doc, _ = TD.merge_answers(TD.blank_declaration(),
                              {"top_cell": TD.NOT_DETERMINED})
    assert TD.answer(doc, "top_cell") == TD.NOT_DETERMINED
    assert TD.audit(doc)["answered"] == 0


@pytest.mark.parametrize("answers,rule", [
    ({"deliverable": "CHIP"}, TD.RULE_ENUM_INVALID),
    ({"die_area_um": [0, 0, 10]}, TD.RULE_RECT_INVALID),
    ({"die_area_um": [10, 10, 10, 20]}, TD.RULE_RECT_INVALID),   # degenerate
    ({"die_origin_um": [0]}, TD.RULE_POINT_INVALID),
    ({"database_unit_um": 0}, TD.RULE_NUMBER_INVALID),
    ({"database_unit_um": -1}, TD.RULE_NUMBER_INVALID),
])
def test_g9_malformed_answers_are_refused(answers, rule):
    doc = TD.blank_declaration()
    doc["answers"].update(answers)          # bypass merge: this IS the mutation
    assert rule in [r["rule"] for r in TD.validate(doc)]


def test_g9_a_question_that_is_absent_is_malformed_not_unanswered():
    doc = TD.blank_declaration()
    del doc["answers"]["die_area_um"]
    rules = [r["rule"] for r in TD.validate(doc)]
    assert TD.RULE_FIELD_MISSING in rules


def test_g9_an_unknown_answer_key_is_never_written_through():
    doc, ignored = TD.merge_answers(TD.blank_declaration(),
                                    {"die_are_um": [0, 0, 1, 1]})
    assert ignored == ["die_are_um"]
    assert "die_are_um" not in doc["answers"]
    assert TD.answer(doc, "die_area_um") == TD.NOT_DETERMINED


def test_g9_every_question_names_a_consumer_that_exists():
    """A question nobody reads is carried forever because it once seemed sensible."""
    for q in TD.QUESTIONS:
        assert (PROGRAMS / f"{q.consumer}.py").is_file(), \
            f"{q.key} names consumer {q.consumer!r}, which does not exist"


def test_g9_a_hardmacro_owes_fewer_answers_and_the_report_says_which():
    doc, _ = TD.merge_answers(TD.blank_declaration(),
                              {"deliverable": "HARDMACRO"})
    audit = TD.audit(doc)
    assert audit["not_applicable"] > 0
    na = audit["sections"]["2B_pad_ring"]["not_applicable_keys"]
    assert len(na) == 8, "an IP has no pad ring, and that is stated not implied"


def test_g9_a_malformed_declaration_leaves_every_declared_step_undetermined(tmp_path):
    proj = tmp_path / "proj"
    _die_at_origin(proj / "phase3/stage4/gds/chip_top.gds")
    p = proj / TD.DECLARATION_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"schema": "vibe-ic/tapeout_declaration/1", "answers": {}}')
    rep = GP.evaluate(proj, runner=_NEVER_RAN)
    assert rep.declaration_refusals, "a declaration with no questions is malformed"
    # Half-reading it would be worse than not reading it.
    assert _step(rep, "KLayout.CheckSize").verdict == GP.NOT_DETERMINED


# --------------------------------------------------------------------------- #
# G10 — THIS LADDER DOES NOT WRITE OVER THE FLOW'S OWN ARTEFACTS
#
# Every DELEGATED step re-RUNS an in-tree checker and gives it a `--json`
# target. Until `DELEGATE_REPORT_DIR` existed those targets WERE the flow's
# canonical report paths, so a precheck run replaced four sign-off artefacts it
# does not own with the output of a weaker invocation — MEASURED on
# `reports/phase3/drc_signoff.json`, where step 31 passes `--signoff --under
# reports/phase3/drc_signoff.rpt` and this ladder passes neither, and the two
# JSONs differ (811 B with `summary.scoped_under` vs 308 B without it).
# `signoff_ladder_run.check_tier_1_drc` grades release-gating tier T1 off that
# file.
#
# Asserted against the LIVE yaml rather than a remembered list, and against
# BASENAMES as well as full paths, because discovery in this tree is by
# recursive glob (`reports/**/drc_signoff.json`) — a private directory keeping
# the canonical NAME would still be found and still be graded as the sign-off.
# --------------------------------------------------------------------------- #
FLOW_YAML = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"


def _flow_owned_report_paths():
    """Every report path the flow DECLARES or a gate DESIGNATES, from the yaml.

    Deliberately over-broad on the gate side: any `--json`/`--out`/`--output`/
    `--report` token in any gate command. A false member here costs a delegate
    one rename; a missing one costs a silently overwritten sign-off.
    """
    import re
    import yaml
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    paths = set()
    flag = re.compile(r"--(?:json|out|output|report)\s+(\S+)")
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "required_outputs" and isinstance(v, list):
                    paths.update(str(x) for x in v if isinstance(x, str))
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            paths.update(flag.findall(node))
    walk(doc)
    return {p for p in paths if p.endswith((".json", ".rpt", ".log", ".txt"))}


def test_g10_no_delegate_writes_over_a_flow_owned_report():
    owned = _flow_owned_report_paths()
    assert owned, "the flow yaml yielded no report path at all — this guard " \
                  "cannot see its subject, which is not the same as a clean run"
    owned_names = {Path(p).name for p in owned}
    for step in GP.LADDER:
        if step.delegate is None:
            continue
        rel = step.delegate.report_rel
        assert rel not in owned, (
            f"{step.step_id} writes {rel!r}, which the flow declares or "
            f"designates. Re-running a checker into the flow's own path "
            f"replaces that step's verdict with this ladder's weaker one.")
        assert Path(rel).name not in owned_names, (
            f"{step.step_id} writes basename {Path(rel).name!r}, which a "
            f"flow-owned report also uses. Discovery here is by recursive "
            f"glob, so a private directory does not save it.")
        assert rel.startswith(GP.DELEGATE_REPORT_DIR + "/"), (
            f"{step.step_id} writes {rel!r}, outside this ladder's own "
            f"{GP.DELEGATE_REPORT_DIR!r}")


def test_g10_the_guard_sees_the_collision_it_was_written_for():
    """NEGATIVE CONTROL. The exact path this ladder used to write must still be
    recognised as flow-owned — otherwise the guard above is asserting over an
    empty set and would pass on the very defect it was written for."""
    owned = _flow_owned_report_paths()
    assert "reports/phase3/drc_signoff.json" in owned
    for p in ("reports/phase3/die_finishing.json",
              "reports/phase3/antenna_signoff.json",
              "reports/phase3/drc_router.json"):
        assert p in owned, p
