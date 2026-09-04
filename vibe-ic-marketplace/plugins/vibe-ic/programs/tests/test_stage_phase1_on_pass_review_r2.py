#!/usr/bin/env python3
"""The stage_phase1 ON-PASS review, rule R2 — and the control that stops it
manufacturing confidence in either direction.

This stage carries TWO rules and this file is R2's.
`test_stage_phase1_on_pass_review.py` owns R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE
and the block-level assertions (that the stage declares a review at all, that
it names a verification-tier skill, that it is not a second membership roster);
they are not repeated here. What IS repeated is the pair that must hold of
EVERY rule sharing this program: both directions on real artefacts, and the
stage-1 partition unmoved.

WHY THIS FILE EXISTS
====================
Step D1's own comment in `flow/phase1_phase2_phase3.yaml` ruled where these
reviewers belong and could not act on it: "`phase1-output-verify` and
`phase1-completeness-deep-review` both ship ... and neither is named by any
stage -- so stage_phase1 has no declared on-pass review ... They belong in an
`on_pass_review:` block on stage_phase1, the field v1.12.87 added for them on
stage1." This file is the control for that block.

WHAT R2 CLAIMS, AND WHY NOTHING ELSE IN THE FLOW MAKES THE CLAIM
================================================================
Step D1 wires thirty gate clauses over `phase1/generated_docs/`. Every one asks
an INTERNAL question (is the layer present, is its own field actionable, do the
layers agree with each other) or a COVERAGE question (did every input literal
land somewhere). None asks whether a specific thing a Phase-1 document SAYS is
true of the design input it was extracted from.

R2 asks it of `L9.top_module` — the field `design_one_shot_runner.
_design_identity_fields` copies verbatim into every stage-1 report as
`design_identity.top`, and `_design_module_set.reconcile_declared_top` measures
the staged RTL against. L9 also declares WHERE it got that name
(`top_module_extraction_strategy`), so the document makes a provenance claim
that can be put to the input. R2 refuses only the case where BOTH are refuted:
the name is in none of the run's input files AND shares no word with the
`L1.ic_name` the strategy names as its source.

MEASURED, AND MEASURED BOTH WAYS
================================
On the published corpus at benchmark-data
a467106a131f46a8375cbb9fefeefcb730635e9b (87 cells carrying an L1): R2 alone
answers 5 REJECT, 41 ACCEPT (37 because the name IS in the design input, 4
because it derives from `L1.ic_name`), 17 DISARMED on the sentinel, 24 NOT
CHECKED for want of a readable input. All three disarms are load-bearing and all three are asserted
below: dropping the input disarm takes the rejection set 5 -> 12, dropping the
`L1.ic_name` accept takes it 5 -> 9, dropping the sentinel disarm takes it
5 -> 12. A rule firing on 12 of 63 answerable cells would be the
detector-that-fires-on-everything failure rather than a finding.

The five are not near-misses, and the fixture is one of them. `ddr5`, `gddr6`
and `hbm3` publish the SAME top module while their own L1 names three different
designs; `io_link` publishes a UART part number; `sas` publishes another
controller's top.

BOTH DIRECTIONS, ON REAL PUBLISHED ARTEFACTS
============================================
  ACCEPT  `fixtures/stage_phase1_on_pass_review/accept_lpddr5` — verbatim from
          the published cell `evaluation/phase1_parity/lpddr5`, whose L9
          declares `LPDDR5_SDRAM_component` and whose L1 names `LPDDR5 SDRAM
          (JEDEC JESD209-5)`. The name is not in the input either; it is
          accepted because it derives from the source its own strategy names,
          which is the narrower of the two disarms.
  REJECT  `fixtures/stage_phase1_on_pass_review/reject_ddr5` — verbatim from
          the published cell `evaluation/phase1_parity/ddr5`, whose L9 declares
          `top_module: "HBM3_stack_on_interposer"` by
          `top_module_extraction_strategy: "l1_ic_name_fallback"` while its own
          L1 names `DDR5 SDRAM (JEDEC JESD79-5)` and the string appears nowhere
          in `ddr5_spec.txt`.

`fixtures/.../PROVENANCE.json` carries each source file's sha256; nothing in
the fixture is authored.

AND R2 IS WHAT KEEPS R1 HONEST
==============================
R1 (stage 1) DISARMS on `no_top_module_in_input: true`. All five R2 rejections
set it. So on exactly the documents whose top module came from nowhere, the
flow's only other on-pass review switches itself off — which is asserted below,
because it is the reason this rule is worth a rung of its own rather than a
clause of R1's.
"""
from __future__ import annotations

