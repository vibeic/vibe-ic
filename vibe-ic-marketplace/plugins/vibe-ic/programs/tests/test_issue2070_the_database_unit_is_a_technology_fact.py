#!/usr/bin/env python3
"""#2070 — `database_unit_um` is read off the technology, and the template
fetch reads the PDK families L1 names.

WHAT WAS MEASURED, AND WHY IT IS TWO DEFECTS WITH ONE CAUSE
===========================================================
Step 0.5ic asked the DESIGN two questions it is not the authority on.

1. `database_unit_um` was a design answer. It is a fact of the TECHNOLOGY: on
   the pinned image the two open PDK families two corpus designs BOTH name
   declare different units — `DATABASE MICRONS 2000` (0.0005 um) and
   `DATABASE MICRONS 1000` (0.001 um). One answers file drives run trees on
   both, so any single scalar written there is wrong for one of the two runs.
   Both designs correctly answered NOT_DETERMINED and cited both measurements.

2. `submission_template_fetch` reported "the design declares no PDK" for those
   same two designs, whose L1 names its target families in prose on one row
   (line 32 in one, line 33 in the other). The fetch resolved the target
   through an L19 document that step 0.5ic — dispatched BEFORE the mode branch
   — has not written yet. The right answer, for a reason that would have kept
   giving the same answer once the design DID name a family.

Both are the same mistake: a question about the run's process, put to the
design, and answered from whatever happened to be readable.

EVERY ASSERTION HERE IS BIDIRECTIONAL. Each one is paired with the state that
must be REFUSED, because a check that cannot fail is not a check: a refusal
that is not re-emitted (the C6b mutant) leaves a contradicted claim passing
silently, and a technology that was never read must not let a design's scalar
through as if it had been measured.

NO DOCKER. The transcription itself runs a container and is exercised on real
silicon evidence in the lane; everything here is the LOGIC around it, driven
with a technology record shaped exactly like the one the fetch writes.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _tapeout_declaration as TD                             # noqa: E402
import submission_template_fetch as STF                       # noqa: E402
import phase1_one_shot_runner as P1                           # noqa: E402

#: Shaped exactly like `submission_template_fetch.technology_facts` output.
GF180 = {"database_unit_um": {
    "value": 0.0005, "pdk": "gf180mcuD",
    "source": "/foss/pdks/<pdk>/libs.ref/<scl>/techlef/<scl>__nom.tlef:40",
    "statement": "DATABASE MICRONS 2000  ;", "database_microns": 2000.0,
    "image": "<repo>@sha256:<digest>", "unavailable": None}}
SKY = {"database_unit_um": {
    "value": 0.001, "pdk": "sky130A",
    "source": "/foss/pdks/<pdk>/libs.ref/<scl>/techlef/<scl>__nom.tlef:26",
    "statement": "DATABASE MICRONS 1000 ;", "database_microns": 1000.0,
    "image": "<repo>@sha256:<digest>", "unavailable": None}}


# ── the vocabulary ────────────────────────────────────────────────────
def test_exactly_the_database_unit_is_answered_by_the_technology():
    """MEMBERSHIP, not a count. A question moved into or out of the
    technology's authority has to show up here by NAME."""
    tech = {q.key for q in TD.QUESTIONS
            if q.answered_by == TD.ANSWERED_BY_TECHNOLOGY}
    assert tech == {"database_unit_um"}
    assert set(TD.TECHNOLOGY_ANSWERED) == tech
    # And the other direction: everything else is still the design's.
    design = {q.key for q in TD.QUESTIONS
              if q.answered_by == TD.ANSWERED_BY_DESIGN}
    assert design and not (design & tech)
    assert design | tech == {q.key for q in TD.QUESTIONS}


def test_the_provenance_key_is_carried_by_the_declaration():
    assert TD.TECHNOLOGY_KEY in TD.EXTRA_KEYS
    doc, ignored = TD.merge_answers(TD.blank_declaration(),
                                    {TD.TECHNOLOGY_KEY: GF180})
    assert ignored == []
    assert doc[TD.TECHNOLOGY_KEY] == GF180


# ── the refusal, both directions ──────────────────────────────────────
def test_a_disagreeing_design_scalar_is_refused_by_name_with_both_values():
    out = TD.technology_refusals({"database_unit_um": 0.001}, GF180,
                                 "the design's answers file")
    assert [r["rule"] for r in out] == [TD.RULE_TECHNOLOGY_FACT_FROM_DESIGN]
    msg = out[0]["message"]
    # BOTH values, and where the measured one was read. A refusal that names
    # only one of the two numbers cannot be acted on.
    assert "0.001" in msg and "0.0005" in msg
    assert GF180["database_unit_um"]["source"] in msg
    assert out[0]["answered"] == 0.001 and out[0]["technology"] == 0.0005


