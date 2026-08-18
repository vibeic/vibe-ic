#!/usr/bin/env python3
"""convergence_doctrine_present_check.py — ORGANIC #716

Deterministic guard that the **program-first + AI-backup DUAL-TRACK CONVERGENCE**
doctrine is documented in `skills/benchmark-enhancement-capture/SKILL.md`.

"AI-backup" is binding-defined as a dual-track convergence (program verdict +
independent AI solve + compare + converge), NOT an "AI only when the program
fails" fallback. This guard pins that the doctrine is not silently dropped by a
future skill edit — and, fittingly, it itself follows the doctrine: it emits the
RAW EVIDENCE it judged on (which markers were found / missing) so an independent
track can re-judge, rather than only a bare verdict.

Exit codes:
    0  doctrine present (all required markers found)
    1  doctrine missing / incomplete (missing markers listed)
    2  skill file not found / unreadable

chip-AGNOSTIC: pure marker presence over the skill markdown; no chip / vendor /
SKU literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SKILL = (_PLUGIN_ROOT / "skills" / "benchmark-enhancement-capture"
                  / "SKILL.md")

# The doctrine's load-bearing markers (newline- AND blockquote-insensitive
# substring match against a flattened lower view of the skill markdown).
_REQUIRED_MARKERS = (
    "dual-track convergence",
    "ai-backup",
    "cross-check",
    "converge",
    "raw evidence",
    "comparator",
    "lone-track",
    # explicitly rejects the on-failure-only misreading
    "only when the program fails",
    # the Benchmark Agent's #1 MANDATE — converge → capture → distill-to-program
    # (owner directive 2026-06-22). PROGRAM-FIRST lesson: prose alone regresses,
    # so the load-bearing doctrine MUST be pinned or a future skill edit can
    # silently drop it with no test going red (Step-2.7 #51).
    "#1 mandate",
    "capture every fail",
    "distill-to-program",
)


def _flat(text: str) -> str:
    """Whitespace + blockquote-marker normalised lower view (a phrase wrapped
    inside a markdown blockquote otherwise reads as 'program > fails')."""
    return re.sub(r"\s+", " ", text.lower().replace(">", " "))


def check(skill_path: Path) -> dict:
    """Return an evidence dict: {present, found[], missing[], skill}. `present`
    is True iff every required marker is in the flattened skill text."""
    text = skill_path.read_text(errors="replace")
    flat = _flat(text)
    found, missing = [], []
    for mk in _REQUIRED_MARKERS:
        (found if mk in flat else missing).append(mk)
    return {
        "skill": str(skill_path),
        "present": not missing,
        "found": found,
        "missing": missing,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Guard the #716 program-first + AI-backup convergence "
                    "doctrine in benchmark-enhancement-capture.")
    ap.add_argument("--skill", default=str(_DEFAULT_SKILL),
                    help="path to the benchmark-enhancement-capture SKILL.md")
    ap.add_argument("--json", default=None, help="write the evidence JSON here")
    args = ap.parse_args(argv)

    skill_path = Path(args.skill)
    if not skill_path.is_file():
        print(f"ERROR: skill file not found: {skill_path}", file=sys.stderr)
        return 2
    evidence = check(skill_path)
    text = json.dumps(evidence, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n")
    print(text)
    if not evidence["present"]:
        print("FAIL: convergence doctrine markers MISSING: "
              f"{evidence['missing']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
