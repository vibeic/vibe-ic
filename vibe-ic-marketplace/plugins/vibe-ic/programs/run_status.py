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
  STUCK            — PID alive AND no verdict AND OBSERVED SILENCE (now −
                     last log/artifact mtime) exceeds the step's silence
                     window → the step it's on + last log line + silence
                     age. The silence window is "the longest a HEALTHY
                     tool plausibly goes without ANY output" (a tool
                     property, NOT a per-step duration budget that depends
                     on design size) — so a large run that keeps writing
                     stays RUNNING however long it takes, and a hang
                     surfaces within one silence window of its onset.
                     This is the watchdog half that makes a hang VISIBLE.
  RUNNING_ON_TIME  — PID alive, log/artifact mtime fresh (within the
                     silence window) → current step (+ ETA hint).

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
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _shape_refusal as _sr  # noqa: E402  (#991)

# ── Liveness doctrine (v0.3.46, addressing the budget-guess critique) ───────
# The STUCK signal is NOT "elapsed > a guessed per-step duration budget".
# A per-step duration depends heavily on cell count / die size, so any
# fixed table is a guess that is two-ways wrong: too large and a real
# hang is detected only after a long forced wait; too small and a
# legitimately slow run is mis-flagged.
#
# Instead the hang evidence is the OBSERVED SILENCE: a healthy long run —
# however large, however many hours — keeps writing its log and updating
# artifact mtimes (route writes per-stage checkpoint DEFs, DRC/LVS append
# transcripts), so its heartbeat stays fresh and it is PROGRESSING
# regardless of total runtime. A hung run's heartbeat STOPS. So:
#
#   STUCK = PID alive AND no final verdict AND
#           (now - last_heartbeat_mtime) > MAX_SILENCE_WINDOW
#
# MAX_SILENCE_WINDOW is "the longest a healthy EDA tool plausibly goes
# without emitting ANY log line or touching ANY artifact" — it depends
# only on tool behaviour, NOT on design size, so it is not a runtime
# guess. `silence = now - last_heartbeat_mtime` is computable from a
# SINGLE probe (the log's mtime IS the timestamp of the last heartbeat),
# so the watchdog never has to first idle through a budget before it can
# answer. Frequent cheap probes + this silence test = a hang surfaces
# within MAX_SILENCE_WINDOW of its onset, independent of step duration.
_DEFAULT_MAX_SILENCE_S = 600   # 10 min of ZERO output ⇒ hung, not slow
# Per-step silence tolerance OVERRIDES (only where a tool legitimately
# computes silently for longer than the default — e.g. Magic ext2spice on
# a huge extraction). These are SILENCE windows, NOT duration budgets.
_STEP_MAX_SILENCE_S: Dict[str, int] = {
    "lvs": 1200,          # Magic ext2spice can extract quietly
    "drc": 900,
    "fpga_compile": 900,  # Quartus place&route phases log sparsely
}

# Per-step EXPECTED duration in SECONDS — INFORMATIONAL ONLY (ETA
# display). NEVER used to decide STUCK (that is the silence test above).
_STEP_ETA_S: Dict[str, int] = {
    "phase1_ingest_render": 300, "phase1": 300,
    "yosys_synth": 600, "synth": 600, "reference_tb": 600,
    "fpga_compile": 1800, "simulation": 900,
    "pnr": 1800, "gds": 600, "drc": 900, "lvs": 900, "sta": 300,
    "corner_sweep": 1200, "spice": 900,
}
_DEFAULT_ETA_S = 1200

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


def _completed_steps(report: dict
                     ) -> Tuple[List[dict], Optional[Dict[str, Any]]]:
    """`(steps, mismatch)`.

    #991 — this was `steps if isinstance(steps, list) else []`, and the
    coerced empty was BYTE-IDENTICAL to a report with no `steps` key: both
    produced `current_step: null, steps_completed: 0`, and 86 of the 176
    reports published in this tree legitimately have no `steps` key at all.
    MEASURED, the two states are NOT equivalent for this program — a report
    whose plan is unreadable also loses the per-step silence window, so
    `max_silence_s` silently reverts from the step's own tolerance to the
    600s default and a healthy quiet step is called STUCK.
    """
    for key in ("steps", "plan"):
        v = (report or {}).get(key)
        if v:                     # preserves the original `or` chain exactly:
            return _sr.read_list(v, key)   # a falsy value falls through
    return [], None


