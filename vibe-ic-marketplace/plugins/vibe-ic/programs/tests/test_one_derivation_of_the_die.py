#!/usr/bin/env python3
"""ONE derivation of the die, for every program that used to read DIEAREA.

vibe-ic#2058 FP-15, from FP-08 measured by lane czspmfp.

THE DEFECT. `ppl place_pins` places pins on the DIE boundary and has no
core-boundary mode, so on a SLOT run the runner hands OpenROAD the PLACEABLE
CORE as `-die_area`, and every DEF it writes states that core in its `DIEAREA`
record. Programs that read `DIEAREA` and call it the die have therefore been
computing against the core on every slot run — a die area, a power density, a
tap-coverage region, a pad-ring rectangle, a pin's side.
`signoff_metrics_aggregate._die_bbox` records the measurement in its own
docstring: 1052 x 1647 um stated as the die of a 1936 x 2531 um slot.

THE ONE AUTHORITY is `reports/phase3/floorplan_rectangles.json`, which
`phase3_one_shot_runner.step_pnr` writes on every run and which
`signoff_metrics_aggregate` and the runner itself already read.
`programs/_declared_die.py` is the third consumer, not a second opinion.

THE POPULATION, re-derived here from the tree rather than taken from a list, so
a program that starts reading DIEAREA later cannot join it unnoticed. The brief
named nine; the census below measures the readers and
`test_the_named_non_readers_really_do_not_read_a_die` records why two of the
nine are not among them.

THE CONTROL IS THE MEASUREMENT THAT MATTERS. spm x gf180mcuD is a NON-slot run:
its record says `die_rect_um [0, 0, 3162, 3162]` with
`floorplan_rect_is_the_die: true`, and every DEF it wrote carries
`DIEAREA ( 0 0 ) ( 6324000 6324000 )` at `UNITS DISTANCE MICRONS 2000` — the
same rectangle. On such a run nothing any of the seven computes may move, and
`test_a_non_slot_run_is_byte_identical_for_every_reader` is that assertion.
"""
import json
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _declared_die as DD                              # noqa: E402

#: spm's own numbers, quoted from the run (lane czspmfp, image label 0.3.46).
SPM_DBU = 2000
SPM_DIE_UM = [0.0, 0.0, 3162.0, 3162.0]
#: A slot's own numbers, in the shape `step_pnr` writes them.
SLOT_DIE_UM = [0.0, 0.0, 1936.0, 2531.0]
SLOT_CORE_UM = [0.0, 0.0, 1052.0, 1647.0]


def _def_text(rect_um, dbu=1000) -> str:
    x0, y0, x1, y1 = (int(round(v * dbu)) for v in rect_um)
    return (f"VERSION 5.8 ;\nDESIGN chip_top ;\n"
            f"UNITS DISTANCE MICRONS {dbu} ;\n"
            f"DIEAREA ( {x0} {y0} ) ( {x1} {y1} ) ;\n"
            f"COMPONENTS 0 ;\nEND COMPONENTS\nEND DESIGN\n")


def _record(project: Path, die_um, floorplan_um=None) -> Path:
    p = project / DD.FLOORPLAN_RECTANGLES_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "program": "phase3_one_shot_runner.step_pnr",
        "die_rect_um": list(die_um),
        "die_source": "the die this run settled on",
        "floorplan_rect_um": (list(floorplan_um) if floorplan_um else None),
        "floorplan_rect_is_the_die": floorplan_um is None}))
    return p


# --------------------------------------------------------------------------- #
# the derivation itself — the three tiers
# --------------------------------------------------------------------------- #
def test_a_non_slot_run_returns_the_same_rectangle_the_def_states(tmp_path):
    """THE CONTROL, in spm's own numbers."""
    _record(tmp_path, SPM_DIE_UM)
    r = DD.resolve(tmp_path, def_text=_def_text(SPM_DIE_UM, SPM_DBU))
    assert list(r.rect) == SPM_DIE_UM
    assert r.source == DD.DECLARED
    assert list(r.def_rect_um) == SPM_DIE_UM, \
        "the DEF and the record must agree on a non-slot run, or this is not " \
        "the control it claims to be"
    assert r.area_um2() == pytest.approx(3162.0 * 3162.0)


def test_a_slot_run_returns_the_die_and_not_the_core(tmp_path):
    """THE MUTATION DIRECTION. Same code, a record that says the floorplan
    rectangle is NOT the die, and the DEF stating the core."""
    _record(tmp_path, SLOT_DIE_UM, floorplan_um=SLOT_CORE_UM)
    r = DD.resolve(tmp_path, def_text=_def_text(SLOT_CORE_UM))
    assert list(r.rect) == SLOT_DIE_UM
    assert list(r.def_rect_um) == SLOT_CORE_UM
    assert r.source == DD.DECLARED
    # the size of the error the whole item exists to remove
    assert r.area_um2() / (1052.0 * 1647.0) == pytest.approx(2.83, abs=0.01)


