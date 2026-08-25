#!/usr/bin/env python3
"""
pnr_via_stack_completeness_check.py — chip-AGNOSTIC audit of how
many routing layers the PDK actually supports vs how many the PnR
flow ended up using.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Background
----------
The Phase 3 runner observed on v10648:

    via_audit: single-cut via missing above M5; routing restricted to M1-M5

This message records that the PDK declared more metal layers (e.g. M6+)
than the open-source PnR flow could safely use because the upper cut
layers ship only multi-cut / directional vias. The runner already
applies the workaround (via `_pdk_via_analyzer` + a tcl
`set_routing_layers` constraint) and PnR succeeds — but no gate
records the resulting design-quality hint:

  * PDK declares N metal layers; PnR used M of them (M < N) →
    routing density is constrained, can affect timing on dense designs.
  * PDK declares N metal layers; PnR used M = N → fully utilised PDK.
  * PDK declares N metal layers but no PnR run yet → SKIP.

This gate is **non-blocking** (WARN, not FAIL) — restricted routing is
a PDK-completeness gap, not a design defect. The audit emits a
structured JSON report at `reports/phase3/pnr_via_stack_completeness.json`
that a tape-out reviewer can use to decide whether the chip actually
needs the upper layers.

Backlog reference
-----------------
v1.6.53 enhancement plan #6 (PnR via-stack audit). Pairs with the
runtime workaround in `phase3_one_shot_runner.step_pnr` v1.6.38.

Verdict tiers
-------------
* PASS         — PnR used every routing layer the PDK declared.
* WARN         — PDK declared more layers than PnR used (cut-layer
                 single-cut via gap or explicit
                 `set_routing_layers` constraint).
* SKIP         — PDK has fewer than 2 routing layers OR no tech.lef
                 found.
* VACUOUS_PASS — PnR has not run (no orchestrator phase3 report).

Usage
-----
    python3 pnr_via_stack_completeness_check.py <project_dir>
                                                 [--json <out>]
                                                 [--verbose]

Exit codes
    0  PASS / WARN / SKIP / VACUOUS_PASS
    2  argument or I/O error

The gate exit-code is intentionally non-zero only on argument /
I/O errors. WARN is informational. Wire only as a `*_check` audit;
do NOT add to `_STRUCTURAL_RTL_GATES` — this is design-quality
guidance, not a structural failure.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Lazy import of the LEF analyzer so this module is callable without
# the analyzer being available (e.g. mirror without programs/).
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from _pdk_via_analyzer import analyze_lef as _analyze_lef
except Exception:  # pragma: no cover — defensive: never block on import
    _analyze_lef = None  # type: ignore[assignment]


@dataclass
class ViaStackFinding:
    rule: str  # PDK_LAYERS_UNUSED | CUT_LAYER_NO_SINGLE_CUT | NO_TECH_LEF
    detail: str
    pdk_metal_layers_total: Optional[int] = None
    pnr_routing_layers_used: Optional[int] = None
    cut_layers_missing_single_cut: List[str] = None  # type: ignore[assignment]


def _find_tech_lef(project: Path) -> Optional[Path]:
    """Heuristic: search the PDK tree for any LEF whose filename
    contains 'tech' (case-insensitive). Real-world PDKs ship
    `<vendor>_<N>lm_tech_<rev>.lef` style names, not literal
    `tech.lef`. Prefers the highest layer-count variant when
    multiple `_<N>lm_tech_*.lef` siblings exist (the PDK's full
    metal-stack capability)."""
    pdk_dir = project / "input" / "pdk"
    if not pdk_dir.is_dir():
        return None
    candidates: List[Path] = []
    for f in pdk_dir.rglob("*.lef"):
        if "tech" in f.name.lower():
            candidates.append(f)
    if not candidates:
        return None

    # Score each candidate: higher layer count wins. Pattern
    # `_<N>lm_` (2/3/4/5/6/7/8 routing layers in the variant) is
    # the convention many vendor PDKs use.
    def _layer_count(p: Path) -> int:
        m = re.search(r"_(\d+)lm_", p.name, re.IGNORECASE)
        return int(m.group(1)) if m else 0

    candidates.sort(key=lambda p: (_layer_count(p), str(p)))
    return candidates[-1]


def _count_routing_layers_in_lef(text: str,
                                 metal_prefix: str = "M") -> int:
    """Count `LAYER <metal_prefix><N>` blocks with `TYPE ROUTING`.
    Falls back to scanning all routing layers if the prefix has no
    matches."""
    pat = (r"^\s*LAYER\s+" + re.escape(metal_prefix) + r"(\d+)\s*\n"
           r"[^L]*?TYPE\s+ROUTING")
    matches = re.findall(pat, text, re.IGNORECASE | re.MULTILINE)
    if matches:
        return len(matches)
    # Fallback: any routing layer (any prefix)
    fallback = re.findall(
        r"^\s*LAYER\s+\S+\s*\n[^L]*?TYPE\s+ROUTING\s*;",
        text, re.IGNORECASE | re.MULTILINE)
    return len(fallback)


def _detect_metal_prefix_from_lef(text: str) -> str:
    """Detect `M`, `MET`, or `MX` prefix from the first routing layer
    declaration. Default to `M`."""
    m = re.search(
        r"^\s*LAYER\s+([A-Za-z]+)\d+\s*\n[^L]*?TYPE\s+ROUTING",
        text, re.IGNORECASE | re.MULTILINE)
    if m:
        return m.group(1)
    return "M"


def _parse_pnr_routing_used(orchestrator_json: Path) -> Tuple[
        Optional[int], Optional[str]]:
    """From `reports/orchestrator/phase3_one_shot.json`, find the
    `pnr` step's `routing_audit_note` (in step.detail) and parse out
    the upper bound. Returns (upper_layer_index, raw_note)."""
    if not orchestrator_json.is_file():
        return None, None
    try:
        d = json.loads(orchestrator_json.read_text())
    except Exception:
        return None, None
    steps = d.get("steps") or []
    for s in steps:
        if s.get("name") != "pnr":
            continue
        detail = s.get("detail", "")
        m = re.search(r"routing restricted to (M|MET|MX)?(\d+)-(M|MET|MX)?(\d+)",
                      detail, re.IGNORECASE)
        if m:
            upper = int(m.group(4))
            return upper, detail
        m2 = re.search(r"single-cut via missing above ([A-Za-z]+)(\d+)",
                       detail, re.IGNORECASE)
        if m2:
            upper = int(m2.group(2))
            return upper, detail
    return None, None


def audit(project: Path) -> Tuple[str, List[ViaStackFinding], Dict[str, Any]]:
    """Audit `project` for PnR via-stack completeness.

    Returns (verdict, findings, summary)."""
    summary: Dict[str, Any] = {
        "tech_lef": None,
        "pdk_metal_layers_total": None,
        "pnr_routing_layers_used": None,
        "cut_layers_missing_single_cut": [],
        "metal_prefix": "M",
    }
    findings: List[ViaStackFinding] = []

    orch_json = (project / "reports" / "orchestrator"
                 / "phase3_one_shot.json")
    if not orch_json.is_file():
        return "VACUOUS_PASS", [], summary

    tech_lef = _find_tech_lef(project)
    if not tech_lef:
        findings.append(ViaStackFinding(
            rule="NO_TECH_LEF",
            detail=("Phase 3 has run but no tech.lef found under "
                    "input/pdk/. Cannot audit via-stack completeness "
                    "without the LEF.")))
        return "SKIP", findings, summary
    summary["tech_lef"] = str(tech_lef)
    text = tech_lef.read_text(errors="ignore")
    metal_prefix = _detect_metal_prefix_from_lef(text)
    summary["metal_prefix"] = metal_prefix
    n_layers = _count_routing_layers_in_lef(text, metal_prefix)
    summary["pdk_metal_layers_total"] = n_layers
    if n_layers < 2:
        return "SKIP", findings, summary

    used_upper, raw_note = _parse_pnr_routing_used(orch_json)
    if used_upper is None:
        used_upper = n_layers
    summary["pnr_routing_layers_used"] = used_upper
    summary["pnr_audit_note"] = raw_note

    # Cut-layer single-cut analysis (chip-AGNOSTIC).
    if _analyze_lef is not None:
        try:
            via_analysis = _analyze_lef(text)
            if isinstance(via_analysis, dict):
                summary["via_analysis_verdict"] = via_analysis.get("verdict")
                missing = via_analysis.get("single_cut_missing") or []
                if isinstance(missing, list):
                    summary["cut_layers_missing_single_cut"] = list(missing)
        except Exception:
            pass

    # WARN when PnR used fewer routing layers than the PDK declared.
    if used_upper < n_layers:
        findings.append(ViaStackFinding(
            rule="PDK_LAYERS_UNUSED",
            detail=(f"PDK declares {n_layers} routing layer(s) "
                    f"({metal_prefix}1..{metal_prefix}{n_layers}) but "
                    f"PnR routed only {metal_prefix}1..{metal_prefix}"
                    f"{used_upper}. Constraint applied: {raw_note!r}. "
                    f"Reviewer: confirm whether the upper "
                    f"{n_layers - used_upper} layer(s) are actually "
                    f"needed for this design's density / timing — if "
                    f"yes, request a PDK update with single-cut vias "
                    f"on the missing cut layers."),
            pdk_metal_layers_total=n_layers,
            pnr_routing_layers_used=used_upper,
            cut_layers_missing_single_cut=summary[
                "cut_layers_missing_single_cut"]))

    if not findings:
        return "PASS", findings, summary
    return "WARN", findings, summary


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit PnR via-stack completeness vs PDK metal "
                    "layer declaration. Non-blocking (WARN-only).")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, findings, summary = audit(project)
    report = {
        "gate": "pnr_via_stack_completeness_check",
        "verdict": verdict,
        "project": str(project),
        "summary": summary,
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings],
    }

    # Auto-emit canonical report path even when --json absent so
    # downstream consumers always know where to find the audit.
    canonical_out = project / "reports" / "phase3" / \
        "pnr_via_stack_completeness.json"
    canonical_out.parent.mkdir(parents=True, exist_ok=True)
    canonical_out.write_text(json.dumps(report, indent=2) + "\n")
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    print(f"{verdict}: pnr_via_stack_completeness_check — "
          f"PDK={summary['pdk_metal_layers_total']} layer(s); "
          f"PnR used={summary['pnr_routing_layers_used']}; "
          f"missing single-cut on={summary['cut_layers_missing_single_cut'] or 'none'}")
    if args.verbose or verdict == "WARN":
        for f in findings:
            print(f"  [{f.rule}] {f.detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