def _current_step(report: Optional[dict]
                  ) -> Tuple[Optional[str], int, Optional[Dict[str, Any]]]:
    """Return (current_step_name, n_completed, plan_mismatch). The current
    step is the first non-terminal one, else the last. `plan_mismatch` is the
    stated description of a plan this program could not read — never `None`
    merely because the plan was empty."""
    if not report:
        return None, 0, None
    steps, mismatch = _completed_steps(report)
    if mismatch is not None:
        # NOT "no steps done". This program does not know how many are done;
        # saying 0 would be a measurement it did not make.
        return None, 0, mismatch
    done = 0
    for s in steps:
        if not isinstance(s, dict):
            continue
        st = str(s.get("status", "")).upper()
        if st in ("PASS", "SKIP", "WAIVED", "SKIPPED-CONDITION",
                  "ENV_UNAVAILABLE", "COVERAGE-INCOMPLETE"):
            done += 1
        else:
            return str(s.get("name") or "?"), done, None
    last = steps[-1].get("name") if steps and isinstance(steps[-1], dict) \
        else None
    return last, done, None


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
           max_silence_s: Optional[int] = None,
           now: Optional[float] = None) -> dict:
    """Compute the run-status verdict. `now` overridable for testing.

    The STUCK test is silence-based (see the liveness doctrine above):
    PID alive + no verdict + observed silence exceeding the step's
    MAX_SILENCE_WINDOW. No per-step DURATION budget gates the decision —
    a healthy run of any size that keeps writing stays RUNNING."""
    now = time.time() if now is None else now
    report = _read_report(project, phase)
    verdict_in_report = (report or {}).get("verdict")
    cur_step, n_done, plan_unreadable = _current_step(report)
    log = _newest_log(project, phase)
    # Heartbeat = the most recent of (live log mtime, newest artifact
    # mtime). A run that touches EITHER is making progress. `silence` is
    # how long since that last observed output.
    log_m = log.stat().st_mtime if (log and log.is_file()) else None
    art_m = _newest_artifact_mtime(project, phase)
    hb_mtime = max([m for m in (log_m, art_m) if m is not None], default=None)
    silence = (now - hb_mtime) if hb_mtime else None
    resolved_pid = _resolve_pid(project, pid)
    alive = _pid_alive(resolved_pid) if resolved_pid else None
    # Silence tolerance: per-step override else default. This is the
    # longest a HEALTHY tool plausibly goes silent — a tool property, not
    # a runtime guess.
    silence_window = (max_silence_s if max_silence_s is not None
                      else _STEP_MAX_SILENCE_S.get(cur_step or "",
                                                   _DEFAULT_MAX_SILENCE_S))
    eta_hint = _STEP_ETA_S.get(cur_step or "", _DEFAULT_ETA_S)

    base = {
        "phase": phase,
        "current_step": cur_step,
        "steps_completed": n_done,
        # #991 — stated, not inferred. `None` when the plan was readable (or
        # legitimately absent); otherwise the description of what arrived, so
        # `current_step: null, steps_completed: 0` can never be read as "this
        # run has not started a step" when the truth is "I could not read the
        # plan". `steps_completed` is 0 in BOTH cases and only this key tells
        # them apart.
        "plan_unreadable": plan_unreadable,
        "pid": resolved_pid,
        "pid_alive": alive,
        "heartbeat_log": str(log) if log else None,
        "silence_s": round(silence, 1) if silence is not None else None,
        "max_silence_s": silence_window,
        "eta_hint_s": eta_hint,           # INFORMATIONAL only, not a gate
        "last_log_line": _last_log_line(log),
    }

    # DONE — a final verdict was written.
    if verdict_in_report:
        base["state"] = "DONE"
        base["verdict"] = verdict_in_report
        return base

    # No verdict. The STUCK evidence is OBSERVED SILENCE beyond the
    # tolerance window — applies whether or not we can probe the PID
    # (the log's mtime is the real timestamp of the last heartbeat).
    silent_too_long = (silence is not None and silence > silence_window)

    # NO EVIDENCE OF A RUN AT ALL is its own answer, and until v1.9.78 this
    # program did not have it — the `UNKNOWN` state its own docstring and
    # `_EXIT` table promise (rc 3, "UNKNOWN/no-run") was unreachable, so a
    # directory with no report, no recorded PID and no artifact of any kind
    # fell through to `RUNNING` and exited 0.
    #
    # MEASURED on `benchmark-data/ic/sha256/clean_run_v1432int_commercial`,
    # whose NDA whitelist publishes RESULT.md and nothing else: this printed
    #     RUNNING — step 'None' (0 done), NO OUTPUT YET (no heartbeat file)
    # and returned 0. Both halves are wrong in the same direction as #590: a
    # caller that asks "is the runner done, hung or dead?" is told a run is in
    # flight, and the exit code says nothing is wrong — over a directory in
    # which nothing has ever been observed to run.
    #
    # A JUST-LAUNCHED RUN IS NOT THIS CASE and must not be caught by it: the
    # runner records `run.pid` / `.runner.lock`, so `resolved_pid` is set and
    # the RUNNING_ON_TIME branch below answers "running; no heartbeat artifact
    # observed yet". The distinction is a live PID, which is exactly the
    # difference between "started and quiet" and "nothing here".
    if hb_mtime is None and resolved_pid is None:
        base["state"] = "UNKNOWN"
        base["reason"] = (
            "no final verdict, no recorded PID and no log or artifact of any "
            "kind under this project — there is no run here to report on. "
            "This is NOT a pass and NOT a run in progress; it is the absence "
            "of anything to look at")
        return base

    if resolved_pid is None or alive is None:
        # No PID to probe liveness. Silence is still decisive evidence.
        if silent_too_long:
            base["state"] = "STUCK"
            base["reason"] = (
                f"no output for {silence:.0f}s (> {silence_window}s "
                f"silence window) and no final verdict — hung (no PID to "
                f"confirm liveness; pass --pid / .runner.lock for certainty)")
            return base
        base["state"] = "RUNNING"
        base["reason"] = (f"fresh output {silence:.0f}s ago" if silence
                          is not None else "no heartbeat artifact yet")
        base["note"] = ("no PID recorded — liveness not confirmed, but "
                        "output is fresh so the run is progressing")
        return base

    if not alive:
        # DIED — PID gone, no verdict written. Unambiguous.
        base["state"] = "DIED"
        base["reason"] = (f"PID {resolved_pid} is gone but no final verdict "
                          f"was written — abnormal exit")
        return base

    # PID alive, no verdict. STUCK iff silent beyond the window.
    if silent_too_long:
        base["state"] = "STUCK"
        base["reason"] = (
            f"PID {resolved_pid} alive but step '{cur_step}' has produced "
            f"NO output for {silence:.0f}s (> {silence_window}s silence "
            f"window) — hung, not progressing (the run is not slow: a "
            f"healthy run of any size keeps writing within this window)")
        return base

    base["state"] = "RUNNING_ON_TIME"
    base["reason"] = (f"fresh output {silence:.0f}s ago (< {silence_window}s "
                      f"silence window) — progressing" if silence is not None
                      else "running; no heartbeat artifact observed yet")
    return base


