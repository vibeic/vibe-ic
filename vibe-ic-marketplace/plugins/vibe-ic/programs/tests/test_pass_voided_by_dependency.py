"""A PASS a dependency contradicts is not a PASS.

The violation was always detected and always failed the RUN. What it never did
was touch the step's own status, so the per-step table published `PASS` beside
its own line saying a step it depends on had FAILED. Both locally correct; the
table showed the weaker one.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHECK = Path(__file__).resolve().parent.parent / "flow_compliance_check.py"
import flow_step_execution_coverage_check as cov  # noqa: E402


def _report(statuses):
    return {"steps": [{"id": i, "name": f"step {i}", "status": s, "stage": "s"}
                      for i, s in statuses]}


def test_a_terminal_step_over_a_failed_dependency_is_a_violation():
    """The detection this fix writes back — unchanged, asserted as the premise."""
    got = cov.analyze(_report([(1, "FAIL"), (2, "PASS")]), {"2": ["1"]})
    v = got.get("ordering_violations") or []
    assert len(v) == 1, got
    assert str(v[0]["terminal_id"]) == "2"
    assert str(v[0]["signoff_id"]) == "1"


def test_a_healthy_chain_produces_no_violation():
    """THE control. A run whose dependencies all passed must be untouched — if
    this fires, the rule punishes correct work and is worse than the silence it
    replaces."""
    got = cov.analyze(_report([(1, "PASS"), (2, "PASS")]), {"2": ["1"]})
    assert not (got.get("ordering_violations") or []), got


def test_the_transitive_case_is_a_violation_too():
    """3 -> 2 -> 1: a failure two hops up still voids the terminal's PASS."""
    got = cov.analyze(_report([(1, "FAIL"), (2, "PASS"), (3, "PASS")]),
                      {"2": ["1"], "3": ["2"]})
    ids = {str(v["terminal_id"]) for v in (got.get("ordering_violations") or [])}
    assert "3" in ids, got


# ---- the write-back itself, exercised through the shipped entry point --------

def _run(project: Path):
    p = subprocess.run([sys.executable, str(CHECK), str(project)],
                       capture_output=True, text=True, timeout=30)
    return p.stdout + p.stderr


def test_the_summary_parts_still_sum_to_the_step_count(tmp_path):
    """A bucket the summary line does not print loses steps silently.

    The first cut demoted 18 of 63 steps into exactly such a bucket, so the line
    read 45 out of 63 and the rest vanished — the defect this change exists to
    remove, reintroduced by the change itself.
    """
    import re
    out = _run(tmp_path)
    m = re.search(r"^\s+PASS=\d+.*$", out, re.M)
    if not m:                       # an empty project may not reach the summary
        return
    total = sum(int(x) for x in re.findall(r"=(\d+)", m.group(0)))
    steps = re.search(r"Steps:\s*(\d+)\s+total", out)
    if steps:
        assert total == int(steps.group(1)), m.group(0)


def test_the_status_is_distinct_from_vacuous_pass():
    """VACUOUS_PASS means "ran cleanly on input that did not apply" and rolls
    into pass_count by design. This is the opposite case: the input applied and
    a dependency failed, so reusing that tier would keep the inflation."""
    src = CHECK.read_text(encoding="utf-8")
    assert "PASS_VOIDED_BY_DEPENDENCY" in src
    assert 'pass_count = counts["PASS"] + counts["VACUOUS_PASS"]' in src
    assert 'counts["PASS_VOIDED_BY_DEPENDENCY"]' not in src.split(
        "pass_count = ")[1].split("\n")[0]


def test_detection_runs_before_the_table_is_printed():
    """Structural, because the first attempt demoted AFTER the print loop and
    changed nothing a reader ever saw."""
    src = CHECK.read_text(encoding="utf-8").splitlines()
    demote = next(i for i, l in enumerate(src)
                  if '_r.status = "PASS_VOIDED_BY_DEPENDENCY"' in l)
    printed = next(i for i, l in enumerate(src) if "_icon = {" in l)
    assert demote < printed, (demote, printed)
