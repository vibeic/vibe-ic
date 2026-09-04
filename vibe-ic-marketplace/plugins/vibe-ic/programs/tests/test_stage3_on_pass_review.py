#!/usr/bin/env python3
"""The stage-3 ON-PASS review — and the control that stops it manufacturing
confidence in either direction.

WHAT NOTHING ELSE IN THE FLOW CHECKS
====================================
Stage 3's gates grade the LAYOUT: LVS against the netlist, DRC against the
rules, STA against the SDC. Every timing-shaped one of them is measured against
`phase3/stage3/pnr/constraint.sdc` — the deck `pnr.tcl` `read_sdc`s and steps
16, 17, 19, 20 and 23 close against — and NO gate in the flow reads that deck
against the design intent:

  * `sdc_validator_check` DOES cross-check a deck against L8, but its
    `_SEARCH_ROOTS` are `phase2/stage1/fpga` and `phase2/stage2/constraints`.
    The stage-3 sign-off deck is never in either.
  * `clock_plan_check` grades the plan's substance and names no L-doc at all
    (MEASURED: zero occurrences of `L8`, `L9`, `generated_docs` or `intent` in
    that program).
  * `achieved_period_recorded_check` says in its own docstring that "it does
    not judge the number", and reads the asked period out of the run's own
    record rather than out of the intent.

So `sdc_gen`'s tier-4 `_DEFAULT_MHZ` (50.0 MHz -> 20.0 ns) can reach the
sign-off deck, the design is placed, CTS'd and timed at that period, and every
one of those steps goes green because every one is graded against the deck.

WHAT IS ACTUALLY AT RISK, AND WHY BOTH DIRECTIONS ARE ASSERTED
==============================================================
A reviewer that never rejects is WORSE than none — it manufactures confidence
in every artefact it looks at. One that rejects everything is worse still. So
every case below asserts BOTH on REAL published artefacts:

  REJECT  `fixtures/stage3_on_pass_review/reject_sgmii` — verbatim from the
          published cell `evaluation/phase1_parity/sgmii`, whose L8 and L9 both
          declare `clk_main` at 625.0 MHz (`period_ns: 1.6`) while its sign-off
          deck constrains 20.0 ns and says so in its own header ("no
          constraints/*.sdc supplied; clk_period_ns=20.0"). Its
          `post_route_timing.rpt` closes a 2.04 ns path against a
          `20.00 clock clk (rise edge)`. Steps 16, 17, 19 and 20 are all PASS on
          that run. 12.5x slower than the design is specified to run.
  ACCEPT  `fixtures/stage3_on_pass_review/accept_subservient` — verbatim from
          `ic/subservient`: intent 100.0 MHz, deck 10.0 ns. They agree.
  ACCEPT  `fixtures/stage3_on_pass_review/accept_espi_overconstrained` —
          verbatim from `evaluation/phase1_parity/espi`, which carries THE SAME
          fabricated 20.0 ns deck as the reject case against a 20.0 MHz
          (50.0 ns) intent. This is the NARROWING, not a convenience: a deck
          stricter than the intent is not the artefact being worse than what
          was asked. MEASURED over the corpus's five sign-off decks, dropping
          the direction rule takes the rejection set from 1 to 2, and the one it
          adds is this cell.

`fixtures/.../PROVENANCE.json` carries each source file's sha256; nothing in
the fixture is authored.
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
FIX = Path(__file__).resolve().parent / "fixtures" / "stage3_on_pass_review"
REJECT = FIX / "reject_sgmii"
ACCEPT = FIX / "accept_subservient"
OVERCONSTRAINED = FIX / "accept_espi_overconstrained"

#: The stage-1 and stage-2 fixtures. They are the CONTROL: this change adds a
#: rule for a THIRD stage and registers it in the registries all three share
#: (`_RULES`, `_EMITTERS`, `_PRINTERS`), so neither landed stage's verdicts may
#: move by one exit code.
FIX1 = Path(__file__).resolve().parent / "fixtures" / "stage1_on_pass_review"
FIX2 = Path(__file__).resolve().parent / "fixtures" / "stage2_on_pass_review"

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _published_corpus as _pc  # noqa: E402
except Exception:  # pragma: no cover
    _pc = None

yaml = pytest.importorskip("yaml")

DECK_REL = "phase3/stage3/pnr/constraint.sdc"


def run(project, *extra, stage="stage3", flow=None, emit=None):
    """Invoke the review exactly as the flow declares it.

    A rejection WRITES the run's own regression INTO the run tree, so every
    test that can provoke one runs against `tree()`, a per-test copy. Nothing
    here ever writes into the shipped fixture."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    argv = [sys.executable, str(PROG), str(project), "--stage", stage,
            "--flow-def", str(flow or FLOW)]
    if emit is not None:
        argv += ["--emit-test", str(emit)]
    return subprocess.run(argv + list(extra), capture_output=True, text=True,
                          env=env)


