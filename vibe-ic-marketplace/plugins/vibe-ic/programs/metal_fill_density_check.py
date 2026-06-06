#!/usr/bin/env python3
"""Verify metal fill was inserted and density is within bounds."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple
import _path_layout as _pl


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


_MIN_DENSITY = 20.0
_MAX_DENSITY = 80.0


def audit(project_dir: Path) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    pnr = _pl.pnr_dir(project_dir)
    filled_def = pnr / "filled.def"
    fill_done = pnr / "metal_fill.done"
    routed_def = pnr / "routed.def"
    density_json = _pl.report_path(project_dir, "density.json")
    density_rpt = _pl.report_path(project_dir, "density.rpt")
    # #445: the phase3 runner emits reports/density.{json,rpt} (repo
    # root of reports/), while report_path routes to reports/phase3/ —
    # accept both so the runner's own data is actually READ.
    if not density_json.exists() and (
            project_dir / "reports" / "density.json").exists():
        density_json = project_dir / "reports" / "density.json"
    if not density_rpt.exists() and (
            project_dir / "reports" / "density.rpt").exists():
        density_rpt = project_dir / "reports" / "density.rpt"

    stats = {"fill_marker": False, "filled_larger": None,
             "density_checked": False, "layers_ok": 0, "layers_bad": 0}

    if not filled_def.exists() and not fill_done.exists():
        findings.append(Finding("ERROR", "NO_FILL",
                                "Neither pnr/filled.def nor pnr/metal_fill.done found"))
        return findings, stats
    stats["fill_marker"] = True

    if filled_def.exists() and routed_def.exists():
        filled_sz = filled_def.stat().st_size
        routed_sz = routed_def.stat().st_size
        stats["filled_larger"] = filled_sz > routed_sz
        if filled_sz <= routed_sz:
            findings.append(Finding("WARNING", "FILL_NOT_LARGER",
                                    f"filled.def ({filled_sz}B) is not larger than "
                                    f"routed.def ({routed_sz}B) — fill may be missing"))

    filler_n = None
    row_util = None
    if density_json.exists():
        stats["density_checked"] = True
        try:
            data = json.loads(density_json.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(Finding("ERROR", "BAD_JSON",
                                    f"Cannot parse density.json: {exc}"))
            return findings, stats

        if isinstance(data, dict):
            if isinstance(data.get("filler_instances"), (int, float)):
                filler_n = int(data["filler_instances"])
            if isinstance(data.get("row_utilization_pct"), (int, float)):
                row_util = float(data["row_utilization_pct"])

        layers = data.get("layers", data) if isinstance(data, dict) else data
        if isinstance(layers, dict):
            # legacy dict-of-layers fallback — #445: exclude the runner's
            # metadata/count fields so filler_instances etc. are never
            # misread as a "layer density".
            _META_KEYS = {"filler_instances", "row_utilization_pct",
                          "utilization_below_report_precision"}
            layers = [{"name": k, "density_pct": v}
                      for k, v in layers.items()
                      if k not in _META_KEYS and isinstance(v, (int, float))]
        if isinstance(layers, list):
            for layer in layers:
                if not isinstance(layer, dict):
                    continue
                name = layer.get("name", layer.get("layer", "?"))
                density = layer.get("density_pct", layer.get("density", None))
                if density is None:
                    continue
                if _MIN_DENSITY <= density <= _MAX_DENSITY:
                    stats["layers_ok"] += 1
                else:
                    stats["layers_bad"] += 1
                    findings.append(Finding(
                        "ERROR", "DENSITY_OOB",
                        f"Layer {name} density {density:.1f}% outside "
                        f"[{_MIN_DENSITY}%, {_MAX_DENSITY}%]"))
    elif density_rpt.exists():
        stats["density_checked"] = True
        if density_rpt.stat().st_size == 0:
            findings.append(Finding("WARNING", "EMPTY_RPT",
                                    "density.rpt is empty"))

    # ORGANIC-20260606 #445 — SUBSTANCE: a fill step that placed 0
    # fillers AND grew nothing AND has no in-window per-layer density
    # achieved NOTHING — the done-marker alone must not PASS. The one
    # legitimate 0-filler shape is rows already (near-)full, which the
    # emitter substantiates via row_utilization_pct >= 95.
    per_layer_ok = stats["layers_ok"] > 0 and stats["layers_bad"] == 0
    rows_already_full = row_util is not None and row_util >= 95.0
    placed_fillers = isinstance(filler_n, int) and filler_n > 0
    counted_zero = filler_n == 0          # the explicit no-op signal
    grew = stats["filled_larger"] is True
    no_baseline = stats["filled_larger"] is None  # routed.def absent
    stats["filler_instances"] = filler_n
    stats["rows_already_full"] = rows_already_full
    if placed_fillers and stats["filled_larger"] is False:
        # contradiction: claims fillers but the DEF didn't grow
        findings.append(Finding(
            "ERROR", "FILL_CLAIM_CONTRADICTION",
            f"density.json claims {filler_n} fillers placed but "
            f"filled.def is not larger than routed.def (#445)"))
    else:
        substance = (per_layer_ok or rows_already_full
                     or (not counted_zero
                         and (grew or (no_baseline and placed_fillers))))
        if not substance:
            findings.append(Finding(
                "ERROR", "FILL_NO_SUBSTANCE",
                "metal fill substantiates nothing: 0 fillers placed (or "
                "no growth evidence), filled.def not larger than "
                "routed.def, no in-window per-layer density, and rows "
                "not already full — presence of filled.def/"
                "metal_fill.done alone is not fill (#445)"))

    return findings, stats


def build_report(findings: List[Finding], stats: dict,
                 project_dir: str) -> dict:
    return {
        "program": "metal_fill_density_check",
        "version": "1.0.0",
        "project_dir": project_dir,
        "summary": {
            "fill_marker": stats["fill_marker"],
            "density_checked": stats["density_checked"],
            "layers_ok": stats["layers_ok"],
            "layers_bad": stats["layers_bad"],
            "findings_count": len(findings),
            "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
            "pass": all(f.severity != "ERROR" for f in findings),
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description="Check metal fill and density")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        print(f"ERROR: not a directory: {project_dir}", file=sys.stderr)
        return 2

    findings, stats = audit(project_dir)
    report = build_report(findings, stats, str(project_dir))
    out = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    print(out)
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