@pytest.mark.parametrize("said", [0.0005, TD.NOT_DETERMINED, None, ""])
def test_agreement_and_silence_are_not_refusals(said):
    assert TD.technology_refusals({"database_unit_um": said}, GF180) == []


def test_a_technology_that_could_not_be_read_refuses_nothing():
    """"We could not read it" must never arrive as a number, and must never
    convict a design of disagreeing with a measurement nobody made."""
    unread = {"database_unit_um": {"value": None, "pdk": "gf180mcuD",
                                   "unavailable": "the tech LEF was not read"}}
    assert TD.technology_refusals({"database_unit_um": 0.001}, unread) == []
    doc = TD.merge_technology(TD.blank_declaration(), unread)
    assert doc["answers"]["database_unit_um"] == TD.NOT_DETERMINED


# ── the validator, both directions ────────────────────────────────────
def test_a_recorded_refusal_reaches_the_declarations_refusal_list():
    """THE REVERT-PROOF for the re-emission. Deleting the clause that carries
    a recorded refusal into `validate` makes `tapeout_declaration_gen` exit 0
    on a design that contradicts the technology — measured, and silent."""
    record = dict(GF180)
    record["refusals"] = TD.technology_refusals({"database_unit_um": 0.001},
                                                GF180)
    doc = TD.merge_technology(TD.blank_declaration(), record)
    rules = [r["rule"] for r in TD.validate(doc)]
    assert TD.RULE_TECHNOLOGY_FACT_FROM_DESIGN in rules
    # And the negative control: the SAME declaration without the recorded
    # refusal is not refused, so the rule above is doing the work.
    clean = TD.merge_technology(TD.blank_declaration(), GF180)
    assert [r["rule"] for r in TD.validate(clean)] == []


def test_a_declaration_that_contradicts_its_own_cited_source_is_malformed():
    doc = TD.merge_technology(TD.blank_declaration(), GF180)
    doc["answers"]["database_unit_um"] = 0.001         # hand-edited half
    rules = [r["rule"] for r in TD.validate(doc)]
    assert TD.RULE_TECHNOLOGY_FACT_FROM_DESIGN in rules


def test_an_absent_technology_record_is_incomplete_not_malformed():
    """A declaration written before this key existed, or a run that could not
    read the tech LEF and said so, is INCOMPLETE — the consuming check's
    NOT_DETERMINED to report, never a malformed-evidence refusal here."""
    doc = TD.blank_declaration()
    # ABSENT, deliberately: a provenance block that says NOT_DETERMINED still
    # asserts that a technology was consulted. Nothing consulted one here.
    assert TD.TECHNOLOGY_KEY not in doc
    assert TD.validate(doc) == []
    assert TD.answer(doc, "database_unit_um") == TD.NOT_DETERMINED


def test_the_two_pdks_produce_two_different_units():
    """The whole reason the design cannot answer: one answers file, two
    processes, two units."""
    a = TD.merge_technology(TD.blank_declaration(), GF180)
    b = TD.merge_technology(TD.blank_declaration(), SKY)
    assert a["answers"]["database_unit_um"] == 0.0005
    assert b["answers"]["database_unit_um"] == 0.001
    assert a["answers"]["database_unit_um"] != b["answers"]["database_unit_um"]


# ── the families L1 names ─────────────────────────────────────────────
def _design(tmp_path: Path, l1_row: str) -> Path:
    proj = tmp_path / "design"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "L1_product_metadata.md").write_text(
        "# L1\n\n## Tapeout target\n\n| field | value |\n|---|---|\n"
        + l1_row + "\n", encoding="utf-8")
    return proj


def test_the_families_named_on_the_designs_own_row_are_read(tmp_path):
    proj = _design(tmp_path,
                   "| target PDK family | open-source (sky130 primary, "
                   "gf180mcu secondary) |")
    rec = STF.declared_pdk_families(proj)
    assert rec["families"] == ["sky130", "gf180mcu"]
    assert rec["source"] and rec["source"].endswith(":7")
    assert rec["unavailable"] is None


def test_a_design_naming_no_family_states_the_search_instead(tmp_path):
    """NOT a default and NOT a silence: the roots that were searched are
    recorded, so "the design names none" is distinguishable from "nobody
    looked" — which is what `unavailable` is for."""
    proj = _design(tmp_path, "| target PDK family | not chosen yet |")
    rec = STF.declared_pdk_families(proj)
    assert rec["families"] == []
    assert "input/docs" in rec["searched"]
    assert rec["unavailable"] is None