def tree(tmp_path, which):
    d = tmp_path / which.name
    if not d.exists():
        shutil.copytree(which, d)
    return d


def declaration(stage="stage3"):
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == stage:
            return st.get("on_pass_review")
    raise AssertionError(f"{stage} is not declared")


def flow_with(tmp_path, **override):
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == "stage3":
            st["on_pass_review"] = {**st["on_pass_review"], **override}
    p = tmp_path / "flow.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# the declaration is in the flow, and nowhere else
# ─────────────────────────────────────────────────────────────────────────────
def test_stage3_declares_an_on_pass_review_naming_a_verification_tier_skill():
    d = declaration()
    assert d is not None, "stage3 declares no on_pass_review"
    assert d["fires_on"] == "stage_pass"
    assert d["verdict"] in ("advisory", "blocking"), (
        "BLOCKING vs ADVISORY must be declared, and declared HERE — whether a "
        "rejection stops the flow is the flow's decision, not the reviewer's")
    tier = json.loads((PLUGIN / "skills" / "_classification.json")
                      .read_text(encoding="utf-8"))["tiers"]["verification"]["skills"]
    assert d["skill"] in tier, (
        f"{d['skill']!r} is not a member of the verification tier {tier}")
    assert (PLUGIN / "skills" / d["skill"] / "SKILL.md").is_file()
    assert d["rejection_requires"] == ["intent", "artefact", "contradiction",
                                       "test"]


def test_the_declaration_is_not_a_second_membership_roster():
    """`flow_stage_membership_single_declaration_check` P1 discovers a roster by
    SHAPE: any stage key whose value is a list naming declared step ids is a
    second membership declaration."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    step_ids = {str(s["id"]) for s in doc["steps"]}
    d = declaration()
    for key, val in d.items():
        if isinstance(val, list):
            named = {str(v) for v in val} & step_ids
            assert not named, f"on_pass_review.{key} names step id(s) {named}"


def test_the_declared_artefact_is_the_deck_stage3_actually_signs_off_against():
    """The rule is only about anything if it reads the deck the stage USED. On
    the published cells `pnr.tcl` read_sdc's exactly this path."""
    assert DECK_REL in declaration()["artefact"]


