"""v0.1.50 — LVS triage classifier (Pattern-B → program).

ROLE: producer/classifier

Issue #1980 moved this classifier out of the gate denominator. It describes an
LVS mismatch; `lvs_report_check` and `lvs_signoff_guard` own the Step-31
refusal predicate.
Doctrine: `skills/lvs-triage/SKILL.md` enumerated a 4-category triage +
top-3 root-cause heuristic. All deterministic.

Categories (canonical):
  unmatched_instance
  unmatched_net          (short or open)
  device_param_mismatch  (W/L/M/NF)
  property_mismatch      (label, dummy)

Top-3 root cause heuristic from skill:
  1. Missing label on a net           → most common net mismatch
  2. Missing via between metal layers → common short/open
  3. Wrong device variant from PDK    → most common param mismatch
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)
import _vacuous_exit as _vx  # noqa: E402


CATEGORIES = (
    "unmatched_instance",
    "unmatched_net",
    "device_param_mismatch",
    "property_mismatch",
)

ROOT_CAUSE_HINTS: Dict[str, str] = {
    "unmatched_net": (
        "TOP-3: missing label on net (most common); missing via between "
        "layers; floating tap-cell connection — check Magic label add + "
        "via insertion"),
    "unmatched_instance": (
        "TOP-3: missing/extra instance (check generate-blocks); blackbox "
        "macro not declared; tap/decap mismatch — check macro stub list"),
    "device_param_mismatch": (
        "TOP-3: wrong device variant from PDK (e.g. HVT vs LVT); W/L/M/NF "
        "stripped during yosys flatten; tolerance too tight — check "
        "extracted vs schematic property"),
    "property_mismatch": (
        "TOP-3: dummy device label missing; intentional analog dummy not "
        "documented; spice-side mult attribute deleted — check sky130A "
        "Netgen setup property delete list"),
}


LINE_PATTERNS: List = [
    # (category, regex)
    ("unmatched_net", re.compile(
        r"net\s+\S+\s+(short|open|mismatch|not\s+matched)", re.I)),
    ("unmatched_net", re.compile(r"Net\s+\S+\s+(?:un)?matched", re.I)),
    ("unmatched_instance", re.compile(
        r"(unmatched|missing)\s+(instance|cell|subcircuit)", re.I)),
    ("device_param_mismatch", re.compile(
        r"(W|L|M|NF)\s*=\s*\S+\s+(?:vs|!=|mismatch)", re.I)),
    ("device_param_mismatch", re.compile(
        r"Property\s+(W|L|M|NF)\b", re.I)),
    ("property_mismatch", re.compile(
        r"property\s+\S+\s+(?:mismatch|differ)", re.I)),
    ("property_mismatch", re.compile(r"label\s+\S+\s+missing", re.I)),
]


@dataclass
class TriageFinding:
    category: str
    line: str
    line_no: int


@dataclass
class TriageReport:
    findings_by_category: Dict[str, List[TriageFinding]]
    counts: Dict[str, int]
    total: int
    top_3_root_causes: Dict[str, str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "findings_by_category": {
                k: [asdict(f) for f in v]
                for k, v in self.findings_by_category.items()
            },
            "counts": self.counts,
            "total": self.total,
            "top_3_root_causes": self.top_3_root_causes,
            "emitted_by": _pmd.emitted_by("lvs_triage_classify"),
        }


def classify_line(line: str) -> Optional[str]:
    """Return the category for a single LVS-report line, or None."""
    for cat, pat in LINE_PATTERNS:
        if pat.search(line):
            return cat
    return None


def classify_report(report_text: str) -> TriageReport:
    findings: Dict[str, List[TriageFinding]] = {c: [] for c in CATEGORIES}
    for lineno, line in enumerate(report_text.splitlines(), start=1):
        cat = classify_line(line)
        if cat:
            findings[cat].append(
                TriageFinding(category=cat, line=line.strip(), line_no=lineno))

    counts = {c: len(v) for c, v in findings.items()}
    total = sum(counts.values())
    # Top-3 by count
    sorted_cats = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top_3 = {c: ROOT_CAUSE_HINTS[c] for c, n in sorted_cats[:3] if n > 0}

    return TriageReport(
        findings_by_category={k: v for k, v in findings.items() if v},
        counts=counts, total=total, top_3_root_causes=top_3,
    )


def report_to_markdown(rep: TriageReport) -> str:
    out = ["# LVS triage",
           "",
           f"_Emitted by `lvs_triage_classify.py` "
           f"(v{_pmd.running_plugin_version()})._",
           "",
           f"Total findings: **{rep.total}**",
           ""]
    out.append("## Counts by category")
    out.append("")
    out.append("| Category | Count |")
    out.append("|---|---|")
    for cat in CATEGORIES:
        out.append(f"| {cat} | {rep.counts.get(cat, 0)} |")
    out.append("")
    out.append("## Top-3 root-cause hints")
    out.append("")
    for cat, hint in rep.top_3_root_causes.items():
        out.append(f"- **{cat}**: {hint}")
    out.append("")
    return "\n".join(out)


def _cli() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--report", type=Path, required=True,
                   help="Netgen/Calibre LVS report text")
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    args = p.parse_args()
    # This is a Step-31 classifier output, not a gate. `reports/phase3/lvs.rpt`
    # is already judged by the blocking predicates, so an absent report is a
    # disclosed no-output state rather than a second authority or a traceback.
    if not args.report.is_file():
        reason = f"LVS report not present: {args.report}"
        _vx.announce_vacuous("lvs_triage_classify", reason)
        print(_vx.verdict_line("lvs_triage_classify", passed=True,
                               skipped=True, reason=reason))
        return _vx.exit_code(passed=True, skipped=True)
    rep = classify_report(args.report.read_text(encoding="utf-8"))
    md = report_to_markdown(rep)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(
            json.dumps(rep.as_dict(), indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
