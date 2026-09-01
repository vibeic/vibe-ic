#!/usr/bin/env python3
"""
pnr_via_stack_completeness_check.py — chip-AGNOSTIC audit of how
many routing layers the PDK actually supports vs how many the PnR
flow ended up using.

ROLE: producer/classifier

Issue #1980 moved this program out of the gate denominator because it has no
reachable refusal predicate. Its structured output remains a Step-31 program
output and must not be flattened into an advisory gate PASS.
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
* SKIP         — PDK has fewer than 2 routing layers OR no uniquely
                 resolvable technology LEF found.
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
from _staged_pdk_tech_lef import (  # noqa: E402
    TechLefResolutionError,
    discover_staged_tech_lefs,
    select_staged_tech_lef,
)
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


def _run_selected_tech_lef(project: Path) -> Tuple[Optional[str], Optional[str]]:
    """Read the technology LEF the PnR producer says it actually loaded.

    The via-patch report is emitted from the resolved ``PdkConfig.tech_lef``;
    it is therefore selection evidence from the producer being audited, not a
    second filename heuristic.  Its container path is mapped to the staged copy
    by the shared resolver, which accepts basename matching only when unique.
    """
    report = project / "reports" / "pdk_via_patch_min_width.json"
    if not report.is_file():
        return None, None
    try:
        selected = (json.loads(report.read_text()) or {}).get("tech_lef")
    except Exception:
        return None, None
    if not isinstance(selected, str) or not selected.strip():
        return None, None
    return (selected.strip(),
            "reports/pdk_via_patch_min_width.json#tech_lef")


def _routing_layer_count(path: Path) -> int:
    text = path.read_text(errors="ignore")
    prefix = _detect_metal_prefix_from_lef(text)
    return _count_routing_layers_in_lef(text, prefix)


def _top_routing_layer(path: Path) -> Optional[str]:
    text = path.read_text(errors="ignore")
    prefix = _detect_metal_prefix_from_lef(text)
    count = _count_routing_layers_in_lef(text, prefix)
    return f"{prefix}{count}" if count else None


def _resolve_tech_lef(project: Path) -> Tuple[
        Optional[Path], Optional[str], List[Path], Optional[str]]:
    """Return selected path, authority, candidates, and refusal detail."""
    pdk_dir = project / "input" / "pdk"
    candidates = list(discover_staged_tech_lefs(pdk_dir))
    selected, authority = _run_selected_tech_lef(project)
    try:
        resolution = select_staged_tech_lef(
            pdk_dir,
            candidates,
            selected_path=selected,
            selected_path_authority=authority,
            top_routing_layer=_top_routing_layer,
            routing_layer_count=_routing_layer_count,
        )
    except TechLefResolutionError as exc:
        return None, None, candidates, str(exc)
    if resolution is None:
        return None, None, candidates, None
    return (resolution.path, resolution.authority,
            list(resolution.candidates), None)


def _find_tech_lef(project: Path) -> Optional[Path]:
    """Compatibility wrapper around the shared declared/staged resolver."""
    return _resolve_tech_lef(project)[0]


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
        "tech_lef_selection_authority": None,
        "tech_lef_candidates": [],
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

    tech_lef, selection_authority, candidates, refusal = \
        _resolve_tech_lef(project)
    summary["tech_lef_candidates"] = [str(path) for path in candidates]
    if refusal:
        findings.append(ViaStackFinding(
            rule="TECH_LEF_SELECTION_REFUSED",
            detail=("Phase 3 has run and staged technology LEFs exist, but "
                    f"the shared resolver refused an arbitrary choice: "
                    f"{refusal}")))
        return "SKIP", findings, summary
    if not tech_lef:
        findings.append(ViaStackFinding(
            rule="NO_TECH_LEF",
            detail=("Phase 3 has run but no technology LEF (.lef or .tlef) "
                    "was resolved from input/pdk/. Cannot audit via-stack "
                    "completeness without that authority.")))
        return "SKIP", findings, summary
    summary["tech_lef"] = str(tech_lef)
    summary["tech_lef_selection_authority"] = selection_authority
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