def test_the_runs_pdk_is_matched_to_a_family_by_the_trees_own_rule():
    fams = ["sky130", "gf180mcu"]
    assert STF.family_named_by_design("gf180mcuD", fams) == "gf180mcu"
    assert STF.family_named_by_design("sky130A", fams) == "sky130"
    # The other direction: a process the design does not name matches nothing.
    assert STF.family_named_by_design("nangate45", fams) is None
    assert STF.family_named_by_design("sky130A", ["gf180mcu"]) is None


def test_a_run_on_a_pdk_the_design_does_not_name_is_refused_by_name(tmp_path):
    """No container is started on this path: the refusal lands BEFORE the
    transcription, because the technology facts of a process the design never
    chose are not its declaration's to carry."""
    proj = _design(tmp_path,
                   "| target PDK family | open-source (sky130 primary, "
                   "gf180mcu secondary) |")
    rep = STF.fetch(proj, pdk="nangate45")
    assert rep["verdict"] == STF.NOT_DETERMINED
    assert rep["refusals"] == [STF.RULE_PDK_NOT_NAMED]
    assert "nangate45" in rep["reason"]
    assert "sky130" in rep["reason"] and "gf180mcu" in rep["reason"]
    assert rep["technology"] == {}
    assert rep["pdk_family_resolved"] is None


def test_a_design_that_names_no_family_is_not_refused_for_naming_none(tmp_path):
    """The negative control for the clause above. A design that names NO
    family constrains nothing, so no run is refused for being outside a list
    the design never wrote — that would refuse every design in the corpus."""
    proj = _design(tmp_path, "| target PDK family | not chosen yet |")
    rep = STF.fetch(proj, pdk="nangate45")
    assert rep["refusals"] != [STF.RULE_PDK_NOT_NAMED]


# ── the run's --pdk reaches step 0.5ic ────────────────────────────────
@pytest.mark.parametrize("extras,want", [
    ([], ""),
    (["--pdk", "sky130A"], "sky130A"),
    (["--pdk=gf180mcuD"], "gf180mcuD"),
    (["--mode", "docs", "--pdk", "sky130A"], "sky130A"),
    (["--pdk", "auto"], ""),          # `auto` is a request, not a process
    (["--pdk"], ""),                  # a flag with no value invents nothing
])
def test_the_runs_pdk_is_read_out_of_extras(extras, want):
    assert P1._pdk_of_this_run(extras) == want


def test_reading_the_pdk_does_not_consume_it():
    """It stays in `extras`, which the docs-mode delegate is handed. An
    argparse option here would silently stop that forwarding."""
    extras = ["--mode", "docs", "--pdk", "sky130A"]
    P1._pdk_of_this_run(extras)
    assert extras == ["--mode", "docs", "--pdk", "sky130A"]


