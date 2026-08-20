#!/usr/bin/env python3
"""Step 15.5ic's config producer — `pad_assignment_gen` + `pad_assignment_check`.

THE DEFECT THESE DEFEND, MEASURED BEFORE THEY WERE WRITTEN
----------------------------------------------------------
On v1.11.7 `pad_ring_gen` read its whole geometry from
`phase3/stage3/pnr/pad_assignment.json` and NOTHING IN THE TREE WROTE IT — a
grep for that path returned five hits, every one a reader. Run against a
project carrying an operator slot template with four pad lists in it, the step
still reported all 13 config variables absent and exited 2. So step 15.5ic
could only ever SKIP, and not only on the self-tape-out path its condition used
to exclude but on the SHUTTLE path, the one path the condition admitted. A die
with no pads cannot be bonded or probed.

Every test below breaks one thing the producer defends and requires the
failure:

  DECLARED, NEVER DERIVED   every one of the 13 comes from a source that wrote
                            it down. A question left NOT_DETERMINED is a
                            refusal NAMING THE QUESTION — never a plausible
                            default, because a default reads as an answer at
                            `pad_ring_gen`, survives into `padring.def`, and
                            cannot be wrong in a way anybody notices.
  DISAGREEMENT IS A REFUSAL an operator template and a design declaration that
                            differ about a pin-out are refused, naming BOTH
                            values and BOTH paths. Choosing one silently
                            records a pin-out nobody chose.
  NOT ITS OWN SOURCE        a config this producer wrote is not read back as a
                            declaration. A producer that re-ingests its own
                            last output agrees with itself forever.
  THE ARTEFACT NEVER OUTLIVES THE EVIDENCE
                            a refusal deletes the stale config THIS program
                            wrote, so no ring can be placed from geometry this
                            run refused — and never touches one it did not
                            write, which is somebody else's input.
  THE GATE DISCRIMINATES    a PASS is believed only where the config is on
                            disk, carries the stamp, and satisfies the placer's
                            own contract.

The fixture is synthetic — a square die, a three-master IO library, four pads a
side — and carries no process, foundry or library name.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _pad_ring as PR                        # noqa: E402
import _submission_template as ST             # noqa: E402
import _tapeout_declaration as TD             # noqa: E402
import pad_assignment_check as CHK            # noqa: E402
import pad_assignment_gen as GEN              # noqa: E402
import pad_ring_gen as RING                   # noqa: E402

FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

UNITS = 1000
DIE = 2_000_000
SIGNALS = {s: [f"{s.lower()}sig{i}" for i in range(4)] for s in PR.SIDES}
ALL_SIGNALS = [n for s in PR.SIDES for n in SIGNALS[s]]
PADS = {n: f"pad_{n}" for n in ALL_SIGNALS}

_IO_LEF = """VERSION 5.8 ;
UNITS
  DATABASE MICRONS 1000 ;
END UNITS
SITE io_site
    CLASS PAD ;
    SIZE 1.00 BY 350.00 ;
END io_site
SITE io_corner_site
    CLASS PAD ;
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
            f"\nEND COMPONENTS\nPINS {len(ALL_SIGNALS)} ;\n{body}\n"
            f"END PINS\nEND DESIGN\n")


#: The eight `2B_pad_ring` answers, in the shape each question's own PROMPT
#: asks for. Nothing here is a default: this is a fixture standing in for a
#: human who answered.
def _answers() -> dict:
    return {
        "pad_order_by_side": {"south": [PADS[n] for n in SIGNALS["S"]],
                              "east": [PADS[n] for n in SIGNALS["E"]],
                              "north": [PADS[n] for n in SIGNALS["N"]],
                              "west": [PADS[n] for n in SIGNALS["W"]]},
        "pad_site_name": "io_site",
        "pad_corner_site_name": "io_corner_site",
        "pad_edge_spacing_um": 10,
        "pad_rotations": {"horizontal": "R0", "vertical": "R90",
                          "corner": "R0"},
        "pad_corner_master": "pad_corner",
        "pad_fillers": ["pad_fill1"],
        "pad_signal_map": {PADS[n]: n for n in ALL_SIGNALS},
    }


