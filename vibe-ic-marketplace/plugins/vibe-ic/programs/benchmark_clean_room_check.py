#!/usr/bin/env python3
"""benchmark_clean_room_check.py — clean-room run-dir guard (ORGANIC-20260604).

Doctrine (user directive 2026-06-04, BINDING, supersedes the 2026-05-29
"re-attempt the FAILing set by default" policy):

    "Run vibe-ic Benchmark 一定是重跑，一定重跑。不要拿舊的資料，也不要用
     memory，也不要用原來 storage 裡面的東西，一定是重跑。"

    Every "run <benchmark>" is a CLEAN-ROOM FULL re-run: a fresh agent
    authors EVERY problem from the spec alone, blind to any prior run. The
    only honest pass@1 is one whose authoring context started EMPTY.

A run is contaminated (NOT clean-room) when its samples were inherited from a
prior run, when its config records a seed/inherited run, or when the harness
read a prior score before authoring. This program is the deterministic gate
that FAILs such a run so it cannot be scored as canonical.

Checks (chip-AGNOSTIC; no benchmark/IC name hardcoded):

  1. EXTERNAL SYMLINK — any path under <run>/samples/ (or <run>/work/) that is
     a symlink resolving OUTSIDE the run dir → inherited authoring. FAIL.
  2. PRE-DATED SAMPLE — any authored sample whose mtime PREDATES the run dir's
     creation marker (.bench_config.json mtime, else the run dir mtime) by more
     than a small clock-skew tolerance → copied in from an earlier run. FAIL.
  3. SEED CONFIG — <run>/.bench_config.json declares a non-null `inherited_from`
     / `seed_run` / `reused_samples_from` field → explicitly inherited. FAIL.
  4. PRIOR-SCORE READ — a harness/run log under <run> shows a read of a prior
     `pass_at_1.json` / `cocotb_score.json` BEFORE authoring (a contaminating
     "what failed last time" lookup) → FAIL.

A run dir whose `.bench_config.json` sets `floor_only: true` is an EXPLICIT,
user-requested opt-in (the `--floor-only` option). It still must re-author its
selected problems blind, so checks 1/2/4 still apply; only check 3's
`inherited_from` is permitted to name the prior run it took the FAIL list from
(the SAMPLES must still be freshly authored, never copied).

Usage:
    python3 benchmark_clean_room_check.py <run_dir> [--json <out>]
                                          [--allow-floor-only]

Exit codes:
    0  clean-room OK (or a sanctioned floor-only run with fresh samples)
    1  contaminated — at least one violation
    2  argument / I/O error (e.g. run dir missing)

This is the front-door guard wired into benchmark_dispatch.py so a
contaminated run cannot be scored as canonical.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

# Authored-sample suffixes we care about (the agent's per-problem output).
_SAMPLE_GLOBS = ("*.v", "*.sv", "*.vh", "*.svh", "spec.yaml", "sample.sv",
                 "sample*.sv", "sample*.v")
# A read of one of these in a run log BEFORE authoring is a contaminating
# "what failed last time" lookup.
_PRIOR_SCORE_RE = re.compile(r"(pass_at_1\.json|cocotb_score\.json)")
# Small tolerance (seconds) for filesystem clock skew when comparing mtimes.
_MTIME_SKEW_TOLERANCE = 5.0


@dataclass
class CleanRoomFinding:
    rule: str
    path: str
    detail: str


def _run_creation_marker(run: Path) -> float:
    """Reference 'run started' timestamp: the .bench_config.json mtime if
    present (written at --setup), else the run dir's own mtime."""
    cfg = run / ".bench_config.json"
    if cfg.is_file():
        return cfg.stat().st_mtime
    return run.stat().st_mtime


def _iter_sample_files(run: Path):
    seen = set()
    for sub in ("samples", "work"):
        d = run / sub
        if not d.is_dir():
            continue
        for pat in _SAMPLE_GLOBS:
            for p in d.rglob(pat):
                if (p.is_symlink() or p.is_file()) and p not in seen:
                    seen.add(p)
                    yield p


def _external_symlink(p: Path, run_resolved: Path) -> bool:
    """True if p is a symlink whose target resolves outside run_resolved."""
    if not p.is_symlink():
        return False
    try:
        target = p.resolve()
    except OSError:
        return True  # broken symlink — treat as suspicious
    try:
        target.relative_to(run_resolved)
        return False
    except ValueError:
        return True


