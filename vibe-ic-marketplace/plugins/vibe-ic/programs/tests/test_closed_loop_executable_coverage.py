#!/usr/bin/env python3
"""Tests for closed_loop_executable_coverage_check.py — a line of YAML is not a
loop, and a census that cannot go red is decoration too.

THE POINT OF THIS FILE IS THE RED.

The green over the shipped flow proves only that the shipped tree is consistent
with the shipped registry. Each RED below proves the census would have SEEN the
corresponding rot:

  * a cited actuator deleted             -> CLC-EVIDENCE-MISSING + DEMOTION
  * a DECLARED_ONLY edge sold as a win   -> CLC-DECLARED-ONLY-PRESENTED-AS-SUCCESS
  * a claim on a step the flow never declared a loop for
                                         -> CLC-CLAIM-UNDECLARED-EDGE

and the vacuity half proves the three ways this check can be handed nothing —
no flow, a flow with no declarations, and a `--claims` path that is not there —
all exit 2 with a marker, never 0 and never 1.

THE ONE THAT MATTERS MOST is `test_a_missing_claims_document_is_rc2_not_a_clean_run`.
`--claims /does/not/exist` returning 0 would make every claim audit in this
repository unfalsifiable by typo, which is the exact shape this lane exists to
close.

`test_the_eco_log_arm_can_fire` is the positive control for the project-tree
scan: without it, `_claims_from_project` could be dead code and every test here
would still be green.

Fixtures build mutant COPIES; nothing here writes the real flow or the real tree.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

_HERE = Path(__file__).resolve().parent
PROG = _HERE.parent / "closed_loop_executable_coverage_check.py"
PLUGIN = _HERE.parent.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(_HERE.parent))

RC_OK, RC_FINDINGS, RC_NOT_MEASURED, RC_BAD = 0, 1, 2, 3

#: Steps the shipped flow declares a closed_loop on, whose class is measured
#: today. Named, not searched: the day one of them changes, this file must fail
#: loudly rather than quietly test nothing.
DECLARED_ONLY_WITNESS = "31"     # PV -> 32; the timing ECO explicitly declines
REMEASURED_WITNESS = "32"        # the repair pass's own self-edge
UNDECLARED_WITNESS = "19"        # a real step that declares no closed_loop


def _run(*extra, expect=None):
    r = subprocess.run([sys.executable, str(PROG), *extra],
                       capture_output=True, text=True)
    if expect is not None:
        assert r.returncode == expect, (
            f"rc={r.returncode} (wanted {expect})\n"
            f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")
    return r


def _report(tmp_path: Path, *extra, expect=None):
    out = tmp_path / "clc.json"
    r = _run(*extra, "--json", str(out), expect=expect)
    return r, (json.loads(out.read_text()) if out.is_file() else None)


def _claims(tmp_path: Path, *steps, name="claims.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(
        {"closed_loop_successes": [{"step": s, "note": "converged"}
                                   for s in steps]}))
    return p


# ══════════════════════════════════════════════════════════════════════════
# POSITIVE — green when it should be green
# ══════════════════════════════════════════════════════════════════════════
def test_the_shipped_flow_and_registry_agree(tmp_path):
    r, rep = _report(tmp_path, expect=RC_OK)
    assert rep["verdict"] == "PASS"
    assert rep["findings"] == []
    # The denominator is printed and is the real one, so a census over an empty
    # flow can never look like this.
    assert rep["declarations"] == len(rep["edges"]) > 0
    assert sum(rep["census"].values()) == rep["declarations"]
    assert "declared closed_loop edge" in r.stdout


def test_every_shipped_citation_actually_resolves(tmp_path):
    _, rep = _report(tmp_path, expect=RC_OK)
    cited = [c for e in rep["edges"] for c in e["citations"]]
    assert cited, "the registry cites nothing — the census would be unfalsifiable"
    unresolved = [c for c in cited if not c["resolved"]]
    assert not unresolved, unresolved


def test_an_unregistered_edge_defaults_to_declared_only(tmp_path):
    _, rep = _report(tmp_path, expect=RC_OK)
    by = {e["step"]: e for e in rep["edges"]}
    unregistered = [e for e in rep["edges"] if not e["registered"]]
    assert unregistered, "no unregistered edge left to prove the default with"
    assert all(e["class"] == "DECLARED_ONLY" for e in unregistered)
    assert by[DECLARED_ONLY_WITNESS]["class"] == "DECLARED_ONLY"
    assert by[REMEASURED_WITNESS]["class"] == "REMEASURED"


def test_nothing_on_main_claims_rollback_proven(tmp_path):
    """The load-bearing zero.

    The step-32 repair DOES implement an undo (`eco_fired_reverted_regression`)
    and no test in this tree exercises it, so the top tier is unreached. If this
    ever fails, someone earned it — update the census and say which test proves
    the rollback.
    """
    _, rep = _report(tmp_path, expect=RC_OK)
    assert rep["census"]["ROLLBACK_PROVEN"] == 0
    token = "eco_fired" + "_reverted_regression"   # split: this file greps for it
    proof = [p for p in _HERE.glob("test_*.py")
             if p.resolve() != Path(__file__).resolve()
             and token in p.read_text(errors="ignore")]
    assert not proof, (
        f"{[p.name for p in proof]} now exercises the ECO undo — promote edges "
        f"23/32 to ROLLBACK_PROVEN in the registry and update this census")


def test_a_claim_on_a_remeasured_edge_is_accepted(tmp_path):
    _, rep = _report(tmp_path, "--claims", str(_claims(tmp_path,
                                                       REMEASURED_WITNESS)),
                     expect=RC_OK)
    assert rep["claim_audit"] == "CHECKED"
    assert rep["claims_examined"] == 1
    assert rep["findings"] == []


# ══════════════════════════════════════════════════════════════════════════
# NEGATIVE — red when it should be red
# ══════════════════════════════════════════════════════════════════════════
def test_a_declared_only_edge_sold_as_a_success_is_refused(tmp_path):
    r, rep = _report(tmp_path, "--claims",
                     str(_claims(tmp_path, DECLARED_ONLY_WITNESS)),
                     expect=RC_FINDINGS)
    rules = {f["rule"] for f in rep["findings"]}
    assert "CLC-DECLARED-ONLY-PRESENTED-AS-SUCCESS" in rules
    assert DECLARED_ONLY_WITNESS in r.stdout


def test_a_claim_on_a_step_with_no_declared_loop_is_refused(tmp_path):
    _, rep = _report(tmp_path, "--claims",
                     str(_claims(tmp_path, UNDECLARED_WITNESS)),
                     expect=RC_FINDINGS)
    assert {f["rule"] for f in rep["findings"]} == {"CLC-CLAIM-UNDECLARED-EDGE"}


def _mutant_root(tmp_path: Path, *, loop: bool, eco: bool) -> Path:
    """A plugin root holding stubs of exactly the files the registry cites.

    `loop=False` removes the `while` around the regeneration call — the call is
    still THERE, so a substring-matching verifier would still say yes. That is
    the whole reason the citations are structural.

    Written out literally rather than dedented from a template: a stub that
    fails to parse demotes EVERY edge citing it, which reads exactly like the
    defect under test and would make the control meaningless.
    """
    root = tmp_path / f"root_loop{int(loop)}_eco{int(eco)}"
    progs = root / "programs"
    progs.mkdir(parents=True)
    (progs / "crosslayer_rewrite_equivalence_check.py").write_text("x = 1\n")

    head = ("def step_reference_tb(): ...\n"
            "def step_rtl_gen(): ...\n"
            "def step_crosslayer_rewrite_fidelity(): ...\n"
            "def main():\n")
    opener = "    while True:\n" if loop else "    if True:\n"
    src = head + opener + "        step_reference_tb()\n        step_rtl_gen()\n"
    compile(src, "<stub>", "exec")          # the stub must be REAL python
    (progs / "design_one_shot_runner.py").write_text(src)

    eco_src = ("def _run_eco_repair(): ...\n"
               "def _measure_posteco_mcorner_ocv(): ...\n"
               "def step_canonicalize_artefacts():\n"
               + ("    _run_eco_repair()\n    _measure_posteco_mcorner_ocv()\n"
                  if eco else "    pass\n"))
    compile(eco_src, "<stub>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(eco_src)
    return root


def test_the_stub_root_is_a_faithful_stand_in(tmp_path):
    """Control for the control: the healthy stub root must be GREEN, or every
    red below could be an artefact of the stub rather than of the mutation."""
    root = _mutant_root(tmp_path, loop=True, eco=True)
    _, rep = _report(tmp_path, "--root", str(root), expect=RC_OK)
    by = {e["step"]: e for e in rep["edges"]}
    assert by["4"]["class"] == "REMEASURED"
    assert by["23"]["class"] == "REMEASURED"
    assert by["32"]["class"] == "REMEASURED"
    # Rewrite fidelity is now a blocking clause of Step 2. The judge can stop
    # the candidate, but no runner re-executes Step 1, so the Step-2 fallback
    # edge remains honestly DECLARED_ONLY rather than inheriting the former
    # standalone step's over-broad EXECUTABLE label.
    assert by["2"]["class"] == "DECLARED_ONLY"


def test_deleting_the_loop_around_the_actuator_demotes_the_edge(tmp_path):
    """The call survives; only the loop is gone. Structural citation, so red."""
    root = _mutant_root(tmp_path, loop=False, eco=True)
    _, rep = _report(tmp_path, "--root", str(root), expect=RC_FINDINGS)
    by = {e["step"]: e for e in rep["edges"]}
    assert by["4"]["class"] == "DECLARED_ONLY", by["4"]
    assert any(f["rule"] == "CLC-EVIDENCE-MISSING" and f["step"] == "4"
               for f in rep["findings"])
    # the paired green arm is test_the_stub_root_is_a_faithful_stand_in:
    # same stub root, `while` restored, edge 4 back to REMEASURED.
    assert by["23"]["class"] == "REMEASURED", "only edge 4 should have moved"


def test_deleting_the_eco_actuator_demotes_both_edges_that_share_it(tmp_path):
    root = _mutant_root(tmp_path, loop=True, eco=False)
    _, rep = _report(tmp_path, "--root", str(root), expect=RC_FINDINGS)
    by = {e["step"]: e for e in rep["edges"]}
    assert by["23"]["class"] == "DECLARED_ONLY"
    assert by["32"]["class"] == "DECLARED_ONLY"
    assert {f["step"] for f in rep["findings"]
            if f["rule"] == "CLC-EVIDENCE-MISSING"} == {"23", "32"}


def test_the_eco_log_arm_can_fire(tmp_path):
    """POSITIVE CONTROL for the project scan.

    A tree whose `eco_log.json` says ECO_APPLIED + re_verified is presenting the
    step-32 loop as converged. Against the real tree that edge is REMEASURED and
    the claim stands; against a root where the actuator is gone the SAME tree is
    refused. Two arms differing only in the root, so the scan cannot be dead.
    """
    proj = tmp_path / "proj"
    eco = proj / "phase3" / "stage3" / "eco"
    eco.mkdir(parents=True)
    (eco / "eco_log.json").write_text(json.dumps(
        {"verdict": "ECO_APPLIED", "re_verified": True,
         "affected_steps": [21]}))

    _, green = _report(tmp_path, str(proj), expect=RC_OK)
    assert green["claim_audit"] == "CHECKED"
    assert green["claims_examined"] == 1
    assert green["claims"][0]["step"] == "32"

    root = _mutant_root(tmp_path, loop=True, eco=False)
    _, red = _report(tmp_path, str(proj), "--root", str(root),
                     expect=RC_FINDINGS)
    assert any(f["rule"] == "CLC-DECLARED-ONLY-PRESENTED-AS-SUCCESS"
               and f["step"] == "32" for f in red["findings"])


def test_an_honest_eco_log_is_not_a_claim(tmp_path):
    """ECO_ATTEMPTED / a false `re_verified` are honest non-successes. Reading
    them as claims would make every failed ECO a finding and the check useless."""
    proj = tmp_path / "proj2"
    eco = proj / "phase3" / "stage3" / "eco"
    eco.mkdir(parents=True)
    (eco / "eco_log.json").write_text(json.dumps(
        {"verdict": "ECO_ATTEMPTED", "re_verified": False}))
    _, rep = _report(tmp_path, str(proj), expect=RC_OK)
    assert rep["claim_audit"] == "CHECKED"      # the source WAS read
    assert rep["claims_examined"] == 0          # and it claimed nothing
    assert rep["claim_sources"]                 # ... and we say where we looked


# ══════════════════════════════════════════════════════════════════════════
# VACUOUS — missing input gives rc=2 with a marker; never 0, never 1
# ══════════════════════════════════════════════════════════════════════════
def test_an_absent_flow_is_rc2_with_a_marker(tmp_path):
    r = _run("--flow", str(tmp_path / "nope.yaml"), expect=RC_NOT_MEASURED)
    assert "[CANNOT CHECK]" in r.stderr


def test_a_flow_with_zero_declarations_is_rc2_not_a_clean_census(tmp_path):
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for s in doc["steps"]:
        s.pop("closed_loop", None)
    p = tmp_path / "flow.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    r, rep = _report(tmp_path, "--flow", str(p), expect=RC_NOT_MEASURED)
    assert rep["verdict"] == "NOT_MEASURED"
    assert rep["declarations"] == 0
    assert "empty denominator" in rep["missing_authority"]
    assert "[CANNOT CHECK]" in r.stderr


def test_a_missing_claims_document_is_rc2_not_a_clean_run(tmp_path):
    r = _run("--claims", str(tmp_path / "absent.json"), expect=RC_NOT_MEASURED)
    assert "[CANNOT CHECK]" in r.stderr


def test_a_claims_document_of_the_wrong_shape_is_rc2(tmp_path):
    p = tmp_path / "wrong.json"
    p.write_text(json.dumps({"results": ["everything converged"]}))
    r, rep = _report(tmp_path, "--claims", str(p), expect=RC_NOT_MEASURED)
    assert "closed_loop_successes" in rep["missing_authority"]
    assert "[CANNOT CHECK]" in r.stderr


def test_an_unparseable_claims_document_is_rc2(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json")
    _run("--claims", str(p), expect=RC_NOT_MEASURED)


def test_a_project_that_is_not_a_directory_is_rc2(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    r = _run(str(f), expect=RC_NOT_MEASURED)
    assert "[CANNOT CHECK]" in r.stderr


def test_no_claim_source_reports_not_checked_never_pass(tmp_path):
    """An unmeasured thing must not read as a measured zero."""
    r, rep = _report(tmp_path, expect=RC_OK)
    assert rep["claim_audit"] == "NOT_CHECKED"
    assert rep["claims_examined"] == 0
    assert rep["claim_sources"] == []
    assert "NOT_CHECKED" in r.stdout


def test_a_bad_argument_is_rc3_never_a_design_finding():
    r = subprocess.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == RC_BAD, r.stderr


def test_help_is_rc0_not_a_bad_invocation():
    """argparse raises SystemExit for `--help` too, with code 0. Mapping every
    SystemExit to rc 3 would make `--help` report an internal error — the same
    class of lie as a refusal exiting 1."""
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == RC_OK, r.stderr


def test_an_early_refusal_still_writes_the_refusal_report(tmp_path):
    """`--json` plus an unreadable input must leave a NOT_MEASURED artefact, not
    nothing: on disk, "I could not look" and "no report was asked for" would
    otherwise be the same state."""
    out = tmp_path / "refusal.json"
    r = subprocess.run([sys.executable, str(PROG), "--claims",
                        str(tmp_path / "absent.json"), "--json", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == RC_NOT_MEASURED, r.stderr
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "NOT_MEASURED"
    assert rep["declarations"] == 0
    assert rep["claim_audit"] == "NOT_CHECKED"
    assert "does not exist" in rep["missing_authority"]
