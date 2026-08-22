#!/usr/bin/env python3
"""Steps 15.5ic and 26.5ic — a die that tapes out ITSELF gets a pad ring and a
seal ring (vibe-ic#1410, agent `cpath`).

THE DEFECT, READ STRAIGHT OUT OF THE FLOW
-----------------------------------------
Both steps were conditioned on the SHUTTLE OPERATOR'S template::

    - id: 15.5ic     condition: {files_exist: [input/submission_template/slots/*.yaml]}
    - id: 26.5ic     condition: {files_exist: [input/submission_template/slots/*.yaml]}

A chip doing its own tape-out has no operator and therefore no such file, so
both steps were skipped as "not applicable" and the design shipped WITH NO PAD
RING AND NO SEAL RING. A chip with no pads cannot be bonded or probed. A die
with no seal ring is what dicing damage and moisture get into — measured by the
external authority rather than by this repository's opinion: an open-MPW
precheck container refused a layout this flow published at ladder step 3 of 16
with "requires a seal ring (guard ring) around the die", and stages 4-16 never
executed.

NEITHER IS A PROPERTY OF BEING ON A SHUTTLE. BOTH ARE PROPERTIES OF BEING A
DIE. The operator's template supplies the GEOMETRY those steps need, so its
absence must change WHERE the geometry comes from and never WHETHER the step
runs.

THE SECOND DEFECT, AND IT IS THE ONE THAT MADE THE FIRST INVISIBLE
------------------------------------------------------------------
`pad_ring_gen` reads `phase3/stage3/pnr/pad_assignment.json`. Measured by grep
over the whole repository at v1.11.18: TWO references, both readers, ZERO
writers. So step 15.5ic could take exactly one branch — the SKIP — on the
shuttle path and on the self-tape-out path alike, and widening its condition
alone would have bought nothing. `pad_assignment_gen` is that file's author.

WHAT EVERY TEST BELOW BREAKS
----------------------------
  * the condition drifts off the chip-path marker           -> red
  * a complete declaration produces no ring                 -> red
  * a NOT_DETERMINED pad field is guessed instead of named  -> red
  * a declaration that could not be READ reports clean      -> red
  * an operator template stops winning where it speaks      -> red
  * a project that answered nothing changes behaviour       -> red

The fixture is the synthetic one `test_pad_ring.py` already uses — a square
die, a three-master IO library, four pads a side. No foundry, PDK, vendor,
process-node or design name appears in this file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _pad_ring as PR                          # noqa: E402
import _submission_template as ST               # noqa: E402
import _tapeout_declaration as TD               # noqa: E402
import die_finishing_gen as DFG                 # noqa: E402
import pad_assignment_gen as PAG                # noqa: E402
import pad_ring_check as CHK                    # noqa: E402
import pad_ring_gen as GEN                      # noqa: E402

PLUGIN = PROGRAMS.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

UNITS = 1000
DIE = 2_000_000
SIDES = ("S", "E", "N", "W")
SIGNALS = {s: [f"{s.lower()}sig{i}" for i in range(4)] for s in SIDES}
ALL_SIGNALS = [n for s in SIDES for n in SIGNALS[s]]
PADS = {n: f"pad_{n}" for n in ALL_SIGNALS}

_IO_LEF = """VERSION 5.8 ;
UNITS
  DATABASE MICRONS 1000 ;
END UNITS
SITE io_site
    CLASS PAD ;
    SYMMETRY R90 ;
    SIZE 1.00 BY 350.00 ;
END io_site
SITE io_corner_site
    CLASS PAD ;
    SYMMETRY R90 ;
    SIZE 350.00 BY 350.00 ;
END io_corner_site
MACRO pad_bidir
  CLASS PAD ;
  SIZE 75 BY 350 ;
END pad_bidir
MACRO pad_corner
  CLASS PAD ;
  SIZE 350 BY 350 ;
END pad_corner
MACRO pad_fill1
  CLASS PAD ;
  SIZE 1 BY 350 ;
