#!/usr/bin/env python3
"""test_issue2191_owning_layers_specificity_floor.py

An OWNERSHIP answer is read over the layer's CONTENT, and it needs a token
that can tell one layer from another (vibe-ic#2191).

WHAT WAS MEASURED
-----------------
`owning_layers` answered "which layers carry this fact" over the WHOLE emitted
document, with no floor on how specific the tokens had to be. The finding
built on that answer (`RULE_AI_MISSCOPED`) says, in as many words:

    ... and ['L19_...', 'L20_DFT_SCAN_TOPOLOGY', ...] DOES -- every one of the
    1 expected token(s). So the fact was extracted and the expectation named
    the wrong layer; this is NOT a missing extraction and must not be repaired
    in an extractor.

That directive is the load-bearing part, and it was reachable on evidence that
says nothing about the design. REPRODUCED on the live tip (lane cz2191, host
8HD-4, 2026-09-08) against a Phase-1 root of 28 emitted documents:

    owning_layers(root, ['crypto_accelerator'])
      -> L19_CONSTRAINTS_PDK L20_DFT_SCAN_TOPOLOGY L21_POWER_INTENT
         L22_VERIFICATION_PLAN L23_SECURITY_REQUIREMENTS L24_SIGNOFF
         L25_RELIABILITY_MISSION_PROFILE L26_MECHANICAL_TRANSDUCTION
         L27_MEMORY_MODULE_SPD

`L20_DFT_SCAN_TOPOLOGY` contains exactly one occurrence of that token and it is
the document's own `ic_class` stamp -- a whole field value, no surrounding
prose. L20 states nothing about the fact the expectation asked for. The same
run had `L6_CONTROL_LOGIC` OWN the token `GHASH`, its only two matches being
the SOURCE FILENAMES the emitter recorded under `extraction_evidence`.

Measured over 482 distinct Phase-1 roots (13,496 L documents) found on that
host, sampling 9,600 tokens from 120 of them:

  * 58.3% of every (layer, token) ownership relation was carried ONLY by the
    emitter's envelope -- the document's identity, its classification stamp,
    its provenance, the hints it gives an extractor, the paths of the files it
    read. Not by anything the layer states.
  * 323 of the 9,600 tokens were carried by EVERY layer of their root, and
    each of them could assert ownership. A rule that matches everything
    decides nothing. After the guards below, ZERO tokens are.
  * of 489 distinct (root, `ic_class` value) pairs, 452 (92.4%) own no layer
    at all once the envelope is out; the 37 that remain are roots whose
    CONTENT genuinely names the class, and they keep owning.
  * the widest single offender is the emitter's own version strings: the bare
    token `1` was carried by all 28 layers of the reproduction root, and in 21
    of them by the ENVELOPE ALONE -- `_generator.plugin_version` ("1.9.62"), a
    `schema_version` / `emitted_by` version suffix, or an
    `extraction_strategy` gate key. Seven carry it in content.

TWO GUARDS, deliberately INDEPENDENT, and a third state
-------------------------------------------------------
  * the haystack is `_ownership_units` -- the document minus the envelope it
    is wrapped in. `met` is untouched and is still decided over the whole
    document, so no verdict moves here and a moved verdict can never be
    attributed to this landing.
  * a token more of the searched layers carry than not is refused, and an
    expectation with no discriminating token at all gets its ownership
    question REFUSED rather than answered.
  * the refusal is a STATUS, never an empty list. `owning_layers: []` already
    means "no layer carries this fact" and the consumer publishes it as a
    finding about the DESIGN; answering a question nobody could ask with a
    design gap is the substitution this whole track exists to prevent. The
    row goes out under `RULE_AI_OWNERSHIP_UNDECIDABLE`, `about: "track"`.

Every test here is PAIRED, in the manner of the sibling #2127 and #312 files:
the refusal case is matched by an acceptance case, so a guard that always
fired would fail as loudly as one that never fired.

Every fixture is synthesised here from neutral parts. No design, PDK, vendor
or IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_issue2191_owning_layers_specificity_floor.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_expert_parse_track as T          # noqa: E402
import _path_layout as _pl                     # noqa: E402
import _progress_run as _pr                    # noqa: E402


_INPUT_DOC = """# Block specification

