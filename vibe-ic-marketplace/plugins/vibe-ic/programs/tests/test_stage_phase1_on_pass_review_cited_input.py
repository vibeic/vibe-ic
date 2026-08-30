#!/usr/bin/env python3
"""The stage_phase1 ON-PASS review — and the control that stops it manufacturing
confidence in either direction.

WHY THIS FILE EXISTS
====================
`skills/_classification.json` declares a `verification` tier — "run AFTER
program PASS to spot-check the deterministic output" — with eight members.
v1.12.87 wired the FIRST of them by giving stage1 an `on_pass_review:` block;
v1.12.99 placed every skill on the stage axis and put `phase1-output-verify`
and `phase1-completeness-deep-review` on `stage_phase1`. This is the second
wiring, and the flow file had already written down that it was missing:

    "`phase1-output-verify` and `phase1-completeness-deep-review` both ship,
     both say in their own descriptions that they run 'After
     phase1_one_shot_runner emits L*.json', and neither is named by any stage
     -- so stage_phase1 has no declared on-pass review ... They belong in an
     `on_pass_review:` block on stage_phase1, the field v1.12.87 added for
     them on stage1."

WHY THIS STAGE AND NOT ONE OF THE OTHER SIX
===========================================
The discriminator that picked stage1 was that its artefact is a TRANSLATION of
the intent rather than a transformation of an upstream artefact. Phase 1 is the
only remaining stage of which that is true: stage2 checks the netlist against
the RTL, stage3 checks the layout against the netlist and the PDK, and both
already have a reader. Measured on the corpus the other candidates also fail
the evidence test — `stage_analog` publishes 13 cells and `stage3` 14, against
`stage_phase1`'s 91, and `compliance-gate-spot-check` has no published
`flow_compliance` report to prove a control over at all.

WHAT NOTHING ELSE CHECKS
========================
`phase1_doc_input_completeness_check` measures the INPUT -> L-doc direction:
which verbatim tokens of the design input reached some layer. On
`ic/spm/v1.9.96_gf180mcuD` it answers PASS, 49 of 49 tokens captured. Nothing
asks the reverse, which is the only machine-readable claim the artefact makes
ABOUT the intent: when a layer records WHERE it read a fact, is that source a
file this run contains?

WHAT IS ACTUALLY AT RISK, AND WHY BOTH DIRECTIONS ARE ASSERTED
==============================================================
A reviewer that never rejects is WORSE than none — it manufactures confidence
in every artefact it looks at. One that rejects everything is worse still: it
is the same failure as a detector that fires on 21 of 21 subjects. Neither is
caught by a test that only proves one direction, so every case below asserts
BOTH on REAL published artefacts:

  ACCEPT  `fixtures/stage_phase1_on_pass_review/accept_a2b` — verbatim from the
          published cell `protocol_parity/a2b`, whose L-docs cite
          `input/docs/a2b_spec.txt` and whose run stages exactly that file.
  REJECT  `fixtures/stage_phase1_on_pass_review/reject_spm` — verbatim from the
          published cell `ic/spm/v1.9.96_gf180mcuD`, whose L-docs attribute
          their literals to `input/docs/*.md` while the run stages that same
          input at `phase1/input_doc/*.txt`. The cell refutes itself: its own
          L19 cites `phase1/input_doc/L1_product_metadata.txt` and RESOLVES,
          so the input was published and it is the CITATION that is wrong.

`fixtures/.../PROVENANCE.json` carries each source file's sha256; nothing in
the fixture is authored. The corpus-bound test re-reads the LIVE cells when the
corpus resolves, and pins the whole partition so a rule that starts firing on
everything, or on nothing, cannot land quietly.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
PROG = PROGRAMS / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
FIX = Path(__file__).resolve().parent / "fixtures" / "stage_phase1_on_pass_review"
ACCEPT = FIX / "accept_a2b"
REJECT = FIX / "reject_spm"
#: a published cell ALL THREE of stage_phase1's rules read and accept
ALL_RULES_OK = FIX / "accept_interlaken"
STAGE = "stage_phase1"

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _published_corpus as _pc  # noqa: E402
except Exception:  # pragma: no cover
    _pc = None

yaml = pytest.importorskip("yaml")


def run(project, *extra, flow=None, emit=None):
    """Invoke the review exactly as the flow declares it.

    A rejection WRITES the run's own regression INTO the run tree, so every
    test that can provoke one runs against `tree()`, a per-test copy. Nothing
    here ever writes into the shipped fixture."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    argv = [sys.executable, str(PROG), str(project), "--stage", STAGE,
            "--flow-def", str(flow or FLOW)]
    if emit is not None:
        argv += ["--emit-test", str(emit)]
    return subprocess.run(argv + list(extra), capture_output=True, text=True,
                          env=env)


