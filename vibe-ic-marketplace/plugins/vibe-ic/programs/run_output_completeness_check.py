#!/usr/bin/env python3
"""run_output_completeness_check.py — the EMPTY / MISSING / STUB deliverable gate.

WHY THIS EXISTS (owner directive 2026-07-08)
============================================
"為什麼常常沒寫 result 或 output 空? 一定要檢查出來為什麼，而且要能 identify 出來
這是有問題的。要有一個 gate，如果 result 空或 output 空就 highlight + 找出問題 +
capture 到 enhancement." — an empty RESULT / empty output must NEVER pass silently.

ROOT CAUSE this gate defends against (observed 3× in one session)
-----------------------------------------------------------------
An agent that delegates a multi-hour run launches the runner as a DETACHED
background process, then its turn ENDS (idle). When the detached process later
finishes, NOTHING re-invokes the agent, so the agent's "then write RESULT.md"
step NEVER runs. The runner's OWN outputs (``reports/final_summary.md`` /
orchestrator ``*_one_shot.json`` verdict / GDS/SPEF artifacts) exist, but the
agent's synthesis deliverable (``RESULT.md``) is never written. Nothing catches
it because every gate keyed off the runner's outputs is green. THIS gate keys
off the DELIVERABLE and names that exact failure mode loudly:
``COMPUTE_DONE_DELIVERABLE_MISSING`` — the launch-and-idle abandon bug.

This is complementary to two neighbours, not a duplicate:
  * ``run_status.py``            answers "is the RUNNER PROCESS done/hung/dead?"
                                 (process + heartbeat). This program answers
                                 "is the DELIVERABLE actually written + real?"
  * ``benchmark_result_md_lint`` answers "does a PRESENT RESULT.md carry the 7
                                 mandatory §6 sections?". This program answers
                                 the prior question — "is there a real,
                                 non-empty, non-stub deliverable AT ALL, and if
                                 not WHY?".

THE FAILURE-MODE TAXONOMY (the WHY is automatic, not a guess)
============================================================
For the run's declared deliverable (default ``RESULT.md``) the classifier emits
exactly one state, each with the evidence it judged on:

  COMPLETE                        — deliverable present, >= a real-content byte
                                    threshold, real section content (not header-
                                    only / not a stub marker), and every declared
                                    artifact/agent-output present + non-empty.
                                    PASS (rc 0) — the only genuinely-done state.
  RUN_STILL_IN_PROGRESS           — the deliverable is not complete YET, but a
                                    runner process or a live ``.runner.lock`` is
                                    STILL ALIVE → this is NOT a fail, the agent
                                    just hasn't reached its write step. Distinct
                                    non-fail status (rc 3). Gated on a genuinely
                                    LIVE pid/lock so it can never mask a truly-
                                    abandoned run (a stale lock from a dead pid
                                    does NOT count as live).
  COMPUTE_DONE_DELIVERABLE_MISSING— the LOAD-BEARING case (the idle-abandon bug):
                                    the runner's compute finished (final_summary
                                    / orchestrator verdict / a declared artifact
                                    present) but RESULT.md is ABSENT or empty and
                                    no runner is live. FAIL (rc 1), loudest.
  DELIVERABLE_STUB                — RESULT.md EXISTS but is hollow (below the byte
                                    threshold, too few content lines, or all-
                                    placeholder). The write step ran but produced
                                    nothing real. FAIL (rc 1).
  RUN_DIED_EARLY                  — RESULT.md absent AND no final_summary AND no
                                    orchestrator verdict AND no artifacts → the
                                    run never got far enough to produce anything.
                                    FAIL (rc 1).
  DECLARED_ARTIFACT_MISSING       — RESULT.md itself is complete, but a
                                    ``--require-artifacts`` entry (or a
                                    ``--agent-output`` file) is missing/empty:
                                    the deliverable claims an output the run did
                                    not produce. FAIL (rc 1).

On any FAIL the program prints a LOUD HIGHLIGHT block and emits a machine-
readable ``capture_candidate`` (ingestible by the enhancement-capture flow —
``enhancement_emit.py`` schema) so an empty output is captured, never silent.

CLI
===
    run_output_completeness_check.py <run_dir>
        [--result <path>]                 # deliverable (default <run_dir>/RESULT.md)
        [--require-artifacts gds,spef,…]   # declared artifacts (ext or glob)
        [--agent-output <path>]            # a captured agent-return file to check
        [--claimed-verdict PASS|FAIL]      # what the run CLAIMED, for consistency
        [--pid N]                          # runner pid (else run.pid/.runner.lock)
        [--json OUT]

Exit codes
----------
    0  COMPLETE (PASS)
    0  ... nothing else maps to 0
    1  a FAIL classification (any of the four fail states above)
    2  usage error
    3  RUN_STILL_IN_PROGRESS  (distinct NON-FAIL — "in progress", do not block)

chip-AGNOSTIC + tool-AGNOSTIC + pure: reasons over file existence, byte sizes,
content-line counts, process liveness and generic artifact extensions only — no
IC / vendor / SKU literal appears as logic.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ── Real-content thresholds (calibrated against the live benchmark-data RESULT.md
#    corpus: the SMALLEST genuine deliverable is 1252 bytes / 16 content lines,
#    so these floors sit far below every real one and only a genuine empty /
#    header-only / stub file trips them). These are DELIVERABLE-content floors,
#    NOT a per-run size budget — a large run produces a larger RESULT, a small
#    run a smaller one, but neither dips below "a real paragraph of substance".
_MIN_REAL_BYTES = 400
_MIN_CONTENT_LINES = 3

# A line is "content" if it carries substance — not blank, not a bare markdown
# heading / horizontal rule / table separator / bullet marker with no text.
_NON_CONTENT_RE = re.compile(r"^\s*(#{1,6}\s.*|[-=*_]{3,}|\|[\s|:-]*\||[-*+]\s*)?$")
# Placeholder tokens that, when they are the WHOLE of the content, mean "stub".
_PLACEHOLDER_RE = re.compile(
    r"^\s*[-*+>#\s]*("
    r"todo|tbd|fixme|xxx|placeholder|to be written|to be filled|fill in|"
    r"coming soon|n/?a|pending|\.\.\.+|<[^>]*>)"
    r"[\s.:;,)\]]*$",
    re.IGNORECASE,
)

_RUN_PID_FILE = "run.pid"
_LOCK_FILE = ".runner.lock"

# Where a runner's OWN "compute finished" evidence plausibly lives. Newest,
# non-empty match wins. Kept in sync in spirit with run_status.py / _path_layout.
_FINAL_SUMMARY_GLOBS = [
    "reports/final_summary.md",
    "reports/orchestrator/final_summary.md",
    "final_summary.md",
]
_ORCH_REPORT_GLOBS = [
    "reports/orchestrator/*_one_shot.json",
    "reports/*_one_shot.json",
    "reports/orchestrator/vibe_ic_one_shot.json",
]


# ---------------------------------------------------------------------------
# Result data model.
# ---------------------------------------------------------------------------
@dataclass
class CompletenessReport:
    run_dir: str
    deliverable: str
    state: str                     # COMPLETE | RUN_STILL_IN_PROGRESS | … (see module doc)
    verdict: str                   # PASS | IN_PROGRESS | FAIL
    reason: str
    evidence: Dict[str, object] = field(default_factory=dict)
    blocking: List[str] = field(default_factory=list)
    highlight: str = ""
    capture_candidate: Optional[dict] = None
    claimed_verdict: Optional[str] = None

    @property
    def is_fail(self) -> bool:
        return self.verdict == "FAIL"

    @property
    def rc(self) -> int:
        return _EXIT.get(self.state, 2)


_EXIT = {
    "COMPLETE": 0,
    "RUN_STILL_IN_PROGRESS": 3,
    "COMPUTE_DONE_DELIVERABLE_MISSING": 1,
    "DELIVERABLE_STUB": 1,
    "RUN_DIED_EARLY": 1,
    "DECLARED_ARTIFACT_MISSING": 1,
}


# ---------------------------------------------------------------------------
# Low-level probes (pure).
# ---------------------------------------------------------------------------
def _pid_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
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


def _resolve_pid(run_dir: Path, pid_arg: Optional[int]) -> Optional[int]:
    """Resolve the runner pid: explicit --pid, else <run_dir>/run.pid, else the
    holder pid recorded in an existing <run_dir>/.runner.lock. Reuses EXISTING
    artifacts (run_status.py convention) — no new pid file convention."""
    if pid_arg:
        return pid_arg
    pf = run_dir / _RUN_PID_FILE
    if pf.is_file():
        try:
            return int(pf.read_text().strip().split()[0])
        except Exception:
            pass
    lock = run_dir / _LOCK_FILE
    if lock.is_file():
        try:
            d = json.loads(lock.read_text())
            v = int(d.get("pid", -1))
            return v if v > 0 else None
        except Exception:
            return None
    return None


def _liveness(run_dir: Path, pid_arg: Optional[int]) -> Dict[str, object]:
    """Is a runner genuinely LIVE for this run_dir? A stale lock (dead pid) is
    NOT live — that must not mask an abandoned run (the false-negative the owner
    directive forbids). RUN_STILL_IN_PROGRESS is gated on this returning
    live=True."""
    pid = _resolve_pid(run_dir, pid_arg)
    alive = _pid_alive(pid)
    lock = run_dir / _LOCK_FILE
    lock_exists = lock.is_file()
    lock_live = False
    if lock_exists:
        try:
            d = json.loads(lock.read_text())
            lock_pid = int(d.get("pid", -1))
            lock_live = _pid_alive(lock_pid)
        except Exception:
            lock_live = False
    live = bool(alive or lock_live)
    return {
        "pid": pid,
        "pid_alive": alive,
        "lock": str(lock) if lock_exists else None,
        "lock_live": lock_live,
        "live": live,
    }


def _content_lines(text: str) -> List[str]:
    """Lines carrying real substance (not blank / bare heading / rule / table
    separator / empty bullet)."""
    out = []
    for ln in text.splitlines():
        if _NON_CONTENT_RE.match(ln):
            continue
        out.append(ln.strip())
    return out


def _is_all_placeholder(content: List[str]) -> bool:
    """True iff EVERY content line is a placeholder token (a whole-file stub)."""
    if not content:
        return False
    return all(_PLACEHOLDER_RE.match(ln) for ln in content)


def _assess_deliverable(path: Path) -> Dict[str, object]:
    """Existence + real-content assessment of one deliverable file (pure)."""
    exists = path.is_file()
    if not exists:
        return {"exists": False, "bytes": 0, "content_lines": 0,
                "all_placeholder": False, "complete": False}
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
    except OSError:
        return {"exists": True, "bytes": 0, "content_lines": 0,
                "all_placeholder": False, "complete": False}
    nbytes = len(raw)
    content = _content_lines(text)
    all_ph = _is_all_placeholder(content)
    complete = (nbytes >= _MIN_REAL_BYTES
                and len(content) >= _MIN_CONTENT_LINES
                and not all_ph)
    return {"exists": True, "bytes": nbytes, "content_lines": len(content),
            "all_placeholder": all_ph, "complete": complete}


def _newest_nonempty(run_dir: Path, globs: List[str]) -> Optional[Path]:
    newest: Optional[Path] = None
    newest_m = -1.0
    for pat in globs:
        for p in run_dir.glob(pat):
            try:
                if p.is_file() and p.stat().st_size > 0:
                    m = p.stat().st_mtime
                    if m > newest_m:
                        newest_m, newest = m, p
            except OSError:
                continue
    return newest


def _orchestrator_verdict(run_dir: Path) -> Dict[str, object]:
    """The newest orchestrator/phase one_shot.json that carries a `verdict`."""
    best: Optional[Path] = None
    best_m = -1.0
    verdict = None
    for pat in _ORCH_REPORT_GLOBS:
        for p in run_dir.glob(pat):
            try:
                if not (p.is_file() and p.stat().st_size > 0):
                    continue
                d = json.loads(p.read_text(errors="replace"))
            except Exception:
                continue
            if isinstance(d, dict) and d.get("verdict"):
                m = p.stat().st_mtime
                if m > best_m:
                    best_m, best, verdict = m, p, d.get("verdict")
    return {"report": str(best) if best else None, "verdict": verdict}


def _norm_artifact_globs(req: List[str]) -> List[str]:
    """Turn 'gds,spef' or globs into concrete glob patterns. A bare token like
    'gds' becomes a recursive '**/*.gds'; a token already containing a glob
    metachar or a slash is used verbatim (recursive if it has no '/')."""
    out = []
    for tok in req:
        tok = tok.strip()
        if not tok:
            continue
        if any(c in tok for c in "*?[") or "/" in tok:
            out.append(tok)
        else:
            out.append(f"**/*.{tok.lstrip('.')}")
    return out


def _check_artifacts(run_dir: Path, req: List[str]) -> Dict[str, object]:
    """For each declared artifact type, find a non-empty match. Returns
    per-token findings + the list of missing/empty tokens."""
    findings: Dict[str, object] = {}
    missing: List[str] = []
    for tok, pat in zip(req, _norm_artifact_globs(req)):
        hit = None
        nbytes = 0
        for p in run_dir.glob(pat):
            try:
                if p.is_file() and p.stat().st_size > 0:
                    hit = p
                    nbytes = p.stat().st_size
                    break
            except OSError:
                continue
        ok = hit is not None
        findings[tok] = {"found": str(hit) if hit else None,
                         "bytes": nbytes, "ok": ok}
        if not ok:
            missing.append(tok)
    return {"findings": findings, "missing": missing,
            "any_present": any(v["ok"] for v in findings.values()) if findings else False}


# ---------------------------------------------------------------------------
# The classifier.
# ---------------------------------------------------------------------------
def check(run_dir: Path, *,
          result: Optional[Path] = None,
          require_artifacts: Optional[List[str]] = None,
          agent_output: Optional[Path] = None,
          claimed_verdict: Optional[str] = None,
          pid: Optional[int] = None) -> CompletenessReport:
    """Judge whether the run's declared deliverable is genuinely COMPLETE, and if
    not, WHY — see the module docstring for the taxonomy. Pure + deterministic."""
    run_dir = Path(run_dir)
    deliverable = Path(result) if result is not None else run_dir / "RESULT.md"
    req = list(require_artifacts or [])

    dl = _assess_deliverable(deliverable)
    fs = _newest_nonempty(run_dir, _FINAL_SUMMARY_GLOBS)
    orch = _orchestrator_verdict(run_dir)
    arts = _check_artifacts(run_dir, req)
    ao = None
    if agent_output is not None:
        ao = _assess_deliverable(Path(agent_output))
        # agent-output need only be NON-EMPTY (bytes>0, ≥1 content line);
        # it is not a full RESULT.md so it need not meet the byte floor.
        ao_ok = bool(ao["exists"] and ao["bytes"] > 0 and ao["content_lines"] >= 1)
    else:
        ao_ok = True
    live = _liveness(run_dir, pid)

    compute_done = bool(fs is not None or orch["verdict"] or arts["any_present"])

    evidence: Dict[str, object] = {
        "deliverable_exists": dl["exists"],
        "deliverable_bytes": dl["bytes"],
        "deliverable_content_lines": dl["content_lines"],
        "deliverable_all_placeholder": dl["all_placeholder"],
        "deliverable_complete": dl["complete"],
        "min_real_bytes": _MIN_REAL_BYTES,
        "min_content_lines": _MIN_CONTENT_LINES,
        "final_summary": str(fs) if fs else None,
        "orchestrator_report": orch["report"],
        "orchestrator_verdict": orch["verdict"],
        "required_artifacts": arts["findings"],
        "missing_artifacts": arts["missing"],
        "agent_output": (str(agent_output) if agent_output is not None else None),
        "agent_output_ok": ao_ok,
        "compute_done": compute_done,
        "liveness": live,
    }

    artifacts_ok = not arts["missing"]
    deliverable_complete = bool(dl["complete"] and artifacts_ok and ao_ok)

    # ── classify ────────────────────────────────────────────────────────────
    if deliverable_complete:
        state, verdict, reason = "COMPLETE", "PASS", (
            f"deliverable {deliverable.name} present ({dl['bytes']} B, "
            f"{dl['content_lines']} content lines)"
            + (f"; all {len(req)} declared artifact(s) present" if req else "")
            + (" ; agent-output present" if agent_output is not None else ""))
    elif live["live"]:
        who = (f"pid {live['pid']} alive" if live["pid_alive"]
               else f"live lock {live['lock']}")
        state, verdict, reason = "RUN_STILL_IN_PROGRESS", "IN_PROGRESS", (
            f"deliverable not complete yet, but a runner is LIVE ({who}) — the "
            f"agent has not reached its write step; not a failure (re-check "
            f"after the run exits)")
    elif not dl["complete"]:
        if dl["exists"]:
            why = ("all content lines are placeholders" if dl["all_placeholder"]
                   else f"only {dl['bytes']} B / {dl['content_lines']} content "
                        f"line(s) (< {_MIN_REAL_BYTES} B / {_MIN_CONTENT_LINES} "
                        f"lines)")
            state, verdict, reason = "DELIVERABLE_STUB", "FAIL", (
                f"{deliverable.name} EXISTS but is hollow: {why} — the write "
                f"step ran but produced no real content")
        elif compute_done:
            ev = []
            if fs:
                ev.append(f"final_summary={Path(fs).name}")
            if orch["verdict"]:
                ev.append(f"orchestrator verdict={orch['verdict']}")
            if arts["any_present"]:
                ev.append("declared artifact(s) present")
            state, verdict, reason = "COMPUTE_DONE_DELIVERABLE_MISSING", "FAIL", (
                f"the run's COMPUTE FINISHED ({', '.join(ev)}) but "
                f"{deliverable.name} is ABSENT — the launch-and-idle abandon "
                f"bug: the agent's turn ended before it wrote the deliverable. "
                f"THIS RUN IS A FAILED RUN (no synthesis output).")
        else:
            state, verdict, reason = "RUN_DIED_EARLY", "FAIL", (
                f"{deliverable.name} absent AND no final_summary, no "
                f"orchestrator verdict, no declared artifact — the run never "
                f"got far enough to produce anything (died early / never ran)")
    else:
        # RESULT itself is complete but a declared artifact / agent-output is
        # missing → the deliverable claims an output the run did not produce.
        gaps = []
        if arts["missing"]:
            gaps.append(f"artifact(s) {arts['missing']}")
        if not ao_ok:
            gaps.append("agent-output empty/missing")
        state, verdict, reason = "DECLARED_ARTIFACT_MISSING", "FAIL", (
            f"{deliverable.name} is complete but a declared deliverable is "
            f"missing/empty: {', '.join(gaps)}")

    rep = CompletenessReport(
        run_dir=str(run_dir), deliverable=str(deliverable),
        state=state, verdict=verdict, reason=reason, evidence=evidence,
        claimed_verdict=claimed_verdict)

    # blocking list + claimed-verdict consistency
    if verdict == "FAIL":
        rep.blocking.append(f"{state}: {reason}")
        if claimed_verdict and str(claimed_verdict).upper() == "PASS":
            rep.blocking.append(
                f"INCONSISTENCY: run CLAIMED verdict=PASS but produced no "
                f"complete deliverable ({state})")
        rep.highlight = _highlight(rep)
        rep.capture_candidate = _capture_candidate(rep)
    return rep


def _highlight(rep: CompletenessReport) -> str:
    bar = "!" * 72
    lines = [
        bar,
        f"!! EMPTY / MISSING / STUB DELIVERABLE — {rep.state}",
        f"!! run_dir     : {rep.run_dir}",
        f"!! deliverable : {rep.deliverable}",
        f"!! why         : {rep.reason}",
    ]
    ev = rep.evidence
    lines.append(
        f"!! evidence    : exists={ev['deliverable_exists']} "
        f"bytes={ev['deliverable_bytes']} lines={ev['deliverable_content_lines']} "
        f"compute_done={ev['compute_done']} "
        f"final_summary={'yes' if ev['final_summary'] else 'no'} "
        f"orch_verdict={ev['orchestrator_verdict']!r} "
        f"live={ev['liveness']['live']}")
    if ev["missing_artifacts"]:
        lines.append(f"!! missing artifacts: {ev['missing_artifacts']}")
    for b in rep.blocking:
        lines.append(f"!! {b}")
    lines.append("!! ACTION      : write the deliverable from the artifacts, "
                 "then re-run this gate — NO RESULT / empty output = the run "
                 "FAILED.")
    lines.append(bar)
    return "\n".join(lines)


def _capture_candidate(rep: CompletenessReport) -> dict:
    """A machine-readable enhancement-capture record (enhancement_emit.py
    schema, Bucket C) so an empty output is captured, never silent."""
    ev = rep.evidence
    return {
        "step": "orchestration.deliverable_finalize",
        "design": Path(rep.run_dir).name or rep.run_dir,
        "bucket": "C",
        "why_not_bucket_a": (
            "run_output_completeness_check.py IS the deterministic gate; the "
            "residual is the ORCHESTRATION discipline a program cannot enforce "
            "on the agent's turn lifecycle — an agent that detaches a long run "
            "and idles never gets re-invoked to write the deliverable."),
        "failure_mode": rep.state,
        "detected_by": "run_output_completeness_check.py",
        "title": f"{rep.state}: {Path(rep.deliverable).name} — {rep.reason[:120]}",
        "suggested_fix": (
            "Run the long tool through the BLOCKING _watchdog.run_supervised "
            "(returns only on exit/stall) so the agent's turn stays alive to "
            "completion; the agent's FINAL act before reporting done is to WRITE "
            "+ SELF-VERIFY the deliverable by running "
            "run_output_completeness_check on its own run_dir. No RESULT / empty "
            "output = the run FAILED."),
        "backlog_slug": f"empty-run-deliverable-{rep.state.lower()}",
        "backlog_type": "bug",
        "severity": "P1",
        "component": "orchestration/deliverable-completeness",
        "session_context": (
            f"run_dir={rep.run_dir}; deliverable={rep.deliverable}; "
            f"exists={ev['deliverable_exists']} bytes={ev['deliverable_bytes']} "
            f"content_lines={ev['deliverable_content_lines']} "
            f"compute_done={ev['compute_done']} "
            f"final_summary={ev['final_summary']} "
            f"orchestrator_verdict={ev['orchestrator_verdict']} "
            f"missing_artifacts={ev['missing_artifacts']} "
            f"live={ev['liveness']['live']}"),
    }


def report_to_dict(rep: CompletenessReport) -> dict:
    return {
        "run_dir": rep.run_dir,
        "deliverable": rep.deliverable,
        "state": rep.state,
        "verdict": rep.verdict,
        "reason": rep.reason,
        "evidence": rep.evidence,
        "blocking": rep.blocking,
        "highlight": rep.highlight,
        "capture_candidate": rep.capture_candidate,
        "claimed_verdict": rep.claimed_verdict,
        "rc": rep.rc,
    }


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Gate an EMPTY / MISSING / STUB run deliverable — highlight "
                    "it, diagnose WHY, and emit a capture candidate.")
    ap.add_argument("run_dir", help="the run directory to check")
    ap.add_argument("--result", default=None,
                    help="deliverable path (default <run_dir>/RESULT.md)")
    ap.add_argument("--require-artifacts", default=None,
                    help="comma-separated declared artifacts: extensions "
                         "(gds,spef,def) or globs")
    ap.add_argument("--agent-output", default=None,
                    help="a captured agent-return file to check is non-empty")
    ap.add_argument("--claimed-verdict", default=None,
                    help="what the run CLAIMED (PASS/FAIL) — flags a PASS claim "
                         "with no complete deliverable")
    ap.add_argument("--pid", type=int, default=None,
                    help="runner pid (else <run_dir>/run.pid or .runner.lock)")
    ap.add_argument("--json", default=None, help="write the verdict JSON here")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"ERROR: not a directory: {run_dir}")
        return 2
    req = ([t for t in args.require_artifacts.split(",") if t.strip()]
           if args.require_artifacts else None)

    rep = check(run_dir,
                result=Path(args.result) if args.result else None,
                require_artifacts=req,
                agent_output=Path(args.agent_output) if args.agent_output else None,
                claimed_verdict=args.claimed_verdict,
                pid=args.pid)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report_to_dict(rep), indent=2, ensure_ascii=False) + "\n")

    if rep.highlight:
        print(rep.highlight)
    tag = {"PASS": "PASS", "IN_PROGRESS": "IN-PROGRESS", "FAIL": "FAIL"}[rep.verdict]
    print(f"[{tag}] {rep.state} — {rep.reason}")
    if rep.capture_candidate:
        print("CAPTURE: emitted an enhancement-capture candidate "
              "(failure_mode=" + rep.state + ") — feed to enhancement_emit.py "
              "so this empty output is absorbed, not silent.")
    return rep.rc


if __name__ == "__main__":
    raise SystemExit(main())
