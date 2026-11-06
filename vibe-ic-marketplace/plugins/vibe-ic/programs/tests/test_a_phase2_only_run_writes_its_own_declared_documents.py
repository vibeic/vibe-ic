"""A PHASE-2-ONLY run executes the producers ITS OWN flow declares.

MEASURED on subservient x gf180mcuD, the same design and the same input twice.

  r46 (`_lane_icsub2/c22_proj`) ran phase 3, so it reached the ONE site that
      invoked `flow_declared_producer_run` — `phase3_one_shot_runner`. Its
      `reports/audit/flow_declared_producer_run.json` exists, verdict PRODUCED,
      and its `results` names `reports/phase1/gates/stage_phase1_compliance.json`
      for step "2". Step 2 read `OUTPUT ATTRIBUTION: step-attributed (4/4 ...)`
      with no `audit_created` code, and phase 2 reached PASS_WITH_WAIVERS.

  r47 (`_lane_icsub2/c23_proj`) halted in phase 2, so that file does not exist
      at all. Step 2 read::

        SELF-CERTIFIED EVIDENCE EXCLUDED (audit_created)
          ['reports/phase1/gates/stage_phase1_compliance.json']
        AUDIT-CREATED OUTPUT REFUSED ... PRODUCER GAP: no pre-audit producer
          supplied these paths; wire them into the owning runner

      and was booked FAIL / missing_artefact, which voided step 4's 10/10 L10
      oracles as `dependency [2] = FAIL` and put every digital IC on the IC path
      behind it.

THE AUDITOR IS RIGHT TO REFUSE. A run executing the producers its own flow
declares is what a flow does; an auditor executing them and then grading its own
output is self-certification. So the gap was never in the refusal — it was that
NOTHING in a phase-2-only run executed the producer.

THE BISECT HAS A NEGATIVE ANSWER, and this file records it so the next reader
does not go looking for a regression. `git log -S'flow_declared_producer_run' --
design_one_shot_runner.py` is EMPTY FOR ALL HISTORY: the phase-2 runner never
invoked it. Both the mechanism (f119083ec) and step 2's `programs:` declaration
(11bd3c487) are ANCESTORS of r46's tree a8c7a3e74 — they already existed then —
and at a8c7a3e74 the invocation counts are identical to main
(design_one_shot_runner 0, phase3_one_shot_runner 5). The differing variable
between r46 and r47 was THE PHASE THE RUN REACHED, not a landing.

MEASURED AFTER THE FIX, on a fresh copy of the pristine r47 project:
  the producer pass reports `29 declared producer clause(s); 28 already produced
  by the run, 1 owed, 1 executed` — the one owed being exactly our path — and
  then step 2 FAIL/missing_artefact -> **PASS** (12 reasons -> 9, the two
  audit_created lines gone and the attribution line's `codes=['audit_created']`
  gone with them) and step 4 NOT_MEASURED/upstream_failed -> **PASS**, its two
  "PASS voided: dependency [2] = FAIL" lines removed.

chip-AGNOSTIC: every population here is recomputed from the shipped yaml and the
shipped runner sources; nothing is tabulated from a chip.
"""
from __future__ import annotations

import ast
import json
import subprocess  # nosec B404 — declared flow programs
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

FLOW_YAML = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
PHASE2_RUNNER = PROGRAMS / "design_one_shot_runner.py"
PHASE3_RUNNER = PROGRAMS / "phase3_one_shot_runner.py"
PRODUCER = "flow_declared_producer_run"

#: The document r47 lost was `reports/phase1/gates/stage_phase1_compliance.json`, and the
#: tests below used step 2's clause for it as their example of a declared producer
#: clause. That clause is GONE (2026-09-24, R-0915-141, the step-38 half, lane ictier1 (spm run23: "AUDIT-CREATED OUTPUT REFUSED: ['reports/phase1/gates/stage_phase1_compliance.json']")): the path is the nested clause's own verdict
#: target and left step 2's declared set, so no producer is owed for it at all. The
#: mechanism these tests pin is unchanged, and they now read it through step 2's OTHER
#: declared producer clause -- same step, same phase-2-only run, a run document.
OWED_TARGET = "reports/phase2/lint/rtl_hygiene.json"
OWED_STEP = "2"
OWED_PROGRAM = "rtl_hygiene_lint"




# --------------------------------------------------------------------------- #
# (1) the wiring: the phase-2 runner invokes the producer, BEFORE the audit
# --------------------------------------------------------------------------- #
def test_the_phase2_runner_invokes_the_declared_producer_pass():
    """RED before this change: 0 occurrences in this file, for all history."""
    src = PHASE2_RUNNER.read_text()
    assert f"{PRODUCER}.py" in src, (
        "the phase-2 runner does not invoke the declared-producer pass, so a "
        "phase-2-only run leaves its declared documents to the audit")


def test_the_producer_pass_runs_BEFORE_the_final_audit():
    """Order is the whole point: the audit is what READS these documents, so a
    pass that ran after it would change nothing this run is graded on."""
    tree = ast.parse(PHASE2_RUNNER.read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "main")
    calls = [n.func.id for n in ast.walk(main) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)]
    assert calls.count("_audit_after_declared_producers") == 1
    assert "step_final_audit" not in calls  # no second audit before the pass

    import design_one_shot_runner as runner
    # The actual producer runs on an empty scratch project and writes its
    # ZERO_POPULATION receipt with rc=2. The audit callback observes the file
    # on disk; its return is only a controlled step verdict for this test.
    with pytest.MonkeyPatch.context() as mp:
        seen = []
        def audit(project, phase, skip_analog):
            receipt = project / "reports/audit/flow_declared_producer_run.json"
            seen.append(json.loads(receipt.read_text())["verdict"])
            assert phase == 2 and skip_analog is True
            return runner.StepResult("final_audit", "PASS")
        mp.setattr(runner, "step_final_audit", audit)
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            result = runner._audit_after_declared_producers(Path(directory), True)
    assert seen == ["ZERO_POPULATION"]
    assert result.name == "final_audit" and result.status == "PASS"


