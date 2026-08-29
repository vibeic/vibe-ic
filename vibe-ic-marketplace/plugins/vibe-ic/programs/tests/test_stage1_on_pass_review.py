#!/usr/bin/env python3
"""The stage-1 ON-PASS review — and the control that stops it manufacturing
confidence in either direction.

WHY THIS FILE EXISTS
====================
`skills/_classification.json` declares a `verification` tier — "run AFTER
program PASS to spot-check the deterministic output" — with eight members, and
MEASURED on v1.12.83 all eight appear ZERO times in
`flow/phase1_phase2_phase3.yaml`. `stage_on_pass_review` is the first wiring of
that tier: stage 1's `on_pass_review:` block declares it, and it reads the
INTENT (L9) and the ARTEFACT (the staged RTL and the stage's reports) after the
stage has PASSED.

WHAT IS ACTUALLY AT RISK, AND WHY BOTH DIRECTIONS ARE ASSERTED
==============================================================
A reviewer that never rejects is WORSE than none — it manufactures confidence
in every artefact it looks at. One that rejects everything is worse still: it
is the same failure as a detector that fires on 21 of 21 subjects, and it
trains its readers to skip it. Neither is caught by a test that only proves one
direction, so every case below asserts BOTH on REAL published artefacts:

  ACCEPT  `fixtures/stage1_on_pass_review/accept_spm` — verbatim from the
          published cell `ic/spm/v1.9.96_gf180mcuD`.
  REJECT  `fixtures/stage1_on_pass_review/reject_caravel` — verbatim from the
          published cell `ic/caravel_user_project`, whose L9 declares
          `top_module: "caravel_user_project"` with
          `no_top_module_in_input: false` while the stage's own RTL declares
          `user_project_wrapper`, `user_proj_example` and `counter` — and the
          name it declares is a module that exists nowhere in that run. Seven
          of its stage reports then stamp `design_identity.top` with it.

`fixtures/.../PROVENANCE.json` carries each source file's sha256; nothing in
the fixture is authored. The corpus-bound test below re-reads the LIVE cells
when the corpus resolves, and pins the whole partition so a rule that starts
firing on everything, or on nothing, cannot land quietly.

THE DEFECT CLASS THIS COMES FROM
================================
v1.12.63: `spec_conformance` audited a submodule and reported port errors about
a module the spec never describes — its internal logic passed perfectly, and
its SUBJECT was wrong. The passing form of the same defect is the dangerous
one: when the mis-identified subject happens not to conflict, the stage goes
green and every downstream gate carries it faithfully to GDS.
"""
from __future__ import annotations

import ast
import json
import os
import tempfile
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
PROG = PROGRAMS / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
FIX = Path(__file__).resolve().parent / "fixtures" / "stage1_on_pass_review"
ACCEPT = FIX / "accept_spm"
REJECT = FIX / "reject_caravel"

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _published_corpus as _pc  # noqa: E402
except Exception:  # pragma: no cover
    _pc = None

yaml = pytest.importorskip("yaml")


def run(project, *extra, flow=None, emit=None):
    """Invoke the review exactly as the flow declares it.

    A rejection WRITES the run's own regression INTO the run tree — that is
    where it belongs and how the emitted test finds its root — so every test
    that can provoke one runs against `tree()`, a per-test copy. Nothing here
    ever writes into the shipped fixture."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    argv = [sys.executable, str(PROG), str(project), "--stage", "stage1",
            "--flow-def", str(flow or FLOW)]
    if emit is not None:
        argv += ["--emit-test", str(emit)]
    return subprocess.run(argv + list(extra), capture_output=True, text=True,
                          env=env)


def tree(tmp_path, which):
    """A writable copy of one published fixture cell."""
    import shutil
    d = tmp_path / which.name
    if not d.exists():
        shutil.copytree(which, d)
    return d


def declaration():
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == "stage1":
            return st.get("on_pass_review")
    raise AssertionError("stage1 is not declared")


def flow_with(tmp_path, **override):
    """A copy of the canonical flow with stage1's on_pass_review patched."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        if st["id"] == "stage1":
            st["on_pass_review"] = {**st["on_pass_review"], **override}
    p = tmp_path / "flow.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# the declaration is in the flow, and nowhere else
