#!/usr/bin/env python3
"""Tests for closed_loop_executable_coverage_check.py — a line of YAML is not a
loop, and a census that cannot go red is decoration too.

THE POINT OF THIS FILE IS THE RED.

The green over the shipped flow proves only that the shipped tree is consistent
with the shipped registry. Each RED below proves the census would have SEEN the
corresponding rot:

  * a cited actuator deleted             -> CLC-EVIDENCE-MISSING + DEMOTION
  * a candidate refusal called execution -> CLC-NON-REEXECUTION-ACTUATION
  * a `re_execute` label over file presence
                                         -> CLC-NONSTRUCTURAL-EVIDENCE
  * a real call to the wrong fallback step
                                         -> CLC-ACTUATION-NOT-FALLBACK-REENTRY
  * another edge's real fallback retry   -> CLC-ACTUATION-NOT-EDGE-TRIGGERED
  * sibling-path remeasurement evidence -> CLC-REMEASURE-NOT-ACTUATION-PATH
  * inverted/overwritten trigger branch  -> CLC-EVIDENCE-MISSING + DEMOTION
  * fallback after a path terminator      -> CLC-EVIDENCE-MISSING + DEMOTION
  * measurement only before fallback      -> CLC-EVIDENCE-MISSING + DEMOTION
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

`test_the_repair_log_arm_can_fire` is the positive control for the project-tree
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
import closed_loop_executable_coverage_check as clc  # noqa: E402
import _hostpaths  # noqa: E402

RC_OK, RC_FINDINGS, RC_NOT_MEASURED, RC_BAD = 0, 1, 2, 3

#: Steps the shipped flow declares a closed_loop on, whose class is measured
#: today. Named, not searched: the day one of them changes, this file must fail
#: loudly rather than quietly test nothing.
DECLARED_ONLY_WITNESS = "31"     # PV -> 32; the timing repair explicitly declines
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

    The step-32 repair DOES implement an undo (`timing_repair_reverted_regression`)
    and no test in this tree exercises it, so the top tier is unreached. If this
    ever fails, someone earned it — update the census and say which test proves
    the rollback.
    """
    _, rep = _report(tmp_path, expect=RC_OK)
    assert rep["census"]["ROLLBACK_PROVEN"] == 0
    token = "timing_repair" + "_reverted_regression"   # split: this file greps for it
    proof = [p for p in _HERE.glob("test_*.py")
             if p.resolve() != Path(__file__).resolve()
             and token in p.read_text(errors="ignore")]
    assert not proof, (
        f"{[p.name for p in proof]} now exercises the repair undo — promote edges "
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


def _mutant_root(tmp_path: Path, *, loop: bool, repair: bool) -> Path:
    """A plugin root holding stubs of exactly the files the registry cites.

    `loop=False` removes the `while` around the regeneration call — the call is
    still THERE, so a substring-matching verifier would still say yes. That is
    the whole reason the citations are structural.

    Written out literally rather than dedented from a template: a stub that
    fails to parse demotes EVERY edge citing it, which reads exactly like the
    defect under test and would make the control meaningless.
    """
    root = tmp_path / f"root_loop{int(loop)}_repair{int(repair)}"
    progs = root / "programs"
    progs.mkdir(parents=True)
    (progs / "crosslayer_rewrite_equivalence_check.py").write_text("x = 1\n")

    head = ("def step_reference_tb(): ...\n"
            "def step_rtl_gen(): ...\n"
            "def step_crosslayer_rewrite_fidelity(): ...\n"
            "def main():\n"
            "    step_crosslayer_rewrite_fidelity()\n")
    if loop:
        src = (head + "    while True:\n"
               + "        sr = step_reference_tb()\n"
               + "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
               + "            break\n"
               + "        step_rtl_gen()\n"
               + "        step_reference_tb()\n")
    else:
        src = (head + "    if True:\n"
               + "        sr = step_reference_tb()\n"
               + "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
               + "            pass\n"
               + "        step_rtl_gen()\n"
               + "        step_reference_tb()\n")
    compile(src, "<stub>", "exec")          # the stub must be REAL python
    (progs / "design_one_shot_runner.py").write_text(src)

    repair_src = ("class _Decision:\n"
               "    def decide(self): return {'repair_needed': True}\n"
               "_repair_dec = _Decision()\n"
               "def _run_postroute_timing_repair(): ...\n"
               "def _measure_postrepair_mcorner_ocv(): ...\n"
               "def step_canonicalize_artefacts():\n"
               "    decision = _repair_dec.decide()\n"
               "    if decision['repair_needed']:\n"
               + ("        _run_postroute_timing_repair()\n"
                  "        _measure_postrepair_mcorner_ocv()\n"
                  if repair else "        pass\n"))
    compile(repair_src, "<stub>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(repair_src)
    return root


def test_the_stub_root_is_a_faithful_stand_in(tmp_path):
    """Control for the control: the healthy stub root must be GREEN, or every
    red below could be an artefact of the stub rather than of the mutation."""
    root = _mutant_root(tmp_path, loop=True, repair=True)
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


def test_refusing_a_candidate_cannot_be_laundered_as_executable(
        tmp_path, monkeypatch):
    """RED on the pre-fix semantics: a resolved refusal citation used to
    promote an edge even though the fallback step was never re-entered."""
    root = _mutant_root(tmp_path, loop=True, repair=True)
    monkeypatch.setitem(clc.REGISTRY, "2", {
        "class": "EXECUTABLE",
        "actuation_form": "refuse_candidate",
        "why": "the judge rejects the candidate but does not run Step 1",
        "evidence": {
            "actuate": [{
                "kind": "file_exists",
                "file": "programs/crosslayer_rewrite_equivalence_check.py",
            }],
        },
    })

    rec = clc.classify_edge("2", root, "1")

    assert rec["citations"][0]["resolved"] is True, (
        "the control must reach the semantic refusal, not fail on a bad path")
    assert rec["class"] == "DECLARED_ONLY"
    assert "actuate" not in rec["roles_satisfied"]
    assert any("CLC-NON-REEXECUTION-ACTUATION" in problem
               for problem in rec["problems"])

    # Run the program's evaluator over the real shipped flow/root too.  This
    # proves the semantic error is not merely annotated on an isolated record:
    # it becomes a named finding and the checker returns its blocking rc 1.
    real_flow = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml")
    real_plugin = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic")
    verdict, report, rc = clc.evaluate(real_flow, None, None, real_plugin)
    assert (verdict, rc) == ("FAIL", RC_FINDINGS)
    assert any(finding["step"] == "2"
               and finding["rule"] == "CLC-NON-REEXECUTION-ACTUATION"
               for finding in report["findings"])


def test_omitting_the_actuation_form_cannot_restore_the_old_default(
        tmp_path, monkeypatch):
    """The refusal fix must not be bypassable by deleting its label."""
    root = _mutant_root(tmp_path, loop=True, repair=True)
    monkeypatch.setitem(clc.REGISTRY, "2", {
        "class": "EXECUTABLE",
        "why": "ambiguous actuator with no declared execution form",
        "evidence": {
            "actuate": [{
                "kind": "file_exists",
                "file": "programs/crosslayer_rewrite_equivalence_check.py",
            }],
        },
    })

    rec = clc.classify_edge("2", root, "1")

    assert rec["citations"][0]["resolved"] is True
    assert rec["class"] == "DECLARED_ONLY"
    assert "actuate" not in rec["roles_satisfied"]
    assert any("CLC-ACTUATION-FORM-MISSING" in problem
               for problem in rec["problems"])


def test_reexecute_label_cannot_launder_file_presence_as_execution(
        tmp_path, monkeypatch):
    """The label is a claim, not proof: file existence cannot earn a tier."""
    root = _mutant_root(tmp_path, loop=True, repair=True)
    monkeypatch.setitem(clc.REGISTRY, "2", {
        "class": "EXECUTABLE",
        "actuation_form": "re_execute",
        "why": "forged label beside the old refusal file",
        "evidence": {
            "actuate": [{
                "kind": "file_exists",
                "file": "programs/crosslayer_rewrite_equivalence_check.py",
            }],
        },
    })

    rec = clc.classify_edge("2", root, "1")

    assert rec["citations"][0]["resolved"] is True
    assert rec["citations"][0]["eligible"] is False
    assert rec["class"] == "DECLARED_ONLY"
    assert "actuate" not in rec["roles_satisfied"]
    assert any("CLC-NONSTRUCTURAL-EVIDENCE" in problem
               for problem in rec["problems"])

    real_flow = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml")
    verdict, report, rc = clc.evaluate(real_flow, None, None, root)
    assert (verdict, rc) == ("FAIL", RC_FINDINGS)
    assert any(finding["step"] == "2"
               and finding["rule"] == "CLC-NONSTRUCTURAL-EVIDENCE"
               for finding in report["findings"])


def test_file_presence_copied_into_every_role_cannot_claim_rollback(
        tmp_path, monkeypatch):
    """Four copies of non-execution evidence are still zero execution proof."""
    root = _mutant_root(tmp_path, loop=True, repair=True)
    citation = {
        "kind": "file_exists",
        "file": "programs/crosslayer_rewrite_equivalence_check.py",
    }
    monkeypatch.setitem(clc.REGISTRY, "2", {
        "class": "ROLLBACK_PROVEN",
        "actuation_form": "re_execute",
        "why": "the same file-presence claim copied into all roles",
        "evidence": {role: [dict(citation)] for role in clc.EVIDENCE_ROLES},
    })

    rec = clc.classify_edge("2", root, "1")

    assert all(c["resolved"] for c in rec["citations"])
    assert not any(c["eligible"] for c in rec["citations"])
    assert rec["roles_satisfied"] == []
    assert rec["class"] == "DECLARED_ONLY"
    assert sum("CLC-NONSTRUCTURAL-EVIDENCE" in p
               for p in rec["problems"]) == len(clc.EVIDENCE_ROLES)


def test_structural_call_to_the_wrong_step_cannot_claim_reentry(
        tmp_path, monkeypatch):
    """A real call is not proof of this edge unless it enters fallback_to."""
    root = _mutant_root(tmp_path, loop=True, repair=True)
    monkeypatch.setitem(clc.REGISTRY, "4", {
        "class": "EXECUTABLE",
        "actuation_form": "re_execute",
        "why": "calls the testbench, not fallback step 1",
        "evidence": {
            "actuate": [{
                "kind": "fallback_after_trigger_in_loop",
                "file": "programs/design_one_shot_runner.py",
                "caller": "main",
                "trigger_callee": "step_reference_tb",
                "trigger_field": "status",
                "terminal_values": ["PASS", "SKIP", "WAIVED"],
                "callee": "step_reference_tb",
            }],
        },
    })

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is True
    assert rec["citations"][0]["structural"] is True
    assert rec["citations"][0]["bound_to_fallback"] is False
    assert rec["citations"][0]["bound_to_trigger"] is True
    assert rec["class"] == "DECLARED_ONLY"
    assert any("CLC-ACTUATION-NOT-FALLBACK-REENTRY" in problem
               for problem in rec["problems"])


def test_step2_cannot_borrow_step4s_real_retry_loop(tmp_path, monkeypatch):
    """Same fallback target is insufficient: the source trigger must match."""
    root = _mutant_root(tmp_path, loop=True, repair=True)
    monkeypatch.setitem(clc.REGISTRY, "2", {
        "class": "EXECUTABLE",
        "actuation_form": "re_execute",
        "why": "borrows Step 4's genuine reference-TB retry",
        "evidence": {
            "actuate": [{
                "kind": "fallback_after_trigger_in_loop",
                "file": "programs/design_one_shot_runner.py",
                "caller": "main",
                "trigger_callee": "step_reference_tb",
                "trigger_field": "status",
                "terminal_values": ["PASS", "SKIP", "WAIVED"],
                "callee": "step_rtl_gen",
            }],
        },
    })

    rec = clc.classify_edge("2", root, "1")

    assert rec["citations"][0]["resolved"] is True
    assert rec["citations"][0]["bound_to_fallback"] is True
    assert rec["citations"][0]["bound_to_trigger"] is False
    assert rec["class"] == "DECLARED_ONLY"
    assert any("CLC-ACTUATION-NOT-EDGE-TRIGGERED" in problem
               for problem in rec["problems"])

    real_flow = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml")
    verdict, report, rc = clc.evaluate(real_flow, None, None, root)
    assert (verdict, rc) == ("FAIL", RC_FINDINGS)
    assert any(finding["step"] == "2"
               and finding["rule"] == "CLC-ACTUATION-NOT-EDGE-TRIGGERED"
               for finding in report["findings"])


def test_guarded_remeasurement_cannot_borrow_a_sibling_path(
        tmp_path, monkeypatch):
    """The measurement must extend this edge's accepted guarded actuation."""
    root = _mutant_root(tmp_path, loop=True, repair=True)
    runner = root / "programs" / "phase3_one_shot_runner.py"
    runner.write_text(
        "class _Decision:\n"
        "    def decide(self): return {'repair_needed': True}\n"
        "_repair_dec = _Decision()\n"
        "_other_dec = _Decision()\n"
        "def _run_postroute_timing_repair(): ...\n"
        "def _other_actuator(): ...\n"
        "def _measure_postrepair_mcorner_ocv(): ...\n"
        "def step_canonicalize_artefacts():\n"
        "    decision = _repair_dec.decide()\n"
        "    if decision['repair_needed']:\n"
        "        _run_postroute_timing_repair()\n"
        "    sibling = _other_dec.decide()\n"
        "    if sibling['repair_needed']:\n"
        "        _other_actuator()\n"
        "        _measure_postrepair_mcorner_ocv()\n")
    compile(runner.read_text(), "<guarded-sibling>", "exec")
    monkeypatch.setitem(clc.REGISTRY, "23", {
        "class": "REMEASURED",
        "actuation_form": "re_execute",
        "why": "attempts to borrow a sibling guarded measurement",
        "evidence": {
            "actuate": [{
                "kind": "fallback_guarded_by_trigger",
                "file": "programs/phase3_one_shot_runner.py",
                "caller": "step_canonicalize_artefacts",
                "trigger_callee": "_repair_dec.decide",
                "trigger_field": "repair_needed",
                "trigger_value": True,
                "callee": "_run_postroute_timing_repair",
            }],
            "remeasure": [{
                "kind": "remeasure_after_fallback_guarded_by_trigger",
                "file": "programs/phase3_one_shot_runner.py",
                "caller": "step_canonicalize_artefacts",
                "trigger_callee": "_other_dec.decide",
                "trigger_field": "repair_needed",
                "trigger_value": True,
                "actuator_callee": "_other_actuator",
                "callee": "_measure_postrepair_mcorner_ocv",
            }],
        },
    })

    rec = clc.classify_edge("23", root, "32")
    remeasure = next(c for c in rec["citations"]
                     if c["role"] == "remeasure")

    assert rec["class"] == "EXECUTABLE"
    assert rec["roles_satisfied"] == ["actuate"]
    assert remeasure["resolved"] is True
    assert remeasure["bound_to_fallback"] is False
    assert remeasure["bound_to_trigger"] is False
    assert remeasure["joined_to_actuation"] is False
    assert remeasure["eligible"] is False
    assert any("CLC-REMEASURE-NOT-ACTUATION-PATH" in problem
               for problem in rec["problems"])


def test_loop_remeasurement_cannot_borrow_a_sibling_retry(
        tmp_path, monkeypatch):
    """A second loop cannot lend its back-edge to the canonical fallback."""
    root = _mutant_root(tmp_path, loop=True, repair=True)
    runner = root / "programs" / "design_one_shot_runner.py"
    runner.write_text(
        "def step_reference_tb(): ...\n"
        "def step_rtl_gen(): ...\n"
        "def _other_tb(): ...\n"
        "def _other_gen(): ...\n"
        "def main():\n"
        "    while True:\n"
        "        result = step_reference_tb()\n"
        "        if result.status in ('PASS', 'SKIP', 'WAIVED'):\n"
        "            break\n"
        "        step_rtl_gen()\n"
        "        return\n"
        "    while True:\n"
        "        sibling = _other_tb()\n"
        "        if sibling.status in ('PASS', 'SKIP', 'WAIVED'):\n"
        "            break\n"
        "        _other_gen()\n"
        "        _other_tb()\n")
    compile(runner.read_text(), "<loop-sibling>", "exec")
    monkeypatch.setitem(clc.REGISTRY, "4", {
        "class": "REMEASURED",
        "actuation_form": "re_execute",
        "why": "attempts to borrow a sibling loop measurement",
        "evidence": {
            "actuate": [{
                "kind": "fallback_after_trigger_in_loop",
                "file": "programs/design_one_shot_runner.py",
                "caller": "main",
                "trigger_callee": "step_reference_tb",
                "trigger_field": "status",
                "terminal_values": ["PASS", "SKIP", "WAIVED"],
                "callee": "step_rtl_gen",
            }],
            "remeasure": [{
                "kind": "remeasure_after_fallback_in_loop",
                "file": "programs/design_one_shot_runner.py",
                "caller": "main",
                "trigger_callee": "_other_tb",
                "trigger_field": "status",
                "terminal_values": ["PASS", "SKIP", "WAIVED"],
                "actuator_callee": "_other_gen",
                "callee": "_other_tb",
            }],
        },
    })

    rec = clc.classify_edge("4", root, "1")
    remeasure = next(c for c in rec["citations"]
                     if c["role"] == "remeasure")

    assert rec["class"] == "EXECUTABLE"
    assert rec["roles_satisfied"] == ["actuate"]
    assert remeasure["resolved"] is True
    assert remeasure["bound_to_fallback"] is False
    assert remeasure["bound_to_trigger"] is False
    assert remeasure["joined_to_actuation"] is False
    assert remeasure["eligible"] is False
    assert any("CLC-REMEASURE-NOT-ACTUATION-PATH" in problem
               for problem in rec["problems"])


def test_step2s_real_trigger_outside_the_retry_loop_is_not_execution(
        tmp_path, monkeypatch):
    """Both calls in one function are not enough; the trigger must guard it."""
    root = _mutant_root(tmp_path, loop=True, repair=True)
    monkeypatch.setitem(clc.REGISTRY, "2", {
        "class": "EXECUTABLE",
        "actuation_form": "re_execute",
        "why": "the real Step-2 judge is outside Step 4's loop",
        "evidence": {
            "actuate": [{
                "kind": "fallback_after_trigger_in_loop",
                "file": "programs/design_one_shot_runner.py",
                "caller": "main",
                "trigger_callee": "step_crosslayer_rewrite_fidelity",
                "trigger_field": "status",
                "terminal_values": ["PASS", "SKIP", "WAIVED"],
                "callee": "step_rtl_gen",
            }],
        },
    })

    rec = clc.classify_edge("2", root, "1")

    assert rec["citations"][0]["bound_to_fallback"] is True
    assert rec["citations"][0]["bound_to_trigger"] is True
    assert rec["citations"][0]["resolved"] is False
    assert rec["class"] == "DECLARED_ONLY"
    assert any("CLC-EVIDENCE-MISSING" in problem
               for problem in rec["problems"])


@pytest.mark.parametrize("body", [
    """while True:
        result = step_crosslayer_rewrite_fidelity()
        if result:
            break
        if False:
            step_rtl_gen()
        break
    """,
    """while True:
        result = step_crosslayer_rewrite_fidelity()
        if result:
            break
        def dead_retry():
            step_rtl_gen()
        break
    """,
    """while False:
        result = step_crosslayer_rewrite_fidelity()
        if result:
            break
        step_rtl_gen()
    """,
    """while True:
        result = step_crosslayer_rewrite_fidelity()
        if result:
            break
        fake_backend.step_rtl_gen()
        break
    """,
], ids=("if-false", "nested-dead-def", "while-false", "qualified-impostor"))
def test_dead_or_name_only_fallback_calls_cannot_claim_execution(
        tmp_path, monkeypatch, body):
    root = tmp_path / "dead_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_crosslayer_rewrite_fidelity(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n" + textwrap.indent(body, "    "))
    compile(source, "<dead-control>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)
    monkeypatch.setitem(clc.REGISTRY, "2", {
        "class": "EXECUTABLE",
        "actuation_form": "re_execute",
        "why": "dead/name-only adversarial control",
        "evidence": {
            "actuate": [{
                "kind": "fallback_after_trigger_in_loop",
                "file": "programs/design_one_shot_runner.py",
                "caller": "main",
                "trigger_callee": "step_crosslayer_rewrite_fidelity",
                "trigger_field": "status",
                "terminal_values": ["PASS", "SKIP", "WAIVED"],
                "callee": "step_rtl_gen",
            }],
        },
    })

    rec = clc.classify_edge("2", root, "1")

    assert rec["citations"][0]["bound_to_fallback"] is True
    assert rec["citations"][0]["bound_to_trigger"] is True
    assert rec["citations"][0]["resolved"] is False
    assert rec["class"] == "DECLARED_ONLY"


@pytest.mark.parametrize("guarded_body", [
    """decision = _repair_dec.decide()
if not decision['repair_needed']:
    _run_postroute_timing_repair()
    _measure_postrepair_mcorner_ocv()
""",
    """decision = _repair_dec.decide()
if decision['repair_needed']:
    pass
else:
    _run_postroute_timing_repair()
    _measure_postrepair_mcorner_ocv()
""",
    """decision = _repair_dec.decide()
decision = {'repair_needed': True}
if decision['repair_needed']:
    _run_postroute_timing_repair()
    _measure_postrepair_mcorner_ocv()
""",
    """decision = _repair_dec.decide()
decision.update({'repair_needed': False})
if decision['repair_needed']:
    _run_postroute_timing_repair()
    _measure_postrepair_mcorner_ocv()
""",
    """decision = _repair_dec.decide()
alias = decision
alias['repair_needed'] = False
if decision['repair_needed']:
    _run_postroute_timing_repair()
    _measure_postrepair_mcorner_ocv()
""",
    """decision = _repair_dec.decide()
if True or decision['repair_needed']:
    _run_postroute_timing_repair()
    _measure_postrepair_mcorner_ocv()
""",
    """decision = _repair_dec.decide()
return
if decision['repair_needed']:
    _run_postroute_timing_repair()
    _measure_postrepair_mcorner_ocv()
""",
], ids=("inverted", "wrong-else", "overwritten", "method-mutation",
        "alias-mutation", "complex-or", "after-return"))
def test_wrong_or_unreachable_trigger_branch_cannot_claim_execution(
        tmp_path, guarded_body):
    root = tmp_path / "guard_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              + textwrap.indent(guarded_body, "    "))
    compile(source, "<guard-control>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert rec["citations"][0]["bound_to_fallback"] is True
        assert rec["citations"][0]["bound_to_trigger"] is True
        assert rec["citations"][0]["resolved"] is False
        assert rec["class"] == "DECLARED_ONLY"


@pytest.mark.parametrize("terminator", [
    "break", "continue", "return", "raise RuntimeError('stop')",
])
def test_fallback_after_a_terminator_is_not_live(
        tmp_path, terminator):
    root = tmp_path / "terminator_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              "        if sr:\n"
              "            break\n"
              f"        {terminator}\n"
              "        step_rtl_gen()\n"
              "        step_reference_tb()\n")
    compile(source, "<terminator-control>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is False
    assert rec["class"] == "DECLARED_ONLY"


def test_overwriting_the_loop_trigger_receipt_breaks_the_proof(tmp_path):
    root = tmp_path / "overwrite_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              "        sr = object()\n"
              "        if sr:\n"
              "            break\n"
              "        step_rtl_gen()\n"
              "        step_reference_tb()\n")
    compile(source, "<overwrite-control>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is False
    assert rec["class"] == "DECLARED_ONLY"


def test_deleting_the_loop_trigger_field_breaks_the_proof(tmp_path):
    root = tmp_path / "delete_loop_receipt_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              "        del sr.status\n"
              "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            break\n"
              "        step_rtl_gen()\n"
              "        step_reference_tb()\n")
    compile(source, "<delete-loop-receipt>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is False
    assert rec["class"] == "DECLARED_ONLY"


@pytest.mark.parametrize("guard", [
    "if sr.status == 'FAIL':\n            break",
    "if (sr := True):\n            break",
])
def test_inverted_or_overwritten_loop_guard_cannot_claim_execution(
        tmp_path, guard):
    root = tmp_path / "loop_polarity_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              + textwrap.indent(guard, "        ") + "\n"
              "        step_rtl_gen()\n"
              "        step_reference_tb()\n")
    compile(source, "<loop-polarity-control>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is False
    assert rec["class"] == "DECLARED_ONLY"


def test_statically_true_or_sibling_makes_loop_fallback_unreachable(tmp_path):
    """A terminal-set spelling is not enough when another arm always exits."""
    root = tmp_path / "constant_true_guard_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              "        if (sr.status in ('PASS', 'SKIP', 'WAIVED') "
              "or 1 == 1):\n"
              "            break\n"
              "        step_rtl_gen()\n"
              "        step_reference_tb()\n")
    compile(source, "<constant-true-loop-guard>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is False
    assert rec["class"] == "DECLARED_ONLY"


@pytest.mark.parametrize("barrier", [
    "while True:\n            pass",
    "assert False",
], ids=("infinite-loop", "assert-false"))
def test_provably_nonreturning_barrier_makes_loop_fallback_unreachable(
        tmp_path, barrier):
    root = tmp_path / "nonreturning_loop_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            break\n"
              + textwrap.indent(barrier, "        ") + "\n"
              "        step_rtl_gen()\n"
              "        step_reference_tb()\n")
    compile(source, "<nonreturning-loop-barrier>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is False
    assert rec["class"] == "DECLARED_ONLY"


def test_loop_fallback_cannot_hide_under_the_terminal_predicate(tmp_path):
    root = tmp_path / "contradictory_loop_actuator_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            break\n"
              "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            step_rtl_gen()\n"
              "            step_reference_tb()\n"
              "        break\n")
    compile(source, "<contradictory-loop-actuator>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is False
    assert rec["class"] == "DECLARED_ONLY"


def test_loop_fact_cannot_survive_receipt_mutation_after_the_guard(tmp_path):
    root = tmp_path / "stale_loop_fact_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            break\n"
              "        sr.status = 'PASS'\n"
              "        if sr.status not in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            step_rtl_gen()\n"
              "            step_reference_tb()\n"
              "        break\n")
    compile(source, "<stale-loop-fact>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is False
    assert rec["class"] == "DECLARED_ONLY"


def test_loop_remeasurement_cannot_hide_under_the_terminal_predicate(tmp_path):
    root = tmp_path / "contradictory_loop_measure_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            break\n"
              "        step_rtl_gen()\n"
              "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            step_reference_tb()\n"
              "        break\n")
    compile(source, "<contradictory-loop-measurement>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is True
    assert rec["citations"][1]["resolved"] is False
    assert rec["class"] == "EXECUTABLE"


def test_loop_backedge_obeys_the_known_trigger_complement(tmp_path):
    root = tmp_path / "fact_owned_backedge_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            break\n"
              "        step_rtl_gen()\n"
              "        if sr.status not in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            break\n")
    compile(source, "<fact-owned-backedge>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is True
    assert rec["citations"][1]["resolved"] is False
    assert rec["class"] == "EXECUTABLE"


@pytest.mark.parametrize("items, expected", [
    ("()", "DECLARED_ONLY"),
    ("(1,)", "REMEASURED"),
])
def test_literal_for_loop_must_actually_iterate(tmp_path, items, expected):
    root = tmp_path / f"literal_for_{expected.lower()}"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              f"    for _ in {items}:\n"
              "        sr = step_reference_tb()\n"
              "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            break\n"
              "        step_rtl_gen()\n"
              "        step_reference_tb()\n")
    compile(source, "<literal-for-loop>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["class"] == expected


def test_loop_remeasurement_requires_a_post_fallback_path(tmp_path):
    root = tmp_path / "no_loop_remeasure_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            break\n"
              "        step_rtl_gen()\n"
              "        break\n")
    compile(source, "<no-loop-remeasure>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is True
    assert rec["citations"][1]["resolved"] is False
    assert rec["class"] == "EXECUTABLE"


def test_nested_fallback_that_breaks_cannot_borrow_another_paths_backedge(
        tmp_path):
    """Only paths that execute the actuator may supply remeasurement."""
    root = tmp_path / "conditional_break_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            break\n"
              "        if should_retry:\n"
              "            step_rtl_gen()\n"
              "            break\n")
    compile(source, "<conditional-break-loop>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert rec["citations"][0]["resolved"] is True
    assert rec["citations"][1]["resolved"] is False
    assert rec["class"] == "EXECUTABLE"


def test_loop_backedge_is_a_real_post_fallback_remeasurement(tmp_path):
    root = tmp_path / "loop_backedge_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "def main():\n"
              "    while True:\n"
              "        sr = step_reference_tb()\n"
              "        if sr.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "            break\n"
              "        step_rtl_gen()\n")
    compile(source, "<loop-backedge-remeasure>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")

    assert all(c["resolved"] for c in rec["citations"])
    assert rec["class"] == "REMEASURED"


def test_guarded_remeasurement_must_follow_the_fallback(tmp_path):
    root = tmp_path / "guarded_order_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    if decision['repair_needed']:\n"
              "        _measure_postrepair_mcorner_ocv()\n"
              "        _run_postroute_timing_repair()\n")
    compile(source, "<guarded-order-control>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert rec["citations"][0]["resolved"] is True
        assert rec["citations"][1]["resolved"] is False
        assert rec["class"] == "EXECUTABLE"


def test_guarded_remeasurement_cannot_come_from_mutually_exclusive_branch(
        tmp_path):
    root = tmp_path / "guarded_exclusive_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    if decision['repair_needed']:\n"
              "        if do_repair:\n"
              "            _run_postroute_timing_repair()\n"
              "        else:\n"
              "            _measure_postrepair_mcorner_ocv()\n")
    compile(source, "<guarded-exclusive-paths>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert rec["citations"][0]["resolved"] is True
        assert rec["citations"][1]["resolved"] is False
        assert rec["class"] == "EXECUTABLE"


def test_sequential_complementary_guards_cannot_invent_a_shared_path(
        tmp_path):
    """Path facts must survive across sibling if statements."""
    root = tmp_path / "guarded_sequential_complement_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    if decision['repair_needed']:\n"
              "        if do_repair:\n"
              "            _run_postroute_timing_repair()\n"
              "        if not do_repair:\n"
              "            _measure_postrepair_mcorner_ocv()\n")
    compile(source, "<guarded-sequential-complement>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert rec["citations"][0]["resolved"] is True
        assert rec["citations"][1]["resolved"] is False
        assert rec["class"] == "EXECUTABLE"


@pytest.mark.parametrize("body", [
    """        if options.do_repair:
            _run_postroute_timing_repair()
        if not options.do_repair:
            _measure_postrepair_mcorner_ocv()
""",
    """        if do_repair and enabled:
            _run_postroute_timing_repair()
        if not do_repair:
            _measure_postrepair_mcorner_ocv()
""",
    """        if do_repair:
            _run_postroute_timing_repair()
        do_repair = False
        if do_repair:
            _measure_postrepair_mcorner_ocv()
""",
    """        if mode == 'repair':
            _run_postroute_timing_repair()
        if mode != 'repair':
            _measure_postrepair_mcorner_ocv()
""",
    """        if not (do_repair and enabled):
            _run_postroute_timing_repair()
        if do_repair and enabled:
            _measure_postrepair_mcorner_ocv()
""",
    """        if do_repair or enabled:
            _run_postroute_timing_repair()
        if not (do_repair or enabled):
            _measure_postrepair_mcorner_ocv()
""",
    """        alias = do_repair
        if alias:
            _run_postroute_timing_repair()
        if not do_repair:
            _measure_postrepair_mcorner_ocv()
""",
    """        if do_repair:
            _run_postroute_timing_repair()
        do_repair |= True
        if not do_repair:
            _measure_postrepair_mcorner_ocv()
""",
])
def test_correlated_predicates_cannot_invent_remeasurement(tmp_path, body):
    """Attribute, short-circuit, and assignment facts remain path-specific."""
    root = tmp_path / "guarded_correlated_predicate_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    if decision['repair_needed']:\n"
              + body)
    compile(source, "<guarded-correlated-predicate>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert rec["citations"][0]["resolved"] is True
        assert rec["citations"][1]["resolved"] is False
        assert rec["class"] == "EXECUTABLE"


@pytest.mark.parametrize("body", [
    """        if do_repair:
            _run_postroute_timing_repair()
        do_repair = False
        if not do_repair:
            _measure_postrepair_mcorner_ocv()
""",
    """        if do_repair or enabled:
            _run_postroute_timing_repair()
        if not do_repair:
            _measure_postrepair_mcorner_ocv()
""",
    """        if mode == 'repair':
            _run_postroute_timing_repair()
        if mode == 'repair':
            _measure_postrepair_mcorner_ocv()
""",
    """        alias = do_repair
        if alias:
            _run_postroute_timing_repair()
        if do_repair:
            _measure_postrepair_mcorner_ocv()
""",
    """        if do_repair:
            _run_postroute_timing_repair()
        do_repair |= True
        if do_repair:
            _measure_postrepair_mcorner_ocv()
""",
])
def test_a_real_correlated_path_is_not_falsely_demoted(tmp_path, body):
    """The predicate proof rejects impossible paths without banning real ones."""
    root = tmp_path / "guarded_real_correlated_path_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    if decision['repair_needed']:\n"
              + body)
    compile(source, "<guarded-real-correlated-path>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert all(citation["resolved"] for citation in rec["citations"])
        assert rec["class"] == "REMEASURED"


@pytest.mark.parametrize("wrapper", [
    "class Decoy:\n"
    "    def step_canonicalize_artefacts(self):\n"
    "        decision = _repair_dec.decide()\n"
    "        if decision['repair_needed']:\n"
    "            _run_postroute_timing_repair()\n"
    "            _measure_postrepair_mcorner_ocv()\n",
    "def unrelated_outer():\n"
    "    def step_canonicalize_artefacts():\n"
    "        decision = _repair_dec.decide()\n"
    "        if decision['repair_needed']:\n"
    "            _run_postroute_timing_repair()\n"
    "            _measure_postrepair_mcorner_ocv()\n",
])
def test_guarded_caller_must_be_a_module_entrypoint(tmp_path, wrapper):
    """A class/nested namesake is not the cited runner entrypoint."""
    root = tmp_path / "guarded_caller_decoy_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              + wrapper)
    compile(source, "<guarded-caller-decoy>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert not any(citation["resolved"] for citation in rec["citations"])
        assert rec["class"] == "DECLARED_ONLY"


def test_loop_caller_must_be_a_module_entrypoint(tmp_path):
    """A class method named main cannot stand in for the runner's main()."""
    root = tmp_path / "loop_caller_decoy_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("def step_reference_tb(): ...\n"
              "def step_rtl_gen(): ...\n"
              "class Decoy:\n"
              "    def main(self):\n"
              "        while True:\n"
              "            result = step_reference_tb()\n"
              "            if result.status in ('PASS', 'SKIP', 'WAIVED'):\n"
              "                break\n"
              "            step_rtl_gen()\n"
              "            step_reference_tb()\n"
              "            break\n")
    compile(source, "<loop-caller-decoy>", "exec")
    (progs / "design_one_shot_runner.py").write_text(source)

    rec = clc.classify_edge("4", root, "1")
    assert not any(citation["resolved"] for citation in rec["citations"])
    assert rec["class"] == "DECLARED_ONLY"


def test_an_uncalled_nested_body_does_not_taint_the_trigger_receipt(tmp_path):
    """Definition-time evaluation excludes an uncalled helper body."""
    root = tmp_path / "guarded_nested_helper_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    if decision['repair_needed']:\n"
              "        def unused_helper():\n"
              "            decision['repair_needed'] = False\n"
              "        _run_postroute_timing_repair()\n"
              "        _measure_postrepair_mcorner_ocv()\n")
    compile(source, "<guarded-nested-helper>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert all(citation["resolved"] for citation in rec["citations"])
        assert rec["class"] == "REMEASURED"


def test_path_state_explosion_refuses_promotion(tmp_path):
    """The bounded proof fails closed before independent branches explode."""
    root = tmp_path / "guarded_state_budget_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    branches = "".join(
        f"        if independent_{index}:\n"
        "            pass\n"
        for index in range(10))
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    if decision['repair_needed']:\n"
              + branches
              + "        _run_postroute_timing_repair()\n"
              "        _measure_postrepair_mcorner_ocv()\n")
    compile(source, "<guarded-state-budget>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert rec["class"] == "DECLARED_ONLY"
        assert not any(citation["resolved"] for citation in rec["citations"])


def test_guarded_fallback_cannot_hide_under_the_opposite_trigger_value(
        tmp_path):
    root = tmp_path / "contradictory_guard_actuator_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    if decision['repair_needed']:\n"
              "        if not decision['repair_needed']:\n"
              "            _run_postroute_timing_repair()\n"
              "            _measure_postrepair_mcorner_ocv()\n")
    compile(source, "<contradictory-guard-actuator>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert rec["citations"][0]["resolved"] is False
        assert rec["class"] == "DECLARED_ONLY"


def test_guarded_fact_cannot_survive_receipt_mutation_inside_branch(tmp_path):
    root = tmp_path / "stale_guard_fact_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    if decision['repair_needed']:\n"
              "        decision['repair_needed'] = False\n"
              "        if decision['repair_needed']:\n"
              "            _run_postroute_timing_repair()\n"
              "            _measure_postrepair_mcorner_ocv()\n")
    compile(source, "<stale-guard-fact>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert rec["citations"][0]["resolved"] is False
        assert rec["class"] == "DECLARED_ONLY"


def test_guarded_known_false_dominates_an_and_sibling(tmp_path):
    root = tmp_path / "guarded_bool_fact_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    if decision['repair_needed']:\n"
              "        if not decision['repair_needed'] and unknown:\n"
              "            _run_postroute_timing_repair()\n"
              "            _measure_postrepair_mcorner_ocv()\n")
    compile(source, "<guarded-bool-fact>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert rec["citations"][0]["resolved"] is False
        assert rec["class"] == "DECLARED_ONLY"


def test_guarded_remeasurement_cannot_hide_under_opposite_trigger_value(
        tmp_path):
    root = tmp_path / "contradictory_guard_measure_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    if decision['repair_needed']:\n"
              "        _run_postroute_timing_repair()\n"
              "        if not decision['repair_needed']:\n"
              "            _measure_postrepair_mcorner_ocv()\n")
    compile(source, "<contradictory-guard-measurement>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert rec["citations"][0]["resolved"] is True
        assert rec["citations"][1]["resolved"] is False
        assert rec["class"] == "EXECUTABLE"


def test_deleting_guarded_trigger_field_breaks_the_proof(tmp_path):
    root = tmp_path / "delete_guard_receipt_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    del decision['repair_needed']\n"
              "    if decision['repair_needed']:\n"
              "        _run_postroute_timing_repair()\n"
              "        _measure_postrepair_mcorner_ocv()\n")
    compile(source, "<delete-guard-receipt>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert rec["citations"][0]["resolved"] is False
        assert rec["class"] == "DECLARED_ONLY"


@pytest.mark.parametrize("barrier", [
    "while True:\n            pass",
    "assert False",
], ids=("infinite-loop", "assert-false"))
def test_provably_nonreturning_barrier_makes_guarded_fallback_unreachable(
        tmp_path, barrier):
    root = tmp_path / "nonreturning_guard_root"
    progs = root / "programs"
    progs.mkdir(parents=True)
    source = ("class _Decision:\n"
              "    def decide(self): return {'repair_needed': True}\n"
              "_repair_dec = _Decision()\n"
              "def _run_postroute_timing_repair(): ...\n"
              "def _measure_postrepair_mcorner_ocv(): ...\n"
              "def step_canonicalize_artefacts():\n"
              "    decision = _repair_dec.decide()\n"
              "    if decision['repair_needed']:\n"
              + textwrap.indent(barrier, "        ") + "\n"
              "        _run_postroute_timing_repair()\n"
              "        _measure_postrepair_mcorner_ocv()\n")
    compile(source, "<nonreturning-guard-barrier>", "exec")
    (progs / "phase3_one_shot_runner.py").write_text(source)

    for step in ("23", "32"):
        rec = clc.classify_edge(step, root, "32")
        assert rec["citations"][0]["resolved"] is False
        assert rec["class"] == "DECLARED_ONLY"


def test_deleting_the_loop_around_the_actuator_demotes_the_edge(tmp_path):
    """The call survives; only the loop is gone. Structural citation, so red."""
    root = _mutant_root(tmp_path, loop=False, repair=True)
    _, rep = _report(tmp_path, "--root", str(root), expect=RC_FINDINGS)
    by = {e["step"]: e for e in rep["edges"]}
    assert by["4"]["class"] == "DECLARED_ONLY", by["4"]
    assert any(f["rule"] == "CLC-EVIDENCE-MISSING" and f["step"] == "4"
               for f in rep["findings"])
    # the paired green arm is test_the_stub_root_is_a_faithful_stand_in:
    # same stub root, `while` restored, edge 4 back to REMEASURED.
    assert by["23"]["class"] == "REMEASURED", "only edge 4 should have moved"


def test_deleting_the_repair_actuator_demotes_both_edges_that_share_it(tmp_path):
    root = _mutant_root(tmp_path, loop=True, repair=False)
    _, rep = _report(tmp_path, "--root", str(root), expect=RC_FINDINGS)
    by = {e["step"]: e for e in rep["edges"]}
    assert by["23"]["class"] == "DECLARED_ONLY"
    assert by["32"]["class"] == "DECLARED_ONLY"
    assert {f["step"] for f in rep["findings"]
            if f["rule"] == "CLC-EVIDENCE-MISSING"} == {"23", "32"}


def test_the_repair_log_arm_can_fire(tmp_path):
    """POSITIVE CONTROL for the project scan.

    A tree whose `repair_log.json` says REPAIR_APPLIED + re_verified is presenting the
    step-32 loop as converged. Against the real tree that edge is REMEASURED and
    the claim stands; against a root where the actuator is gone the SAME tree is
    refused. Two arms differing only in the root, so the scan cannot be dead.
    """
    proj = tmp_path / "proj"
    repair = proj / "phase3" / "stage3" / "postroute_timing_repair"
    repair.mkdir(parents=True)
    (repair / "repair_log.json").write_text(json.dumps(
        {"verdict": "REPAIR_APPLIED", "re_verified": True,
         "affected_steps": [21]}))

    _, green = _report(tmp_path, str(proj), expect=RC_OK)
    assert green["claim_audit"] == "CHECKED"
    assert green["claims_examined"] == 1
    assert green["claims"][0]["step"] == "32"

    root = _mutant_root(tmp_path, loop=True, repair=False)
    _, red = _report(tmp_path, str(proj), "--root", str(root),
                     expect=RC_FINDINGS)
    assert any(f["rule"] == "CLC-DECLARED-ONLY-PRESENTED-AS-SUCCESS"
               and f["step"] == "32" for f in red["findings"])


def test_an_honest_repair_log_is_not_a_claim(tmp_path):
    """REPAIR_ATTEMPTED / a false `re_verified` are honest non-successes. Reading
    them as claims would make every failed repair a finding and the check useless."""
    proj = tmp_path / "proj2"
    repair = proj / "phase3" / "stage3" / "postroute_timing_repair"
    repair.mkdir(parents=True)
    (repair / "repair_log.json").write_text(json.dumps(
        {"verdict": "REPAIR_ATTEMPTED", "re_verified": False}))
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