END pad_fill1
END LIBRARY
"""

PAD_ANSWERS = {
    "pad_order_by_side": {"south": [PADS[n] for n in SIGNALS["S"]],
                          "east": [PADS[n] for n in SIGNALS["E"]],
                          "north": [PADS[n] for n in SIGNALS["N"]],
                          "west": [PADS[n] for n in SIGNALS["W"]]},
    "pad_site_name": "io_site",
    "pad_corner_site_name": "io_corner_site",
    "pad_edge_spacing_um": 10,
    # `vertical` is R0, librelane's own default, DELIBERATELY: the placer does
    # not read PAD_ROTATION_VERTICAL (measured in four separate OpenROAD runs
    # -- R0/R90/R180/MX all give WEST MXR90 / EAST R90), so `pad_ring_gen`
    # refuses rc 2 on any other declared value. A fixture declaring R90 would
    # trip that refusal before reaching what these tests assert.
    "pad_rotations": {"horizontal": "R0", "vertical": "R0", "corner": "R0"},
    "pad_corner_master": "pad_corner",
    "pad_fillers": ["pad_fill1"],
    "pad_signal_map": {PADS[n]: n for n in ALL_SIGNALS},
}
DIE_ANSWERS = {
    "deliverable": TD.DELIVERABLE_DIE,
    "top_cell": "core",
    "die_area_um": [0, 0, 2000, 2000],
    "core_area_um": [400, 400, 1600, 1600],
    "fp_sizing": "absolute",
    "die_origin_um": [0, 0],
    "database_unit_um": 0.001,
}
SEAL_ANSWERS = {
    "seal_ring_required": True,
    "seal_ring_script": "libs.tech/klayout/tech/scripts/sealring.py",
    "seal_ring_marker_layer": "63/0",
}


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _floorplan() -> str:
    comps = ["- u_core CORE_MACRO + PLACED ( 900000 900000 ) N ;"]
    comps += [f"- {i} pad_bidir + UNPLACED ;" for i in PADS.values()]
    body = "\n".join(
        f"- {n} + NET {n} + DIRECTION INPUT + USE SIGNAL\n"
        f"  + LAYER met2 ( -70 -70 ) ( 70 70 ) + PLACED ( 1000 1000 ) N ;"
        for n in ALL_SIGNALS)
    return (f'VERSION 5.8 ;\nDIVIDERCHAR "/" ;\nBUSBITCHARS "[]" ;\n'
            f"DESIGN core ;\nUNITS DISTANCE MICRONS {UNITS} ;\n"
            f"DIEAREA ( 0 0 ) ( {DIE} {DIE} ) ;\n"
            f"COMPONENTS {len(comps)} ;\n" + "\n".join(comps) +
            f"\nEND COMPONENTS\n"
            f"PINS {len(ALL_SIGNALS)} ;\n{body}\nEND PINS\nEND DESIGN\n")


def _declaration(root: Path, answers, raw=None) -> None:
    dest = root / TD.DECLARATION_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        dest.write_text(raw)
        return
    doc = TD.blank_declaration()
    doc, ignored = TD.merge_answers(doc, answers)
    assert not ignored, ignored
    assert TD.validate(doc) == [], TD.validate(doc)
    dest.write_text(json.dumps(doc, indent=2))


def _project(tmp_path: Path, *, answers=None, raw=None, self_tapeout=True,
             slots=None) -> Path:
    """A floor-planned chip on ONE of the two chip-path routes.

    `slots` is a mapping filename -> YAML text; when given, the design is on
    the SHUTTLE route and no `SELF_TAPEOUT.txt` is written, because the two
    router files are mutually exclusive by construction.
    """
    root = tmp_path / "proj"
    (root / "phase3/stage3/pnr").mkdir(parents=True, exist_ok=True)
    (root / PR.FLOORPLAN_DEF_REL).write_text(_floorplan())
    lib = root / "pdk/proc/libs.ref/proc_io/lef"
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "io.lef").write_text(_IO_LEF)
    (root / ST.INGEST_DIR_REL).mkdir(parents=True, exist_ok=True)
    if slots:
        d = root / ST.SLOTS_DIR_REL
        d.mkdir(parents=True, exist_ok=True)
        for name, text in slots.items():
            (d / name).write_text(text)
    elif self_tapeout:
        (root / TD.SELF_TAPEOUT_REL).write_text(
            TD.SELF_TAPEOUT_MARKER + "\nthis die tapes out on its own "
            "submission; there is no operator template to ingest.\n")
    _declaration(root, answers if answers is not None else {}, raw=raw)
    return root


def _slot(pads: bool = False, name: str = "slot_a") -> str:
    text = (f"SLOT: {name}\n"
            "DIE_AREA: [0, 0, 2000, 2000]\n"
            "CORE_AREA: [400, 400, 1600, 1600]\n"
            "FP_SIZING: absolute\n")
    if pads:
        for side, var in (("S", "PAD_SOUTH"), ("E", "PAD_EAST"),
                          ("N", "PAD_NORTH"), ("W", "PAD_WEST")):
            text += f"{var}:\n" + "".join(
                f"  - {PADS[n]}\n" for n in SIGNALS[side])
    return text


def _pag(root: Path, *extra) -> int:
    return PAG.main([str(root), "--json", str(root / PAG.REPORT_REL), *extra])


def _pag_report(root: Path) -> dict:
    return json.loads((root / PAG.REPORT_REL).read_text())


def _gen(root: Path) -> int:
    return GEN.main([str(root), "--json", str(root / PR.REPORT_REL),
                     "--pdk-root", str(root / "pdk"), "--pdk", "proc"])


def _chk(root: Path) -> int:
    return CHK.main([str(root), "--json", str(root / PR.REPORT_REL),
                     "--pdk-root", str(root / "pdk"), "--pdk", "proc"])


def _steps():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(FLOW.read_text())["steps"]


def _step(sid: str) -> dict:
    for s in _steps():
        if str(s["id"]) == sid:
            return s
    raise AssertionError(f"step {sid} is not in the flow")


# ══════════════════════════════════════════════════════════════════════════
# 1. THE CONDITION — both steps run on the CHIP PATH, not on the template
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("sid", ["15.5ic", "26.5ic"])
def test_the_step_is_conditioned_on_the_chip_path_and_not_on_the_operator(sid):
    """The marker is read LIVE off 37.5ic rather than restated here.

    37.5ic is the tape-out terminal and it is the step that ESTABLISHED what
    the chip path is. Copying its two filenames into this file would create a
    second answer to "which designs are on the chip path" that can drift from
    the first; reading them makes drift impossible.
    """
    cond = _step(sid)["condition"]
    terminal = _step("37.5ic")["condition"]
    assert cond.get("any_of") is True, (
        f"step {sid}: the two router files are mutually exclusive, so an "
        f"ALL-of reading makes the step unreachable for every design: {cond}")
    assert set(cond["files_exist"]) == set(terminal["files_exist"]), (
        f"step {sid} and step 37.5ic disagree about what the chip path is",
        cond["files_exist"], terminal["files_exist"])
    assert TD.SELF_TAPEOUT_REL in cond["files_exist"], cond


@pytest.mark.parametrize("sid", ["15.5ic", "26.5ic"])
def test_widening_the_condition_did_not_change_the_d6_reading(sid):
    """`design_dependent` is still the right classification and is still
    STATED. A conditional step with no `condition_kind` falls to the benign
    default and the discriminator between "this design legitimately has none"
    and "someone forgot" dies with it — which is the whole of dimension 6."""
    assert _step(sid)["condition_kind"] == "design_dependent"


@pytest.mark.parametrize("sid", ["15.5ic", "26.5ic"])
def test_the_declaration_is_a_declared_input_and_a_declared_edge(sid):
    """The geometry's other source. An edge that is real and undeclared is one
    the flow's ordering guard cannot see."""
    step = _step(sid)
    assert TD.DECLARATION_REL in {i.get("path") for i in step["required_inputs"]}
    assert "0.5ic" in {str(b) for b in step["blocks_on"]}


