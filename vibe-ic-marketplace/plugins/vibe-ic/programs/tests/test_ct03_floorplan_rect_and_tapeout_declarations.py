#!/usr/bin/env python3
"""The floorplan rectangle that is not the die, and the four declarations
`tapeout_precheck` could not get an answer to.

MEASURED (host 8HD-6, image `ghcr.io/vibeic/vibeic-eda@sha256:06537f7e…`, own
label 0.3.46; base = main v1.17.67 + lane czspmtail).

1. CT-03 — `ppl place_pins` HAS NO CORE-BOUNDARY MODE.
   spm x gf180mcuD, run 3, `phase3/stage3/pnr/pnr.tcl`::

       initialize_floorplan -die_area  "0 0 3162 3162" \\
                            -core_area "381 381 2400 2400"

   `routed.def` then carried `DIEAREA ( 0 0 ) ( 6324000 6324000 )` at
   `UNITS DISTANCE MICRONS 2000` — 0..3162 um — while its 514 ROW records ran
   from y=384.16 um to y=2395.12 um. Every antenna-violating pin came out at
   y=3161.48 um: **762 um outside the last row, with zero components in that
   band.** `repair_antenna` inserts a diode where a ROW is, so every marker on
   those nets carried `DIODES_AREA 0` and no iteration of the repair loop could
   reach them. The residual was a FLOORPLAN fact, not the router's.

   The slot path already fixes exactly this, by handing OpenROAD the CORE as
   `-die_area` so the ring band lies outside the die the pin placer knows
   about. Applying the same shape to a design whose OWN PAD RING pins the die
   moves the DEF's `DIEAREA` off the die — which is why the run now RECORDS
   both rectangles and every consumer that needs the die is handed it.

2. THE FOUR QUESTIONS BEHIND THE DATABASE UNIT (rbspm RB-08 remainder).
   Same run, `reports/phase3/general_precheck.json`::

       KLayout.CheckTopLevel   NOT_DETERMINED  `top_cell` was not declared
       KLayout.CheckSize       NOT_DETERMINED  `deliverable` was not declared
       General.SealRing        NOT_DETERMINED  `seal_ring_required` ...
       General.ForbiddenLayers NOT_DETERMINED  `forbidden_layers` ...

   A NOT_DETERMINED rung is a NON-PASS, so `tapeout_precheck` was unreachable
   for every self-tape-out however correct the die. Each of the four is now
   derived from an artefact the consuming rung does NOT measure — the rule that
   separates a real comparison from a check against its own input — or reported
   NOT_DETERMINED naming the artefact it went without.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import phase3_one_shot_runner as r          # noqa: E402
import signoff_metrics_aggregate as sma     # noqa: E402
import general_precheck as gp               # noqa: E402
import _tapeout_declaration as td           # noqa: E402


# ───────────────────────── 1. the CT-03 pin rectangle ──────────────────────

def test_ct03_no_slot_no_ring_keeps_todays_pin_placement():
    """THE CONTROL. A design with no slot and no pad ring is untouched."""
    assert r.ct03_pin_rect(None, None, 10, 480, 480) is None


def test_ct03_a_ring_inset_moves_the_pins_onto_the_core():
    """The rectangle is the one `-core_area` ALREADY carries, so the pins land
    exactly where the rows are and no other number in the run moves."""
    assert r.ct03_pin_rect(None, 381.0, 381, 2400, 2400) == [381, 381, 2400, 2400]


def test_ct03_is_not_taken_on_a_slot_because_the_die_is_already_the_core():
    """The slot path makes the CORE the `-die_area`, so `place_pins` is already
    on the core boundary and there is nothing to move."""
    assert r.ct03_pin_rect([442, 442, 1494, 2089], 381.0,
                           381, 2400, 2400) is None
    assert r.ct03_pin_rect([442, 442, 1494, 2089], None, 10, 480, 480) is None


def test_ct03_is_NOT_taken_when_this_run_places_a_pad_ring_in_the_band():
    """THE BAND IS ONLY EMPTY WHEN NOTHING IS PUT IN IT. A pin on the core
    boundary is a pin no pad reaches, so on a ring-PLACING design the pins stay
    where they are and the residual is reported instead."""
    assert r.ct03_pin_rect(None, 381.0, 381, 2400, 2400, True) is None


def test_ct03_the_scope_predicate_is_the_flows_own_pad_ring_condition(tmp_path):
    """MEASURED on spm: neither router file is present, so no ring is placed
    into the band — which is why all 15674 components sit inside the core and
    the band is empty."""
    (tmp_path / "input" / "submission_template").mkdir(parents=True)
    assert r._chip_path_requests_pad_ring(tmp_path) is False
    (tmp_path / "input/submission_template/SELF_TAPEOUT.txt").write_text("x")
    assert r._chip_path_requests_pad_ring(tmp_path) is True


def test_ct03_a_ring_inset_of_zero_is_an_answer_and_not_an_absence():
    """0.0 is a MEASURED inset. `is None` is the test, never truthiness."""
    assert r.ct03_pin_rect(None, 0.0, 0, 3162, 3162) == [0, 0, 3162, 3162]


# ─────────── 2. the emitted TCL: both branches, both directions ────────────

def test_the_pin_block_is_returned_BYTE_FOR_BYTE_when_ct03_does_not_apply():
    """THE CONTROL that matters most: every design outside CT-03's scope emits
    the identical `place_pins` it emits today."""
    block = "place_pins -hor_layers Metal3 -ver_layers Metal2"
    assert r.ct03_pin_rect_tcl(block, None) == block


def test_the_pin_block_shrinks_the_die_places_and_restores_it():
    block = "place_pins -hor_layers Metal3 -ver_layers Metal2"
    tcl = r.ct03_pin_rect_tcl(block, [381, 381, 2400, 2400])
    assert block in tcl                       # the command survives verbatim
    assert tcl.index("_vic_ct03_saved") < tcl.index("odb::dbBlock_setDieArea")
    assert tcl.index("set _vic_ct03_on 1") < tcl.index(block)
    assert tcl.rindex("odb::dbBlock_setDieArea") > tcl.index(block)
    assert "CT03_DIE_RESTORED" in tcl
    # microns in, converted with the DATABASE's own units — never a hard-coded
    # 1000 or 2000.
    assert "int(381 * $_vic_ct03_dbu)" in tcl
    assert "int(2400 * $_vic_ct03_dbu)" in tcl
    assert "getDbUnitsPerMicron" in tcl


def test_the_pin_block_degrades_loudly_and_restores_after_a_throw():
    """An OpenROAD without the ODB setter must SAY so rather than silently
    place the pins on the die boundary; and a `place_pins` that throws must
    still leave the die as it found it."""
    tcl = r.ct03_pin_rect_tcl("place_pins", [381, 381, 2400, 2400])
    assert "CT03_PIN_RECT_UNAVAILABLE" in tcl
    assert "info commands odb::dbBlock_setDieArea" in tcl
    assert tcl.index("CT03_DIE_RESTORED") < tcl.index("error $_vic_ct03_err")


def test_the_floorplan_geometry_itself_is_UNTOUCHED():
    """CT-03 no longer moves `-die_area`, and it must not: measured end to end
    TWICE, the core as the die deletes the router's tracks outside it and spm
    did not converge in either arm (1 violation, then 3), where the same design
    with the die stated whole routes clean."""
    assert r._floorplan_geometry_tcl(3162, 3162, 381, 2400, 2400) == (
        'initialize_floorplan -die_area "0 0 3162 3162" \\\n'
        '                      -core_area "381 381 2400 2400"')
    tcl = r._floorplan_geometry_tcl(3162, 3162, 381, 2400, 2400,
                                    [442, 442, 1494, 2089])
    assert '-die_area "442 442 1494 2089"' in tcl
    assert '-core_area "442 442 1494 2089"' in tcl


# ─────────────────── 3. the die rectangle record and its reader ─────────────

def _record(tmp_path, **kw):
    kw.setdefault("die_rect", [0, 0, 3162, 3162])
    kw.setdefault("fp_rect", [381, 381, 2400, 2400])
    kw.setdefault("die_source", "--die-um 3162x3162 at the origin")
    kw.setdefault("core_pad", 381)
    kw.setdefault("ring_inset_um", 380.4)
    return r._floorplan_rectangles_record(tmp_path, **kw)


def test_the_record_is_written_on_every_run_and_names_both_rectangles(tmp_path):
    rec = _record(tmp_path)
    on_disk = json.loads(
        (tmp_path / r.FLOORPLAN_RECTANGLES_REL).read_text())
    assert on_disk["die_rect_um"] == [0, 0, 3162, 3162]
    assert on_disk["floorplan_rect_um"] == [381, 381, 2400, 2400]
    assert on_disk["floorplan_rect_is_the_die"] is False
    assert "DIEAREA states it" in on_disk["note"]
    assert rec["record"] == str(tmp_path / r.FLOORPLAN_RECTANGLES_REL)
    # …and the file SAYS SO ABOUT ITSELF. MEASURED on run 3 before this: the
    # record on disk carried `"record": null` while being read from the very
    # path it denied, because the field was set after the serialisation.
    assert on_disk["record"] == str(tmp_path / r.FLOORPLAN_RECTANGLES_REL)


def test_the_record_says_so_when_the_floorplan_rectangle_IS_the_die(tmp_path):
    _record(tmp_path, fp_rect=None, ring_inset_um=None, core_pad=10)
    on_disk = json.loads((tmp_path / r.FLOORPLAN_RECTANGLES_REL).read_text())
    assert on_disk["floorplan_rect_um"] is None
    assert on_disk["floorplan_rect_is_the_die"] is True


def test_declared_die_rect_reads_the_record(tmp_path):
    _record(tmp_path)
    rect, basis = r.declared_die_rect(tmp_path)
    assert rect == [0, 0, 3162, 3162]
    assert "--die-um 3162x3162" in basis


def test_declared_die_rect_names_the_path_it_could_not_find(tmp_path):
    rect, why = r.declared_die_rect(tmp_path)
    assert rect is None
    assert r.FLOORPLAN_RECTANGLES_REL in why


def test_declared_die_rect_refuses_an_unreadable_record(tmp_path):
    p = tmp_path / r.FLOORPLAN_RECTANGLES_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json")
    rect, why = r.declared_die_rect(tmp_path)
    assert rect is None and "could not be read" in why


def test_declared_die_rect_refuses_a_degenerate_rectangle(tmp_path):
    _record(tmp_path, die_rect=[100, 100, 100, 500])
    rect, why = r.declared_die_rect(tmp_path)
    assert rect is None and "degenerate or inverted" in why


@pytest.mark.parametrize("bad", [
    ["3162", "3162", "x", None],     # strings and a null
    [0, 0, 3162],                    # three of four
    "0 0 3162 3162",                 # the DEF's own spelling, not a list
    None,
])
def test_declared_die_rect_never_invents_a_rectangle(tmp_path, bad):
    """NOT_DETERMINED, never a plausible number: the whole point. Written by
    hand rather than through the writer, because these are the shapes a record
    from another version — or another hand — can carry."""
    p = tmp_path / r.FLOORPLAN_RECTANGLES_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"die_rect_um": bad}))
    rect, why = r.declared_die_rect(tmp_path)
    assert rect is None and "no usable `die_rect_um`" in why


# ─────────────── 4. the metrics aggregate stops quoting the core ────────────

_DEF = ("VERSION 5.8 ;\nDESIGN spm ;\nUNITS DISTANCE MICRONS 2000 ;\n"
        "DIEAREA ( 762000 762000 ) ( 4800000 4800000 ) ;\nEND DESIGN\n")


def test_the_two_record_paths_are_the_same_string():
    """The aggregator spells the path rather than importing 2.7 MB of runner.
    This is what stops the duplication drifting."""
    assert sma.FLOORPLAN_RECTANGLES_REL == r.FLOORPLAN_RECTANGLES_REL


def test_die_bbox_prefers_the_declared_die_over_the_defs_own_DIEAREA(tmp_path):
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (tmp_path / "phase3" / "stage3" / "pnr" / "routed.def").write_text(_DEF)
    _record(tmp_path)
    cell = sma._die_bbox(tmp_path)
    assert cell.value == "0 0 3162 3162"          # the DIE
    assert "declared die rectangle" in cell.basis


def test_die_bbox_falls_back_to_the_def_and_says_that_it_did(tmp_path):
    """THE OTHER DIRECTION. Every tree written before the record still gets an
    answer, and the basis names which authority produced it."""
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (tmp_path / "phase3" / "stage3" / "pnr" / "routed.def").write_text(_DEF)
    cell = sma._die_bbox(tmp_path)
    assert cell.value == "381 381 2400 2400"      # the DEF's own DIEAREA
    assert "DIEAREA / UNITS DISTANCE MICRONS" in cell.basis
    assert r.FLOORPLAN_RECTANGLES_REL in cell.basis


# ───────────────────── 5. `deliverable`, and its deadlock ──────────────────

def _io_pad_report(project, sides):
    p = project / "reports" / "phase3" / "io_pad_chip_top.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "program": "io_pad_chip_top_gen", "verdict": "WROTE",
        "pad_placement": {"source": "input/docs/L3_external_interface.md",
                          "heading": "Physical Pad Placement",
                          "side_signals": sides}}))


def test_deliverable_is_a_DIE_when_the_input_names_the_die_sides(tmp_path):
    """spm's OWN case. `_ppa/delivery_path` cannot answer, because the route
    is chosen from a router file step 0.5ic writes only once THIS field is
    answered — measured as `route NOT_DETERMINED … no router file was written`.
    The design's own input breaks that deadlock."""
    _io_pad_report(tmp_path, {"N": ["x[size-1:0]"], "S": ["rst"],
                              "E": ["clk"], "W": ["p", "y"]})
    value, basis = r._declared_deliverable(tmp_path)
    assert value == td.DELIVERABLE_DIE
    assert "4 side(s)" in basis
    assert "L3_external_interface.md" in basis
    assert "Physical Pad Placement" in basis