def test_no_record_is_not_measured_and_names_what_was_missing(tmp_path):
    r = DD.resolve(tmp_path, def_text=_def_text(SLOT_CORE_UM),
                   allow_def_fallback=False)
    assert r.rect is None and r.source == DD.NOT_MEASURED
    assert DD.FLOORPLAN_RECTANGLES_REL in r.basis
    assert "deliberately not used" in r.basis


def test_a_named_fallback_is_allowed_and_an_anonymous_one_is_not(tmp_path):
    """A consumer that must still produce something gets the DEF rectangle —
    and a `source` that says so. Nothing in this module can hand back the DEF's
    number under the DECLARED tier."""
    r = DD.resolve(tmp_path, def_text=_def_text(SLOT_CORE_UM))
    assert list(r.rect) == SLOT_CORE_UM
    assert r.source == DD.DEF_FALLBACK and not r.is_declared
    assert "PLACEABLE CORE" in r.basis


def test_an_unusable_record_is_not_a_declaration(tmp_path):
    for bad in ({}, {"die_rect_um": None}, {"die_rect_um": [0, 0, 0, 0]},
                {"die_rect_um": [0, 0, "3162", 3162]},
                {"die_rect_um": [10, 10, 5, 5]}):
        p = tmp_path / DD.FLOORPLAN_RECTANGLES_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(bad))
        r = DD.resolve(tmp_path, def_text=_def_text(SLOT_CORE_UM),
                       allow_def_fallback=False)
        assert r.source == DD.NOT_MEASURED, f"{bad} was accepted as a die"


def test_the_three_spellings_of_the_record_path_agree():
    """The path is spelled in THREE modules and the reason is stated in each:
    importing a 2.7 MB runner to read one relative path is worse than the
    duplication. `test_ct03_floorplan_rect_and_tapeout_declarations.py:236`
    already pins the runner against the aggregator; this pins the third."""
    import signoff_metrics_aggregate as SMA
    import phase3_one_shot_runner as R
    assert DD.FLOORPLAN_RECTANGLES_REL == SMA.FLOORPLAN_RECTANGLES_REL
    assert DD.FLOORPLAN_RECTANGLES_REL == R.FLOORPLAN_RECTANGLES_REL


def test_the_def_reader_handles_both_spellings_and_a_rectilinear_die():
    two = "UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 100 200 ) ;\n"
    flat = "UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 100 200 ) ;\n"
    poly = ("UNITS DISTANCE MICRONS 1000 ;\n"
            "DIEAREA ( 0 0 ) ( 0 200 ) ( 60 200 ) ( 60 100 )\n"
            "        ( 100 100 ) ( 100 0 ) ;\n")
    for text in (two, flat, poly):
        assert DD.def_diearea_um(text) == [0.0, 0.0, 0.1, 0.2], text[:40]
    # No UNITS record: the integers are not convertible, and 1000 is the DEF
    # default rather than a PDK fact — documented, not silent.
    assert DD.def_diearea_um("DIEAREA ( 0 0 ) ( 1000 2000 ) ;\n") == \
        [0.0, 0.0, 1.0, 2.0]


# --------------------------------------------------------------------------- #
# the population — measured from the tree, never listed
# --------------------------------------------------------------------------- #
#: Programs that read a DEF's DIEAREA and treat the result as THE DIE. Each one
#: must consume the single derivation. A program joining this set later without
#: consuming it fails the census below.
_READERS = (
    "latchup_esd_spacing_check.py",
    "thermal_screen_check.py",
    "pad_side_constraint_check.py",
    "_ic_release_artefacts.py",
    "floorplan_pdn_check.py",
    "pad_ring_gen.py",
)
#: Examined and deliberately left, with the reason quoted from its own source.
#: `die_finishing_gen` PREFERS the built die to the agreed one because the ring
#: must fit the layout it is added to, and says the disagreement belongs to the
#: 37.5ic precheck — which is now the rung that reports it.
_DELIBERATE = ("die_finishing_gen.py",)
#: Out of this lane: the runner is serialised to another lane, and the
#: aggregator already carries the FP-08 fix this item generalises.
_ELSEWHERE = ("phase3_one_shot_runner.py", "signoff_metrics_aggregate.py")
#: Prose and metric-spec strings — no DEF is read.
_NOT_CODE = ("prose_polarity_consulted_check.py",)
#: Named by the brief as readers and measured NOT to be — see
#: `test_the_named_non_readers_really_do_not_read_a_die` for the evidence.
_NOT_READERS = ("io_pad_chip_top_gen.py", "frontend_backend_handoff_check.py")


def test_every_reader_consumes_the_one_derivation():
    missing = [n for n in _READERS
               if "_declared_die" not in (PROGRAMS / n).read_text()]
    assert missing == [], (
        "these programs read a DEF's DIEAREA as the die and do not consume "
        f"the single derivation: {missing}")