The block exposes a control surface of four addressable words. Word zero is
read-only and reports the busy flag; word three latches the trim code.
"""

# THE STAMP. A classification value the emitter writes into EVERY document it
# emits, as a bare unit -- a whole field value with no surrounding prose. It is
# a fact about the run, not about the layer.
_STAMP = "widget_class_alpha"

# The layer the fact actually lives in: it STATES the classification, in a
# sentence of its own, and it states the specific token too.
_STATING_LAYER = {
    "doc_id": "L4",
    "ic_class": _STAMP,
    "fields": {"rationale": f"This block is a {_STAMP}; the trim code is "
                            f"latched in TRIM_WORD. Sizing is deferred.",
               "notes": "deferred"},
}

# A layer that says nothing about the fact. It carries the stamp -- because
# every emitted document does -- and nothing else that bears on it.
_STAMPED_ONLY_LAYER = {
    "doc_id": "L20",
    "ic_class": _STAMP,
    "applicability": "APPLICABLE",
    "extraction_status": "NOT_YET_EXTRACTED",
    "extraction_hints": ["Look for scan sections."],
    "emitted_by": "some_emitter.emit_skeleton v0.1.0",
    "_generator": {"plugin": "vibe-ic", "plugin_version": "9.9.99"},
    "fields": {"scan_chains": [], "dft_present": False,
               "notes": "deferred"},
}

# The layer the expectation ADDRESSES. Carries the stamp, nothing else.
_ADDRESSED_LAYER = {
    "doc_id": "L9",
    "ic_class": _STAMP,
    "fields": {"top_ports": ["clk", "rst_n"]},
}


def _project(tmp_path, name="proj", layers=None):
    p = tmp_path / name
    (p / "input" / "docs").mkdir(parents=True)
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "input" / "docs" / "spec.md").write_text(_INPUT_DOC)
    for stem, blob in (layers or {}).items():
        (p / "phase1" / "generated_docs" / f"{stem}.json").write_text(
            json.dumps(blob))
    return p


def _stamped_project(tmp_path, name="proj"):
    return _project(tmp_path, name, layers={
        "L9_INTEGRATION_SPEC": _ADDRESSED_LAYER,
        "L20_DFT_SCAN_TOPOLOGY": _STAMPED_ONLY_LAYER,
        "L4_REGMAP": _STATING_LAYER,
    })


def _pack_dir(project: Path) -> Path:
    return _pl.report_path(project, "phase1/expert_parse_track").parent \
        / "expert_parse_track_pack"


def _answer(project: Path, expectations):
    d = _pack_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    (d / "l_doc_expectations.json").write_text(
        json.dumps({"expectations": expectations}))


def _run_track(project: Path):
    env = dict(os.environ)
    env["VIBE_IC_DISABLE_LLM_CONFIRM"] = "1"
    return _pr.run(
        [sys.executable, str(_PROGRAMS / "phase1_expert_parse_track.py"),
         str(project)], capture_output=True, text=True, env=env)


def _report(project: Path):
    return json.loads(
        _pl.report_path(project, "phase1/expert_parse_track.json").read_text())


def _rules(rep, prefix):
    """Findings under exactly this rule id, anchored on `::`."""
    return sorted(f["rule"] for f in rep["findings"]
                  if f["rule"] == prefix or f["rule"].startswith(prefix + "::"))


def _exp(eid, layer, field_path, tokens):
    return {"id": eid, "layer": layer, "field_path": field_path,
            "requirement": "the layer records why the fact is as it is",
            "evidence": ["input spec: four addressable words"],
            "expected_tokens": tokens}


# ── the envelope is not content ─────────────────────────────────────────────

def test_a_classification_stamp_does_not_own_a_fact(tmp_path):
    """RED ARM -- the reproduced defect. A layer whose ONLY occurrence of the
    token is the document's own `ic_class` stamp does not own the fact."""
    p = _stamped_project(tmp_path)
    a = T.owning_layers_answer(p, [_STAMP])
    assert a["status"] == "OK", a
    assert "L20_DFT_SCAN_TOPOLOGY" not in a["layers"], a
    assert "L9_INTEGRATION_SPEC" not in a["layers"], a


