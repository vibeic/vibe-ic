"""The flow reads the CLI's exit code, and five gates had nobody driving it.

A neutering survey over the 127 gate programs the flow names — insert
``return 0`` as the first statement of the entry point, run every test file that
names the program, and see whether anything reddens — came back 122 CAUGHT and
5 SILENT.  All five SILENT gates DO have tests, and those tests DO import them.
They call ``audit()``.

    tests exercise:   audit(project) -> {"rc": ..., "findings": [...]}
    the flow reads:   main() -> argparse -> audit -> rc -> --json report

So the finding logic was measured and the verdict-to-exit-code mapping was not.
An audit that correctly finds the defect, a ``main`` that fails to return it,
and a flow that reads PASS: the same disease as everywhere else in this
campaign, sitting at the exit instead of the entrance.

Each case below drives the program the way the flow drives it — as a
subprocess, with the flag the flow passes — and pins the exit code the flow
would act on.  Every one of them reddens under the neutering that the survey
found nobody noticing.

The rc values are the programs' own conventions, read from their behaviour and
not chosen here: 2 is the disclosed input-missing tier, 1 is a refusal.  What
matters is that they are NOT 0, because 0 is what a neutered gate returns.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).resolve().parents[1]


def _run(program: str, project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRAMS_DIR / f"{program}.py"), str(project), *args],
        capture_output=True, text=True)


# (program, extra argv, the non-zero rc the flow would see, what makes it non-zero)
CASES = [
    ("sdc_exception_correlation_check", (), 2,
     "an empty project has no SDC and no CDC report to correlate"),
    ("perc_signoff_check", (), 2,
     "an empty project ships no PERC report to sign off"),
    ("ip_integration_check", (), 2,
     "an empty project declares no macro file-set to align"),
    ("phase1_expert_track_evidence_check", ("--require-expert-track",), 1,
     "the expert track NEVER_RAN and the caller required it"),
]


@pytest.mark.parametrize("program,extra,want_rc,why", CASES,
                         ids=[c[0] for c in CASES])
def test_the_cli_returns_the_verdict_the_flow_acts_on(program, extra, want_rc,
                                                      why, tmp_path):
    """Drive it as the flow drives it, and pin the code the flow reads.

    Asserting the exact value rather than "non-zero" is deliberate: the tiers
    mean different things to `flow_compliance_check` (2 is a disclosed skip, 1
    is a refusal), and a change that silently moved a refusal into the skip tier
    would pass a non-zero assertion while changing what the step reports.
    """
    report = tmp_path / "gate.json"
    r = _run(program, tmp_path, *extra, "--json", str(report))
    assert r.returncode == want_rc, (
        f"{program}: the flow would read rc={r.returncode}, expected "
        f"{want_rc} — {why}\nstdout: {r.stdout[-400:]}\nstderr: {r.stderr[-400:]}")
    assert report.is_file(), (
        f"{program}: exit code aside, the flow's declared --json report was "
        f"never written, so nothing downstream can read what it decided")


def test_a_disclosure_only_gate_still_refuses_an_unreadable_project():
    """`route_congestion_trade_disclosure` is wired ADVISORY and cannot block.

    Its content path returns 0 by design — it discloses a trade, it does not
    judge one — so the only exit code it owns is the IO refusal.  That is a
    narrower property than the four above and it is stated as such rather than
    dressed up: what it pins is that the entry point still runs and still
    refuses an input it cannot read.
    """
    r = _run("route_congestion_trade_disclosure", Path("/nonexistent/project"))
    assert r.returncode == 2, (
        "the disclosure gate accepted a project directory that does not exist; "
        f"rc={r.returncode}, stderr={r.stderr[-300:]}")
    assert "IO_ERROR" in r.stderr, r.stderr