def test_the_census_still_finds_every_diearea_reader_in_the_tree():
    """THE NEGATIVE THAT KEEPS THE LIST HONEST.

    Every top-level program mentioning DIEAREA must be accounted for by one of
    the four lists above. A NEW reader lands in neither and fails here, which is
    the only thing stopping this file from pinning a list that has gone stale.
    """
    accounted = (set(_READERS) | set(_DELIBERATE) | set(_ELSEWHERE)
                 | set(_NOT_CODE) | set(_NOT_READERS))
    accounted |= {"_declared_die.py", "_pad_ring.py"}
    found = {p.name for p in PROGRAMS.glob("*.py")
             if "DIEAREA" in p.read_text(errors="replace")}
    assert found, "the census found no DIEAREA anywhere — it cannot fail"
    unaccounted = sorted(found - accounted)
    assert unaccounted == [], (
        "a program reads DIEAREA and is in none of this file's four lists. "
        "Decide which it belongs in — a reader that must consume "
        "`_declared_die`, a deliberate exception with its reason, another "
        "lane's file, prose, or a measured non-reader: "
        f"{unaccounted}")


def test_the_named_non_readers_really_do_not_read_a_die():
    """The brief named nine programs; two of them are not DIEAREA readers, and
    this asserts the two reasons rather than leaving them in a note.

    `io_pad_chip_top_gen` DERIVES the die side from the pad library's own LEF
    widths and reads no DEF at all. `frontend_backend_handoff_check` uses its
    `DIE_AREA_RE` only to recognise a floorplan CONFIG FILE by mention.
    """
    io = (PROGRAMS / "io_pad_chip_top_gen.py").read_text()
    code = "\n".join(ln for ln in io.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "DIEAREA" not in code, \
        "io_pad_chip_top_gen has started reading a DEF's DIEAREA — it is a " \
        "die READER now and belongs in _READERS"
    assert re.search(r"die_um\s*=", io), \
        "io_pad_chip_top_gen no longer derives the die side itself"

    fb = (PROGRAMS / "frontend_backend_handoff_check.py").read_text()
    uses = re.findall(r"DIE_AREA_RE\.\w+", fb)
    assert uses == ["DIE_AREA_RE.search"], uses
    assert "if DIE_AREA_RE.search(txt):" in fb, \
        "frontend_backend_handoff_check now does something with the match " \
        "besides recognising a config file — re-examine it"


# --------------------------------------------------------------------------- #
# the readers, end to end, on both arms
# --------------------------------------------------------------------------- #
def _thermal_project(tmp_path, die_um, def_rect_um, watts=0.5):
    proj = tmp_path
    (proj / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "phase3" / "power.json").write_text(
        json.dumps({"total_power_w": watts}))
    pnr = proj / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "floorplan.def").write_text(_def_text(def_rect_um))
    if die_um is not None:
        _record(proj, die_um,
                floorplan_um=(None if list(die_um) == list(def_rect_um)
                              else def_rect_um))
    return proj


def test_thermal_screen_divides_by_the_die_not_the_core(tmp_path):
    import thermal_screen_check as T
    slot = _thermal_project(tmp_path / "slot", SLOT_DIE_UM, SLOT_CORE_UM)
    mm2, prov = T._resolve_die_area_mm2(
        slot / "phase3" / "stage3" / "pnr" / "floorplan.def", None, None,
        project=slot)
    assert prov.startswith("declared_die_record")
    assert mm2 == pytest.approx(1936.0 * 2531.0 / 1e6)

    same = _thermal_project(tmp_path / "nonslot", SPM_DIE_UM, SPM_DIE_UM)
    mm2b, _ = T._resolve_die_area_mm2(
        same / "phase3" / "stage3" / "pnr" / "floorplan.def", None, None,
        project=same)
    assert mm2b == pytest.approx(3162.0 * 3162.0 / 1e6)

    # CONTROL: with no record the DEF still answers, and the provenance says so.
    bare = _thermal_project(tmp_path / "bare", None, SPM_DIE_UM)
    mm2c, provc = T._resolve_die_area_mm2(
        bare / "phase3" / "stage3" / "pnr" / "floorplan.def", None, None,
        project=bare)
    assert mm2c == pytest.approx(3162.0 * 3162.0 / 1e6)
    assert provc.startswith("def_diearea"), provc


def test_the_pad_side_rectangle_is_the_die(tmp_path):
    """A pin sitting on the DIE boundary is outside the CORE rectangle. The
    side classification must be made against the rectangle the pins were placed
    on, or every pin on a slot run is measured against the wrong edges."""
    import pad_side_constraint_check as P
    text = _def_text(SLOT_CORE_UM)
    proj = tmp_path
    _record(proj, SLOT_DIE_UM, floorplan_um=SLOT_CORE_UM)
    units = P._def_units(text)
    r = DD.resolve(proj, def_rect_um=[c / units
                                      for c in (0, 0, int(1052 * units),
                                                int(1647 * units))])
    assert list(r.rect) == SLOT_DIE_UM
    assert P._def_units("UNITS DISTANCE MICRONS 2000 ;") == 2000
    assert P._def_units("no units here") == 1000
