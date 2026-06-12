#!/usr/bin/env python3
"""run_status.py — ORGANIC #599. Universal runner watchdog.

Any long-running runner step can hang silently — phase1 text extraction
on a pathological doc, phase2 synth in yosys, phase3 route/DRC/LVS in
OpenROAD/Magic, an analog SPICE corner sweep, the orchestrator between
phases. The only wait mechanisms an agent has (background
`until ! ps -p PID` or a Monitor on the log) FIRE ONLY ON PROCESS EXIT,
so a hung process (PID alive, zero forward progress) is indistinguishable
from normal running — silence means BOTH, and the agent waits forever.

This is a BOUNDED ONE-SHOT probe (no new instrumentation, reads only
existing artifacts) that returns ONE of four states in seconds for any
phase:

  DONE             — the phase's reports/orchestrator/<phase>_one_shot.json
                     carries a final verdict → report it.
  DIED             — a recorded PID is gone AND no final verdict was
                     written → abnormal exit + last log line.
  STUCK            — PID alive AND elapsed > the step's deadline budget
                     AND the live log / latest artifact mtime is stale
                     (no heartbeat for > the stale window) → OVERDUE +
                     the step it's on + last log line + last-artifact age.
                     This is the watchdog half that makes a hang VISIBLE.
  RUNNING_ON_TIME  — PID alive, within budget, log/artifact mtime fresh
                     → current step + ETA.

Wire it as the canonical answer to a 'check status' request and as the
field-agent-loop heartbeat (#598 artifact-first): launch async, record
PID, and each status check is this one bounded probe — never block on a
watcher.

Exit codes: 0 = DONE, 0 = RUNNING_ON_TIME, 1 = STUCK, 2 = DIED,
3 = UNKNOWN/no-run. chip-AGNOSTIC: artifact paths + numeric budgets only.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Per-step expected-duration budget in SECONDS (a coarse table; a step
# running well past its budget WITHOUT a fresh heartbeat is STUCK). These
# are deliberately generous — the STUCK signal also requires a stale
# heartbeat, so the budget only gates WHEN we start checking liveness.
_STEP_BUDGET_S: Dict[str, int] = {
    # phase1
    "phase1_ingest_render": 300,
    "phase1": 300,
    # phase2
    "yosys_synth": 600,
    "synth": 600,
    "reference_tb": 600,
    "fpga_compile": 1800,
    "simulation": 900,
    # phase3
    "pnr": 1800,          # route can be ~21 min on a large design
    "gds": 600,
    "drc": 900,
    "lvs": 900,
    "sta": 300,
    # analog
    "corner_sweep": 1200,
    "spice": 900,
}
_DEFAULT_STEP_BUDGET_S = 1200
# A heartbeat (live log / newest artifact mtime) older than this while
# the PID is alive and past budget is the STUCK signal.
_DEFAULT_STALE_WINDOW_S = 300

_PHASE_REPORTS = {
    "phase1": "phase1_one_shot.json",
    "phase2": "phase2_one_shot.json",
    "phase3": "phase3_one_shot.json",
    "phase23": "phase23_one_shot.json",
    "analog": "analog_one_shot.json",
    "orchestrator": "vibe_ic_one_shot.json",
}
# Where each phase's live log most plausibly lives (newest match wins).
_PHASE_LOG_GLOBS = {
    "phase1": ["reports/orchestrator/logs/phase1*.log"],
    "phase2": ["phase2/stage2/synth/*.log",
               "reports/orchestrator/logs/phase2*.log"],
    "phase3": ["phase3/stage3/pnr/openroad.log",
               "phase3/**/*.log",
               "reports/orchestrator/logs/phase3*.log"],
    "phase23": ["reports/orchestrator/logs/phase*.log"],
    "analog": ["phase3/analog/**/*.log", "phase2/analog/**/*.log"],
    "orchestrator": ["reports/orchestrator/logs/*.log"],
}
_RUN_PID_FILE = "run.pid"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_report(project: Path, phase: str) -> Optional[dict]:
    fname = _PHASE_REPORTS.get(phase)
    if not fname:
        return None
    for cand in (project / "reports" / "orchestrator" / fname,
                 project / "reports" / fname):
        if cand.is_file():
            try:
                return json.loads(cand.read_text(errors="replace"))
            except Exception:
                return None
    return None


def _newest_log(project: Path, phase: str) -> Optional[Path]:
    newest: Optional[Path] = None
    newest_m = -1.0
    for pat in _PHASE_LOG_GLOBS.get(phase, []):
        for p in project.glob(pat):
            if p.is_file():
                m = p.stat().st_mtime
                if m > newest_m:
                    newest_m, newest = m, p
    return newest


def _newest_artifact_mtime(project: Path, phase: str) -> Optional[float]:
    """Newest mtime among the phase's plausible output trees (heartbeat
    fallback when no log)."""
    roots = {
        "phase1": ["phase1/generated_docs"],
        "phase2": ["phase2/stage2", "phase2/stage1"],
        "phase3": ["phase3/stage3"],
        "phase23": ["phase2", "phase3"],
        "analog": ["phase3/analog", "phase2/analog"],
        "orchestrator": ["reports"],
    }.get(phase, ["reports"])
    newest = -1.0
    for r in roots:
        base = project / r
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            try:
                if p.is_file():
                    newest = max(newest, p.stat().st_mtime)
            except OSError:
                continue
    return newest if newest > 0 else None


def _completed_steps(report: dict) -> List[dict]:
    steps = report.get("steps") or report.get("plan") or []
    return steps if isinstance(steps, list) else []


def _current_step(report: Optional[dict]) -> Tuple[Optional[str], int]:
    """Return (current_step_name, n_completed). The current step is the
    first non-terminal one, else the last."""
    if not report:
        return None, 0
    steps = _completed_steps(report)
    done = 0
    for s in steps:
        if not isinstance(s, dict):
            continue
        st = str(s.get("status", "")).upper()
        if st in ("PASS", "SKIP", "WAIVED", "SKIPPED-CONDITION",
                  "ENV_UNAVAILABLE", "COVERAGE-INCOMPLETE"):
            done += 1
        else:
            return str(s.get("name") or "?"), done
    last = steps[-1].get("name") if steps and isinstance(steps[-1], dict) \
        else None
    return last, done


def _last_log_line(log: Optional[Path]) -> str:
    if not log or not log.is_file():
        return ""
    try:
        tail = log.read_text(errors="replace").splitlines()
        for ln in reversed(tail):
            if ln.strip():
                return ln.strip()[:300]
    except Exception:
        pass
    return ""


def _resolve_pid(project: Path, pid_arg: Optional[int]) -> Optional[int]:
    """Resolve the runner PID: explicit --pid, else <project>/run.pid,
    else the holder pid recorded in the existing single-driver lock
    (<project>/.runner.lock, #588) — reusing an EXISTING artifact rather
    than requiring a new run.pid convention."""
    if pid_arg:
        return pid_arg
    pf = project / _RUN_PID_FILE
    if pf.is_file():
        try:
            return int(pf.read_text().strip().split()[0])
        except Exception:
            pass
    lock = project / ".runner.lock"
    if lock.is_file():
        try:
            d = json.loads(lock.read_text())
            v = int(d.get("pid", -1))
            return v if v > 0 else None
        except Exception:
            return None
    return None


def status(project: Path, phase: str, pid: Optional[int] = None,
           stale_window_s: int = _DEFAULT_STALE_WINDOW_S,
           now: Optional[float] = None) -> dict:
    """Compute the run-status verdict. `now` overridable for testing."""
    now = time.time() if now is None else now
    report = _read_report(project, phase)
    verdict_in_report = (report or {}).get("verdict")
    cur_step, n_done = _current_step(report)
    log = _newest_log(project, phase)
    hb_mtime = log.stat().st_mtime if (log and log.is_file()) \
        else _newest_artifact_mtime(project, phase)
    hb_age = (now - hb_mtime) if hb_mtime else None
    resolved_pid = _resolve_pid(project, pid)
    alive = _pid_alive(resolved_pid) if resolved_pid else None
    budget = _STEP_BUDGET_S.get(cur_step or "", _DEFAULT_STEP_BUDGET_S)

    base = {
        "phase": phase,
        "current_step": cur_step,
        "steps_completed": n_done,
        "pid": resolved_pid,
        "pid_alive": alive,
        "heartbeat_log": str(log) if log else None,
        "heartbeat_age_s": round(hb_age, 1) if hb_age is not None else None,
        "step_budget_s": budget,
        "last_log_line": _last_log_line(log),
    }

    # DONE — a final verdict was written.
    if verdict_in_report:
        base["state"] = "DONE"
        base["verdict"] = verdict_in_report
        return base

    # No verdict yet. Decide DIED / STUCK / RUNNING_ON_TIME / UNKNOWN.
    if resolved_pid is None or alive is None:
        # No PID to probe → cannot assert liveness; fall back to
        # heartbeat-only inference.
        if hb_age is not None and hb_age > max(stale_window_s, budget):
            base["state"] = "STUCK"
            base["reason"] = (
                f"no PID recorded; heartbeat stale {hb_age:.0f}s "
                f"(> {max(stale_window_s, budget)}s) with no final verdict")
            return base
        base["state"] = "UNKNOWN"
        base["reason"] = ("no PID recorded and no final verdict; "
                          "heartbeat fresh — pass --pid or drop run.pid "
                          "for a definitive liveness probe")
        return base

    if not alive:
        # DIED — PID gone, no verdict written.
        base["state"] = "DIED"
        base["reason"] = (f"PID {resolved_pid} is gone but no final verdict "
                          f"was written — abnormal exit")
        return base

    # PID alive, no verdict. STUCK iff past budget AND heartbeat stale.
    over_budget = (hb_age is not None and hb_age > budget)
    stale = (hb_age is not None and hb_age > stale_window_s)
    if over_budget and stale:
        base["state"] = "STUCK"
        base["reason"] = (
            f"PID {resolved_pid} alive but step '{cur_step}' OVERDUE: "
            f"heartbeat stale {hb_age:.0f}s (> budget {budget}s, > stale "
            f"window {stale_window_s}s) — likely hung, not progressing")
        return base

    base["state"] = "RUNNING_ON_TIME"
    eta = None
    if hb_age is not None:
        eta = max(0, budget - hb_age)
    base["eta_s"] = round(eta, 1) if eta is not None else None
    return base


def summarize(rep: dict) -> str:
    st = rep.get("state")
    step = rep.get("current_step")
    if st == "DONE":
        return f"DONE — verdict={rep.get('verdict')} ({rep['phase']})"
    if st == "DIED":
        return (f"DIED — {rep.get('reason')}; last log: "
                f"{rep.get('last_log_line') or '(none)'}")
    if st == "STUCK":
        return (f"STUCK — {rep.get('reason')}; last log: "
                f"{rep.get('last_log_line') or '(none)'}")
    if st == "RUNNING_ON_TIME":
        return (f"RUNNING_ON_TIME — step '{step}' "
                f"({rep.get('steps_completed')} done), heartbeat "
                f"{rep.get('heartbeat_age_s')}s ago, ETA "
                f"~{rep.get('eta_s')}s")
    return f"UNKNOWN — {rep.get('reason')}"


_EXIT = {"DONE": 0, "RUNNING_ON_TIME": 0, "STUCK": 1, "DIED": 2,
         "UNKNOWN": 3}


def _detect_phase(project: Path) -> str:
    """auto: the phase with the newest one_shot.json (most recent run),
    else phase3 if its tree exists, else orchestrator."""
    newest_phase, newest_m = None, -1.0
    for ph, fname in _PHASE_REPORTS.items():
        for cand in (project / "reports" / "orchestrator" / fname,
                     project / "reports" / fname):
            if cand.is_file():
                m = cand.stat().st_mtime
                if m > newest_m:
                    newest_m, newest_phase = m, ph
    if newest_phase:
        return newest_phase
    if (project / "phase3").is_dir():
        return "phase3"
    return "orchestrator"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project")
    p.add_argument("--phase", default="auto",
                   choices=["auto", "phase1", "phase2", "phase3", "phase23",
                            "analog", "orchestrator"])
    p.add_argument("--pid", type=int, default=None,
                   help="runner PID (else read <project>/run.pid)")
    p.add_argument("--stale-window-s", type=int,
                   default=_DEFAULT_STALE_WINDOW_S)
    p.add_argument("--json", default=None)
    args = p.parse_args(argv if argv is not None else None)
    project = Path(args.project)
    if not project.is_dir():
        print(f"error: not a directory: {project}")
        return 3
    phase = _detect_phase(project) if args.phase == "auto" else args.phase
    rep = status(project, phase, pid=args.pid,
                 stale_window_s=args.stale_window_s)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(rep, indent=2) + "\n")
    print(summarize(rep))
    return _EXIT.get(rep.get("state", "UNKNOWN"), 3)


if __name__ == "__main__":
    raise SystemExit(main())
