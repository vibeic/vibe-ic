#!/usr/bin/env python3
"""test_issue2068_budget_exhausted_no_verdict_is_non_waivable.py

#2068. A step whose declared budget ran out while it decided NOTHING was being
credited as a waiver, and the IC came out PASS_WITH_WAIVERS on it.

MEASURED (lane rbaes2, opentitan_aes, 8HD-8, EDA image 0.3.46): step 13's LEC
ran 8553.69 s against a 7200 s step budget, proved 830 of 4072 miter points,
established no base case, recorded no counterexample, and was written
`step_budget_exhausted: true, exhausted_resource: "wall_clock_seconds"` with
`verdict: INCONCLUSIVE`. `lec_equivalence_check` mapped INCONCLUSIVE onto rc=3 +
the `PASS_WITH_WAIVERS` sentinel, `flow_compliance_check` promoted step 13 to
WAIVED-DEFERRED, and the completion audit credited the slot.

A waiver is a decision to ACCEPT A KNOWN OUTCOME. Here there is no outcome:
not a pass, not a fail, not a capability gap whose shape is understood — a
measurement that did not finish. So budget-exhaustion-without-a-verdict is its
own terminal state, NOT_MEASURED, with the exhausted resource named, and it is
never waiver-eligible.

THE OTHER DIRECTION, and it is the half that constrains the fix: the budget is
a RECORDING ceiling (owner ruling on #2051) — it records and notifies, it never
kills. So a verdict reached PAST the budget is still a verdict and KEEPS its
tier; only the overrun is recorded. Nothing here shortens a budget, turns one
into a deadline, or adds a kill.

The fixture is that real record, carried in-line, so the test measures the state
that was actually observed rather than one composed to suit the fix.
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

import lec_equivalence_check as L  # noqa: E402
import flow_compliance_check as F  # noqa: E402


# The rbaes2 step-13 record, reduced to the fields this state is made of.
_RBAES2 = {
    "equivalent": False,
    "compared_points": 830,
    "miter_points": 4072,
    "non_equivalent_points": 0,
    "unproven_points": 3242,
    "verdict": "INCONCLUSIVE",
    "inconclusive": True,
    "non_convergence": True,
    "program": "lec_run",
    "elapsed_sec": 8551.3,
    "lec_attempts": 3,
    "step_budget_sec": 7200,
    "step_elapsed_sec": 8553.69,
    "step_budget_exhausted": True,
    "exhausted_resource": "wall_clock_seconds",
}


def _project(tmp_path: Path, **over) -> Path:
    doc = dict(_RBAES2)
    doc.update(over)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "lec.json").write_text(
        json.dumps(doc), encoding="utf-8")
    return tmp_path


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_PROGRAMS / "lec_equivalence_check.py"),
         str(project)],
        capture_output=True, text=True)


# ── direction 1: the measured record is refused, by name ───────────────────

def test_exhausted_budget_with_no_verdict_is_not_measured(tmp_path):
    res = L.audit(_project(tmp_path))
    assert res.not_measured is True, (
        "the rbaes2 record — budget exhausted, nothing decided — did not "
        "reach the NOT_MEASURED state")
    assert res.passed is False
    # NOT the waiver-eligible tier: that is the whole defect.
    assert res.inconclusive is False, (
        "the state is still INCONCLUSIVE, which is the tier that carries the "
        "rc=3 waiver sentinel — the slot can still be credited")
    assert res.exhausted_resource == "wall_clock_seconds", (
        "the exhausted resource is not named; NOT_MEASURED without naming "
        "what ran out is not a disclosure")
    assert any(f.rule == "LEC_BUDGET_EXHAUSTED" for f in res.findings)


def test_the_cli_refuses_by_name_and_prints_no_waiver_sentinel(tmp_path):
    r = _run(_project(tmp_path))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout[-600:]}"
    assert "LEC_BUDGET_EXHAUSTED" in r.stdout
    assert "wall_clock_seconds" in r.stdout
    # MEMBERSHIP, not a count: the waiver sentinel must not be printed at all,
    # because its presence is the entire promotion condition downstream.
    assert not any(line.lstrip().startswith("PASS_WITH_WAIVERS")
                   for line in r.stdout.splitlines()), (
        "the waiver sentinel is still printed — flow_compliance will promote "
        "this to WAIVED-DEFERRED and the completion audit will credit it")
    assert any(line.lstrip().startswith("NOT_MEASURED_NON_WAIVABLE")
               for line in r.stdout.splitlines()), (
        "the non-waivable token is missing or is not at line-start; the "
        "consumer reads only line-starts in the trailing stdout window")


# ── direction 2: a real verdict past the budget is UNTOUCHED ───────────────

def test_a_proof_reached_past_the_budget_keeps_its_pass(tmp_path):
    """The ceiling records; it never voids a verdict it did not stop."""
    p = _project(tmp_path, equivalent=True, inconclusive=False,
                 verdict="EQUIVALENT", unproven_points=0,
                 non_equivalent_points=0)
    res = L.audit(p)
    assert res.not_measured is False, (
        "a LEC that PROVED equivalence was called NOT_MEASURED because it "
        "ran past its budget — the ceiling killed a real verdict")
    assert res.passed is True, [f.rule for f in res.findings]
    assert res.budget_overrun.get("exhausted_resource") == "wall_clock_seconds", (
        "the overrun was not recorded — a ceiling that records nothing is "
        "not a ceiling")
    assert _run(p).returncode == 0


def test_a_counterexample_past_the_budget_stays_a_hard_fail(tmp_path):
    p = _project(tmp_path, non_equivalent_points=3)
    res = L.audit(p)
    assert res.not_measured is False, (
        "a recorded counterexample was laundered into NOT_MEASURED — a real "
        "non-equivalence must never become 'we did not measure it'")
    assert _run(p).returncode == 1


def test_an_inconclusive_run_that_never_exhausted_its_budget_is_unchanged(
        tmp_path):
    """NO-LEAK. The pre-existing INCONCLUSIVE waiver tier still exists for the
    runs it was written for; only the verdict-less exhaustion leaves it."""
    p = _project(tmp_path, step_budget_exhausted=False)
    res = L.audit(p)
    assert res.not_measured is False
    assert res.inconclusive is True
    r = _run(p)
    assert r.returncode == 3, f"rc={r.returncode}"
    assert any(line.lstrip().startswith("PASS_WITH_WAIVERS")
               for line in r.stdout.splitlines())


def test_exhaustion_declared_without_naming_the_resource_is_not_defaulted(
        tmp_path):
    """'Could not read it' is not 'wall clock'. An exhaustion whose resource
    the producer never recorded is reported unnamed, never defaulted."""
    doc = dict(_RBAES2)
    doc.pop("exhausted_resource")
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "lec.json").write_text(json.dumps(doc))
    res = L.audit(tmp_path)
    assert res.not_measured is True
    assert res.exhausted_resource == "unnamed"


# ── direction 3: the CONSUMER refuses the promotion, for ANY gate ──────────

def _gate(tmp_path: Path, body: str) -> str:
    prog = tmp_path / "a_gate.py"
    prog.write_text(body, encoding="utf-8")
    return str(prog)


def _outcome(tmp_path, monkeypatch, body):
    prog = _gate(tmp_path, body)
    monkeypatch.setattr(F, "_resolve_program_cmd",
                        lambda cmd, cwd=None: [sys.executable, prog])
    return F._check_program_exit_zero(tmp_path, "a_gate")


def test_flow_compliance_refuses_a_waiver_that_declares_no_measurement(
        tmp_path, monkeypatch):
    ok, out = _outcome(tmp_path, monkeypatch, (
        "import sys\n"
        "print('PASS_WITH_WAIVERS: credit me')\n"
        "print('NOT_MEASURED_NON_WAIVABLE: LEC_BUDGET_EXHAUSTED (wall_clock_seconds)')\n"
        "sys.exit(3)\n"))
    assert ok is False, (
        "a gate that declared its measurement never finished was still "
        "promoted to WAIVED-DEFERRED")
    assert F._WAIVER_HINT_PREFIX not in out, (
        "the waiver hint is attached, so the step is counted as a waiver and "
        "the completion audit credits the slot")
    assert "NOT_MEASURED_NON_WAIVABLE" in out, (
        "the refusal does not name the state it refused on")


def test_flow_compliance_still_honours_an_ordinary_waiver(
        tmp_path, monkeypatch):
    """The mutation control for the clause above: without the non-waivable
    token the SAME rc=3 gate is credited exactly as before."""
    ok, out = _outcome(tmp_path, monkeypatch, (
        "import sys\n"
        "print('PASS_WITH_WAIVERS: credit me')\n"
        "sys.exit(3)\n"))
    assert ok is True, out
    assert F._WAIVER_HINT_PREFIX in out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