def _declaration(project: Path, answers: dict | None,
                 route: str = TD.ROUTE_SELF_TAPEOUT) -> None:
    """Write a declaration the way step 0.5ic writes one — through the real
    module, so a fixture cannot be a shape the producer will never meet."""
    doc = TD.blank_declaration()
    if answers:
        doc, ignored = TD.merge_answers(doc, dict(answers))
        assert not ignored, f"fixture wrote unknown key(s): {ignored}"
    path = project / TD.DECLARATION_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    if route == TD.ROUTE_SELF_TAPEOUT:
        (project / TD.SELF_TAPEOUT_REL).write_text(
            TD.SELF_TAPEOUT_MARKER + "\nfixture\n")


def _ingest_report(project: Path, pad_lists: dict | None,
                   declared_slot: str | None = "slot_a") -> None:
    """The OPERATOR half, in the shape `submission_template_ingest` emits it.

    The slot yaml is deliberately not written: the producer reads the INGEST'S
    PARSE and never re-parses the operator's file, and a fixture that supplied
    the yaml instead would test a path the producer does not have.
    """
    lists = [{"key": k, "raw": v, "count": len(v)}
             for k, v in (pad_lists or {}).items()]
    doc = {"schema": ST.SCHEMA, "program": "submission_template_ingest",
           "ingest": {"status": "INGESTED", "declared_slot": declared_slot,
                      "slots_shipped": ["slot_a"],
                      "slots": [{"slot": "slot_a",
                                 "source_relpath": "slots/slot_a.yaml",
                                 "pads": {"lists": lists,
                                          "keys_matched": list(pad_lists or {})}}]}}
    path = project / ST.REPORT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2))
    (project / ST.SLOTS_DIR_REL).mkdir(parents=True, exist_ok=True)
    (project / ST.SLOTS_DIR_REL / "slot_a.yaml").write_text("DIE_AREA: [0,0,1,1]\n")


def _project(tmp_path: Path, *, answers=..., operator=None,
             route=TD.ROUTE_SELF_TAPEOUT, layout=True) -> Path:
    root = tmp_path / "proj"
    (root / "phase3/stage3/pnr").mkdir(parents=True, exist_ok=True)
    (root / "input/submission_template").mkdir(parents=True, exist_ok=True)
    if layout:
        (root / PR.FLOORPLAN_DEF_REL).write_text(_floorplan())
        lib = root / "pdk/proc/libs.ref/proc_io/lef"
        lib.mkdir(parents=True, exist_ok=True)
        (lib / "io.lef").write_text(_IO_LEF)
    if operator is not None:
        _ingest_report(root, operator)
        route = TD.ROUTE_SHUTTLE
    _declaration(root, _answers() if answers is ... else answers, route)
    return root


def _operator_lists() -> dict:
    return {PR.SIDE_VAR[s]: [PADS[n] for n in SIGNALS[s]] for s in PR.SIDES}


def _gen(root: Path) -> int:
    return GEN.main([str(root)])


def _chk(root: Path) -> int:
    return CHK.main([str(root)])


def _report(root: Path) -> dict:
    return json.loads((root / GEN.REPORT_REL).read_text())


def _rules(root: Path) -> set:
    """The rule ids in the verdict document AND in the producer's report."""
    doc = _report(root)
    prod, _ = CHK._unwrap(doc)
    out = {f["rule"] for f in (doc.get("findings") or [])}
    if isinstance(prod, dict):
        out |= {f["rule"] for f in (prod.get("findings") or [])}
    return out