# ─────────────────────────────────────────────────────────────────────────────
def test_stage1_declares_an_on_pass_review_naming_a_verification_tier_skill():
    d = declaration()
    assert d is not None, "stage1 declares no on_pass_review"
    assert d["fires_on"] == "stage_pass"
    assert d["verdict"] in ("advisory", "blocking"), (
        "BLOCKING vs ADVISORY must be declared, and declared HERE — whether a "
        "rejection stops the flow is the flow's decision, not the reviewer's")
    tier = json.loads((PLUGIN / "skills" / "_classification.json")
                      .read_text(encoding="utf-8"))["tiers"]["verification"]["skills"]
    assert d["skill"] in tier, (
        f"{d['skill']!r} is not a member of the verification tier {tier}")
    assert (PLUGIN / "skills" / d["skill"] / "SKILL.md").is_file()


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
    assert rec["not_checked"] == []


def test_a_real_run_whose_intent_names_a_top_the_stage_never_built_is_rejected(tmp_path):
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS",
            "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REJECT" in r.stdout
    rec = json.loads((tmp_path / "r.json").read_text())
    assert len(rec["rejections"]) == 1
    f = rec["rejections"][0]
    assert f["rule"] == "R1_INTENT_TOP_NOT_BUILT"
    # the INTENT it read
    assert f["intent"]["field"] == "top_module"
    assert f["intent"]["value"] == "caravel_user_project"
    assert f["intent"]["no_top_module_in_input"] is False, (
        "the disarm must not be reachable here: this intent CLAIMS it read a "
        "top out of the design input")
    # the ARTEFACT fact it read
    assert f["artefact"]["module_count"] == 3
    assert set(f["artefact"]["modules"]) == {
        "user_project_wrapper", "user_proj_example", "counter"}
    assert "caravel_user_project" not in f["artefact"]["modules"]
    # the CONTRADICTION, and the blast radius
    assert "caravel_user_project" in f["contradiction"]
    assert f["restamped_in"], "no report was found carrying the refuted subject"
    # the TEST — a path that EXISTS, written by this run of the review
    assert f["test"], "the rejection carries no test"
    assert (tmp_path / REJECT.name / f["test"]).is_file(), f["test"]


def test_the_emitted_test_fails_today_and_passes_when_the_run_is_repaired(tmp_path):
    """The doctrine, executable. `an AI rejection must be proven by a
    prompt-derived executable test before repair` is only wired if the test the
    rejection names actually discriminates. So: run the EMITTED file against
    the defective run (must fail), then build the one module its intent names
    and run THE SAME FILE again (must pass). A test that could not fail proves
    nothing, and a test that could not pass would block every repair."""
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
    assert "caravel_user_project" in before.stdout

    (run_dir / "phase2" / "stage1" / "rtl" / "top.v").write_text(
        "module caravel_user_project (input wb_clk_i);\nendmodule\n",
        encoding="utf-8")
    after = subprocess.run([sys.executable, str(emitted)],
                           capture_output=True, text=True)
    assert after.returncode == 0, (
        "the emitted test still fails after the repair it asks for:\n"
        + after.stdout + after.stderr)


def test_the_emitted_test_refuses_an_empty_artefact_rather_than_passing(tmp_path):
    """The emitted test carries the same rule its emitter does: an empty module
    set refutes nothing and certifies nothing. Deleting the RTL must not be a
    way to make the run's own regression go green."""
    run_dir = tree(tmp_path, REJECT)
    r = run(run_dir, "--stage-verdict", "PASS", "--json", str(tmp_path / "r.json"))
    assert r.returncode == 1
    emitted = run_dir / json.loads((tmp_path / "r.json").read_text())[
        "rejections"][0]["test"]
    for f in (run_dir / "phase2" / "stage1" / "rtl").glob("*.v"):
        f.unlink()
    out = subprocess.run([sys.executable, str(emitted)],
                         capture_output=True, text=True)
    assert out.returncode == 1
    assert "staged no readable module" in out.stdout


def test_the_accept_control_does_not_move_when_the_reject_case_is_measured(tmp_path):
    """Both directions in ONE invocation shape. A rule that started refusing
    everything would take the accept case with it; a rule that stopped biting
    would take the reject case with it. Neither may move alone."""
    good = run(tree(tmp_path, ACCEPT), "--stage-verdict", "PASS")
    bad = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS")
    assert (good.returncode, bad.returncode) == (0, 1), (
        f"good={good.returncode} bad={bad.returncode}\n"
        f"{good.stdout}\n---\n{bad.stdout}")