import collections
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
ACCEPT = FIX / "accept_lpddr5"        # R2 ACCEPT via L1.ic_name; R1 has no constant
BOTH_OK = FIX / "accept_interlaken"   # the tree BOTH rules answer, and both accept
REJECT = FIX / "reject_ddr5"
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


def r2_verdict(tmp_path, run_dir, tag="v"):
    """R2's own verdict on this tree.

    THE RUN'S rc IS THE COMPOSED ANSWER OF TWO RULES and is pinned by
    `test_stage_phase1_on_pass_review.py`. A test about R2's rule must read
    R2's row, or it is really testing whether R1 happened to be answerable on
    the same tree — which for several of these cells it is not, and asserting
    rc there would pin a coincidence."""
    j = tmp_path / f"{tag}.json"
    run(run_dir, "--stage-verdict", "PASS", "--json", str(j))
    rec = json.loads(j.read_text())
    rows = [r for r in rec["rules"]
            if r["rule"] == "R2_TOP_MODULE_PROVENANCE_REFUTED"]
    assert len(rows) == 1, rec["rules"]
    return rows[0]["verdict"]


def l9(run_dir):
    return run_dir / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"


def edit_l9(run_dir, **fields):
    p = l9(run_dir)
    d = json.loads(p.read_text(encoding="utf-8"))
    d.update(fields)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# the declaration is in the flow, and nowhere else
# ─────────────────────────────────────────────────────────────────────────────
def test_r2_needs_no_declaration_of_its_own():
    """One program, one flow block per stage — so R2 adds no second block and
    changes none of the first's fields. It reads `intent:`, `artefact:` and
    `intent_deny:` exactly as R1 left them, which is the whole reason a second
    rule is cheap. MEASURED: R2's partition over the published corpus is
    identical under this declaration to what it was under the four-path intent
    list it was developed against — 5 REJECT, 76 ACCEPT, 24 NOT CHECKED, the
    same five cells."""
    d = declaration()
    assert d is not None, f"{STAGE} declares no on_pass_review"
    assert d["artefact"] == ["phase1/generated_docs/"]
    assert d["rejection_requires"] == ["intent", "artefact", "contradiction",
                                       "test"]
    for path in d["intent"]:
        assert "generated_docs" not in path, (
            f"intent path {path!r} is the stage's own artefact, not its input")


