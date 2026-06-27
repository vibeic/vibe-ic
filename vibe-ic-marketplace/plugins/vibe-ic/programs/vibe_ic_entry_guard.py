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


@dataclass
class EntryGuardFinding:
    rule: str
    path: str
    detail: str


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
    # None found — build a human finding.
    checked = ", ".join(_EVIDENCE_FILES)
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
