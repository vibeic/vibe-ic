"""#590 — `--phase auto` selected the phase that HID the failure.

`_detect_phase` took "the phase with the newest `one_shot.json`". A phase that
is KILLED never writes one, so the only report on disk belonged to the last
phase that SUCCEEDED, and `auto` picked it. The later a run died, the more
confidently `run_status` reported success — the failure mode chose its own
hiding place.

Measured on the issue's own case (sha256 x sky130A, killed 9 minutes in by a
10-minute harness timeout, phase3 never started):

    auto            DONE — verdict=PASS (phase1)     rc 0
    --phase phase2  STUCK — no output for 8221s      rc 1   <- the true answer
    --phase phase3  RUNNING                          rc 0   <- also wrong

Ordering by REACH inverts it: a phase with a working tree or a log and no report
is FURTHER than one that completed, because completing is what produced the
report the other one lacks.

AN ORCHESTRATOR VERDICT OUTRANKS REACH, and leaving that out was a false finding
I nearly shipped. phase3 legitimately writes no report of its own when it is
skipped or waived, so its tree exists, its report does not, and reach alone
reads a FINISHED run as "died in phase3". Measured over the 182 tracked run
dirs: reach-only flipped 11 of them 0 -> 1/2, and 3 of the first 4 inspected
(ibex, sha256, opentitan_aes on the commercial PDK) had an orchestrator verdict
on disk. With the orchestrator check the flip set is 2, and both are real:

    phase1_parity/arm_aix                  reached phase2, no phase2 report,
                                           no final verdict
      was  DONE — verdict=FAIL (phase1)
    sha256/clean_run_v1432int_commercial   reached phase3, no phase3 report,
                                           no final verdict
      was  DONE — verdict=PASS_WITH_WAIVERS (phase2)

The second is the dangerous one: `PASS_WITH_WAIVERS` reads like a sign-off.

SCOPE. The issue also names a contributing root cause — the runner writes no
`run.pid` and `_runner_lock` deletes the lock — so a dead run cannot be
distinguished from a finished one by liveness. That is a change to the runner,
not to this reader, and is not addressed here; this fixes the reader's choice of
subject, which is what makes the wrong answer the DEFAULT one.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "run_status.py"
_REPO = _PROGRAMS.parents[3]


def _run(project, *extra):
    return subprocess.run([sys.executable, str(PROG), str(project), *extra],
                          capture_output=True, text=True, timeout=30)


def _report(project, name, verdict="PASS"):
    d = project / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps({"verdict": verdict, "steps": []}),
                          encoding="utf-8")


def _stale_log(path, text="Time spent: 46% 2x abc"):
    """A log old enough to be past the silence window."""
    import os
    import time
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    old = time.time() - 3 * 3600
    os.utime(path, (old, old))


# ── the defect ───────────────────────────────────────────────────────────────
def test_a_run_killed_in_phase2_is_not_reported_DONE(tmp_path):
    """The issue's case: phase1 passed and wrote its report, phase2 was killed
    before writing one. `auto` used to answer about phase1."""
    _report(tmp_path, "phase1_one_shot.json", "PASS")
    _stale_log(tmp_path / "phase2" / "stage2" / "synth" / "yosys.log")
    r = _run(tmp_path)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "DONE" not in r.stdout.split("\n")[0], r.stdout
    assert "STUCK" in r.stdout or "DIED" in r.stdout, r.stdout


def test_auto_now_agrees_with_the_explicit_flag(tmp_path):
    """"The correct answer is one flag away" — so the default must give it."""
    _report(tmp_path, "phase1_one_shot.json", "PASS")
    _stale_log(tmp_path / "phase2" / "stage2" / "synth" / "yosys.log")
    auto = _run(tmp_path)
    explicit = _run(tmp_path, "--phase", "phase2")
    assert auto.returncode == explicit.returncode
    assert auto.stdout.split("\n")[0] == explicit.stdout.split("\n")[0]


def test_a_phase3_tree_with_no_phase3_report_outranks_a_passing_phase2(tmp_path):
    """The shape that reads like a sign-off: `PASS_WITH_WAIVERS (phase2)` while
    phase3 was entered and never concluded. Found live on
    `sha256/clean_run_v1432int_commercial`."""
    _report(tmp_path, "phase1_one_shot.json", "PASS")
    _report(tmp_path, "phase2_one_shot.json", "PASS_WITH_WAIVERS")
    _stale_log(tmp_path / "phase3" / "stage3" / "pnr" / "openroad.log")
    r = _run(tmp_path)
    assert "PASS_WITH_WAIVERS" not in r.stdout.split("\n")[0], r.stdout
    assert r.returncode != 0, r.stdout


# ── the accept cases: a finished run must not be called dead ────────────────
def test_an_orchestrator_verdict_outranks_reach(tmp_path):
    """LOAD-BEARING. phase3 writes no report of its own when it is skipped or
    waived. Without this, reach alone calls every such FINISHED run STUCK — 11
    of 182 tracked run dirs, measured."""
    _report(tmp_path, "phase1_one_shot.json", "PASS")
    _report(tmp_path, "phase2_one_shot.json", "PASS")
    _report(tmp_path, "vibe_ic_one_shot.json", "FAIL")
    (tmp_path / "phase3").mkdir()
    r = _run(tmp_path)
    assert "DONE" in r.stdout, r.stdout
    assert "FAIL" in r.stdout, "the orchestrator's own verdict must be the one reported"


def test_a_fully_reported_run_is_unchanged(tmp_path):
    _report(tmp_path, "phase1_one_shot.json", "PASS")
    _report(tmp_path, "phase2_one_shot.json", "PASS")
    _report(tmp_path, "phase3_one_shot.json", "PASS")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DONE" in r.stdout


def test_a_phase1_only_run_still_answers_about_phase1(tmp_path):
    """No later phase was reached, so there is nothing further to report on."""
    _report(tmp_path, "phase1_one_shot.json", "PASS")
    r = _run(tmp_path)
    assert "phase1" in r.stdout, r.stdout
    assert r.returncode == 0


def test_an_empty_project_does_not_claim_a_phase(tmp_path):
    """Nothing was reached. It must not pick one and report on it."""
    (tmp_path / "reports").mkdir()
    r = _run(tmp_path)
    assert "phase2" not in r.stdout and "phase3" not in r.stdout, r.stdout


# ── the two real runs this was measured on ───────────────────────────────────
@pytest.mark.parametrize("rel,must_not_say", [
    ("benchmark-data/evaluation/phase1_parity/arm_aix", "DONE"),
    ("benchmark-data/ic/sha256/clean_run_v1432int_commercial", "DONE"),
])
def test_the_corpus_runs_that_flipped(rel, must_not_say):
    """Fixtures prove the logic; these are the artefacts. Skipped rather than
    assumed when the corpus is absent — "I could not look" and "I looked and it
    is fine" are different claims."""
    d = _REPO / rel
    if not d.is_dir():
        pytest.skip(f"corpus absent: {rel}")
    r = _run(d)
    assert must_not_say not in r.stdout.split("\n")[0], r.stdout
    assert r.returncode != 0, r.stdout
