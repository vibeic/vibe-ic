"""v0.1.51 — Chip-level 5-tier sign-off ladder runner (B1 from spm pilot).

Doctrine: spm pilot discovered the 9 sub-tier sign-off ladder
serially-by-hand, surfacing 4 silicon-critical bugs along the way.
This program runs all 9 sub-tiers in one pass against a project
directory, aggregating verdicts into a canonical JSON.

Tiers (9 sub-checks):

  Tier 1   DRC          full KLayout / Magic deck (not basic)
  Tier 1.5 DRC heatmap   geographic violation distribution
  Tier 2   PDN           SPECIALNETS count > 0
  Tier 2   IR-drop       worst-IR < budget threshold
  Tier 2   EM/decap      decap_cell_count >= per-area threshold
  Tier 3   Antenna       Magic + KLayout
  Tier 3   ESD/pad-ring  sky130 ESD diodes per cell row
  Tier 4   LVS device    Netgen 261=261 device-class match
  Tier 4.5 LVS net       Netgen w/ lvs_netgen_setup_emit supplement
  Tier 5   Latch-up      tapcell density >= PDK threshold

Each tier is a deterministic check; the runner doesn't invoke EDA
tools directly (that's mcp-eda's job) — it consumes per-tier check
artifacts and emits a canonical verdict.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TierResult:
    tier_id: str           # e.g. "T1", "T1.5", "T2_PDN"
    name: str              # human label
    verdict: str           # PASS / FAIL / WARN / WAIVED / NOT_RUN
    details: Dict[str, Any] = field(default_factory=dict)
    artifact_path: Optional[str] = None
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Per-tier checkers
# ---------------------------------------------------------------------------
def check_tier_1_drc(project_dir: Path) -> TierResult:
    """Tier 1 DRC — read reports/drc/full_deck.json if present."""
    art = project_dir / "reports" / "drc" / "full_deck.json"
    if not art.exists():
        return TierResult("T1", "Full DRC (KLayout/Magic)", "NOT_RUN",
                            notes="reports/drc/full_deck.json missing")
    data = json.loads(art.read_text(encoding="utf-8"))
    n = int(data.get("violations", -1))
    verdict = "PASS" if n == 0 else "FAIL"
    return TierResult("T1", "Full DRC (KLayout/Magic)", verdict,
                        details={"violations": n},
                        artifact_path=str(art))


def check_tier_1_5_drc_heatmap(project_dir: Path) -> TierResult:
    """Tier 1.5 — diagnostic only, report presence."""
    art = project_dir / "reports" / "drc" / "geographic_heatmap.json"
    if not art.exists():
        return TierResult("T1.5", "DRC heatmap", "NOT_RUN",
                            notes="diagnostic only")
    return TierResult("T1.5", "DRC heatmap", "PASS",
                        artifact_path=str(art))


def check_tier_2_pdn(project_dir: Path,
                       min_specialnets: int = 1) -> TierResult:
    """Tier 2 PDN — SPECIALNETS in the final DEF must be > 0."""
    art = project_dir / "reports" / "pnr" / "pdn.json"
    if not art.exists():
        return TierResult("T2_PDN", "Power Distribution Network",
                            "NOT_RUN", notes="reports/pnr/pdn.json missing")
    data = json.loads(art.read_text(encoding="utf-8"))
    n = int(data.get("specialnets", 0))
    verdict = "PASS" if n >= min_specialnets else "FAIL"
    return TierResult("T2_PDN", "Power Distribution Network", verdict,
                        details={"specialnets": n,
                                 "min_required": min_specialnets},
                        artifact_path=str(art))


def check_tier_2_ir(project_dir: Path,
                     budget_uv: float = 35.0) -> TierResult:
    """Tier 2 IR-drop — worst IR must be below per-budget threshold."""
    art = project_dir / "reports" / "pnr" / "ir_drop.json"
    if not art.exists():
        return TierResult("T2_IR", "IR-drop", "NOT_RUN",
                            notes="reports/pnr/ir_drop.json missing")
    data = json.loads(art.read_text(encoding="utf-8"))
    worst = float(data.get("worst_ir_uv", 1e9))
    verdict = "PASS" if worst <= budget_uv else "FAIL"
    return TierResult("T2_IR", "IR-drop", verdict,
                        details={"worst_ir_uv": worst,
                                 "budget_uv": budget_uv},
                        artifact_path=str(art))


def check_tier_2_decap(project_dir: Path,
                        min_decap: int = 100) -> TierResult:
    """Tier 2 EM/decap — total decap cell count >= threshold."""
    art = project_dir / "reports" / "pnr" / "decap_count.json"
    if not art.exists():
        return TierResult("T2_DECAP", "EM/decap", "NOT_RUN",
                            notes="reports/pnr/decap_count.json missing")
    data = json.loads(art.read_text(encoding="utf-8"))
    n = int(data.get("decap_cells", 0))
    verdict = "PASS" if n >= min_decap else "FAIL"
    return TierResult("T2_DECAP", "EM/decap", verdict,
                        details={"decap_cells": n,
                                 "min_required": min_decap},
                        artifact_path=str(art))


def check_tier_3_antenna(project_dir: Path) -> TierResult:
    """Tier 3 antenna — Magic + KLayout both report 0."""
    art_magic = project_dir / "reports" / "antenna" / "magic.json"
    art_klayout = project_dir / "reports" / "antenna" / "klayout.json"
    if not art_magic.exists() and not art_klayout.exists():
        return TierResult("T3_ANTENNA", "Antenna", "NOT_RUN",
                            notes="no antenna artifacts found")
    m_viol = (int(json.loads(art_magic.read_text(encoding="utf-8")).get(
        "violations", -1)) if art_magic.exists() else -1)
    k_viol = (int(json.loads(art_klayout.read_text(encoding="utf-8")).get(
        "violations", -1)) if art_klayout.exists() else -1)
    verdict = ("PASS" if (m_viol == 0 and k_viol == 0)
                else "FAIL" if (m_viol > 0 or k_viol > 0)
                else "WARN")
    return TierResult("T3_ANTENNA", "Antenna", verdict,
                        details={"magic_violations": m_viol,
                                 "klayout_violations": k_viol})


def check_tier_3_esd(project_dir: Path) -> TierResult:
    """Tier 3 ESD/pad-ring — qualitative artifact present."""
    art = project_dir / "reports" / "esd" / "esd_padring.json"
    if not art.exists():
        return TierResult("T3_ESD", "ESD/pad-ring", "NOT_RUN")
    data = json.loads(art.read_text(encoding="utf-8"))
    verdict = "PASS" if data.get("clean") else "FAIL"
    return TierResult("T3_ESD", "ESD/pad-ring", verdict,
                        details=data, artifact_path=str(art))


def check_tier_4_lvs_device(project_dir: Path) -> TierResult:
    """Tier 4 LVS device class — Netgen 261=261 style match."""
    art = project_dir / "reports" / "lvs" / "device_class.json"
    if not art.exists():
        return TierResult("T4_LVS_DEV", "LVS device class", "NOT_RUN")
    data = json.loads(art.read_text(encoding="utf-8"))
    verdict = "PASS" if data.get("device_class_match") else "FAIL"
    return TierResult("T4_LVS_DEV", "LVS device class", verdict,
                        details=data, artifact_path=str(art))


def check_tier_4_5_lvs_net(project_dir: Path) -> TierResult:
    """Tier 4.5 LVS net-level. Uses lvs_netgen_setup_emit supplement
    in practice; here we just consume the resulting netgen verdict."""
    art = project_dir / "reports" / "lvs" / "net_level.json"
    if not art.exists():
        return TierResult("T4.5_LVS_NET", "LVS net-level", "NOT_RUN")
    data = json.loads(art.read_text(encoding="utf-8"))
    verdict = data.get("verdict", "FAIL")
    # The standard verdict for blackbox-macro projects is "WAIVED"
    # (open-source LVS gap; commercial Calibre closes it).
    return TierResult("T4.5_LVS_NET", "LVS net-level", verdict,
                        details=data, artifact_path=str(art))


def check_tier_5_latchup(project_dir: Path,
                          min_tapcells_per_mm2: int = 100) -> TierResult:
    """Tier 5 latch-up — tap cell density above PDK threshold."""
    art = project_dir / "reports" / "pnr" / "tapcell_density.json"
    if not art.exists():
        return TierResult("T5_LATCHUP", "Latch-up tap cells", "NOT_RUN")
    data = json.loads(art.read_text(encoding="utf-8"))
    density = float(data.get("tapcells_per_mm2", 0))
    verdict = "PASS" if density >= min_tapcells_per_mm2 else "FAIL"
    return TierResult("T5_LATCHUP", "Latch-up tap cells", verdict,
                        details={"tapcells_per_mm2": density,
                                 "min_required": min_tapcells_per_mm2},
                        artifact_path=str(art))


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
TIER_CHECKS: Tuple = (
    check_tier_1_drc,
    check_tier_1_5_drc_heatmap,
    check_tier_2_pdn,
    check_tier_2_ir,
    check_tier_2_decap,
    check_tier_3_antenna,
    check_tier_3_esd,
    check_tier_4_lvs_device,
    check_tier_4_5_lvs_net,
    check_tier_5_latchup,
)


@dataclass
class LadderReport:
    project_dir: str
    tiers: List[TierResult]
    overall_verdict: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "tiers": [t.as_dict() for t in self.tiers],
            "overall_verdict": self.overall_verdict,
            "emitted_by": "signoff_ladder_run v0.1.51",
        }


def aggregate_verdict(tiers: List[TierResult]) -> str:
    """Aggregate per-tier verdicts to overall.

      any FAIL → FAIL
      else any WARN → WARN
      else all PASS (with optional WAIVED/NOT_RUN) → PASS_WITH_WAIVERS
      all PASS (no WAIVED, no NOT_RUN) → PASS
    """
    verdicts = [t.verdict for t in tiers]
    if "FAIL" in verdicts:
        return "FAIL"
    if "WARN" in verdicts:
        return "WARN"
    has_waivers_or_skipped = ("WAIVED" in verdicts
                                or "NOT_RUN" in verdicts)
    if has_waivers_or_skipped:
        return "PASS_WITH_WAIVERS"
    return "PASS"


def run_ladder(project_dir: Path) -> LadderReport:
    tiers = [check(project_dir) for check in TIER_CHECKS]
    return LadderReport(
        project_dir=str(project_dir),
        tiers=tiers,
        overall_verdict=aggregate_verdict(tiers),
    )


def report_to_markdown(rep: LadderReport) -> str:
    out: List[str] = []
    out.append(f"# Sign-off ladder — {rep.project_dir}")
    out.append("")
    out.append(f"_Emitted by `signoff_ladder_run.py` (v0.1.51). "
               f"Doctrine: 9-sub-tier ladder discovered by spm pilot, "
               f"now a single deterministic runner._")
    out.append("")
    out.append(f"**Overall verdict: {rep.overall_verdict}**")
    out.append("")
    out.append("| Tier | Check | Verdict | Notes |")
    out.append("|---|---|---|---|")
    for t in rep.tiers:
        notes = t.notes or json.dumps(t.details)[:80]
        out.append(f"| {t.tier_id} | {t.name} | {t.verdict} | {notes} |")
    out.append("")
    return "\n".join(out)


def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Chip-level 5-tier sign-off ladder runner.")
    p.add_argument("project_dir", type=Path)
    p.add_argument("--out-md", type=Path)
    p.add_argument("--out-json", type=Path)
    p.add_argument("--strict", action="store_true",
                   help="Exit non-zero on FAIL or WARN")
    args = p.parse_args()
    rep = run_ladder(args.project_dir)
    md = report_to_markdown(rep)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.out_json:
        args.out_json.write_text(json.dumps(rep.as_dict(), indent=2),
                                  encoding="utf-8")
    if args.strict and rep.overall_verdict in ("FAIL", "WARN"):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
