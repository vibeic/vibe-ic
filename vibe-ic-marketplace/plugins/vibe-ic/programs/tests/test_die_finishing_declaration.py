#!/usr/bin/env python3
"""Step 26.5ic on the SELF-TAPE-OUT route — the declaration is the only
authority, and silence must not buy a satisfied step.

THE DEFECT, MEASURED
--------------------
Step 26.5ic's condition was `files_exist: [input/submission_template/
slots/*.yaml]` — the SHUTTLE OPERATOR'S file. A chip doing its own tape-out has
no operator and therefore no slot file, so the step was skipped as "not
applicable" and the die shipped with no seal ring. A seal ring is not a
property of being on a shuttle; it is a property of being a DIE, and it is what
dicing damage and moisture get into.

Under that, a second hole. When no seal-ring generator resolves, this step
takes its DISCLOSED SKIP branch and writes
`phase3/stage3/pnr/die_finishing.SKIPPED.txt` — one of the step's two declared
`required_outputs`. That is the right answer when nobody ever said a ring was
needed: the PDK not shipping a generator is not this design getting something
wrong. It is the WRONG answer the moment the design has declared
`seal_ring_required` = true, because then an unmet requirement buys a satisfied
output.

WHAT IS ASSERTED, and the direction of every one
------------------------------------------------
  * the SHUTTLE route is UNCHANGED, byte for byte, including the case where
    the declaration is entirely NOT_DETERMINED — which is every design that
    has not been asked. The operator answers there and this program must not
    start refusing on its behalf.
  * on the self-tape-out route each of the three `2C_seal_ring` questions is
    refused BY NAME rather than skipped over.
  * `seal_ring_required` = false is a DECIDED not-applicable — the question was
    read and it did not hold — and it DOES earn the skip marker.
  * a declared requirement plus no generator is a FAIL that keeps every word of
    the skip's own disclosure and adds the verdict.

No foundry, PDK, vendor or design literal appears here: the fixture declares a
script path that does not exist, which is the whole of what it needs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _submission_template as ST                            # noqa: E402
import _tapeout_declaration as TD                            # noqa: E402
import die_finishing_gen as DFG                              # noqa: E402

_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
_STEP = "26.5ic"
_SKIPPED_REL = "phase3/stage3/pnr/die_finishing.SKIPPED.txt"

_ANSWERS = {
    "seal_ring_required": True,
    "seal_ring_script": "/nowhere/that/exists/sealring.py",
    "seal_ring_marker_layer": "99/0",
}


def _project(tmp_path: Path, *, route: str, answers: dict,
             gds: bool = False) -> Path:
    root = tmp_path / "proj"
    (root / "input/submission_template").mkdir(parents=True, exist_ok=True)
    doc = TD.blank_declaration()
    if answers:
        doc, ignored = TD.merge_answers(doc, dict(answers))
        assert not ignored, ignored
    (root / TD.DECLARATION_REL).write_text(json.dumps(doc, indent=2) + "\n")
    if route == TD.ROUTE_SELF_TAPEOUT:
        (root / TD.SELF_TAPEOUT_REL).write_text(
            TD.SELF_TAPEOUT_MARKER + "\nfixture\n")
    else:
        (root / ST.SLOTS_DIR_REL).mkdir(parents=True, exist_ok=True)
        (root / ST.SLOTS_DIR_REL / "slot_a.yaml").write_text(
            "DIE_AREA: [0, 0, 2000, 2000]\n")
    if gds:
        (root / "phase3/stage4/gds").mkdir(parents=True, exist_ok=True)
        (root / "phase3/stage4/gds/top.gds").write_bytes(b"")
    return root


def _run(root: Path) -> dict:
    return DFG.run(root, None, None, None, None, str(root / "pdk"), "proc",
                   "python3", None, None, None, None, False, None)


def _seal(root: Path) -> dict:
    return _run(root).get("seal_ring") or {}


# --------------------------------------------------------------------------- #
# the route is read from the tree, not guessed
# --------------------------------------------------------------------------- #
def test_the_route_is_read_from_the_router_file_the_flow_also_reads(tmp_path):
    a = _project(tmp_path / "a", route=TD.ROUTE_SELF_TAPEOUT, answers={})
    b = _project(tmp_path / "b", route=TD.ROUTE_SHUTTLE, answers={})
    assert TD.route_on_disk(a) == TD.ROUTE_SELF_TAPEOUT
    assert TD.route_on_disk(b) == TD.ROUTE_SHUTTLE
    assert TD.route_on_disk(tmp_path / "nothing") == TD.NOT_DETERMINED


def test_two_router_files_at_once_are_not_resolved_by_preference(tmp_path):
    """They are mutually exclusive by construction and
    `tapeout_declaration_check` refuses that tree. Picking one here would
    resolve by preference a contradiction somebody has to see."""
    root = _project(tmp_path, route=TD.ROUTE_SELF_TAPEOUT, answers={})
    (root / ST.SLOTS_DIR_REL).mkdir(parents=True, exist_ok=True)
    (root / ST.SLOTS_DIR_REL / "slot_a.yaml").write_text("DIE_AREA: [0,0,1,1]\n")
    assert TD.route_on_disk(root) == TD.NOT_DETERMINED


# --------------------------------------------------------------------------- #
# the SHUTTLE route is unchanged
# --------------------------------------------------------------------------- #
def test_an_unanswered_declaration_on_the_shuttle_route_changes_nothing(
        tmp_path):
    """The operator answers there. This program must not start refusing on its
    behalf, or every shuttle design newly fails."""
    root = _project(tmp_path, route=TD.ROUTE_SHUTTLE, answers={})
    seal = _seal(root)
    assert seal["state"] == "DISCLOSED_SKIP"
    assert "seal_ring_required" not in (seal.get("reason") or "")


def test_an_unanswered_declaration_on_the_self_route_is_refused_by_name(
        tmp_path):
    root = _project(tmp_path, route=TD.ROUTE_SELF_TAPEOUT, answers={})
    seal = _seal(root)
    assert seal["state"] == "FAIL"
    assert "seal_ring_required" in seal["reason"]
    assert not (root / _SKIPPED_REL).exists(), (
        "a skip marker is one of this step's two declared outputs; silence "
        "must not buy a satisfied step")


@pytest.mark.parametrize("question", ["seal_ring_script",
                                      "seal_ring_marker_layer"])
def test_a_required_ring_with_an_unanswered_input_is_refused_by_name(
        tmp_path, question):
    answers = dict(_ANSWERS)
    del answers[question]
    root = _project(tmp_path, route=TD.ROUTE_SELF_TAPEOUT, answers=answers)
    seal = _seal(root)
    assert seal["state"] == "FAIL"
    assert question in seal["reason"]
    assert not (root / _SKIPPED_REL).exists()


def test_a_declared_no_ring_is_a_decided_not_applicable(tmp_path):
    """The question was READ and it did not hold. That is an answer, and it
    earns the step's skip marker — unlike a silence."""
    answers = dict(_ANSWERS)
    answers["seal_ring_required"] = False
    root = _project(tmp_path, route=TD.ROUTE_SELF_TAPEOUT, answers=answers)
    seal = _seal(root)
    assert seal["state"] == "DISCLOSED_SKIP"
    assert seal["marker"] is True
    assert "seal_ring_required" in seal["reason"]
    assert (root / _SKIPPED_REL).is_file()