def tree(tmp_path, which):
    """A writable copy of one published fixture cell."""
    d = tmp_path / which.name
    if not d.exists():
        shutil.copytree(which, d)
    return d


RULE = "R1_CITED_INPUT_ABSENT"


def record_of(rec, rule=RULE):
    """This rule's own finding, out of the composed review record.

    WHY THESE CONTROLS READ THE RULE AND NOT THE EXIT CODE. `stage_phase1`
    declares THREE rules (#1845's two and this one, merged into the one
    `on_pass_review:` block the doctrine allows a stage), and the run's exit
    code is their COMPOSITION: rc 2 as soon as ANY of them cannot be answered.
    A synthetic tree built to exercise this rule carries nothing for its
    siblings to read — no L9, no cited hexadecimal constant — so asserting
    `rc == 0` on one would be asserting a fact about the siblings. What this
    rule claims is this rule's verdict, so that is what is asserted, and every
    control below ALSO asserts that no sibling rejected, which is what keeps
    the case discriminating in the direction that matters.

    It raises rather than returning None when the rule is absent, which makes
    it the merge's own guard: a rule dropped from `_RULES` would otherwise
    turn every control here into a test of nothing that passes.
    """
    for f in (rec["rejections"] + rec["observations"]
              + rec["not_checked"] + rec["unproven_rejections"]):
        if f["rule"] == rule:
            return f
    raise AssertionError(
        f"{rule} produced no finding at all — it is not registered for "
        f"{rec.get('stage')}. Rules seen: {[x['rule'] for x in rec['rules']]}")


def verdict_of(rec, rule=RULE):
    return record_of(rec, rule)["verdict"]


def no_sibling_rejected(rec, rule=RULE):
    """Every rejection in the record is this rule's."""
    return [f["rule"] for f in rec["rejections"] if f["rule"] != rule] == []


def declaration():
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == STAGE:
            return st.get("on_pass_review")
    raise AssertionError(f"{STAGE} is not declared")


def flow_with(tmp_path, **override):
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == STAGE:
            st["on_pass_review"] = {**st["on_pass_review"], **override}
    p = tmp_path / "flow.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return p


def synthetic(root: Path, evidence, staged=("input/docs/real.md",)):
    """A minimal run tree whose single L-doc carries `evidence`.

    Used ONLY for the rule's mechanics — which evidence values are citations
    and which are disclosures. Every claim about whether the rule is RIGHT is
    made against the published fixtures above.
    """
    docs = root / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_DATASHEET.json").write_text(
        json.dumps({"extraction_evidence": evidence}), encoding="utf-8")
    for rel in staged:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("staged design input\n", encoding="utf-8")
    return root


# ─────────────────────────────────────────────────────────────────────────────
# the declaration is in the flow, and nowhere else
# ─────────────────────────────────────────────────────────────────────────────
def test_stage_phase1_declares_an_on_pass_review_naming_a_verification_tier_skill():
    d = declaration()
    assert d is not None, f"{STAGE} declares no on_pass_review"
    assert d["fires_on"] == "stage_pass"
    assert d["verdict"] in ("advisory", "blocking"), (
        "BLOCKING vs ADVISORY must be declared, and declared HERE — whether a "
        "rejection stops the flow is the flow's decision, not the reviewer's")
    tier = json.loads((PLUGIN / "skills" / "_classification.json")
                      .read_text(encoding="utf-8"))["tiers"]["verification"]["skills"]
    assert d["skill"] in tier, (
        f"{d['skill']!r} is not a member of the verification tier {tier}")
    assert (PLUGIN / "skills" / d["skill"] / "SKILL.md").is_file()