def test_the_ip_terminal_is_still_excluded():
    """An IP is delivered as a hardmacro somebody else places: no die edge, so
    no pad ring and no seal ring of its own. `NO_TEMPLATE.txt` must NOT have
    been swept into the widened condition."""
    for sid in ("15.5ic", "26.5ic"):
        assert ST.NO_TEMPLATE_REL not in _step(sid)["condition"]["files_exist"]


# ══════════════════════════════════════════════════════════════════════════
# 2. THE HEADLINE — no operator template, a complete declaration, a real ring
# ══════════════════════════════════════════════════════════════════════════
def test_a_self_tapeout_with_a_complete_declaration_gets_a_pad_ring(tmp_path):
    root = _project(tmp_path, answers={**DIE_ANSWERS, **PAD_ANSWERS,
                                       **SEAL_ANSWERS, "forbidden_layers": []})
    assert not (root / ST.SLOTS_DIR_REL).exists(), (
        "this project must have NO operator template — that is the whole case")

    assert _pag(root) == 0, _pag_report(root)["reason"]
    cfg = json.loads((root / PR.ASSIGNMENT_REL).read_text())
    for var in PR.REQUIRED_VARS:
        assert var in cfg, (var, sorted(cfg))

    assert _gen(root) == 0, json.loads((root / PR.REPORT_REL).read_text())["reason"]
    assert (root / PR.PADRING_DEF_REL).is_file()
    rep, _ = CHK._unwrap(json.loads((root / PR.REPORT_REL).read_text()))
    assert rep["verdict"] == "PASS"
    assert len(rep["pads"]) == len(ALL_SIGNALS)
    assert len(rep["corners"]) == 4
    assert rep["abutment"]["abuts"] is True
    assert rep["bterms"]["uncovered"] == []
    assert _chk(root) == 0


def test_every_written_variable_names_the_source_it_came_from(tmp_path):
    """NOTHING IS DERIVED, and the artefact proves it rather than the docstring.

    Every variable carries a `_provenance` entry, and every entry names either
    a slot file or a declaration question — the two sources. A value with no
    source is a value this program invented.
    """
    root = _project(tmp_path, answers={**DIE_ANSWERS, **PAD_ANSWERS})
    assert _pag(root) == 0
    cfg = json.loads((root / PR.ASSIGNMENT_REL).read_text())
    prov = cfg["_provenance"]
    assert set(prov) == set(PR.REQUIRED_VARS), sorted(prov)
    for var, src in prov.items():
        assert src.startswith(("slot ", "declaration answer ")), (var, src)


def test_the_question_to_variable_map_covers_both_sides_exactly():
    """The import-time assertion in `pad_assignment_gen` is load-bearing, and
    this is the test that says so: a question added to section 2B with no
    variable behind it, or a variable `_pad_ring` requires that no question
    answers, is a config that is silently 12-of-13 — which `pad_ring_gen`
    calls MALFORMED and FAILs on."""
    section = {q.key for q in TD.QUESTIONS
               if q.section == TD.SECTION_PAD_RING}
    mapped_q = {k for k, _ in PAG.QUESTION_TO_VARS}
    mapped_v = [v for _, vs in PAG.QUESTION_TO_VARS for v in vs]
    assert mapped_q == section, (sorted(mapped_q), sorted(section))
    assert sorted(mapped_v) == sorted(PR.REQUIRED_VARS)
    assert len(mapped_v) == len(set(mapped_v)), "a variable is produced twice"


# ══════════════════════════════════════════════════════════════════════════
# 3. NOT_DETERMINED IS NAMED, NEVER GUESSED
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("question", [q.key for q in TD.QUESTIONS
                                      if q.section == TD.SECTION_PAD_RING])