def test_the_rejection_is_caused_by_the_module_set_and_nothing_else(tmp_path):
    """The negative control for the rejection itself: copy the REAL reject tree
    and add the one module its intent names. Nothing else changes — same L9,
    same reports, same cell. It must flip to ACCEPT, which is what proves the
    finding is about the artefact rather than about that cell."""
    import shutil
    repaired = tmp_path / "repaired"
    shutil.copytree(REJECT, repaired)
    (repaired / "phase2" / "stage1" / "rtl" / "caravel_user_project.v").write_text(
        "module caravel_user_project (input wb_clk_i);\nendmodule\n",
        encoding="utf-8")
    before = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS")
    after = run(repaired, "--stage-verdict", "PASS")
    assert before.returncode == 1
    assert after.returncode == 0, after.stdout + after.stderr


# ─────────────────────────────────────────────────────────────────────────────
# it fires on SUCCESS, and only on an ESTABLISHED success
# ─────────────────────────────────────────────────────────────────────────────
def test_the_review_does_not_run_on_a_stage_that_failed(tmp_path):
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "FAIL")
    assert r.returncode == 2, r.stdout
    assert "did not pass" in r.stdout


def test_an_unestablished_verdict_is_not_a_pass(tmp_path):
    """No compliance report and no stated verdict. Answering 0 here would be a
    review of nothing reporting a pass — the exact shape this rung exists to
    stop."""
    r = run(tree(tmp_path, REJECT))
    assert r.returncode == 2, r.stdout
    assert "unestablished" in r.stdout


def test_a_compliance_report_supplies_the_verdict(tmp_path):
    """And BOTH ways: a green stage-1 row reaches the rules, a red one does
    not. A test that only proved the refusal would pass against a program that
    refuses every compliance report it is given."""
    green = tmp_path / "green.json"
    green.write_text(json.dumps({"steps": [
        {"id": 1, "stage": "stage1", "status": "PASS"},
        {"id": 9, "stage": "stage2", "status": "FAIL"}]}))
    red = tmp_path / "red.json"
    red.write_text(json.dumps({"steps": [
        {"id": 1, "stage": "stage1", "status": "PASS"},
        {"id": 2, "stage": "stage1", "status": "FAIL"}]}))
    assert run(tree(tmp_path, REJECT), "--compliance", str(green)).returncode == 1
    assert run(tree(tmp_path, ACCEPT), "--compliance", str(green)).returncode == 0
    assert run(tree(tmp_path / "red", REJECT), "--compliance", str(red)).returncode == 2


# ─────────────────────────────────────────────────────────────────────────────
# §4.05 — the reviewer reads the design INPUT
# ─────────────────────────────────────────────────────────────────────────────
def test_a_denied_intent_path_is_refused_rather_than_read(tmp_path):
    flow = flow_with(tmp_path, intent=[
        "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
        "benchmark/oracle/expected_ports.json"])
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS", flow=flow)
    assert r.returncode == 2, r.stdout
    assert "4.05" in r.stdout and "oracle" in r.stdout


def test_the_denial_is_a_list_not_a_hardcode_and_an_allowed_path_still_reads(tmp_path):
    """The control for the guard: with the same shape but a path carrying no
    denied segment, the review reaches its rules and rejects as before. A guard
    that refused everything would pass the test above."""
    flow = flow_with(tmp_path, intent=[
        "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
        "phase1/generated_docs/L2_FRS.json"])
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


def test_the_four_required_parts_are_declared_by_the_flow():
    assert declaration()["rejection_requires"] == [
        "intent", "artefact", "contradiction", "test"]