# ─────────────────────────────────────────────────────────────────────────────
# BOTH DIRECTIONS, ON REAL ARTEFACTS
# ─────────────────────────────────────────────────────────────────────────────
def test_a_real_known_good_artefact_is_accepted_by_r2(tmp_path):
    """The narrower accept path, on a real cell: `LPDDR5_SDRAM_component` is in
    none of this run's input files and is accepted because it derives from the
    `L1.ic_name` its own strategy names.

    The assertion is on R2's OWN verdict rather than on the run's exit code,
    and that distinction is the point of a stage carrying two rules: this cell
    cites no hexadecimal constant, so R1 cannot be answered on it and the RUN
    is honestly NOT CHECKED. `test_a_tree_both_rules_can_answer_exits_zero`
    below is where rc 0 is pinned."""
    r = run(tree(tmp_path, ACCEPT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == []
    r2 = [o for o in rec["observations"] if o["rule"].startswith("R2_")]
    assert [o["grounded_in"] for o in r2] == ["l1_ic_name"]
    assert r.returncode == 2, r.stdout + r.stderr
    assert "R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE" in r.stdout


def test_a_tree_every_rule_can_answer_exits_zero(tmp_path):
    """The full-ACCEPT direction, on a real published cell ALL THREE rules read.
    A reviewer whose only green is "nobody could look" is not a reviewer, so
    this is the case that has to exist: every rule the stage declares answered,
    and every one of them accepting.

    The set below is asserted by EQUALITY and not by containment, which is what
    makes this test the merge's own guard: a rule that silently stopped being
    registered leaves the stage green here, and only an exact set notices."""
    r = run(tree(tmp_path, BOTH_OK), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 0, r.stdout + r.stderr
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == [] and rec["not_checked"] == []
    assert {o["rule"] for o in rec["observations"]} == {
        "R1_CITED_CONSTANT_NOT_IN_ITS_SOURCE",
        "R2_TOP_MODULE_PROVENANCE_REFUTED",
        "R1_CITED_INPUT_ABSENT"}
    assert {o["verdict"] for o in rec["observations"]} == {"ACCEPT"}


def test_a_real_artefact_whose_top_module_came_from_nowhere_is_rejected(tmp_path):
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REJECT" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert len(rec["rejections"]) == 1
    f = rec["rejections"][0]
    assert f["rule"] == "R2_TOP_MODULE_PROVENANCE_REFUTED"
    # the INTENT it read — the design input, named file by file
    assert f["intent"]["files"] == ["input/docs/ddr5_spec.txt",
                                    "phase1/input_doc/ddr5_spec.txt"]
    # the ARTEFACT fact it read
    art = f["artefact"]
    assert art["file"] == "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    assert art["top_module"] == "HBM3_stack_on_interposer"
    assert art["strategy"] == "l1_ic_name_fallback"
    assert art["l1_ic_name"] == "DDR5 SDRAM (JEDEC JESD79-5)"
    # the CONTRADICTION, naming both refuted sources
    assert "HBM3_stack_on_interposer" in f["contradiction"]
    assert "DDR5 SDRAM (JEDEC JESD79-5)" in f["contradiction"]
    assert "ddr5_spec.txt" in f["contradiction"]
    # the TEST — a path that EXISTS, written by this run of the review
    assert f["test"], "the rejection carries no test"
    assert (tmp_path / REJECT.name / f["test"]).is_file(), f["test"]


def test_the_rejected_document_is_the_one_that_disarms_the_stage1_review(tmp_path):
    """Why this rule is worth a rung of its own. R1 disarms on
    `no_top_module_in_input: true`; this document sets it. The document that
    invented the name also switches off the only other review that measures
    it, so a clause inside R1 could never have reached this case."""
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1
    f = json.loads((tmp_path / "r.json").read_text())["rejections"][0]
    assert f["artefact"]["no_top_module_in_input"] is True
    assert f["disarms_stage1_r1"] is True
    assert "DISARMS" in r.stdout


def test_the_accept_control_does_not_move_when_the_reject_case_is_measured(tmp_path):
    """Both directions in ONE invocation shape. A rule that started refusing
    everything would take the accept case with it; a rule that stopped biting
    would take the reject case with it. Neither may move alone."""
    good = run(tree(tmp_path, BOTH_OK), "--stage-verdict", "PASS")
    bad = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS")
    assert (good.returncode, bad.returncode) == (0, 1), (
        f"good={good.returncode} bad={bad.returncode}\n"
        f"{good.stdout}\n---\n{bad.stdout}")


# ─────────────────────────────────────────────────────────────────────────────
# the rejection is caused by the top module and by nothing else about the cell
# ─────────────────────────────────────────────────────────────────────────────
def test_a_top_module_the_input_does_name_flips_the_same_cell_to_accept(tmp_path):
    """The negative control for the finding. Same published cell, same input,
    same L1 — only `L9.top_module` moves, to a string the run's own input
    contains. It must flip to ACCEPT, which is what proves the rejection is
    about the name's provenance and not about that cell."""
    repaired = tree(tmp_path / "repaired", REJECT)
    spec = (repaired / "input" / "docs" / "ddr5_spec.txt").read_text(
        encoding="utf-8", errors="replace")
    assert "DDR5 SDRAM" in spec, "the control's premise is not in the input"
    edit_l9(repaired, top_module="DDR5_SDRAM")
    assert r2_verdict(tmp_path, tree(tmp_path, REJECT), "b") == "REJECT"
    assert r2_verdict(tmp_path, repaired, "a") == "ACCEPT"


def test_a_top_module_derived_from_the_l1_ic_name_flips_the_same_cell_to_accept(tmp_path):
    """The other accept path, on the same cell. `DDR5_SDRAM_component` is in
    none of this run's input files either — it is accepted because it shares a
    word with the `L1.ic_name` the document's own strategy names."""
    repaired = tree(tmp_path / "repaired", REJECT)
    spec = (repaired / "input" / "docs" / "ddr5_spec.txt").read_text(
        encoding="utf-8", errors="replace")
    assert "DDR5_SDRAM_component" not in spec
    edit_l9(repaired, top_module="DDR5_SDRAM_component")
    assert r2_verdict(tmp_path, repaired) == "ACCEPT"


def test_the_sentinel_placeholder_disarms_instead_of_rejecting(tmp_path):
    """The corpus's own disclosure: when phase 1 could not read a top out of
    the design input it says so and publishes a placeholder. A review that
    called that a contradiction would reject 22 of the corpus's cells for a
    claim their documents never made."""
    d = tree(tmp_path / "sentinel", REJECT)
    edit_l9(d, top_module="chip_top",
            top_module_extraction_strategy="canonical_chip_top_sentinel")
    assert r2_verdict(tmp_path, d) == "DISARMED"
    assert "placeholder" in run(d, "--stage-verdict", "PASS").stdout


# ─────────────────────────────────────────────────────────────────────────────
# each disarm is load-bearing, and is asserted as such
# ─────────────────────────────────────────────────────────────────────────────
def test_the_input_disarm_is_what_keeps_this_a_detector(tmp_path):
    """MEASURED: without it the corpus rejection set goes 5 -> 12. The cell
    below is one of the seven it would take — a name the run's own input
    contains verbatim, which is the ordinary case, not a defect."""
    d = tree(tmp_path / "grounded", REJECT)
    spec = (d / "input" / "docs" / "ddr5_spec.txt").read_text(
        encoding="utf-8", errors="replace")
    assert "sub-channel" in spec
    edit_l9(d, top_module="sub_channel", top_module_extraction_strategy="x")
    assert r2_verdict(tmp_path, d) == "ACCEPT"


def test_the_ic_name_accept_is_load_bearing_and_narrow(tmp_path):
    """It accepts on a SHARED WORD with the source the strategy names, and on
    nothing weaker. A name sharing no word with either source is still
    rejected — otherwise the accept would swallow the rule."""
    weak = tree(tmp_path / "weak", REJECT)
    edit_l9(weak, top_module="PC16550D")
    assert run(weak, "--stage-verdict", "PASS").returncode == 1


# ─────────────────────────────────────────────────────────────────────────────
# the emitted test discriminates, or the rejection proved nothing
# ─────────────────────────────────────────────────────────────────────────────
def test_the_emitted_test_fails_today_and_passes_when_the_run_is_repaired(tmp_path):
    """The doctrine, executable. Run the EMITTED file against the defective run
    (must fail), then correct the one field it names and run THE SAME FILE
    again (must pass). A test that could not fail proves nothing, and one that
    could not pass would block every repair."""
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
    assert "HBM3_stack_on_interposer" in before.stdout

    edit_l9(run_dir, top_module="DDR5_SDRAM_component")
    after = subprocess.run([sys.executable, str(emitted)],
                           capture_output=True, text=True)
    assert after.returncode == 0, (
        "the emitted test still fails after the repair it asks for:\n"
        + after.stdout + after.stderr)


def test_the_emitted_test_refuses_an_absent_input_rather_than_passing(tmp_path):
    """The emitted test carries the same rule its emitter does: the question
    cannot be put over an absent input. Deleting the design input must not be a
    way to make the run's own regression go green."""
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1
    emitted = run_dir / json.loads(
        (tmp_path / "r.json").read_text())["rejections"][0]["test"]
    shutil.rmtree(run_dir / "input")
    shutil.rmtree(run_dir / "phase1" / "input_doc")
    out = subprocess.run([sys.executable, str(emitted)],
                         capture_output=True, text=True)
    assert out.returncode == 1
    assert "cannot be put over an absent input" in out.stdout


def test_the_emitted_test_refuses_a_DELETED_claim_rather_than_passing(tmp_path):
    """Deleting the field the rejection names must not be a way to go green.

    THIS IS THE ONE THE OTHER TWO EMITTED-TEST CONTROLS COULD NOT SEE. R2's
    emitted body opened `if not top or top == SENTINEL_TOP or strategy ==
    SENTINEL_STRATEGY: return`, fusing "the claim is ABSENT" into the sentinel
    disarm. So `python3 test_r2_top_module_provenance_refuted.py` printed
    "PASS: the declared top module is grounded in the input or in L1.ic_name"
    on the very tree that emitted it, as soon as `top_module` was removed --
    a regression that cannot fail for the reason it exists, which is worse
    than no regression because it counts as coverage.

    THE PROPERTY IS AGREEMENT WITH THE REVIEW, not a preference about asserts:
    on this same tree the review reports rc=2 NOT_CHECKED -- "a document that
    claims nothing cannot be contradicted, and an absent claim is not a
    grounded one". The emitted regression must not certify green what the
    review declines to certify. Both halves are asserted below, so the day the
    RULE changes its mind about an absent claim, this test says so.

    ITS TWO SIBLING top_module READERS ALREADY DO THIS: R1's template asserts
    `declared, "%s declares no top_module"` and R4's asserts the same. R2 was
    the odd one of the three.
    """
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1
    emitted = run_dir / json.loads(
        (tmp_path / "r.json").read_text())["rejections"][0]["test"]

    p = l9(run_dir)
    d = json.loads(p.read_text(encoding="utf-8"))
    d.pop("top_module", None)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")

    out = subprocess.run([sys.executable, str(emitted)],
                         capture_output=True, text=True)
    assert out.returncode == 1, (
        "the emitted test PASSES once the claim it was emitted about is "
        "DELETED; deleting the field is not a repair:\n" + out.stdout + out.stderr)
    assert "DELETING THE CLAIM IS NOT A REPAIR" in out.stdout, out.stdout

    # and the REVIEW agrees: it declines to certify this tree at all.
    again = run(run_dir, "--stage-verdict", "PASS")
    assert again.returncode == 2, again.stdout
    assert "declares no `top_module`" in again.stdout, again.stdout


def test_the_emitted_test_still_accepts_the_sentinel_it_is_meant_to_accept(tmp_path):
    """The false-positive half. The fix above must not broaden the emitted test
    into refusing the disclosure the flow offers as the SECOND repair.

    The emitted docstring names it: "L9 stops claiming a top module and
    publishes the canonical placeholder with the sentinel strategy". That was
    already the contract; what the code accepted was a THIRD thing the contract
    never offered. Both spellings of the disarm are asserted because the rule
    disarms on EITHER -- the placeholder name or the strategy -- and a fix that
    kept only one would move cells the rule does not move."""
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1
    emitted = run_dir / json.loads(
        (tmp_path / "r.json").read_text())["rejections"][0]["test"]

    rel = emitted.relative_to(run_dir)
    for tag, field in (("name", {"top_module": "chip_top"}),
                       ("strategy", {"top_module_extraction_strategy":
                                     "canonical_chip_top_sentinel"})):
        d = tree(tmp_path / ("sentinel_" + tag), REJECT)
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(emitted, d / rel)
        edit_l9(d, **field)
        out = subprocess.run([sys.executable, str(d / rel)],
                             capture_output=True, text=True)
        assert out.returncode == 0, (
            f"the emitted test refuses the sentinel disclosure {field!r}, "
            f"which is the repair its own docstring offers:\n"
            + out.stdout + out.stderr)


def test_the_emitted_test_is_the_r2_one_and_not_the_stage1_template(tmp_path):
    """Each rule owns its regression. Emitting R1's template here would assert
    something this rejection never proved — that the staged RTL declares a
    module — about a stage that has staged no RTL at all."""
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    emitted = (run_dir / json.loads(
        (tmp_path / "r.json").read_text())["rejections"][0]["test"]
        ).read_text(encoding="utf-8")
    assert "top_module_extraction_strategy" in emitted
    assert "staged no readable module" not in emitted


# ─────────────────────────────────────────────────────────────────────────────
# an absent input is NOT CHECKED, never an acceptance
# ─────────────────────────────────────────────────────────────────────────────
def test_a_run_that_publishes_no_design_input_is_not_checked(tmp_path):
    """24 of the corpus's 105 cells publish no input. Whether the name came
    from the input is exactly the question, and it cannot be put without the
    input. Answering 0 there would be a review of nothing reporting a pass."""
    d = tree(tmp_path / "no_input", REJECT)
    shutil.rmtree(d / "input")
    shutil.rmtree(d / "phase1" / "input_doc")
    r = run(d, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert "readable design input" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())

    # THIS RULE could not be answered, and says so by name. That is the claim
    # the test makes, and it is asserted on the RULE and not on the run's exit
    # code — because the stage carries a sibling that CAN be answered here.
    nc = {f["rule"]: f["why"] for f in rec["not_checked"]}
    assert "R2_TOP_MODULE_PROVENANCE_REFUTED" in nc
    assert "readable design input" in nc["R2_TOP_MODULE_PROVENANCE_REFUTED"]
    assert not any(f["rule"] == "R2_TOP_MODULE_PROVENANCE_REFUTED"
                   for f in rec["rejections"] + rec["observations"]), \
        "an absent input must not be read as a grounded name"

    # The run exits 1, not 2, and that is this program's declared precedence
    # rather than a softened assertion: stripping the input leaves
    # R1_CITED_INPUT_ABSENT with a PROVEN contradiction — the L-docs cite a
    # source the run does not have — and a proven rejection outranks NOT
    # CHECKED. The rules that could not look are still named in the output
    # above and carried in `not_checked`, which the assertions above read.
    assert r.returncode == 1, r.stdout
    assert [f["rule"] for f in rec["rejections"]] == ["R1_CITED_INPUT_ABSENT"]


def test_an_l9_that_declares_no_top_module_is_not_checked(tmp_path):
    d = tree(tmp_path / "no_top", REJECT)
    edit_l9(d, top_module="")
    r = run(d, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "declares no `top_module`" in r.stdout


def test_an_absent_l1_ic_name_is_not_checked_rather_than_refuted(tmp_path):
    """"Unverified" and "refuted" are different answers. With no `ic_name` the
    source the strategy names cannot be read, so the provenance is unproven —
    and an unproven rejection is the thing this rung exists to refuse."""
    d = tree(tmp_path / "no_icname", REJECT)
    l1 = d / "phase1" / "generated_docs" / "L1_DATASHEET.json"
    j = json.loads(l1.read_text(encoding="utf-8"))
    j.pop("ic_name", None)
    l1.write_text(json.dumps(j, indent=2), encoding="utf-8")
    r = run(d, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "not the same as" in r.stdout


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
        {"id": "D1", "stage": STAGE, "status": "PASS"},
        {"id": 9, "stage": "stage2", "status": "FAIL"}]}))
    red = tmp_path / "red.json"
    red.write_text(json.dumps({"steps": [
        {"id": "D1", "stage": STAGE, "status": "FAIL"}]}))
    assert run(tree(tmp_path, REJECT), "--compliance", str(green)).returncode == 1
    assert run(tree(tmp_path, BOTH_OK), "--compliance", str(green)).returncode == 0
    assert run(tree(tmp_path / "red", REJECT),
               "--compliance", str(red)).returncode == 2


# ─────────────────────────────────────────────────────────────────────────────
# §4.05 — the reviewer reads the design INPUT
# ─────────────────────────────────────────────────────────────────────────────
def test_a_denied_intent_path_is_refused_rather_than_read(tmp_path):
    flow = flow_with(tmp_path, intent=["input/docs/", "benchmark/oracle/vectors/"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS", flow=flow)
    assert r.returncode == 2, r.stdout
    assert "4.05" in r.stdout and "oracle" in r.stdout


def test_the_denial_is_a_list_not_a_hardcode_and_an_allowed_path_still_reads(tmp_path):
    """The control for the guard: same shape, no denied segment — the review
    reaches its rule and rejects as before. A guard that refused everything
    would pass the test above."""
    flow = flow_with(tmp_path, intent=["input/docs/", "phase1/input_doc/"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS", flow=flow)
    assert r.returncode == 1, r.stdout


def test_a_denied_directory_under_an_allowed_intent_path_is_not_read(tmp_path):
    """The path-level guard is not the whole of §4.05 for THIS rule. R1's
    intent paths name single files, so vetting the declared path is the whole
    check. These name DIRECTORIES, and `input/docs/` passes the deny check
    while `input/docs/oracle/answers.txt` under it does not. The walk must skip
    it — otherwise the review reads the oracle through a clean declaration."""
    d = tree(tmp_path / "planted", REJECT)
    oracle = d / "input" / "docs" / "oracle"
    oracle.mkdir(parents=True)
    (oracle / "answers.txt").write_text(
        "the top module is HBM3_stack_on_interposer", encoding="utf-8")
    r = run(d, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, (
        "the planted oracle names the top module, so reading it would have "
        "turned this rejection into an acceptance:\n" + r.stdout)
    f = json.loads((tmp_path / "r.json").read_text())["rejections"][0]
    assert not any("oracle" in p for p in f["intent"]["files"]), f["intent"]["files"]


def test_the_same_file_outside_a_denied_directory_is_read(tmp_path):
    """The control for the skip above: a detector that skipped every file would
    pass that test by reading nothing at all. Identical content, ordinary
    directory — it must be read, and the cell must flip to ACCEPT."""
    d = tree(tmp_path / "plain", REJECT)
    (d / "input" / "docs" / "addendum.txt").write_text(
        "the top module is HBM3_stack_on_interposer", encoding="utf-8")
    assert r2_verdict(tmp_path, d) == "ACCEPT"


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
    assert "waiver_reference" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert rec["rejections"] == [], "an unproven finding was emitted anyway"
    assert rec["unproven_rejections"][0]["missing_evidence"] == ["waiver_reference"]


# ─────────────────────────────────────────────────────────────────────────────
# the stage-1 rule is the control that must not move
# ─────────────────────────────────────────────────────────────────────────────
def test_adding_stage_phase1_did_not_move_the_stage1_partition(tmp_path):
    """R1's own fixtures, run through the changed program. A second rule that
    perturbed the first would be a regression this file is the only place to
    notice, because the two share a program, an evidence contract and an
    emitter."""
    s1 = Path(__file__).resolve().parent / "fixtures" / "stage1_on_pass_review"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

    def r1(which):
        d = tmp_path / ("s1_" + which)
        shutil.copytree(s1 / which, d)
        return subprocess.run(
            [sys.executable, str(PROG), str(d), "--stage", "stage1",
             "--flow-def", str(FLOW), "--stage-verdict", "PASS"],
            capture_output=True, text=True, env=env)

    good, bad = r1("accept_spm"), r1("reject_caravel")
    assert (good.returncode, bad.returncode) == (0, 1), (
        f"stage1 moved: good={good.returncode} bad={bad.returncode}\n"
        f"{good.stdout}\n---\n{bad.stdout}")
    assert "R1_INTENT_TOP_NOT_BUILT" in bad.stdout


def test_each_stage_gets_its_own_rules_and_not_the_other_stages(tmp_path):
    """R1 on a stage_phase1 tree must not silently answer. The rules are keyed
    by stage; a program that ran every rule everywhere would report R1's
    'staged no readable module' about a stage that stages no RTL."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    d = tree(tmp_path, REJECT)
    out = subprocess.run(
        [sys.executable, str(PROG), str(d), "--stage", "stage1",
         "--flow-def", str(FLOW), "--stage-verdict", "PASS"],
        capture_output=True, text=True, env=env)
    assert out.returncode == 2, out.stdout
    assert "R2_TOP_MODULE_PROVENANCE_REFUTED" not in out.stdout


# ─────────────────────────────────────────────────────────────────────────────
# the review does not re-derive the artefact
# ─────────────────────────────────────────────────────────────────────────────
def test_the_emitted_regression_starts_no_process_and_re_derives_nothing(tmp_path):
    """The emitted test travels into someone else's run tree, so the
    no-re-derivation property has to hold of the EMITTED file too, not only of
    the emitter that `test_stage1_on_pass_review` already pins."""
    import ast
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1
    emitted = run_dir / json.loads(
        (tmp_path / "r.json").read_text())["rejections"][0]["test"]
    src = emitted.read_text(encoding="utf-8")
    banned = {"subprocess", "os", "shutil", "socket", "urllib", "requests"}
    imported = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imported.add((n.module or "").split(".")[0])
    assert not (imported & banned), (
        f"the emitted regression imports {imported & banned}; it must read the "
        f"run and do no more")
    assert imported <= {"json", "re", "sys", "pathlib"}, imported


# ─────────────────────────────────────────────────────────────────────────────
# a stage with no declaration is NOT CHECKED, never a pass
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# the live corpus: the whole partition, pinned
# ─────────────────────────────────────────────────────────────────────────────
#: MEASURED on benchmark-data, 2026-08-30, over every published cell carrying an
#: L1 (87 cells). These are R2's OWN verdicts, not the run's exit code: the
#: composed rc partition is pinned by `test_stage_phase1_on_pass_review.py`,
#: and pinning it twice would make one of the two a copy nobody re-derives.
#:
#: R2 alone: 5 REJECT, 41 ACCEPT, 17 DISARMED, 24 NOT CHECKED. All five
#: rejections are verified — `ddr5`, `gddr6` and `hbm3` publish the SAME
#: `HBM3_stack_on_interposer` while their own L1 names three different designs,
#: `io_link` publishes the UART part number `PC16550D`, and `sas` publishes
#: `AHCI_HBA`.
_CORPUS_REJECTS = {
    "protocol_parity/ddr5",
    "protocol_parity/gddr6",
    "protocol_parity/hbm3",
    "protocol_parity/io_link",
    "protocol_parity/sas",
}
#: The two accept paths must BOTH stay populated. A rule that stopped reading
#: the input, or stopped consulting `L1.ic_name`, would keep the rejection set
#: intact while quietly becoming a different rule.
_MIN_ACCEPTS = {"design_input": 30, "l1_ic_name": 3}


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_r2s_own_partition_over_the_published_corpus_does_not_move():
    """Pins every side of R2 on the live corpus. The reject set is named cell by
    cell so a rule that widened shows up as an extra NAME rather than as a count
    nobody reads; the accept side is pinned BY PATH so a rule that quietly
    stopped using one of its two sources cannot pass by keeping the total."""
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    cells = sorted({p.parents[2] for p in
                    root.rglob("phase1/generated_docs/L1_DATASHEET.json")
                    if "claude_extracted" not in str(p)})
    if not cells:
        pytest.skip("the corpus carries no cell with an L1")
    scratch = Path(tempfile.mkdtemp(prefix="on_pass_r2_corpus_"))
    rejects, verdicts, grounded = set(), collections.Counter(), collections.Counter()
    for n, cell in enumerate(cells):
        run_dir = scratch / f"cell{n}"
        shutil.copytree(cell, run_dir)
        j = scratch / f"{n}.json"
        run(run_dir, "--stage-verdict", "PASS", "--json", str(j))
        try:
            rec = json.loads(j.read_text())
        except (OSError, ValueError):
            continue
        v = {r["rule"]: r["verdict"] for r in rec.get("rules", [])}
        got = v.get("R2_TOP_MODULE_PROVENANCE_REFUTED")
        assert got is not None, f"R2 did not run on {cell}"
        verdicts[got] += 1
        if got == "REJECT":
            rejects.add(str(cell.relative_to(root)))
        for o in rec.get("observations", []):
            if o["rule"].startswith("R2_") and o.get("grounded_in"):
                grounded[o["grounded_in"]] += 1
    present = {str(c.relative_to(root)) for c in cells}
    assert rejects == _CORPUS_REJECTS & present, (
        f"R2's rejection set moved: {sorted(rejects)}")
    assert verdicts["ACCEPT"], (
        "every answerable cell was refused or disarmed; a reviewer that never "
        "accepts is not a reviewer")
    for path, floor in _MIN_ACCEPTS.items():
        assert grounded[path] >= floor, (
            f"acceptances grounded in {path!r} fell to {grounded[path]} "
            f"(floor {floor}); a rule that stopped consulting one of its two "
            f"sources keeps its rejections and is no longer this rule")


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_the_fixtures_are_verbatim_copies_of_the_published_cells():
    """PROVENANCE.json is a claim about bytes; this is the check of it. A
    fixture that drifted from the cell it names would let this file prove a
    rule against an artefact nobody published."""
    import hashlib
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    prov = json.loads((FIX / "PROVENANCE.json").read_text(encoding="utf-8"))
    checked = 0
    unsourced: list = []
    for name, spec in prov["trees"].items():
        cell = root / spec["cell"]
        if not cell.is_dir():
            continue
        for rel, meta in spec["files"].items():
            local = (FIX / name / rel).read_bytes()
            assert hashlib.sha256(local).hexdigest() == meta["sha256"]
            if not (cell / rel).is_file():
                # The one file carried in a form the corpus does not hold, and
                # PROVENANCE says which and why. Its content IS still pinned to
                # the published bytes, by the decompressed hash that
                # `test_every_fixture_file_matches_its_recorded_hash` checks.
                assert "decompressed_sha256" in meta, f"{name}/{rel} has no source"
                unsourced.append(f"{name}/{rel}")
                continue
            assert (cell / rel).read_bytes() == local, f"{name}/{rel} drifted"
            checked += 1
    if not checked:
        pytest.skip("the corpus carries none of the named cells")
    assert len(unsourced) <= 1, unsourced
