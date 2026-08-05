"""v0.1.50 — Hold-fix planner (Pattern-B → program).

Doctrine: `skills/hold-fix/SKILL.md` had a 3-row strategy table mapping
hold-slack buckets to fix strategies. Pure rule lookup.

Strategy table (verbatim):
  slack >  -50 ps     → single buffer insertion
  -200 ≤ slack ≤ -50  → buffer chain (2-3 buffers)
  slack <  -200 ps    → delay cell insertion OR path restructure
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


STRATEGIES = (
    "single_buffer",
    "buffer_chain",
    "delay_cell_or_restructure",
)

STRATEGY_DESC: Dict[str, str] = {
    "single_buffer": "Insert 1 buffer on the data path",
    "buffer_chain": "Insert 2-3 buffer chain on the data path",
    "delay_cell_or_restructure":
        "Insert delay cell OR restructure path; may need RTL change",
}

BUCKET_BOUNDS_PS = (-50, -200)  # > -50, [-200,-50], < -200


@dataclass
class HoldEndpoint:
    endpoint: str
    slack_ps: float
    strategy: str


def pick_strategy(slack_ps: float) -> str:
    if slack_ps > BUCKET_BOUNDS_PS[0]:
        return "single_buffer"
    if slack_ps >= BUCKET_BOUNDS_PS[1]:
        return "buffer_chain"
    return "delay_cell_or_restructure"


def build_plan(endpoints: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: List[HoldEndpoint] = []
    strat_count = {s: 0 for s in STRATEGIES}
    worst_slack = 0.0
    total_neg = 0.0
    for ep in endpoints:
        slack = ep.get("slack_ps", 0)
        if slack >= 0:
            continue
        s = pick_strategy(slack)
        strat_count[s] += 1
        worst_slack = min(worst_slack, slack)
        total_neg += slack
        out.append(HoldEndpoint(
            endpoint=ep["endpoint"], slack_ps=slack, strategy=s))
    return {
        "endpoints": [asdict(e) for e in out],
        "strategy_counts": strat_count,
        "endpoint_count": len(out),
        "WHS_ps": worst_slack,
        "THS_ps": total_neg,
        "emitted_by": _pmd.emitted_by("hold_fix_planner"),
    }


def plan_to_markdown(plan: Dict[str, Any]) -> str:
    out = ["# Hold-fix plan",
           "",
           f"_Emitted by `hold_fix_planner.py` "
           f"(v{_pmd.running_plugin_version()})._",
           "",
           f"- Violating endpoints: **{plan['endpoint_count']}**",
           f"- WHS: {plan['WHS_ps']} ps",
           f"- THS: {plan['THS_ps']} ps",
           ""]
    out.append("## Strategy distribution")
    out.append("")
    out.append("| Strategy | Endpoints | Description |")
    out.append("|---|---|---|")
    for s in STRATEGIES:
        n = plan["strategy_counts"].get(s, 0)
        if n > 0:
            out.append(f"| {s} | {n} | {STRATEGY_DESC[s]} |")
    out.append("")
    return "\n".join(out)


def _cli() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--endpoints-json", type=Path, required=True,
                   help='JSON: [{"endpoint":"...", "slack_ps":-75}, ...]')
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    args = p.parse_args()
    raw = json.loads(args.endpoints_json.read_text(encoding="utf-8"))
    plan = build_plan(raw)
    md = plan_to_markdown(plan)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
