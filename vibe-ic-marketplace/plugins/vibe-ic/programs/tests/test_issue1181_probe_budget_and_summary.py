"""A test that outlives the harness bound destroys the whole invocation. #1181.

RECOVERED from vibe-ic#1234, which was closed in favour of this PR and took a
146-line file with it. The two PRs answered #1181 differently — #1234 gave the
slow test a longer bound and an always-on `DEFAULT_CI_BUDGET_S`; this PR makes
the sweep FAST (192.9s -> 44.6s) with an opt-in `budget` — and that arbitration
is not reopened here. What is recovered is the part that survives either answer:
the MECHANISM claim both designs rest on, and a deterministic exercise of the
truncation path.

TWO OF #1234's SIX TESTS ARE DELIBERATELY NOT CARRIED, because they assert the
OTHER design's remedy and importing them would smuggle it in through the tests:

  * `test_the_slow_test_carries_a_bound_it_can_actually_meet` asserts that
    `test_gate_discloses_denominator.py` contains `@pytest.mark.timeout(`. That
    is #1234's fix. This PR has no such marker and needs none, because it made
    the sweep fit the bound instead of widening the bound. Carrying this test
    would fail here, and "repairing" it by adding a marker would adopt the
    design that lost.
  * `test_the_backstop_is_far_above_the_measured_time_not_a_squeeze` asserts
    `G.DEFAULT_CI_BUDGET_S >= 600`. This PR has no module-level default at all —
    `budget` is `Optional[float] = None` and the CLI's `--budget` defaults to
    None. Its caller-side equivalent is `_CI_SWEEP_BUDGET_S = 600.0` in
    `test_gate_discloses_denominator.py`, which already carries that reasoning
    ("a CEILING, not a target"). Asserting a constant from the file that defines
    it would be the claim wearing a test.

WHY THE FIRST TEST BELOW IS THE ONE THIS CLUSTER CAN LEAST AFFORD TO LOSE.
Every docstring in the #1181/#1272 cluster CITES the mechanism — that
`--timeout-method=thread` cannot interrupt a blocking `subprocess.wait`, so
pytest-timeout dumps stacks and calls `os._exit(1)`, killing the interpreter
before a summary is written. #1234 was the only PR that MEASURED it. The
consequence is not one slow test: the invocation produces NO SUMMARY LINE and
ZERO `FAILED` lines, which greps as a clean sweep. Two full-suite sweeps of
clean main died that way today at 22% and 23%, and the first reading of the
wreckage was "0 failing nodes" on a suite whose 63x9 matrix alone is 26 red.

If a future pytest-timeout stopped calling `os._exit`, this test says so rather
than leaving the cluster's premise standing on a citation.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import gate_discloses_denominator_check as G  # noqa: E402

_T = 55


# --------------------------------------------------------------------------
# the mechanism — design-independent, carried from #1234 unchanged
# --------------------------------------------------------------------------
def test_pytest_timeout_thread_method_really_does_exit_the_process(tmp_path):
    """The claim this whole cluster rests on, measured rather than cited."""
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


def test_a_bound_the_work_fits_restores_the_summary(tmp_path):
    """The other half of the mechanism: once the work is inside the bound, the
    summary comes back and the other files in the invocation keep their result.

    #1234 demonstrated this by widening the bound and this PR by shrinking the
    work; on a fixture the two are the same fact, which is why this survives the
    arbitration while the assertion about the real file's marker does not.
    """
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
# the truncation path, RETARGETED onto this PR's `truncated` design
#
# `test_gate_discloses_denominator.py::test_the_real_ci_gate_set_is_currently_
# clean` already asserts this property, but CONDITIONALLY — `if res.truncated:`
# over a real 600s budget against a measured 192.9s sweep. On any host quick
# enough not to truncate it takes the `else` branch, so the disclosure code is
# never executed and could rot green. These two force both outcomes.
# --------------------------------------------------------------------------
def _repo_with(tmp_path: Path, body: str) -> Path:
    repo = tmp_path / "repo"
    (repo / "tools" / "ci").mkdir(parents=True)
    (repo / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(body)
    return repo


def test_an_exhausted_budget_is_a_NAMED_finding_not_a_quiet_shrink(tmp_path):
    """PAIRED GUARD. If truncation were folded into the ordinary result, the
    audit would report a clean verdict over a SMALLER DENOMINATOR — which is
    the exact defect this program exists to detect in everybody else, committed
    by the program itself.
    """
    repo = _repo_with(tmp_path,
                      'run "slow one" "$ROOT" sleep 5\n'
                      'run "slow two" "$ROOT" sleep 5\n'
                      'run "slow three" "$ROOT" sleep 5\n')
    res = G.audit_ci(repo, timeout=30, budget=0.001)

    assert res.truncated is True, (
        f"the budget stopped the sweep and `truncated` stayed False: {res}")
    assert res.verdict != "PASS", (
        "a run that never reached its gates reported PASS — that is a smaller "
        "denominator wearing a clean verdict")
    assert res.verdict == "NOT_CHECKED", res.verdict
    assert any("aggregate budget" in why for _label, why in res.not_driven), (
        f"truncation is not NAMED in not_driven: {res.not_driven}")


def test_a_generous_budget_does_not_fire(tmp_path):
    """FALSE-POSITIVE CONTROL: without it the guard above is satisfied by an
    `always truncate`, and `truncated` would carry no information."""
    repo = _repo_with(tmp_path, 'run "quick" "$ROOT" true\n')
    res = G.audit_ci(repo, timeout=30, budget=900)
    assert res.truncated is False, res
    assert not any("aggregate budget" in why for _l, why in res.not_driven), \
        res.not_driven
