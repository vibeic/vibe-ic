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
from _hostpaths import require_repo  # noqa: E402


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


# ── STUCK = observed silence beyond the window (NOT a duration budget) ───────

def test_stuck_when_alive_and_silent_beyond_window(tmp_path):
    """PID alive + no verdict + NO output for longer than the silence
    window → STUCK. The default window is 600s; make the log 4000s old."""
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "pnr", "status": "RUNNING"}],
                 log_age_s=4000.0, with_pid=os.getpid())
    rep = RS.status(p, "phase3")
    assert rep["state"] == "STUCK"
    assert rep["silence_s"] > 600
    assert "not progressing" in rep["reason"]


def test_long_run_not_stuck_while_writing(tmp_path):
    """THE KEY FIX (user critique): a run that has been going a LONG time
    but keeps writing (fresh heartbeat) is RUNNING, not STUCK — the
    verdict does not depend on a guessed per-step DURATION budget, only
    on observed silence. Here the step has 'run' a notional 3 hours but
    its last output was 20s ago → RUNNING."""
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "pnr", "status": "RUNNING"}],
                 log_age_s=20.0, with_pid=os.getpid())
    rep = RS.status(p, "phase3")
    assert rep["state"] == "RUNNING_ON_TIME"
    assert rep["silence_s"] < 600
    # no per-step duration budget appears in the verdict
    assert "budget" not in rep.get("reason", "").lower()


def test_not_stuck_within_silence_window(tmp_path):
    """Silence below the window (even at 9 minutes, under the 600s... wait,
    540s < 600s default) is RUNNING, not STUCK."""
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "pnr", "status": "RUNNING"}],
                 log_age_s=540.0, with_pid=os.getpid())
    rep = RS.status(p, "phase3")
    assert rep["state"] == "RUNNING_ON_TIME"


def test_per_step_silence_override(tmp_path):
    """A step with a longer legitimate silence (lvs: Magic ext2spice can
    extract quietly for 1200s) is RUNNING at 900s silence where pnr
    (600s window) would be STUCK."""
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "lvs", "status": "RUNNING"}],
                 log_age_s=900.0, with_pid=os.getpid())
    rep = RS.status(p, "phase3")
    assert rep["state"] == "RUNNING_ON_TIME"   # 900 < lvs window 1200
    # but explicit small override flips it to STUCK
    rep2 = RS.status(p, "phase3", max_silence_s=300)
    assert rep2["state"] == "STUCK"


# ── RUNNING_ON_TIME ──────────────────────────────────────────────────────────

def test_running_on_time_reports_step(tmp_path):
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "synth", "status": "PASS"},
                        {"name": "pnr", "status": "RUNNING"}],
                 log_age_s=30.0, with_pid=os.getpid())
    rep = RS.status(p, "phase3")
    assert rep["state"] == "RUNNING_ON_TIME"
    assert rep["current_step"] == "pnr"
    assert rep["steps_completed"] == 1
    assert rep["silence_s"] is not None


# ── no-PID: silence is still decisive evidence ───────────────────────────────

def test_running_when_no_pid_but_fresh(tmp_path):
    """No PID to confirm liveness, but output is fresh → RUNNING (not
    blocked on liveness — fresh output IS progress)."""
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "pnr", "status": "RUNNING"}],
                 log_age_s=10.0)  # no pid
    rep = RS.status(p, "phase3")
    assert rep["state"] == "RUNNING"
    assert "not confirmed" in rep.get("note", "")


def test_stuck_inferred_when_no_pid_but_silent(tmp_path):
    """No PID, but silent beyond the window → STUCK (the log mtime is the
    real timestamp of the last heartbeat; we don't need the PID)."""
    p = _project(tmp_path, verdict=None,
                 steps=[{"name": "pnr", "status": "RUNNING"}],
                 log_age_s=5000.0)  # no pid, very silent
    rep = RS.status(p, "phase3")
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
    art = require_repo("benchmark_ic/5th__opentitan_aes_v0338")
    rep_f = art / "reports" / "orchestrator" / "phase3_one_shot.json"
    if not rep_f.is_file():
        pytest.skip("real phase3 report not on this host (live corpus)")
    rep = RS.status(art, "phase3")
    assert rep["state"] == "DONE"
    assert rep["verdict"] is not None


# --- the one-line summary rendered "I do not know" as a number

def test_no_heartbeat_is_named_not_rendered_as_a_duration():
    """`silence_s` is None when there is no heartbeat file AT ALL.

    That is not "silent for N seconds" — it means the run has written nothing
    yet, which is the state an operator most needs to see. Unguarded, the
    f-string produced:

        RUNNING — step 'None' (0 done), last output Nones ago

    "Nones" reads as a number that failed to render, so the eye slides past it;
    the distinct state it stands for disappears. Found by running the watchdog
    against an empty project while sweeping for gates that pass on nothing.

    The two neighbouring call sites in the same file (the DIED reason and the
    RUNNING_ON_TIME reason) already guard this exact value. This one was the
    outlier, which is the usual shape: the guard exists, and one site missed it.
    """
    import run_status as RS
    line = RS.summarize({"state": "RUNNING", "current_step": None,
                         "steps_completed": 0, "silence_s": None,
                         "max_silence_s": 600, "eta_hint_s": 1200})
    assert "Nones" not in line
    assert "NO OUTPUT YET" in line


def test_a_real_silence_still_reads_as_a_duration():
    """…or the fix is satisfied by never printing the number at all."""
    import run_status as RS
    line = RS.summarize({"state": "RUNNING", "current_step": "step07",
                         "steps_completed": 3, "silence_s": 42.0,
                         "max_silence_s": 600, "eta_hint_s": 1200})
    assert "last output 42.0s ago" in line
    assert "NO OUTPUT YET" not in line


def test_a_missing_eta_is_named_too():
    """Same value, same shape, one field over — `~Nones` for an absent ETA."""
    import run_status as RS
    line = RS.summarize({"state": "RUNNING", "current_step": "step07",
                         "steps_completed": 3, "silence_s": 42.0,
                         "max_silence_s": 600, "eta_hint_s": None})
    assert "Nones" not in line
    assert "no ETA hint" in line