def test_naming_the_skill_here_removes_it_from_the_stage_axis():
    """ONE PREMISE, ONE PLACE. v1.12.99 placed `phase1-output-verify` on
    `stage_phase1` in `_classification.json` because no stage named it. Naming
    it here makes that stage DERIVED, and `skill_stage_membership_check` P4
    rejects the pair as a DOUBLE DECLARATION — so the axis entry comes out, as
    `phase2-rtl-verify`'s did when stage1 was wired at v1.12.87.

    Asserted from both ends: the skill this block names must be absent from the
    axis, and `phase2-rtl-verify` is checked alongside it so a future edit that
    reintroduced either would fail here rather than only in P4."""
    axis = json.loads((PLUGIN / "skills" / "_classification.json")
                      .read_text(encoding="utf-8"))["stage_axis"]["stages"]
    for skill in (declaration()["skill"], "phase2-rtl-verify"):
        assert skill not in axis, (
            f"{skill!r} is named by a flow on_pass_review block AND carries a "
            f"stage_axis entry; its stage is declared twice")
    # and the OTHER phase-1 reviewer, which no stage names, keeps its entry —
    # the control that this is a derivation rule and not a deletion sweep
    assert "phase1-completeness-deep-review" in axis


def test_the_declaration_is_not_a_second_membership_roster():
    """`flow_stage_membership_single_declaration_check` P1 discovers a roster by
    SHAPE, not by key name: any stage key whose value is a list naming declared
    step ids is a second membership declaration. The review block is a mapping
    and names no step, so membership is still declared once, on the step."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    step_ids = {str(s["id"]) for s in doc["steps"]}
    d = declaration()
    assert isinstance(d, dict)
    for key, val in d.items():
        if isinstance(val, list):
            named = {str(v) for v in val} & step_ids
            assert not named, f"on_pass_review.{key} names step id(s) {named}"


def test_the_four_required_parts_are_declared_by_the_flow():
    assert declaration()["rejection_requires"] == [
        "intent", "artefact", "contradiction", "test"]


# ─────────────────────────────────────────────────────────────────────────────
# BOTH DIRECTIONS, ON REAL ARTEFACTS
# ─────────────────────────────────────────────────────────────────────────────
def test_a_real_known_good_artefact_is_accepted(tmp_path):
    r = run(tree(tmp_path, ACCEPT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert "ACCEPT" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert verdict_of(rec) == "ACCEPT", r.stdout
    assert rec["rejections"] == []
    # and it accepted because the citations RESOLVED, not because there were none
    assert record_of(rec)["artefact"]["grounded"], (
        "the accept case makes no grounded citation; it would pass against a "
        "rule that checks nothing")
    # The RUN exits 2, and that is a fact about a SIBLING and not a softening
    # of the line above: `protocol_parity/a2b` cites no hexadecimal constant,
    # so R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE cannot be answered on it and says
    # so by name. Named here so the number is read rather than assumed.
    assert r.returncode == 2, r.stdout
    assert [f["rule"] for f in rec["not_checked"]] == [
        "R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE"]


def test_a_real_cell_every_rule_of_the_stage_accepts_exits_zero(tmp_path):
    """The composed green, which the ACCEPT control above cannot give because
    its cell leaves a sibling unanswerable. `protocol_parity/interlaken` is a
    published cell all THREE of stage_phase1's rules can read and all three
    accept, so this is the case that proves the merged stage has a green at
    all — and, by asserting the observed set by EQUALITY, that all three are
    still registered."""
    r = run(tree(tmp_path, ALL_RULES_OK), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 0, r.stdout + r.stderr
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == [] and rec["not_checked"] == []
    assert {o["rule"] for o in rec["observations"]} == {
        "R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE",
        "R2_TOP_MODULE_PROVENANCE_REFUTED",
        "R1_CITED_INPUT_ABSENT"}
    assert verdict_of(rec) == "ACCEPT"
    assert record_of(rec)["artefact"]["grounded"]


def test_a_real_run_whose_l_docs_cite_input_it_does_not_have_is_rejected(tmp_path):
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REJECT" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert len(rec["rejections"]) == 1
    f = rec["rejections"][0]
    assert f["rule"] == "R1_CITED_INPUT_ABSENT"
    # the INTENT it read — the design input this run actually stages
    assert f["intent"]["field"] == "staged design input"
    assert f["intent"]["staged_count"] == 9
    # the ARTEFACT fact it read
    art = f["artefact"]
    assert art["generated_docs"] == "phase1/generated_docs"
    assert len(art["absent"]) == 9
    assert "input/docs/L1_product_metadata.md" in art["absent"]
    # the cell refutes ITSELF: one citation in the same run resolves
    assert art["grounded"] == ["phase1/input_doc/L1_product_metadata.txt"], (
        "the reject cell must carry a RESOLVING citation too — that is what "
        "proves the input was published and the citation is what is wrong")
    # every absent citation names a file this run stages under another path
    assert len(f["same_basename_staged_elsewhere"]) == 9
    # the CONTRADICTION
    assert "CITATION is what is wrong" in f["contradiction"]
    # the TEST — a path that EXISTS, written by this run of the review
    assert f["test"], "the rejection carries no test"
    assert (tmp_path / REJECT.name / f["test"]).is_file(), f["test"]


def test_the_accept_control_does_not_move_when_the_reject_case_is_measured(tmp_path):
    """Both directions in ONE invocation shape. A rule that started refusing
    everything would take the accept case with it; a rule that stopped biting
    would take the reject case with it. Neither may move alone."""
    good = run(tree(tmp_path, ACCEPT), "--stage-verdict", "PASS",
               "--json", str(tmp_path / "good.json"))
    bad = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
              "--json", str(tmp_path / "bad.json"))
    gr = json.loads((tmp_path / "good.json").read_text())
    br = json.loads((tmp_path / "bad.json").read_text())
    assert (verdict_of(gr), verdict_of(br)) == ("ACCEPT", "REJECT"), (
        f"good={verdict_of(gr)} bad={verdict_of(br)}\n"
        f"{good.stdout}\n---\n{bad.stdout}")
    assert no_sibling_rejected(gr) and no_sibling_rejected(br)
    # the reject side is the run's verdict too: a proven rejection outranks a
    # sibling that could not look
    assert bad.returncode == 1, bad.stdout


def test_the_rejection_is_caused_by_the_citation_and_nothing_else(tmp_path):
    """The negative control for the rejection itself: copy the REAL reject tree
    and stage the design input at the path its L-docs cite. Nothing else
    changes — same L-docs, same literals, same cell. It must flip to ACCEPT,
    which is what proves the finding is about the provenance rather than about
    that cell."""
    repaired = tmp_path / "repaired"
    shutil.copytree(REJECT, repaired)
    (repaired / "input" / "docs").mkdir(parents=True)
    for f in sorted((repaired / "phase1" / "input_doc").glob("*.txt")):
        shutil.copy(f, repaired / "input" / "docs" / (f.stem + ".md"))
    before = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
                 "--json", str(tmp_path / "before.json"))
    after = run(repaired, "--stage-verdict", "PASS",
                "--json", str(tmp_path / "after.json"))
    bj = json.loads((tmp_path / "before.json").read_text())
    aj = json.loads((tmp_path / "after.json").read_text())
    assert verdict_of(bj) == "REJECT", before.stdout
    assert verdict_of(aj) == "ACCEPT", after.stdout + after.stderr
    assert before.returncode == 1
    assert aj["rejections"] == [], (
        "staging the input must leave NO rejection standing, this rule's or "
        "any sibling's")


# ─────────────────────────────────────────────────────────────────────────────
# the emitted test is a proof, not a citation
# ─────────────────────────────────────────────────────────────────────────────
def test_the_emitted_test_fails_today_and_passes_when_the_run_is_repaired(tmp_path):
    """The doctrine, executable. `an AI rejection must be proven by a
    prompt-derived executable test before repair` is only wired if the test the
    rejection names actually discriminates. So: run the EMITTED file against
    the defective run (must fail), then stage the input where its L-docs say it
    is and run THE SAME FILE again (must pass). A test that could not fail
    proves nothing, and one that could not pass would block every repair."""
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, r.stdout
    emitted = run_dir / json.loads((tmp_path / "r.json").read_text())[
        "rejections"][0]["test"]
    assert emitted.is_file()

    before = subprocess.run([sys.executable, str(emitted)],
                            capture_output=True, text=True)
    assert before.returncode == 1, (
        "the emitted test does not fail on the artefact it was emitted from:\n"
        + before.stdout + before.stderr)
    assert "input/docs/L1_product_metadata.md" in before.stdout

    (run_dir / "input" / "docs").mkdir(parents=True)
    for f in sorted((run_dir / "phase1" / "input_doc").glob("*.txt")):
        shutil.copy(f, run_dir / "input" / "docs" / (f.stem + ".md"))
    after = subprocess.run([sys.executable, str(emitted)],
                           capture_output=True, text=True)
    assert after.returncode == 0, (
        "the emitted test still fails after the repair it asks for:\n"
        + after.stdout + after.stderr)


def test_the_emitted_test_refuses_an_artefact_that_cites_nothing(tmp_path):
    """The emitted test carries the same rule its emitter does: an artefact
    making no checkable claim refutes nothing and certifies nothing. Emptying
    the L-docs must not be a way to make the run's own regression go green."""
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1
    emitted = run_dir / json.loads((tmp_path / "r.json").read_text())[
        "rejections"][0]["test"]
    for f in (run_dir / "phase1" / "generated_docs").glob("L*.json"):
        f.write_text("{}", encoding="utf-8")
    out = subprocess.run([sys.executable, str(emitted)],
                         capture_output=True, text=True)
    assert out.returncode == 1
    assert "no checkable provenance claim" in out.stdout


