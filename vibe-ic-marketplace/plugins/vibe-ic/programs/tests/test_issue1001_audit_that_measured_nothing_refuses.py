#!/usr/bin/env python3
"""vibe-ic#1001 — a completion audit that measured NOTHING must not claim a FAIL.

WHAT THIS PINS
==============
`phase23_completion_audit.json::verdict` is the ONE field every content-reading
consumer keys on — `step_internal_fail_bubble_up_check` walks
`reports/**/*.json` for exactly that key and reads a `FAIL` in it as "a
step-internal gate found a defect in this design".

MEASURED at the branch base: point `flow_compliance_check.py` at a directory
holding no design at all and it writes `verdict: FAIL` while recording
`invoked_gate_count: 0` (of 246 registered), `step_counts` PASS 0 / FAIL 0, and
EMPTY structural / step-artifact failure-line lists — with its own stdout
saying ``GATE EXECUTION LEDGER: no program gate was invoked in this run``.
Nothing ran, nothing was decided, and the artefact asserted a finding anyway.

THE ASYMMETRY THIS FILE IS BUILT AROUND (§4.05)
==============================================
Making an audit refuse is a guard-RELAXING change, so the positive case is the
CHEAP half and the NEGATIVE no-leak proof is the load-bearing one. A refusal
that is one conjunct too wide would silence a real step-internal FAIL — the
exact defect the Step-36 gate exists to catch. So every negative below sits
JUST OUTSIDE the refusal boundary: it is the measured-nothing shape with
EXACTLY ONE axis carrying a numerator, and each must still FAIL.

The second load-bearing property is that refusing is not passing: the
end-to-end test asserts the process still exits 1 and the artefact still
carries the run's own `FAIL` in `run_status`.

Chip-AGNOSTIC and version-less: the unit tests are pure counts, and the
end-to-end fixture is an EMPTY directory — no design, no PDK, no tool, no
vendor, no process token anywhere.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as F  # noqa: E402

CHECKER = PROGRAMS / "flow_compliance_check.py"

#: Bounds for the process launches below. NOT round numbers picked by feel:
#: `ci_harness_timeout_ceiling_check` (BLOCKING) resolves the pytest harness
#: bound from `tools/gatekeeper-land.sh` — `--timeout=180`,
#: `--timeout-method=thread` — and permits any ONE blocking call at most
#: `180 // 3` = 60 s. The landed values were 1800 and 300, both ABOVE that, so
#: neither could ever fire: pytest reaches 180 s first and the thread method
#: takes the whole SESSION down instead of the test, which produces no verdict
#: at all rather than a red one.
#:
#: 1800 s was never this file's cost. It is the bound a `flow_compliance_check`
#: run against a REAL design needs; both fixtures here are a design-LESS tree
#: (an empty directory, and a directory holding one 20-byte report), which is
#: the whole point of the file. MEASURED, three runs each: the empty-project
#: run is 0.33/0.31/0.32 s, the wrong-root run is 0.32/0.32/0.32 s, and
#: `step_internal_fail_bubble_up_check` is 0.02/0.03/0.02 s.
#:
#: TWO values, because the divisor counts CALLS PER TEST, not calls per file:
_ONE_CALL_S = 60      #: a test whose only bounded call is this one — the ceiling.
_THREE_CALL_S = 30    #: `…is_no_longer_read_as_a_step_internal_fail` makes THREE
#: bounded calls in one test function. 3 x 60 = 180 s is exactly the harness
#: bound, which leaves it nothing to report with — the two-call shape is the most
#: the `// 3` divisor was measured to cover. 3 x 30 = 90 s keeps half the budget
#: in reserve, and is still ~90x the 0.32 s worst case measured above.

#: The measured-nothing shape, as recorded by a run against a design-less tree.
NOTHING = dict(
    overall="FAIL",
    invoked_gate_count=0,
    step_counts={"PASS": 0, "FAIL": 0, "MISSING": 40, "SKIPPED-CONDITION": 23},
    structural_fail_lines=[],
    step_artifact_fail_lines=[],
    registered_gate_count=246,
)


def _verdict(**over):
    kw = dict(NOTHING)
    kw.update(over)
    return F.completion_audit_verdict(**kw)


# ── POSITIVE: the real shape refuses ──────────────────────────────────────
def test_an_audit_that_invoked_no_gate_and_decided_no_step_refuses():
    verdict, reason = _verdict()
    assert verdict == "INSUFFICIENT_DATA", (verdict, reason)
    assert reason, "a refusal with no stated reason is not a disclosure"


def test_the_refusal_discloses_its_denominator():
    """House rule: a verdict must say how much it looked at."""
    _, reason = _verdict()
    assert "246 registered" in reason, reason
    assert "0 step(s) were decided" in reason, reason


def test_the_refusal_says_the_run_is_still_failing():
    """Refusing narrows what the AUDIT claims, never what the RUN is."""
    _, reason = _verdict()
    assert "FAIL" in reason and "not passing" in reason, reason


def test_an_unresolved_registered_population_still_states_what_it_had():
    _, reason = _verdict(registered_gate_count=None)
    assert "unresolved registered-gate population" in reason, reason


# ── NEGATIVE NO-LEAK: one numerator on ANY axis and the FAIL stands ───────
# Each fixture is the measured-nothing shape with EXACTLY ONE axis moved.
@pytest.mark.parametrize("label,over", [
    # A gate ran. Something WAS measured, so the FAIL is a finding.
    ("one_gate_invoked", {"invoked_gate_count": 1}),
    # A step was decided as failing — the loudest possible numerator.
    ("one_step_failed",
     {"step_counts": {"PASS": 0, "FAIL": 1, "MISSING": 40}}),
    # A step was decided as passing: the audit read the design.
    ("one_step_passed",
     {"step_counts": {"PASS": 1, "FAIL": 0, "MISSING": 40}}),
    # Line-level evidence exists even though no gate reported a verdict.
    ("structural_line", {"structural_fail_lines": ["[9] some structural gate"]}),
    ("step_artifact_line",
     {"step_artifact_fail_lines": ["[21] declared output absent"]}),
    # NOT ASKED is not the same fact as ASKED-AND-NOTHING-ANSWERED.
    ("invoked_count_unknown", {"invoked_gate_count": None}),
])
def test_the_refusal_does_not_leak(label, over):
    verdict, reason = _verdict(**over)
    assert verdict == "FAIL", f"{label} leaked through the refusal: {verdict}"
    assert reason is None, f"{label} carried a refusal reason: {reason}"


def test_a_passing_run_is_never_rewritten():
    """The refusal is scoped to FAIL; it can never touch a green verdict."""
    for green in ("PASS", "PASS_WITH_WAIVERS",
                  "PASS_WITH_OPEN_SOURCE_CONSTRAINTS"):
        verdict, reason = _verdict(overall=green)
        assert (verdict, reason) == (green, None), (green, verdict, reason)


# ── END TO END: the wiring, and that refusing is not passing ─────────────
def test_empty_project_refuses_in_the_artefact_and_still_exits_1(tmp_path):
    """The measured-nothing shape, produced rather than asserted.

    An EMPTY directory is the smallest possible instance of "the audit was
    pointed somewhere with no design in it" — the same condition a wrong-root
    invocation produces. It must refuse in the artefact and STILL exit 1.
    """
    proj = tmp_path / "no_design_here"
    proj.mkdir()
    r = subprocess.run(
        [sys.executable, str(CHECKER), ".", "--phase", "all"],
        cwd=proj, capture_output=True, text=True, timeout=_ONE_CALL_S)
    assert r.returncode == 1, (
        "refusing is not passing — the run must stay red "
        f"(rc={r.returncode})\n{r.stdout[-2000:]}")
    audit = json.loads(
        (proj / "reports" / "audit"
         / "phase23_completion_audit.json").read_text(encoding="utf-8"))
    assert audit["invoked_gate_count"] == 0, audit["invoked_gate_count"]
    assert audit["step_counts"]["PASS"] == 0
    assert audit["step_counts"]["FAIL"] == 0
    assert audit["verdict"] == "INSUFFICIENT_DATA", audit["verdict"]
    assert audit["verdict_refusal_reason"], audit
    # The run's own status is untouched and still visible in the artefact.
    assert audit["run_status"] == "FAIL", audit["run_status"]


def test_the_refused_artefact_is_no_longer_read_as_a_step_internal_fail(
        tmp_path):
    """The cascade this fix exists to stop, DRIVEN rather than asserted.

    The published instance reaches a consumer because the audit was invoked
    from INSIDE the run's own `reports/` directory: the artefact then lands at
    `reports/reports/audit/…`, which `step_internal_fail_bubble_up_check` does
    NOT exclude (it excludes `reports/audit/`), so the measured-nothing FAIL is
    read as a leaf step report. This reproduces exactly that shape.

    The clean `verdict: PASS` report is load-bearing twice: it gives the gate a
    real denominator to disclose (a design-less tree would otherwise make it
    refuse at rc 2, which proves nothing about this fix), and it proves the
    rc 0 below is a real PASS over a real population rather than an empty one.
    """
    proj = tmp_path / "run_root"
    (proj / "reports" / "phase2").mkdir(parents=True)
    (proj / "reports" / "phase2" / "clean_gate.json").write_text(
        json.dumps({"verdict": "PASS"}) + "\n", encoding="utf-8")

    # The wrong-root invocation, verbatim: cwd is the run's own reports/ dir.
    subprocess.run([sys.executable, str(CHECKER), ".", "--phase", "all"],
                   cwd=proj / "reports", capture_output=True, text=True,
                   timeout=_THREE_CALL_S)
    nested = (proj / "reports" / "reports" / "audit"
              / "phase23_completion_audit.json")
    assert nested.is_file(), "fixture did not reproduce the wrong-root shape"
    assert json.loads(nested.read_text())["verdict"] == "INSUFFICIENT_DATA"

    gate = PROGRAMS / "step_internal_fail_bubble_up_check.py"
    r = subprocess.run([sys.executable, str(gate), str(proj)],
                       capture_output=True, text=True, timeout=_THREE_CALL_S)
    assert r.returncode == 0, (
        "a refused audit must not read as an unacknowledged step-internal "
        f"FAIL\n{r.stdout}\n{r.stderr}")
    assert "report(s) examined" in r.stdout, (
        "the PASS must disclose its denominator", r.stdout)

    # NEGATIVE, same tree: a genuine step-internal FAIL is still caught.
    (proj / "reports" / "phase2" / "broken_gate.json").write_text(
        json.dumps({"verdict": "FAIL"}) + "\n", encoding="utf-8")
    r2 = subprocess.run([sys.executable, str(gate), str(proj)],
                        capture_output=True, text=True, timeout=_THREE_CALL_S)
    assert r2.returncode == 1, (
        "the refusal must not silence a real step-internal FAIL in the same "
        f"tree\n{r2.stdout}\n{r2.stderr}")
