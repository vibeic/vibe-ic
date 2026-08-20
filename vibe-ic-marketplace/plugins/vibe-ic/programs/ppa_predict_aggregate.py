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
from _ppa import area as _ppa_area  # noqa: E402  (PPA-009 taxonomy labels)

# ─── WHAT CLASS OF NUMBER THIS PROGRAM PRODUCES (PPA-009, spec §7.3) ─────────
# Every number below is an ESTIMATE made BEFORE synthesis has run: a cell count
# multiplied by a constant from a table. It is not a measurement of anything.
#
# PPA_INTERFACES.md §2 says ESTIMATED is "never in final PPA", and the way that
# is enforced here is structural rather than advisory: the figures are published
# under `area.estimate.pre_synthesis_*`, which `_ppa.area` registers as
# RTL_PROXY, and `_ppa.area.area_record` REFUSES to build a PHYSICAL metric with
# status ESTIMATED at all. So a final-measurement extractor cannot adopt these
# numbers by relabelling them: the record it would need cannot be constructed.
#
# The scale of the error being guarded against, from one real completed run
# (`spm`, gf180mcuD, 252 cells): this table predicts 252 * 30.0 = 7560 um^2,
# against a post-route core of 12294 um^2 and a die of 20164 um^2. The estimate
# is 38.5% under the core and 62.5% under the die. It is a planning number.
STATUS = _ppa_area.ESTIMATED
METRIC_CLASS = _ppa_area.RTL_PROXY
ELIGIBLE_FOR_PHYSICAL_PPA = False
NOT_A_MEASUREMENT = (
    "PRE-SYNTHESIS ESTIMATE, not a measurement. Produced before synthesis, "
    "placement or routing exist, from a cell count and a constant table. It "
    "may not be adopted as, compared against, or reported in place of a "
    "post-route area (docs/PPA_INTERFACES.md §2).")


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


def _assumptions(pdk: str, activity_factor: float) -> Dict[str, Dict[str, Any]]:
    """One entry per published number, stating what that number assumed.

    The brief for this program is "give every number its assumption". A number
    whose assumptions are not written next to it reads exactly like a
    measurement at the moment somebody quotes it into a summary — which is how
    a planning figure becomes a claim about silicon.
    """
    known = pdk in AREA_PER_CELL_UM2
    fallback = "" if known else (
        f" PDK {pdk!r} is not in the table, so the sky130A row was used as a "
        f"fallback and the figure is weaker still.")
    return {
        "area_um2": {
            "formula": "rtl_cell_count * AREA_PER_CELL_UM2[pdk]",
            "area_per_cell_um2": AREA_PER_CELL_UM2.get(
                pdk, AREA_PER_CELL_UM2["sky130A"]),
            "pdk_in_table": known,
            "assumes": (
                "the mean standard-cell area of the library is representative "
                "of the cells synthesis will actually pick; that the RTL cell "
                "count survives synthesis unchanged; and that placement "
                "density, filler, routing-driven upsizing and the die envelope "
                "contribute nothing." + fallback),
            "known_direction_of_error": (
                "UNDER. Measured on one real completed run (spm, gf180mcuD, "
                "252 cells): this table gives 7560 um^2 against a post-route "
                "core of 12294 um^2 (-38.5%) and a die of 20164 um^2 "
                "(-62.5%)."),
        },
        "area_mm2": {
            "formula": "area_um2 / 1e6",
            "assumes": "everything area_um2 assumes; it is the same number.",
        },
        "power_uw": {
            "formula": ("rtl_cell_count * POWER_PER_CELL_UW[pdk] * "
                        "max(0, activity_factor)"),
            "power_per_cell_uw": POWER_PER_CELL_UW.get(
                pdk, POWER_PER_CELL_UW["sky130A"]),
            "activity_factor": activity_factor,
            "pdk_in_table": known,
            "assumes": (
                "100 MHz, the table's typical activity, a uniform activity "
                "factor across every cell, and no clock-gating, no glitch "
                "power and no leakage split." + fallback),
        },
        "fmax_hint_mhz": {
            "formula": "read verbatim from README/spec if declared, else None",
            "assumes": ("nothing — it is a DECLARATION copied from the "
                        "document, not an estimate. It is not evidence that "
                        "the design meets it."),
        },
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
    activity_factor: float = 1.0   # PPA-009: an assumption must be recoverable
                                   # from the record it qualifies
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["emitted_by"] = _pmd.emitted_by("ppa_predict_aggregate")
        # PPA-009. These four keys travel with EVERY emitted document, before
        # any caller gets a chance to drop them, because the failure mode is a
        # number quoted without them.
        d["status"] = STATUS
        d["metric_class"] = METRIC_CLASS
        d["eligible_for_physical_ppa"] = ELIGIBLE_FOR_PHYSICAL_PPA
        d["not_a_measurement"] = NOT_A_MEASUREMENT
        d["assumptions"] = _assumptions(self.pdk, self.activity_factor)
        return d

    def as_metric_records(self) -> List[Dict[str, Any]]:
        """The estimate as canonical `vibeic.ppa.metric.v1` records.

        THIS IS THE WIRING THAT MAKES THE LABEL LOAD-BEARING. It is the only
        canonical form of these numbers, every record it returns is ESTIMATED
        and RTL_PROXY, and `_ppa.area.assert_eligible_for_physical_ppa` raises
        on all of them. A final-measurement extractor therefore has no route
        from this program to a physical area figure — not a discouraged route,
        no route.
        """
        scope = {"stage": "pre_synthesis", "pdk": self.pdk,
                 "activity_factor": self.activity_factor}
        assume = _assumptions(self.pdk, self.activity_factor)
        return [
            _ppa_area.area_record(
                "area.estimate.pre_synthesis_um2", _ppa_area.ESTIMATED,
                value=self.area_um2, scope=scope,
                assumptions=assume["area_um2"]),
            _ppa_area.area_record(
                "area.estimate.pre_synthesis_mm2", _ppa_area.ESTIMATED,
                value=self.area_mm2, scope=scope,
                assumptions=assume["area_mm2"]),
        ]


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
        activity_factor=activity_factor,
        notes=notes,
    )


def estimate_to_markdown(est: PpaEstimate) -> str:
    out = ["# PPA pre-synthesis estimate",
           "",
           f"**status: {STATUS}** &nbsp;|&nbsp; "
           f"`metric_class: {METRIC_CLASS}` &nbsp;|&nbsp; "
           f"`eligible_for_physical_ppa: "
           f"{str(ELIGIBLE_FOR_PHYSICAL_PPA).lower()}`",
           "",
           f"> {NOT_A_MEASUREMENT}",
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
    out.append("## What each number assumed")
    out.append("")
    out.append("Every figure above is ESTIMATED. These are the assumptions it "
               "rests on; a number quoted without them reads as a measurement.")
    out.append("")
    for name, a in _assumptions(est.pdk, est.activity_factor).items():
        out.append(f"- **`{name}`** — `{a['formula']}`")
        out.append(f"  - assumes: {a['assumes']}")
        if "known_direction_of_error" in a:
            out.append(f"  - known direction of error: "
                       f"{a['known_direction_of_error']}")
    out.append("")
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