def test_the_dispatcher_hands_step_0_5ic_the_runs_own_pdk():
    """BY AST, not by grep. `_pdk_of_this_run` existing proves nothing — the
    defect this closes is that step 0.5ic was never TOLD, and dropping the
    keyword at the one call site restores it in full while every string in
    this file still reads as if the wiring were there."""
    import ast
    tree = ast.parse((_PROGRAMS / "phase1_one_shot_runner.py").read_text(
        errors="replace"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "_run_step_0_5ic"]
    assert calls, "nothing dispatches step 0.5ic"
    for call in calls:
        kw = {k.arg: k.value for k in call.keywords}
        assert "pdk" in kw, ("a step-0.5ic dispatch that does not pass the "
                             "run's PDK cannot transcribe its technology")
        inner = [n for n in ast.walk(kw["pdk"])
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        assert any(c.func.id == "_pdk_of_this_run" for c in inner)


def test_step_0_5ic_forwards_the_pdk_to_the_fetch():
    """The second half of the same wire: the parameter reaching the function
    and the function reaching the program are two failures, not one."""
    import ast
    tree = ast.parse((_PROGRAMS / "phase1_one_shot_runner.py").read_text(
        errors="replace"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_run_step_0_5ic")
    src = ast.dump(fn)
    assert "'--pdk'" in src.replace('"', "'"), (
        "_run_step_0_5ic never puts --pdk on any argv it builds")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "pdk" in names


def test_the_answers_producer_is_handed_the_fetchs_own_report():
    """One reader of the tech LEF, not two: the value in the declaration is
    the value a named program read at a named line."""
    src = (_PROGRAMS / "phase1_one_shot_runner.py").read_text(errors="replace")
    assert "--technology-json" in src
    assert P1._ST_FETCH_REPORT_REL == STF.REPORT_REL


# ── the polarity claim, falsifiable ───────────────────────────────────
def test_the_not_prose_claim_for_the_tech_lef_reader_is_falsifiable():
    """THE ARGUMENT BEHIND THE `_NOT_PROSE` ENTRY, RE-MEASURED HERE.

    `technology_facts` is registered as reading a formal grammar rather than
    prose. That claim is only worth anything if it can be checked, so this
    checks it: every denial token of `_prose_polarity`'s OWN vocabulary, in
    every position reachable in the one production the function parses.

    THE PROPERTY: the grammar's only alternative to a value is SILENCE. A
    denial can stop the record from parsing — and then the function answers
    None with a stated `unavailable`, and the caller withholds the field — but
    no denial can make it publish a DIFFERENT number. That is what makes a
    polarity consult here a branch that can never fire.

    THE CONTRAST is the other half of the claim: the IDENTICAL strings, read as
    prose, are full of denials. The vocabulary is not inert; this grammar is."""
    import re
    import _prose_polarity as PP
    raw = PP._DENIAL_CORE + "|" + PP._DENIAL_RETIRED
    tokens = sorted({m for m in re.findall(
        r"(?:\\b)?([A-Za-z][A-Za-z' -]{2,})", raw)})
    assert len(tokens) >= 10, "the vocabulary was not read"
    positions = ("{t} DATABASE MICRONS 2000 ;", "DATABASE {t} MICRONS 2000 ;",
                 "DATABASE MICRONS {t} 2000 ;", "DATABASE MICRONS 2000 {t} ;",
                 "DATABASE MICRONS 2000 ; # {t}",
                 "DATABASE MICRONS 2000 ; {t} 1000",
                 "  DATABASE MICRONS 2000 ;   {t}",
                 "{t}: DATABASE MICRONS 2000 ;")
    inverted, refused, trials = 0, 0, 0
    for tok in tokens:
        for shape in positions:
            line = shape.format(t=tok)
            trials += 1
            m = STF._DBU_RE.search(line)
            got = float(m.group(1)) if m else None
            if got is None:
                refused += 1
            elif got != 2000.0:
                inverted += 1
    assert trials >= 80
    assert inverted == 0, ("a denial token changed the value this grammar "
                           "publishes — the _NOT_PROSE claim is false")
    assert refused > 0, ("no denial could even disturb the parse; the "
                         "falsifier is not exercising the grammar")
    prose = sum(1 for tok in tokens for shape in positions
                if PP.is_denied(shape.format(t=tok)))
    assert prose > 0, ("the vocabulary found no denial in ANY of these "
                       "strings, so this test proves nothing about the "
                       "grammar — it would pass against an empty vocabulary")


def test_the_family_reader_does_consult_polarity_through_what_it_reuses(
        tmp_path):
    """THE OTHER HALF. `declared_pdk_families` reads L1's tapeout-target ROW,
    which IS prose and in which a family IS denied in practice. It re-matches
    nothing: the consult it inherits is the extractor's own, and this is the
    behavioural proof that it is inherited rather than merely claimed."""
    def _row(text):
        proj = tmp_path / text[:8].replace(" ", "_").replace("/", "_")
        (proj / "input" / "docs").mkdir(parents=True)
        (proj / "input" / "docs" / "L1.md").write_text(
            "# L1\n\n## Tapeout target\n\n| f | v |\n|---|---|\n"
            f"| target PDK family | {text} |\n", encoding="utf-8")
        return STF.declared_pdk_families(proj)["families"]

    # AFFIRMED: both families are adopted.
    assert _row("sky130 primary, gf180mcu secondary") == ["sky130", "gf180mcu"]
    # DENIED: the planted denial yields NO sky130 family. Nothing is adopted
    # off a row the design used to deny.
    assert "sky130" not in _row("the design targets no sky130 process")
    # DENIED SELECTIVELY: the surviving family is still adopted, so the consult
    # is a polarity check and not a blanket refusal of any row with a `no` in
    # it — which would be the easy wrong fix.
    assert _row("no longer sky130; the target is gf180mcu") == ["gf180mcu"]


# ── end to end through the two producers ──────────────────────────────
def _project(tmp_path: Path, design_answers: dict, technology: dict) -> Path:
    proj = tmp_path / "p"
    (proj / "input").mkdir(parents=True)
    (proj / "reports" / "phase1").mkdir(parents=True)
    ans = proj / "input" / "step_0_5ic_answers.json"
    ans.write_text(json.dumps({"schema": "vibe-ic/step_0_5ic_answers/1",
                               "answers": design_answers}), encoding="utf-8")
    fetch_rep = proj / "reports" / "phase1" / "fetch.json"
    fetch_rep.write_text(json.dumps({"program": "submission_template_fetch",
                                     "technology": technology}),
                         encoding="utf-8")
    return proj


def _run(proj: Path, ans_rel: str = "input/step_0_5ic_answers.json") -> int:
    rc_a = subprocess.run(
        [sys.executable, str(_PROGRAMS / "submission_template_answers.py"),
         str(proj), "--design-answers", str(proj / ans_rel),
         "--technology-json", str(proj / "reports/phase1/fetch.json")],
        capture_output=True, text=True).returncode
    assert rc_a == 0, "the producer's rc 1 is reserved for something BROKEN"
    merged = proj / "input" / "submission_template" / "operator_answers.json"
    return subprocess.run(
        [sys.executable, str(_PROGRAMS / "tapeout_declaration_gen.py"),
         str(proj), "--answers", str(merged)],
        capture_output=True, text=True).returncode


def _declared(proj: Path):
    return json.loads((proj / TD.DECLARATION_REL).read_text())


def test_the_transcription_is_published_with_its_provenance(tmp_path):
    proj = _project(tmp_path, {"deliverable": "HARDMACRO", "top_cell": "x"},
                    GF180)
    assert _run(proj) == 0
    doc = _declared(proj)
    assert doc["answers"]["database_unit_um"] == 0.0005
    rec = doc[TD.TECHNOLOGY_KEY]["database_unit_um"]
    assert rec["source"].endswith(":40") and rec["pdk"] == "gf180mcuD"


def test_a_design_that_agrees_is_accepted_and_still_not_the_authority(tmp_path):
    proj = _project(tmp_path, {"deliverable": "HARDMACRO",
                               "database_unit_um": 0.001}, SKY)
    assert _run(proj) == 0
    assert _declared(proj)["answers"]["database_unit_um"] == 0.001
    rep = json.loads((proj / "reports" / "phase1"
                      / "submission_template_answers.json").read_text())
    assert rep["technology_refusals"] == []
    assert any("database_unit_um" in n for n in rep["technology_agreed"])


def test_a_design_that_disagrees_refuses_the_declaration(tmp_path):
    """The teeth. `tapeout_declaration_gen` exits non-zero, which is what
    `_run_step_0_5ic` turns into a FAILing phase 1."""
    proj = _project(tmp_path, {"deliverable": "HARDMACRO",
                               "database_unit_um": 0.001}, GF180)
    assert _run(proj) == 1
    doc = _declared(proj)
    # The TRANSCRIBED value is what the declaration carries either way.
    assert doc["answers"]["database_unit_um"] == 0.0005
    rules = [r["rule"] for r in doc[TD.TECHNOLOGY_KEY]["refusals"]]
    assert rules == [TD.RULE_TECHNOLOGY_FACT_FROM_DESIGN]


def test_an_unmeasured_technology_withholds_the_designs_claim(tmp_path):
    """THE HOLE THIS CLOSES, measured while building it: a run whose PDK the
    design does not name is refused by the fetch, which transcribes nothing —
    and the design's own scalar sailed into the declaration as
    `database_unit_um`, read downstream as a measured technology fact. A claim
    that was never checked against a technology is not published as one."""
    proj = _project(tmp_path, {"deliverable": "HARDMACRO",
                               "database_unit_um": 0.001}, {})
    assert _run(proj) == 0
    assert _declared(proj)["answers"]["database_unit_um"] == TD.NOT_DETERMINED
    rep = json.loads((proj / "reports" / "phase1"
                      / "submission_template_answers.json").read_text())
    assert rep["technology_withheld"] == {"database_unit_um": 0.001}


def test_the_designs_other_answers_are_untouched_by_all_of_this(tmp_path):
    """The blast radius, asserted rather than assumed: seventeen questions are
    still the design's, and the merge that publishes one technology fact must
    not disturb them."""
    proj = _project(tmp_path, {"deliverable": "DIE", "top_cell": "chip_top",
                               "die_origin_um": [0, 0]}, SKY)
    assert _run(proj) == 0
    ans = _declared(proj)["answers"]
    assert ans["deliverable"] == "DIE" and ans["top_cell"] == "chip_top"
    assert ans["die_origin_um"] == [0, 0]
    assert ans["database_unit_um"] == 0.001
