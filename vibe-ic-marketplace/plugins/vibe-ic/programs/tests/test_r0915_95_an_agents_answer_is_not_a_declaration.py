#!/usr/bin/env python3
"""R-0915-95 — an agent's answer to an OWNER-ONLY question is not a declaration.

WHAT WAS MEASURED. On 2026-09-06 an agent authored
`input/step_0_5ic_answers.json` for five designs and wrote `deliverable` into
each of them "cited from the input docs", inferring HARDMACRO from those
documents' SILENCE about a pad ring. The files were well-formed.
`tapeout_declaration_check` reported PASS, `route_of` selected the IP terminal,
every lane ran the IP route for eleven days, and an IP result was published as
an IC PASS. The owner ruled on 2026-09-17 (R-0915-95) that all five are dies.

Nothing in the tree could have caught it. The questionnaire recorded WHAT was
answered and never WHO answered it, so an inference and a declaration were the
same bytes.

EVERY PROPERTY BELOW IS ASSERTED IN THE DIRECTION THAT COULD FAIL.

  1. POSITIVE     an owner-attested answer IS a declaration, all the way to the
                  router file. Without this the guard could be satisfied by
                  refusing everything, which is the cheapest wrong fix here.
  2. NEGATIVE     the same bytes without the owner behind them are refused, by
                  the one reader, at the producer AND at the gate -- and the
                  refusal is `NOT_DECLARED` with the owner's own wording.
  3. DISCRIMINATION  an UNANSWERED owner-only question is NOT refused. A blank
                  declaration stays legal; a guard that reddens on silence is
                  measuring the wrong thing and would halt every design that
                  has not reached step 0.5ic yet.
  4. ONE READER   there is no second reader of `deliverable` left to disagree
                  with the first -- asserted over the AST of the two modules
                  that carried one, not over a grep.
  5. DELETED      the docs-derived inference is GONE, not disabled: a project
                  carrying the very report it used to read yields no
                  deliverable at all.

chip-AGNOSTIC: no vendor, foundry, process node, SKU or design name.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _tapeout_declaration as TD                              # noqa: E402
import tapeout_declaration_gen as GEN                          # noqa: E402

#: The owner's own words, cited the way a real answers file cites them.
CITATION = 'R-0915-95 (2026-09-17, owner ruling: the IC path)'

#: THE VOCABULARY AS LITERALS, and this is not laziness — it is what makes this
#: file a falsifier. Written as `TD.ANSWERED_BY_OWNER_VALUE` at module scope
#: (in a default argument and in the `parametrize` lists below) the whole file
#: raises AttributeError AT COLLECTION on a tree without the fix, and pytest
#: reports `1 error` instead of fifteen failures. A scraper looking for
#: "failed" then reads ZERO, which is the shape this repository has been bitten
#: by before: an unimportable test file is indistinguishable from a passing one.
#: So the literals are here, the file COLLECTS on a tree with no fix at all,
#: every case fails for its own attributable reason — and
#: `test_the_vocabulary_is_the_modules_own` below pins each literal to the
#: constant it stands for, so they cannot drift apart in silence.
OWNER = "owner"
AGENT = "agent"
MISSING = "missing"


def test_the_vocabulary_is_the_modules_own():
    """The literals above ARE the module's constants. Asserted, not assumed."""
    assert TD.ANSWERED_BY_OWNER_VALUE == OWNER
    assert TD.ANSWERED_BY_AGENT_VALUE == AGENT
    assert TD.ANSWERED_BY_MISSING == MISSING
    assert TD.PROVENANCE_KEY == "answer_provenance"
    assert TD.RULE_NOT_DECLARED == "NOT_DECLARED"


def _attested(by=OWNER, citation=CITATION):
    """One `answer_provenance` map for `deliverable`."""
    rec = {}
    if by is not None:
        rec["answered_by"] = by
    if citation is not None:
        rec["citation"] = citation
    return {"deliverable": rec}


def _declaration(deliverable, provenance=None):
    doc = TD.blank_declaration()
    doc["answers"]["deliverable"] = deliverable
    if provenance is not None:
        doc[TD.PROVENANCE_KEY] = provenance
    return doc


def _project(tmp_path, deliverable, provenance=None):
    """A project tree carrying only the declaration, as step 0.5ic writes it."""
    proj = tmp_path / "p"
    path = proj / TD.DECLARATION_REL
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(_declaration(deliverable, provenance)), encoding="utf-8")
    return proj