def test_one_unanswered_pad_field_refuses_and_names_it(tmp_path, question):
    """Seven of eight answered is a declaration somebody STARTED. It refuses,
    it names the field, and it writes no config — because a pad site or an edge
    spacing invented here would be indistinguishable in the artefact from a
    real pin-out."""
    partial = {k: v for k, v in PAD_ANSWERS.items() if k != question}
    root = _project(tmp_path, answers={**DIE_ANSWERS, **partial})
    assert _pag(root) == 1
    rep = _pag_report(root)
    assert rep["verdict"] == "REFUSE"
    assert question in rep["reason"], rep["reason"]
    assert {f["rule"] for f in rep["findings"]} == {"PAD_CONFIG_VARIABLE_ABSENT"}
    assert not (root / PR.ASSIGNMENT_REL).exists(), (
        "a refusal must leave no config behind for the next program to read")


def test_a_partial_mapping_answer_names_the_side_it_is_missing(tmp_path):
    """`pad_order_by_side` answered for three sides is not an answer for four.
    An absent key is MISSING, never an empty default: "no pads on the north
    side" is written `[]` on purpose."""
    orders = dict(PAD_ANSWERS["pad_order_by_side"])
    orders.pop("north")
    root = _project(tmp_path, answers={**DIE_ANSWERS, **PAD_ANSWERS,
                                       "pad_order_by_side": orders})
    assert _pag(root) == 1
    rep = _pag_report(root)
    assert "PAD_NORTH" in rep["reason"], rep["reason"]
    assert "PAD_SOUTH" not in rep["reason"], rep["reason"]


def test_an_empty_side_list_is_an_answer_and_not_a_silence(tmp_path):
    """`[]` and NOT_DETERMINED are different facts and `_tapeout_declaration`
    already draws that line. A design with nothing on one side must be able to
    SAY so without being told it left the question blank."""
    orders = dict(PAD_ANSWERS["pad_order_by_side"])
    orders["north"] = []
    answers = {**DIE_ANSWERS, **PAD_ANSWERS, "pad_order_by_side": orders,
               "pad_signal_map": {PADS[n]: n for s in ("S", "E", "W")
                                  for n in SIGNALS[s]}}
    root = _project(tmp_path, answers=answers)
    assert _pag(root) == 0, _pag_report(root)["reason"]
    cfg = json.loads((root / PR.ASSIGNMENT_REL).read_text())
    assert cfg["PAD_NORTH"] == []


# ══════════════════════════════════════════════════════════════════════════
# 4. NOBODY WAS ASKED — today's state, and it must not move
# ══════════════════════════════════════════════════════════════════════════
def test_a_declaration_nobody_answered_is_not_asked_and_writes_nothing(tmp_path):
    """THE REGRESSION CONTROL. Every tree in this repository is in this state,
    so this is the behaviour that must not move: rc=2 (the flow's disclosed-skip
    tier, never a plain pass), no config written, and `pad_ring_gen`'s own SKIP
    reached exactly as it is today."""
    root = _project(tmp_path, answers={}, self_tapeout=False,
                    slots={"slot_a.yaml": _slot()})
    assert _pag(root) == 2
    rep = _pag_report(root)
    assert rep["verdict"] == "NOT_ASKED"
    assert not (root / PR.ASSIGNMENT_REL).exists()

    # ...and the ring producer behind it is untouched: still SKIP, still rc=2,
    # still naming every absent variable one by one.
    assert _gen(root) == 2
    ring, _ = CHK._unwrap(json.loads((root / PR.REPORT_REL).read_text()))
    assert ring["verdict"] == "SKIP"
    absent = {v for m in ring["missing_inputs"]
              for v in m.get("variables_absent", [])}
    assert absent == set(PR.REQUIRED_VARS), sorted(absent)
    assert (root / PR.PADRING_SKIPPED_REL).is_file()
    assert not (root / PR.PADRING_DEF_REL).exists()


def test_not_asked_and_refuse_are_different_exit_codes(tmp_path):
    """An unanswered question and a wrong answer must never buy the same exit
    code. This is the split `pad_ring_gen` already draws between an ABSENT
    config and a HALF-WRITTEN one, drawn one step earlier."""
    empty = _project(tmp_path / "a", answers={})
    partial = {k: v for k, v in PAD_ANSWERS.items() if k != "pad_fillers"}
    started = _project(tmp_path / "b", answers={**DIE_ANSWERS, **partial})
    assert _pag(empty) == 2
    assert _pag(started) == 1


# ══════════════════════════════════════════════════════════════════════════
# 5. "I COULD NOT READ IT" IS NEVER "I READ IT AND IT WAS EMPTY"
# ══════════════════════════════════════════════════════════════════════════
def test_a_declaration_that_cannot_be_parsed_refuses_rather_than_skipping(tmp_path):
    root = _project(tmp_path, raw="{ this is not json")
    assert _pag(root) == 1
    rep = _pag_report(root)
    assert rep["verdict"] == "REFUSE"
    assert {f["rule"] for f in rep["findings"]} == {"DECLARATION_UNREADABLE"}
    assert rep["sources"]["declaration_unreadable"]


