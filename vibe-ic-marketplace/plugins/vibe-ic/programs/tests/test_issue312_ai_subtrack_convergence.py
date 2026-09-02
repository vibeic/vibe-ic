#!/usr/bin/env python3
"""test_issue312_ai_subtrack_convergence.py

The CONVERGE half of Phase-1's dual track (vibe-ic#312, second landing).

The first landing wired the AI half as far as reading the subagent's answer
back and stopped. Two measured defects made it inert, and together they
reproduced — one nesting level in — the exact shape #312 was filed about:

  1. The hand-off was gated on `llm_semantic_confirm.backend_available()`, a
     probe for an in-process SDK that nothing on this path uses: the assembler
     is deterministic and the author is a SUBAGENT. On a host without that SDK
     the track never wrote the pack (so no agent could be invoked on it) AND
     returned before the answer-file check (so an answer already on disk was
     never read). A state that no execution could leave.
  2. A consumed answer was dead data: `evaluate` built findings from the
     deterministic rules alone, so an AI expectation naming a field no L-doc
     contains produced `verdict: PASS`, `findings: 0` — which the evidence
     check then reports as "ran and named NO findings — a real zero". The
     disagreement was rendered as an agreement.

Every test here is PAIRED: the disagreement case is matched by the agreement
case, so a comparator that simply always fires would fail just as loudly as
one that never fires. The anti-gaming pair is
`test_the_comparator_ignores_a_met_the_answer_claims` — an AI half that scored
itself would agree with itself, and a consumer that reads the file and always
agrees is not a second track.

Every fixture is synthesised here from neutral parts. No design, PDK, vendor
or IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_issue312_ai_subtrack_convergence.py -q
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
import _path_layout as _pl                     # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────────
#
# A minimal project: one input document and one L-doc the program track is
# taken to have written. Deliberately NOT the nvm fixture from the sibling
# file — the convergence path must be shown to work with no deterministic rule
# applying at all, which is the state every design on the fleet is in.

_INPUT_DOC = """# Block specification

