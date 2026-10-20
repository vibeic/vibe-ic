#!/usr/bin/env python3
"""test_issue2127_expectation_field_path_scoping.py

An expectation's SCOPE is checked, and a fact one layer over is not a missing
extraction (vibe-ic#2127).

WHAT WAS MEASURED
-----------------
`converge_ai_expectation` read the expectation's `layer` and PRINTED its
`field_path`. On a published Phase-1 run all 46 consumed expectations named a
`field_path` under a top-level key the addressed layer does not declare at any
depth, so every finding read

    expected <layer>.<fabricated path> to carry: <requirement>.
    The program track produced: <layer> does not carry [...]

— an authoritative sentence about a field nothing had looked at, because the
whole layer was searched and the path was decoration. Downstream, 11 of the 43
disagreements on that run named facts another layer carried IN FULL, and were
published as `about: "design"`: the tree was reported as missing facts it
demonstrably had, which points a reader at an extractor for a defect that lives
in the expectation.

Two checks close it, and they are deliberately INDEPENDENT:

  * the field_path GUARD refuses an undeclared path BY NAME and does NOT touch
    the verdict — so a moved verdict can never be blamed on the guard;
  * MISSCOPE detection reclassifies a miss the addressed layer does not explain
    but another layer does, `about: "track"`, naming the owning layer.

AND WHERE THE TOKENS ARE LOOKED FOR (#2127 addendum, from #2128)
----------------------------------------------------------------
The token test was whole-token but UNSCOPED: it searched the layer's entire
serialized content, so any field could satisfy any token, and a phrase could be
ASSEMBLED out of parts belonging to different fields. MEASURED on a real run, a
new unrelated L19 key `yielded: false` made the token "false" score and moved a
row from 2-missing to 1-missing on a coincidence. MEASURED here on neutral
fixtures, three more assemblies the layer never states:

    {"x": ["power", "domain"]}   phrase "power domain"  -> matched
    {"mode": "fast"}             phrase "mode fast"     -> matched
    {"busy": {}, "mode": {}}     phrase "busy mode"     -> matched

So the reading is SCOPED to the field the expectation names when that path
resolves, and matched WITHIN ONE UNIT (one key, or one scalar) rather than over
a joined document. When the path does not resolve there is nowhere to scope to;
the whole-layer reading is kept — moving 46 of 46 verdicts is a much larger
decision than this one — and the scope is RECORDED so a `met` obtained without
scoping is visibly the weaker claim it is.

NOTE, so nobody reads more into it: the matcher was never a SUBSTRING test.
`REF` did not match inside `REFHI` before this landing and does not now. What
it did was match across field boundaries, which has the same effect and a
different cause.

Every test here is PAIRED, in the manner of the sibling #312 file: the refusal
case is matched by an acceptance case, and the misscope case by a genuinely
absent fact, so a check that always fired would fail as loudly as one that
never fired.

Every fixture is synthesised here from neutral parts. No design, PDK, vendor or
IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_issue2127_expectation_field_path_scoping.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_expert_parse_track as T          # noqa: E402
import phase1_expert_track_evidence_check as E  # noqa: E402
import _path_layout as _pl                     # noqa: E402
import _progress_run as _pr                    # noqa: E402


_INPUT_DOC = """# Block specification