def test_a_layer_that_STATES_the_classification_still_owns_it(tmp_path):
    """GREEN ARM. The same word, in a sentence the layer states, still owns --
    the guard removes the envelope, not the content. Without this arm a guard
    that dropped the token everywhere would look identical."""
    p = _stamped_project(tmp_path)
    a = T.owning_layers_answer(p, [_STAMP])
    assert a["layers"] == ["L4_REGMAP"], a
    # and it says WHERE, so the claim can be falsified from the report.
    assert _STAMP in a["evidence"]["L4_REGMAP"][_STAMP]


def test_the_envelope_is_dropped_at_the_TOP_LEVEL_ONLY(tmp_path):
    """A CONTENT field that happens to share an envelope key's name at depth
    is content. Dropping by name at any depth would silently delete real
    extracted facts, which is the same class of error in the other direction.
    """
    p = _project(tmp_path, layers={
        "L9_INTEGRATION_SPEC": _ADDRESSED_LAYER,
        "L5_ADI_SPEC": {"doc_id": "L5", "ic_class": _STAMP,
                        "fields": {"nested": {"ic_class": "TRIM_WORD"}}},
    })
    a = T.owning_layers_answer(p, ["TRIM_WORD"])
    assert a["layers"] == ["L5_ADI_SPEC"], a


def test_a_source_filename_does_not_own_a_fact(tmp_path):
    """RED ARM. `extraction_evidence` is keyed by the PATH of the file the
    emitter read. A design fact is not owned by the name of that file."""
    p = _project(tmp_path, layers={
        "L9_INTEGRATION_SPEC": _ADDRESSED_LAYER,
        "L6_CONTROL_LOGIC": {
            "doc_id": "L6",
            "fields": {"fsm_states": []},
            "extraction_evidence": {"input/docs/trimcode_diagram.svg": []},
        },
    })
    a = T.owning_layers_answer(p, ["trimcode"])
    assert a["layers"] == [], a


def test_a_line_the_layer_QUOTED_from_the_input_still_owns(tmp_path):
    """GREEN ARM for the same subtree. The `literal` under an evidence entry
    is a line the layer recorded from the design input -- content, and it
    keeps owning. Dropping `extraction_evidence` WHOLESALE was measured on the
    corpus and costs 2.6% of tokens their only owner; dropping the path keys
    and the provenance labels costs 0.7%."""
    p = _project(tmp_path, layers={
        "L9_INTEGRATION_SPEC": _ADDRESSED_LAYER,
        "L6_CONTROL_LOGIC": {
            "doc_id": "L6",
            "fields": {"fsm_states": []},
            "extraction_evidence": {"input/docs/spec.md": [
                {"literal": "word three latches the TRIM_WORD",
                 "label": "fsm_states (input/docs/other_file.md:12)"}]},
        },
    })
    assert T.owning_layers_answer(p, ["TRIM_WORD"])["layers"] == \
        ["L6_CONTROL_LOGIC"]
    # ...and the LABEL, which names a field and a file:line, is provenance:
    # a token that appears only there does not own the layer.
    assert T.owning_layers_answer(p, ["other_file"])["layers"] == []


