"""v0.1.50 — STA endpoint triage (Pattern-B → program).

Doctrine: `skills/sta-review/SKILL.md` enumerated 5 STA-violation
categories with fix proposals. All deterministic given a STA report
plus per-path delay breakdown.

Categories:
  cell_delay_limited  → upsize driver / Vt swap
  net_delay_limited   → insert buffer / reroute / shorten wire
  logic_depth_limited → pipeline / restructure RTL
  clock_skew_limited  → useful skew / CTS re-balance
  hold_violation      → buffer insertion on min paths
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


CATEGORIES = (
    "cell_delay_limited",
    "net_delay_limited",
    "logic_depth_limited",
    "clock_skew_limited",
    "hold_violation",
)

FIX_STRATEGY: Dict[str, str] = {
    "cell_delay_limited":  "upsize driver cells; Vt swap (LVT)",
    "net_delay_limited":   "insert buffer; reroute or shorten wire",
    "logic_depth_limited": "pipeline path; restructure RTL",
    "clock_skew_limited":  "useful skew; CTS re-balance",
    "hold_violation":      "buffer insertion on min path; delay cell",
}


@dataclass
class EndpointFinding:
    endpoint: str
    slack_ns: float
    category: str
    fix_strategy: str
    cell_delay_pct: Optional[float] = None
    net_delay_pct: Optional[float] = None
    logic_depth: Optional[int] = None


@dataclass
class StaReport:
    findings: List[EndpointFinding]
    wns_ns: Optional[float]
    tns_ns: Optional[float]
    counts_by_category: Dict[str, int]
    total_violations: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "findings": [asdict(f) for f in self.findings],
            "wns_ns": self.wns_ns,
            "tns_ns": self.tns_ns,
            "counts_by_category": self.counts_by_category,
            "total_violations": self.total_violations,
            "emitted_by": _pmd.emitted_by("sta_triage_classify"),
        }


def classify_endpoint(
    cell_delay_pct: Optional[float],
    net_delay_pct: Optional[float],
    logic_depth: Optional[int],
    skew_dominant: bool = False,
    is_hold: bool = False,
) -> str:
    """Classify a single violating endpoint by delay breakdown."""
    if is_hold:
        return "hold_violation"
    if skew_dominant:
        return "clock_skew_limited"
    if logic_depth is not None and logic_depth >= 40:
        return "logic_depth_limited"
    if net_delay_pct is not None and net_delay_pct >= 60:
        return "net_delay_limited"
    if cell_delay_pct is not None and cell_delay_pct >= 60:
        return "cell_delay_limited"
    # Default: pick the bigger of cell/net
    cd = cell_delay_pct or 0
    nd = net_delay_pct or 0
    return "net_delay_limited" if nd >= cd else "cell_delay_limited"


def parse_sta_summary(text: str) -> tuple:
    """Extract WNS / TNS from a typical OpenSTA / DC summary text."""
    wns = None
    tns = None
    m = re.search(r"wns\s+(-?\d+\.?\d*)", text, re.I)
    if m:
        wns = float(m.group(1))
    m = re.search(r"tns\s+(-?\d+\.?\d*)", text, re.I)
    if m:
        tns = float(m.group(1))
    return wns, tns


def build_report(endpoints: List[EndpointFinding],
                  wns: Optional[float],
                  tns: Optional[float]) -> StaReport:
    counts: Dict[str, int] = {c: 0 for c in CATEGORIES}
    for e in endpoints:
        counts[e.category] = counts.get(e.category, 0) + 1
    return StaReport(
        findings=endpoints, wns_ns=wns, tns_ns=tns,
        counts_by_category=counts,
        total_violations=len(endpoints),
    )


def make_finding(endpoint: str, slack_ns: float,
                  cell_delay_pct: Optional[float] = None,
                  net_delay_pct: Optional[float] = None,
                  logic_depth: Optional[int] = None,
                  skew_dominant: bool = False) -> EndpointFinding:
    is_hold = slack_ns < 0 and logic_depth is not None and logic_depth <= 2
    cat = classify_endpoint(cell_delay_pct, net_delay_pct,
                            logic_depth, skew_dominant=skew_dominant,
                            is_hold=is_hold)
    return EndpointFinding(
        endpoint=endpoint, slack_ns=slack_ns, category=cat,
        fix_strategy=FIX_STRATEGY[cat],
        cell_delay_pct=cell_delay_pct, net_delay_pct=net_delay_pct,
        logic_depth=logic_depth,
    )


def report_to_markdown(rep: StaReport) -> str:
    out = ["# STA triage",
           "",
           f"_Emitted by `sta_triage_classify.py` "
           f"(v{_pmd.running_plugin_version()})._",
           "",
           f"- WNS: {rep.wns_ns}",
           f"- TNS: {rep.tns_ns}",
           f"- Total violating endpoints: **{rep.total_violations}**",
           ""]
    out.append("## By category")
    out.append("")
    out.append("| Category | Count | Fix strategy |")
    out.append("|---|---|---|")
    for c in CATEGORIES:
        n = rep.counts_by_category.get(c, 0)
        if n > 0:
            out.append(f"| {c} | {n} | {FIX_STRATEGY[c]} |")
    out.append("")
    out.append("## Per-endpoint")
    out.append("")
    for f in rep.findings[:50]:
        out.append(f"- `{f.endpoint}` slack={f.slack_ns} ns "
                   f"[{f.category}] — {f.fix_strategy}")
    if len(rep.findings) > 50:
        out.append(f"_(+{len(rep.findings)-50} more)_")
    out.append("")
    return "\n".join(out)


def _cli() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--endpoints-json", type=Path, required=True,
                   help='JSON: [{"endpoint": ..., "slack_ns": ..., '
                        '"cell_delay_pct": ..., "net_delay_pct": ..., '
                        '"logic_depth": ...}, ...]')
    p.add_argument("--wns", type=float)
    p.add_argument("--tns", type=float)
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    args = p.parse_args()
    raw = json.loads(args.endpoints_json.read_text(encoding="utf-8"))
    endpoints = [make_finding(**r) for r in raw]
    rep = build_report(endpoints, args.wns, args.tns)
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
