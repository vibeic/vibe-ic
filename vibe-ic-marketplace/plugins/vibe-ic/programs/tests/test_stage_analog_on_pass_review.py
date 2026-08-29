#!/usr/bin/env python3
"""The stage_analog ON-PASS review — and the control that stops it
manufacturing confidence in either direction.

WHAT THIS RULE IS FOR, AND WHY NO A-GATE HOLDS IT
=================================================
A1 reads the INTENT (`phase1/generated_docs/L5_ADI_SPEC.json`) ONCE and writes
`phase3/analog/<block>/spec.json`. From A2 to A9 that file IS the spec: the
topology is chosen against it, the deck sized against it, the PVT sweep graded
against it — `corner_yield_vs_spec_check`'s own docstring is "parse yield table
vs spec.json limits" — and the layout and the hardmacro signed off on the
result.

MEASURED on this tree: of the 54 `analog_*` programs, SEVEN open
`L5_ADI_SPEC.json`. FIVE are PRODUCERS (`analog_a1_spec_emit`,
`analog_a2_topology_emit`, `analog_a3_netlist_emit`,
`analog_real_corner_sweep`, `analog_one_shot_runner`). The other two are
checkers asking a different question: `analog_a0_skip_forbidden_check` uses
`analog_blocks_detected=false` as a waiver for a forbidden skip file and never
reads a block's requirements, and `analog_content_detected_must_emit_l5_check`
grades L5 against the input DOCS and never opens a `spec.json`. NO A1-A9 GATE
READS A BLOCK'S REQUIREMENTS OUT OF L5 AT ALL — one of them opens an L doc for
an unrelated purpose (`analog_netlist_pdk_check` reads L19_CONSTRAINTS_PDK,
the PDK constraint layer), and that is the whole of it.

So nothing compares the spec the stage GRADES AGAINST with the spec the design
ASKED FOR. A1's own gate is explicit about its threshold —
`analog_a1_spec_extract_check` certifies a block that "declares >= 1 spec
field" — and MEASURED on `reject_adc_stub` it reports "PASS: 2/2 block(s)
clean", as do the A2 and A3 gates, on a `spec.json` whose single row is
`vout target 1.0 V` while the intent declares `Vout 1.2 V (1.1-1.3)` and twelve
further numeric requirements. That is the shape this rung exists for: an
artefact that passes every gate and is still not the thing that was asked for.

WHY BOTH DIRECTIONS ARE ASSERTED, ON REAL ARTEFACTS
===================================================
A reviewer that never rejects is WORSE than none — it manufactures confidence
in every artefact it looks at. One that rejects everything is worse still: it
is the same failure as a detector that fires on 21 of 21 subjects, and it
trains its readers to skip it. Neither is caught by a test that proves one
direction, so every case below asserts BOTH, and on artefacts nobody authored:

  ACCEPT  `fixtures/.../accept_adc_conv` — from a completed run of the
          incremental delta-sigma ADC front-end. 13 numeric requirements
          across 2 blocks, every one carried.
  REJECT  `fixtures/.../reject_adc_stub` — the SAME design, a BYTE-IDENTICAL
          L5 (asserted below), and the analog runner's deterministic-stub A1
          tier. The control therefore varies the ARTEFACT alone while the
          intent and the harness are held fixed; a red on both arms would be
          the instrument, not the subject.
  ACCEPT  `fixtures/.../accept_published_partial` — the published benchmark
          cell, where the intent declares no numeric requirement for one of
          the two blocks. That block is DISARMED by the intent's own
          disclosure and the other is measured and accepted, so the disarm is
          exercised on real published data rather than asserted.

THE PARTITION, AND WHY THE DISARM IS NARROW
===========================================
Swept over every root on this fleet carrying an A1 `spec.json` (1149 roots):

    ACCEPT                                406 block observations
    REJECT                                  6   (2 on the run above;
                                                 4 identical copies of one
                                                 program's own pytest tree)
    disarmed — intent declares no
      numeric requirement for the block   196
    not checked — no L5, or no spec.json  794

The disarm fires on the INTENT's disclosure and never on the ARTEFACT's. A
`spec.json` that discloses `extraction_strategy: deterministic_stub` is NOT
disarmed, and that is the whole point: the artefact saying it made the number
up does not retract the thirteen the intent supplied. MEASURED, the
`low_confidence` / `spurious` half of the disarm moves ZERO blocks that carry
a numeric requirement on this corpus — it is there because the intent uses
those fields to decline, not because it was needed to get the count down.
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
FIX = Path(__file__).resolve().parent / "fixtures" / "stage_analog_on_pass_review"
ACCEPT = FIX / "accept_adc_conv"
REJECT = FIX / "reject_adc_stub"
PUBLISHED = FIX / "accept_published_partial"
STAGE = "stage_analog"
RULE = "R_ANALOG_INTENT_SPEC_NOT_THE_GRADED_SPEC"

yaml = pytest.importorskip("yaml")


def _program():
    """The reviewer, imported rather than shelled out to.

    The registry invariants below are about the module's own tables,
    which no amount of subprocess output can show.
    """
    import importlib.util as _u
    spec = _u.spec_from_file_location("_sopr_under_test", PROG)
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(project, *extra, flow=None, emit=None, stage=STAGE):
    """Invoke the review exactly as the flow declares it.

    A rejection WRITES the run's own regression INTO the run tree, so every
    test that can provoke one runs against `tree()`, a per-test copy. Nothing
    here ever writes into the shipped fixture.
    """
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    argv = [sys.executable, str(PROG), str(project), "--stage", stage,
            "--flow-def", str(flow or FLOW)]
    if emit is not None:
        argv += ["--emit-test", str(emit)]
    return subprocess.run(argv + list(extra), capture_output=True, text=True,
                          env=env)


@pytest.fixture
def tree(tmp_path_factory):
    """A writable copy of a fixture tree.

    `tempfile.mkdtemp` and not `tmp_path`: this fleet's pytest tmp path
    carries a newline, and a path with a newline in it breaks tools invoked
    with it. Nothing here invokes one, but the copy is what a rejection writes
    into and the habit is cheap.
    """
    made = []

    def _mk(src: Path) -> Path:
        d = Path(tempfile.mkdtemp(prefix="onpass_analog_"))
        made.append(d)
        dst = d / src.name
        shutil.copytree(src, dst)
        return dst

    yield _mk
    for d in made:
        shutil.rmtree(d, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# the control's own premise
# ─────────────────────────────────────────────────────────────────────────────
def test_the_two_arms_differ_in_the_artefact_and_only_in_the_artefact():
    """A red on two trees can be one instrument. Hold the intent fixed.

    The accept and reject arms are the same design, and this asserts it by
    bytes rather than by claim: identical L5, different spec.json. When this
    ever stops holding, the control below has stopped being a control and is
    just two unrelated runs that happen to answer differently.
    """
    rel = "phase1/generated_docs/L5_ADI_SPEC.json"
    assert (ACCEPT / rel).read_bytes() == (REJECT / rel).read_bytes(), (
        "the two arms no longer share an intent; the control varies more than "
        "the artefact")
    for block in ("delta_sigma", "ldo"):
        rel = f"phase3/analog/{block}/spec.json"
        assert (ACCEPT / rel).read_bytes() != (REJECT / rel).read_bytes(), (
            f"the two arms carry the same {rel}; there is nothing for the "
            f"review to answer differently about")


def test_the_provenance_records_the_bytes_that_shipped():
    """Nothing in the fixture is authored, and this is how that is checked."""
    import hashlib
    prov = json.loads((FIX / "PROVENANCE.json").read_text(encoding="utf-8"))
    seen = 0
    for name, tree_meta in prov["trees"].items():
        for rel, meta in tree_meta["files"].items():
            b = (FIX / name / rel).read_bytes()
            assert len(b) == meta["bytes"], f"{name}/{rel} size moved"
            assert hashlib.sha256(b).hexdigest() == meta["sha256"], (
                f"{name}/{rel} is no longer the file that was copied")
            seen += 1
    assert seen == 9, f"expected 9 recorded files, found {seen}"


# ─────────────────────────────────────────────────────────────────────────────
# both directions
# ─────────────────────────────────────────────────────────────────────────────
def test_a_known_good_run_is_accepted(tree):
    p = tree(ACCEPT)
    r = run(p, "--stage-verdict", "PASS")
    assert r.returncode == 0, f"expected rc 0, got {r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "ACCEPT" in r.stdout
    assert not list(p.rglob("test_*.py")), (
        "an ACCEPT emitted a regression; only a rejection may write into the "
        "run it reviews")


def test_a_known_bad_run_is_rejected_and_the_evidence_names_it(tree):
    p = tree(REJECT)
    out = p / "rep.json"
    r = run(p, "--stage-verdict", "PASS", "--json", str(out))
    assert r.returncode == 1, f"expected rc 1, got {r.returncode}\n{r.stdout}\n{r.stderr}"

    rec = json.loads(out.read_text(encoding="utf-8"))
    assert not rec["unproven_rejections"], rec["unproven_rejections"]
    assert not rec["not_checked"], rec["not_checked"]
    assert len(rec["rejections"]) == 1
    f = rec["rejections"][0]
    assert f["rule"] == RULE

    # The four parts `rejection_requires:` names, each actually carrying
    # something — not merely present as a key.
    for part in ("intent", "artefact", "contradiction", "test"):
        assert f.get(part), f"rejection carries no {part}"
    assert f["intent"]["intent_rel"] == "phase1/generated_docs/L5_ADI_SPEC.json"

    # THE ACTUAL CONTRADICTION, not merely "a" contradiction. Both shapes are
    # present on this artefact and both must be named.
    blocks = {b["block"]: b for b in f["findings_per_block"]}
    assert set(blocks) == {"delta_sigma", "ldo"}
    dropped_ldo = {d["name"] for d in blocks["ldo"]["dropped"]}
    assert dropped_ldo == {"Iout", "Vin", "Dropout", "PSRR", "Iq"}, dropped_ldo
    assert {d["name"] for d in blocks["delta_sigma"]["dropped"]} == {
        "Order", "OSR", "ENOB", "Vin (diff)", "Vref", "Vdd (core)", "fclk"}
    oor = blocks["ldo"]["contradicted"]
    assert len(oor) == 1 and oor[0]["name"] == "Vout"
    assert oor[0]["graded_target"] == 1.0
    assert oor[0]["declared"]["min"] == 1.1 and oor[0]["declared"]["max"] == 1.3

    # and the reader is told what it read, not just what it found
    assert "1.0" in f["contradiction"] and "1.1-1.3" in f["contradiction"]
    assert "Vout" in f["contradiction"]


def test_the_disarm_fires_on_the_intents_own_disclosure_not_the_artefacts(tree):
    """The published cell: one block the intent states no requirement for.

    That block is out of scope and the OTHER is still measured — the disarm
    narrows the subject, it does not excuse the run.
    """
    p = tree(PUBLISHED)
    out = p / "rep.json"
    r = run(p, "--stage-verdict", "PASS", "--json", str(out))
    assert r.returncode == 0, f"expected rc 0, got {r.returncode}\n{r.stdout}"
    rec = json.loads(out.read_text(encoding="utf-8"))
    obs = [o for o in rec["observations"] if o["rule"] == RULE]
    assert len(obs) == 1 and obs[0]["verdict"] == "ACCEPT"
    assert [d["block"] for d in obs[0]["disarmed"]] == ["delta_sigma"]
    assert obs[0]["artefact"]["block_count"] == 1, (
        "the disarm must remove a block from scope, not the whole rule")
    assert "1 block(s) disarmed" in r.stdout, (
        "a rule that measured fewer subjects than the intent names must say "
        "so on the line a human reads")


def test_the_artefacts_own_stub_disclosure_does_not_disarm(tree):
    """`extraction_strategy: deterministic_stub` is the ARTEFACT confessing.

    A reviewer that accepted it would be letting the thing under review excuse
    itself. The intent supplied thirteen numbers and none of them went away.
    """
    p = tree(REJECT)
    for block in ("delta_sigma", "ldo"):
        art = json.loads(
            (p / "phase3" / "analog" / block / "spec.json").read_text("utf-8"))
        assert art["extraction_strategy"] == "deterministic_stub"
        assert art["low_confidence"] is True
    assert run(p, "--stage-verdict", "PASS").returncode == 1


# ─────────────────────────────────────────────────────────────────────────────
# the emitted regression IS the proof, so it is falsified both ways
# ─────────────────────────────────────────────────────────────────────────────
def test_the_emitted_regression_fails_here_and_passes_when_repaired(tree):
    """One emitted file, two trees, opposite answers.

    The emitted test is what the rejection offers as proof, so a test that
    only checked it exists would be checking a promise. This runs the SAME
    emitted bytes against the defective run (must fail) and against the run
    with the same intent whose artefact is right (must pass).
    """
    bad = tree(REJECT)
    assert run(bad, "--stage-verdict", "PASS").returncode == 1
    emitted = bad / "reports" / "analog" / "on_pass_review" / \
        f"test_{RULE.lower()}.py"
    assert emitted.is_file(), "the rejection named a test it did not write"

    body = emitted.read_text(encoding="utf-8")
    assert "subprocess" not in body and "import os" not in body, (
        "the emitted regression must re-derive nothing; it reads this run's "
        "own intent and artefact and starts no process")

    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r_bad = subprocess.run([sys.executable, str(emitted)],
                           capture_output=True, text=True, env=env)
    assert r_bad.returncode == 1, (
        f"the emitted regression passed on the run it was emitted from; it "
        f"proves nothing\n{r_bad.stdout}")
    assert "Vout" in r_bad.stdout and "1.0" in r_bad.stdout

    good = tree(ACCEPT)
    moved = good / "reports" / "analog" / "on_pass_review" / emitted.name
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_text(body, encoding="utf-8")
    r_good = subprocess.run([sys.executable, str(moved)],
                            capture_output=True, text=True, env=env)
    assert r_good.returncode == 0, (
        f"the emitted regression still fails on a run whose artefact carries "
        f"every declared requirement; it fires on its subject rather than on "
        f"the defect\n{r_good.stdout}")


# ─────────────────────────────────────────────────────────────────────────────
# rc 2 is "the question could not be put", and never a pass
# ─────────────────────────────────────────────────────────────────────────────
def test_an_unestablished_stage_verdict_is_not_checked(tree):
    r = run(tree(REJECT))
    assert r.returncode == 2, r.stdout
    assert "unestablished" in r.stdout


def test_a_failed_stage_is_not_this_rungs_business(tree):
    r = run(tree(REJECT), "--stage-verdict", "FAIL")
    assert r.returncode == 2, r.stdout
    assert "did not pass" in r.stdout


def test_an_empty_scope_is_not_checked_never_accepted(tree):
    """Every block disarmed leaves a zero denominator.

    Reporting that as "no contradiction found" is how a review of nothing
    reports a pass, and it is the failure `gate_zero_denominator_refuses_check`
    already names elsewhere in this repo.
    """
    p = tree(ACCEPT)
    l5p = p / "phase1" / "generated_docs" / "L5_ADI_SPEC.json"
    doc = json.loads(l5p.read_text(encoding="utf-8"))
    for b in doc["analog_blocks"]:
        b["low_confidence"] = True
    l5p.write_text(json.dumps(doc), encoding="utf-8")
    r = run(p, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "0 measured" in r.stdout


def test_a_denied_intent_path_makes_the_review_refuse(tree):
    """4.05 — a reviewer allowed to read the oracle is grading itself."""
    flow = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in flow["stages"]:
        if st["id"] == STAGE:
            st["on_pass_review"]["intent"] = [
                "phase1/oracle/L5_ADI_SPEC.json"]
    d = Path(tempfile.mkdtemp(prefix="onpass_analog_flow_"))
    try:
        f = d / "flow.yaml"
        f.write_text(yaml.safe_dump(flow), encoding="utf-8")
        r = run(tree(ACCEPT), "--stage-verdict", "PASS", flow=f)
        assert r.returncode == 2, r.stdout
        assert "4.05" in r.stdout and "oracle" in r.stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# the declaration lives in the flow
# ─────────────────────────────────────────────────────────────────────────────
def test_the_flow_declares_this_stages_review():
    flow = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    st = next(s for s in flow["stages"] if s["id"] == STAGE)
    blk = st["on_pass_review"]
    assert blk["skill"] == "analog-output-verify"
    assert blk["fires_on"] == "stage_pass"
    assert blk["rejection_requires"] == ["intent", "artefact",
                                         "contradiction", "test"]
    assert blk["intent"] == ["phase1/generated_docs/L5_ADI_SPEC.json"]
    assert "phase3/analog/" in blk["artefact"]
    assert STAGE in blk["gate"]["program_exit_zero"]
    assert "stage_on_pass_review" in blk["gate"]["program_exit_zero"]


def test_the_reviewer_skill_is_not_declared_twice():
    """NO FOURTH MAPPING.

    A skill named by a stage's `on_pass_review:` inherits that stage by
    derivation; listing it in the stage axis as well would be the second
    declaration `flow_stage_membership_single_declaration_check` exists to
    prevent.
    """
    cls = json.loads(
        (PLUGIN / "skills" / "_classification.json").read_text("utf-8"))
    assert "analog-output-verify" not in cls["stage_axis"]["stages"]


def test_a_stage_with_no_rule_is_not_checked(tree):
    """The registry, not the declaration, is what makes a stage reviewable.

    A stage this program implements no rule for must say so rather than report
    a clean run. `stage2` was this probe's subject until v1.13.2 gave it R2;
    `stage3` is ruleless today and the assertion is on the rc, not on which
    stage happens to be empty.
    """
    r = run(tree(ACCEPT), "--stage-verdict", "PASS", stage="stage3")
    assert r.returncode == 2, r.stdout


def test_every_rule_has_an_emitter_and_a_printer():
    """The invariant behind the deliberate KeyError.

    `emit_test` looks the emitter up by rule id and raises KeyError rather than
    writing somebody else's test; `review()` then leaves `test` absent and the
    unproven-rejection branch refuses the rejection. That is the right
    behaviour at runtime and the wrong thing to discover at runtime, so the
    active and declared-not-enabled registries are pinned to agree with the
    emitter and printer registries here — including for rules this stage did
    not author.
    """
    mod = _program()
    ids = {rid for rules in mod._RULES.values() for rid, _ in rules}
    ids |= {rid for rules in getattr(mod, "_DECLARED_NOT_ENABLED", {}).values()
            for rid, _ in rules}
    assert RULE in ids
    assert set(mod._EMITTERS) == ids, (
        f"emitters {sorted(set(mod._EMITTERS) ^ ids)} do not match the rules")
    assert set(mod._PRINTERS) == ids, (
        f"printers {sorted(set(mod._PRINTERS) ^ ids)} do not match the rules")
    assert mod._EMITTERS[RULE] is mod._body_analog
    assert mod._PRINTERS[RULE] is mod._print_analog


def test_the_accept_observation_branch_is_inert_for_the_other_stages(tree):
    """This stage added four lines to a loop `main()` shares.

    They print a rule's own denominator on an ACCEPT that carries one, because
    the summary line counts RULES and would otherwise report "0 disarmed" over
    a non-empty per-block disarm set. R1 and R2 carry `observation` only on a
    DISARMED verdict, so the branch cannot fire for them.

    ASSERTED BY RUNNING THEM, not by reading the source: the first version of
    this test sliced the source for `"observation"` after `"verdict":
    "ACCEPT"` and failed on R2, whose DISARMED branch starts from an ACCEPT
    dict and then overwrites the verdict. The checker was wrong, not the code.
    """
    other = Path(__file__).resolve().parent / "fixtures"
    arms = [("stage1", other / "stage1_on_pass_review" / "accept_spm"),
            ("stage2", other / "stage2_on_pass_review" / "accept_spm")]
    ran = 0
    for stage, src in arms:
        if not src.is_dir():
            continue
        r = run(tree(src), "--stage-verdict", "PASS", stage=stage)
        assert r.returncode == 0, f"{stage} accept arm: rc {r.returncode}\n{r.stdout}"
        assert "ACCEPT — " not in r.stdout.split("\n")[0] or "[INFO]" not in \
            r.stdout.split("\n")[0], r.stdout
        for line in r.stdout.splitlines():
            assert not (line.startswith(f"{PROG.stem}: [INFO]")
                        and " ACCEPT — " in line), (
                f"the shared ACCEPT-observation branch fired for {stage}; it "
                f"is no longer inert for a rule this stage does not own:\n"
                f"{line}")
        ran += 1
    assert ran == 2, (
        f"only {ran} of the other two stages' accept fixtures resolved; this "
        f"control did not run on an empty set of subjects")


def test_the_emitted_regression_is_this_rules_own_body(tree):
    """A port that stays green while emitting the wrong body is invisible.

    The registries make it possible to wire a rule to another rule's emitter
    and still pass every verdict assertion, because the rc and the record come
    from the rule and only the FILE comes from the emitter. So the emitted
    bytes are read and checked to be this rule's.
    """
    p = tree(REJECT)
    assert run(p, "--stage-verdict", "PASS").returncode == 1
    emitted = p / "reports" / "analog" / "on_pass_review" / \
        f"test_{RULE.lower()}.py"
    body = emitted.read_text(encoding="utf-8")

    assert "INTENT_REL = 'phase1/generated_docs/L5_ADI_SPEC.json'" in body
    assert "ANALOG_RELS = " in body and "phase3/analog/" in body
    assert "BLOCKS = " in body and "delta_sigma" in body and "ldo" in body
    assert ("def test_the_spec_this_run_grades_against_is_the_spec_the_intent"
            "_declares(") in body

    # and none of the other stages' bodies
    for foreign in ("RTL_RELS", "_MODULE_RE", "top_module", "NETLIST_REL",
                    "declared_pins", "the synthesised top"):
        assert foreign not in body, (
            f"the emitted regression carries {foreign!r} — this is another "
            f"stage's test body, not this rule's")
