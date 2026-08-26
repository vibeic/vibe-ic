#!/usr/bin/env python3
"""The STA evidence verdict is a CONJUNCTION, and must stay one.

Two measured bugs motivate this file:

  #1  `eda_sta` returned success:true and wrote manifest status:"PASS" while
      openroad exited 0 having linked NO design at all.
  #2  On a clockless netlist a source-less clock still prints `wns max 0.00`,
      byte-identical to a genuinely clean result.

The fix adds a metrics channel next to the exit code. The point of THIS file is
that the metrics channel is only ever ONE TERM OF AN AND, because both terms
were measured to be individually untrustworthy — and, crucially, wrong in
OPPOSITE directions on the same broken input.

Measured on openroad 26Q3-1797-g1c09d62b96 (image digest
sha256:4ece6c01cddc99903af4f027326f7624b069311f2073a5a0b565d5a9cf649a16):

    openroad -exit -metrics a.json bad.tcl    -> rc=1, flow__errors__count=0
    openroad -exit -metrics b.json < bad.tcl  -> rc=0, flow__errors__count=4

An exit-code-only gate passes the second. An error-count-only gate passes the
first. Only the conjunction rejects both, which is what `test_measured_*`
below pins.

`test_no_term_may_be_dropped` is the anti-demotion test: for EVERY declared
term it builds an input in which that term is the ONLY failing one and asserts
the verdict is still a failure. If someone later promotes any single term to
the sole check, the cases belonging to the terms they dropped flip to PASS and
this test goes red. `test_term_membership_is_pinned` stops the sweep itself
from being quietly hollowed out by deleting a term from the exported list —
it compares MEMBERSHIP, not a count, so swapping one term for another is
caught too.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "src" / "lib" / "sta_evidence.mjs"

ERR_METRIC = "flow__errors__count"
LINK_METRIC = "sta__design__port__count"

# The full membership of the conjunction, pinned. Each member is here because a
# real run was measured that ONLY it rejects. Adding a term is fine; removing
# or renaming one re-opens a measured bug and must fail this test.
EXPECTED_TERMS = {
    "exit_code_zero",
    "metrics_file_present",
    f"metric:{ERR_METRIC}",
    f"metric:{LINK_METRIC}",
}

# A metrics payload in which every rule is satisfied.
CLEAN_METRICS = {ERR_METRIC: 0, LINK_METRIC: 4}


def _node():
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node not available; the module under test is JavaScript")
    return exe


def _evaluate(**kwargs) -> dict:
    """Run the real exported evaluator under node. No re-implementation here:
    a Python mirror of the logic could pass while the shipped module fails."""
    script = (
        f'import("file://{MODULE}").then(m => {{'
        f'  const r = m.evaluateStaEvidence({json.dumps(kwargs)});'
        f'  process.stdout.write(JSON.stringify({{'
        f'    pass: r.pass, verdict: r.verdict, failedTerms: r.failedTerms,'
        f'    terms: Object.fromEntries(Object.entries(r.terms).map(([k,v])=>[k,v.ok])),'
        f'    allTerms: m.STA_EVIDENCE_TERMS}}));'
        f'}}).catch(e => {{ process.stderr.write(String(e)); process.exit(9); }});'
    )
    run = subprocess.run([_node(), "--input-type=module", "-e", script],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, f"node failed: {run.stderr}"
    return json.loads(run.stdout)


def _payload(metrics=None, exit_code=0, file_exists=True):
    return dict(exitCode=exit_code, metricsFileExists=file_exists,
                metricsRaw=None if metrics is None else json.dumps(metrics))


# ─────────────────────────── the two measured runs ───────────────────────────

def test_measured_file_script_abort_is_caught_by_the_and():
    """rc=1 with errors=0. The error count ALONE would have called this clean."""
    metrics = {ERR_METRIC: 0, LINK_METRIC: 4}
    got = _evaluate(**_payload(metrics, exit_code=1))
    assert got["pass"] is False, got
    # Show BOTH terms' values: the error-count term is satisfied, the exit-code
    # term is not. An error-count-only gate would have passed this run.
    assert got["terms"][f"metric:{ERR_METRIC}"] is True
    assert got["terms"]["exit_code_zero"] is False
    assert got["failedTerms"] == ["exit_code_zero"]


def test_measured_stdin_form_is_caught_by_the_and():
    """rc=0 with errors=4. The exit code ALONE would have called this clean —
    this is the shape of bug #1 as it actually shipped."""
    metrics = {ERR_METRIC: 4, LINK_METRIC: 4}
    got = _evaluate(**_payload(metrics, exit_code=0))
    assert got["pass"] is False, got
    assert got["terms"]["exit_code_zero"] is True      # would have passed alone
    assert got["terms"][f"metric:{ERR_METRIC}"] is False
    assert got["failedTerms"] == [f"metric:{ERR_METRIC}"]


def test_the_two_measured_runs_disagree_in_opposite_directions():
    """The reason the AND is mandatory, stated as an assertion rather than a
    comment: neither single term is a superset of the other."""
    a = _evaluate(**_payload({ERR_METRIC: 0, LINK_METRIC: 4}, exit_code=1))
    b = _evaluate(**_payload({ERR_METRIC: 4, LINK_METRIC: 4}, exit_code=0))
    assert a["terms"]["exit_code_zero"] != b["terms"]["exit_code_zero"]
    assert a["terms"][f"metric:{ERR_METRIC}"] != b["terms"][f"metric:{ERR_METRIC}"]
    assert a["pass"] is False and b["pass"] is False