# ─────────────────────────────────────────────────────────────────────────────
# an empty artefact certifies nothing
# ─────────────────────────────────────────────────────────────────────────────
def test_an_empty_module_set_is_not_an_acceptance(tmp_path):
    tree = tmp_path / "no_rtl"
    (tree / "phase1" / "generated_docs").mkdir(parents=True)
    (tree / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "widget_top", "no_top_module_in_input": False}))
    (tree / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    r = run(tree, "--stage-verdict", "PASS")
    assert r.returncode == 2, r.stdout
    assert "EMPTY module set" in r.stdout


def test_an_intent_that_declares_no_top_disarms_instead_of_rejecting(tmp_path):
    """The published corpus's own disclosure: when phase 1 could not read a top
    out of the design input it says so and publishes a placeholder. A review
    that called that a contradiction would reject 20 of the corpus's cells for
    a claim their intent never made."""
    r = run(tree(tmp_path, ACCEPT), "--stage-verdict", "PASS")
    assert r.returncode == 0
    assert "DISARMED" in r.stdout
    assert "no_top_module_in_input=True" in r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# the review does not re-derive the artefact
# ─────────────────────────────────────────────────────────────────────────────
_SPAWN = {"subprocess", "popen", "system", "execv", "execvp", "spawn",
          "check_output", "check_call", "run_tcl"}


def _spawn_names(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and n.attr.lower() in _SPAWN:
            found.add(n.attr)
        elif isinstance(n, ast.Name) and n.id.lower() in _SPAWN:
            found.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            mod = getattr(n, "module", None) or ""
            names = [a.name for a in n.names] + [mod]
            for nm in names:
                if nm and nm.split(".")[0].lower() in _SPAWN:
                    found.add(nm)
    return found


def test_the_review_starts_no_process_so_it_cannot_re_derive_the_artefact():
    """A reviewer that regenerates the RTL or re-runs the router has replaced
    the program rather than reviewed it. This is structural, not a promise in a
    docstring."""
    assert _spawn_names(PROG) == set(), (
        "stage_on_pass_review must read the artefact the stage left behind, "
        f"not produce another one; found {_spawn_names(PROG)}")


def test_the_no_re_derivation_check_can_actually_fail():
    """The control for the check above: a detector that finds nothing anywhere
    would pass it against any program at all. This file spawns processes, so
    the same detector must find them here."""
    assert _spawn_names(Path(__file__)) >= {"subprocess", "run"} - {"run"}
    assert "subprocess" in _spawn_names(Path(__file__))


# ─────────────────────────────────────────────────────────────────────────────
# a stage with no declaration is NOT CHECKED, never a pass
# ─────────────────────────────────────────────────────────────────────────────
def test_a_stage_that_declares_no_review_is_not_checked(tmp_path):
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for st in doc["stages"]:
        st.pop("on_pass_review", None)
    p = tmp_path / "bare.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    r = run(tree(tmp_path, REJECT), "--stage-verdict", "PASS", flow=p)
    assert r.returncode == 2, r.stdout
    assert "declares no" in r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# the live corpus: the whole partition, pinned
# ─────────────────────────────────────────────────────────────────────────────
#: MEASURED on benchmark-data, 2026-08-30, over every published cell carrying an
#: L9. The three rejections are verified true positives: `module ibex_top` and
#: `module caravel_user_project` exist NOWHERE in their own run trees.
_CORPUS_REJECTS = {"ic/ibex",
                   "ic/caravel_user_project",
                   "ic/caravel_user_project/v1.9.43_sky130A"}


@pytest.mark.skipif(_pc is None, reason="corpus helper unavailable")
def test_the_partition_over_the_published_corpus_does_not_move():
    """Pins BOTH sides on the live corpus. The reject set is named cell by cell
    so a rule that widened would show up as an extra name rather than as a
    count nobody reads; the accept side is required to be non-empty so a rule
    that stopped biting cannot pass by rejecting everything."""
    root = _pc.corpus_tree()
    if root is None:
        pytest.skip(_pc.skip_reason())
    cells = sorted({p.parent.parent.parent
                    for p in root.rglob("phase1/generated_docs/L9_INTEGRATION_SPEC.json")})
    if not cells:
        pytest.skip("the corpus carries no cell with an L9")
    scratch = Path(tempfile.mkdtemp(prefix="on_pass_review_corpus_"))
    rejects, accepts = set(), set()
    for cell in cells:
        rc = run(cell, "--stage-verdict", "PASS",
                 emit=scratch / f"cell{len(rejects) + len(accepts)}").returncode
        rel = str(cell.relative_to(root))
        if rc == 1:
            rejects.add(rel)
        elif rc == 0:
            accepts.add(rel)
    assert rejects == _CORPUS_REJECTS & set(
        str(c.relative_to(root)) for c in cells), (
        f"the rejection set moved: {sorted(rejects)}")
    assert accepts, "every cell was refused; a reviewer that rejects all is none"
