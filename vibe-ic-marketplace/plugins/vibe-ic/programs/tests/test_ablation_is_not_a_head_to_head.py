#!/usr/bin/env python3
"""`vibeic.ppa.ablation.v1` — the document kind a within-project ranking needs.

WHY IT EXISTS. `h2h_F` compared trial `p04` (the place-and-route-only search
winner) against `c02` (the cross-layer search winner) — BOTH configurations this
project chose — and was filed as `vibeic.ppa.comparison.v2`, whose entire claim
is a comparison against an opponent we did NOT tune. `ppa_head_to_head_check`
refused it `BASELINE_TUNED_BY_US`, correctly, for two months.

The record was honest: it declared `tuned_by_this_project: true` on its own
baseline, which is the fact that convicts it. The document KIND was the lie, and
until now there was no other kind to file it under — that absence WAS the finding
and it is why `ablation.v1` is offered as a proposal (argued in
ppa-gate-audit/RESULT.md Part 20) rather than slipped in.

THE ONE PROPERTY THAT MAKES A SCHEMA WORTH HAVING HERE is that the two kinds are
mutually exclusive BY SHAPE, in both directions:

    comparison.v2   a `baseline` arm MUST declare tuned_by_this_project: false
    ablation.v1     EVERY arm MUST declare tuned_by_this_project: true

so a document cannot satisfy both. Without the second clause this schema would be
a hiding place: a real head-to-head re-filed as an ablation would escape the
fairness conditions `ppa_head_to_head_check` applies. That is the failure this
file is mostly about, and it is asserted in both directions below.

chip-AGNOSTIC: no design, PDK, vendor or node literal.
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
SCHEMAS = PLUGIN / "schemas" / "ppa"
REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(PROGRAMS))

from _ppa import jsonschema_bundled as J  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_abl_hh", PROGRAMS / "ppa_head_to_head_check.py")
HH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(HH)

ABLATION = json.loads((SCHEMAS / "ablation.v1.schema.json").read_text("utf-8"))
COMPARISON = json.loads((SCHEMAS / "comparison.v2.schema.json").read_text("utf-8"))

#: The re-filed record. Absent on a checkout without the campaign trees, which
#: is a SKIP and not a pass — the shape tests below still run on fixtures.
REFILED = (REPO / "docs" / "campaigns" / "ppa-crosslayer" / "records" / "ablations"
           / "ablation_pnr_only_vs_crosslayer.json")


def _errs(schema, doc):
    return [str(e) for e in J.iter_errors(schema, doc)]


def _ablation(**over):
    doc = {
        "schema": "vibeic.ppa.ablation.v1",
        "claim_scope": "within_project",
        "isolates": "the one decision these arms differ on",
        "arms": [
            {"flow": "arm-one", "role": "arm_a", "config_source": "chosen here",
             "tuned_by_this_project": True, "ppa": {}},
            {"flow": "arm-two", "role": "arm_b", "config_source": "chosen here",
             "tuned_by_this_project": True, "ppa": {}},
        ],
    }
    doc.update(over)
    return doc


# ---------------------------------------------------------------------------
# The schema itself
# ---------------------------------------------------------------------------
def test_the_bundled_validator_can_apply_every_keyword_this_schema_uses():
    """A schema carrying a construct the shipped engine cannot apply is a schema
    that reports clean over a rule it never ran."""
    assert J.unsupported(ABLATION) == []


def test_a_well_formed_ablation_validates():
    assert _errs(ABLATION, _ablation()) == []


@pytest.mark.parametrize("key", ["schema", "claim_scope", "arms"])
def test_the_three_required_keys_are_required(key):
    doc = _ablation()
    del doc[key]
    assert _errs(ABLATION, doc), f"{key} was dropped and the schema accepted it"


def test_claim_scope_must_be_stated_and_cannot_say_anything_else():
    """`within_project` is the sentence a reader is entitled to BEFORE the
    numbers. A file free to say something else here is free to imply it ranks
    this project against somebody."""
    assert _errs(ABLATION, _ablation(claim_scope="head_to_head"))
    assert _errs(ABLATION, _ablation(claim_scope=""))


def test_one_arm_is_not_an_ablation():
    doc = _ablation()
    doc["arms"] = doc["arms"][:1]
    assert _errs(ABLATION, doc)


def test_a_collapsed_scalar_is_refused_here_too():
    """Area, timing and power trade against each other. A single number is the
    figure that gets quoted, whichever document kind carries it."""
    for bad in ("score", "ppa_score", "overall", "figure_of_merit", "fom",
                "composite"):
        doc = _ablation()
        doc["arms"][0][bad] = 1.0
        assert _errs(ABLATION, doc), f"{bad!r} was accepted on an ablation arm"


def test_an_ablation_may_not_declare_a_winner():
    """The document kind exists because a within-project ranking is NOT a win
    over anyone. A `verdict` / `winner` / `beats` key would smuggle the claim
    back in through the top level."""
    for bad in ("verdict", "winner", "beats"):
        assert _errs(ABLATION, _ablation(**{bad: {"a": "b"}}))


# ---------------------------------------------------------------------------
# THE LOAD-BEARING PAIR — mutual exclusivity, asserted in BOTH directions
# ---------------------------------------------------------------------------
def test_an_ablation_cannot_also_validate_as_a_head_to_head():
    """Every arm declares `true`, and comparison.v2 requires a baseline arm to
    declare `false`. If this ever passed, an ablation could be read as a
    head-to-head by anything that trusts the schema."""
    doc = _ablation()
    doc["arms"][0]["role"] = "baseline"
    doc["arms"][1]["role"] = "subject"
    doc["schema"] = "vibeic.ppa.comparison.v2"
    assert _errs(COMPARISON, doc), (
        "a document with a self-tuned baseline validated as comparison.v2")


def test_a_REAL_head_to_head_cannot_HIDE_here():
    """THE FAILURE THIS SCHEMA WOULD OTHERWISE CREATE.

    An arm this project did not tune is an OPPONENT, and a document holding one
    is a head-to-head that must face `ppa_head_to_head_check`'s fairness
    conditions. Without the `const: true` clause, re-filing it as an ablation
    would be a way out of them -- a hiding place built by the very fix that
    closed the mis-filing.
    """
    doc = _ablation()
    doc["arms"][0]["tuned_by_this_project"] = False      # an opponent
    errs = _errs(ABLATION, doc)
    assert errs, (
        "an arm this project did NOT tune was accepted as part of an ablation; "
        "that is a head-to-head with the fairness conditions switched off")
    assert any("tuned_by_this_project" in e for e in errs), errs


# ---------------------------------------------------------------------------
# The re-filed record itself
# ---------------------------------------------------------------------------
def _refiled():
    if not REFILED.is_file():
        pytest.skip(f"{REFILED} is absent on this checkout; the campaign trees "
                    f"are not part of the plugin. NOT a pass.")
    return json.loads(REFILED.read_text(encoding="utf-8"))


def test_the_refiled_record_validates_as_an_ablation():
    assert _errs(ABLATION, _refiled()) == []


def test_the_refiled_record_would_STILL_be_refused_as_a_head_to_head():
    """The re-filing is a correction, not an escape. Judged as what it was filed
    as before, the very same bytes are still refused, for the very same reason.
    If this ever stopped being true the move would have been a way out."""
    doc = copy.deepcopy(_refiled())
    doc["schema"] = "vibeic.ppa.comparison.v2"
    errs = _errs(COMPARISON, doc)
    assert any("tuned_by_this_project" in e for e in errs), (
        f"the re-filed record no longer fails comparison.v2's baseline rule, "
        f"so re-filing it changed what it claims: {errs}")


def test_the_refiled_record_carries_its_provenance():
    """A record that changes document kind without saying so reads to the next
    person as one that was always this kind."""
    prov = _refiled().get("provenance") or {}
    assert prov.get("former_schema") == "vibeic.ppa.comparison.v2"
    assert prov.get("refused_as") == "BASELINE_TUNED_BY_US"
    assert "h2h_F" in prov.get("former_path", "")


def test_the_numbers_did_not_change_in_the_move():
    """A re-filing may not touch a measurement. The refusal report kept beside
    the record states the arms it was refused over, and they must still be the
    arms the record carries."""
    doc = _refiled()
    assert [a["ppa"]["area_um2"]["value"] for a in doc["arms"]] == [6136.0, 6040.0]
    assert [a["ppa"]["power_mw"]["value"] for a in doc["arms"]] == [0.559, 0.54]
    assert all(a["tuned_by_this_project"] is True for a in doc["arms"])


def test_the_refusal_that_caused_the_move_is_kept_beside_it():
    """Evidence that this was a correction. A re-filing whose causing refusal
    has been deleted is indistinguishable from a record that was always this
    kind."""
    ev = REFILED.with_name(
        "ablation_pnr_only_vs_crosslayer.refusal_that_caused_it.json")
    if not REFILED.is_file():
        pytest.skip("campaign trees absent on this checkout. NOT a pass.")
    assert ev.is_file(), f"{ev} is missing"
    doc = json.loads(ev.read_text(encoding="utf-8"))
    assert doc.get("refusal", {}).get("code") == "BASELINE_TUNED_BY_US"


def test_the_head_to_head_corpus_no_longer_holds_it():
    """Selection is by DECLARED SCHEMA, so re-filing is what removes it -- not a
    rename, not a move, and certainly not an exemption."""
    if not REFILED.is_file():
        pytest.skip("campaign trees absent on this checkout. NOT a pass.")
    found = [p for p in HH.corpus_records(REPO / "docs" / "campaigns" / "ppa-crosslayer")]
    assert REFILED not in found
    assert not any(p.name.startswith("h2h_F") for p in found), (
        "the re-filed record is still being walked as a head-to-head")