def test_a_slot_file_that_cannot_be_parsed_refuses_rather_than_skipping(tmp_path):
    """An unparsable slot file may carry the very pad list that should have
    OVERRIDDEN the declaration. Taking the declaration's answer while a source
    that outranks it could not be read is the substitution rule 9 exists for."""
    root = _project(tmp_path, answers={**DIE_ANSWERS, **PAD_ANSWERS},
                    self_tapeout=False,
                    slots={"slot_a.yaml": _slot(pads=True),
                           "broken.yaml": "DIE_AREA: [0, 0, 2000\n  : : bad\n"})
    assert _pag(root) == 1
    rep = _pag_report(root)
    assert {f["rule"] for f in rep["findings"]} == {"SLOT_FILE_UNREADABLE"}
    assert "broken.yaml" in rep["reason"]
    assert not (root / PR.ASSIGNMENT_REL).exists()


# ══════════════════════════════════════════════════════════════════════════
# 6. THE OPERATOR STILL WINS WHERE THE OPERATOR SPEAKS
# ══════════════════════════════════════════════════════════════════════════
def test_the_slot_geometry_beats_the_declaration_for_the_per_side_lists(tmp_path):
    """UNCHANGED BEHAVIOUR FOR A SHUTTLE DESIGN is the regression that would
    matter most. A slot file that pins the four per-side lists supplies them;
    the declaration supplies the nine variables a slot file cannot express, and
    the artefact says which is which."""
    other = {"south": ["pad_wrong"], "east": [], "north": [], "west": []}
    root = _project(tmp_path, self_tapeout=False,
                    slots={"slot_a.yaml": _slot(pads=True)},
                    answers={**DIE_ANSWERS, **PAD_ANSWERS,
                             "pad_order_by_side": other})
    assert _pag(root) == 0, _pag_report(root)["reason"]
    cfg = json.loads((root / PR.ASSIGNMENT_REL).read_text())
    assert cfg["PAD_SOUTH"] == [PADS[n] for n in SIGNALS["S"]], (
        "the operator's own slot geometry must win over what the design says "
        "about itself")
    assert cfg["_provenance"]["PAD_SOUTH"].startswith("slot ")
    assert cfg["_provenance"]["PAD_SITE_NAME"].startswith("declaration ")
    assert _gen(root) == 0
    assert _chk(root) == 0


def test_a_slot_that_pins_the_pads_while_the_design_says_nothing_refuses(tmp_path):
    """THE CASE THAT IS NOT `NOT_ASKED`, and the distinction is the point.

    A real operator template pins the per-side pad lists. That is a source
    being asked and answering, so reporting "nobody was asked" would be false
    about the tree. It is also ALL an operator template can supply — a slot
    file carries no site name, no edge spacing, no rotation, no corner master,
    no filler and no signal map — so the remaining nine variables are owed by
    the DESIGN whatever the operator published.

    THIS IS A BEHAVIOUR CHANGE ON THE SHUTTLE PATH and it is stated rather than
    slipped in: such a tree used to reach `pad_ring_gen`'s SKIP and the step
    read MISSING; it now refuses one step earlier with the nine owed variables
    named. Both are non-pass and neither produces a ring, so no green becomes
    red — what moves is that the reader is told what to answer.
    """
    root = _project(tmp_path, answers={}, self_tapeout=False,
                    slots={"slot_a.yaml": _slot(pads=True)})
    assert _pag(root) == 1
    rep = _pag_report(root)
    assert rep["verdict"] == "REFUSE"
    assert rep["questions_answered"] == 0
    owed = rep["findings"][0]["variables_owed"]
    assert len(owed) == len(PR.REQUIRED_VARS) - 4, owed
    for var in ("PAD_SITE_NAME", "PAD_CORNER_SITE_NAME", "PAD_EDGE_SPACING",
                "SIGNAL_MAP"):
        assert any(o.startswith(var) for o in owed), (var, owed)
    for var in ("PAD_SOUTH", "PAD_EAST", "PAD_NORTH", "PAD_WEST"):
        assert not any(o.startswith(var) for o in owed), (var, owed)
    assert "the operator's slot geometry pinned 4" in rep["reason"], rep["reason"]
    assert not (root / PR.ASSIGNMENT_REL).exists()


def test_two_slot_files_pinning_one_side_differently_refuse(tmp_path):
    """Nothing here can say which slot this design was accepted into, and
    picking one would be choosing a pin-out on the design's behalf."""
    a = _slot(pads=True, name="slot_a")
    b = _slot(name="slot_b") + "PAD_SOUTH:\n  - pad_other\n"
    root = _project(tmp_path, answers={**DIE_ANSWERS, **PAD_ANSWERS},
                    self_tapeout=False,
                    slots={"slot_a.yaml": a, "slot_b.yaml": b})
    assert _pag(root) == 1
    assert {f["rule"] for f in _pag_report(root)["findings"]} == {
        "SLOT_PAD_LIST_CONFLICT"}


def test_a_slot_pad_list_that_names_no_side_refuses_rather_than_splitting(tmp_path):
    """`PADS` / `PAD_LIST` / `PAD_ORDER` are real pad lists that name no die
    side. Assigning them to sides would be choosing which package pin each
    signal leaves on. Silently IGNORING them would be worse: the slot's pads
    would vanish from a config that looks complete."""
    text = _slot(name="slot_a") + "PADS:\n" + "".join(
        f"  - {PADS[n]}\n" for n in ALL_SIGNALS)
    root = _project(tmp_path, answers={**DIE_ANSWERS, **PAD_ANSWERS},
                    self_tapeout=False, slots={"slot_a.yaml": text})
    assert _pag(root) == 1
    rep = _pag_report(root)
    assert {f["rule"] for f in rep["findings"]} == {
        "SLOT_PAD_LIST_WITHOUT_A_SIDE"}
    assert rep["sources"]["slot_lists_without_a_side"]


