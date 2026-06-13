#!/usr/bin/env python3
"""dfm_screen_check.py — Step 35 DFM screen (v2.3).

Design-for-Manufacturability, scoped HONESTLY for an open-source
130-180nm flow. Flow v2.3.1 (external review P0-1): the THREE density
touchpoints have DISTINCT natures and this screen no longer re-gates
what Step 34 owns —
  Step 31 = RULE compliance (the sign-off DRC deck's min-density
            rules — legal/illegal),
  Step 34 = EXECUTION verification (metal_fill_density_check gates
            that the fill actually achieved the window),
  Step 35 = OPTIMIZATION advisory (THIS screen: "could be filled
            better / via redundancy could improve yield" — findings,
            never a duplicate FAIL of Step 34).

  1. CMP density — CROSS-REFERENCE only: reads Step 34's gate result
     (reports/phase2/gates/metal_fill_density.json) and surfaces its
     verdict as an INFO/REVIEW finding; the gate itself lives at 34.
  2. Redundant-via ratio — counted deterministically from the routed
     DEF's VIAS section (ROWCOL r c → multi-cut when r*c > 1) and the
     per-via usage in NETS/SPECIALNETS. A high single-cut fraction on
     signal nets is a YIELD advisory (WARN, never a fabricated FAIL —
     OpenROAD has no via-doubling pass to repair it with).
  3. Litho / min-width margins — cross-referenced to the Step-31
     sign-off DRC deck (not re-executed here; ownership disclosed).
  4. FOUNDRY_SIDE items — OPC / RET / SRAF / PSM are mask-synthesis
     work the FOUNDRY performs on the delivered GDS. They are listed
     by name at their correct flow position (status FOUNDRY_SIDE),
     never pretended as designer-executed. At <=28nm these become
     designer-collaboration items (noted).

Always writes the canonical step artifact
`reports/phase3/dfm_screen.json` (in addition to --json).

flow v2.3.1: ADVANCED-NODE trigger — process node derived from the PDK's
own liberty filenames (the foundry_handoff_pack_gen heuristic); at
<= 28 nm the FOUNDRY_SIDE items escalate to DESIGNER_COLLAB_REVIEW
findings (dormant at this flow's 130-180 nm PDKs, mechanism present).

Exit codes: 0 PASS / PASS_WITH_ADVISORIES (advisory screen — never a
duplicate density FAIL; Step 34 owns that gate), 2 vacuous (no
routed.def / no density artifacts yet).
chip-AGNOSTIC: DEF structure + window numbers only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402

# advisory threshold: fraction of signal-net via USES that are
# single-cut. Industry DFM aims for dual-via where room allows; at
# 130-180nm this is yield-advisory, not sign-off.
_SINGLE_CUT_ADVISORY = 0.90

_FOUNDRY_SIDE_ITEMS = [
    {"item": "OPC (optical proximity correction)",
     "status": "FOUNDRY_SIDE",
     "note": "mask synthesis on the delivered GDS — foundry mask shop"},
    {"item": "RET / SRAF (sub-resolution assist features)",
     "status": "FOUNDRY_SIDE",
     "note": "resolution enhancement — foundry mask shop"},
    {"item": "PSM (phase-shift mask)",
     "status": "FOUNDRY_SIDE",
     "note": "mask technology selection — foundry"},
]
_ADVANCED_NODE_NOTE = (
    "at <=28nm the FOUNDRY_SIDE items become designer-collaboration "
    "items (litho-friendly design rules, OPC-aware routing) — out of "
    "scope for this 130-180nm open-source flow")


def _via_cut_counts(def_text: str):
    """{via_name: cuts} from the DEF VIAS section (ROWCOL r c → r*c;
    no ROWCOL → 1 cut)."""
    cuts = {}
    m = re.search(r"^VIAS\s+\d+\s*;(.*?)^END VIAS", def_text,
                  re.DOTALL | re.MULTILINE)
    if not m:
        return cuts
    for block in re.split(r"^\s*-\s+", m.group(1), flags=re.MULTILINE):
        name_m = re.match(r"(\S+)", block)
        if not name_m:
            continue
        rc = re.search(r"\+\s*ROWCOL\s+(\d+)\s+(\d+)", block)
        cuts[name_m.group(1)] = (int(rc.group(1)) * int(rc.group(2))
                                 if rc else 1)
    return cuts


def _via_usage(def_text: str, via_names):
    """{via_name: uses} counted in the NETS (signal) section."""
    m = re.search(r"^NETS\s+\d+\s*;(.*?)^END NETS", def_text,
                  re.DOTALL | re.MULTILINE)
    if not m:
        return {}
    body = m.group(1)
    return {v: len(re.findall(rf"(?<![\w]){re.escape(v)}(?![\w])", body))
            for v in via_names}


def audit(project: Path) -> dict:
    findings = []
    routed = _pl.pnr_dir(project) / "routed.def"
    density_json = project / "reports" / "density.json"
    if not routed.is_file() and not density_json.is_file() \
            and not _pl.report_path(project, "density.json").is_file():
        return {"verdict": "SKIP", "rc": 2,
                "reason": ("no routed.def and no density artifacts yet — "
                           "run routing + metal fill first")}

    # 1) CMP density — CROSS-REFERENCE Step 34's gate (flow v2.3.1: no
    # duplicate gating; three-natures split 31/34/35).
    gate_json = project / "reports" / "phase2" / "gates" / \
        "metal_fill_density.json"
    density_ref = None
    if gate_json.is_file():
        try:
            g = json.loads(gate_json.read_text(errors="replace"))
            density_ref = {
                "step34_pass": bool(g.get("summary", {}).get("pass")),
                "errors": g.get("summary", {}).get("errors_count"),
                "source": str(gate_json.relative_to(project)),
            }
        except (OSError, ValueError):
            density_ref = {"unparseable": True,
                           "source": str(gate_json.relative_to(project))}
    if density_ref is None:
        findings.append({
            "severity": "INFO", "category": "DENSITY_REF",
            "message": ("Step-34 metal-fill density gate result not "
                        "present yet — density is GATED at Step 34, "
                        "referenced here (run metal_fill_density_check)")})
    elif density_ref.get("step34_pass"):
        findings.append({
            "severity": "INFO", "category": "DENSITY_REF",
            "message": "Step-34 density gate: PASS (cross-reference)"})
    else:
        findings.append({
            "severity": "WARNING", "category": "DENSITY_REF",
            "message": ("Step-34 density gate did not PASS — resolve at "
                        "Step 34 (this screen is optimization advisory, "
                        "not a duplicate gate)")})

    # 2) redundant-via ratio ------------------------------------------------
    via_summary = None
    if routed.is_file():
        txt = routed.read_text(errors="replace")
        cuts = _via_cut_counts(txt)
        if cuts:
            uses = _via_usage(txt, cuts.keys())
            total = sum(uses.values())
            single = sum(n for v, n in uses.items() if cuts.get(v, 1) <= 1)
            frac = (single / total) if total else None
            via_summary = {
                "via_defs": len(cuts),
                "multi_cut_defs": sum(1 for c in cuts.values() if c > 1),
                "signal_via_uses": total,
                "single_cut_uses": single,
                "single_cut_fraction": (round(frac, 4)
                                        if frac is not None else None),
                "advisory_threshold": _SINGLE_CUT_ADVISORY,
            }
            if frac is not None and frac > _SINGLE_CUT_ADVISORY:
                findings.append({
                    "severity": "WARNING",
                    "category": "VIA_REDUNDANCY_LOW",
                    "message": (f"{frac:.1%} of signal-net via uses are "
                                f"single-cut (> {_SINGLE_CUT_ADVISORY:.0%} "
                                f"advisory) — dual-via insertion improves "
                                f"yield; OpenROAD has no via-doubling "
                                f"repair pass (advisory only)")})
            elif frac is not None:
                findings.append({
                    "severity": "INFO", "category": "VIA_REDUNDANCY_OK",
                    "message": (f"single-cut via fraction {frac:.1%} "
                                f"(<= {_SINGLE_CUT_ADVISORY:.0%} advisory)")})
        else:
            findings.append({
                "severity": "INFO", "category": "VIA_DEFS_NOT_FOUND",
                "message": ("routed.def has no parseable VIAS section — "
                            "via-redundancy screen skipped (honest)")})

    # 3) litho / min-width ownership ----------------------------------------
    findings.append({
        "severity": "INFO", "category": "LITHO_MIN_WIDTH_OWNERSHIP",
        "message": ("litho-friendly / min-width-margin rules are enforced "
                    "by the Step-31 sign-off DRC deck (KLayout) — not "
                    "re-executed here")})

    # flow v2.3.1 — advanced-node trigger: derive the process node from the
    # PDK's own liberty filenames (input/pdk/liberty/*.lib); at <=28nm
    # the foundry-side items escalate to designer-collaboration REVIEW.
    process_nm = _derive_process_nm(project)
    advanced_node = process_nm is not None and process_nm <= 28
    foundry_side = [dict(i) for i in _FOUNDRY_SIDE_ITEMS]
    if advanced_node:
        for item in foundry_side:
            item["status"] = "DESIGNER_COLLAB_REVIEW"
        findings.append({
            "severity": "WARNING", "category": "ADVANCED_NODE_DFM",
            "message": (f"process node {process_nm} nm <= 28 nm — "
                        f"OPC/RET/litho-friendly items escalate to "
                        f"designer-collaboration review (flow v2.3.1)")})

    advisories = [f for f in findings if f["severity"] == "WARNING"]
    verdict = "PASS_WITH_ADVISORIES" if advisories else "PASS"
    return {
        "verdict": verdict,
        "rc": 0,   # advisory screen — Step 34 owns the density gate
        "density_ref": density_ref,
        "via_redundancy": via_summary,
        "process_nm": process_nm,
        "advanced_node": advanced_node,
        "foundry_side": foundry_side,
        "advanced_node_note": _ADVANCED_NODE_NOTE,
        "findings": findings,
    }


def _derive_process_nm(project: Path):
    """Process node from the PDK's own liberty filenames — the same
    PDK-namespaced heuristic foundry_handoff_pack_gen uses."""
    lib_dir = project / "input" / "pdk" / "liberty"
    if not lib_dir.is_dir():
        return None
    for tag in ("180", "130", "65", "45", "28", "22", "16", "12", "7", "5"):
        if any(tag in f.name for f in lib_dir.glob("*.lib")):
            return int(tag)
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1
    project = args.project_dir.resolve()
    rep = audit(project)
    rc = rep.pop("rc")
    rep = {"program": "dfm_screen_check", "version": "1.0.0", **rep}
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    # canonical step artifact (Step 35 required_outputs) — always written
    # when the screen actually ran (not on vacuous SKIP).
    if rc != 2:
        canon = project / "reports" / "phase3" / "dfm_screen.json"
        canon.parent.mkdir(parents=True, exist_ok=True)
        canon.write_text(out + "\n")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
