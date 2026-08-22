#!/usr/bin/env python3
"""benchmark_result_md_lint.py — presence-check linter for the
mandatory § 6 RESULT.md section checklist.

Extracted from open-benchmark-methodology § 6 ("The benchmark
RESULT.md must include"). Every benchmark RESULT.md MUST carry seven
sections; an agent that omits one (most commonly the residual-triage
or tool-substitution block) produces an un-auditable result. This
linter fails the run if any mandatory section is missing.

Mandatory sections (§ 6):
  1. Headline          — score / denominator / what was measured
  2. Shape             — A/B/C/D/E + the entry point
  3. Score trajectory  — single-shot, close-loop stages
  4. Residual triage   — every fail mapped to category A-H with evidence
  5. Tool substitution — every substitution per § 3
  6. Reproduce         — exact scorer command line + dataset path
  7. Sequence/plan status — which roadmap items were intentionally skipped

Detection is keyword/synonym based (headings or inline tokens), so a
RESULT.md that uses reasonable phrasing passes, while one missing a
whole concept fails.

Usage
=====
  python3 benchmark_result_md_lint.py <RESULT.md> [--json out.json]

Honest failure
==============
  * Missing / empty / unreadable RESULT.md → FAIL (rc 1). A linter
    cannot vacuously PASS a file with no content.
  * Any of the seven mandatory sections absent → FAIL (rc 1) with the
    missing section names listed.

Exit codes
==========
  0 — PASS (all 7 sections present)
  1 — FAIL (missing file / missing section)
  2 — usage error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Each section: (canonical name, list of synonym tokens — any match counts).
# Tokens are matched case-insensitively as substrings of the document text.
SECTIONS = [
    ("headline", ["headline", "pass@1", "score:", "denominator", "what was measured"]),
    ("shape", ["shape a", "shape b", "shape c", "shape d", "shape e",
               "run-shape", "run shape", "entry point"]),
    ("score_trajectory", ["trajectory", "single-shot", "single shot",
                          "close-loop stage", "close loop stage", "iteration 1"]),
    ("residual_triage", ["residual triage", "residual-triage", "triage",
                         "category a", "category b", "category h",
                         "floor", "agent-fixable", "agent fixable"]),
    ("tool_substitution", ["tool substitution", "tool-substitution",
                          "we substitute", "iverilog", "substitut"]),
    ("reproduce", ["reproduce", "reproduction", "command line", "dataset path",
                   "to rerun", "to re-run"]),
    ("sequence_plan_status", ["sequence", "plan status", "roadmap",
                             "intentionally skipped", "out-of-scope", "out of scope",
                             "open-benchmark.md"]),
]


def lint_text(text: str) -> list[str]:
    """Return the list of missing canonical section names."""
    low = text.lower()
    missing: list[str] = []
    for name, tokens in SECTIONS:
        if not any(tok in low for tok in tokens):
            missing.append(name)
    return missing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("result_md", help="path to the RESULT.md to lint")
    ap.add_argument("--json", help="write JSON report to this path")
    a = ap.parse_args(argv)

    report: dict = {"program": "benchmark_result_md_lint",
                    "path": a.result_md,
                    "required_sections": [s[0] for s in SECTIONS]}
    p = Path(a.result_md)
    if not p.exists():
        report.update(verdict="FAIL", reason="result_md_missing")
        _emit(a, report)
        print(f"FAIL: RESULT.md not found: {p}", file=sys.stderr)
        return 1
    text = p.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        report.update(verdict="FAIL", reason="result_md_empty")
        _emit(a, report)
        print(f"FAIL: RESULT.md is empty: {p}", file=sys.stderr)
        return 1

    missing = lint_text(text)
    report["missing_sections"] = missing
    report["present_sections"] = [s[0] for s in SECTIONS if s[0] not in missing]
    if missing:
        report.update(verdict="FAIL", reason="missing_mandatory_sections")
        _emit(a, report)
        print("FAIL: RESULT.md missing mandatory § 6 section(s): "
              + ", ".join(missing), file=sys.stderr)
        return 1
    report["verdict"] = "PASS"
    _emit(a, report)
    print(f"PASS: all {len(SECTIONS)} mandatory § 6 sections present in {p.name}")
    return 0


def _emit(a, report: dict) -> None:
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