# ══════════════════════════════════════════════════════════════════════════
# 7. EVERY ONE OF THE PAD PLACER'S OWN REFUSALS IS STILL REACHABLE
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("question,value,rule", [
    ("pad_site_name", "no_such_site", "PAD_SITE_NOT_FOUND"),
    ("pad_corner_site_name", "no_such_site", "PAD_SITE_NOT_FOUND"),
    ("pad_corner_master", "no_such_master", "PAD_MASTER_NOT_IN_PDK_IO_LIBRARY"),
])
def test_a_declared_value_the_pdk_does_not_carry_is_still_refused(
        tmp_path, question, value, rule):
    """`pad_assignment_gen` hands `pad_ring_gen` DECLARED values and never
    manufactured ones, so upstream's refusals still fire on a bad declaration
    instead of being smoothed over one step earlier."""
    root = _project(tmp_path, answers={**DIE_ANSWERS, **PAD_ANSWERS,
                                       question: value})
    assert _pag(root) == 0, _pag_report(root)["reason"]
    assert _gen(root) == 1
    rules = {f["rule"] for f in
             json.loads((root / PR.REPORT_REL).read_text()).get("findings", [])}
    assert rule in rules, rules


# ══════════════════════════════════════════════════════════════════════════
# 8. THE SEAL RING — declaration section 2C
# ══════════════════════════════════════════════════════════════════════════
#: The environment variables `resolve_script` consults, steps 4 and 5 of its
#: own documented order: `$KLAYOUT_SEALRING_SCRIPT` (LibreLane's variable) and
#: `$PDK_ROOT/$PDK/` + the conventional script path.
_PDK_ENV = ("PDK", "PDK_ROOT", "KLAYOUT_SEALRING_SCRIPT")


def _seal(tmp_path: Path, answers, raw=None) -> tuple:
    """Drive the seal path over a DECLARATION, with the PDK condition PINNED.

    WHY THE ENVIRONMENT IS CLEARED, and it is not a relaxation. Every test that
    uses this helper is about what the DESIGN DECLARED; none is about which PDK
    the host happens to have installed. `resolve_script` reads `$PDK_ROOT/$PDK`
    and `$KLAYOUT_SEALRING_SCRIPT`, so leaving them set makes the branch taken a
    property of the machine:

        host  (PDK unset)                     -> "no seal-ring generator is
              declared for the … PDK" -> marker=True
        image (PDK=…, PDK_ROOT=/foss/pdks with real PDKs installed)
              -> a generator RESOLVES, so that branch never fires and control
                 reaches "no streamed GDS to seal" -> marker=False

    MEASURED 2026-08-21: unpinned, three tests in this file pass on a host with
    no PDK and fail in the pinned runner image, which is the lane CI actually
    uses. BOTH results were the program behaving correctly — `_skip`'s docstring
    makes "the PDK ships no generator" a DECIDED not-applicable that earns the
    marker, and "no streamed GDS" an absent INPUT that must not. The defect was
    that the fixture never stated which of the two conditions it meant, so the
    assertion was answered by the machine instead of by the test.
    """
    root = tmp_path / "seal"
    (root / TD.DECLARATION_REL).parent.mkdir(parents=True, exist_ok=True)
    _declaration(root, answers, raw=raw)
    saved = {k: os.environ.pop(k, None) for k in _PDK_ENV}
    try:
        res = DFG.run(root, None, None, None, None, None, None, "python3",
                      None, None, None, None, False,
                      str(root / "die_finishing.json"))
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    marker = root / DFG._SKIPPED_REL
    return res["seal_ring"], marker


def test_a_design_that_declares_no_ring_is_required_skips_with_the_marker(tmp_path):
    """A DECIDED outcome, and the only source that can decide it is the design:
    "required by whom?" is not a property of the layout. It earns
    `die_finishing.SKIPPED.txt`, the artefact the flow declares as the
    alternative to a finished die."""
    seal, marker = _seal(tmp_path, {"seal_ring_required": False})
    assert seal["state"] == "DISCLOSED_SKIP"
    assert seal["marker"] is True
    assert marker.is_file()
    assert TD.DECLARATION_REL in seal["reason"]


def test_a_declared_required_ring_that_could_not_be_built_earns_no_marker(tmp_path):
    """THE SHARP EDGE. `_skip`'s own docstring splits "die finishing
    legitimately does not apply" from "the step could not run", and only the
    first earns the marker the flow reads as the step having answered. A design
    that declared a ring is REQUIRED and got none is the second — it must not
    leave a `SKIPPED.txt` behind, or the die ships unsealed against its own
    declaration with the step reading as complete."""
    seal, marker = _seal(tmp_path, {"seal_ring_required": True})
    assert seal["state"] == "DISCLOSED_SKIP"
    assert seal["marker"] is False
    assert not marker.is_file()
    assert seal["seal_ring_required"] is True


