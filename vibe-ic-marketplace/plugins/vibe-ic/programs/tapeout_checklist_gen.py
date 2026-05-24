#!/usr/bin/env python3
"""tapeout_checklist_gen.py — emit Step 33 reports/audit/tapeout_checklist.json.

v1.6.36 — closes the Step 33 runner-vs-flow drift waiver. The flow YAML's
gate runs `tapeout_signoff_check` (= signoff_audit --mode tapeout), which
expects a structured tapeout-checklist artefact at `reports/audit/
tapeout_checklist.json`. The audit walks the project's known sign-off
sources (GDS, netlist, sta, drc, lvs, irdrop, em, antenna, density,
power, foundry-handoff package) and pre-fills the tape-out reviewer's
TODO list with what's PASS / WAIVED / MISSING.

This is a DERIVED-VIEW generator: it does NOT run any EDA tool itself.
It walks the existing artefacts the runner already produced and emits a
machine-readable inventory. Substance gates upstream (drc_report_check,
lvs_report_check, sta_report_check, …) are still the source of truth.

chip-AGNOSTIC. Exits 0 on success, 2 if project dir missing.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402


# Each entry: (item, glob-relative-to-project, severity)
# Severity is reviewer guidance — not a blocking gate (the upstream
# substance check is the blocker).
_CHECKLIST_ITEMS = [
    ("gds",                "phase3/stage4/gds/*.gds",                  "blocker"),
    ("netlist",            "phase2/stage2/synth/*.v",                 "blocker"),
    ("post_route_def",     "phase3/stage3/pnr/*.def",                  "blocker"),
    ("sta_report",         "phase3/stage3/pnr/sta.rpt",                "blocker"),
    ("sta_per_corner",     "phase3/stage3/sta/per_corner/sta_*.rpt",   "advisory"),
    ("drc_report",         "reports/phase3/drc_signoff.rpt",           "blocker"),
    ("lvs_report",         "reports/phase3/lvs.rpt",                   "blocker"),
    ("erc_report",         "reports/phase3/erc.rpt",                   "advisory"),
    ("ir_drop_report",     "reports/phase3/ir_drop.rpt",               "advisory"),
    ("em_report",          "reports/phase3/em.rpt",                    "advisory"),
    ("antenna_report",     "reports/phase3/antenna.rpt",               "advisory"),
    ("density_report",     "reports/density.rpt",                      "advisory"),
    ("power_report",       "reports/phase3/power.rpt",                 "advisory"),
    ("metal_fill",         "phase3/stage3/pnr/filled.def",             "advisory"),
    ("metal_fill_flag",    "phase3/stage3/pnr/metal_fill.done",        "advisory"),
    ("spef",               "phase3/stage3/extracted/*.spef",           "advisory"),
    ("post_layout_sim",    "phase3/stage3/sim_postlayout/pass.flag",   "advisory"),
    ("eco_status",         "phase3/stage3/eco/no_eco_needed.flag",     "advisory"),
    ("foundry_mask_spec",  "phase3/stage4/foundry_handoff/mask_spec.json", "blocker"),
    ("foundry_wat_plan",   "phase3/stage4/foundry_handoff/wat_plan.json",  "blocker"),
    ("foundry_corner_kit", "phase3/stage4/foundry_handoff/corner_test_vectors.json", "blocker"),
    ("fpga_attestation",   "reports/phase2/fpga/on_board_pass.json",  "blocker"),
]


def _glob_first(project: Path, pattern: str):
    matches = sorted(project.glob(pattern))
    return matches[0] if matches else None


def _file_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except Exception:
        return 0


def _waivers_referencing(project: Path) -> dict:
    """Map step_id (int or str) → ticket id, from the project's waivers.json."""
    wpath = project / "waivers.json"
    if not wpath.is_file():
        return {}
    try:
        d = json.loads(wpath.read_text())
    except Exception:
        return {}
    out = {}
    for w in d.get("waived_steps", []):
        sid = w.get("id")
        out[str(sid)] = {
            "ticket": w.get("ticket", ""),
            "reason": (w.get("reason", "") or "")[:120],
        }
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("project", type=Path)
    p.add_argument("--out", default=None,
                   help="Override the output path (default: "
                        "reports/audit/tapeout_checklist.json)")
    args = p.parse_args(argv)

    project = args.project.resolve()
    if not project.is_dir():
        print(f"VACUOUS_PASS: project dir missing: {project}",
              file=sys.stderr)
        return 2

    waivers = _waivers_referencing(project)

    items = []
    blockers_present = 0
    blockers_total = 0
    for name, pattern, severity in _CHECKLIST_ITEMS:
        f = _glob_first(project, pattern)
        present = f is not None
        size = _file_size(f) if f else 0
        if severity == "blocker":
            blockers_total += 1
            if present:
                blockers_present += 1
        items.append({
            "name": name,
            "pattern": pattern,
            "present": present,
            "path": str(f.relative_to(project)) if f else None,
            "size_bytes": size,
            "severity": severity,
        })

    # Cross-reference outstanding waivers — anything not satisfied here
    # but waived in waivers.json is a reviewer to-do (sub-task) not a fail.
    out_path = Path(args.out) if args.out else (
        _pl.reports_audit_dir(project) / "tapeout_checklist.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "program": "tapeout_checklist_gen",
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": str(project),
        "summary": {
            "blockers_total": blockers_total,
            "blockers_present": blockers_present,
            "blockers_missing": blockers_total - blockers_present,
            "advisory_items_total": len(items) - blockers_total,
            "advisory_items_present":
                sum(1 for it in items
                    if it["severity"] == "advisory" and it["present"]),
        },
        "verdict": (
            "READY_FOR_TAPEOUT" if blockers_present == blockers_total
            else "BLOCKER_MISSING"
        ),
        "items": items,
        "open_waivers": waivers,
        "reviewer_todo": [
            f"Review waiver {w['ticket']}: {w['reason']}"
            for w in waivers.values()
            if w.get("ticket")
        ],
        "notes": (
            "This checklist is a derived inventory of present artefacts. "
            "BLOCKER items missing here MUST be authored before tape-out. "
            "Substance verification (DRC/LVS/STA/IR-drop) is performed by "
            "the dedicated upstream gates — this generator does not "
            "re-validate their content. Foundry-side acceptance of mask "
            "spec, WAT plan, scribe layout, corner test kit is also "
            "enforced by foundry_handoff_package_check (Step 35)."
        ),
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        "verdict": payload["verdict"],
        "blockers_present": blockers_present,
        "blockers_total": blockers_total,
        "out": str(out_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
