#!/usr/bin/env python3
"""skill_doc_section_present_check.py — ORGANIC #724 / #725

A generic, program-first guard that a durably-captured doctrine SECTION is
present in a skill / agent markdown file — so a future edit cannot silently
drop a captured lesson. A prose lesson a fresh editor forgets must become a
CI-checkable invariant (the #517 program-first-upgrade pattern).

Given a markdown file and a set of required MARKER substrings (case-insensitive,
whitespace- and markdown-blockquote-insensitive), exit 0 iff every marker is
present, 1 if any is missing. Emits the raw evidence (found / missing) so an
independent track can re-judge (the #716 dual-track convergence shape).

Exit codes:
    0  all markers present
    1  one or more markers missing
    2  file not found / no markers given

chip-AGNOSTIC: pure marker-presence over markdown; no chip / vendor / SKU literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _flat(text: str) -> str:
    """Whitespace + markdown-blockquote (`>`) normalised lower view (a phrase
    line-wrapped inside a blockquote otherwise reads as 'a > b')."""
    return re.sub(r"\s+", " ", text.lower().replace(">", " "))


def check(doc: Path, markers) -> dict:
    """Evidence: {present, found[], missing[], doc}."""
    flat = _flat(doc.read_text(errors="replace"))
    found, missing = [], []
    for mk in markers:
        (found if _flat(mk) in flat else missing).append(mk)
    return {"doc": str(doc), "present": not missing,
            "found": found, "missing": missing}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Guard a durably-captured doctrine section is present in a "
                    "skill/agent markdown (#724/#725).")
    ap.add_argument("--doc", required=True, help="markdown file to check")
    ap.add_argument("--marker", action="append", default=[],
                    help="a required substring (repeatable); ALL must be present")
    ap.add_argument("--json", default=None, help="write evidence JSON here")
    args = ap.parse_args(argv)

    doc = Path(args.doc)
    if not doc.is_file():
        print(f"ERROR: doc not found: {doc}", file=sys.stderr)
        return 2
    if not args.marker:
        print("ERROR: at least one --marker is required", file=sys.stderr)
        return 2
    ev = check(doc, args.marker)
    text = json.dumps(ev, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n")
    print(text)
    if not ev["present"]:
        print(f"FAIL: missing doctrine marker(s): {ev['missing']}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
