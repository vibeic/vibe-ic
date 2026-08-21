#!/usr/bin/env python3
"""offgrid_drc_classify_check.py — ORGANIC #594.

The first design to reach GDS in a campaign failed signoff DRC with the
count DOMINATED by OFFGRID-vertex rules: on the motivating IC, 61,324
total violations with m1_OFFGRID=29,670 + ct_OFFGRID=6,204 ≈ 74% of the
user-class violations, while real spacing rules (m1.2=11,470) were a
distant second. An OFFGRID vertex (PDK rule "x.1b") is a polygon vertex
that does not land on the manufacturing grid (sky130 = 5 nm). That is a
FLOW defect — the routing/streamout produced off-grid geometry — NOT
design content. Counting it together with real spacing/width DRC hides
the flow regression inside a huge "design DRC" number.

This gate reads a KLayout sign-off DRC XML report, splits the violations
into the OFFGRID class vs everything else, and FAILs with a distinct
``FLOW_OFFGRID`` finding when any OFFGRID-class violation is present — so
a grid regression can never be miscounted as design DRC, and the real
spacing/width count is reported separately.

Exit: 0 = no OFFGRID-class violations, 1 = FLOW_OFFGRID present,
2 = input error. Chip-AGNOSTIC: KLayout XML schema + the universal
``OFFGRID`` rule-name token only (sky130A / gf180mcuD / sg13g2 share it).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Tuple

# An OFFGRID-class rule is identified by the universal `OFFGRID` token in
# its category NAME (m1_OFFGRID / ct_OFFGRID / via_OFFGRID …) or by the
# canonical "x.1b" / "off-grid vertex" phrasing in its description. Real
# spacing/width rules (m1.2, li.1, x.2, …) never carry it.
_OFFGRID_NAME_RE = re.compile(r"off[\s_-]?grid", re.IGNORECASE)
_OFFGRID_DESC_RE = re.compile(r"off[\s_-]?grid\s+vertex|\bx\.1b\b", re.IGNORECASE)


def _category_descriptions(root: ET.Element) -> Dict[str, str]:
    """Map category name → description text (for the desc-based match)."""
    out: Dict[str, str] = {}
    for cat in root.iter("category"):
        nm = cat.findtext("name")
        if nm:
            out[nm.strip().strip("'\"")] = (cat.findtext("description") or "")
    return out


def _is_offgrid(rule: str, desc: str) -> bool:
    return bool(_OFFGRID_NAME_RE.search(rule)
                or (desc and _OFFGRID_DESC_RE.search(desc)))


def classify(rpt_path: Path) -> Dict:
    """Parse a KLayout DRC XML report → classification dict.

    Returns {total, offgrid_total, offgrid_fraction, offgrid_per_rule,
    other_per_rule, verdict}. verdict is FLOW_OFFGRID when any OFFGRID
    violation exists, else PASS. On parse error returns verdict ERROR."""
    if not rpt_path or not rpt_path.is_file():
        return {"verdict": "ERROR", "reason": f"report not found: {rpt_path}",
                "total": 0, "offgrid_total": 0}
    try:
        tree = ET.parse(str(rpt_path))
    except Exception as exc:
        return {"verdict": "ERROR", "reason": f"XML parse failed: {exc}",
                "total": 0, "offgrid_total": 0}
    root = tree.getroot()
    descs = _category_descriptions(root)

    offgrid_per_rule: Dict[str, int] = {}
    other_per_rule: Dict[str, int] = {}
    total = 0
    for item in root.iter("item"):
        # one <item> = one violation; <multiplicity> may aggregate.
        rule = (item.findtext("category") or "").strip().strip("'\"")
        if not rule:
            continue
        try:
            mult = int((item.findtext("multiplicity") or "1").strip())
        except ValueError:
            mult = 1
        mult = max(1, mult)
        total += mult
        if _is_offgrid(rule, descs.get(rule, "")):
            offgrid_per_rule[rule] = offgrid_per_rule.get(rule, 0) + mult
        else:
            other_per_rule[rule] = other_per_rule.get(rule, 0) + mult

    offgrid_total = sum(offgrid_per_rule.values())
    frac = (offgrid_total / total) if total else 0.0
    return {
        "verdict": "FLOW_OFFGRID" if offgrid_total > 0 else "PASS",
        "total": total,
        "offgrid_total": offgrid_total,
        "other_total": total - offgrid_total,
        "offgrid_fraction": round(frac, 4),
        "offgrid_per_rule": dict(sorted(offgrid_per_rule.items())),
        "other_per_rule": dict(sorted(other_per_rule.items())),
    }


def classify_per_rule(per_rule: Dict[str, int]) -> Dict:
    """Classify an already-parsed rule→count dict (the in-flow step_drc
    path has the per-rule counts but not the XML descriptions, so this
    matches on the universal `OFFGRID` rule-NAME token only). Same return
    shape as :func:`classify`, verdict FLOW_OFFGRID when any OFFGRID-class
    rule carries a nonzero count."""
    offgrid_per_rule: Dict[str, int] = {}
    other_per_rule: Dict[str, int] = {}
    for rule, cnt in (per_rule or {}).items():
        if _OFFGRID_NAME_RE.search(str(rule)):
            offgrid_per_rule[str(rule)] = offgrid_per_rule.get(str(rule), 0) + cnt
        else:
            other_per_rule[str(rule)] = other_per_rule.get(str(rule), 0) + cnt
    total = sum(offgrid_per_rule.values()) + sum(other_per_rule.values())
    offgrid_total = sum(offgrid_per_rule.values())
    return {
        "verdict": "FLOW_OFFGRID" if offgrid_total > 0 else "PASS",
        "total": total,
        "offgrid_total": offgrid_total,
        "other_total": total - offgrid_total,
        "offgrid_fraction": round(offgrid_total / total, 4) if total else 0.0,
        "offgrid_per_rule": dict(sorted(offgrid_per_rule.items())),
        "other_per_rule": dict(sorted(other_per_rule.items())),
    }


def summarize(report: Dict) -> str:
    """One-line human verdict for the DRC step's cross-reference."""
    if report["verdict"] == "ERROR":
        return f"OFFGRID classify ERROR: {report.get('reason')}"
    if report["verdict"] == "PASS":
        return (f"no OFFGRID-class DRC ({report['total']} total "
                f"violations are real spacing/width)")
    return (f"FLOW_OFFGRID: {report['offgrid_total']}/{report['total']} "
            f"({report['offgrid_fraction']:.0%}) DRC violations are "
            f"off-grid vertices — a FLOW grid defect, NOT design content "
            f"(top: {dict(list(report['offgrid_per_rule'].items())[:4])}). "
            f"Real spacing/width violations: {report['other_total']}. Fix "
            f"the routing/streamout manufacturing-grid alignment, not the "
            f"design.")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("report", help="KLayout sign-off DRC XML report")
    p.add_argument("--json", default=None, help="write classification JSON")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    report = classify(Path(args.report))
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
    print(summarize(report))
    if report["verdict"] == "ERROR":
        return 2
    return 1 if report["verdict"] == "FLOW_OFFGRID" else 0


if __name__ == "__main__":
    raise SystemExit(main())
