#!/usr/bin/env python3
"""test_issue2150_split_expectation_grammar.py

One expectation can now ask N layers, and agrees only when EVERY branch does
(vibe-ic#2150, class 3).

WHAT WAS MEASURED, ON PRISTINE MAIN
-----------------------------------
An expectation carries ONE `layer`. When the program track extracted a fact
whose halves live in two different layers, no expectation could say so: asked
of either layer it is `met: False`, and `owning_layers` is empty because no
SINGLE layer carries every token, so the row falls through to `about: "design"`
— "the program track is missing this" — about a fact the program track has, in
full, twice over.

MEASURED on the surviving opentitan_aes Phase-1 root, one fact, two spellings:

    UNSPLIT  L1.fields ["one-hot", "SoC integration spec"]
             met=False  missing=['SoC integration spec']  owning_layers=[]
             -> about="design"  EXPERT_TRACK_AI_EXPECTATION_UNMET
    SPLIT    [L1.fields ["one-hot"], L19.fields.notes ["SoC integration spec"]]
             met=True   -> no design finding at all

A conjunction that cannot be written down is not a fact the corpus lacks; it is
a sentence the grammar cannot say, and the report blamed the design for the
difference. #2127 recorded exactly this as an open follow-up: "2 need a SPLIT
the grammar lacks (one expectation cannot ask two layers)".

THE SPLIT IS A CONJUNCTION, NOT A DISJUNCTION
---------------------------------------------
Every branch must agree. An "any branch" form would make a two-branch
expectation EASIER to satisfy than either of its halves — a comparator that
gets weaker as an author writes more, which is the opposite of what this track
is for. The test that pins this is paired: one branch missing is enough to make
the whole split disagree.

WHAT ELSE IS PINNED
-------------------
  * EVERY ill-formed split is a refusal to DECIDE (`usable: False`, reported
    under RULE_AI_UNUSABLE), never a verdict. Silently treating a broken split
    as "not met" would put a design finding on the record for an authoring
    mistake, which is the family of defect this whole issue is;
  * each branch is SCOPED on its own — the #2127 reading, per branch;
  * the field_path guard fires PER BRANCH, named `<parent id>#<i>`, so an
    author repairs the one branch rather than re-reading all of them, and it
    stays ADDITIVE: it never moves the verdict;
  * MEMBERSHIP: a split produces exactly ONE verdict finding, never one per
    branch — a row that decided once must be counted once;
  * a SINGLE expectation is decided exactly as before this landing.

Every fixture is synthesised here from neutral parts. No design, PDK, vendor or
IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_issue2150_split_expectation_grammar.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_expert_parse_track as T   # noqa: E402
import _path_layout as _pl              # noqa: E402
import _progress_run as _pr             # noqa: E402


_INPUT_DOC = """# Block specification