def summarize(rep: dict) -> str:
    st = rep.get("state")
    step = rep.get("current_step")
    # #991 — the ONE line an operator actually reads. Without this, an
    # unreadable plan renders as `step 'None' (0 done)`, which is exactly what
    # a run that has completed nothing renders as, and the silence window that
    # decided this verdict silently reverted to the default. Prefixed rather
    # than appended so it cannot be cut off by a terminal width.
    _pu = rep.get("plan_unreadable")
    _pfx = ""
    if _pu:
        _pfx = (f"PLAN UNREADABLE ({_sr.sentence(_pu)}) — `current_step` and "
                f"`steps_completed` below are NOT measurements, and the "
                f"silence window is the {rep.get('max_silence_s')}s DEFAULT "
                f"rather than this step's own. ")
        return _pfx + _summarize_state(rep, st, step)
    return _summarize_state(rep, st, step)


def _summarize_state(rep: dict, st: Any, step: Any) -> str:
    if st == "DONE":
        return f"DONE — verdict={rep.get('verdict')} ({rep['phase']})"
    if st == "DIED":
        return (f"DIED — {rep.get('reason')}; last log: "
                f"{rep.get('last_log_line') or '(none)'}")
    if st == "STUCK":
        return (f"STUCK — {rep.get('reason')}; last log: "
                f"{rep.get('last_log_line') or '(none)'}")
    if st in ("RUNNING_ON_TIME", "RUNNING"):
        # `silence_s` is None when there is no heartbeat file AT ALL — the run
        # has produced no output ever, which is a different state from "silent
        # for N seconds" and the one an operator most wants to see. Unguarded,
        # the f-string rendered it as `last output Nones ago`: a reader skims
        # that as a number they cannot parse rather than as "nothing has been
        # written yet". The two neighbouring call sites (the DIED and
        # RUNNING_ON_TIME reasons) already guard the same value; this one was
        # the outlier.
        sil = rep.get("silence_s")
        eta = rep.get("eta_hint_s")
        return (f"{st} — step '{step}' "
                f"({rep.get('steps_completed')} done), "
                + (f"last output {sil}s ago" if sil is not None
                   else "NO OUTPUT YET (no heartbeat file)")
                + f" (silence window {rep.get('max_silence_s')}s"
                + (f"; ETA hint ~{eta}s)" if eta is not None
                   else "; no ETA hint — nothing timed yet)"))
    return f"UNKNOWN — {rep.get('reason')}"


_EXIT = {"DONE": 0, "RUNNING_ON_TIME": 0, "RUNNING": 0, "STUCK": 1,
         "DIED": 2, "UNKNOWN": 3}