def test_deliverable_is_NOT_DETERMINED_when_nothing_has_said(tmp_path):
    value, why = r._declared_deliverable(tmp_path)
    assert value is None
    assert "io_pad_chip_top.json is not on disk" in why


def test_deliverable_refuses_one_named_side(tmp_path):
    """One side is not a die. A hardmacro's spec can name an edge too."""
    _io_pad_report(tmp_path, {"N": ["x"], "S": [], "E": [], "W": []})
    value, why = r._declared_deliverable(tmp_path)
    assert value is None and "1 die side(s)" in why


# ───────────────────────── 6. `forbidden_layers` ───────────────────────────

def test_forbidden_layers_comes_from_the_pdk_bridge_config(tmp_path):
    p = tmp_path / "input" / "pdk" / "bridge" / "signoff.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"forbidden_layers": ["81/0", "82/0"]}))
    value, basis = r._declared_forbidden_layers(tmp_path)
    assert value == ["81/0", "82/0"]
    assert "bridge config" in basis


def test_forbidden_layers_comes_from_the_designs_own_L19(tmp_path):
    p = tmp_path / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(
        {"constraints": {"forbidden_layers": ["72/20"]}}))
    value, basis = r._declared_forbidden_layers(tmp_path)
    assert value == ["72/20"] and "L19" in basis