# EVERY key of the roster gets a witness. MEASURED on the rebased landing
# (lane cz2191b): removing any single key from `_L_DOC_ENVELOPE_KEYS` left all
# 117 tests of this module and its neighbours GREEN for 13 of the 14 keys --
# only `ic_class` had a witness, because `ic_class` is the only envelope key
# the fixtures above ever ask a token about. The roster was measured over 482
# roots and asserted by one of its fourteen entries.
#
# `_generator` is the one that makes this a test rather than a note: the corpus
# names the emitter's VERSION STRINGS as the widest single offender -- the bare
# token `1` carried by all 28 layers of the reproduction root, 21 of them
# through the envelope alone -- and `_STAMPED_ONLY_LAYER` above has carried
# `"_generator": {"plugin_version": "9.9.99"}` all along with nothing ever
# asking about it. A fixture is not a witness until an assertion reads it.
#
# THE LIST IS A LITERAL, AND THAT IS THE POINT. Parametrizing over
# `T._L_DOC_ENVELOPE_KEYS` was tried first and is UNFALSIFIABLE: a mutation
# that drops a key from the roster drops that key's test case with it, so the
# case that should have failed does not exist to fail, and emptying the roster
# outright reduces the whole test to zero cases and reads as GREEN. A test
# parametrized over the constant under test cannot see that constant change.
# So the population is pinned here and `test_the_witness_list_is_the_whole_
# roster` compares it to the program's own roster -- a key added there is then
# a LOUD red asking for its witness, instead of silently joining the
# unwitnessed thirteen.
_ENVELOPE_KEYS_UNDER_TEST = (
    "applicability", "class_path", "doc_class", "doc_id", "doc_name",
    "emitted_by", "extraction_hints", "extraction_status",
    "extraction_strategy", "ic_class", "ic_name", "schema_version",
    "source_documents", "_generator",
)


@pytest.mark.consistency
def test_the_witness_list_is_the_whole_roster():
    """The pinned population IS the program's roster -- no more, no less."""
    assert set(_ENVELOPE_KEYS_UNDER_TEST) == set(T._L_DOC_ENVELOPE_KEYS)
    assert len(_ENVELOPE_KEYS_UNDER_TEST) == len(set(_ENVELOPE_KEYS_UNDER_TEST))


@pytest.mark.parametrize("env_key", sorted(_ENVELOPE_KEYS_UNDER_TEST))
def test_every_envelope_key_is_witnessed(tmp_path, env_key):
    """No envelope key, alone, makes a silent layer the owner of a fact."""
    tok = "envelopeonlytoken"
    quiet = {"doc_id": "L20", env_key: tok,
             "fields": {"scan_chains": [], "notes": "deferred"}}
    p = _project(tmp_path, layers={
        "L9_INTEGRATION_SPEC": _ADDRESSED_LAYER,
        "L20_DFT_SCAN_TOPOLOGY": quiet,
    })
    a = T.owning_layers_answer(p, [tok])
    # OK, not a refusal: no layer carries the token once the envelope is out,
    # so the question WAS answerable and the answer is a real zero. Asserting
    # the status too keeps this from passing for the wrong reason -- a refusal
    # also carries an empty `layers`, which is the exact substitution this
    # landing exists to prevent.
    assert a["status"] == "OK", (env_key, a)
    assert a["layers"] == [], (env_key, a)


def test_the_envelope_witness_can_fail(tmp_path):
    """The paired arm: the SAME token in a CONTENT field of the same
    otherwise-silent layer DOES own it. Without this, a fixture that quietly
    stopped planting the token would leave the parametrized test asserting
    `[] == []` over an empty population and passing for every key forever."""
    tok = "envelopeonlytoken"
    p = _project(tmp_path, layers={
        "L9_INTEGRATION_SPEC": _ADDRESSED_LAYER,
        "L20_DFT_SCAN_TOPOLOGY": {"doc_id": "L20",
                                  "fields": {"notes": tok}},
    })
    a = T.owning_layers_answer(p, [tok])
    assert a["status"] == "OK", a
    assert a["layers"] == ["L20_DFT_SCAN_TOPOLOGY"], a


# ── the floor: a token that cannot tell one layer from another ──────────────