#: The linear phases, earliest first. `analog` and `phase23` are alternative
#: shapes rather than points on this line, so they are not ordered here — they
#: are still selected when they are the only evidence present.
_PHASE_ORDER = ("phase1", "phase2", "phase3")


def _phase_was_reached(project: Path, phase: str) -> bool:
    """Did the run GET to this phase — whether or not it finished it?

    Evidence, in the order it becomes available to a phase that is running:
    its working tree, any log it writes, or its final report. A phase that
    was killed has the first two and not the third, and that is exactly the
    case `_detect_phase` used to be unable to see.
    """
    for fname in (project / "reports" / "orchestrator" / _PHASE_REPORTS[phase],
                  project / "reports" / _PHASE_REPORTS[phase]):
        if fname.is_file():
            return True
    if phase in ("phase2", "phase3") and (project / phase).is_dir():
        return True
    for pat in _PHASE_LOG_GLOBS.get(phase, []):
        try:
            if any(project.glob(pat)):
                return True
        except (OSError, ValueError):
            continue
    return False


def _detect_phase(project: Path) -> str:
    """auto: the FURTHEST phase the run reached, not the newest report.

    THE DEFECT (vibe-ic#590). This took "the phase with the newest
    `one_shot.json`". A phase that was KILLED never writes one, so the only
    report on disk belonged to the last phase that SUCCEEDED — and `auto`
    selected it. The failure mode chose the phase that hides it, and the later
    a run died the more confidently this reported success:

        killed mid-phase2, phase3 never started
          auto          DONE — verdict=PASS (phase1)      rc 0
          --phase phase2  STUCK — no output for 8221s     (the true answer)

    Ordering by REACH inverts that. A phase with a working tree or a log and no
    report is FURTHER than one that completed, because completing is what
    produced the report the other one lacks. `phase23` and `analog` are
    alternative run shapes rather than points on the phase1->3 line, so they are
    chosen only when nothing on that line was reached.
    """
    # AN ORCHESTRATOR VERDICT MEANS THE RUN FINISHED, and it outranks reach.
    # Ordering by reach without this check calls a COMPLETED run dead: phase3
    # legitimately writes no report of its own when it is skipped or waived, so
    # its tree exists, its report does not, and reach alone reads that as "died
    # in phase3". Measured over the 182 tracked run dirs while writing this —
    # 11 flipped 0 -> 1/2, and 3 of the first 4 inspected (ibex, sha256,
    # opentitan_aes on the commercial PDK) had an orchestrator verdict on disk.
    # Those are finished runs and calling them STUCK would be a false finding
    # of exactly the kind this program exists to remove.
    for cand in (project / "reports" / "orchestrator" / _PHASE_REPORTS["orchestrator"],
                 project / "reports" / _PHASE_REPORTS["orchestrator"]):
        if cand.is_file():
            return "orchestrator"

    for phase in reversed(_PHASE_ORDER):
        if _phase_was_reached(project, phase):
            return phase
    # Off-line shapes: whichever left a report, newest first — the old rule,
    # which is correct when there is no linear phase to be further than.
    newest_phase, newest_m = None, -1.0
    for ph in ("phase23", "analog", "orchestrator"):
        for cand in (project / "reports" / "orchestrator" / _PHASE_REPORTS[ph],
                     project / "reports" / _PHASE_REPORTS[ph]):
            if cand.is_file():
                m = cand.stat().st_mtime
                if m > newest_m:
                    newest_m, newest_phase = m, ph
    if newest_phase:
        return newest_phase
    return "orchestrator"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project")
    p.add_argument("--phase", default="auto",
                   choices=["auto", "phase1", "phase2", "phase3", "phase23",
                            "analog", "orchestrator"])
    p.add_argument("--pid", type=int, default=None,
                   help="runner PID (else read <project>/run.pid or "
                        ".runner.lock)")
    p.add_argument("--max-silence-s", type=int, default=None,
                   help="STUCK when no log/artifact output for this many "
                        "seconds (default per-step; a SILENCE window, not a "
                        "duration budget — independent of design size)")
    p.add_argument("--json", default=None)
    args = p.parse_args(argv if argv is not None else None)
    project = Path(args.project)
    if not project.is_dir():
        print(f"error: not a directory: {project}")
        return 3
    phase = _detect_phase(project) if args.phase == "auto" else args.phase
    rep = status(project, phase, pid=args.pid,
                 max_silence_s=args.max_silence_s)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(rep, indent=2) + "\n")
    print(summarize(rep))
    return _EXIT.get(rep.get("state", "UNKNOWN"), 3)


if __name__ == "__main__":
    raise SystemExit(main())