# ─────────────────────────────────────────────────────────────────────────────
# BOTH DIRECTIONS, ON REAL ARTEFACTS
# ─────────────────────────────────────────────────────────────────────────────
def test_a_real_known_good_artefact_is_accepted(tmp_path):
    r = run(tree(tmp_path, ACCEPT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ACCEPT" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == []
    assert rec["not_checked"] == [], (
        "an ACCEPT must be a rule that READ both sides, not one that could not "
        "look")
    obs = rec["observations"][0]
    assert obs["intent"]["period_ns"] == 10.0
    assert obs["artefact"]["fastest_clock"]["period_ns"] == 10.0


def test_a_real_run_signed_off_slower_than_its_intent_asks_is_rejected(tmp_path):
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REJECT" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert len(rec["rejections"]) == 1
    f = rec["rejections"][0]
    assert f["rule"] == "R3_SIGNOFF_CLOCK_SLOWER_THAN_INTENT"
    # the INTENT it read — the design INPUT, and the period it asks for
    assert f["intent"]["file"].endswith("L8_TIMING_WAVEFORM.json")
    assert f["intent"]["value"] == "clk_main"
    assert f["intent"]["period_ns"] == 1.6
    # the ARTEFACT fact it read — the deck the stage signed off against
    assert f["artefact"]["file"] == DECK_REL
    assert f["artefact"]["fastest_clock"]["period_ns"] == 20.0
    assert "create_clock" in f["artefact"]["fastest_clock"]["line"]
    # the CONTRADICTION, with the factor spelled out, and the blast radius
    assert "12.5" in f["contradiction"]
    assert "1.6 ns" in f["contradiction"] and "20.0 ns" in f["contradiction"]
    stamped = {s["file"] for s in f["signed_off_under"]}
    assert "phase3/stage3/sta/post_route_timing.rpt" in stamped, (
        "the sign-off evidence closed under the refuted period was not found")
    # the TEST — a path that EXISTS, written by this run of the review
    assert f["test"], "the rejection carries no test"
    assert (tmp_path / REJECT.name / f["test"]).is_file(), f["test"]


def test_a_deck_stricter_than_the_intent_is_not_a_contradiction(tmp_path):
    """The NARROWING, on a real cell carrying the SAME fabricated 20.0 ns deck
    as the reject case. Timing that closes at 20.0 ns closes at the 50.0 ns the
    intent asks for, so the artefact is not worse than what was asked, and a
    review that rejected it would be complaining about conservatism."""
    r = run(tree(tmp_path, OVERCONSTRAINED), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 0, r.stdout + r.stderr
    rec = json.loads((tmp_path / "r.json").read_text())
    obs = rec["observations"][0]
    assert obs["intent"]["period_ns"] == 50.0
    assert obs["artefact"]["fastest_clock"]["period_ns"] == 20.0
    assert "SHORTER" in obs["observation"], (
        "the acceptance must SAY it is accepting a deck that does not match, "
        "or the narrowing is invisible to its reader")


def test_the_narrowing_is_load_bearing_and_not_a_blanket_disarm(tmp_path):
    """The two cells carry a BYTE-IDENTICAL deck. One is rejected and one is
    accepted, so the direction rule — and only the direction rule — is what
    separates them. A disarm keyed on the deck rather than on the comparison
    would take both."""
    a = (OVERCONSTRAINED / DECK_REL).read_text()
    b = (REJECT / DECK_REL).read_text()
    assert a == b, "the two cells no longer share a deck; this control is void"
    assert run(tree(tmp_path, OVERCONSTRAINED), "--stage-verdict",
               "PASS").returncode == 0
    assert run(tree(tmp_path, REJECT), "--stage-verdict", "PASS").returncode == 1


def test_the_emitted_test_fails_today_and_passes_when_the_run_is_repaired(tmp_path):
    """The doctrine, executable. Run the EMITTED file against the defective run
    (must fail), then regenerate the deck at the period the intent asks for and
    run THE SAME FILE again (must pass). A test that could not fail proves
    nothing, and one that could not pass would block every repair."""
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, r.stdout
    emitted = run_dir / json.loads(
        (tmp_path / "r.json").read_text())["rejections"][0]["test"]
    assert emitted.is_file()

    before = subprocess.run([sys.executable, str(emitted)],
                            capture_output=True, text=True)
    assert before.returncode == 1, (
        "the emitted test does not fail on the artefact it was emitted from:\n"
        + before.stdout + before.stderr)
    assert "12.5x slower" in before.stdout

    deck = run_dir / DECK_REL
    deck.write_text(deck.read_text().replace("-period 20.0", "-period 1.6"),
                    encoding="utf-8")
    after = subprocess.run([sys.executable, str(emitted)],
                           capture_output=True, text=True)
    assert after.returncode == 0, (
        "the emitted test still fails after the repair it asks for:\n"
        + after.stdout + after.stderr)


def test_the_emitted_test_refuses_an_empty_artefact_rather_than_passing(tmp_path):
    """The emitted test carries the same rule its emitter does: a deck that
    constrains nothing refutes nothing. Emptying the deck must not be a way to
    make the run's own regression go green."""
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1
    emitted = run_dir / json.loads(
        (tmp_path / "r.json").read_text())["rejections"][0]["test"]
    (run_dir / DECK_REL).write_text("# every constraint removed\n",
                                    encoding="utf-8")
    out = subprocess.run([sys.executable, str(emitted)],
                         capture_output=True, text=True)
    assert out.returncode == 1
    assert "constrains nothing" in out.stdout


def test_the_emitted_test_refuses_an_intent_that_asks_for_nothing(tmp_path):
    """And the other empty side: deleting the design's declared frequency must
    not turn the run's own regression green either."""
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1
    emitted = run_dir / json.loads(
        (tmp_path / "r.json").read_text())["rejections"][0]["test"]
    for rel in ("phase1/generated_docs/L8_TIMING_WAVEFORM.json",
                "phase1/generated_docs/L9_INTEGRATION_SPEC.json"):
        p = run_dir / rel
        d = json.loads(p.read_text())
        d["clock_mhz"] = None
        d["clock_domains"] = []
        p.write_text(json.dumps(d), encoding="utf-8")
    out = subprocess.run([sys.executable, str(emitted)],
                         capture_output=True, text=True)
    assert out.returncode == 1
    assert "no intent document declares a clock frequency" in out.stdout


def test_the_rejection_is_caused_by_the_deck_and_nothing_else(tmp_path):
    """The negative control for the rejection itself: copy the REAL reject tree
    and change ONLY the deck's period. Same L8, same L9, same reports, same
    cell. It must flip to ACCEPT, which is what proves the finding is about the
    artefact rather than about that cell."""
    repaired = tmp_path / "repaired"
    shutil.copytree(REJECT, repaired)
    deck = repaired / DECK_REL
    deck.write_text(deck.read_text().replace("-period 20.0", "-period 1.6"),
                    encoding="utf-8")
    assert run(tree(tmp_path, REJECT), "--stage-verdict", "PASS").returncode == 1
    after = run(repaired, "--stage-verdict", "PASS")
    assert after.returncode == 0, after.stdout + after.stderr


def test_the_accept_control_does_not_move_when_the_reject_case_is_measured(tmp_path):
    """Both directions in ONE invocation shape. A rule that started refusing
    everything would take the accept cases with it; a rule that stopped biting
    would take the reject case with it. Neither may move alone."""
    good = run(tree(tmp_path, ACCEPT), "--stage-verdict", "PASS")
    lax = run(tree(tmp_path, OVERCONSTRAINED), "--stage-verdict", "PASS")
    bad = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS")
    assert (good.returncode, lax.returncode, bad.returncode) == (0, 0, 1), (
        f"good={good.returncode} lax={lax.returncode} bad={bad.returncode}\n"
        f"{good.stdout}\n---\n{lax.stdout}\n---\n{bad.stdout}")


# ─────────────────────────────────────────────────────────────────────────────
# an absent declaration is not an agreement; an absent artefact certifies nothing
# ─────────────────────────────────────────────────────────────────────────────
def test_an_intent_that_declares_no_frequency_is_not_checked_rather_than_accepted(tmp_path):
    """MEASURED on `evaluation/phase1_parity/mdio`: L8.clock_mhz is null and
    both clock-domain lists are empty. Answering ACCEPT would certify every deck
    on every run whose intent never stated a frequency."""
    run_dir = tree(tmp_path, REJECT)
    for rel in ("phase1/generated_docs/L8_TIMING_WAVEFORM.json",
                "phase1/generated_docs/L9_INTEGRATION_SPEC.json"):
        p = run_dir / rel
        d = json.loads(p.read_text())
        d["clock_mhz"] = None
        d["clock_domains"] = []
        p.write_text(json.dumps(d), encoding="utf-8")
    r = run(run_dir, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "no declared intent document carries a clock frequency" in r.stdout


def test_an_absent_signoff_deck_is_not_an_acceptance(tmp_path):
    """MEASURED: 193 of the corpus's 197 L9-bearing runs land here. A run that
    never staged a deck refutes nothing and certifies nothing."""
    run_dir = tree(tmp_path, ACCEPT)
    (run_dir / DECK_REL).unlink()
    r = run(run_dir, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "staged no stage-3 sign-off deck" in r.stdout


def test_a_deck_that_constrains_nothing_is_not_an_acceptance(tmp_path):
    run_dir = tree(tmp_path, ACCEPT)
    (run_dir / DECK_REL).write_text("# no create_clock here\n", encoding="utf-8")
    r = run(run_dir, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "creates no clock with a period" in r.stdout


def test_an_intent_that_declares_two_disagreeing_primaries_cannot_put_the_question(tmp_path):
    """An SDC cannot be validated against a contradictory constraint set, and
    picking one of the two would be the reviewer resolving a disagreement the
    intent has not resolved."""
    run_dir = tree(tmp_path, REJECT)
    p = run_dir / "phase1/generated_docs/L8_TIMING_WAVEFORM.json"
    d = json.loads(p.read_text())
    d["clock_mhz"] = None
    d["clock_domains"] = [{"name": "clk_main", "role": "primary", "period_ns": 1.6},
                          {"name": "clk_alt", "role": "primary", "period_ns": 4.0}]
    p.write_text(json.dumps(d), encoding="utf-8")
    r = run(run_dir, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "DIFFERENT periods" in r.stdout


def test_an_incidental_document_frequency_mention_is_not_a_declared_domain(tmp_path):
    """The published corpus routinely carries a second clock_domains record with
    `role: extracted_from_doc_freq_mention` — a number scraped out of prose.
    Reading it as the design's period would make the accept case contradictory
    and the whole rule NOT CHECKED, which is how a rule stops biting quietly."""
    d = json.loads((ACCEPT / "phase1/generated_docs/L8_TIMING_WAVEFORM.json")
                   .read_text())
    roles = [c.get("role") for c in d["clock_domains"]]
    assert "extracted_from_doc_freq_mention" in roles, (
        "the fixture no longer carries the incidental record this guards")
    assert run(tree(tmp_path, ACCEPT), "--stage-verdict", "PASS").returncode == 0


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


def test_a_compliance_report_supplies_the_verdict_both_ways(tmp_path):
    green = tmp_path / "green.json"
    green.write_text(json.dumps({"steps": [
        {"id": 16, "stage": "stage3", "status": "PASS"},
        {"id": 1, "stage": "stage1", "status": "FAIL"}]}))
    red = tmp_path / "red.json"
    red.write_text(json.dumps({"steps": [
        {"id": 16, "stage": "stage3", "status": "PASS"},
        {"id": 23, "stage": "stage3", "status": "FAIL"}]}))
    assert run(tree(tmp_path, REJECT), "--compliance", str(green)).returncode == 1
    assert run(tree(tmp_path, ACCEPT), "--compliance", str(green)).returncode == 0
    assert run(tree(tmp_path / "red", REJECT),
               "--compliance", str(red)).returncode == 2


# ─────────────────────────────────────────────────────────────────────────────
# §4.05 — the reviewer reads the design INPUT
# ─────────────────────────────────────────────────────────────────────────────
def test_a_denied_intent_path_is_refused_rather_than_read(tmp_path):
    flow = flow_with(tmp_path, intent=[
        "phase1/generated_docs/L8_TIMING_WAVEFORM.json",
        "benchmark/oracle/expected_period.json"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS", flow=flow)
    assert r.returncode == 2, r.stdout
    assert "4.05" in r.stdout and "oracle" in r.stdout


def test_the_denial_is_a_list_not_a_hardcode_and_an_allowed_path_still_reads(tmp_path):
    """The control for the guard: same shape, no denied segment, and the review
    reaches its rule and rejects as before."""
    flow = flow_with(tmp_path, intent=[
        "phase1/generated_docs/L8_TIMING_WAVEFORM.json",
        "phase1/generated_docs/L9_INTEGRATION_SPEC.json"])
    assert run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
               flow=flow).returncode == 1


def test_the_review_reads_no_sta_or_synthesis_log_to_reach_its_verdict(tmp_path):
    """§4.05 in the direction that matters for THIS rule: the contradiction is
    between the L-docs and the deck. Deleting every report in the tree must not
    change the verdict — only the blast radius it can cite."""
    stripped = tmp_path / "stripped"
    shutil.copytree(REJECT, stripped)
    shutil.rmtree(stripped / "phase3" / "stage3" / "sta")
    shutil.rmtree(stripped / "phase3" / "stage3" / "cts")
    r = run(stripped, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, r.stdout
    assert json.loads((tmp_path / "r.json").read_text())[
        "rejections"][0]["signed_off_under"] == []


# ─────────────────────────────────────────────────────────────────────────────
# a rejection carries evidence or it is not a rejection
# ─────────────────────────────────────────────────────────────────────────────
def test_an_unproven_rejection_is_not_emitted_as_a_rejection(tmp_path):
    flow = flow_with(tmp_path, rejection_requires=[
        "intent", "artefact", "contradiction", "test", "waiver_reference"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"), flow=flow)
    assert r.returncode == 2, r.stdout
    assert "could not be proven" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == [], "an unproven finding was emitted anyway"
    assert rec["unproven_rejections"][0]["missing_evidence"] == ["waiver_reference"]


# ─────────────────────────────────────────────────────────────────────────────
# THE CONTROL: stage 1 must not move
# ─────────────────────────────────────────────────────────────────────────────
def test_stage1_verdicts_do_not_move(tmp_path):
    """R3 is registered in `_RULES`, `_EMITTERS` and `_PRINTERS` — the three
    dicts every rule shares. The control is the stage-1 partition: exactly the
    same two exit codes on exactly the same two published cells, and R1's own
    evidence lines still rendered by its own printer."""
    good = run(tree(tmp_path, FIX1 / "accept_spm"), "--stage-verdict", "PASS",
               stage="stage1")
    bad = run(tree(tmp_path, FIX1 / "reject_caravel"), "--stage-verdict", "PASS",
              stage="stage1")
    assert (good.returncode, bad.returncode) == (0, 1), (
        f"the stage-1 control moved: good={good.returncode} bad={bad.returncode}"
        f"\n{good.stdout}\n---\n{bad.stdout}")
    assert "DISARMED" in good.stdout
    assert "R1_INTENT_TOP_NOT_BUILT" in bad.stdout
    assert "RESTAMPED" in bad.stdout, "R1's own evidence line was lost"


def test_stage2_verdicts_do_not_move(tmp_path):
    """The second control, on the rule v1.13.2 landed. R3 must not reach it,
    borrow its printer, or move any of its three published cells."""
    good = run(tree(tmp_path, FIX2 / "accept_spm"), "--stage-verdict", "PASS",
               stage="stage2")
    disarm = run(tree(tmp_path, FIX2 / "disarm_caravel"), "--stage-verdict",
                 "PASS", stage="stage2")
    bad = run(tree(tmp_path, FIX2 / "reject_opentitan_aes"), "--stage-verdict",
              "PASS", stage="stage2")
    assert (good.returncode, disarm.returncode, bad.returncode) == (0, 0, 1), (
        f"the stage-2 control moved: good={good.returncode} "
        f"disarm={disarm.returncode} bad={bad.returncode}\n{good.stdout}\n---\n"
        f"{disarm.stdout}\n---\n{bad.stdout}")
    assert "R2_INTENT_PIN_NOT_IN_NETLIST" in bad.stdout
    assert "ABSENT" in bad.stdout, "R2's own evidence line was lost"


def test_each_rule_has_its_own_emitter_and_printer_and_r3_borrows_neither():
    """The registry contract v1.13.2 landed: a rule with no `_EMITTERS` entry
    raises KeyError inside `emit_test` rather than writing somebody else's test,
    and `review()` then refuses the rejection as unproven. R3 is registered in
    all three dicts, and no two rules share an emitter or a printer."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sopr", PROG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    ids = {rid for rules in m._RULES.values() for rid, _ in rules}
    assert "R3_SIGNOFF_CLOCK_SLOWER_THAN_INTENT" in ids
    assert ids <= set(m._EMITTERS), f"no emitter for {ids - set(m._EMITTERS)}"
    assert ids <= set(m._PRINTERS), f"no printer for {ids - set(m._PRINTERS)}"
    for reg in (m._EMITTERS, m._PRINTERS):
        fns = [reg[i] for i in ids]
        assert len(set(fns)) == len(fns), (
            "two rules share one renderer; each artefact shape is its own")


def test_a_rule_with_no_emitter_is_refused_rather_than_given_another_rules_test(tmp_path):
    """The contract's teeth, exercised rather than described: strip R3 from
    `_EMITTERS` and the rejection must NOT come out as rc 1 with somebody
    else's test attached, and must NOT be downgraded to a pass."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sopr2", PROG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m._EMITTERS.pop("R3_SIGNOFF_CLOCK_SLOWER_THAN_INTENT")
    run_dir = tree(tmp_path, REJECT)
    decl = declaration()
    with pytest.raises(KeyError):
        m.emit_test(tmp_path / "t.py",
                    {**m.rule_signoff_clock_slower_than_intent(run_dir, decl),
                     "rule": "R3_SIGNOFF_CLOCK_SLOWER_THAN_INTENT"}, "stage3")


def test_the_stages_do_not_share_a_rule(tmp_path):
    """One program, one flow block per stage — and one rule set per stage. A
    stage-3 tree run as stage1 or stage2, and a stage-1 tree run as stage3, must
    be NOT CHECKED, never a pass borrowed from another stage's rule."""
    assert run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
               stage="stage1").returncode == 2
    assert run(tree(tmp_path / "s2", REJECT), "--stage-verdict", "PASS",
               stage="stage2").returncode == 2
    assert run(tree(tmp_path / "x", FIX1 / "accept_spm"), "--stage-verdict",
               "PASS", stage="stage3").returncode == 2


# ─────────────────────────────────────────────────────────────────────────────
# the review does not re-derive the artefact
# ─────────────────────────────────────────────────────────────────────────────
def test_the_review_starts_no_process_so_it_cannot_re_derive_the_artefact():
    """A reviewer that re-runs the router or regenerates the deck has replaced
    the program rather than reviewed it. Reuses stage 1's detector so the two
    cannot drift."""
    import test_stage1_on_pass_review as t1
    assert t1._spawn_names(PROG) == set(), (
        "stage_on_pass_review must read the artefact the stage left behind, "
        f"not produce another one; found {t1._spawn_names(PROG)}")


# ─────────────────────────────────────────────────────────────────────────────
# the live corpus: the whole partition, pinned
# ─────────────────────────────────────────────────────────────────────────────
#: Historical identities measured on benchmark-data, 2026-08-30.  They remain
#: provenance for the focused fixtures above, NOT a mutable acceptance baseline
#: for every corpus revision: older corpus commits do not yet carry every one
#: of those subjects' sign-off decks.  The corpus test below instead proves the
#: classification of every subject for which the exact pinned corpus has a
#: denominator, and proves that NOT_CHECKED is not counted as acceptance.
_CORPUS_REJECTS = {"evaluation/phase1_parity/sgmii"}
_CORPUS_ACCEPTS = {"evaluation/phase1_parity/espi",
                   "ic/caravel_user_project",
                   "ic/subservient"}


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_the_partition_over_the_published_corpus_does_not_move():
    """Prove both sides over the exact corpus without an exception roster.

    Corpus history can add or relocate a subject, and an older commit can carry
    L9 before it carries the stage-3 SDC.  Such a subject has no comparison
    denominator and must remain NOT_CHECKED; it must never be smuggled into the
    acceptance side merely to preserve a frozen name list.  Every executable
    classification below therefore has to carry its own numeric proof, and
    every rejection's generated regression has to fail on the copied run.
    """
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    cells = sorted({p.parent.parent.parent for p in
                    root.rglob("phase1/generated_docs/L9_INTEGRATION_SPEC.json")})
    if not cells:
        pytest.skip("the corpus carries no cell with an L9")
    scratch = Path(tempfile.mkdtemp(prefix="on_pass_review_s3_corpus_"))
    rejects, accepts, not_checked, run_dirs, records = set(), set(), set(), {}, {}
    for i, cell in enumerate(cells):
        run_dir = scratch / f"cell{i}"
        shutil.copytree(cell, run_dir)
        record = scratch / f"cell{i}.json"
        result = run(run_dir, "--stage-verdict", "PASS", "--json", str(record))
        rc = result.returncode
        rel = str(cell.relative_to(root))
        run_dirs[rel] = run_dir
        assert record.is_file(), result.stdout + result.stderr
        records[rel] = json.loads(record.read_text())
        if rc == 1:
            rejects.add(rel)
        elif rc == 0:
            accepts.add(rel)
        elif rc == 2:
            not_checked.add(rel)
        else:
            raise AssertionError(
                f"{rel}: review crashed with rc={rc}:\n{result.stdout}{result.stderr}")

    assert rejects | accepts | not_checked == set(run_dirs)
    assert not (rejects & accepts or rejects & not_checked or accepts & not_checked)

    for rel in rejects:
        rec = records[rel]
        assert rec["not_checked"] == []
        assert len(rec["rejections"]) == 1
        finding = rec["rejections"][0]
        assert finding["rule"] == "R3_SIGNOFF_CLOCK_SLOWER_THAN_INTENT"
        asked = float(finding["intent"]["period_ns"])
        signed_off = float(finding["artefact"]["fastest_clock"]["period_ns"])
        assert signed_off > asked, (rel, asked, signed_off)
        proofs = list((run_dirs[rel] / "reports/phase3/gates/on_pass_review")
                      .glob("test_*.py"))
        assert len(proofs) == 1, (rel, proofs)
        proof = subprocess.run([sys.executable, str(proofs[0])],
                               cwd=str(run_dirs[rel]), capture_output=True,
                               text=True)
        assert proof.returncode == 1, proof.stdout + proof.stderr

    for rel in accepts:
        rec = records[rel]
        assert rec["rejections"] == []
        assert rec["not_checked"] == [], (
            f"{rel}: NOT_CHECKED was counted as acceptance")
        findings = [f for f in rec["observations"]
                    if f["rule"] == "R3_SIGNOFF_CLOCK_SLOWER_THAN_INTENT"]
        assert len(findings) == 1, (rel, findings)
        finding = findings[0]
        asked = float(finding["intent"]["period_ns"])
        signed_off = float(finding["artefact"]["fastest_clock"]["period_ns"])
        assert signed_off <= asked, (rel, asked, signed_off)

    for rel in not_checked:
        rec = records[rel]
        assert rec["rejections"] == []
        assert rec["observations"] == []
        assert rec["not_checked"], f"{rel}: rc 2 carried no reason"

    # A vacuous corpus (all NOT_CHECKED), an always-accept reviewer, and an
    # always-reject reviewer must each fail this test.
    assert rejects, "no corpus subject exercised the rejection side"
    assert accepts, "every cell was refused; a reviewer that rejects all is none"