def _gate_rules(root: Path) -> set:
    """ONLY the GATE'S OWN findings.

    `_rules` unions the producer's, which is right for most assertions and
    exactly wrong for one: a test that a REFUSAL SURVIVES INTO THE GATE'S
    VERDICT must not be satisfiable by the rule id merely sitting in the
    embedded producer report, where it was already. Measured — a mutant that
    deleted the gate's whole FAIL branch passed such a test, because the report
    still carried the producer's finding and the PASS branch happened to reach
    rc 1 by a different route (`PAD_ASSIGNMENT_ABSENT`).
    """
    doc = _report(root)
    if doc.get("gate") != CHK.GATE:
        return set()
    return {f["rule"] for f in (doc.get("findings") or [])}


def _config(root: Path) -> dict:
    return json.loads((root / PR.ASSIGNMENT_REL).read_text())


# --------------------------------------------------------------------------- #
# DECLARED, NEVER DERIVED
# --------------------------------------------------------------------------- #
def test_a_complete_declaration_alone_produces_the_config(tmp_path):
    """The self-tape-out case: no operator anywhere, and a ring all the same."""
    root = _project(tmp_path)
    assert _gen(root) == 0
    assert _chk(root) == 0
    cfg = _config(root)
    for var in PR.REQUIRED_VARS:
        assert cfg.get(var) not in (None, ""), var


def test_the_ring_the_placer_then_builds_is_a_real_one(tmp_path):
    """The whole point, end to end: the config the producer writes drives the
    UNMODIFIED placer to a placed, abutting ring covering every BTerm."""
    root = _project(tmp_path)
    assert _gen(root) == 0
    rc = RING.main([str(root), "--json", str(root / PR.REPORT_REL),
                    "--pdk-root", str(root / "pdk"), "--pdk", "proc"])
    assert rc == 0
    rep = json.loads((root / PR.REPORT_REL).read_text())
    assert rep["verdict"] == "PASS"
    assert len(rep["pads"]) == len(ALL_SIGNALS)
    assert len(rep["corners"]) == len(PR.CORNER_POSITIONS)
    assert rep["abutment"]["abuts"] is True
    assert rep["bterms"]["uncovered"] == []
    assert (root / PR.PADRING_DEF_REL).is_file()


@pytest.mark.parametrize("question", sorted(
    q.key for q in TD.QUESTIONS if q.section == TD.SECTION_PAD_RING))
def test_one_unanswered_question_refuses_and_names_that_question(tmp_path,
                                                                 question):
    """Every one of the eight, one at a time. `NOT_DETERMINED` is refused BY
    NAME and never filled in."""
    answers = _answers()
    del answers[question]
    root = _project(tmp_path, answers=answers)
    assert _gen(root) == 1
    assert _chk(root) == 1
    assert "PAD_CONFIG_VARIABLE_ABSENT" in _rules(root)
    reason = json.dumps(_report(root))
    assert question in reason, f"the refusal never names {question}"
    assert not (root / PR.ASSIGNMENT_REL).exists(), (
        "a refused run must leave no config for the placer to read")


def test_an_unanswered_sub_key_is_refused_not_half_filled(tmp_path):
    answers = _answers()
    answers["pad_rotations"] = {"horizontal": "R0", "vertical": "R90"}
    root = _project(tmp_path, answers=answers)
    assert _gen(root) == 1
    assert "PAD_ROTATION_CORNER" in json.dumps(_report(root))
    assert not (root / PR.ASSIGNMENT_REL).exists()


@pytest.mark.parametrize("bad", [
    ("pad_order_by_side", ["a", "b"]),
    ("pad_rotations", "R0"),
])
def test_an_answer_of_the_wrong_shape_is_refused_and_named(tmp_path, bad):
    """`_tapeout_declaration.validate` deliberately does not look inside a
    `list`-kind answer, so this is the only place the shape is judged."""
    key, value = bad
    answers = _answers()
    answers[key] = value
    root = _project(tmp_path, answers=answers)
    assert _gen(root) == 1
    assert "PAD_DECLARATION_SHAPE_INVALID" in _rules(root)
    assert key in json.dumps(_report(root))