The block exposes a control surface of four addressable words. Word zero is
read-only and reports the busy flag; word three latches the trim code.
"""

# The layer the fact BELONGS to under the layer contract: a list of records,
# each with the field the expectation asks about. Deliberately shaped like a
# real emitted layer (a list under a top-level key) so the guard is exercised
# on the list-elision path.
_OWNING_LAYER = {
    "doc_id": "L4",
    "records": [
        {"name": "STATUS_WORD", "offset": "0x0", "access": "read-only"},
        {"name": "TRIM_WORD", "offset": "0xc", "access": "read-write"},
    ],
}

# The layer the expectation ADDRESSES. It declares nothing the expectation
# names, and carries none of the tokens.
_ADDRESSED_LAYER = {"doc_id": "L9", "fields": {"top_ports": ["clk", "rst_n"]}}


def _project(tmp_path, name="proj", layers=None):
    p = tmp_path / name
    (p / "input" / "docs").mkdir(parents=True)
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "input" / "docs" / "spec.md").write_text(_INPUT_DOC)
    (p / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
        json.dumps({"doc_id": "L1", "fields": {"word_count": 4}}))
    for stem, blob in (layers or {}).items():
        (p / "phase1" / "generated_docs" / f"{stem}.json").write_text(
            json.dumps(blob))
    return p


def _two_layer_project(tmp_path, name="proj"):
    return _project(tmp_path, name, layers={
        "L9_INTEGRATION_SPEC": _ADDRESSED_LAYER,
        "L4_REGMAP": _OWNING_LAYER,
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
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / "phase1_expert_parse_track.py"),
         str(project)], capture_output=True, text=True, env=env)
    return cp.returncode, cp.stdout, cp.stderr


def _report(project: Path):
    return json.loads(
        _pl.report_path(project, "phase1/expert_parse_track.json").read_text())


def _rules(rep, prefix):
    """Findings under exactly this rule id.

    ANCHORED ON `::`. A bare `startswith` matched
    `EXPERT_TRACK_AI_EXPECTATION_WITHDRAWN_WITHOUT_REASON` when asked for
    `EXPERT_TRACK_AI_EXPECTATION_WITHDRAWN` — the same prefix/suffix trap that
    made a sibling test count two findings as one."""
    return sorted(f["rule"] for f in rep["findings"]
                  if f["rule"] == prefix or f["rule"].startswith(prefix + "::"))


def _exp(eid, layer, field_path, tokens):
    return {"id": eid, "layer": layer, "field_path": field_path,
            "requirement": "the layer states the control-surface offsets",
            "evidence": ["input spec: four addressable words"],
            "expected_tokens": tokens}


# ── the guard: an undeclared field_path is refused BY NAME ──────────────────

def test_an_undeclared_field_path_is_refused_by_name(tmp_path):
    """RED ARM. A fabricated path is not silently printed as though checked."""
    p = _two_layer_project(tmp_path)
    _answer(p, [_exp("e-fabricated", "L9", "integration.register_map.offsets",
                     ["STATUS_WORD"])])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_FIELD_PATH_UNDECLARED) == [
        f"{T.RULE_AI_FIELD_PATH_UNDECLARED}::e-fabricated"], rep["findings"]
    f = [x for x in rep["findings"]
         if x["rule"].startswith(T.RULE_AI_FIELD_PATH_UNDECLARED)][0]
    # It is about the TRACK, and it NAMES the path and what the layer declares
    # — a refusal that did not say which path it refused would need the reader
    # to guess which expectation to repair.
    assert f["about"] == "track"
    assert "integration.register_map.offsets" in f["message"]
    assert "top_ports" in f["message"] or "fields" in f["message"]


def test_a_declared_field_path_is_not_refused(tmp_path):
    """GREEN ARM — the same shape of expectation, a path the layer declares."""
    p = _two_layer_project(tmp_path)
    _answer(p, [_exp("e-declared", "L4_REGMAP", "records.name",
                     ["STATUS_WORD"])])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_FIELD_PATH_UNDECLARED) == [], rep["findings"]
    assert rep["ai_convergence"]["field_path_undeclared"] == 0
    # and it was a SCOPED reading, not a whole-layer one that happened to agree
    assert rep["ai_convergence"]["unscoped_readings"] == 0


def test_a_layer_qualified_field_path_is_the_same_path(tmp_path):
    """`L4_REGMAP.records[].offset` asks for the field `records.offset`.

    Refusing the qualified spelling would refuse exactly the repair this guard
    exists to ask for — an expectation re-scoped onto the layer that owns the
    fact naturally writes the layer into the path."""
    p = _two_layer_project(tmp_path)
    _answer(p, [_exp("e-qualified", "L4_REGMAP",
                     "L4_REGMAP.records[].offset", ["STATUS_WORD"])])
    _run_track(p)
    assert _rules(_report(p), T.RULE_AI_FIELD_PATH_UNDECLARED) == []


def test_an_expectation_naming_no_field_path_is_not_refused(tmp_path):
    """ABSENT is not UNDECLARED. Nothing was named, so nothing is refused —
    "could not read it" is not "read it and it was fabricated"."""
    p = _two_layer_project(tmp_path)
    e = _exp("e-nopath", "L4_REGMAP", None, ["STATUS_WORD"])
    _answer(p, [e])
    _run_track(p)
    assert _rules(_report(p), T.RULE_AI_FIELD_PATH_UNDECLARED) == []


def test_the_refusal_does_not_move_the_verdict(tmp_path):
    """The REFUSAL is additive, isolated from the SCOPE.

    Two expectations that are both read at whole-layer scope — one naming no
    field_path at all, one naming a path that resolves nowhere — converge
    identically. Only one of them is refused. So the refusal changes what the
    report SAYS and never what it DECIDES.

    (Scope is a different axis and it does move verdicts, by design: that is
    `test_an_unrelated_field_cannot_satisfy_a_scoped_token`. The two are
    separated here on purpose — a landing that moved both at once could not
    say which one moved a row.)"""
    p = _two_layer_project(tmp_path)
    none_ = T.converge_ai_expectation(
        p, _exp("e", "L4_REGMAP", None, ["STATUS_WORD"]))
    fab = T.converge_ai_expectation(
        p, _exp("e", "L4_REGMAP", "no.such.path.here", ["STATUS_WORD"]))
    assert none_["field_path_status"] == "ABSENT"
    assert fab["field_path_status"] == "UNDECLARED"
    assert none_["scope"] == fab["scope"] == "whole_layer"
    assert none_["met"] is fab["met"] is True
    assert none_["missing_tokens"] == fab["missing_tokens"] == []


def test_a_layer_that_was_never_written_is_not_reported_as_declared(tmp_path):
    """NOT_MEASURED, never a default. A layer the program track never wrote
    cannot declare or fail to declare anything, and supplying either answer
    would report a reading that did not happen."""
    p = _two_layer_project(tmp_path)
    c = T.converge_ai_expectation(
        p, _exp("e-nolayer", "L20", "scan_chains.length", ["STATUS_WORD"]))
    assert c["field_path_status"] == "NOT_MEASURED"
    assert c["met"] is False
    assert "no L20 layer" in c["observed"]


# ── misscope: the fact IS extracted, one layer over ─────────────────────────

def test_a_fact_another_layer_carries_is_misscoped_not_a_design_finding(
        tmp_path):
    """The addressed layer misses it; the owning layer carries EVERY token."""
    p = _two_layer_project(tmp_path)
    _answer(p, [_exp("e-misscoped", "L9", "integration.register_map.offsets",
                     ["STATUS_WORD", "TRIM_WORD", "0xc"])])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_MISSCOPED) == [
        f"{T.RULE_AI_MISSCOPED}::e-misscoped"], rep["findings"]
    # and it is NOT ALSO reported as a design finding — the point of the
    # reclassification is that the design is not what is in question.
    assert _rules(rep, T.RULE_AI_UNMET) == []
    f = [x for x in rep["findings"]
         if x["rule"].startswith(T.RULE_AI_MISSCOPED)][0]
    assert f["about"] == "track"
    assert f["owning_layers"] == ["L4_REGMAP"]
    # The owner is NAMED in the prose too, because that is the whole repair
    # instruction: point the field_path here.
    assert "L4_REGMAP" in f["message"]


def test_a_fact_no_layer_carries_is_still_a_design_finding(tmp_path):
    """NEGATIVE CONTROL for the test above. A token nothing in the Phase-1
    output carries stays `about: "design"` — the misscope path must not become
    a way for a real extraction gap to leave the design column."""
    p = _two_layer_project(tmp_path)
    _answer(p, [_exp("e-absent", "L9", "integration.register_map.offsets",
                     ["STATUS_WORD", "A_TOKEN_NO_LAYER_CARRIES"])])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_MISSCOPED) == [], rep["findings"]
    assert _rules(rep, T.RULE_AI_UNMET) == [f"{T.RULE_AI_UNMET}::e-absent"]
    f = [x for x in rep["findings"]
         if x["rule"].startswith(T.RULE_AI_UNMET)][0]
    assert f["about"] == "design"


def test_a_partial_carry_is_not_an_owner(tmp_path):
    """A layer carrying SOME of the tokens does not own the fact. Scoring a
    partial match as ownership would launder real gaps into scope findings the
    moment one token happened to appear anywhere."""
    p = _two_layer_project(tmp_path)
    c = T.converge_ai_expectation(
        p, _exp("e", "L9", "integration.x",
                ["STATUS_WORD", "A_TOKEN_NO_LAYER_CARRIES"]))
    assert c["owning_layers"] == []


def test_the_addressed_layer_is_never_its_own_owner(tmp_path):
    """A met expectation has nothing to re-scope, and an unmet one cannot be
    owned by the layer that just missed it."""
    p = _two_layer_project(tmp_path)
    c = T.converge_ai_expectation(
        p, _exp("e", "L4_REGMAP", "records.name", ["STATUS_WORD"]))
    assert c["scope"] == "field_path"
    assert c["met"] is True
    assert c["owning_layers"] == []


# ── the ledger, and the consumer one level down ─────────────────────────────

def test_the_ledger_counts_the_two_new_populations(tmp_path):
    """A fact that exists only inside finding prose is a fact nobody counts."""
    p = _two_layer_project(tmp_path)
    _answer(p, [
        _exp("e-misscoped", "L9", "integration.register_map.offsets",
             ["STATUS_WORD", "TRIM_WORD"]),
        _exp("e-absent", "L9", "integration.other",
             ["A_TOKEN_NO_LAYER_CARRIES"]),
        _exp("e-declared", "L4_REGMAP", "records.name", ["STATUS_WORD"]),
    ])
    _run_track(p)
    led = _report(p)["ai_convergence"]
    assert led["consumed"] == 3
    # `agreed` / `disagreed` are decided on `met` exactly as before: the two
    # new populations are SUB-populations of `disagreed`, never a third column
    # carved out of it.
    assert led["agreed"] == 1
    assert led["disagreed"] == 2
    assert led["misscoped"] == 1
    assert led["field_path_undeclared"] == 2


def test_a_misscoped_expectation_is_still_a_disagreement(tmp_path):
    """Reclassifying WHO must repair it does not turn it into an agreement."""
    p = _two_layer_project(tmp_path)
    _answer(p, [_exp("e-misscoped", "L9", "integration.register_map.offsets",
                     ["STATUS_WORD", "TRIM_WORD"])])
    _run_track(p)
    led = _report(p)["ai_convergence"]
    assert led["agreed"] == 0 and led["disagreed"] == 1


def test_the_evidence_consumer_still_sees_a_real_design_finding(tmp_path):
    """One misscoped expectation and one genuinely absent fact: the evidence
    check must still read RAN. If reclassification could empty the design
    column on its own, a run with a real gap would report a real zero — the
    two-zeros conflation the expert track exists to prevent."""
    p = _two_layer_project(tmp_path)
    _answer(p, [
        _exp("e-misscoped", "L9", "integration.register_map.offsets",
             ["STATUS_WORD", "TRIM_WORD"]),
        _exp("e-absent", "L9", "integration.other",
             ["A_TOKEN_NO_LAYER_CARRIES"]),
    ])
    _run_track(p)
    st = E.assess(p, _PROGRAMS)
    assert st["state"] == "RAN", st
    assert st["patch_count"] == 1, st


def test_a_run_whose_only_disagreements_are_misscoped_says_so(tmp_path):
    """PAIRED with the test above. With nothing left in the design column the
    consumer reports RAN_EMPTY — a real zero, and correct: nothing about the
    design was found. The state must be reachable, or the reclassification
    would be unfalsifiable."""
    p = _two_layer_project(tmp_path)
    _answer(p, [_exp("e-misscoped", "L9", "integration.register_map.offsets",
                     ["STATUS_WORD", "TRIM_WORD"])])
    _run_track(p)
    st = E.assess(p, _PROGRAMS)
    assert st["state"] == "RAN_EMPTY", st
    assert st["patch_count"] == 0, st


def test_the_track_still_exits_zero_and_stays_advisory(tmp_path):
    """Neither new finding blocks. The track's enforcement contract is
    unchanged by this landing."""
    p = _two_layer_project(tmp_path)
    _answer(p, [_exp("e-misscoped", "L9", "integration.register_map.offsets",
                     ["STATUS_WORD", "TRIM_WORD"])])
    rc, out, _ = _run_track(p)
    rep = _report(p)
    assert rc == 0, out
    assert rep["blocking"] is False


# ── WHERE the tokens are looked for (#2127 addendum, from #2128) ────────────

def _scoped_project(tmp_path, name="proj"):
    """A layer that STATES the fact at one field and carries an unrelated
    field whose value happens to be one of the expected tokens."""
    return _project(tmp_path, name, layers={"L19_CONSTRAINTS_PDK": {
        "doc_id": "L19",
        "fields": {
            "budget": {"masking": "disabled"},
            "yielded": False,          # the unrelated field
            "notes": "unrelated prose mentioning disabled elsewhere",
        },
    }})


def test_an_unrelated_field_cannot_satisfy_a_scoped_token(tmp_path):
    """RED ARM — the mutation. The token is planted in a field the expectation
    does not name; scoped at the named path it must NOT score."""
    p = _scoped_project(tmp_path)
    c = T.converge_ai_expectation(p, {
        "id": "e-scoped", "layer": "L19", "field_path": "fields.budget.masking",
        "requirement": "the budget states the masking disposition",
        "evidence": ["input spec"], "expected_tokens": ["disabled", "false"]})
    assert c["scope"] == "field_path"
    assert c["met"] is False
    # "disabled" IS at the named field; "false" is only at `yielded`.
    assert c["missing_tokens"] == ["false"], c


def test_the_same_token_at_the_named_field_does_score(tmp_path):
    """GREEN ARM — the pair. Same layer, same matcher, the token where the
    expectation says it should be. A scope that refused everything would fail
    here just as loudly."""
    p = _scoped_project(tmp_path)
    c = T.converge_ai_expectation(p, {
        "id": "e-scoped-ok", "layer": "L19",
        "field_path": "fields.budget.masking",
        "requirement": "the budget states the masking disposition",
        "evidence": ["input spec"], "expected_tokens": ["disabled"]})
    assert c["scope"] == "field_path"
    assert c["met"] is True, c


def test_an_unscoped_reading_is_recorded_as_unscoped(tmp_path):
    """The whole-layer fallback is kept, and it SAYS SO. A `met` reached
    without scoping is a weaker claim than one reached at the named field, and
    the report must not spell the two the same way."""
    p = _scoped_project(tmp_path)
    c = T.converge_ai_expectation(p, {
        "id": "e-unscoped", "layer": "L19",
        "field_path": "constraints.parameters.masking",   # resolves nowhere
        "requirement": "the layer states the masking disposition",
        "evidence": ["input spec"], "expected_tokens": ["false"]})
    assert c["scope"] == "whole_layer"
    assert c["field_path_status"] == "UNDECLARED"
    assert c["met"] is True          # unchanged from before this landing
    assert "UNSCOPED" in c["observed"]
    assert "does not resolve" in c["observed"]


def test_a_phrase_is_never_assembled_across_two_fields(tmp_path):
    """The four measured assemblies, as one table. Each document does NOT
    state the phrase; before this landing every one of them matched."""
    u = T._haystack_units
    assert T.present_in_units("power domain", u({"x": ["power", "domain"]})) is False
    assert T.present_in_units("mode fast", u({"mode": "fast"})) is False
    assert T.present_in_units("busy mode", u({"busy": {}, "mode": {}})) is False
    assert T.present_in_units("false", u({"yielded": False, "a": "b"})) is True
    # ^ still True: within ONE unit. Only SCOPING excludes an unrelated field,
    #   which is what the two arms above pin.


def test_the_properties_the_matcher_was_built_for_survive(tmp_path):
    """PAIRED with the test above. Per-unit matching must not have quietly
    become a substring test, nor started scoring a separator difference as a
    disagreement — both are the reasons `phrase_present` exists."""
    u = T._haystack_units
    assert T.present_in_units("REF", u({"x": "REFHI"})) is False
    assert T.present_in_units("1.8 V", u({"x": "1.8V"})) is True
    assert T.present_in_units("power domain",
                              u({"x": "the power domain here"})) is True
    assert T.present_in_units("TRIM_SEL", u({"trim sel": 1})) is True


def test_a_path_that_resolves_to_nothing_is_not_an_empty_subtree(tmp_path):
    """`None` and `[]` are different answers. A path that does not resolve must
    not be handed back as a field that resolved and was empty — that is the
    default this repo keeps measuring the cost of."""
    blob = {"fields": {"budget": {}}}
    assert T.subtree_at(blob, "fields.budget") == [{}]
    assert T.subtree_at(blob, "fields.nothing") is None
    assert T.subtree_at(blob, None) is None


def test_the_ledger_counts_unscoped_readings(tmp_path):
    """A reading nobody can tell was unscoped is a reading that passes for
    something stronger."""
    p = _scoped_project(tmp_path)
    _answer(p, [
        {"id": "e-scoped", "layer": "L19", "field_path": "fields.budget.masking",
         "requirement": "r", "evidence": ["i"], "expected_tokens": ["disabled"]},
        {"id": "e-unscoped", "layer": "L19", "field_path": "constraints.x",
         "requirement": "r", "evidence": ["i"], "expected_tokens": ["disabled"]},
    ])
    _run_track(p)
    led = _report(p)["ai_convergence"]
    assert led["unscoped_readings"] == 1, led
    assert led["field_path_undeclared"] == 1, led


def test_the_status_and_the_resolver_can_never_disagree(tmp_path):
    """ONE convention, ONE evaluation.

    An earlier revision of this landing answered "does the layer declare this
    path" from a SECOND walk that collected declared paths, and within a day
    the two disagreed: `budget.masking` on a document whose real path is
    `fields.budget.masking` read DECLARED and then resolved to nothing, so the
    reading silently fell back to whole-layer while the guard said the path was
    there. Two answers about one path is the same disease as a field_path
    nothing reads. `field_path_status` is now derived from `subtree_at`, and
    this test is what keeps it that way."""
    blob = {"doc_id": "L19", "fields": {"budget": {"masking": "disabled"}}}
    for fp in ("fields.budget.masking", "budget.masking", "fields.budget",
               "L19.budget.masking", "budget", "nope.here",
               "fields.budget.masking.deeper", None, ""):
        status = T.field_path_status(blob, fp)
        resolved = T.subtree_at(blob, fp) is not None
        assert (status == "DECLARED") == resolved, (fp, status, resolved)


def test_both_spellings_of_the_payload_prefix_resolve(tmp_path):
    """The emitter nests the payload under `fields`; some synthesizers write it
    flat. An expectation may spell either, and a spelling difference between a
    schema and an expectation is not a design defect."""
    blob = {"fields": {"budget": {"masking": "disabled"}}}
    assert T.subtree_at(blob, "fields.budget.masking") == ["disabled"]
    assert T.subtree_at(blob, "budget.masking") == ["disabled"]
    flat = {"budget": {"masking": "disabled"}}
    assert T.subtree_at(flat, "budget.masking") == ["disabled"]
    assert T.subtree_at(flat, "fields.budget.masking") == ["disabled"]
    # and neither spelling invents a path that is not there
    assert T.subtree_at(flat, "fields.budget.absent") is None


# ── WITHDRAWAL (#2127 second addendum; the disposition #2132 reaches for 12) ─

def test_a_withdrawn_expectation_is_recorded_with_its_reason(tmp_path):
    """It is a DECISION, not an absence. Named, `about: "track"`, carrying the
    reason, and NOT converged against the design."""
    p = _two_layer_project(tmp_path)
    e = _exp("e-withdrawn", "L9", "integration.x", ["STATUS_WORD"])
    e["withdrawn"] = {"reason": "behavioural: no layer should carry it"}
    _answer(p, [e])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_WITHDRAWN) == [
        f"{T.RULE_AI_WITHDRAWN}::e-withdrawn"], rep["findings"]
    f = [x for x in rep["findings"]
         if x["rule"].startswith(T.RULE_AI_WITHDRAWN)][0]
    assert f["about"] == "track"
    assert "behavioural: no layer should carry it" in f["message"]
    # never ALSO a design finding, and never an "unusable answer"
    assert _rules(rep, T.RULE_AI_UNMET) == []
    assert _rules(rep, T.RULE_AI_UNUSABLE) == []
    assert rep["ai_convergence"]["withdrawn"] == 1


def test_a_withdrawal_with_no_reason_is_refused_and_still_decided(tmp_path):
    """RED ARM. Withdrawal is the one operation that can remove a row from what
    this track reports, so it is the one that must not be silent. A reasonless
    withdrawal is REFUSED and the row is converged exactly as if it had never
    carried one — the expectation cannot disappear by asserting it should."""
    p = _two_layer_project(tmp_path)
    e = _exp("e-noreason", "L9", "integration.x", ["A_TOKEN_NO_LAYER_CARRIES"])
    e["withdrawn"] = True
    _answer(p, [e])
    _run_track(p)
    rep = _report(p)
    assert _rules(rep, T.RULE_AI_WITHDRAWN_NO_REASON) == [
        f"{T.RULE_AI_WITHDRAWN_NO_REASON}::e-noreason"], rep["findings"]
    # STILL decided, and still a design finding
    assert _rules(rep, T.RULE_AI_UNMET) == [f"{T.RULE_AI_UNMET}::e-noreason"]
    # and NOT counted as an honoured withdrawal
    assert rep["ai_convergence"]["withdrawn"] == 0
    assert _rules(rep, T.RULE_AI_WITHDRAWN) == []


def test_a_withdrawn_row_is_not_an_undecidable_row(tmp_path):
    """PAIRED. Both are "not decided" and they are not the same event: one is an
    answer this comparator could not read, the other is a decision its author
    took and stated. Under one column a reader cannot tell them apart."""
    p = _two_layer_project(tmp_path)
    wd = _exp("e-wd", "L9", "integration.x", ["STATUS_WORD"])
    wd["withdrawn"] = {"reason": "behavioural"}
    prose = {"id": "e-prose", "layer": "L9", "field_path": "integration.y",
             "requirement": "stated in prose only", "evidence": ["i"]}
    _answer(p, [wd, prose])
    _run_track(p)
    led = _report(p)["ai_convergence"]
    assert led["consumed"] == 2
    assert led["withdrawn"] == 1
    assert led["undecidable"] == 1
    assert led["agreed"] == 0 and led["disagreed"] == 0


def test_the_reason_may_be_the_string_itself(tmp_path):
    """Both spellings are accepted — `{"reason": "..."}` and a bare string. An
    author who wrote the reason where it reads naturally has still stated it,
    and refusing that spelling would push people toward the bare marker."""
    p = _two_layer_project(tmp_path)
    e = _exp("e-str", "L9", "integration.x", ["STATUS_WORD"])
    e["withdrawn"] = "behavioural: outside the closed vocabulary"
    c = T.converge_ai_expectation(p, e)
    assert c["withdrawn_reason"] == "behavioural: outside the closed vocabulary"
    blank = _exp("e-blank", "L9", "integration.x", ["STATUS_WORD"])
    blank["withdrawn"] = "   "
    assert T.converge_ai_expectation(p, blank)["withdrawn_reason"] == ""


def test_an_expectation_that_is_not_withdrawn_says_so(tmp_path):
    """`None` means "not withdrawn"; `""` means "withdrawn with no reason".
    Two different facts, and neither is a default for the other."""
    p = _two_layer_project(tmp_path)
    c = T.converge_ai_expectation(
        p, _exp("e", "L4_REGMAP", "records.name", ["STATUS_WORD"]))
    assert c["withdrawn_reason"] is None
    assert c["met"] is True


# #3383: opt-in RFC6901 addresses, independent of legacy dotted paths.
import pytest


def _pointer_project(tmp_path):
    return _project(tmp_path, layers={"L4_REGMAP": {"registers": [
        {"name": "CONTROL_A", "fields": [{"field_name": "MODE", "msb": 1,
          "lsb": 1, "access": "RW", "reset": "0x0"}]},
        {"name": "CONTROL_B", "fields": [{"field_name": "MODE", "msb": 7,
          "lsb": 7, "access": "RO", "reset": "0x1"}]}],
        "metadata": {"name": "CONTROL_A", "msb": 1, "lsb": 1,
                     "access": "RW", "reset": "0x0"}}})


def _pointer_split():
    leaves = [("/registers/0/name", "CONTROL_A"),
              ("/registers/0/fields/0/field_name", "MODE"),
              ("/registers/0/fields/0/msb", "1"),
              ("/registers/0/fields/0/lsb", "1"),
              ("/registers/0/fields/0/access", "RW"),
              ("/registers/0/fields/0/reset", "0x0")]
    return {"id": "one-record", "requirement": "CONTROL_A.MODE bit1 RW reset0",
            "evidence": ["input/docs/spec.md: declared register field"],
            "sub_expectations": [{"layer": "L4_REGMAP", "field_path": path,
                                  "expected_tokens": [token]}
                                 for path, token in leaves]}


def test_issue3383_exact_record_does_not_borrow_sibling_value(tmp_path):
    p = _pointer_project(tmp_path)
    path = "/registers/0/fields/0/msb"
    yes = T.converge_ai_expectation(p, _exp("yes", "L4", path, ["1"]))
    no = T.converge_ai_expectation(p, _exp("no", "L4", path, ["7"]))
    assert yes["met"] is True and yes["scope"] == "json_pointer"
    assert no["usable"] is True and no["met"] is False
    assert no["missing_tokens"] == ["7"]


def test_issue3383_split_preserves_one_parent_and_each_leaf(tmp_path):
    r = T.converge_ai_expectation(_pointer_project(tmp_path), _pointer_split())
    assert r["usable"] is True and r["met"] is True
    assert len(r["sub_results"]) == 6
    assert all(b["field_path_status"] == "DECLARED"
               and b["scope"] == "json_pointer" for b in r["sub_results"])


@pytest.mark.parametrize("key,bad", [("name", "OTHER_CONTROL"), ("msb", 7),
                                    ("lsb", 7), ("access", "RO"),
                                    ("reset", "0x1")])
def test_issue3383_changed_selected_leaf_not_rescued_by_metadata(tmp_path, key, bad):
    p = _pointer_project(tmp_path)
    file = p / "phase1/generated_docs/L4_REGMAP.json"
    original = file.read_bytes()
    data = json.loads(original)
    target = data["registers"][0] if key == "name" else data["registers"][0]["fields"][0]
    target[key] = bad
    file.write_text(json.dumps(data))
    r = T.converge_ai_expectation(p, _pointer_split())
    assert r["usable"] is True and r["met"] is False
    file.write_bytes(original)
    assert T.converge_ai_expectation(p, _pointer_split())["met"] is True


@pytest.mark.parametrize("path", ["/missing", "/registers/9/name",
    "/registers/00/name", "/registers/-1/name", "/registers/-/name",
    "/registers/+0/name", "/registers/0/name/child", "/registers/0/~2",
    "/registers/0/name~", "/Registers/0/name", "/fields/registers/0/name",
    "/registers[0]/name"])
def test_issue3383_invalid_pointer_refuses_without_whole_layer_agreement(tmp_path, path):
    p = _pointer_project(tmp_path)
    r = T.converge_ai_expectation(p, _exp("bad", "L4", path, ["CONTROL_A"]))
    assert r["usable"] is False and r["met"] is False
    assert r["field_path_status"] == "UNDECLARED"
    assert r["scope"] == "json_pointer_refused"
    assert "JSON Pointer" in r["observed"]
    assert T.refuse_undeclared_field_path(T.authoring_schema(p), "L4", path)


@pytest.mark.parametrize("pointer,value", [("/a~1b", 1), ("/m~0n", 2),
    ("/~01", 3), ("/", 4), ("/01", 5), ("/list/0", None),
    ("/Case", 6), ("/case", 7), ("/\u00e9", 8), ("/e\u0301", 9)])
def test_issue3383_rfc_pointer_keys_escape_order_and_null(pointer, value):
    blob = {"a/b": 1, "m~n": 2, "~1": 3, "": 4, "01": 5,
            "list": [None], "Case": 6, "case": 7, "\u00e9": 8, "e\u0301": 9}
    assert T.subtree_at(blob, pointer) == [value]
    assert T.field_path_status(blob, pointer) == "DECLARED"


def test_issue3383_schema_vocabulary_and_resolver_are_one_authority(tmp_path):
    p = _pointer_project(tmp_path)
    schema = T.authoring_schema(p)
    doc = json.loads((p / "phase1/generated_docs/L4_REGMAP.json").read_text())
    info = schema["layers"]["L4_REGMAP"]
    paths = info["declared_json_pointer_paths"]
    assert "/registers/0/fields/0/reset" in paths
    assert info["declared_json_pointer_count"] == len(paths)
    for path in paths:
        assert T.subtree_at(doc, path) is not None
        assert T.field_path_status(doc, path) == "DECLARED"
        assert T.refuse_undeclared_field_path(schema, "L4", path) is None
    assert T.refuse_undeclared_field_path(schema, "L4", "/registers/999/name")
    assert "/registers/0/name" not in info["declared_field_paths"]


def test_issue3383_ambiguous_json_member_refused_only_by_pointer(tmp_path):
    p = _pointer_project(tmp_path)
    file = p / "phase1/generated_docs/L4_REGMAP.json"
    file.write_text('{"records":[{"name":"FIRST","name":"LAST","bit":1}]}')
    r = T.converge_ai_expectation(p, _exp("ambiguous", "L4", "/records/0/name", ["LAST"]))
    assert r["usable"] is False and r["met"] is False
    assert T.refuse_undeclared_field_path(T.authoring_schema(p), "L4", "/records/0/name")
    # Last-key legacy JSON behavior is unchanged; pointers do not change it.
    legacy = T.converge_ai_expectation(p, _exp("old", "L4", "records.name", ["LAST"]))
    assert legacy["met"] is True and legacy["scope"] == "field_path"


def test_issue3383_legacy_bracket_index_still_elides_to_all_records(tmp_path):
    p = _pointer_project(tmp_path)
    r = T.converge_ai_expectation(p, _exp("old", "L4", "registers[0].fields.msb", ["7"]))
    assert r["met"] is True and r["scope"] == "field_path"
    assert T.subtree_at({"fields": {"X": 1}}, "/X") is None
    assert T.subtree_at({"fields": {"X": 1}}, "X") == [1]
