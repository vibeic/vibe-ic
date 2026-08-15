#!/usr/bin/env python3
"""
agent_report_presence_check.py — verify the project ships a structured
top-level AGENT_REPORT.md summarising what the run delivered.

Real-world inspiration: phase2+3_v10619-vendor/AGENT_REPORT.md carried a
clear five-section breakdown (Verdict, Acceptance evidence, Waivers
list, Discoveries, Iteration log) that made the run independently
reviewable. phase2+3_v10619 (other agent) shipped no such file, so
verifying its end-state required reading raw logs across the project
tree. v1.6.24 promotes the AGENT_REPORT.md discipline from convention
to gate so every project has one auditable report card.

Required structure:
  Top-level `AGENT_REPORT.md` exists, non-empty, and contains a heading
  for each of the five mandatory sections (case-insensitive
  substring match, since markdown heading levels and exact wording
  vary across runs):
      - Verdict
      - Acceptance evidence  (also accepts: "Acceptance" / "Deliverables")
      - Waivers list         (also accepts: "Waivers" / "Deferred")
      - Discoveries          (also accepts: "Backlog" / "Findings")
      - Iteration log        (also accepts: "Iterations" / "Wave log")

Project-level acceptance: file exists + all 5 section synonyms hit.

This gate is universal — every project type benefits from a final
report. NO VACUOUS_PASS — there is no "this IC class doesn't need a
report" exception.

Usage:
    python3 agent_report_presence_check.py <project_dir> [--json <out>]

Exit codes:
    0  PASS
    1  AGENT_REPORT.md missing OR sections missing
    2  argument or I/O error

chip-AGNOSTIC. Section synonyms come from the v10619-vendor template
plus common alternates; no chip / project-name hardcoded.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


# Each tuple is (canonical_section_name, [synonym_substrings_lowercase]).
# A section is satisfied when ANY synonym appears as part of a markdown
# heading (`#`, `##`, `###`, ...). Synonyms are matched
# case-insensitively against the heading text only, so body text
# referring to "verdict" doesn't accidentally satisfy the section.
_REQUIRED_SECTIONS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Verdict",
     ("verdict",)),
    ("Acceptance evidence",
     ("acceptance evidence", "acceptance", "deliverables")),
    ("Waivers list",
     ("waivers list", "waivers", "deferred")),
    ("Discoveries",
     ("discoveries", "backlog", "findings")),
    ("Iteration log",
     ("iteration log", "iterations", "wave log", "iteration")),
)
_RE_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class SectionCheck:
    canonical_name: str
    matched_synonym: Optional[str] = None
    matched_heading: Optional[str] = None


def _extract_headings(text: str) -> List[str]:
    """Return all markdown heading texts (without the `#` prefix)."""
    return [m.group(2).strip().lower() for m in _RE_HEADING.finditer(text)]


def _check_sections(text: str) -> Tuple[List[SectionCheck], List[str]]:
    """For each required section, find a heading whose text contains
    one of the synonyms. Returns (per-section results, overall missing).
    """
    headings = _extract_headings(text)
    results: List[SectionCheck] = []
    missing: List[str] = []
    for canonical, synonyms in _REQUIRED_SECTIONS:
        sc = SectionCheck(canonical_name=canonical)
        for h in headings:
            for syn in synonyms:
                if syn in h:
                    sc.matched_synonym = syn
                    sc.matched_heading = h
                    break
            if sc.matched_synonym:
                break
        results.append(sc)
        if not sc.matched_synonym:
            missing.append(canonical)
    return results, missing


def audit(project: Path) -> Tuple[str, List[SectionCheck], List[str]]:
    report_path = project / "AGENT_REPORT.md"
    if not report_path.is_file():
        return "FAIL", [], ["AGENT_REPORT.md does not exist at project root"]
    text = report_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return "FAIL", [], ["AGENT_REPORT.md is empty"]
    sections, missing = _check_sections(text)
    if missing:
        diagnostics = [f"missing section: {s}" for s in missing]
        return "FAIL", sections, diagnostics
    return "PASS", sections, []


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify project ships a structured AGENT_REPORT.md.")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, sections, diagnostics = audit(project)
    report = {
        "gate": "agent_report_presence_check",
        "verdict": verdict,
        "project": str(project),
        "report_path": "AGENT_REPORT.md",
        "required_sections": [c for c, _ in _REQUIRED_SECTIONS],
        "section_results": [asdict(s) for s in sections],
        "diagnostics": diagnostics,
    }

    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, json.dumps(report, indent=2) + "\n")

    if verdict == "PASS":
        print(f"PASS: AGENT_REPORT.md present with all "
              f"{len(_REQUIRED_SECTIONS)} required sections")
        return 0
    print(f"FAIL: AGENT_REPORT.md problems:", file=sys.stderr)
    for d in diagnostics:
        print(f"  {d}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