def test_the_pass_is_recorded_not_gating(tmp_path, monkeypatch, capsys):
    """It never decides a verdict: the step gates re-run these programs and keep
    their own. The real producer's empty-population rc=2 is reported, then the
    audit still runs and owns the returned verdict."""
    import design_one_shot_runner as runner
    seen = []
    def audit(project, phase, skip_analog):
        seen.append(json.loads((project / "reports/audit/flow_declared_producer_run.json")
                               .read_text())["verdict"])
        return runner.StepResult("final_audit", "PASS")
    monkeypatch.setattr(runner, "step_final_audit", audit)
    result = runner._audit_after_declared_producers(tmp_path, False)
    assert seen == ["ZERO_POPULATION"]
    assert "flow_declared_producer_run rc=2" in capsys.readouterr().err
    assert result.name == "final_audit" and result.status == "PASS"


# --------------------------------------------------------------------------- #
# (2) the other direction: a target with no DECLARED producer is still refused
# --------------------------------------------------------------------------- #






# --------------------------------------------------------------------------- #
# (3) the phase-3 site is untouched
# --------------------------------------------------------------------------- #
def test_the_phase3_site_is_unchanged():
    """This change ADDS a caller; it does not move the one that existed. The
    phase-3 runner must still invoke the pass, with the same guarantees."""
    src = PHASE3_RUNNER.read_text()
    assert src.count(f"{PRODUCER}.py") == 1
    i = src.index(f"{PRODUCER}.py")
    window = src[i - 1200:i + 1600]
    assert "check=False" in window and "must not abort" in window


def test_both_runners_invoke_it_the_same_way():
    """One shape, two callers. The argv, the timeout basis and the rc handling
    are compared as PARSED CALLS, not as text, so a reformat cannot pass and a
    changed argument cannot hide."""
    def _call(path: Path):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if PRODUCER not in ast.dump(node):
                continue
            kw = {k.arg for k in node.keywords}
            return kw
        return None
    two = _call(PHASE2_RUNNER)
    three = _call(PHASE3_RUNNER)
    assert two is not None and three is not None
    assert two == three == {"timeout", "check", "capture_output", "text"}


# --------------------------------------------------------------------------- #
# (4) the r48 receipt: producing the document is NECESSARY, NOT SUFFICIENT
# --------------------------------------------------------------------------- #
# MEASURED on r48 (a fresh front-door run on v1.22.29, `_lane_icsub2/c24_proj`),
# which is a DIFFERENT project state from r47 and shows the boundary of this fix.
# There the strict stage_phase1 invocation the producer executes returns rc=1
# with its own `overall: NOT_MEASURED`, because step D1 is NOT_MEASURED, because
# `phase1_expert_parse_track . --check-report` exits 4 AWAITING: its report
# records `execution.disposition == "AWAITING"` and
# `awaiting.action == "invoke subagent vibe-ic:ic-expert-agent on <pack>, then
# re-run this track to consume its answer"` — a second pass only an AGENT can
# make, which that run did not make. On r47 the same gate was PASS, which is why
# r47 reaches step 2 PASS and r48 does not. That is a RUN-SHAPE difference, not a
# plugin defect, and not something a producer wiring can close.
#
# So this fix is measured at BOTH projects and claimed at neither more than it
# earns:
#   r47  step 2 FAIL/missing_artefact -> PASS            step 4 NOT_MEASURED -> PASS
#   r48  step 2 FAIL/missing_artefact -> NOT_MEASURED/partial_population
#        (step 4 fails on its own oracle gate there, 1/10 — not this change's)
# In both, what my change removes is the same pair of audit_created lines; what
# it never claims to remove is a document whose own verdict is NOT_MEASURED.


def test_a_NOT_MEASURED_stage_document_does_not_buy_the_step_a_PASS():
    """The other half of the r48 receipt, and the negative control on this fix.
    Once the run produces the document, the step is graded on what the document
    SAYS. A stage-compliance run whose own `overall` is NOT_MEASURED is booked on
    a class that is NOT skip-eligible, so the step lands on the INCOMPLETE tier —
    never on a silent PASS bought by the mere existence of a file."""
    import _flow_reason_taxonomy as RT  # noqa: PLC0415
    measured = ("flow_compliance_check . --stage-id stage_phase1 --strict "
                "--json reports/phase1/gates/stage_phase1_compliance.json "
                "--skip-analog [verdict=NOT_MEASURED, "
                "reason_class=EXECUTION_ERROR]")
    got = RT.infer_nonverdict_reason(verdict="NOT_MEASURED", message=measured)
    assert got not in RT.SKIP_ELIGIBLE, got
    assert RT.record_verdict(got) in ("INCOMPLETE", "BLOCKED")
    # and the two tiers the P0 umbrella can give such a step are both non-green
    assert RT.p0_tier_for_reason_classes([got]) == "INCOMPLETE"