def test_a_started_seal_section_that_owes_the_required_field_fails_naming_it(tmp_path):
    """A script and a marker layer answered while `seal_ring_required` is left
    NOT_DETERMINED is a declaration started and abandoned. It must not buy the
    exit code of a declaration nobody was ever handed."""
    seal, marker = _seal(tmp_path, {
        "seal_ring_script": "libs.tech/klayout/tech/scripts/sealring.py",
        "seal_ring_marker_layer": "63/0"})
    assert seal["state"] == "FAIL"
    assert "seal_ring_required" in seal["reason"]
    assert TD.NOT_DETERMINED in seal["reason"]
    assert not marker.is_file()


def test_a_declaration_that_cannot_be_read_is_not_a_clean_not_applicable(tmp_path):
    """MEASURED ON origin/main @ 867de4289: this project, an unreadable
    declaration and a project that answered nothing produced the IDENTICAL
    verdict — DISCLOSED_SKIP, marker True, `die_finishing.SKIPPED.txt`
    written, and the same sentence about the PDK shipping no generator. A step
    that cannot see its input must SAY SO, not report clean."""
    seal, marker = _seal(tmp_path, None, raw="{ this is not json")
    assert seal["state"] == "FAIL"
    assert "could not be read" in seal["reason"]
    assert not marker.is_file()


def test_a_project_that_answered_nothing_is_unchanged(tmp_path):
    """The seal-ring regression control, and the mirror of the pad-ring one:
    every tree in this repository is in this state and it must not move."""
    seal, marker = _seal(tmp_path, {})
    assert seal["state"] == "DISCLOSED_SKIP"
    assert seal["marker"] is True
    assert marker.is_file()


def test_the_declaration_is_a_named_source_of_the_seal_ring_script(tmp_path):
    """`_tapeout_declaration` derived `seal_ring_script` FROM this program —
    "Read by `die_finishing_gen`" is its own note — and nothing read it back.
    The resolution order must NAME the declaration whether or not it answered,
    because "unset" is only checkable if the reader is told where it was looked
    for."""
    root = tmp_path / "s"
    _declaration(root, {"seal_ring_required": True,
                        "seal_ring_script": "/pdk/x/sealring.py"})
    decl, why = DFG._declaration(root)
    assert why is None
    script, src, tried = DFG.resolve_script(root, None, None, None, decl)
    assert script == "/pdk/x/sealring.py"
    assert TD.DECLARATION_REL in src
    # ...and when it does NOT answer, it is still named among the places tried.
    _declaration(root, {})
    decl, _ = DFG._declaration(root)
    _, _, tried = DFG.resolve_script(root, None, None, None, decl)
    assert any(TD.DECLARATION_REL in t for t in tried), tried


def test_a_declared_marker_layer_reaches_the_verifier(tmp_path):
    """`seal_ring_marker_layer` answers "which layer must carry geometry once
    the ring exists", which is the one question an exit code cannot: a measured
    PDK script prints "Couldn't load the seal ring library", calls
    `sys.exit()` with no argument, and exits 0 having written nothing."""
    root = tmp_path / "m"
    _declaration(root, {"seal_ring_required": True,
                        "seal_ring_marker_layer": "63/0"})
    decl, _ = DFG._declaration(root)
    assert DFG._declared(decl, DFG._DECL_MARKER) == "63/0"
    _declaration(root, {"seal_ring_required": True})
    decl, _ = DFG._declaration(root)
    assert DFG._declared(decl, DFG._DECL_MARKER) is None, (
        "an unanswered marker layer must come back as nothing, never as a "
        "plausible default")


def test_the_declared_die_area_is_the_LAST_die_size_source_never_the_first(tmp_path):
    """A DEF's DIEAREA is the die that was BUILT; `die_area_um` is the die that
    was AGREED, and where both exist the built one wins.

    That ordering is what makes the new source safe to add at all: every
    project that has ever reached this step carries a DEF, so none of them
    moves. Where the two DISAGREE it is 37.5ic's general precheck that owns the
    finding — quietly sealing to the declared number here would erase the
    evidence it reads. What it closes is the OTHER case, measured live in the
    pinned EDA image: a self-tape-out that streamed a GDS and carries no DEF
    reached "no DIEAREA found; caller must pass --die-width/--die-height" and
    skipped, while the number it needed was written down two directories away.
    """
    root = tmp_path / "d"
    (root / "phase3/stage3/pnr").mkdir(parents=True)
    gds = root / "phase3/stage3/pnr/x.gds"
    gds.write_bytes(b"")
    _declaration(root, {"seal_ring_required": True,
                        "die_area_um": [0, 0, 1000, 500]})
    decl, _ = DFG._declaration(root)

    # no DEF anywhere -> the declaration answers, and SAYS it did
    w, h, src = DFG.die_size(root, gds, None, None, decl)
    assert (w, h) == (1000.0, 500.0), (w, h, src)
    assert TD.DECLARATION_REL in src and "die_area_um" in src

    # a DEF exists -> the DEF wins and the declaration is not consulted
    (root / "phase3/stage3/pnr/routed.def").write_text(
        "UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 7000 3000 ) ;\n")
    w, h, src = DFG.die_size(root, gds, None, None, decl)
    assert (w, h) == (7.0, 3.0), (w, h, src)
    assert "DIEAREA of" in src, src

    # explicit flags still outrank both
    w, h, src = DFG.die_size(root, gds, 11.0, 12.0, decl)
    assert (w, h, src) == (11.0, 12.0, "--die-width/--die-height")