The block exposes a control surface of four addressable words, and its
constraint budget is stated by the integrating system rather than here.
"""

#: HALF the fact.
_LAYER_A = {"doc_id": "L4", "records": [{"name": "STATUS_WORD",
                                         "offset": "0x0"}]}
#: THE OTHER HALF, in a different layer. Neither carries both.
_LAYER_B = {"doc_id": "L19",
            "fields": {"notes": "budget deferred to the integrating system"}}


def _project(tmp_path, name="proj"):
    p = tmp_path / name
    (p / "input" / "docs").mkdir(parents=True)
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "input" / "docs" / "spec.md").write_text(_INPUT_DOC)
    (p / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
        json.dumps({"doc_id": "L1", "word_count": 4}))
    (p / "phase1" / "generated_docs" / "L4_REGMAP.json").write_text(
        json.dumps(_LAYER_A))
    (p / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps(_LAYER_B))
    return p


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
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / "phase1_expert_parse_track.py"),
         str(project)], capture_output=True, text=True, env=env)
    return cp.returncode, cp.stdout, cp.stderr


def _report(project: Path):
    return json.loads(
        _pl.report_path(project, "phase1/expert_parse_track.json").read_text())


def _rules(rep, prefix):
    return sorted(f["rule"] for f in rep["findings"]
                  if f["rule"] == prefix or f["rule"].startswith(prefix + "::"))


#: The one fact, spread over two layers.
_TOKEN_A = "STATUS_WORD"
_TOKEN_B = "deferred to the integrating system"

_UNSPLIT = {"id": "e-unsplit", "layer": "L4_REGMAP", "field_path": "records",
            "requirement": "the control surface and where its budget is set",
            "evidence": ["input spec"],
            "expected_tokens": [_TOKEN_A, _TOKEN_B]}

_SPLIT = {"id": "e-split",
          "requirement": "the control surface and where its budget is set",
          "evidence": ["input spec"],
          "sub_expectations": [
              {"layer": "L4_REGMAP", "field_path": "records",
               "expected_tokens": [_TOKEN_A]},
              {"layer": "L19_CONSTRAINTS_PDK", "field_path": "fields.notes",
               "expected_tokens": [_TOKEN_B]},
          ]}


# ── the reverse pair: the same fact, both spellings, in one run ─────────────

def test_the_unsplit_form_of_this_fact_is_still_a_false_design_gap(tmp_path):
    """THE REVERSE TEST. The grammar the split replaces must still be red.

    If this ever goes green the split has stopped being the thing that made
    the difference, and the paired test below would be proving nothing."""
    p = _project(tmp_path)
    c = T.converge_ai_expectation(p, _UNSPLIT)
    assert c["met"] is False
    assert c["missing_tokens"] == [_TOKEN_B]
    # No SINGLE layer carries both, which is exactly why it reads as a design
    # gap rather than as a misscope.
    assert c["owning_layers"] == []


def test_the_split_form_of_the_same_fact_agrees(tmp_path):
    p = _project(tmp_path)
    c = T.converge_ai_expectation(p, _SPLIT)
    assert c["usable"] is True
    assert c["met"] is True
    assert c["sub_layers"] == ["L4_REGMAP", "L19_CONSTRAINTS_PDK"]


def test_only_the_split_form_avoids_the_design_finding(tmp_path):
    """Both spellings in ONE run, so nothing but the grammar differs."""
    p = _project(tmp_path)
    _answer(p, [_UNSPLIT, _SPLIT])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_UNMET) == [
        f"{T.RULE_AI_UNMET}::e-unsplit"], rep["findings"]
    # And the split row produced NO finding of ANY kind — it agreed. Asserted
    # separately: without it a tree that cannot read a split at all satisfies
    # the line above, because the split would then be refused as UNUSABLE
    # rather than filed as UNMET, and the test would pass for the wrong
    # reason.
    assert [f["rule"] for f in rep["findings"] if "e-split" in f["rule"]] == \
        [], rep["findings"]


# ── a conjunction, never a disjunction ─────────────────────────────────────

def test_one_disagreeing_branch_makes_the_whole_split_disagree(tmp_path):
    """PAIRED with the agreement above. A split must not be easier to satisfy
    than its own halves."""
    p = _project(tmp_path)
    exp = json.loads(json.dumps(_SPLIT))
    exp["id"] = "e-one-bad"
    exp["sub_expectations"][1]["expected_tokens"] = ["NO_LAYER_CARRIES_THIS"]
    c = T.converge_ai_expectation(p, exp)
    assert c["met"] is False
    assert "1 of 2 branch(es)" in c["observed"]
    assert "NO_LAYER_CARRIES_THIS" in c["observed"]


def test_a_split_emits_exactly_one_verdict_finding(tmp_path):
    """MEMBERSHIP. One row decided once is one row counted once."""
    p = _project(tmp_path)
    exp = json.loads(json.dumps(_SPLIT))
    exp["id"] = "e-one-bad"
    exp["sub_expectations"][0]["expected_tokens"] = ["NO_LAYER_CARRIES_THIS_A"]
    exp["sub_expectations"][1]["expected_tokens"] = ["NO_LAYER_CARRIES_THIS_B"]
    _answer(p, [exp])
    _run_track(p)
    rep = _report(p)
    verdicts = [f for f in rep["findings"]
                if f["rule"].startswith(T.RULE_AI_UNMET)
                or f["rule"].startswith(T.RULE_AI_MISSCOPED)]
    assert [f["rule"] for f in verdicts] == [
        f"{T.RULE_AI_UNMET}::e-one-bad"], rep["findings"]


# ── each branch is scoped on its own ───────────────────────────────────────

def test_each_branch_is_scoped_independently(tmp_path):
    p = _project(tmp_path)
    c = T.converge_ai_expectation(p, _SPLIT)
    assert [b["scope"] for b in c["sub_results"]] == \
        ["field_path", "field_path"]
    exp = json.loads(json.dumps(_SPLIT))
    exp["id"] = "e-unscoped-branch"
    exp["sub_expectations"][0]["field_path"] = "not.a.declared.path"
    c2 = T.converge_ai_expectation(p, exp)
    assert [b["scope"] for b in c2["sub_results"]] == \
        ["field_path_refused", "field_path"]
    assert c2["usable"] is False and c2["met"] is False


def test_the_field_path_guard_fires_per_branch_and_moves_no_verdict(tmp_path):
    p = _project(tmp_path)
    exp = json.loads(json.dumps(_SPLIT))
    exp["id"] = "e-badpath"
    exp["sub_expectations"][0]["field_path"] = "not.a.declared.path"
    _answer(p, [exp])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_FIELD_PATH_UNDECLARED) == [
        f"{T.RULE_AI_FIELD_PATH_UNDECLARED}::e-badpath#0"], rep["findings"]
    f = [x for x in rep["findings"]
         if x["rule"].startswith(T.RULE_AI_FIELD_PATH_UNDECLARED)][0]
    assert f["about"] == "track"
    # ADDITIVE: the verdict is unchanged — the whole-layer reading still finds
    # the token, so the split still agrees and there is no design finding.
    assert _rules(rep, T.RULE_AI_UNMET) == [], rep["findings"]


# ── every ill-formed split REFUSES TO DECIDE, and says why ─────────────────

def _refusal(project, exp):
    c = T.converge_ai_expectation(project, exp)
    assert c["split"] is True
    assert c["usable"] is False, c
    assert c["met"] is False
    return c["observed"]


def test_an_empty_split_is_a_zero_denominator_not_an_agreement(tmp_path):
    p = _project(tmp_path)
    why = _refusal(p, {"id": "e", "requirement": "r", "evidence": ["x"],
                       "sub_expectations": []})
    assert "empty list" in why and "decides nothing" in why


def test_a_split_that_is_not_a_list_is_refused_naming_what_arrived(tmp_path):
    p = _project(tmp_path)
    why = _refusal(p, {"id": "e", "requirement": "r", "evidence": ["x"],
                       "sub_expectations": {"layer": "L4_REGMAP"}})
    assert "object" in why


def test_a_branch_that_is_not_an_object_is_refused_by_index(tmp_path):
    p = _project(tmp_path)
    why = _refusal(p, {"id": "e", "requirement": "r", "evidence": ["x"],
                       "sub_expectations": ["L4_REGMAP"]})
    assert "branch 0" in why


def test_a_nested_split_is_refused(tmp_path):
    """Exactly one level deep. A nested one would make the row's denominator
    depend on a shape no reader of the report can see."""
    p = _project(tmp_path)
    why = _refusal(p, {"id": "e", "requirement": "r", "evidence": ["x"],
                       "sub_expectations": [
                           {"layer": "L4_REGMAP", "expected_tokens": ["x"],
                            "sub_expectations": [{"layer": "L1_DATASHEET"}]}]})
    assert "branch 0" in why and "one level deep" in why


def test_stating_both_grammars_at_once_is_refused(tmp_path):
    """Two grammars, each of which would decide the row: the report could not
    say which one produced the verdict it carries."""
    p = _project(tmp_path)
    exp = json.loads(json.dumps(_SPLIT))
    exp["layer"] = "L4_REGMAP"
    exp["expected_tokens"] = [_TOKEN_A]
    why = _refusal(p, exp)
    assert "two grammars" in why


def test_a_branch_the_comparator_cannot_decide_refuses_the_whole_split(
        tmp_path):
    """A split is decided only when every branch is — a prose-only branch
    cannot be, and quietly dropping it would make the split agree on the
    strength of the branches that were checkable."""
    p = _project(tmp_path)
    exp = json.loads(json.dumps(_SPLIT))
    exp["sub_expectations"][1].pop("expected_tokens")
    why = _refusal(p, exp)
    assert "branch 1" in why and "prose only" in why


def test_an_ill_formed_split_is_reported_never_dropped(tmp_path):
    p = _project(tmp_path)
    _answer(p, [{"id": "e-broken", "requirement": "r", "evidence": ["x"],
                 "sub_expectations": []}])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_UNUSABLE) == [
        f"{T.RULE_AI_UNUSABLE}::e-broken"], rep["findings"]
    assert [f for f in rep["findings"]
            if f["rule"].startswith(T.RULE_AI_UNUSABLE)][0]["about"] == "track"


# ── the absent-layer answer, through a branch ──────────────────────────────

def test_a_branch_naming_an_undeclared_layer_refuses_the_row(tmp_path):
    """A conjunction containing a term NO root can ever satisfy is
    unanswerable however well-formed the rest of it is."""
    p = _project(tmp_path)
    exp = json.loads(json.dumps(_SPLIT))
    exp["id"] = "e-undeclared-branch"
    exp["sub_expectations"][1]["layer"] = "L91_NOT_A_DECLARED_LAYER"
    _answer(p, [exp])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_LAYER_ABSENT) == [
        f"{T.RULE_AI_LAYER_ABSENT}::e-undeclared-branch"], rep["findings"]
    assert _rules(rep, T.RULE_AI_UNMET) == [], rep["findings"]


def test_a_declared_but_absent_branch_layer_is_a_misscope_when_a_layer_owns_it(
        tmp_path):
    """BOUNDING control, the split's own version of #312's rule.

    A layer the taxonomy declares and this root does not carry is NOT refused
    as an undeclared layer: it is decided like any other miss. Here the fact
    lives wholly in a layer the root DOES have, so the answer is the #2127
    misscope, naming the owner — which is a better answer than "the design
    lacks it", and the point is that the row keeps a VERDICT rather than
    becoming this landing's refusal."""
    p = _project(tmp_path)
    exp = json.loads(json.dumps(_SPLIT))
    exp["id"] = "e-declared-absent-owned"
    exp["sub_expectations"][1]["layer"] = "L21_POWER_INTENT"
    _answer(p, [exp])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_LAYER_ABSENT) == [], rep["findings"]
    assert _rules(rep, T.RULE_AI_MISSCOPED) == [
        f"{T.RULE_AI_MISSCOPED}::e-declared-absent-owned"], rep["findings"]
    f = [x for x in rep["findings"]
         if x["rule"].startswith(T.RULE_AI_MISSCOPED)][0]
    assert f["owning_layers"] == ["L19_CONSTRAINTS_PDK"]


