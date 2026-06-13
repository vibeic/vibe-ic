#!/usr/bin/env python3
"""v0.3.16 — ORGANIC #514. Classify ERC floating nets/pins BY OWNER into
benign-by-construction vs functional.

The open-source ERC sub-gate FAILs on a raw floating net/pin COUNT. But
on a real routed design those floats can be 100% design-for-ECO
spare-cell I/O — the inputs/outputs of spare inverter/nand/mux/dff cells
that are DELIBERATELY left unconnected, pre-placed for a late metal ECO
(a spare cell is SUPPOSED to float until ECO wires it) — plus
optional-unused top input ports. These are benign by construction, not a
functional connectivity defect; only a float owned by a FUNCTIONAL
instance is a real ERC defect.

Each float name from OpenROAD `report_floating_nets -verbose` is
`<instance>/<pin>` (or a bare net). The owner is the instance prefix; a
float is benign when its owner is a spare cell (instance name contains
'spare') or the float is a caller-declared optional-unused top port. When
the FUNCTIONAL count is 0, mark 'benign-ERC' (waiver-eligible) instead of
a raw float FAIL.

Validated on real spm/subservient (Step-31 ERC): floats are 100%
spare_*/<pin> + i_gpio[0] optional-unused → functional == 0.

chip/PDK-AGNOSTIC: the only convention is the generic 'spare' instance
name; optional-unused ports are passed in, never hardcoded.

Exit 0 = clean OR benign-ERC (functional == 0). Exit 1 = functional
floats present. Exit 2 = bad input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import List, Set, Tuple

_SPARE_RE = re.compile(r'spare', re.I)
# a verbose floating line: leading whitespace then "<inst>/<pin>" or a net.
_FLOAT_LINE_RE = re.compile(r'^\s+([A-Za-z0-9_\\\[\]/.$:]+)\s*$')


def parse_floats(report_text: str) -> List[str]:
    """Extract floating net/pin names from an OpenROAD
    `report_floating_nets -verbose` transcript. Returns the bare names
    (e.g. 'spare_aoi_0/A1')."""
    out: List[str] = []
    capture = False
    for line in report_text.splitlines():
        if re.search(r'floating (pin|net)', line, re.I):
            capture = True
            continue
        if capture:
            m = _FLOAT_LINE_RE.match(line)
            if m and "/" in m.group(1) or (m and "." not in m.group(1)
                                           and m.group(1) not in ("", )):
                # accept inst/pin OR a bare net token; stop on a non-name line
                out.append(m.group(1))
            elif not m:
                capture = False
    # de-dup preserve order
    seen: Set[str] = set()
    uniq: List[str] = []
    for n in out:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def classify(floats: List[str],
             optional_ports: Set[str] | None = None) -> dict:
    """Classify floats by owner. benign = spare-cell I/O (owner contains
    'spare') OR an optional-unused top port; functional = everything else."""
    optional_ports = optional_ports or set()
    benign: List[str] = []
    functional: List[str] = []
    by_owner: Counter = Counter()
    for f in floats:
        owner = f.split("/", 1)[0]
        by_owner[owner] += 1
        if _SPARE_RE.search(owner):
            benign.append(f)
        elif f in optional_ports or owner in optional_ports:
            benign.append(f)
        else:
            functional.append(f)
    total = len(floats)
    if total == 0:
        classification = "clean"
    elif not functional:
        classification = "benign-ERC"
    else:
        classification = "has-functional-floats"
    return {
        "total_floats": total,
        "benign_count": len(benign),
        "functional_count": len(functional),
        "functional_floats": functional[:50],
        "by_owner": dict(by_owner.most_common()),
        "classification": classification,
        "waiver_eligible": classification in ("clean", "benign-ERC"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Classify ERC floats by owner")
    ap.add_argument("report", help="OpenROAD report_floating_nets -verbose "
                                   "transcript (e.g. reports/phase3/erc.rpt)")
    ap.add_argument("--optional-port", action="append", default=[],
                    help="an optional-unused top port name (repeatable)")
    ap.add_argument("--json", default=None, help="write JSON summary here")
    args = ap.parse_args(argv)
    p = Path(args.report)
    if not p.is_file():
        print(f"ERROR: report not found: {p}", file=sys.stderr)
        return 2
    floats = parse_floats(p.read_text(errors="replace"))
    summary = classify(floats, set(args.optional_port))
    out = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out + "\n")
    print(out)
    return 0 if summary["waiver_eligible"] else 1


if __name__ == "__main__":
    sys.exit(main())
