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

ORGANIC #696 — the open-source ERC screen (OpenROAD report_floating_nets)
ALSO reports three structurally-benign BARE-NET classes that are not a
functional connectivity defect on any open-PDK digital P&R:
  * power / ground rails (the design's SPECIALNETS — e.g. VPWR/VGND,
    vdd/vss, vcc/gnd, vccd/vssd) — these are power-delivery nets, not
    signal connectivity, and OpenROAD reports them as "floating" only
    because they are tied via the PDN, not via a routed signal segment;
  * the constant-tie net synthesized by yosys `hilomap` (the `zero_` /
    `one_` / tie-lo / tie-hi net — CLAUDE.md rule #4), a literal-0/1 source
    that has no driver/load in the routed-signal sense.
These are benign by construction and are excluded from the FUNCTIONAL set
the same way spare-cell I/O is — STRUCTURALLY (by net-class shape), never
by a chip/SKU literal. §4.05 no-leak: a genuine floating SIGNAL net (a
real functional name that is neither a power/ground rail nor a tie net nor
spare-owned) is STILL functional → ERC FAIL.

Validated on real spm/subservient (Step-31 ERC): floats are 100%
spare_*/<pin> + i_gpio[0] optional-unused → functional == 0.

chip/PDK-AGNOSTIC: the only conventions are the generic 'spare' instance
name and the structural power/ground + constant-tie net-class shapes;
optional-unused ports are passed in, never hardcoded.

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

# ORGANIC #696 — structurally-benign BARE-NET classes (no /pin owner).
# Power / ground rails: the exact canonical rail spellings used across open
# PDKs (sky130 VPWR/VGND/VPB/VNB + the core/io domain VCCD/VSSD/VCCD1/VSSD1
# /VDDA/VSSA/VDDIO/VSSIO families, gf180 VDD/VSS, and the generic
# vdd/vss/vcc/gnd/vddio/vssio). Anchored to a WHOLE-NAME match (optionally
# with a trailing digit, e.g. VCCD1 / VDD2) so a real signal that merely
# CONTAINS 'vdd' (e.g. 'vdd_ok', 'pll_vdd_sel', 'data_vss_n') is NOT
# swallowed. Constant-tie net from yosys hilomap: zero_/one_/tie-lo/tie-hi
# — the literal-0/1 source (CLAUDE.md rule #4).
_POWER_GROUND_RE = re.compile(
    r'^(?:v(?:pwr|gnd|pb|nb|ccd|ssd|dda|ssa|ddio|ssio|dd|ss|cc|ee)|gnd|gnda'
    r'|vbgr)\d*$',
    re.I,
)
_TIE_NET_RE = re.compile(
    r'^(?:zero_+\d*|one_+\d*|tie_?(?:lo|hi|0|1|low|high)\w*'
    r'|tielo|tiehi|logic[01]|net_?(?:vdd|vss))$',
    re.I,
)


def _is_benign_net_class(name: str) -> bool:
    """True for a structurally-benign BARE net (power/ground rail or the
    hilomap constant-tie net). §4.05: only WHOLE-NAME canonical rail/tie
    spellings match — a real signal net that merely contains 'vdd'/'zero'
    as a substring (e.g. 'vdd_ok', 'data_zero_flag') is NOT benign."""
    # a pin float (inst/pin) is owned by an instance, handled by the spare
    # path — the bare-net classes never carry a '/'.
    if "/" in name:
        return False
    return bool(_POWER_GROUND_RE.match(name) or _TIE_NET_RE.match(name))


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
        elif _is_benign_net_class(f):
            # ORGANIC #696 — power/ground rail or hilomap constant-tie net.
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