# ─────────────────────────────────────────────────────────────────────────────
# the disarms, and what each one costs
# ─────────────────────────────────────────────────────────────────────────────
def test_a_disclosure_that_names_no_file_disarms_instead_of_rejecting(tmp_path):
    """Phase 1 writes CITATIONS and DISCLOSURES into the same field. A
    `derived_from_*` key, or a sentence recording that a port was synthesised
    to match an RTL contract, says the fact was NOT read out of a file. There
    is no path to check, and calling that a broken citation would reject a
    layer for being honest. MEASURED: 259 of the corpus's 1008 evidence values
    are disclosures."""
    d = synthetic(tmp_path / "disc", {
        "derived_from_L3": [{"literal": "x"}],
        "v1.6.269 (#127): class detected via L2; the generator always emits "
        "clk/reset_n so L9 is augmented to match the RTL contract.": [{"literal": "y"}],
        "input/docs/real.md": [{"literal": "z"}]})
    r = run(d, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    rec = json.loads((tmp_path / "r.json").read_text())
    assert verdict_of(rec) == "ACCEPT", r.stdout
    assert no_sibling_rejected(rec), r.stdout
    assert record_of(rec)["artefact"]["disclosures"] == 2


def test_the_disclosure_disarm_still_bites_on_a_real_path(tmp_path):
    """The control for the disarm above: a detector that treated everything as
    a disclosure would pass that test against any artefact at all."""
    d = synthetic(tmp_path / "bites", {
        "derived_from_L3": [{"literal": "x"}],
        "input/docs/absent.md": [{"literal": "y"}]})
    r = run(d, "--stage-verdict", "PASS")
    assert r.returncode == 1, r.stdout
    assert "input/docs/absent.md" in r.stdout


def test_an_unreadable_source_disarms_and_a_readable_one_in_the_same_shape_does_not(tmp_path):
    """THE LOAD-BEARING DISARM, and its cost stated as a measurement. The
    published corpus commits some binary design inputs and strips others (15
    `.pdf` blobs committed; 202 `.pdf` citations resolving to nothing), so a
    missing binary is a fact about the SNAPSHOT the reader holds rather than
    about what the layer claimed. Text input is always published, which is what
    makes a missing `.md` evidence about the citation instead.

    Without this disarm the rule rejects 37 of the corpus's 91 roots; with it,
    4. The two trees below are IDENTICAL but for the extension, so the test
    fails if the disarm ever widens to swallow text or narrows to bite binaries.
    """
    binary = synthetic(tmp_path / "bin", {"input/docs/spec.pdf": [{"literal": "x"}]})
    text = synthetic(tmp_path / "txt", {"input/docs/spec.md": [{"literal": "x"}]})
    rb = run(binary, "--stage-verdict", "PASS", "--json", str(tmp_path / "b.json"))
    rt = run(text, "--stage-verdict", "PASS", "--json", str(tmp_path / "t.json"))
    bj = json.loads((tmp_path / "b.json").read_text())
    tj = json.loads((tmp_path / "t.json").read_text())
    assert (verdict_of(bj), verdict_of(tj)) == ("ACCEPT", "REJECT"), (
        rb.stdout + "\n---\n" + rt.stdout)
    assert no_sibling_rejected(bj) and no_sibling_rejected(tj)
    # the text side is the run's verdict too
    assert rt.returncode == 1, rt.stdout


# ─────────────────────────────────────────────────────────────────────────────
# an artefact that claims nothing certifies nothing
# ─────────────────────────────────────────────────────────────────────────────
def test_an_artefact_with_no_provenance_claim_is_not_checked_rather_than_accepted(tmp_path):
    """A layer set that records no provenance at all refutes nothing. Answering
    0 here would be a review of nothing reporting a pass — the same rule R1
    applies to an empty module set one stage down."""
    d = synthetic(tmp_path / "silent", {"derived_from_L3": [{"literal": "x"}]})
    r = run(d, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 2, r.stdout
    assert "NOT ONE path-shaped provenance claim" in r.stdout
    # on the RULE, so this cannot pass because a sibling happened to be the
    # one that could not look
    assert verdict_of(json.loads((tmp_path / "r.json").read_text())) \
        == "NOT_CHECKED", r.stdout


def test_a_missing_generated_docs_directory_is_not_checked(tmp_path):
    d = tmp_path / "bare"
    (d / "phase1").mkdir(parents=True)
    r = run(d, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# it fires on SUCCESS, and only on an ESTABLISHED success
# ─────────────────────────────────────────────────────────────────────────────
def test_the_review_does_not_run_on_a_stage_that_failed(tmp_path):
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "FAIL")
    assert r.returncode == 2, r.stdout
    assert "did not pass" in r.stdout


def test_an_unestablished_verdict_is_not_a_pass(tmp_path):
    r = run(tree(tmp_path, REJECT))
    assert r.returncode == 2, r.stdout
    assert "unestablished" in r.stdout


def test_a_compliance_report_supplies_the_verdict(tmp_path):
    """And BOTH ways: a green stage_phase1 row reaches the rules, a red one
    does not. A test that only proved the refusal would pass against a program
    that refuses every compliance report it is given."""
    green = tmp_path / "green.json"
    green.write_text(json.dumps({"steps": [
        {"id": 1, "stage": STAGE, "status": "PASS"},
        {"id": 9, "stage": "stage2", "status": "FAIL"}]}))
    red = tmp_path / "red.json"
    red.write_text(json.dumps({"steps": [
        {"id": 1, "stage": STAGE, "status": "PASS"},
        {"id": 2, "stage": STAGE, "status": "FAIL"}]}))
    assert run(tree(tmp_path, REJECT), "--compliance", str(green)).returncode == 1
    ok = run(tree(tmp_path, ACCEPT), "--compliance", str(green),
             "--json", str(tmp_path / "ok.json"))
    oj = json.loads((tmp_path / "ok.json").read_text())
    assert verdict_of(oj) == "ACCEPT", ok.stdout
    assert oj["rejections"] == []
    # a green row REACHED the rules — asserted on the rule, because the run's
    # rc 2 here is a sibling that cannot read this cell, not a refusal
    assert run(tree(tmp_path / "red", REJECT),
               "--compliance", str(red)).returncode == 2


# ─────────────────────────────────────────────────────────────────────────────
# §4.05 — the reviewer reads the design INPUT
# ─────────────────────────────────────────────────────────────────────────────
def test_a_denied_intent_path_is_refused_rather_than_read(tmp_path):
    flow = flow_with(tmp_path, intent=["phase1/input_doc/",
                                       "benchmark/oracle/expected_docs/"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS", flow=flow)
    assert r.returncode == 2, r.stdout
    assert "4.05" in r.stdout and "oracle" in r.stdout


def test_the_denial_is_a_list_not_a_hardcode_and_an_allowed_path_still_reads(tmp_path):
    """The control for the guard: with the same shape but a path carrying no
    denied segment, the review reaches its rules and rejects as before. A guard
    that refused everything would pass the test above."""
    flow = flow_with(tmp_path, intent=["phase1/input_doc/", "input/docs/"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS", flow=flow)
    assert r.returncode == 1, r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# a rejection carries evidence or it is not a rejection
# ─────────────────────────────────────────────────────────────────────────────
def test_an_unproven_rejection_is_not_emitted_as_a_rejection(tmp_path):
    """Raise the evidence bar to something this finding does not carry. The
    finding must NOT come out as rc 1 with a missing part, and must NOT be
    quietly downgraded to a pass: it is NOT CHECKED, and the reason names the
    part that is missing."""
    flow = flow_with(tmp_path, rejection_requires=[
        "intent", "artefact", "contradiction", "test", "waiver_reference"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"), flow=flow)
    assert r.returncode == 2, r.stdout
    assert "could not be proven" in r.stdout
    assert "waiver_reference" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == [], "an unproven finding was emitted anyway"
    assert rec["unproven_rejections"][0]["missing_evidence"] == ["waiver_reference"]


# ─────────────────────────────────────────────────────────────────────────────
# the fixture is a copy, not an authored artefact
# ─────────────────────────────────────────────────────────────────────────────
def test_every_fixture_file_matches_the_sha256_of_the_published_cell():
    import hashlib
    prov = json.loads((FIX / "PROVENANCE.json").read_text(encoding="utf-8"))
    seen = 0
    for tree_name, spec in prov["trees"].items():
        for rel, meta in spec["files"].items():
            b = (FIX / tree_name / rel).read_bytes()
            assert hashlib.sha256(b).hexdigest() == meta["sha256"], (
                f"{tree_name}/{rel} is not the published file it claims to be")
            assert len(b) == meta["bytes"]
            seen += 1
    assert seen == sum(len(s["files"]) for s in prov["trees"].values())
    on_disk = {str(p.relative_to(FIX)) for p in FIX.rglob("*") if p.is_file()}
    declared = {"PROVENANCE.json"} | {
        f"{t}/{r}" for t, s in prov["trees"].items() for r in s["files"]}
    assert on_disk == declared, (
        f"undeclared fixture file(s): {sorted(on_disk - declared)}")


# ─────────────────────────────────────────────────────────────────────────────
# the live corpus: the whole partition, pinned
# ─────────────────────────────────────────────────────────────────────────────
#: MEASURED on benchmark-data @ 88621a5, 2026-08-30, over every published cell
#: carrying an L1: 88 cells. THE STAGE NOW CARRIES THREE RULES — #1845's two
#: and #1854's one, merged into the single `on_pass_review:` block the doctrine
#: allows a stage — so this is the COMPOSED partition and not any one rule's:
#: 5 rc 0, 7 rc 1, 76 rc 2. rc 2 dominates because a cell is NOT CHECKED as
#: soon as ANY rule cannot be answered on it, and the three rules need
#: different documents — R1_CITED_CONSTANT needs a cited hexadecimal constant,
#: R2_TOP_MODULE needs a readable design input, R1_CITED_INPUT needs a
#: path-shaped provenance claim. That is the honest reading: the stage was not
#: fully reviewed there, and the run names which rule could not look and why.
#:
#: PER RULE, over the same 88 cells:
#:   R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE    5 ACCEPT,  1 REJECT, 82 NOT CHECKED
#:   R2_TOP_MODULE_PROVENANCE_REFUTED      42 ACCEPT,  5 REJECT, 24 NOT CHECKED,
#:                                         17 DISARMED
#:   R1_CITED_INPUT_ABSENT                 87 ACCEPT,  1 REJECT,  0 NOT CHECKED
#:
#: THE MERGE TOOK NOTHING AWAY, and that is the arithmetic that matters here.
#: Every cell either PR named as a rejection and that is STILL PUBLISHED is
#: still rejected, by the same rule, and no rule widened by one cell:
#:   `pcie_gen5`                     R1_CITED_CONSTANT's, #1845's, unchanged
#:   ddr5/gddr6/hbm3/io_link/sas     R2_TOP_MODULE's, #1845's five, unchanged
#:   `ic/spm/v1.10.18_sky130A`       R1_CITED_INPUT's, and the ONLY one of
#:                                   #1854's four still in the corpus — the
#:                                   other three (`ic/spm/v1.9.96_gf180mcuD`,
#:                                   `ic/spm/v1.5.58_ihp-sg13g2`,
#:                                   `ic/u_hawaii_adc/v1.9.86_sky130A`) have
#:                                   since been withdrawn from benchmark-data,
#:                                   which `& present` below already handles.
#: The rc 0 set did not move by a single cell either: the same five #1845
#: named are the five all three rules read and accept.
_CORPUS_REJECTS = {"protocol_parity/pcie_gen5",
                   "protocol_parity/ddr5",
                   "protocol_parity/gddr6",
                   "protocol_parity/hbm3",
                   "protocol_parity/io_link",
                   "protocol_parity/sas",
                   "ic/spm/v1.10.18_sky130A",
                   # withdrawn from the corpus since #1854 measured them; kept
                   # so a republish is a PASS rather than a surprise
                   "ic/spm/v1.9.96_gf180mcuD",
                   "ic/spm/v1.5.58_ihp-sg13g2",
                   "ic/u_hawaii_adc/v1.9.86_sky130A"}

@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_the_partition_over_the_published_corpus_does_not_move():
    """Pins BOTH sides on the live corpus. The reject set is named cell by cell
    so a rule that widened would show up as an extra name rather than as a
    count nobody reads; the accept side is required to be non-empty so a rule
    that stopped biting cannot pass by rejecting everything."""
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    cells = sorted({p.parents[2] for p in
                    root.rglob("phase1/generated_docs/L1_DATASHEET.json")})
    if not cells:
        pytest.skip("the corpus carries no root with phase1/generated_docs")
    scratch = Path(tempfile.mkdtemp(prefix="phase1_on_pass_review_corpus_"))
    rejects, accepts, unchecked = set(), set(), set()
    mine = {"ACCEPT": set(), "REJECT": set(), "NOT_CHECKED": set(),
            "DISARMED": set()}
    for i, cell in enumerate(cells):
        rel = str(cell.relative_to(root))
        rec_path = scratch / f"cell{i}.json"
        rc = run(cell, "--stage-verdict", "PASS", "--json", str(rec_path),
                 emit=scratch / f"cell{i}").returncode
        {0: accepts, 1: rejects, 2: unchecked}.get(rc, unchecked).add(rel)
        mine[verdict_of(json.loads(rec_path.read_text()))].add(rel)
    shutil.rmtree(scratch, ignore_errors=True)
    present = {str(c.relative_to(root)) for c in cells}
    assert rejects == _CORPUS_REJECTS & present, (
        f"the rejection set moved: {sorted(rejects)}")
    assert accepts or unchecked, "every cell was refused"

    # A DETECTOR THAT FIRES ON MOST OF ITS CORPUS IS THE FAILURE THIS RUNG
    # EXISTS TO PREVENT — and on a stage carrying THREE rules that has to be
    # asked of the RULE, not of the run. The run's rc 0 set is small because
    # rc 2 is honest here: a cell is NOT CHECKED as soon as ANY of the three
    # cannot be answered on it, so comparing rc 0 against rc 1 would be
    # measuring the siblings' silence rather than this rule's appetite.
    # MEASURED above: 87 ACCEPT against 1 REJECT.
    assert mine["REJECT"] == {"ic/spm/v1.10.18_sky130A"} & present, (
        f"THIS RULE's rejection set moved: {sorted(mine['REJECT'])}")
    assert len(mine["ACCEPT"]) > 10 * len(mine["REJECT"]), (
        f"{len(mine['REJECT'])} rejected against {len(mine['ACCEPT'])} "
        f"accepted by this rule alone")