# ───────────────────────── the metrics file is absent ────────────────────────

def test_absent_metrics_file_is_unmeasured_not_clean():
    """Measured: the file is genuinely absent after SIGKILL (rc=137) and after
    an unwritable metrics path (rc=1, UTL-0010). Absent must never be read as
    'zero errors'. This is ORFS checkMetadata.py:103-111, NOT LibreLane's
    warn-only checker.py:130-135."""
    got = _evaluate(**_payload(None, exit_code=0, file_exists=False))
    assert got["pass"] is False, got
    assert got["verdict"] == "UNMEASURED"
    assert got["terms"]["metrics_file_present"] is False
    # Note the exit code was ZERO here: exit-code-only would have passed.
    assert got["terms"]["exit_code_zero"] is True


def test_unparseable_metrics_file_is_no_better_than_a_missing_one():
    got = _evaluate(exitCode=0, metricsFileExists=True, metricsRaw="{not json")
    assert got["pass"] is False, got
    assert got["terms"]["metrics_file_present"] is False


def test_absent_required_metric_never_counts_as_satisfied():
    """A metrics file that simply lacks the metric must fail, not default."""
    got = _evaluate(**_payload({LINK_METRIC: 4}, exit_code=0))   # no error count
    assert got["pass"] is False, got
    assert got["verdict"] == "UNMEASURED"
    assert got["terms"][f"metric:{ERR_METRIC}"] is False


# ───────────────────────────── the green pole ────────────────────────────────

def test_a_run_with_every_term_satisfied_passes():
    got = _evaluate(**_payload(CLEAN_METRICS, exit_code=0))
    assert got["pass"] is True, got
    assert got["verdict"] == "PASS"
    assert got["failedTerms"] == []


# ──────────────────── the anti-demotion sweep (the point) ────────────────────

# For each term: an input that fails it, paired with the EXACT set of terms
# that input is expected to fail.
#
# Three of the four can be failed in isolation. `metrics_file_present` cannot,
# and pretending otherwise would be a lie: when the file is absent there is
# nothing to read the metric rules out of, so they are unmeasured too. That
# cascade is stated here as an exact expected set rather than softened to an
# "is among" check — dropping ANY term still changes the observed set and still
# turns this test red, so the ratchet survives being honest about the cascade.
_CASES = {
    "exit_code_zero": (
        lambda: _payload(CLEAN_METRICS, exit_code=1),
        {"exit_code_zero"},
    ),
    "metrics_file_present": (
        lambda: _payload(None, exit_code=0, file_exists=False),
        {"metrics_file_present", f"metric:{ERR_METRIC}", f"metric:{LINK_METRIC}"},
    ),
    f"metric:{ERR_METRIC}": (
        lambda: _payload({**CLEAN_METRICS, ERR_METRIC: 3}, exit_code=0),
        {f"metric:{ERR_METRIC}"},
    ),
    f"metric:{LINK_METRIC}": (
        lambda: _payload({**CLEAN_METRICS, LINK_METRIC: 0}, exit_code=0),
        {f"metric:{LINK_METRIC}"},
    ),
}


def _input_failing_only(term: str) -> dict:
    """Build a run in which `term` is unsatisfied."""
    try:
        build, _ = _CASES[term]
    except KeyError:
        raise AssertionError(
            f"term {term!r} has no counterexample in this test. A term was added "
            f"to STA_EVIDENCE_TERMS without a case proving it can fail a run; "
            f"add one rather than deleting the term.") from None
    return build()


def test_term_membership_is_pinned():
    """Membership, not count — swapping one term for another must be caught."""
    got = _evaluate(**_payload(CLEAN_METRICS, exit_code=0))
    assert set(got["allTerms"]) == EXPECTED_TERMS, (
        "The conjunction's membership changed. If a term was REMOVED, a measured "
        "bug has been re-opened. If one was ADDED, extend EXPECTED_TERMS and "
        "_input_failing_only together.")


@pytest.mark.parametrize("term", sorted(EXPECTED_TERMS))
def test_no_term_may_be_dropped(term):
    """THE ANTI-DEMOTION TEST.

    For each term, the run below fails that term and NOTHING else. If the
    verdict were ever computed from a single term — or from any strict subset —
    every case outside that subset would come back PASS and this parametrised
    test would go red on exactly the dropped terms.
    """
    got = _evaluate(**_input_failing_only(term))
    assert got["pass"] is False, (
        f"{term} no longer fails a run — the conjunction has been weakened to a "
        f"subset or a sole check. Verdict was {got}")
    assert set(got["failedTerms"]) == _CASES[term][1], (
        f"for the {term} case the failing set changed: expected "
        f"{_CASES[term][1]}, got {set(got['failedTerms'])}. A term that used to "
        f"reject this run no longer does.")


def test_the_sweep_can_go_red(monkeypatch):
    """Control for the sweep itself: an evaluator that ORs its terms instead of
    ANDing them must be rejected by the same cases. Proves the sweep is capable
    of failing, rather than being a test that passes on anything."""
    disjunctive_pass = lambda terms: any(terms.values())   # the demoted form
    for term in sorted(EXPECTED_TERMS):
        got = _evaluate(**_input_failing_only(term))
        # Under a disjunction, exactly these inputs would have been called PASS.
        assert disjunctive_pass(got["terms"]) is True
        # Under the shipped conjunction they are not.
        assert got["pass"] is False
