#!/usr/bin/env python3
"""extraction_credited_by_prose_only_check.py — how much of the Phase-1
coverage number is earned by a field that merely COPIED the input?

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This runs, prints, and cannot deny its step a PASS
tier; the reason is measured below and repeated at its flow clause.

WHAT THE COVERAGE NUMBER MEANS TODAY
====================================
`phase1/extraction_patterns.json` says so in its own header: "this file is the
coverage denominator". A literal is credited when its verbatim string appears
anywhere in the `generated_docs/L*.json` payload.

Several L fields carry the input PROSE, unchanged. `L2.frs_sections` holds
requirement sentences as written. `L8.auto_discovered_literals` holds every
literal the harvester saw, by construction. `extraction_evidence` quotes the
matched substring. A literal sitting in one of those has not been extracted into
anything — it has been copied — yet it satisfies the credit test.

MEASURED, on a 4-channel PWM controller written as a plain-English spec:

    denominator                                35
    reported coverage                          100.0%
    credited ONLY by a verbatim-prose field     8
    structured-only coverage                   27/35 = 77.1%

and the eight are worth reading:

    0xDEADBEEF  0xCAFEBABE  0xFEEDFACE  0xBAADF00D   invented trim constants,
                                                     structured nowhere
    25 MHz                                           the SYSTEM CLOCK
    98 kHz      760 Hz      3.3 V

`25 MHz` is the one that matters. The same run emitted `L8.clock_mhz = 10.0` —
the SPI clock, from the same sentence — so the coverage metric certified as
extracted the very number the extractor got wrong. A metric cannot be a check on
extraction while a verbatim copy of the input satisfies it.

WHY THIS REPORTS AND DOES NOT REFUSE
====================================
The honest structured-only figure is lower than the published one on every
project, by construction — so refusing on it would redden every tree at once
over debt this program did not create. What it CAN do is make the gap a number
somebody reads, which is the difference between a known cost and an invisible
one. Promote it to blocking when the published figure and this one agree.

Chip-AGNOSTIC: the predicate is a field-name classification and a substring
test. No protocol, chip class or layer vocabulary participates.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

#: Fields whose CONTENT is a copy of the input rather than a structured reading
#: of it. Named individually, never by a pattern: a field earns a place here by
#: being demonstrably a verbatim carrier, and the list is short enough to read.
PROSE_CARRIER_FIELDS = frozenset({
    "frs_sections",                          # requirement sentences, as written
    "auto_discovered_literals",              # every literal, by construction
    "extraction_evidence",                   # quotes the matched substring
    "electrical_specs_unextracted_mentions",  # says so in its own name
    "notes",
    "description",
    "extraction_strategy",
    "_generator",
    "_comment",
})


def _denominator(project: Path) -> List[str]:
    """The literals `extraction_patterns.json` declares as the denominator."""
    f = project / "phase1" / "extraction_patterns.json"
    if not f.is_file():
        return []
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: List[str] = []
    for key, rows in (doc or {}).items():
        if key.startswith("_") or not isinstance(rows, list):
            continue
        for row in rows:
            lit = row.get("literal") if isinstance(row, dict) else row
            if isinstance(lit, str) and lit.strip():
                out.append(lit)
    return out


def _haystacks(project: Path) -> Tuple[str, str]:
    """(structured, prose) — the L-doc payload split by field classification."""
    gd = project / "phase1" / "generated_docs"
    structured: List[str] = []
    prose: List[str] = []
    for f in sorted(gd.glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        for key, value in doc.items():
            blob = json.dumps(value).lower()
            (prose if key in PROSE_CARRIER_FIELDS else structured).append(blob)
    return "\n".join(structured), "\n".join(prose)


def audit(project: Path) -> Dict:
    lits = _denominator(project)
    structured, prose = _haystacks(project)
    prose_only, uncredited, structured_ok = [], [], []
    for lit in lits:
        low = lit.lower()
        in_s, in_p = low in structured, low in prose
        if in_s:
            structured_ok.append(lit)
        elif in_p:
            prose_only.append(lit)
        else:
            uncredited.append(lit)
    total = len(lits)
    return {
        "denominator": total,
        "structured": len(structured_ok),
        "prose_only": prose_only,
        "uncredited": uncredited,
        "structured_pct": (round(100.0 * len(structured_ok) / total, 1)
                           if total else None),
        "prose_carrier_fields": sorted(PROSE_CARRIER_FIELDS),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=("how much of the Phase-1 coverage number is earned by a "
                     "field that copied the input rather than read it"))
    ap.add_argument("project", nargs="?", default=".")
    ap.add_argument("--json", default=None, help="write the audit as JSON")
    args = ap.parse_args(argv)

    project = Path(args.project)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    rep = audit(project)
    n = rep["denominator"]
    if not n:
        # A zero denominator REFUSES rather than passing: "nothing to examine"
        # and "everything examined and clean" are different facts (the house
        # rule `gate_zero_denominator_refuses_check` enforces).
        print("[CANNOT CHECK] extraction_credited_by_prose_only_check: "
              "phase1/extraction_patterns.json declares no denominator, so "
              "there is no coverage claim to audit. This is the ABSENCE of a "
              "question, not a pass.")
        return 2

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")

    for lit in rep["prose_only"]:
        print(f"  [PROSE-ONLY] {lit!r} appears only in a field that carries the "
              f"input verbatim; it was copied, not extracted")
    for lit in rep["uncredited"]:
        print(f"  [UNCREDITED] {lit!r} is in the denominator and in no L doc "
              f"at all")
    print(f"extraction_credited_by_prose_only_check: {rep['structured']}/"
          f"{n} = {rep['structured_pct']}% of the coverage denominator is "
          f"credited by a STRUCTURED field; {len(rep['prose_only'])} literal(s) "
          f"are credited only by a verbatim-prose carrier "
          f"({', '.join(sorted(PROSE_CARRIER_FIELDS))}). "
          f"ADVISORY — reported, never blocking.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