# --------------------------------------------------------------------------- #
# the declaration reaches the resolvers
# --------------------------------------------------------------------------- #
def test_the_declared_script_beats_the_conventional_pdk_path(tmp_path):
    root = _project(tmp_path, route=TD.ROUTE_SELF_TAPEOUT, answers=_ANSWERS)
    script, src, tried = DFG.resolve_script(root, None, str(root / "pdk"),
                                            "proc")
    assert script == _ANSWERS["seal_ring_script"]
    assert src.startswith(TD.DECLARATION_REL)
    # every rung consulted BEFORE the winner is named, so an absence is a
    # statement about specific locations rather than a shrug.
    assert DFG._BRIDGE_CFG in "; ".join(tried)
    assert f"${DFG._ENV_SCRIPT}" not in "; ".join(tried), (
        "the environment rung is below this one and must not have been reached")


def test_an_unanswered_script_leaves_the_ladder_exactly_as_it_was(tmp_path):
    """The new rung must be a no-op for every design that has not been asked."""
    root = _project(tmp_path, route=TD.ROUTE_SHUTTLE, answers={})
    script, src, _ = DFG.resolve_script(root, None, str(root / "pdk"), "proc")
    assert src == "$PDK_ROOT/$PDK/" + DFG._PDK_SCRIPT_REL
    assert script.endswith(DFG._PDK_SCRIPT_REL)


def test_a_pdk_relative_script_answer_is_joined_to_the_pdk_root(tmp_path):
    answers = dict(_ANSWERS)
    answers["seal_ring_script"] = DFG._PDK_SCRIPT_REL
    root = _project(tmp_path, route=TD.ROUTE_SELF_TAPEOUT, answers=answers)
    script, _src, _ = DFG.resolve_script(root, None, str(root / "pdk"), "proc")
    assert script == f"{root}/pdk/proc/{DFG._PDK_SCRIPT_REL}"


