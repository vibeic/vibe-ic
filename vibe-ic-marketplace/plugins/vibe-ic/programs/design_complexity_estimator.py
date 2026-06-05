#!/usr/bin/env python3
"""
design_complexity_estimator.py -- Heuristic design-complexity score and
flow-effort recommendation.

Estimates a 0-100 complexity score from cheap, deterministic features (RTL
line count, #modules, #clocks, max bit width, SRAM/macro instances, target
frequency) and maps it to a TIER, then recommends per-tier flow effort:
prefer catalog-glue vs from-scratch RTL, synthesis effort, whether to run the
FPGA early-prototype, and STA corner depth.

This is ADVISORY only -- never a hard gate, so it cannot cause a false
failure. It exists to route effort, not to block a flow.

The complexity-estimator-drives-effort idea is borrowed from ChipAgentix's
ComplexityEstimator; the OSS<->commercial tool-tier arbitration is
deliberately dropped because Vibe-IC is OSS-only. Implementation is
independent and chip-AGNOSTIC.

Features may be supplied directly as JSON or derived from a project_dir by
scanning RTL with gate_utils.

Usage:
    python3 design_complexity_estimator.py <project_dir>
    python3 design_complexity_estimator.py --features feats.json
    python3 design_complexity_estimator.py <project_dir> --json out.json

Exit codes:
    0 = always (advisory tool; the score/tier is in the JSON output)

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List

import gate_utils


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
@dataclass
class ComplexityFeatures:
    loc: int = 0
    num_modules: int = 0
    num_clocks: int = 1
    max_bit_width: int = 1
    sram_count: int = 0
    macro_count: int = 0
    target_freq_mhz: float = 0.0


# Each feature contributes a bounded number of points; contributions are
# log-scaled so a 10x bigger design does not produce a 10x bigger score.
# Weights sum to 100. Tuned to be monotonic and explainable, not exact.
_WEIGHTS = {
    "loc": 28.0,           # saturates around ~50k LoC
    "num_modules": 16.0,   # saturates around ~120 modules
    "num_clocks": 16.0,    # multi-clock designs are disproportionately harder
    "max_bit_width": 8.0,  # saturates around 256-bit
    "sram_count": 12.0,    # memories drive PnR/macro complexity
    "macro_count": 10.0,   # hardmacros drive integration complexity
    "target_freq_mhz": 10.0,  # high freq -> timing-closure effort
}

# Feature value that maps to ~63% of that feature's max contribution.
_SCALE = {
    "loc": 8000.0,
    "num_modules": 25.0,
    "num_clocks": 3.0,
    "max_bit_width": 64.0,
    "sram_count": 4.0,
    "macro_count": 4.0,
    "target_freq_mhz": 400.0,
}


def _contribution(name: str, value: float) -> float:
    """Saturating contribution: weight * (1 - exp(-value/scale))."""
    if value <= 0:
        return 0.0
    scale = _SCALE[name]
    return _WEIGHTS[name] * (1.0 - math.exp(-value / scale))


_TIERS = [
    (15.0, "TRIVIAL"),
    (35.0, "SMALL"),
    (60.0, "MEDIUM"),
    (82.0, "LARGE"),
    (float("inf"), "COMPLEX"),
]


def _tier_for(score: float) -> str:
    for threshold, name in _TIERS:
        if score < threshold:
            return name
    return "COMPLEX"


_RECOMMENDATIONS = {
    "TRIVIAL": {
        "prefer_catalog_glue": False,
        "synth_effort": "low",
        "run_fpga_early_prototype": False,
        "sta_corners": "typical",
        "advice": "Single-shot from-scratch RTL; light verification is enough.",
    },
    "SMALL": {
        "prefer_catalog_glue": False,
        "synth_effort": "low",
        "run_fpga_early_prototype": False,
        "sta_corners": "typical",
        "advice": "From-scratch RTL; run lint + sim, skip FPGA early prototype.",
    },
    "MEDIUM": {
        "prefer_catalog_glue": False,
        "synth_effort": "medium",
        "run_fpga_early_prototype": True,
        "sta_corners": "multi",
        "advice": "From-scratch RTL with full Phase-2 verification; "
                  "FPGA early prototype recommended.",
    },
    "LARGE": {
        "prefer_catalog_glue": True,
        "synth_effort": "high",
        "run_fpga_early_prototype": True,
        "sta_corners": "multi",
        "advice": "Prefer catalog-glue (pull validated open-source IP) over "
                  "from-scratch; multi-corner STA; FPGA early prototype.",
    },
    "COMPLEX": {
        "prefer_catalog_glue": True,
        "synth_effort": "high",
        "run_fpga_early_prototype": True,
        "sta_corners": "multi+aging",
        "advice": "SoC-class: catalog-glue integration, hierarchical PnR, "
                  "multi-corner+aging STA, FPGA early prototype mandatory.",
    },
}


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class ComplexityResult:
    score: float
    tier: str
    features: Dict = field(default_factory=dict)
    contributions: Dict = field(default_factory=dict)
    recommendations: Dict = field(default_factory=dict)


def estimate(features: ComplexityFeatures) -> ComplexityResult:
    contribs = {
        "loc": _contribution("loc", features.loc),
        "num_modules": _contribution("num_modules", features.num_modules),
        # clocks beyond the first are what add difficulty
        "num_clocks": _contribution("num_clocks", max(0, features.num_clocks - 1)),
        # width beyond a single bit is what adds difficulty (1-bit == baseline)
        "max_bit_width": _contribution("max_bit_width", max(0, features.max_bit_width - 1)),
        "sram_count": _contribution("sram_count", features.sram_count),
        "macro_count": _contribution("macro_count", features.macro_count),
        "target_freq_mhz": _contribution("target_freq_mhz", features.target_freq_mhz),
    }
    score = round(min(100.0, sum(contribs.values())), 2)
    tier = _tier_for(score)
    return ComplexityResult(
        score=score,
        tier=tier,
        features=asdict(features),
        contributions={k: round(v, 2) for k, v in contribs.items()},
        recommendations=dict(_RECOMMENDATIONS[tier]),
    )


# ---------------------------------------------------------------------------
# Feature extraction from a project directory
# ---------------------------------------------------------------------------
_POSEDGE_RE = re.compile(r"\b(?:pos|neg)edge\s+([A-Za-z_]\w*)")
_WIDTH_RE = re.compile(r"\[\s*(\d+)\s*:\s*0\s*\]")
_SRAM_RE = re.compile(r"\b\w*(?:sram|ram|rom|mem)\w*\b", re.IGNORECASE)
_MACRO_HINT_RE = re.compile(r"\b\w*(?:macro|pll|dll|phy|io_pad|bandgap)\w*\b", re.IGNORECASE)


def features_from_project(project_dir: Path) -> ComplexityFeatures:
    # ORGANIC-20260606 #436 — scope to the DESIGN RTL. The project-wide
    # rglob counted analog behavioral stubs / FPGA harness templates as
    # design source, so a zero-RTL (pure-analog) project reported nonzero
    # loc/module/SRAM counts in its complexity advisory. Prefer the
    # canonical rtl dir; fall back to the legacy sweep only when no
    # canonical layout exists.
    rtl_files: list = []
    try:
        import _path_layout as _pl
        canon = _pl.rtl_dir(Path(project_dir))
        if canon.is_dir():
            rtl_files = sorted(canon.glob("*.v")) + sorted(canon.glob("*.sv"))
    except Exception:
        pass
    if not rtl_files:
        canon_probe = Path(project_dir) / "phase2" / "stage1" / "rtl"
        if canon_probe.is_dir():
            rtl_files = (sorted(canon_probe.glob("*.v"))
                         + sorted(canon_probe.glob("*.sv")))
        else:
            rtl_files = gate_utils.find_rtl_files(project_dir)
    loc = 0
    clocks: set = set()
    max_width = 1
    sram = 0
    macro = 0
    modules = 0

    for f in rtl_files:
        text = gate_utils.read_text(f)
        loc += text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        for m in _POSEDGE_RE.finditer(text):
            name = m.group(1).lower()
            # heuristic: clock-like edge signals (clk / clock), not resets
            if "clk" in name or "clock" in name:
                clocks.add(name)
        for w in _WIDTH_RE.finditer(text):
            max_width = max(max_width, int(w.group(1)) + 1)
        modules += len(gate_utils.find_modules(text))
        sram += len(set(_SRAM_RE.findall(text)))
        macro += len(set(_MACRO_HINT_RE.findall(text)))

    return ComplexityFeatures(
        loc=loc,
        num_modules=modules,
        num_clocks=max(1, len(clocks)),
        max_bit_width=max_width,
        sram_count=sram,
        macro_count=macro,
        target_freq_mhz=0.0,   # not derivable from RTL; supply via --features
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Heuristic design-complexity -> flow-effort recommender.")
    parser.add_argument("project_dir", nargs="?", default=None,
                        help="Project directory to scan for RTL")
    parser.add_argument("--features", default=None,
                        help="JSON file of ComplexityFeatures (overrides scan)")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    if args.features:
        spec = json.loads(Path(args.features).read_text())
        feats = ComplexityFeatures(**{
            k: spec[k] for k in spec
            if k in ComplexityFeatures.__dataclass_fields__})
    elif args.project_dir:
        feats = features_from_project(Path(args.project_dir))
    else:
        parser.error("provide a project_dir or --features")

    result = estimate(feats)
    report_json = json.dumps(asdict(result), indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)
    print(report_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
