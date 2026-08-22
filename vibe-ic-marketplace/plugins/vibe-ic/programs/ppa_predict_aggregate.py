"""v0.1.50 — PPA predict aggregator (Pattern-B → program).

Doctrine: `skills/ppa-predict/SKILL.md` returns power/area/Fmax
estimates pre-synthesis. The deterministic part is:
  - parsing README/spec for declared PPA hints  → readme_ppa_extractor
  - counting RTL cells (yosys stat)              → eda_synth stat tool
  - mapping cell count → area estimate by PDK   → deterministic table

This aggregator pins those rules; the skill is the wrapper that
narrates trade-off implications.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import plugin_manifest_discovery as _pmd  # noqa: E402  (#800 ONE version reader)


# Area-per-cell (um^2) estimates per PDK. Conservative averages used as
# floors for an EARLY estimate (not signoff). Source: typical sky130A/
# gf180mcuC standard-cell library means.
AREA_PER_CELL_UM2: Dict[str, float] = {
    "sky130A":  20.0,
    "gf180mcuC": 30.0,
    "gf180mcuD": 30.0,
}

# Power per cell at 100 MHz typical activity (uW), conservative floor.
POWER_PER_CELL_UW: Dict[str, float] = {
    "sky130A":  0.6,
    "gf180mcuC": 1.0,
    "gf180mcuD": 1.0,
}


@dataclass
class PpaEstimate:
    rtl_cell_count: int
    pdk: str
    area_um2: float
    area_mm2: float
    power_uw: float
    fmax_hint_mhz: Optional[float]   # from README/spec if declared, else None
    declared_area_um2: Optional[float]
    declared_power_uw: Optional[float]
    estimate_floor: bool      # True when relying on conservative tables only
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["emitted_by"] = _pmd.emitted_by("ppa_predict_aggregate")
        return d


def estimate_area_um2(cell_count: int, pdk: str) -> float:
    return cell_count * AREA_PER_CELL_UM2.get(pdk, AREA_PER_CELL_UM2["sky130A"])


def estimate_power_uw(cell_count: int, pdk: str,
                       activity_factor: float = 1.0) -> float:
    return (cell_count
            * POWER_PER_CELL_UW.get(pdk, POWER_PER_CELL_UW["sky130A"])
            * max(0.0, activity_factor))


def build_estimate(
    rtl_cell_count: int,
    pdk: str = "sky130A",
    fmax_hint_mhz: Optional[float] = None,
    declared_area_um2: Optional[float] = None,
    declared_power_uw: Optional[float] = None,
    activity_factor: float = 1.0,
) -> PpaEstimate:
    area = estimate_area_um2(rtl_cell_count, pdk)
    power = estimate_power_uw(rtl_cell_count, pdk, activity_factor)
    notes: List[str] = []
    if declared_area_um2 is not None and area > declared_area_um2 * 1.2:
        notes.append("RTL-cell-count estimate exceeds declared area by >20%; "
                     "expect synthesis to tighten via flatten/sharing.")
    if declared_power_uw is not None and power > declared_power_uw * 1.5:
        notes.append("Estimated power exceeds declared by >50%; review "
                     "activity factor or clock gating.")
    if fmax_hint_mhz is None:
        notes.append("No Fmax hint found in README/spec; predict step "
                     "cannot offer a number — defer to STA after synth.")
    return PpaEstimate(
        rtl_cell_count=rtl_cell_count,
        pdk=pdk,
        area_um2=area, area_mm2=area / 1e6,
        power_uw=power,
        fmax_hint_mhz=fmax_hint_mhz,
        declared_area_um2=declared_area_um2,
        declared_power_uw=declared_power_uw,
        estimate_floor=(declared_area_um2 is None and declared_power_uw is None),
        notes=notes,
    )


def estimate_to_markdown(est: PpaEstimate) -> str:
    out = ["# PPA pre-synthesis estimate",
           "",
           f"_Emitted by `ppa_predict_aggregate.py` "
           f"(v{_pmd.running_plugin_version()}). "
           f"Refuse to overclaim — the estimate is a FLOOR derived from "
           f"cell-count tables, not signoff PPA._",
           "",
           f"- **PDK**: `{est.pdk}`",
           f"- **RTL cell count**: {est.rtl_cell_count}",
           f"- **Estimated area**: {est.area_um2:.1f} um² ({est.area_mm2:.4f} mm²)",
           f"- **Estimated power**: {est.power_uw:.2f} uW",
           f"- **Fmax hint** (from spec): "
           f"{est.fmax_hint_mhz if est.fmax_hint_mhz else 'not declared'} MHz",
           f"- **Pure-floor estimate?**: {est.estimate_floor}",
           ""]
    if est.notes:
        out.append("## Notes")
        out.append("")
        for n in est.notes:
            out.append(f"- {n}")
        out.append("")
    return "\n".join(out)


def _cli() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cell-count", type=int, required=True)
    p.add_argument("--pdk", default="sky130A")
    p.add_argument("--fmax-hint-mhz", type=float)
    p.add_argument("--declared-area-um2", type=float)
    p.add_argument("--declared-power-uw", type=float)
    p.add_argument("--activity", type=float, default=1.0)
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    args = p.parse_args()
    est = build_estimate(
        rtl_cell_count=args.cell_count, pdk=args.pdk,
        fmax_hint_mhz=args.fmax_hint_mhz,
        declared_area_um2=args.declared_area_um2,
        declared_power_uw=args.declared_power_uw,
        activity_factor=args.activity,
    )
    md = estimate_to_markdown(est)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(json.dumps(est.as_dict(), indent=2),
                                  encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