def test_a_sub_key_that_names_no_side_is_refused(tmp_path):
    answers = _answers()
    answers["pad_order_by_side"] = dict(answers["pad_order_by_side"])
    answers["pad_order_by_side"]["up"] = []
    root = _project(tmp_path, answers=answers)
    assert _gen(root) == 1
    assert "PAD_DECLARATION_SHAPE_INVALID" in _rules(root)


def test_the_merged_config_must_satisfy_the_placers_own_contract(tmp_path):
    """Refused HERE, not one step later: a config written to disk and refused
    by the placer afterwards is a refusal a reader has to go looking for."""
    answers = _answers()
    order = dict(answers["pad_order_by_side"])
    order["north"] = list(order["north"]) + [order["south"][0]]
    answers["pad_order_by_side"] = order
    root = _project(tmp_path, answers=answers)
    assert _gen(root) == 1
    assert "PAD_INSTANCE_DUPLICATED" in _rules(root)
    assert not (root / PR.ASSIGNMENT_REL).exists()


# --------------------------------------------------------------------------- #
# THE OPERATOR HALF
# --------------------------------------------------------------------------- #
def test_the_operator_slot_supplies_the_four_side_lists_and_says_so(tmp_path):
    root = _project(tmp_path, operator=_operator_lists())
    assert _gen(root) == 0
    prov = _report(root)["provenance"]
    for var in PR.SIDE_VAR.values():
        assert prov[var] == ST.REPORT_REL, var
    for var in ("PAD_SITE_NAME", "PAD_FILLERS", "SIGNAL_MAP"):
        assert prov[var] == TD.DECLARATION_REL, var


def test_the_operator_alone_supplies_four_of_thirteen_and_the_rest_refuse(
        tmp_path):
    """A shuttle design whose declaration answers nothing. The operator's
    template pins the pads for its slot and nothing else — the site names, the
    rotations, the fillers and the signal map are the DESIGN'S to declare."""
    root = _project(tmp_path, answers=None, operator=_operator_lists())
    assert _gen(root) == 1
    rep = _report(root)
    assert set(rep["absent_variables"]) == set(PR.REQUIRED_VARS) - set(
        PR.SIDE_VAR.values())
    assert len(rep["absent_variables"]) == 9
    for q in ("pad_site_name", "pad_corner_master", "pad_signal_map"):
        assert q in json.dumps(rep)


def test_the_slot_file_itself_is_never_reparsed(tmp_path):
    """The producer reads the ingest's parse. A slot yaml with pad lists in it
    and NO ingest report must contribute nothing — two parsers of one file
    drift, and the second is the one nobody re-measures."""
    root = _project(tmp_path, answers=None)
    slots = root / ST.SLOTS_DIR_REL
    slots.mkdir(parents=True, exist_ok=True)
    (slots / "slot_a.yaml").write_text(
        "DIE_AREA: [0, 0, 2000, 2000]\nPAD_SOUTH:\n  - pad_ssig0\n")
    assert _gen(root) == 2, "nothing was declared through a source it reads"
    assert not _report(root)["provenance"]


def test_an_undeclared_slot_is_refused_rather_than_guessed(tmp_path):
    root = _project(tmp_path, answers=None)
    _ingest_report(root, _operator_lists(), declared_slot=None)
    assert _gen(root) == 2
    src = [s for s in _report(root)["sources"] if s["path"] == ST.REPORT_REL][0]
    assert src["declared"] == {}
    assert any("no slot was declared" in n for n in src["notes"])