# --------------------------------------------------------------------------- #
# 1. POSITIVE — the owner's answer is believed, all the way to the router file
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("deliverable,route", [
    (TD.DELIVERABLE_DIE, TD.ROUTE_SELF_TAPEOUT),
    (TD.DELIVERABLE_HARDMACRO, TD.ROUTE_IP),
])
def test_an_owner_attested_answer_is_a_declaration(deliverable, route):
    doc = _declaration(deliverable, _attested())
    assert TD.answer(doc, "deliverable") == deliverable
    assert TD.route_of(doc, has_slots=False) == route
    assert TD.owner_attestation_refusals(doc) == []
    assert TD.audit(doc)["deliverable"] == deliverable
    assert TD.attestation_of(doc, "deliverable")["citation"] == CITATION


def test_the_owners_answer_reaches_the_producer_and_the_gate(tmp_path):
    """END TO END, the direction that must stay green. The producer writes the
    router file and exits 0; the gate does not refuse."""
    proj = tmp_path / "p"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "answers.json").write_text(json.dumps({
        "answers": {"deliverable": TD.DELIVERABLE_DIE},
        TD.PROVENANCE_KEY: _attested(),
    }), encoding="utf-8")

    rc = GEN.main([str(proj), "--answers", str(proj / "input" / "answers.json")])
    assert rc == 0
    assert (proj / TD.SELF_TAPEOUT_REL).is_file(), (
        "an owner-declared die must select the self-tape-out terminal")


# --------------------------------------------------------------------------- #
# 2. NEGATIVE — the same bytes, nobody entitled behind them
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("provenance,expected_word", [
    (None, MISSING),
    ({}, MISSING),
    (_attested(by=AGENT, citation="cited from the input docs"), AGENT),
    (_attested(by=None), MISSING),
    (_attested(citation=None), OWNER),
    ({"deliverable": "owner"}, MISSING),
])
def test_an_answer_the_owner_did_not_give_is_not_declared(provenance,
                                                          expected_word):
    """The 2026-09-06 shape, and the four ways of getting close to it.

    `_attested(citation=None)` is the one that says `owner` and cites nothing:
    it is refused too, because an attestation nobody can check is the silence
    the record exists to replace, and it must never be cheaper to write than
    the truth."""
    doc = _declaration(TD.DELIVERABLE_HARDMACRO, provenance)
    assert TD.answer(doc, "deliverable") == TD.NOT_DETERMINED
    assert TD.route_of(doc, has_slots=False) == TD.NOT_DETERMINED
    assert TD.audit(doc)["deliverable"] == TD.NOT_DETERMINED

    refusals = TD.owner_attestation_refusals(doc)
    assert [r["rule"] for r in refusals] == [TD.RULE_NOT_DECLARED]
    assert refusals[0]["message"].startswith(
        f"NOT_DECLARED: deliverable — answered_by={expected_word}; "
        f"the owner must answer"), refusals[0]["message"][:200]


def test_the_refusal_names_where_the_answer_goes():
    """A refusal that does not say what would fix it sends the reader back to
    the inference that caused this."""
    msg = TD.not_declared_message(
        _declaration(TD.DELIVERABLE_HARDMACRO), "deliverable")
    assert TD.PROVENANCE_KEY in msg
    assert OWNER in msg and AGENT in msg


def test_the_producer_halts_step_0_5_and_writes_no_router_file(tmp_path):
    """THE HALT. `tapeout_declaration_gen` is blocking in step 0.5ic's producer
    chain, so its rc is what stops Phase 1."""
    proj = tmp_path / "p"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "answers.json").write_text(json.dumps({
        "answers": {"deliverable": TD.DELIVERABLE_HARDMACRO},
    }), encoding="utf-8")

    rec = GEN.build(proj, proj / "input" / "answers.json")
    assert rec["declaration_refusals"] == [], (
        "the document is well-formed -- that was always the point")
    assert [r["rule"] for r in rec["attestation_refusals"]] == [
        TD.RULE_NOT_DECLARED]
    assert rec["route"] == TD.NOT_DETERMINED

    rc = GEN.main([str(proj), "--answers", str(proj / "input" / "answers.json")])
    assert rc == 1, "step 0.5ic must not proceed on an undeclared deliverable"
    assert not (proj / TD.SELF_TAPEOUT_REL).is_file()


