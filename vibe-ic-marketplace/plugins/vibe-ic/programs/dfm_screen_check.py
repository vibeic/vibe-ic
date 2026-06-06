#!/usr/bin/env python3
"""dfm_screen_check.py — Step 35 DFM screen (v2.3).

Design-for-Manufacturability, scoped HONESTLY for an open-source
130-180nm flow. Three designer-side measurables + one foundry-side
disclosure block:

  1. CMP density window — delegates to metal_fill_density_check's
     audit (per-layer 20-80% window + fill substance); its ERRORs are
     this screen's ERRORs (density is the CMP-aware half of DFM).
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

Exit codes: 0 PASS / PASS_WITH_ADVISORIES, 1 FAIL (density ERROR),
2 vacuous (no routed.def / no density artifacts yet).
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
import metal_fill_density_check as _mfd  # noqa: E402

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

    # 1) CMP density (delegate) --------------------------------------------
    d_findings, d_stats = _mfd.audit(project)
    density_errors = [f for f in d_findings if f.severity == "ERROR"]
    for f in d_findings:
        findings.append({"severity": f.severity,
                         "category": f"DENSITY/{f.category}",
                         "message": f.message})

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

    errors = density_errors
    advisories = [f for f in findings if f["severity"] == "WARNING"]
    verdict = ("FAIL" if errors else
               "PASS_WITH_ADVISORIES" if advisories else "PASS")
    return {
        "verdict": verdict,
        "rc": 1 if errors else 0,
        "density": {"errors": len(density_errors),
                    "stats": d_stats},
        "via_redundancy": via_summary,
        "foundry_side": _FOUNDRY_SIDE_ITEMS,
        "advanced_node_note": _ADVANCED_NODE_NOTE,
        "findings": findings,
    }


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