# --------------------------------------------------------------------------- #
# DISAGREEMENT IS A REFUSAL, NOT A PREFERENCE
# --------------------------------------------------------------------------- #
def test_two_sources_that_disagree_are_refused_naming_both_values(tmp_path):
    operator = _operator_lists()
    operator["PAD_SOUTH"] = list(reversed(operator["PAD_SOUTH"]))
    root = _project(tmp_path, operator=operator)
    assert _gen(root) == 1
    assert _chk(root) == 1
    rep = _report(root)
    prod, _ = CHK._unwrap(rep)
    dis = prod["disagreements"]
    assert len(dis) == 1 and dis[0]["variable"] == "PAD_SOUTH"
    paths = {s["path"] for s in dis[0]["sources"]}
    assert paths == {ST.REPORT_REL, TD.DECLARATION_REL}
    values = [s["value"] for s in dis[0]["sources"]]
    assert values[0] != values[1]
    blob = json.dumps(rep)
    for v in values:
        assert json.dumps(v) in blob, "the losing value must be visible too"
    assert not (root / PR.ASSIGNMENT_REL).exists()


def test_two_sources_that_agree_are_not_a_disagreement(tmp_path):
    """Precedence exists, but it can only ever apply where the sources agree —
    which is where precedence cannot change an answer."""
    root = _project(tmp_path, operator=_operator_lists())
    assert _gen(root) == 0
    prod, _ = CHK._unwrap(_report(root))
    assert prod["disagreements"] == []
    cfg = _config(root)
    assert cfg["PAD_SOUTH"] == _operator_lists()["PAD_SOUTH"]


# --------------------------------------------------------------------------- #
# NOT ITS OWN SOURCE / THE ARTEFACT NEVER OUTLIVES THE EVIDENCE
# --------------------------------------------------------------------------- #
def test_its_own_output_is_not_read_back_as_a_declaration(tmp_path):
    root = _project(tmp_path)
    assert _gen(root) == 0
    assert _gen(root) == 0, "re-running must be idempotent"
    src = [s for s in _report(root)["sources"]
           if s["path"] == PR.ASSIGNMENT_REL][0]
    assert src["ours"] is True
    assert src["declared"] == {}
    assert all(v == TD.DECLARATION_REL
               for v in _report(root)["provenance"].values())


def test_a_refusal_deletes_the_stale_config_this_program_wrote(tmp_path):
    """Otherwise the placer builds a ring from geometry this run refused — the
    artefact outliving the evidence."""
    root = _project(tmp_path)
    assert _gen(root) == 0
    assert (root / PR.ASSIGNMENT_REL).is_file()
    answers = _answers()
    del answers["pad_site_name"]
    _declaration(root, answers)
    assert _gen(root) == 1
    assert not (root / PR.ASSIGNMENT_REL).exists()
    assert _report(root)["stale_removed"] == PR.ASSIGNMENT_REL


def test_a_config_this_program_did_not_write_is_never_deleted(tmp_path):
    """It is somebody else's input. Refusing must not destroy it."""
    root = _project(tmp_path, answers=None)
    hand = {v: "x" for v in PR.REQUIRED_VARS}
    hand["PAD_SOUTH"] = [PADS[n] for n in SIGNALS["S"]]
    (root / PR.ASSIGNMENT_REL).write_text(json.dumps(hand))
    rc = _gen(root)
    assert rc == 1
    assert (root / PR.ASSIGNMENT_REL).is_file(), "somebody else's file"
    assert _report(root)["stale_removed"] is None


def test_a_hand_written_config_is_a_source_and_can_disagree(tmp_path):
    root = _project(tmp_path)
    hand = {"PAD_SITE_NAME": "some_other_site"}
    (root / PR.ASSIGNMENT_REL).write_text(json.dumps(hand))
    assert _gen(root) == 1
    prod, _ = CHK._unwrap(_report(root))
    assert any(d["variable"] == "PAD_SITE_NAME"
               for d in prod["disagreements"])


