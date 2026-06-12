"""ORGANIC #599 — universal run_status watchdog. A watcher
(wait-for-exit) cannot distinguish a hung step from progress — a hung
process (PID alive, zero forward progress) is indistinguishable from
normal running, so the agent waits forever. run_status.py is a bounded
one-shot probe returning DONE / DIED / STUCK / RUNNING_ON_TIME in seconds
from existing artifacts, for any phase.

Acceptance (from the issue): a deliberately-killed run reports DIED; a
sleep-stalled run past its budget reports STUCK with the stale mtime; a
completed run reports DONE+verdict; a fresh mid-run reports
RUNNING_ON_TIME+step.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import run_status as RS  # noqa: E402


def _project(tmp_path, phase="phase3", verdict=None, steps=None,
             log_age_s=0.0, with_pid=None):
    """Build a fake project with a phase one_shot report + a live log."""
    orch = tmp_path / "reports" / "orchestrator"
    orch.mkdir(parents=True)
    rep = {"project": str(tmp_path), "verdict": verdict,
           "steps": steps or []}
    if verdict is None:
        rep.pop("verdict")
    (orch / f"{phase}_one_shot.json").write_text(json.dumps(rep))
    # a phase3 log for heartbeat
    logd = tmp_path / "phase3" / "stage3" / "pnr"
    logd.mkdir(parents=True)
    log = logd / "openroad.log"
    log.write_text("[INFO DRT-0195] iteration 5\nstill routing\n")
    if log_age_s:
        old = time.time() - log_age_s
        os.utime(log, (old, old))
    if with_pid is not None:
        (tmp_path / "run.pid").write_text(str(with_pid))
    return tmp_path


# ── DONE ─────────────────────────────────────────────────────────────────────

def test_done_when_verdict_present(tmp_path):
    p = _project(tmp_path, verdict="PASS",
                 steps=[{"name": "pnr", "status": "PASS"}])
    rep = RS.status(p, "phase3")
    assert rep["state"] == "DONE"
    assert rep["verdict"] == "PASS"


def test_done_reports_fail_verdict_too(tmp_path):
    """A completed run with a FAIL verdict is still DONE (the watchdog
    reports completion, not pass/fail)."""
    p = _project(tmp_path, verdict="FAIL")
    assert RS.status(p, "phase3")["state"] == "DONE"


# ── DIED ─────────────────────────────────────────────────────────────────────

def test_died_when_pid_gone_no_verdict(tmp_path):
    # a PID that is certainly dead
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "pnr", "status": "RUNNING"}],
                 with_pid=999999)
    rep = RS.status(p, "phase3")
    assert rep["state"] == "DIED"
    assert "abnormal exit" in rep["reason"]
    assert rep["last_log_line"]          # last log surfaced


# ── STUCK ────────────────────────────────────────────────────────────────────

def test_stuck_when_alive_overdue_and_stale(tmp_path):
    """PID alive (this test process) + past budget + stale heartbeat →
    STUCK. pnr budget is 1800s; make the log 4000s old."""
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "pnr", "status": "RUNNING"}],
                 log_age_s=4000.0, with_pid=os.getpid())
    rep = RS.status(p, "phase3", stale_window_s=300)
    assert rep["state"] == "STUCK"
    assert "OVERDUE" in rep["reason"]
    assert rep["heartbeat_age_s"] > 1800


def test_not_stuck_when_fresh_even_if_alive(tmp_path):
    """A fresh heartbeat (within budget) is RUNNING_ON_TIME, not STUCK,
    even though the PID is alive and there's no verdict."""
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "pnr", "status": "RUNNING"}],
                 log_age_s=10.0, with_pid=os.getpid())
    rep = RS.status(p, "phase3")
    assert rep["state"] == "RUNNING_ON_TIME"
    assert rep["current_step"] == "pnr"


# ── RUNNING_ON_TIME ──────────────────────────────────────────────────────────

def test_running_on_time_reports_step_and_eta(tmp_path):
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "synth", "status": "PASS"},
                        {"name": "pnr", "status": "RUNNING"}],
                 log_age_s=30.0, with_pid=os.getpid())
    rep = RS.status(p, "phase3")
    assert rep["state"] == "RUNNING_ON_TIME"
    assert rep["current_step"] == "pnr"
    assert rep["steps_completed"] == 1
    assert rep["eta_s"] is not None


# ── no-PID heartbeat inference ───────────────────────────────────────────────

def test_unknown_when_no_pid_but_fresh(tmp_path):
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "pnr", "status": "RUNNING"}],
                 log_age_s=10.0)  # no pid
    rep = RS.status(p, "phase3")
    assert rep["state"] == "UNKNOWN"
    assert "no PID" in rep["reason"]


def test_stuck_inferred_when_no_pid_but_very_stale(tmp_path):
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "pnr", "status": "RUNNING"}],
                 log_age_s=5000.0)  # no pid, very stale
    rep = RS.status(p, "phase3", stale_window_s=300)
    assert rep["state"] == "STUCK"


# ── PID resolved from the existing #588 single-driver lock ──────────────────

def test_pid_resolved_from_runner_lock(tmp_path):
    """run_status reuses the EXISTING .runner.lock (#588) holder pid — no
    new run.pid convention required. A dead lock pid + no verdict → DIED."""
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "pnr", "status": "RUNNING"}])
    (tmp_path / ".runner.lock").write_text(
        json.dumps({"pid": 999999, "runner": "phase3_one_shot_runner"}))
    rep = RS.status(p, "phase3")
    assert rep["pid"] == 999999
    assert rep["state"] == "DIED"


# ── CLI + exit codes ─────────────────────────────────────────────────────────

def test_cli_exit_codes(tmp_path):
    p = _project(tmp_path, verdict="PASS")
    r = subprocess.run(
        [sys.executable, str(PROG / "run_status.py"), str(p),
         "--phase", "phase3"],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert "DONE" in r.stdout


def test_cli_died_exit_2(tmp_path):
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "pnr", "status": "RUNNING"}],
                 with_pid=999999)
    r = subprocess.run(
        [sys.executable, str(PROG / "run_status.py"), str(p),
         "--phase", "phase3"],
        capture_output=True, text=True)
    assert r.returncode == 2
    assert "DIED" in r.stdout


# ── #599 wired into the field-agent artifact-first 'check status' (#598) ────

def test_run_status_wired_into_field_agent_skill():
    skill = (PROG.parent / "skills" / "field-agent-loop" / "SKILL.md")
    if not skill.is_file():  # PROG may already be the plugin root
        skill = PROG / "skills" / "field-agent-loop" / "SKILL.md"
    t = skill.read_text(errors="replace")
    assert "run_status.py" in t
    # the four states are named (may wrap across lines in the prose)
    for state in ("DONE", "DIED", "STUCK", "RUNNING_ON_TIME"):
        assert state in t, state
    # named as the canonical 'check status' answer
    assert "check status" in t.lower()


# ── live-corpus canary: real completed run reports DONE ──────────────────────

def test_real_completed_run_is_done():
    import pytest
    art = Path("/home/reyerchu/vibe-ic/benchmark_ic/5th__opentitan_aes_v0338")
    rep_f = art / "reports" / "orchestrator" / "phase3_one_shot.json"
    if not rep_f.is_file():
        pytest.skip("real phase3 report not on this host (live corpus)")
    rep = RS.status(art, "phase3")
    assert rep["state"] == "DONE"
    assert rep["verdict"] is not None