def test_a_token_more_layers_carry_than_not_is_REFUSED(tmp_path):
    """RED ARM. `deferred` is carried by BOTH searched layers here (the
    addressed layer is excluded from its own ownership question). An answer
    built on it would name every candidate while deciding nothing. Note the
    token is neither short nor numeric: the floor is about BREADTH -- what the
    corpus shows a token can distinguish -- not about how a token is spelt."""
    p = _stamped_project(tmp_path)
    a = T.owning_layers_answer(p, ["deferred"])
    assert a["status"] == "NO_DISCRIMINATING_TOKEN", a
    assert a["layers"] == [], a
    assert a["token_breadth"]["deferred"] == 2 and a["searched_layers"] == 3
    assert "more than half" in a["refusal"]


def test_ONE_discriminating_token_is_enough(tmp_path):
    """GREEN ARM. The floor asks for at least one token that can discriminate,
    not for all of them: an expectation may legitimately pair a broad word
    with a specific one, and the conjunction is still decided over EVERY
    token exactly as before."""
    p = _stamped_project(tmp_path)
    a = T.owning_layers_answer(p, ["deferred", "TRIM_WORD"])
    assert a["status"] == "OK", a
    assert a["layers"] == ["L4_REGMAP"], a


def test_a_token_no_layer_carries_is_a_real_zero_not_a_refusal(tmp_path):
    """The two zeros stay separable. A token nothing carries is `OK` with an
    empty list -- a reading, and a real zero -- and NOT a refusal."""
    p = _stamped_project(tmp_path)
    a = T.owning_layers_answer(p, ["A_TOKEN_NO_LAYER_CARRIES"])
    assert a["status"] == "OK" and a["layers"] == [], a


# ── the consumer: a refused question is not a design finding ────────────────

def test_a_refused_ownership_answer_is_not_published_as_a_design_gap(tmp_path):
    """THE POINT OF THE LANDING. The row goes out under its own rule and
    `about: "track"` -- never under `RULE_AI_UNMET` (`about: "design"`, "the
    program track is missing this") and never under `RULE_AI_MISSCOPED`
    ("must not be repaired in an extractor"). Both of those would be a verdict
    on a question nobody could answer."""
    p = _stamped_project(tmp_path)
    _answer(p, [_exp("e-vacuous", "L9_INTEGRATION_SPEC", "fields.absent",
                     ["deferred"])])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_OWNERSHIP_UNDECIDABLE) == [
        f"{T.RULE_AI_OWNERSHIP_UNDECIDABLE}::e-vacuous"], rep["findings"]
    assert _rules(rep, T.RULE_AI_UNMET) == [], rep["findings"]
    assert _rules(rep, T.RULE_AI_MISSCOPED) == [], rep["findings"]
    f = [x for x in rep["findings"]
         if x["rule"].startswith(T.RULE_AI_OWNERSHIP_UNDECIDABLE)][0]
    assert f["about"] == "track"
    assert f["owning_layers"] == []
    # and it names WHY, and what to repair.
    assert "more than half" in f["message"]
    assert "at least one token" in f["message"]


def test_a_fact_no_layer_carries_is_STILL_a_design_finding(tmp_path):
    """NEGATIVE CONTROL for the test above, and the load-bearing one: the new
    refusal must not become a way for a real extraction gap to leave the
    design column. A discriminating token nothing carries stays
    `about: "design"`."""
    p = _stamped_project(tmp_path)
    _answer(p, [_exp("e-absent", "L9_INTEGRATION_SPEC", "fields.absent",
                     ["A_TOKEN_NO_LAYER_CARRIES"])])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_OWNERSHIP_UNDECIDABLE) == [], rep["findings"]
    assert _rules(rep, T.RULE_AI_UNMET) == [
        f"{T.RULE_AI_UNMET}::e-absent"], rep["findings"]
    assert [x for x in rep["findings"]
            if x["rule"].startswith(T.RULE_AI_UNMET)][0]["about"] == "design"


