#!/usr/bin/env python3
"""vibe_ic_entry_guard.py — enforce single entry point for benchmark + IC runs.

Doctrine (owner directive 2026-06-28, BINDING):

    A benchmark / IC-design number is meaningful ONLY if it measures what the
    Vibe-IC deterministic runner chain can produce.  Therefore every run MUST
    enter through the Vibe-IC plugin's Phase-1 path; direct-agent authoring or
    patching followed by a host-scorer invocation measures "Opus + MCP-EDA",
    not Vibe-IC.

Canonical single entry point:

    python3 vibe_ic_one_shot_runner.py <project>

That orchestrator already integrates phase1_one_shot_runner.py (which in turn
invokes phase1_engine.cli), then phase2 / analog / phase3.

This guard accepts any of the following as evidence that the run went through
the Vibe-IC runner:

  - reports/orchestrator/vibe_ic_one_shot.json   (full orchestrator report)
  - reports/phase1_one_shot.json                 (phase1 standalone runner)
  - phase1/generated_docs/L1_DATASHEET.json      (phase1 engine output)
  - work/<design>/reports/orchestrator/vibe_ic_one_shot.json (Shape-B run)
  - work/<design>/phase1/generated_docs/L*.json  (Shape-B fact graph)

A run dir that lacks all of these is rejected unless the caller explicitly
passes --allow-direct-agent (which still emits a mandatory disclosure).

Usage:
    python3 vibe_ic_entry_guard.py <project|run_dir> [--strict]
    python3 vibe_ic_entry_guard.py <project|run_dir> --allow-direct-agent

Exit codes:
    0  entry-point evidence found (or --allow-direct-agent warn issued)
    1  no evidence (only under --strict; default is warn + rc=0 for back-compat)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple


# Ordered: strongest evidence first.  Any one of these is sufficient.
_EVIDENCE_FILES = [
    "reports/orchestrator/vibe_ic_one_shot.json",
    "reports/phase1_one_shot.json",
    "phase1/generated_docs/L1_DATASHEET.json",
]

# Shape-C per-problem evidence (open-benchmark-methodology § 7.5 rule 3).
#
# An atomic-micro-problem (Shape-C) run does NOT have a single run-root phase1
# tree: the harness drives `phase1_engine` ONCE PER PROBLEM, so the fact-graph
# lands under `<run>/work/<problem>/…/generated_docs/L*.json`.  § 7.5 rule 3 is
# explicit that this path still counts as Phase-1 entry ("the Phase-1
# fact-graph is still produced; the gate simply wraps the emit") — the run-root
# file list above simply had no branch for that layout, so a fully-compliant
# Shape-C run was rejected as if it were direct-agent authoring.
#
# Both layouts `gates_atomic.py` itself accepts are honoured (see its
# `out/generated_docs` / `phase1_proj/phase1/generated_docs` lookup).
#
# NO-LEAK (§ 4.05): this is a guard-RELAXING branch, so it is deliberately
# narrow — it requires an actual rendered phase1 LAYER DOC (`L<digits>_*.json`)
# inside a `generated_docs/` directory under a per-problem work dir.  A bare
# `work/` tree, an empty `generated_docs/`, or hand-dropped non-layer JSON does
# NOT satisfy it, so direct-agent authoring is still caught.
_EVIDENCE_GLOBS = [
    # Shape-B: one canonical project per benchmark design.
    "work/*/phase1/generated_docs/L*.json",
    # Shape-C: one atomic phase1 project per problem.
    "work/*/out/generated_docs/L*.json",
    "work/*/phase1_proj/phase1/generated_docs/L*.json",
]

# Shape-B's full orchestrator evidence is a fixed filename, not a layer doc.
# Keep it separate from the L-doc regex so an arbitrary JSON file at a similar
# depth cannot satisfy the guard.
_EVIDENCE_REPORT_GLOBS = [
    "work/*/reports/orchestrator/vibe_ic_one_shot.json",
]

# A layer doc is L<digits>_<NAME>.json — pinned so a stray `Lfoo.json` or a
# `L1_DATASHEET.json.bak` cannot stand in for real phase1 output.
_LAYER_DOC_RE = re.compile(r"^L\d+_[A-Za-z0-9_]+\.json$")


@dataclass
class EntryGuardFinding:
    rule: str
    path: str
    detail: str


def _is_orchestrator_report(path: Path) -> bool:
    """Require the minimal canonical one-shot report structure.

    The exact filename/depth prevents similar-path leakage; checking the report
    envelope prevents an empty file or hand-dropped ``{"verdict": "PASS"}``
    from standing in for evidence that the orchestrator actually ran.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return (isinstance(data, dict)
            and isinstance(data.get("project"), str) and bool(data["project"])
            and isinstance(data.get("verdict"), str) and bool(data["verdict"])
            and isinstance(data.get("phases"), (dict, list)))


def _has_evidence(project: Path) -> Tuple[bool, List[EntryGuardFinding]]:
    """Return (has_evidence, findings)."""
    findings: List[EntryGuardFinding] = []
    found = []
    for rel in _EVIDENCE_FILES:
        p = project / rel
        if p.is_file():
            found.append(str(p))
    if found:
        return True, findings
    for pattern in _EVIDENCE_REPORT_GLOBS:
        if any(p.is_file() and _is_orchestrator_report(p)
               for p in project.glob(pattern)):
            return True, findings
    # Per-design/per-problem phase1 evidence (§ 7.5 rule 3). Narrow by design:
    # the matched path must be a real rendered layer doc, not merely a file
    # sitting at the right depth.
    for pattern in _EVIDENCE_GLOBS:
        for p in project.glob(pattern):
            if p.is_file() and _LAYER_DOC_RE.match(p.name):
                return True, findings
    # None found — build a human finding.
    checked = ", ".join(
        _EVIDENCE_FILES + _EVIDENCE_REPORT_GLOBS + _EVIDENCE_GLOBS)
    findings.append(EntryGuardFinding(
        rule="MISSING_VIBE_IC_ENTRY_EVIDENCE",
        path=str(project),
        detail=(f"no Vibe-IC runner evidence found. Expected one of: {checked}. "
                "Run through `vibe_ic_one_shot_runner.py <project>` first.")))
    return False, findings


def audit(project: Path) -> Tuple[str, List[EntryGuardFinding]]:
    ok, findings = _has_evidence(project)
    return ("PASS", []) if ok else ("FAIL", findings)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=("Enforce that a benchmark/IC run started through the "
                     "Vibe-IC plugin (vibe_ic_one_shot_runner.py)."))
    ap.add_argument("project", help="project / run directory to audit")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when evidence is missing (default: warn only)")
    ap.add_argument("--allow-direct-agent", action="store_true",
                    help=("explicit opt-out for exploratory direct-agent runs; "
                          "emits a mandatory disclosure"))
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    project = Path(args.project)
    if not project.exists():
        print(f"error: project/run dir not found: {project}", file=sys.stderr)
        return 2

    verdict, findings = audit(project)

    report = {
        "gate": "vibe_ic_entry_guard",
        "verdict": verdict,
        "project": str(project.resolve()),
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings],
        "doctrine": ("every benchmark / IC run MUST enter through "
                     "vibe_ic_one_shot_runner.py (owner directive 2026-06-28)"),
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "PASS":
        print(f"PASS: Vibe-IC runner entry evidence found — {project}")
        return 0

    # FAIL branch
    detail = findings[0].detail if findings else "missing runner evidence"
    if args.allow_direct_agent:
        print(f"WARN(direct-agent): {detail}")
        return 0

    print(f"FAIL: {detail}", file=sys.stderr)
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
