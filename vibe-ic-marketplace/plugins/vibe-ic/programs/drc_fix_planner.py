"""v0.1.50 — DRC fix-planner (Pattern-B → program).

Doctrine: `skills/drc-fix/SKILL.md` enumerated a 5-step fix workflow + a
rule→fix-strategy table + a fix-order rule. All deterministic. This
program codifies them; the skill becomes a thin wrapper.

Rules
=====

  rule_pattern → fix_strategy:
    spacing  → 'add jog or move sink'
    width    → 'widen wire or replace with wider cell'
    density  → 'add metal fill / add decap'
    antenna  → 'add diode at gate sink OR insert jumper to upper layer'
    enclosure→ 'increase pad/contact enclosure'
    via      → 'add via array / widen single via'
    overhang → 'extend metal beyond contact'
    minarea  → 'add notch/extension to reach min-area'

  fix order (apply in sequence):
    1. spacing (high count, often root-cause for downstream)
    2. minarea
    3. enclosure
    4. via
    5. width
    6. antenna
    7. density
    8. unclassified

Severity gates:
    > 10000 violations on one rule  → MAJOR (likely root-cause root)
    > 1000                          → SIGNIFICANT
    > 100                           → NOTABLE
    > 0                             → MINOR
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


# ---------------------------------------------------------------------------
# Rule classification (sky130/gf180 conventions; deterministic)
# ---------------------------------------------------------------------------
RULE_CATEGORY: Dict[str, str] = {
    "spacing": "spacing", ".sp.": "spacing",
    "width": "width", "min_width": "width",
    "density": "density", "fill": "density",
    "antenna": "antenna", ".ant.": "antenna",
    "enclosure": "enclosure", "encl": "enclosure",
    "via_size": "via",
    "overhang": "overhang", ".ovh.": "overhang",
    "minarea": "minarea", "min_area": "minarea",
    "notch": "minarea",
}

FIX_STRATEGY: Dict[str, str] = {
    "spacing":   "add jog or move sink to clear spacing",
    "width":     "widen wire or replace with wider cell variant",
    "density":   "add metal fill or decap cells; rerun fill insertion",
    "antenna":   "add diode at gate sink OR insert jumper to upper layer",
    "enclosure": "increase pad/contact enclosure",
    "via":       "add via array or widen single via",
    "overhang":  "extend metal beyond contact",
    "minarea":   "add notch/extension to reach min-area threshold",
    "unknown":   "manual triage; check rule deck",
}

FIX_ORDER: Tuple[str, ...] = (
    "spacing", "minarea", "enclosure", "via",
    "width", "antenna", "density", "unknown",
)

SEVERITY_BAND: Tuple[Tuple[int, str], ...] = (
    (10000, "MAJOR"),
    (1000, "SIGNIFICANT"),
    (100, "NOTABLE"),
    (1, "MINOR"),
)


def classify_rule(rule_id: str) -> str:
    """Map a DRC rule-id (e.g. 'met1.2', 'M2.SP.1', 'ANTENNA.5') to a
    canonical category. Uses substring keys with dot-boundaries to avoid
    accidental matches (e.g. 'w' matching 'weird')."""
    s = "." + rule_id.lower() + "."
    for key, cat in RULE_CATEGORY.items():
        if key in s:
            return cat
    # bare 'via' check (covers via1, via2, via.* but not 'via_size' which
    # already matched above)
    if ".via" in s:
        return "via"
    return "unknown"


def severity_for(count: int) -> str:
    for threshold, label in SEVERITY_BAND:
        if count >= threshold:
            return label
    return "NONE"


# ---------------------------------------------------------------------------
# Plan dataclasses
# ---------------------------------------------------------------------------
@dataclass
class RulePlan:
    rule_id: str
    count: int
    category: str
    severity: str
    fix_strategy: str


@dataclass
class FixPlan:
    rules_by_category: Dict[str, List[RulePlan]]
    ordered: List[RulePlan]       # ordered per FIX_ORDER then by count desc
    total_violations: int
    expected_residual_after_plan: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rules_by_category": {
                k: [asdict(r) for r in v]
                for k, v in self.rules_by_category.items()
            },
            "ordered": [asdict(r) for r in self.ordered],
            "total_violations": self.total_violations,
            "expected_residual_after_plan": self.expected_residual_after_plan,
            "emitted_by": _pmd.emitted_by("drc_fix_planner"),
        }


def build_plan(per_rule_counts: Dict[str, int]) -> FixPlan:
    """Pure function: build the fix plan from a {rule_id: count} dict."""
    rules: List[RulePlan] = []
    by_cat: Dict[str, List[RulePlan]] = {c: [] for c in FIX_ORDER}
    for rule_id, count in per_rule_counts.items():
        cat = classify_rule(rule_id)
        rp = RulePlan(
            rule_id=rule_id, count=count, category=cat,
            severity=severity_for(count),
            fix_strategy=FIX_STRATEGY.get(cat, FIX_STRATEGY["unknown"]),
        )
        rules.append(rp)
        by_cat.setdefault(cat, []).append(rp)

    # Order by FIX_ORDER then by count descending within each category
    ordered: List[RulePlan] = []
    for cat in FIX_ORDER:
        ordered.extend(sorted(by_cat.get(cat, []),
                              key=lambda r: r.count, reverse=True))

    total = sum(per_rule_counts.values())
    # Heuristic: spacing fixes ~70% of violations of all types when applied
    # FIRST (skill's observation: '1000 violations are usually 5 root causes').
    # Conservative estimate: assume 80% reduction.
    expected_residual = int(round(total * 0.2))

    return FixPlan(
        rules_by_category={k: v for k, v in by_cat.items() if v},
        ordered=ordered,
        total_violations=total,
        expected_residual_after_plan=expected_residual,
    )


# ---------------------------------------------------------------------------
# Markdown emit (skill's § Root causes table)
# ---------------------------------------------------------------------------
def plan_to_markdown(plan: FixPlan) -> str:
    out = ["# DRC fix plan",
           "",
           f"_Emitted by `drc_fix_planner.py` "
           f"(v{_pmd.running_plugin_version()}). "
           f"Refuse to overclaim the fix-coverage estimate._",
           ""]
    out.append(f"- Total violations: **{plan.total_violations}**")
    out.append(f"- Expected residual after plan: ~{plan.expected_residual_after_plan}")
    out.append("")
    out.append("## Root causes")
    out.append("")
    out.append("| # | Rule | Count | Severity | Category | Fix strategy |")
    out.append("|---|------|-------|----------|----------|--------------|")
    for i, r in enumerate(plan.ordered, start=1):
        out.append(f"| {i} | `{r.rule_id}` | {r.count} | {r.severity} "
                   f"| {r.category} | {r.fix_strategy} |")
    out.append("")
    out.append("## Fix order")
    out.append("")
    for i, cat in enumerate(FIX_ORDER, start=1):
        rules_in_cat = plan.rules_by_category.get(cat, [])
        if rules_in_cat:
            count_str = ", ".join(f"`{r.rule_id}`({r.count})"
                                  for r in rules_in_cat[:3])
            out.append(f"{i}. **{cat}** — {count_str}"
                       f"{', ...' if len(rules_in_cat) > 3 else ''}")
    out.append("")
    return "\n".join(out)


def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Deterministic DRC fix planner.")
    p.add_argument("--counts-json", type=Path, required=True,
                   help='JSON: {"rule_id": count, ...}')
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    args = p.parse_args()
    counts = json.loads(args.counts_json.read_text(encoding="utf-8"))
    plan = build_plan(counts)
    md = plan_to_markdown(plan)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(
            json.dumps(plan.as_dict(), indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