def audit(run: Path, allow_floor_only: bool = True
          ) -> Tuple[str, List[CleanRoomFinding]]:
    findings: List[CleanRoomFinding] = []
    run_resolved = run.resolve()

    cfg_path = run / ".bench_config.json"
    cfg = {}
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text())
        except (OSError, ValueError):
            cfg = {}
    floor_only = bool(cfg.get("floor_only"))

    # ── Check 3: seed/inherited config field ──────────────────────────
    for key in ("inherited_from", "seed_run", "reused_samples_from"):
        val = cfg.get(key)
        if val:
            # floor_only runs may NAME the prior run they took the FAIL list
            # from via inherited_from, but reused_samples_from is never ok.
            sanctioned = (allow_floor_only and floor_only
                          and key == "inherited_from")
            if not sanctioned:
                findings.append(CleanRoomFinding(
                    rule="SEED_CONFIG",
                    path=str(cfg_path),
                    detail=(f".bench_config.json sets {key}={val!r} — the run "
                            "inherited authoring state from a prior run. A "
                            "clean-room run starts EMPTY.")))

    t0 = _run_creation_marker(run)

    # ── Checks 1 + 2: external symlink / pre-dated sample ─────────────
    for p in _iter_sample_files(run):
        if _external_symlink(p, run_resolved):
            findings.append(CleanRoomFinding(
                rule="EXTERNAL_SYMLINK",
                path=str(p),
                detail=("authored sample is a symlink resolving OUTSIDE the "
                        "run dir — inherited from another run, not authored "
                        "fresh.")))
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if mtime < t0 - _MTIME_SKEW_TOLERANCE:
            findings.append(CleanRoomFinding(
                rule="PREDATED_SAMPLE",
                path=str(p),
                detail=(f"sample mtime {mtime:.0f} predates run-dir creation "
                        f"{t0:.0f} — copied in from an earlier run rather than "
                        "authored after --setup.")))

    # ── Check 4: prior-score read in a run/harness log ────────────────
    for log in list(run.rglob("*.log")) + list(run.rglob("harness*.txt")):
        try:
            txt = log.read_text(errors="ignore")
        except OSError:
            continue
        m = _PRIOR_SCORE_RE.search(txt)
        if m:
            findings.append(CleanRoomFinding(
                rule="PRIOR_SCORE_READ",
                path=str(log),
                detail=(f"run log reads a prior '{m.group(1)}' — a "
                        "'what-failed-last-time' lookup contaminates blind "
                        "authoring. Clean-room authoring context starts empty.")))

    return ("FAIL" if findings else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Clean-room run-dir guard: FAIL a benchmark run that "
                    "inherited prior samples / scores / memory (ORGANIC-20260604).")
    ap.add_argument("run_dir", help="benchmark run directory to audit")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--allow-floor-only", action="store_true", default=True,
                    help="permit a floor_only run to NAME its seed run via "
                         "inherited_from (samples must still be fresh). Default on.")
    ap.add_argument("--no-floor-only", dest="allow_floor_only",
                    action="store_false",
                    help="strict: even floor_only inherited_from is a violation.")
    args = ap.parse_args(argv)

    run = Path(args.run_dir)
    if not run.is_dir():
        print(f"error: run dir not found: {run}", file=sys.stderr)
        return 2

    verdict, findings = audit(run, allow_floor_only=args.allow_floor_only)
    report = {
        "gate": "benchmark_clean_room_check",
        "verdict": verdict,
        "run_dir": str(run.resolve()),
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings],
        "doctrine": ("clean-room full re-run is the default; no inherited "
                     "samples / memory / prior storage (user directive "
                     "2026-06-04, supersedes 2026-05-29 re-attempt default)"),
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(report, indent=2) + "\n")

    if verdict == "PASS":
        print(f"PASS: clean-room run dir (no inherited samples / scores) — {run}")
        return 0
    print(f"FAIL: {len(findings)} clean-room violation(s) in {run}:",
          file=sys.stderr)
    for f in findings[:20]:
        print(f"  [{f.rule}] {f.path} — {f.detail}", file=sys.stderr)
    if len(findings) > 20:
        print(f"  … and {len(findings) - 20} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