# --------------------------------------------------------------------------- #
# 3. DISCRIMINATION — silence is not refused, and the population is pinned
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("unanswered", [TD.NOT_DETERMINED, "", None])
def test_an_unanswered_owner_question_is_not_refused(unanswered):
    """A blank declaration stays legal. A guard that reddens on silence would
    halt every design that has not reached step 0.5ic yet, and would say
    nothing about the defect -- the 09-06 files were not silent."""
    doc = _declaration(unanswered)
    assert TD.owner_attestation_refusals(doc) == []
    assert TD.answer(doc, "deliverable") == TD.NOT_DETERMINED


def test_the_owner_only_population_is_exactly_one_question():
    """PINNED, because widening it is a decision and not a tidy-up.

    `seal_ring_required` ("does the party that takes this layout require a
    seal ring?") and `forbidden_layers` ("forbidden by whom?") ask the same
    SHAPE of question and are deliberately NOT here: the owner has ruled on
    `deliverable` and on neither of those, and adding them would halt every
    design in the corpus on a question nobody has been asked. They join when
    there is a ruling to cite."""
    assert TD.OWNER_ANSWERED == ("deliverable",)
    assert set(TD.OWNER_ANSWERED).isdisjoint(TD.TECHNOLOGY_ANSWERED)
    assert TD.question("seal_ring_required").answered_by == TD.ANSWERED_BY_DESIGN


def test_a_provenance_map_does_not_answer_a_question_by_itself():
    """An attestation for a question nobody answered answers nothing. Otherwise
    the map would be a second place to declare a deliverable."""
    doc = _declaration(TD.NOT_DETERMINED, _attested())
    assert TD.answer(doc, "deliverable") == TD.NOT_DETERMINED
    assert TD.route_of(doc, has_slots=False) == TD.NOT_DETERMINED


# --------------------------------------------------------------------------- #
# 4. ONE READER — asserted over the AST, not over a grep
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("module", [
    "_tapeout_declaration.py", "phase3_one_shot_runner.py"])
def test_nothing_reaches_into_the_answers_mapping_for_the_deliverable(module):
    """Both of these modules carried a hand-rolled `.get("deliverable")` that
    could -- and on 2026-09-06 did -- answer a question `TD.answer` would have
    refused. Two readers of one field is two answers waiting to differ."""
    tree = ast.parse((_PROGRAMS / module).read_text(encoding="utf-8"))
    hits = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get" and n.args
            and isinstance(n.args[0], ast.Constant)
            and n.args[0].value == "deliverable"]
    assert hits == [], (
        f"{module} reads `deliverable` out of a mapping directly at line(s) "
        f"{hits}; it must go through `_tapeout_declaration.answer` (or "
        f"`raw_answer`, for quoting a refused value)")


def test_route_of_and_audit_and_answer_cannot_disagree():
    """The same document, the three entry points, one verdict."""
    doc = _declaration(TD.DELIVERABLE_DIE)          # answered, unattested
    assert TD.answer(doc, "deliverable") == TD.NOT_DETERMINED
    assert TD.audit(doc)["deliverable"] == TD.NOT_DETERMINED
    assert TD.route_of(doc, has_slots=False) == TD.NOT_DETERMINED
    doc[TD.PROVENANCE_KEY] = _attested()
    assert TD.answer(doc, "deliverable") == TD.DELIVERABLE_DIE
    assert TD.audit(doc)["deliverable"] == TD.DELIVERABLE_DIE
    assert TD.route_of(doc, has_slots=False) == TD.ROUTE_SELF_TAPEOUT


def test_the_operator_still_outranks_the_declaration():
    """NOT WIDENED. An ingested operator template wins whatever the design
    says about itself, attested or not -- that ordering is what keeps step
    37.5ic's verdict on the shuttle route."""
    doc = _declaration(TD.DELIVERABLE_HARDMACRO)
    assert TD.route_of(doc, has_slots=True) == TD.ROUTE_SHUTTLE


def test_the_audit_says_who_answered_beside_what_was_answered():
    """A reader holding an audit that says NOT_DETERMINED for a file whose
    `answers` plainly carries a word has to be told why in the same record."""
    att = TD.audit(_declaration(TD.DELIVERABLE_DIE))["deliverable_attestation"]
    assert att["declares"] is False
    assert att["answered_by"] == MISSING
    assert att["why_not"]


# --------------------------------------------------------------------------- #
# 5. DELETED, NOT DISABLED — the docs-derived inference
# --------------------------------------------------------------------------- #
