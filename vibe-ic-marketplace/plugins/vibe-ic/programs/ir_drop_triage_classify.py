"""v0.1.50 — IR-drop triage classifier (Pattern-B → program).

Doctrine: `skills/ir-drop-triage/SKILL.md` enumerated 4 causes + 4 fixes
mapped 1:1. Deterministic.

Causes  : strap_sparse, switching_cluster, narrow_metal, weak_via
Fixes   : add_straps,   add_decap,         widen_metal,  add_via_array
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


CAUSES = ("strap_sparse", "switching_cluster", "narrow_metal", "weak_via")

CAUSE_TO_FIX: Dict[str, str] = {
    "strap_sparse":       "add_straps",
    "switching_cluster":  "add_decap",
    "narrow_metal":       "widen_metal",
    "weak_via":           "add_via_array",
}

FIX_DESC: Dict[str, str] = {
    "add_straps":     "Add power straps or widen existing in the hotspot region",
    "add_decap":      "Insert decap cells near aggressors; spread high-activity flops",
    "widen_metal":    "Widen metal trunk OR shorten run length (EM and IR)",
    "add_via_array":  "Replace single via with via-array on hotspot straps",
}


@dataclass
class IrHotspot:
    cell: str
    ir_uv: float            # local IR drop in microvolts
    cause: str
    fix: str
    fix_desc: str


def classify_cause(strap_pitch_um: float,
                   activity_density: float,
                   metal_width_um: float,
                   via_count: int) -> str:
    """Pick the dominant cause from physical-design knobs.

    Rules (deterministic ordering):
      via_count < 4                → weak_via
      strap_pitch_um > 100         → strap_sparse
      activity_density > 0.7       → switching_cluster
      metal_width_um < 0.4         → narrow_metal
      else                         → strap_sparse (default)
    """
    if via_count < 4:
        return "weak_via"
    if strap_pitch_um > 100:
        return "strap_sparse"
    if activity_density > 0.7:
        return "switching_cluster"
    if metal_width_um < 0.4:
        return "narrow_metal"
    return "strap_sparse"


def build_triage(hotspots: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: List[IrHotspot] = []
    cause_count: Dict[str, int] = {c: 0 for c in CAUSES}
    worst_ir = 0.0
    for h in hotspots:
        cause = classify_cause(
            strap_pitch_um=h.get("strap_pitch_um", 50),
            activity_density=h.get("activity_density", 0),
            metal_width_um=h.get("metal_width_um", 1),
            via_count=h.get("via_count", 100),
        )
        fix = CAUSE_TO_FIX[cause]
        out.append(IrHotspot(
            cell=h["cell"], ir_uv=h.get("ir_uv", 0),
            cause=cause, fix=fix,
            fix_desc=FIX_DESC[fix],
        ))
        cause_count[cause] += 1
        worst_ir = max(worst_ir, h.get("ir_uv", 0))
    return {
        "hotspots": [asdict(h) for h in out],
        "cause_count": cause_count,
        "worst_ir_uv": worst_ir,
        "hotspot_count": len(out),
        "emitted_by": _pmd.emitted_by("ir_drop_triage_classify"),
    }


def triage_to_markdown(t: Dict[str, Any]) -> str:
    out = ["# IR-drop triage",
           "",
           f"_Emitted by `ir_drop_triage_classify.py` "
           f"(v{_pmd.running_plugin_version()})._",
           "",
           f"- Hotspots: **{t['hotspot_count']}**",
           f"- Worst IR: {t['worst_ir_uv']} uV",
           ""]
    out.append("## Causes")
    out.append("")
    out.append("| Cause | Count | Fix | Description |")
    out.append("|---|---|---|---|")
    for c in CAUSES:
        n = t["cause_count"].get(c, 0)
        if n > 0:
            fix = CAUSE_TO_FIX[c]
            out.append(f"| {c} | {n} | {fix} | {FIX_DESC[fix]} |")
    out.append("")
    return "\n".join(out)


def _cli() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hotspots-json", type=Path, required=True)
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    args = p.parse_args()
    raw = json.loads(args.hotspots_json.read_text(encoding="utf-8"))
    t = build_triage(raw)
    md = triage_to_markdown(t)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(json.dumps(t, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