def test_a_genuine_misscope_is_STILL_reported_as_one(tmp_path):
    """NEGATIVE CONTROL in the other direction. A fact another layer really
    does state is still re-scoped, `about: "track"`, naming the owner -- the
    #2127 behaviour this landing must not weaken."""
    p = _stamped_project(tmp_path)
    _answer(p, [_exp("e-misscoped", "L9_INTEGRATION_SPEC", "fields.absent",
                     ["TRIM_WORD"])])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_MISSCOPED) == [
        f"{T.RULE_AI_MISSCOPED}::e-misscoped"], rep["findings"]
    f = [x for x in rep["findings"]
         if x["rule"].startswith(T.RULE_AI_MISSCOPED)][0]
    assert f["owning_layers"] == ["L4_REGMAP"]
    # and it now says WHERE the owner carried it, so a reader can falsify the
    # claim without re-running the comparator -- the half whose absence let
    # "L20 DOES carry it" stand on a classification stamp.
    assert "TRIM_WORD" in f["owning_layers_evidence"]["L4_REGMAP"]["TRIM_WORD"]


def test_the_ledger_counts_the_refused_population(tmp_path):
    """A fact that exists only inside finding prose is a fact nobody counts.
    `ownership_undecidable` is its own column: it is neither a re-scope nor a
    design gap, and folding it into either would hide the whole population."""
    p = _stamped_project(tmp_path)
    _answer(p, [
        _exp("e-vacuous", "L9_INTEGRATION_SPEC", "fields.absent",
             ["deferred"]),
        _exp("e-misscoped", "L9_INTEGRATION_SPEC", "fields.absent",
             ["TRIM_WORD"]),
        _exp("e-absent", "L9_INTEGRATION_SPEC", "fields.absent",
             ["A_TOKEN_NO_LAYER_CARRIES"]),
    ])
    _run_track(p)
    led = _report(p)["ai_convergence"]
    assert led["consumed"] == 3
    assert led["disagreed"] == 3
    assert led["ownership_undecidable"] == 1, led
    assert led["misscoped"] == 1, led


# ── the split grammar carries the refusal up ────────────────────────────────

def test_a_split_branch_whose_ownership_was_refused_refuses_the_parent(
        tmp_path):
    """A conjunction is only as decided as its least decided term. A split
    whose failing branch had its ownership question refused must not reach the
    design column through the parent -- `owning_layers` is [] on that path for
    two different reasons and the status is what separates them."""
    p = _stamped_project(tmp_path)
    parent = {
        "id": "e-split", "requirement": "both halves are recorded",
        "evidence": ["input spec"],
        "sub_expectations": [
            {"id": "b1", "layer": "L9_INTEGRATION_SPEC",
             "field_path": "fields.top_ports", "expected_tokens": ["deferred"]},
            {"id": "b2", "layer": "L9_INTEGRATION_SPEC",
             "field_path": "fields.top_ports", "expected_tokens": ["TRIM_WORD"]},
        ]}
    c = T.converge_ai_expectation(p, parent)
    assert c["usable"] is True and c["met"] is False, c
    assert c["owning_layers_status"] == "NO_DISCRIMINATING_TOKEN", c
    assert c["owning_layers"] == [], c
    # the refusal NAMES the branch it came from -- the split machinery ids
    # branches by index, and a parent refusal that did not say which branch
    # forced it would leave the author with nothing to repair.
    assert "e-split#0" in c["owning_layers_refusal"], c["owning_layers_refusal"]


def test_a_split_whose_branches_all_discriminate_is_still_decided(tmp_path):
    """GREEN ARM. Nothing about the split grammar changes when every branch
    has a token that can discriminate."""
    p = _stamped_project(tmp_path)
    parent = {
        "id": "e-split-ok", "requirement": "both halves are recorded",
        "evidence": ["input spec"],
        "sub_expectations": [
            {"id": "b1", "layer": "L9_INTEGRATION_SPEC",
             "field_path": "fields.top_ports", "expected_tokens": ["TRIM_WORD"]},
            {"id": "b2", "layer": "L9_INTEGRATION_SPEC",
             "field_path": "fields.top_ports", "expected_tokens": [_STAMP]},
        ]}
    c = T.converge_ai_expectation(p, parent)
    assert c["usable"] is True and c["met"] is False, c
    assert c["owning_layers_status"] == "OK", c
    assert c["owning_layers"] == ["L4_REGMAP"], c