def test_forbidden_layers_never_publishes_an_empty_set(tmp_path):
    """THE PROHIBITION THIS FIELD IS MOST EXPOSED TO. `[]` is a REAL answer in
    this schema and it would turn the rung green — so a run where no party
    forbids a layer must publish NOTHING, and say which parties it asked."""
    value, why = r._declared_forbidden_layers(tmp_path)
    assert value is None
    assert value != []
    assert "input/pdk/bridge/signoff.json:forbidden_layers" in why
    assert "L19_CONSTRAINTS_PDK.json" in why
    assert "different facts" in why


# ─────────────────────── 7. the publisher, end to end ──────────────────────

class _Pdk:
    """The two attributes the derivations touch."""
    tech_lef = "/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc/tech.lef"
    tech_lef_source = None
    cell_lef = ""
    liberty = ""
    cell_gds = ""


def _project(tmp_path, *, decl=True):
    (tmp_path / "input" / "submission_template").mkdir(parents=True)
    if decl:
        (tmp_path / td.DECLARATION_REL).write_text(
            json.dumps(td.blank_declaration(), indent=2))
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (tmp_path / "phase3" / "stage3" / "pnr" / "routed.def").write_text(_DEF)
    _record(tmp_path)
    _io_pad_report(tmp_path, {"N": ["x"], "S": ["rst"], "E": ["clk"],
                              "W": ["p", "y"]})
    return tmp_path