The converter accepts an external reference on the REFHI terminal and
digitises to 12 bits at 500 ksps. Trim values are restored at power-up.
"""


def _project(tmp_path, name="proj", l1=None, layers=None):
    p = tmp_path / name
    (p / "input" / "docs").mkdir(parents=True)
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "input" / "docs" / "spec.md").write_text(_INPUT_DOC)
    (p / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
        json.dumps(l1 if l1 is not None else
                   {"doc_id": "L1", "fields": {"resolution_bits": 12}}))
    for stem, blob in (layers or {}).items():
        (p / "phase1" / "generated_docs" / f"{stem}.json").write_text(
            json.dumps(blob))
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
    env["VIBE_IC_DISABLE_LLM_CONFIRM"] = "1"     # force the no-backend path
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / "phase1_expert_parse_track.py"),
         str(project)], capture_output=True, text=True, env=env)
    return cp.returncode, cp.stdout, cp.stderr


def _report(project: Path):
    return json.loads(
        _pl.report_path(project, "phase1/expert_parse_track.json").read_text())


def _ai_findings(rep, rule=T.RULE_AI_UNMET):
    return [f for f in rep["findings"] if f["rule"].startswith(rule)]


# ── defect 1: the hand-off was gated on a backend it does not use ───────────

def test_handoff_is_emitted_with_no_inline_llm_backend(tmp_path):
    """`ic_expert_backup_pack.assemble` performs no network call and the answer
    is authored by a SUBAGENT, so the in-process SDK is irrelevant to both.
    While it could veto this path, the pack was never written — and a pack that
    is never written is a subagent that can never be invoked."""
    p = _project(tmp_path)
    rc, out, _ = _run_track(p)
    rep = _report(p)
    assert rep["ai_subtrack"]["status"] == "HANDOFF_EMITTED"
    assert rep["verdict"] == "INCOMPLETE"
    # #2014 D1 — the exit code is RETARGETED, not relaxed. This test's subject
    # is that the PACK GETS WRITTEN with no inline SDK; the old `rc == 1` also
    # made an unanswered hand-off a failed run, which is what made D1
    # unpassable by any program-only invocation. Three assertions replace one.
    assert rc != 0, "an unanswered hand-off exited 0 — that reads as credit"
    assert rc == T.AWAITING_EXIT_CODE and rc != 1
    assert rep["execution"]["disposition"] == T.DISPOSITION_AWAITING
    assert "VACUOUS_PASS" not in out
    assert (_pack_dir(p) / "ic_expert_agent_handoff.json").is_file()
    # the SDK fact is not lost, only demoted from veto to record
    assert rep["ai_subtrack"]["inline_llm_backend"] is False


def test_an_answer_on_disk_is_consumed_with_no_inline_llm_backend(tmp_path):
    """The paired half. Reading a file a subagent already wrote needs no LLM at
    all; the old early return happened BEFORE the answer-file check, so an
    answer sitting right there was ignored."""
    p = _project(tmp_path)
    _answer(p, [{"id": "r::s", "layer": "L1_DATASHEET",
                 "requirement": "x", "expected_tokens": ["12"]}])
    _run_track(p)
    rep = _report(p)
    assert rep["ai_subtrack"]["status"] == "CONSUMED"
    assert rep["ai_subtrack"]["inline_llm_backend"] is False


def test_the_ai_half_still_says_so_when_it_did_not_read(tmp_path):
    """Removing the veto must not remove the DISCLOSURE. A run whose AI half
    delivered nothing still carries a named finding saying so — otherwise
    partial coverage would read as full coverage."""
    p = _project(tmp_path)
    _, out, _ = _run_track(p)
    rep = _report(p)
    fs = [f for f in rep["findings"] if f["rule"] == T.RULE_AI_SKIPPED]
    assert len(fs) == 1 and fs[0]["about"] == "track"
    assert T.RULE_AI_SKIPPED in out, "and it must be PRINTED"


def test_a_consumed_reading_retires_the_did_not_read_finding(tmp_path):
    """The pair. Once the AI half HAS read, continuing to announce that it did
    not would be false, and a track that cries wolf is one nobody reads."""
    p = _project(tmp_path)
    _answer(p, [{"id": "r::s", "layer": "L1_DATASHEET",
                 "requirement": "x", "expected_tokens": ["12"]}])
    _run_track(p)
    rep = _report(p)
    assert not [f for f in rep["findings"] if f["rule"] == T.RULE_AI_SKIPPED]


# ── defect 2: a consumed answer was dead data ───────────────────────────────

def test_an_unmet_ai_expectation_becomes_a_named_finding(tmp_path):
    """THE defect. Before this landing an expectation naming a fact no L-doc
    carries produced verdict PASS with zero findings."""
    p = _project(tmp_path)
    _answer(p, [{"id": "external_reference::REFHI",
                 "layer": "L1_DATASHEET",
                 "field_path": "fields.pinout",
                 "requirement": "a terminal for the external reference",
                 "evidence": ["input/docs/spec.md: external reference on the "
                              "REFHI terminal"],
                 "expected_tokens": ["REFHI"]}])
    rc, out, _ = _run_track(p)
    rep = _report(p)
    fs = _ai_findings(rep)
    assert len(fs) == 1, rep["findings"]
    f = fs[0]
    # identified by rule AND subject — a count tells nobody what to do
    assert f["rule"] == f"{T.RULE_AI_UNMET}::external_reference::REFHI"
    assert f["about"] == "design"      # it is about the DESIGN, not the track
    assert f["layer"] == "L1_DATASHEET"
    assert "REFHI" in f["message"]
    # it carries the grounds, so a reader can converge it without re-deriving
    assert "external reference on the REFHI terminal" in f["message"]
    assert rep["verdict"] == "FINDINGS"
    assert f["rule"] in out, "and it must be PRINTED where a human sees it"


def test_a_met_ai_expectation_does_not_become_a_finding(tmp_path):
    """The pair that makes the test above mean something. A comparator that
    fires on everything is as useless as one that fires on nothing."""
    p = _project(tmp_path, l1={"doc_id": "L1", "fields": {
        "pinout": {"REFHI": {"type": "analog_reference"}}}})
    _answer(p, [{"id": "external_reference::REFHI",
                 "layer": "L1_DATASHEET",
                 "requirement": "a terminal for the external reference",
                 "expected_tokens": ["REFHI"]}])
    _run_track(p)
    rep = _report(p)
    assert _ai_findings(rep) == []
    assert rep["ai_convergence"]["agreed"] == 1


def test_the_comparator_ignores_a_met_the_answer_claims(tmp_path):
    """ANTI-GAMING. The AI half must not mark its own homework: an answer that
    scored itself would agree with itself, and "a consumer that reads the file
    and always agrees" is the first track with a witness, not a second track.

    Both directions are checked, because trusting a claimed `met` would be
    wrong twice: it would hide a real gap AND manufacture a false one."""
    # claims met=True on a fact that is absent -> still a disagreement
    p1 = _project(tmp_path, name="lies_met")
    _answer(p1, [{"id": "a::b", "layer": "L1_DATASHEET", "requirement": "x",
                  "expected_tokens": ["REFHI"], "met": True}])
    _run_track(p1)
    assert len(_ai_findings(_report(p1))) == 1

    # claims met=False on a fact that is present -> still an agreement
    p2 = _project(tmp_path, name="lies_unmet", l1={
        "doc_id": "L1", "fields": {"pinout": {"REFHI": {}}}})
    _answer(p2, [{"id": "a::b", "layer": "L1_DATASHEET", "requirement": "x",
                  "expected_tokens": ["REFHI"], "met": False}])
    _run_track(p2)
    assert _ai_findings(_report(p2)) == []


def test_every_expected_token_must_be_present(tmp_path):
    """A partially-satisfied expectation is not satisfied, and the finding
    names WHICH token is missing — not how many."""
    p = _project(tmp_path, l1={"doc_id": "L1", "fields": {
        "pinout": {"REFHI": {}}, "resolution_bits": 12}})
    _answer(p, [{"id": "a::b", "layer": "L1_DATASHEET", "requirement": "x",
                 "expected_tokens": ["REFHI", "500 ksps"]}])
    _run_track(p)
    rep = _report(p)
    fs = _ai_findings(rep)
    assert len(fs) == 1
    assert "500 ksps" in fs[0]["message"] and "REFHI" not in fs[0]["message"]


# ── the comparator's own correctness ────────────────────────────────────────

def test_token_match_is_whole_token_never_substring(tmp_path):
    """#309 landed with a matcher that bound `VDD` to an `AVDD_REF` rail. A
    comparator making that mistake would report agreement on the strength of a
    substring — a false clean, which is the worse direction."""
    assert T.phrase_present("REFHI", '{"pins": ["REFHI"]}')
    assert T.phrase_present("REFHI", '{"pins": ["refhi"]}')          # case
    assert not T.phrase_present("REF", '{"pins": ["REFHI"]}')        # prefix
    assert not T.phrase_present("HI", '{"pins": ["REFHI"]}')         # suffix
    assert not T.phrase_present("REFH", '{"pins": ["A_REFHI_B"]}')   # infix
    assert not T.phrase_present("", '{"pins": ["REFHI"]}')           # empty
    # the #309 case itself, both directions
    assert not T.phrase_present("VDD", '{"rails": ["AVDD_REF"]}')
    assert T.phrase_present("AVDD_REF", '{"rails": ["AVDD_REF"]}')


def test_a_separator_difference_is_not_a_disagreement(tmp_path):
    """The paired half of the matcher. Spec prose and JSON field names spell
    the same fact with and without separators constantly; scoring that as a gap
    would fill an advisory channel with noise until nobody read it — its own
    way of becoming a report nobody opens."""
    assert T.phrase_present("1.8 V", '{"supply": "1.8V nominal"}')
    assert T.phrase_present("1.8V", '{"supply": "1.8 V nominal"}')
    assert T.phrase_present("TRIM_SEL", '{"f": "trim sel"}')
    assert T.phrase_present("500 ksps", '{"rate": "500ksps"}')
    # but tolerance stops at the token boundary — it never bridges INTO a
    # longer token, or `1.8 V` would match `1.8 VREF`
    assert not T.phrase_present("1.8 V", '{"supply": "1.8 VREF"}')


def test_a_fact_carried_as_a_field_NAME_counts(tmp_path):
    """A layer can carry a fact as a key as legitimately as as a value. A
    comparator blind to half the document would report a gap the design does
    not have."""
    p = _project(tmp_path, l1={"doc_id": "L1", "fields": {"REFHI": "external"}})
    _answer(p, [{"id": "a::b", "layer": "L1_DATASHEET", "requirement": "x",
                 "expected_tokens": ["REFHI"]}])
    _run_track(p)
    assert _ai_findings(_report(p)) == []


def test_layer_spelling_variants_resolve_to_the_same_layer(tmp_path):
    """An expert naming `L21` and one naming `L21_POWER_INTENT` mean the same
    layer. Scoring a spelling difference as a design gap would fill the report
    with disagreements the design does not have — the fastest way to make a
    findings list unreadable."""
    p = _project(tmp_path, layers={
        "L21_POWER_INTENT": {"doc_id": "L21",
                             "fields": {"power_rails": ["VDDA"]}}})
    for spelling in ("L21", "L21_POWER_INTENT", "l21"):
        _answer(p, [{"id": f"a::{spelling}", "layer": spelling,
                     "requirement": "x", "expected_tokens": ["VDDA"]}])
        _run_track(p)
        assert _ai_findings(_report(p)) == [], spelling


def test_a_layer_the_program_track_never_wrote_is_a_disagreement(tmp_path):
    """The case that matters most in practice: the expert expected a whole
    layer to carry something and the layer is not there at all. Silence here
    would be the original defect exactly."""
    p = _project(tmp_path)          # no L21 written
    _answer(p, [{"id": "supply::VDDA", "layer": "L21_POWER_INTENT",
                 "requirement": "an analog rail entry",
                 "expected_tokens": ["VDDA"]}])
    _run_track(p)
    fs = _ai_findings(_report(p))
    assert len(fs) == 1
    assert "no L21_POWER_INTENT layer at all" in fs[0]["message"]


# ── undecidable is not agreed ───────────────────────────────────────────────

def test_a_prose_only_expectation_is_undecidable_not_agreed(tmp_path):
    """An expectation with no checkable token cannot be decided by a program.
    Dropping it would make the AI half look like it agreed — the same
    conflation of two different zeros this whole track exists to stop."""
    p = _project(tmp_path)
    _answer(p, [{"id": "vague::thing", "layer": "L1_DATASHEET",
                 "requirement": "the datasheet should feel complete"}])
    _run_track(p)
    rep = _report(p)
    fs = _ai_findings(rep, T.RULE_AI_UNUSABLE)
    assert len(fs) == 1
    # about the TRACK: it says nothing about the design, so it must not be
    # counted as something the expert track found in the design
    assert fs[0]["about"] == "track"
    assert rep["ai_convergence"] == {"consumed": 1, "agreed": 0,
                                     "disagreed": 0, "undecidable": 1}


def test_a_malformed_answer_entry_is_reported_not_dropped(tmp_path):
    p = _project(tmp_path)
    _answer(p, ["not an object", {"layer": "L1_DATASHEET"}])
    _run_track(p)
    rep = _report(p)
    assert len(_ai_findings(rep, T.RULE_AI_UNUSABLE)) == 2
    assert rep["ai_convergence"]["undecidable"] == 2


# ── the ledger, and the live consumer ───────────────────────────────────────

def test_the_ledger_counts_agreements_not_only_disagreements(tmp_path):
    """"The second track always agrees" and "the second track works" are
    different states that a disagreement-only report renders identical. The
    first one is worth knowing about, so agreements are counted too."""
    p = _project(tmp_path, l1={"doc_id": "L1", "fields": {"pinout": {"REFHI": {}}}})
    _answer(p, [
        {"id": "a::met", "layer": "L1_DATASHEET", "requirement": "x",
         "expected_tokens": ["REFHI"]},
        {"id": "b::unmet", "layer": "L1_DATASHEET", "requirement": "y",
         "expected_tokens": ["TRIMSEL"]},
        {"id": "c::vague", "layer": "L1_DATASHEET", "requirement": "z"},
    ])
    _run_track(p)
    assert _report(p)["ai_convergence"] == {
        "consumed": 3, "agreed": 1, "disagreed": 1, "undecidable": 1}


def test_an_ai_disagreement_reaches_the_live_evidence_consumer(tmp_path):
    """END TO END into something already wired. `phase1_expert_track_evidence_
    check` runs advisory in the flow and counts DESIGN findings; an AI-only
    disagreement must flip it RAN_EMPTY -> RAN. Without this the finding would
    land in a report nobody reads, which is the failure mode #439 records three
    live instances of."""
    import phase1_expert_track_evidence_check as E

    quiet = _project(tmp_path, name="quiet")
    _run_track(quiet)
    assert E.assess(quiet, _PROGRAMS)["state"] == "INCOMPLETE"

    loud = _project(tmp_path, name="loud")
    _answer(loud, [{"id": "external_reference::REFHI", "layer": "L1_DATASHEET",
                    "requirement": "a terminal for the external reference",
                    "expected_tokens": ["REFHI"]}])
    _run_track(loud)
    ev = E.assess(loud, _PROGRAMS)
    assert ev["state"] == "RAN" and ev["patch_count"] == 1
    assert ev["layers"] == ["L1_DATASHEET"]
    assert ev["ai_subtrack"] == "CONSUMED"


def test_an_undecidable_entry_does_not_flip_the_evidence_consumer(tmp_path):
    """The pair. A finding about the TRACK must not be counted as the track
    having found something in the DESIGN."""
    import phase1_expert_track_evidence_check as E
    p = _project(tmp_path)
    _answer(p, [{"id": "vague::thing", "layer": "L1_DATASHEET",
                 "requirement": "prose only"}])
    _run_track(p)
    assert E.assess(p, _PROGRAMS)["state"] == "RAN_EMPTY"


# ── what must NOT have changed ──────────────────────────────────────────────

def test_ai_findings_are_advisory_and_do_not_block(tmp_path):
    """Advisory, proven by the exit code of a run that HAS AI findings. The
    increment is that a human sees the disagreement — not a new Phase-1 stop."""
    p = _project(tmp_path)
    _answer(p, [{"id": "a::b", "layer": "L1_DATASHEET", "requirement": "x",
                 "expected_tokens": ["TRIMSEL"]}])
    rc, out, _ = _run_track(p)
    assert rc == 0
    assert _report(p)["blocking"] is False


def test_the_track_does_not_write_the_ai_patch_sidecar(tmp_path):
    """Unchanged and load-bearing. The three completeness gates MERGE the
    sidecar into the haystack they then measure, so a track writing there would
    supply its own score. Convergence goes to FINDINGS, never to the haystack."""
    p = _project(tmp_path)
    _answer(p, [{"id": "a::b", "layer": "L1_DATASHEET", "requirement": "x",
                 "expected_tokens": ["TRIMSEL"]}])
    _run_track(p)
    assert not _pl.phase1_ai_deep_review_patches_file(p).is_file()
    assert _report(p)["track_health"]["ai_patch_sidecar_present"] is False


def test_an_unreadable_answer_is_still_an_error_not_an_empty_reading(tmp_path):
    """Unreadable evidence is not evidence — the rule the sidecar and the track
    report are already held to, preserved through the rewiring."""
    p = _project(tmp_path)
    d = _pack_dir(p)
    d.mkdir(parents=True, exist_ok=True)
    (d / "l_doc_expectations.json").write_text("{not json")
    _run_track(p)
    rep = _report(p)
    assert rep["ai_subtrack"]["status"] == "ERROR"
    assert "does not parse" in rep["ai_subtrack"]["reason"]
    # and an ERROR is not a reading, so the "did not read" finding still fires
    assert [f for f in rep["findings"] if f["rule"] == T.RULE_AI_SKIPPED]
