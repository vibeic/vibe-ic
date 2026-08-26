#!/usr/bin/env python3
"""Tests for coverage_closure.py — RTL coverage gap analysis.

WHY THIS FILE WAS REWRITTEN
===========================
The previous version encoded the defect as expected behaviour. It asserted:

    _write_cov(project, {"coverage_pct": 92})  -> "[PASS] coverage_closure"
    _write_cov(project, {"pct": 85})           -> "[PASS] coverage_closure"

Neither payload is a coverage MEASUREMENT. `verilator_coverage_measure
measure` — the only producer of a measurement at
`reports/phase2/coverage/coverage_verilator.json` — writes
`totals.{line,toggle,branch}.pct` and never a bare `coverage_pct`/`pct`. So
the two "positive" cases were asserting that a coverage CLAIM with nothing
behind it buys a PASS, which is precisely the forgery
`verilator_coverage_measure.classify_coverage_artefact` classifies as
`forged`. Meanwhile no test in the file ever handed the program the real
schema, so the reader could drift off it unnoticed — and it had:

  * a genuine 95/92/91 % Verilator artefact       -> "[FAIL] 0% < 80%"
  * the live spm x ihp-sg13g2 functional payload  -> "[FAIL] 0% < 80%"
  * a bare `{"coverage_pct": 95}` forgery         -> "[PASS] 95%"

The assertions below are TIGHTENED to the honest behaviour, not relaxed:
every case the old file covered is still covered, in the direction that
matches what the artefact actually says.

TEST FAMILIES
=============
  test_DEFECT_*  fail on origin/main (they need the schema fix).
  test_GUARD_*   pass on BOTH trees — what must NOT change: a real gap still
                 FAILs, a corrupt artefact still FAILs, and exit 0 stays
                 reachable only through a real `totals` measurement.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "coverage_closure.py"

sys.path.insert(0, str(PROG.parent))
from verilator_coverage_measure import COVERAGE_MEASUREMENT_REL  # noqa: E402


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def _write_cov(project: Path, body) -> None:
    cov_dir = project / "reports" / "phase2" / "coverage"
    cov_dir.mkdir(parents=True, exist_ok=True)
    # The MEASUREMENT path. `coverage_actual.json` belongs to the functional-
    # verdict producer; coverage_closure reads the coverage producer's own
    # artefact, and the name is taken from the program so the two cannot drift.
    target = cov_dir / Path(COVERAGE_MEASUREMENT_REL).name
    if isinstance(body, str):
        target.write_text(body)
    else:
        target.write_text(json.dumps(body))


def _measured(project: Path, line: float, toggle: float, branch: float) -> dict:
    """Write the REAL `verilator_coverage_measure measure` payload shape.

    `classify_coverage_artefact` additionally requires the recorded
    `coverage_dat` backlink to exist, so this creates one.
    """
    dat = project / "coverage.dat"
    dat.parent.mkdir(parents=True, exist_ok=True)
    dat.write_text("# verilator coverage\n")
    payload = {
        "tool": "verilator",
        "coverage_dat": str(dat),
        "totals": {
            "line": {"covered": int(line), "total": 100, "pct": line},
            "toggle": {"covered": int(toggle), "total": 100, "pct": toggle},
            "branch": {"covered": int(branch), "total": 100, "pct": branch},
        },
    }
    _write_cov(project, payload)
    return payload


def _proj(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── DEFECT direction — these FAIL against origin/main's coverage_closure.py ──

def test_DEFECT_real_verilator_measurement_above_goal_passes(tmp_path):
    """A genuine tool-generated 95/92/91 % artefact must PASS.

    origin/main reads `coverage_pct`/`pct`, finds neither, falls back to `0`
    and prints `[FAIL] coverage_closure: 0% < 80%` — failing real coverage.
    """
    project = _proj(tmp_path)
    _measured(project, 95.0, 92.0, 91.0)
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "[PASS] coverage_closure" in cp.stdout
    # the REAL numbers must appear — not a fabricated aggregate
    for token in ("line=95.0%", "toggle=92.0%", "branch=91.0%"):
        assert token in cp.stdout, cp.stdout


def test_DEFECT_forged_bare_percentage_claim_is_rejected(tmp_path):
    """A coverage CLAIM with no `totals` behind it is a forgery, not a PASS.

    origin/main prints `[PASS] coverage_closure: 95%` for this payload.
    """
    project = _proj(tmp_path)
    _write_cov(project, {"coverage_pct": 95, "note": "estimated by agent"})
    cp = _run([str(project)])
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "forged" in cp.stdout
    assert "coverage claim is not a coverage measurement" in cp.stdout


def test_DEFECT_foreign_producer_payload_is_disclosed_not_scored(tmp_path):
    """The live-run shape: another producer owns the declared coverage path.

    `design_one_shot_runner` writes a functional-verification verdict payload
    (verdict / evidence / verification_track / scenarios_covered) to
    reports/phase2/coverage/coverage_verilator.json. No line/toggle/branch was
    measured there. origin/main turns that into the specific, false claim
    `0% < 80%`; the honest answer is a DISCLOSED skip (rc=2), which
    flow_compliance_check renders as `n/a`, never as a clean result.
    """
    project = _proj(tmp_path)
    _write_cov(project, {
        "verdict": "PASS",
        "evidence": "phase2/stage1/sim_full_stack/oracle_run/oracle.log",
        "verification_track": "oracle_tb",
        "scenarios_covered": [],
        "vectors_passed": 28, "vectors_total": 28,
    })
    cp = _run([str(project)])
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert "no coverage MEASUREMENT" in cp.stdout
    # the disclosure must NAME the other producer, so the collision is
    # attributable rather than merely reported as "missing"
    assert "oracle_tb" in cp.stdout
    # rc=2 is the flow's disclosed-skip tier; the sentinel must be on stdout
    # too, because `_stdout_signals_vacuous` scans for it independently.
    assert any(ln.lstrip().startswith("VACUOUS_PASS")
               for ln in cp.stdout.splitlines()), cp.stdout


def test_DEFECT_absent_artefact_is_a_disclosed_skip_not_a_clean_exit(tmp_path):
    """No artefact at all -> rc=2 (disclosed), not rc=0 (audited and clean).

    origin/main exits 0 here, which the advisory slot records as `ok:` —
    "this project was audited and found clean" substituted for "there was
    nothing to audit".
    """
    project = _proj(tmp_path)
    cp = _run([str(project)])
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert "[SKIP] coverage_closure" in cp.stdout
    assert "no coverage MEASUREMENT" in cp.stdout


def test_DEFECT_bare_pct_key_is_not_a_measurement(tmp_path):
    """`{"pct": 85}` carries no `totals` — it is not a measurement.

    The old `test_edge_pct_key_fallback` asserted this shape PASSES, which is
    the same defect as the `coverage_pct` case one layer down: a number with
    no counters behind it. `pct` is not one of the recognised bare-claim keys,
    so it classifies as `foreign` (another producer's payload) rather than
    `forged` — either way it is never a coverage result.
    """
    project = _proj(tmp_path)
    _write_cov(project, {"pct": 85})
    cp = _run([str(project)])
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert "no coverage MEASUREMENT" in cp.stdout


def test_DEFECT_below_goal_report_names_the_measured_numbers(tmp_path):
    """A gap report must carry the numbers it measured.

    origin/main FAILs this input too — but at "0% < 80%", a number that
    appears in no artefact. A FAIL for the wrong reason is not the same
    check, and only the measured values make the finding actionable.
    """
    project = _proj(tmp_path)
    _measured(project, 65.0, 90.0, 88.0)
    cp = _run([str(project)])
    assert "65" in cp.stdout, cp.stdout
    assert "line=65.0%" in cp.stdout and "toggle=90.0%" in cp.stdout


def test_DEFECT_exactly_at_goal_passes(tmp_path):
    """Boundary: the comparison is strict `<`, so exactly-at-goal is a PASS.

    Needs the schema fix — origin/main reads 0 for this payload and FAILs.
    """
    project = _proj(tmp_path)
    _measured(project, 80.0, 80.0, 80.0)
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "[PASS]" in cp.stdout


@pytest.mark.parametrize("payload", [
    {"coverage_pct": 99},                                    # forged claim
    {"pct": 99},                                             # bare number
    {"verdict": "PASS", "verification_track": "oracle_tb"},  # foreign
    {"totals": {}},                                          # empty container
    None,                                                    # nothing there
])
def test_DEFECT_exit_zero_requires_a_real_measurement(tmp_path, payload):
    """Exit 0 must be reachable ONLY through a real `totals` measurement.

    This is the property the whole fix is about: no shape that lacks measured
    counters may buy a clean exit. Parametrised over every non-measured shape
    so a future "fallback key" cannot quietly reopen the hole. Three of the
    five buy a clean exit 0 on origin/main.
    """
    project = _proj(tmp_path)
    if payload is not None:
        _write_cov(project, payload)
    cp = _run([str(project)])
    assert cp.returncode != 0, (
        f"{payload!r} bought a clean exit 0:\n{cp.stdout}{cp.stderr}")


# ── GUARD direction — must hold on BOTH trees ────────────────────────────────

def test_GUARD_measurement_below_goal_still_fails(tmp_path):
    """The gap analysis must keep its teeth: a real 65 % line coverage FAILs.

    Direction-1 only — that the verdict stays FAIL. What the report SAYS about
    it is the DEFECT test above; splitting them keeps this half honest on both
    trees.
    """
    project = _proj(tmp_path)
    _measured(project, 65.0, 90.0, 88.0)
    cp = _run([str(project)])
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "[FAIL] coverage_closure" in cp.stdout


def test_GUARD_corrupt_artefact_still_fails(tmp_path):
    """Unparseable JSON at the declared path is a defect, never an exemption."""
    project = _proj(tmp_path)
    _write_cov(project, "garbage {not json")
    cp = _run([str(project)])
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "[FAIL] coverage_closure" in cp.stdout
