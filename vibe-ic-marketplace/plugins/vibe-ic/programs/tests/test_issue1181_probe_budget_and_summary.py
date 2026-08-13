"""A test that outlives the harness bound destroys the whole invocation. #1181.

`test_gate_discloses_denominator.py::test_the_real_ci_gate_set_is_currently_clean`
drives 50 real gates and needs **204 s** on `a38902d1`. The landing gate runs
pytest at `--timeout=180`.

`pytest-timeout`'s `thread` method cannot interrupt a blocking `subprocess.wait`,
so when it fires it dumps stacks and calls **`os._exit(1)`** — its own docstring
says exactly that. The interpreter dies before pytest writes a summary, so:

    RED  (origin/main, --timeout=180)   Timeout dump, NO summary line, exit 1
    GREEN (with the marker)             `8 passed in 202.89s`, exit 0

The cost is not one slow test. It is that **every other file in the same
invocation loses its result**, and what the operator sees is neither a pass nor
a failure — the same ambiguity as `no tests ran`.

TWO HALVES, and they are deliberately not the same mechanism:

  * the TEST gets a `pytest.mark.timeout(600)` — the honest fit for work that
    legitimately takes 3.5 minutes;
  * the PROGRAM gets `DEFAULT_CI_BUDGET_S`, a far-above BACKSTOP, so a loop over
    74 per-gate timeouts cannot run unbounded if a gate starts hanging. Sizing
    that budget to squeeze under 180 s instead would trade a crash for a FLAKY
    test, because the sweep's wall clock moves with host load.

A budget that is exhausted is never a quiet reduction of the denominator: it is
a NAMED finding, because "I ran out of clock before reaching 12 gates" and "12
gates cannot be driven by construction" are different facts.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import gate_discloses_denominator_check as G  # noqa: E402

_T = 55


# --------------------------------------------------------------------------
# the mechanism, pinned so nobody "simplifies" the marker away
# --------------------------------------------------------------------------
def test_the_slow_test_carries_a_bound_it_can_actually_meet():
    src = (PROGRAMS / "tests" / "test_gate_discloses_denominator.py").read_text()
    assert "@pytest.mark.timeout(" in src, (
        "the 204s test has no bound of its own, so the harness's 180s bound "
        "fires and os._exit(1) takes the whole invocation's summary with it")


def test_pytest_timeout_thread_method_really_does_exit_the_process(tmp_path):
    """The claim this whole fix rests on, measured rather than cited.

    If a future pytest-timeout stopped calling `os._exit`, the marker would be
    unnecessary and this test says so instead of leaving a cargo-culted marker
    behind.
    """
    t = tmp_path / "test_x.py"
    t.write_text(textwrap.dedent("""\
        import subprocess
        def test_a():
            assert True
        def test_slow():
            subprocess.run(["sleep", "6"])
    """))
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "pytest_timeout",
         "--timeout=2", "--timeout-method=thread", str(t)],
        capture_output=True, text=True, timeout=_T,
        env={"PATH": "/usr/bin:/bin", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
    out = p.stdout + p.stderr
    assert "Timeout" in out, out
    # the whole point: no summary, so even `test_a`'s pass is lost
    assert not any(l.strip().startswith(("1 passed", "2 passed", "1 failed"))
                   for l in out.splitlines()), (
        "pytest wrote a summary despite the thread-method timeout — the "
        f"premise of #1181 no longer holds:\n{out}")


def test_a_marker_restores_the_summary(tmp_path):
    """The fix's mechanism, on a fixture rather than on the 204s real thing."""
    t = tmp_path / "test_y.py"
    t.write_text(textwrap.dedent("""\
        import subprocess, pytest
        def test_a():
            assert True
        @pytest.mark.timeout(30)
        def test_slow():
            subprocess.run(["sleep", "6"])
    """))
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "pytest_timeout",
         "--timeout=2", "--timeout-method=thread", str(t)],
        capture_output=True, text=True, timeout=_T,
        env={"PATH": "/usr/bin:/bin", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
    assert p.returncode == 0, p.stdout + p.stderr
    assert "2 passed" in p.stdout, p.stdout


# --------------------------------------------------------------------------
# the backstop, and the disclosure that stops it being a silent shrink
# --------------------------------------------------------------------------
def test_the_backstop_is_far_above_the_measured_time_not_a_squeeze():
    """A budget near the measured 204s would fail on a busy host and pass on a
    quiet one. Flaky is worse than slow."""
    assert G.DEFAULT_CI_BUDGET_S >= 600, G.DEFAULT_CI_BUDGET_S


def test_an_exhausted_budget_is_a_NAMED_finding_not_a_quiet_shrink(tmp_path):
    """PAIRED GUARD. If the budget silently dropped the unreached gates into
    `not_driven`, the audit would still say PASS over a smaller denominator —
    which is the exact defect this program exists to detect, committed by the
    program itself."""
    repo = tmp_path / "repo"
    (repo / "tools" / "ci").mkdir(parents=True)
    (repo / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        'run "slow one" "$ROOT" sleep 5\n'
        'run "slow two" "$ROOT" sleep 5\n'
        'run "slow three" "$ROOT" sleep 5\n')
    res = G.audit_ci(repo, timeout=30, budget_s=0.001)
    kinds = [f.get("kind") for f in res.findings]
    assert "BUDGET_EXHAUSTED" in kinds, (
        f"the budget stopped the sweep and the audit did not say so: {res}")
    assert res.verdict != "PASS", (
        "a run that never reached its gates reported PASS — that is a smaller "
        "denominator wearing a clean verdict")
    detail = next(f["detail"] for f in res.findings
                  if f.get("kind") == "BUDGET_EXHAUSTED")
    assert "never driven" in detail and "denominator" in detail, detail


def test_a_generous_budget_does_not_fire(tmp_path):
    """False-positive control: without it the backstop could be `always fire`."""
    repo = tmp_path / "repo"
    (repo / "tools" / "ci").mkdir(parents=True)
    (repo / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        'run "quick" "$ROOT" true\n')
    res = G.audit_ci(repo, timeout=30, budget_s=900)
    assert not any(f.get("kind") == "BUDGET_EXHAUSTED" for f in res.findings), \
        res.findings