def test_a_declared_but_absent_branch_layer_stays_a_design_disagreement(
        tmp_path):
    """PAIRED with the misscope above: when NO layer carries the fact, the
    same shape is a disagreement about the design, exactly as #312 has it for
    a single expectation. The two halves of this pair are what prove the
    landing reclassified undeclared layers and nothing else."""
    p = _project(tmp_path)
    exp = json.loads(json.dumps(_SPLIT))
    exp["id"] = "e-declared-absent-unowned"
    exp["sub_expectations"][1]["layer"] = "L21_POWER_INTENT"
    exp["sub_expectations"][1]["expected_tokens"] = ["NO_LAYER_CARRIES_THIS"]
    _answer(p, [exp])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_LAYER_ABSENT) == [], rep["findings"]
    assert _rules(rep, T.RULE_AI_UNMET) == [
        f"{T.RULE_AI_UNMET}::e-declared-absent-unowned"], rep["findings"]
    assert [x for x in rep["findings"]
            if x["rule"].startswith(T.RULE_AI_UNMET)][0]["about"] == "design"


# ── a SINGLE expectation is decided exactly as before ──────────────────────

def test_a_single_expectation_is_untouched_by_the_split_grammar(tmp_path):
    """CONTROL. The parent's SPLIT markers must appear only on a split."""
    p = _project(tmp_path)
    c = T.converge_ai_expectation(p, {
        "id": "e-single", "layer": "L4_REGMAP", "field_path": "records",
        "requirement": "r", "evidence": ["x"], "expected_tokens": [_TOKEN_A]})
    assert c.get("split") is None
    assert c["met"] is True
    assert c["scope"] == "field_path"
    assert c["field_path_status"] == "DECLARED"