def test_an_unanswered_die_area_says_so_rather_than_defaulting(tmp_path):
    """The absence message must name BOTH places it looked. "Unset" is only
    checkable if the reader is told where the search happened."""
    root = tmp_path / "n"
    (root / "phase3/stage3/pnr").mkdir(parents=True)
    gds = root / "phase3/stage3/pnr/x.gds"
    gds.write_bytes(b"")
    _declaration(root, {})
    decl, _ = DFG._declaration(root)
    w, h, src = DFG.die_size(root, gds, None, None, decl)
    assert (w, h) == (None, None)
    assert "no DIEAREA found in any DEF" in src
    assert "die_area_um" in src and TD.NOT_DETERMINED in src


def test_a_degenerate_declared_die_area_is_not_taken(tmp_path):
    """`validate` already refuses an inverted rectangle at the declaration's
    own gate; this is the second half of the same rule, at the point of use.
    A zero-area die must not become a zero-by-zero seal ring."""
    root = tmp_path / "z"
    (root / "phase3/stage3/pnr").mkdir(parents=True)
    gds = root / "phase3/stage3/pnr/x.gds"
    gds.write_bytes(b"")
    _declaration(root, {})
    # written past `merge_answers`, because the declaration's own validator
    # would refuse this shape — which is the point: the reader must not rely
    # on the writer having been the one that ran.
    doc = json.loads((root / TD.DECLARATION_REL).read_text())
    doc["answers"]["die_area_um"] = [10, 10, 10, 10]
    (root / TD.DECLARATION_REL).write_text(json.dumps(doc))
    decl, _ = DFG._declaration(root)
    w, h, _src = DFG.die_size(root, gds, None, None, decl)
    assert (w, h) == (None, None)


def test_answering_the_die_area_does_not_make_the_seal_section_look_started(tmp_path):
    """`die_area_um` is section 2A. Answering it must not trip the 2C
    "started and still owes `seal_ring_required`" refusal, or every design that
    stated its die size would be charged for a seal-ring question nobody
    asked it."""
    seal, marker = _seal(tmp_path, {"die_area_um": [0, 0, 100, 100]})
    assert seal["state"] == "DISCLOSED_SKIP"
    assert seal["marker"] is True
    assert marker.is_file()


# ══════════════════════════════════════════════════════════════════════════
# 9. WIRING — this cannot be satisfied by adding a file nobody calls
# ══════════════════════════════════════════════════════════════════════════
def test_the_flow_names_the_producer_and_the_gate_runs_it():
    step = _step("15.5ic")
    assert "pad_assignment_gen" in step["programs"], step["programs"]
    cmds = [c["program_exit_zero"] for c in step["gate"]["all_of"]]
    assert any(c.startswith("pad_assignment_gen ") for c in cmds), cmds
    assert any(c.startswith("pad_ring_check ") for c in cmds), cmds
    fcc = pytest.importorskip("flow_compliance_check")
    for cmd in cmds:
        argv = fcc._resolve_program_cmd(cmd)
        assert argv and Path(argv[1]).is_file(), cmd


def test_the_producers_report_is_a_declared_output():
    """It is written on EVERY path this step takes, including the two that
    produce no ring — unlike `padring.def`, which is deliberately NOT given an
    `OR ...SKIPPED.txt` alternative because a pad ring on a die is never
    legitimately not-applicable."""
    outs = _step("15.5ic")["required_outputs"]
    assert PAG.REPORT_REL in outs, outs
    assert not any("padring.SKIPPED" in o for o in outs), (
        "a skipped pad ring must stay MISSING; crediting the skip as an "
        "output would make a chip with no pads read as complete", outs)


def test_the_gate_runs_as_the_flow_spawns_it(tmp_path):
    """cwd = the project, report path relative, no flags — the invocation
    `program_exit_zero` actually performs."""
    root = _project(tmp_path, answers={**DIE_ANSWERS, **PAD_ANSWERS})
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "pad_assignment_gen.py"), ".",
         "--json", PAG.REPORT_REL],
        cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "pad_assignment_gen" in r.stdout
    assert (root / PAG.REPORT_REL).is_file()


# ══════════════════════════════════════════════════════════════════════════
# 10. chip-AGNOSTICISM — asserted by the rule that already exists
# ══════════════════════════════════════════════════════════════════════════
def test_the_new_files_are_inside_the_existing_agnosticism_rule():
    """No second, weaker rule of this file's own.

    `test_pad_ring.py` already carries the two predicates that decide this —
    a process-node-SHAPED literal, and the names of the PDK trees the host can
    actually see — and it applies them to a named list of files. A list-membership
    assertion here means the new program is covered by THAT rule rather than by
    a hand-written token list which is only ever as good as its author's memory
    of which vendors exist.
    """
    import test_pad_ring as TPR
    for rel in ("pad_assignment_gen.py",
                "tests/test_pad_and_seal_ring_on_the_chip_path.py"):
        assert rel in TPR._OURS, (rel, TPR._OURS)