@pytest.fixture
def seal_present(monkeypatch):
    monkeypatch.setattr(
        r, "_docker_exec",
        lambda *a, **k: (0, "VIC_SEAL_SCRIPT_OK\n", ""))


@pytest.fixture
def seal_absent(monkeypatch):
    monkeypatch.setattr(r, "_docker_exec", lambda *a, **k: (1, "", "no such"))


def test_publish_answers_the_five_it_can_and_names_the_one_it_cannot(
        tmp_path, seal_present):
    project = _project(tmp_path)
    rec = r.publish_tapeout_declarations(
        project, _Pdk(), "c", project / "phase3/stage3/pnr/routed.def", "spm")
    assert set(rec["published"]) == {
        "top_cell", "deliverable", "die_origin_um", "die_area_um",
        "seal_ring_required"}
    assert set(rec["not_determined"]) == {"forbidden_layers"}
    doc, err = td.load(project / td.DECLARATION_REL)
    assert err is None
    assert td.answer(doc, "top_cell") == "spm"
    assert td.answer(doc, "deliverable") == td.DELIVERABLE_DIE
    assert td.answer(doc, "die_origin_um") == [0, 0]
    assert td.answer(doc, "die_area_um") == [0, 0, 3162, 3162]
    assert td.answer(doc, "seal_ring_required") is True
    assert td.answer(doc, td.FORBIDDEN_LAYERS_KEY) == td.NOT_DETERMINED
    # …and the declaration it wrote is still a WELL-FORMED one.
    assert td.validate(doc) == []