def test_an_explicit_flag_still_beats_the_declaration(tmp_path):
    root = _project(tmp_path, route=TD.ROUTE_SELF_TAPEOUT, answers=_ANSWERS)
    script, src, _ = DFG.resolve_script(root, "/explicit.py",
                                        str(root / "pdk"), "proc")
    assert (script, src) == ("/explicit.py", "--script")


def test_the_declared_marker_layer_is_carried_into_the_run(tmp_path):
    root = _project(tmp_path, route=TD.ROUTE_SELF_TAPEOUT, answers=_ANSWERS,
                    gds=True)
    decl = DFG.declaration(root)
    assert decl["marker"] == _ANSWERS["seal_ring_marker_layer"]
    assert decl["unanswered"] == []


def test_every_report_records_the_declaration_it_was_decided_against(tmp_path):
    """A reader asking "why did this skip" must not have to go and find the
    declaration; going to find it is how a reader concludes it was never
    consulted."""
    root = _project(tmp_path, route=TD.ROUTE_SHUTTLE, answers={})
    res = _run(root)
    assert res["declaration"]["path"] == TD.DECLARATION_REL
    assert res["declaration"]["route"] == TD.ROUTE_SHUTTLE
    assert set(res["declaration"]["unanswered"]) == {
        q.key for q in TD.QUESTIONS if q.section == TD.SECTION_SEAL_RING}


def test_this_program_reads_exactly_the_three_questions_2C_declares():
    assert set(DFG._2C_SLOT.values()) == {
        q.key for q in TD.QUESTIONS if q.section == TD.SECTION_SEAL_RING}
    assert len(DFG._2C_SLOT) == 3



# --------------------------------------------------------------------------- #
# THE FORK UNDER THE SKIP — a declared requirement is not satisfied by
# disclosing that the generator is missing
# --------------------------------------------------------------------------- #
def test_no_generator_is_a_skip_when_nobody_said_a_ring_was_needed():
    """The PDK not shipping a generator is not this design getting something
    wrong, and the marker earns the step's declared skip artefact."""
    out = DFG._no_generator({"required": TD.NOT_DETERMINED},
                            "no seal-ring generator is declared for this PDK")
    assert out["state"] == "DISCLOSED_SKIP"
    assert out["marker"] is True


def test_no_generator_is_a_refusal_once_the_die_declared_it_needs_a_ring():
    reason = "no seal-ring generator is declared for this PDK (looked for: X)"
    out = DFG._no_generator({"required": True}, reason)
    assert out["state"] == "FAIL"
    assert out["marker"] is False
    assert reason in out["reason"], (
        "the refusal must keep every word of the skip's own disclosure — "
        "where the generator was looked for — and only add the verdict")


def test_a_declared_no_ring_still_takes_the_skip_branch():
    out = DFG._no_generator({"required": False}, "the PDK ships no generator")
    assert out["state"] == "DISCLOSED_SKIP"


def test_the_fork_end_to_end_against_a_real_klayout_runner(tmp_path):
    """Driven all the way to the "does the declared generator exist" branch.

    The SHUTTLE route is the one that shows the fork in isolation: it reaches
    that branch on both arms, so `seal_ring_required` is the ONLY difference
    between the two projects. On the self-tape-out route an unanswered
    declaration is refused earlier, by name — which is the point of the two
    tests above and is asserted there.
    """
    kl = pytest.importorskip("_klayout_launch")
    if kl.find_runner() is None:
        pytest.skip("no KLayout runner on this host; the branch is unreachable")
    unanswered = _project(tmp_path / "u", route=TD.ROUTE_SHUTTLE, answers={},
                          gds=True)
    required = _project(tmp_path / "r", route=TD.ROUTE_SHUTTLE,
                        answers=_ANSWERS, gds=True)
    a, b = _seal(unanswered), _seal(required)
    assert a["state"] == "DISCLOSED_SKIP" and a["marker"] is True
    assert (unanswered / _SKIPPED_REL).is_file()
    assert b["state"] == "FAIL"
    assert not (required / _SKIPPED_REL).exists()


def test_a_self_taped_out_die_that_needs_a_ring_and_cannot_build_one_fails(
        tmp_path):
    kl = pytest.importorskip("_klayout_launch")
    if kl.find_runner() is None:
        pytest.skip("no KLayout runner on this host; the branch is unreachable")
    root = _project(tmp_path, route=TD.ROUTE_SELF_TAPEOUT, answers=_ANSWERS,
                    gds=True)
    seal = _seal(root)
    assert seal["state"] == "FAIL"
    assert "seal_ring_required" in seal["reason"]
    assert _ANSWERS["seal_ring_script"] in seal["reason"], (
        "the refusal must still say WHERE the generator was looked for")
    assert not (root / _SKIPPED_REL).exists()