# --------------------------------------------------------------------------- #
# THE SKIP TIER — nobody was ever asked
# --------------------------------------------------------------------------- #
def test_no_source_at_all_is_a_disclosed_skip_and_not_a_refusal(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    assert _gen(root) == 2
    assert _chk(root) == 2
    rep = _report(root)
    prod, _ = CHK._unwrap(rep)
    assert prod["verdict"] == "SKIP"
    for s in prod["sources"]:
        assert s["path"] in prod["reason"], (
            "the reason a reader sees must name every source consulted")
    assert not (root / PR.ASSIGNMENT_REL).exists()


def test_a_skip_that_names_no_source_fails_at_the_gate(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    assert _gen(root) == 2
    doc = _report(root)
    doc["sources"] = []
    (root / GEN.REPORT_REL).write_text(json.dumps(doc))
    assert _chk(root) == 1
    assert "PAD_ASSIGNMENT_SKIP_UNDISCLOSED" in _rules(root)


def test_a_skip_contradicted_by_its_own_evidence_fails_at_the_gate(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    assert _gen(root) == 2
    doc = _report(root)
    doc["sources"][0]["declared"] = {"PAD_SITE_NAME": "io_site"}
    (root / GEN.REPORT_REL).write_text(json.dumps(doc))
    assert _chk(root) == 1
    assert "PAD_ASSIGNMENT_SKIP_CONTRADICTED" in _rules(root)


# --------------------------------------------------------------------------- #
# THE GATE DISCRIMINATES
# --------------------------------------------------------------------------- #
def test_an_absent_report_is_not_a_skip(tmp_path):
    root = _project(tmp_path)
    assert _chk(root) == 1
    assert "PAD_ASSIGNMENT_REPORT_ABSENT" in _rules(root)


def test_a_report_of_an_unknown_schema_is_not_interpreted(tmp_path):
    root = _project(tmp_path)
    assert _gen(root) == 0
    doc = _report(root)
    doc["schema"] = "something/else"
    (root / GEN.REPORT_REL).write_text(json.dumps(doc))
    assert _chk(root) == 1
    assert "PAD_ASSIGNMENT_REPORT_SCHEMA_UNKNOWN" in _rules(root)


def test_a_verdict_outside_the_vocabulary_is_not_a_pass(tmp_path):
    root = _project(tmp_path)
    assert _gen(root) == 0
    doc = _report(root)
    doc["verdict"] = "FINE"
    (root / GEN.REPORT_REL).write_text(json.dumps(doc))
    assert _chk(root) == 1
    assert "PAD_ASSIGNMENT_VERDICT_UNRECOGNISED" in _rules(root)


def test_a_pass_with_no_config_behind_it_fails(tmp_path):
    root = _project(tmp_path)
    assert _gen(root) == 0
    (root / PR.ASSIGNMENT_REL).unlink()
    assert _chk(root) == 1
    assert "PAD_ASSIGNMENT_ABSENT" in _rules(root)


def test_a_config_edited_after_the_report_fails(tmp_path):
    root = _project(tmp_path)
    assert _gen(root) == 0
    cfg = _config(root)
    del cfg["PAD_SITE_NAME"]
    (root / PR.ASSIGNMENT_REL).write_text(json.dumps(cfg))
    assert _chk(root) == 1
    assert "PAD_ASSIGNMENT_INCOMPLETE" in _rules(root)


def test_a_config_that_lost_its_stamp_fails(tmp_path):
    root = _project(tmp_path)
    assert _gen(root) == 0
    cfg = _config(root)
    del cfg[GEN.PROVENANCE_KEY]
    (root / PR.ASSIGNMENT_REL).write_text(json.dumps(cfg))
    assert _chk(root) == 1
    assert "PAD_ASSIGNMENT_NOT_STAMPED" in _rules(root)


def test_a_pass_that_attributes_nothing_fails(tmp_path):
    root = _project(tmp_path)
    assert _gen(root) == 0
    doc = _report(root)
    doc["provenance"] = {}
    (root / GEN.REPORT_REL).write_text(json.dumps(doc))
    assert _chk(root) == 1
    assert "PAD_ASSIGNMENT_PROVENANCE_INCOMPLETE" in _rules(root)


def test_the_gate_preserves_the_producers_claim_and_re_runs_cleanly(tmp_path):
    root = _project(tmp_path)
    assert _gen(root) == 0
    assert _chk(root) == 0
    doc = _report(root)
    assert doc["gate"] == CHK.GATE and doc["producer"]["program"] == GEN.PROGRAM
    assert _chk(root) == 0, "re-running the gate must not nest or flip"
    assert _report(root)["producer"]["program"] == GEN.PROGRAM


def test_a_producer_refusal_is_restated_by_rule_id_not_absorbed(tmp_path):
    """Without this the refusal reaches the reader only as a downstream skip
    saying 'the config is absent', and three different facts arrive wearing the
    same sentence."""
    answers = _answers()
    del answers["pad_site_name"]
    root = _project(tmp_path, answers=answers)
    assert _gen(root) == 1
    assert _chk(root) == 1
    assert "PAD_CONFIG_VARIABLE_ABSENT" in _gate_rules(root), (
        "the GATE'S OWN verdict must carry the producer's rule id; finding it "
        "only in the embedded producer report proves nothing about what the "
        "step's verdict says")
    assert "PAD_ASSIGNMENT_ABSENT" not in _gate_rules(root), (
        "the gate must refuse for the reason the producer gave, not stumble "
        "into rc 1 by noticing the config it never wrote is missing")


# --------------------------------------------------------------------------- #
# wiring — none of this can be satisfied by a file nobody calls
# --------------------------------------------------------------------------- #
def test_the_map_covers_the_placers_contract_and_the_declarations_section():
    assert set(GEN.QUESTION_OF_VAR) == set(PR.REQUIRED_VARS)
    assert len(PR.REQUIRED_VARS) == 13
    section = {q.key for q in TD.QUESTIONS if q.section == TD.SECTION_PAD_RING}
    assert len(section) == 8
    assert set(GEN.SCALAR_QUESTION) | {"pad_order_by_side",
                                       "pad_rotations"} == section


def test_the_gate_the_flow_names_resolves_to_programs_that_exist():
    fcc = pytest.importorskip("flow_compliance_check")
    argv = fcc._resolve_program_cmd(
        "pad_assignment_check . --json reports/phase3/pad_assignment.json")
    assert argv and Path(argv[1]).name == "pad_assignment_check.py"
    assert (PROGRAMS / "pad_assignment_gen.py").is_file()


def test_the_gate_runs_as_the_flow_spawns_it(tmp_path):
    """cwd = the project, report path relative — the shape `program_exit_zero`
    actually uses."""
    root = _project(tmp_path)
    assert _gen(root) == 0
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "pad_assignment_check.py"), ".",
         "--json", GEN.REPORT_REL],
        cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "pad_assignment_check" in r.stdout


def test_the_report_is_a_declared_output_of_the_step():
    yaml = pytest.importorskip("yaml")
    steps = yaml.safe_load(FLOW.read_text())["steps"]
    step = next(s for s in steps if str(s["id"]) == "15.5ic")
    assert GEN.REPORT_REL in step["required_outputs"]


# --------------------------------------------------------------------------- #
# chip-agnosticism
# --------------------------------------------------------------------------- #
_OURS = ("pad_assignment_gen.py", "pad_assignment_check.py",
         "tests/test_pad_assignment_gen.py")


def test_no_process_node_shaped_literal_in_these_programs():
    import re
    shaped = re.compile(r"\b[a-z]{2,}\d{2,}\w*\b")
    for rel in _OURS:
        for hit in shaped.findall((PROGRAMS / rel).read_text()):
            pytest.fail(f"{rel}: process-node-shaped literal {hit!r}")