def test_publish_writes_its_record_even_when_it_publishes_nothing(tmp_path,
                                                                  seal_absent):
    """A producer that writes nothing when it declines is indistinguishable
    from one that never ran."""
    project = tmp_path
    (project / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (project / "phase3/stage3/pnr/routed.def").write_text(_DEF)
    rec = r.publish_tapeout_declarations(
        project, _Pdk(), "c", project / "phase3/stage3/pnr/routed.def", "")
    assert rec["published"] == []
    assert set(rec["not_determined"]) == {
        "top_cell", "deliverable", "die_origin_um", "die_area_um",
        "seal_ring_required", "forbidden_layers"}
    on_disk = json.loads(
        (project / "reports/phase3/tapeout_declaration_publish.json").read_text())
    assert on_disk["published"] == []
    assert on_disk["record"] == str(
        project / "reports/phase3/tapeout_declaration_publish.json")
    assert r.FLOORPLAN_RECTANGLES_REL in on_disk["not_determined"]["die_area_um"]


def test_an_existing_answer_outranks_the_derivation_and_is_never_overwritten(
        tmp_path, seal_present):
    """THE REFUSAL DIRECTION. An operator (or a human) who declared the top
    cell keeps it — which is what leaves the precheck free to REFUSE when the
    declaration and the layout disagree."""
    project = _project(tmp_path)
    doc, _ = td.load(project / td.DECLARATION_REL)
    doc, _ig = td.merge_answers(doc, {"top_cell": "somebody_elses_top"})
    (project / td.DECLARATION_REL).write_text(json.dumps(doc, indent=2))
    rec = r.publish_tapeout_declarations(
        project, _Pdk(), "c", project / "phase3/stage3/pnr/routed.def", "spm")
    assert "top_cell" not in rec["published"]
    assert "outranks this derivation" in rec["already_answered"]["top_cell"]
    doc, _ = td.load(project / td.DECLARATION_REL)
    assert td.answer(doc, "top_cell") == "somebody_elses_top"


def test_the_precheck_still_refuses_a_declaration_that_contradicts_the_layout():
    """`declare top_cell X while the GDS top is Y -> FAIL naming both`."""
    ev = gp._blank(gp.LADDER[2])
    gp._step_top_level(ev, {"top_cells": ["spm"]}, "somebody_elses_top")
    assert ev.verdict == gp.FAIL
    assert "'spm'" in ev.evidence
    assert "somebody_elses_top" in ev.evidence
    assert "not this design" in ev.evidence


def test_the_precheck_passes_the_rung_once_the_derivation_has_answered_it():
    ev = gp._blank(gp.LADDER[2])
    gp._step_top_level(ev, {"top_cells": ["spm"]}, "spm")
    assert ev.verdict == gp.PASS


def test_the_size_rung_reaches_a_verdict_on_the_published_trio():
    """Before: `deliverable` unanswered -> NOT_DETERMINED, and the two
    rectangles behind it were never even reached."""
    ev = gp._blank(gp.LADDER[3])
    geom = {"bbox_um": [0.0, 0.0, 3162.0, 3162.0], "dbu_um": 0.001,
            "bbox_complete": True, "width_um": 3162.0, "height_um": 3162.0}
    gp._step_size(ev, geom, td.DELIVERABLE_DIE, [0, 0], [0, 0, 3162, 3162])
    assert ev.verdict == gp.PASS


def test_the_size_rung_refuses_a_stream_that_is_not_the_declared_die():
    """THE OTHER DIRECTION — the hollow-die shape. A stream whose extent is
    the CORE instead of the die is exactly what CT-03 makes possible if the
    die-wide fill is not told the die, so the rung must catch it."""
    ev = gp._blank(gp.LADDER[3])
    geom = {"bbox_um": [381.0, 381.0, 2400.0, 2400.0], "dbu_um": 0.001,
            "bbox_complete": True, "width_um": 2019.0, "height_um": 2019.0}
    gp._step_size(ev, geom, td.DELIVERABLE_DIE, [0, 0], [0, 0, 3162, 3162])
    assert ev.verdict == gp.FAIL
    assert "381" in ev.evidence and "2019" in ev.evidence
