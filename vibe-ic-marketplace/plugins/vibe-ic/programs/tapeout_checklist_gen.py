#!/usr/bin/env python3
"""tapeout_checklist_gen.py — emit Step 36 (v2.3) reports/audit/tapeout_checklist.json.

v1.6.36 — closes the tapeout-checklist runner-vs-flow drift waiver. The flow YAML's
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


# Each entry: (item, glob-relative-to-project, severity, gate)
# `gate` names the AUTHORITATIVE sign-off gate program (or None for a
# presence-only inventory row). For a row with a gate, the checklist is a
# reminder that PRESENCE alone is NOT a pass — the named gate (run by
# `signoff_ladder_run --mode tapeout`) verifies substance (e.g. the LVS row
# requires a GENUINE netgen match, not a POWER_PIN_ONLY waiver).
# Severity is reviewer guidance — not a blocking gate (the upstream
# substance check is the blocker).
_CHECKLIST_ITEMS = [
    ("gds",                "phase3/stage4/gds/*.gds",                  "blocker",  None),
    ("netlist",            "phase2/stage2/synth/*.v",                 "blocker",  None),
    ("post_route_def",     "phase3/stage3/pnr/*.def",                  "blocker",  None),
    ("sta_report",         "phase3/stage3/pnr/sta.rpt",                "blocker",  None),
    ("sta_per_corner",     "phase3/stage3/sta/per_corner/sta_*.rpt",   "advisory", None),
    ("sta_rigor",          "phase3/stage3/pnr/post_route_timing.rpt",  "advisory", "sta_signoff_rigor_check"),
    ("drc_report",         "reports/phase3/drc_signoff.rpt",           "blocker",  None),
    # LVS is genuine-match-required, NOT presence-only: a POWER_PIN_ONLY netgen
    # waiver does NOT count as a tapeout LVS pass (lvs_tapeout_signoff_check).
    ("lvs_report",         "reports/phase3/lvs.rpt",                   "blocker",  "lvs_tapeout_signoff_check"),
    ("erc_report",         "reports/phase3/erc.rpt",                   "advisory", None),
    ("ir_drop_report",     "reports/phase3/ir_drop.rpt",               "advisory", None),
    ("em_report",          "reports/phase3/em.rpt",                    "advisory", None),
    # EM current-density is the REAL J-vs-Jmax gate (replaces the decap-count
    # proxy); the per-segment CSV is the artifact its gate consumes.
    ("em_density",         "reports/phase3/em_segments.csv",           "advisory", "em_current_density_check"),
    ("antenna_report",     "reports/phase3/antenna.rpt",               "advisory", None),
    ("density_report",     "reports/density.rpt",                      "advisory", None),
    ("power_report",       "reports/phase3/power.rpt",                 "advisory", None),
    ("metal_fill",         "phase3/stage3/pnr/filled.def",             "advisory", None),
    ("metal_fill_flag",    "phase3/stage3/pnr/metal_fill.done",        "advisory", None),
    ("spef",               "phase3/stage3/extracted/*.spef",           "advisory", None),
    # MBIST — every writable on-chip RAM needs a March-test wrapper (N/A when
    # the design is RAM-less). mbist_wrapper_gen is the authority.
    ("mbist_wrapper",      "phase3/**/mbist_manifest.json",            "advisory", "mbist_wrapper_gen"),
    # DYNAMIC (transient) IR-drop — di/dt droop vs a %-of-Vdd budget. Distinct
    # from the STATIC ir_drop above; dynamic_ir_drop_check is the authority
    # (absent report → SKIP, never the static report as a dynamic pass).
    ("dynamic_ir_report",  "reports/phase3/dynamic_ir.json",           "advisory", "dynamic_ir_drop_check"),
    # PER-LAYER metal density (foundry CMP / Efabless met_min_ca_density) —
    # distinct axis from the row/core-util density.rpt above. metal_layer_
    # density_check is the authority.
    ("metal_layer_density","reports/phase3/metal_density.json",         "advisory", "metal_layer_density_check"),
    # Aging-corner STA (NBTI/PBTI/HCI Vt-drift over lifetime) — aging_derate_
    # sta_check is the authority (no foundry aging Liberty → honest SKIP).
    ("aging_sta_report",   "reports/phase3/aging_sta.json",             "advisory", "aging_derate_sta_check"),
    # Thermal power-density screen (W/mm² + Tj) — thermal_screen_check is the
    # authority (power not_computed / no die area → honest SKIP).
    ("thermal_screen",     "reports/phase3/thermal_screen.json",        "advisory", "thermal_screen_check"),
    # DFT sign-off (stuck-at + at-speed transition + BSDL) — dft_signoff_check
    # is the authority (recomputes coverage vs the foundry floor).
    ("dft_signoff",        "reports/phase2/dft/coverage.json",          "advisory", "dft_signoff_check"),
    # POST-LAYOUT LEC — the FINAL routed/repair netlist re-proven == synth/RTL
    # (Step-13 LEC only proved RTL==synth). lec_post_layout_check is the
    # authority (a non-proof is a FAIL, not a pass; no routed netlist → SKIP).
    ("lec_post_layout",    "reports/phase3/lec_post_layout.json",       "advisory", "lec_post_layout_check"),
    ("post_layout_sim",    "phase3/stage3/sim_postlayout/pass.flag",   "advisory", None),
    ("postroute_timing_repair_status",         "phase3/stage3/postroute_timing_repair/no_repair_needed.flag",     "advisory", None),
    ("foundry_mask_spec",  "phase3/stage4/foundry_handoff/mask_spec.json", "blocker", None),
    ("foundry_wat_plan",   "phase3/stage4/foundry_handoff/wat_plan.json",  "blocker", None),
    ("foundry_corner_kit", "phase3/stage4/foundry_handoff/corner_test_vectors.json", "blocker", None),
    ("fpga_attestation",   "reports/phase2/fpga/on_board_pass.json",  "blocker",  None),
    # Caravel / Open-MPW shuttle rows (N/A for non-Caravel designs — absent is
    # not a failure there). The gate is the authority, not file presence.
    #
    # #1744 — the `mpw_precheck` row addresses a RETIRED shuttle. It is KEPT so
    # a project carrying old evidence still has somewhere to put it, and so the
    # retirement is visible rather than looking like an omission. It can no
    # longer be the answer to "would an outside party accept this", because the
    # outside party it names stopped answering in 2025.
    ("mpw_precheck",       "**/mpw_precheck/**/*.log",                 "advisory", "mpw_precheck_result_gate"),
    # The LIVE external refusal. This is the ONLY row on this checklist whose
    # authority is not us: every other gate named here is a program in this
    # tree, and a gate we wrote can be made to pass by editing it.
    ("shuttle_readiness",  "reports/audit/tapeout_readiness.json",     "advisory", "tapeout_readiness_check"),
    ("layout_xor",         "reports/**/xor_report.json",               "advisory", "xor_layout_check"),
]

#: Where `tapeout_readiness_check` writes its verdict. Read — never written —
#: here: this generator does not run EDA tools and does not run that gate. The
#: path is IMPORTED from the gate that owns it rather than retyped, so the row
#: above cannot end up watching a file nothing writes.
try:
    from tapeout_readiness_check import READINESS_ARTEFACT as _READINESS_ARTEFACT
except ImportError:  # pragma: no cover - package-context fallback
    _READINESS_ARTEFACT = "reports/audit/tapeout_readiness.json"

# Human-readable "why the gate, not presence" note per authoritative gate.
_GATE_NOTES = {
    "lvs_tapeout_signoff_check":
        "genuine netgen `Circuits match uniquely` required — a POWER_PIN_ONLY "
        "waiver is NOT a tapeout LVS pass.",
    "em_current_density_check":
        "real per-segment J vs the PDK Jmax limit — replaces the decap-count "
        "proxy; absent Jmax reference → SKIP, never a pass.",
    "sta_signoff_rigor_check":
        "sign-off STA must carry OCV derate + recovery/removal + "
        "min-pulse-width — a bare setup/hold-MET report is optimistic.",
    "mbist_wrapper_gen":
        "every writable on-chip RAM needs a March-test MBIST wrapper "
        "(N/A when the design is RAM-less).",
    "mpw_precheck_result_gate":
        "RETIRED (#1744): the Efabless/chipIgnite shuttle operator ceased "
        "operating in 2025. This row can no longer yield an external verdict — "
        "an absent run here is NOT_DETERMINED and PERMANENTLY so, never a clean "
        "shuttle result. See the shuttle_readiness row for the live interface.",
    "tapeout_readiness_check":
        "the LIVE external refusal: the shuttle operator's OWN precheck, run "
        "unmodified, with its own run directory read back. The only authority "
        "on this checklist that is not a program in this tree — which is why "
        "its absence is reported as NOT_DETERMINED rather than passed over.",
    "xor_layout_check":
        "computed GDS-vs-golden XOR with an EXPLICIT blackbox-macro waiver "
        "allow-list — replaces the hardcoded 2/7 floor.",
    "dynamic_ir_drop_check":
        "transient (di/dt) IR droop vs a %-of-Vdd budget — distinct from the "
        "static IR row; absent dynamic report → SKIP, never the static report "
        "read as a dynamic pass.",
    "metal_layer_density_check":
        "PER-LAYER metal density within the foundry CMP window (Efabless "
        "met_min_ca_density) — the row/core-util density.rpt is a different "
        "axis and is NOT a substitute.",
    "aging_derate_sta_check":
        "aging-derated STA (NBTI/PBTI/HCI Vt-drift) worst slack >= margin — no "
        "foundry aging Liberty → honest SKIP, never a fabricated aging number.",
    "thermal_screen_check":
        "first-order power-density screen (W/mm², + Tj when available) — power "
        "not_computed / no die area → honest SKIP.",
    "dft_signoff_check":
        "aggregate DFT sign-off: stuck-at recomputed vs the foundry floor + a "
        "real/documented-engine-limited at-speed transition record + a BSDL "
        "for a padded design.",
    "lec_post_layout_check":
        "the FINAL routed/repair netlist re-proven logically == synth/RTL "
        "(Step-13 only proved RTL==synth) — a non-proof is a FAIL, not a pass.",
}


def _external_refusal(project: Path) -> dict:
    """State what the OUTSIDE party said — including that it said nothing.

    #1744. Every other block in this payload summarises an artefact one of our
    own programs produced. This one summarises the single interface where the
    verdict is not ours, and its default is the honest one: with no readiness
    artefact on disk, the shuttle was never asked, so the verdict is
    NOT_DETERMINED. It is emitted UNCONDITIONALLY — a key that only appears when
    there is good news is a key nobody notices is missing, and "the dead vendor
    said nothing" and "the live shuttle passed us" must not be the same silence.

    This does NOT run the gate. This generator runs no EDA tool and asks no
    counterparty; it reports the gate's artefact if one is there.
    """
    out = {
        "verdict": "NOT_DETERMINED",
        "gate": "tapeout_readiness_check",
        "artefact": _READINESS_ARTEFACT,
        "present": False,
        "why": ("no shuttle-readiness artefact on disk: the live external "
                "refusal interface was never asked, so nothing outside this "
                "tree has judged this layout. Run `tapeout_readiness_check "
                "<project>` to obtain one."),
        "retired_paths": [
            {"gate": "mpw_precheck_result_gate",
             "status": "RETIRED",
             "why": ("the Efabless/chipIgnite shuttle operator ceased "
                     "operating in 2025; no run of that ladder can produce an "
                     "external verdict, so its silence is NOT_DETERMINED and "
                     "permanently so")},
        ],
    }
    path = project / _READINESS_ARTEFACT
    if not path.is_file():
        return out
    try:
        data = json.loads(path.read_text(errors="replace"))
    except Exception:
        out["present"] = True
        out["why"] = (f"{_READINESS_ARTEFACT} is present but unparseable — an "
                      "unreadable verdict is not a verdict")
        return out
    out["present"] = True
    verdict = str(data.get("verdict", "")).strip().upper()
    # Only the gate's own three tokens are honoured. Anything else — an older
    # schema, a truncated write, a hand-edited file — is NOT_DETERMINED, because
    # a token we do not recognise must not be promoted to a pass.
    out["verdict"] = verdict if verdict in ("PASS", "FAIL",
                                            "NOT_DETERMINED") else "NOT_DETERMINED"
    for key in ("shuttle", "shuttle_status", "tool", "reason", "layout",
                "failed_steps", "undetermined_steps", "uncovered_in_tree"):
        if key in data:
            out[key] = data[key]
    if out["verdict"] != verdict:
        out["why"] = (f"unrecognised verdict token {verdict!r} in "
                      f"{_READINESS_ARTEFACT}; read as NOT_DETERMINED")
    else:
        out["why"] = str(data.get("reason", ""))[:400]
    return out


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
    external_refusal = _external_refusal(project)

    items = []
    blockers_present = 0
    blockers_total = 0
    for name, pattern, severity, gate in _CHECKLIST_ITEMS:
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
            # AUTHORITATIVE sign-off gate for this row (None = presence-only).
            # When set, PRESENCE is NOT a pass — the named gate verifies
            # substance (run via `signoff_ladder_run --mode tapeout`).
            "gate": gate,
            "gate_note": _GATE_NOTES.get(gate) if gate else None,
            "presence_is_pass": gate is None,
        })

    # flow v2.3.1 (review P1-5) — PENDING_FOUNDRY tracking closes here: the
    # handoff gate's pending_foundry_fields become NAMED checklist open
    # items, owned by the tapeout checklist until the foundry replies
    # and the fields are back-filled into mask_spec.json.
    pending_foundry = []
    for rel in ("reports/phase2/gates/foundry_handoff.json",
                 "reports/phase3/foundry_handoff_audit.json"):
        gp = project / rel
        if not gp.is_file():
            continue
        try:
            gd = json.loads(gp.read_text(errors="replace"))
        except Exception:
            continue
        pf = gd.get("pending_foundry_fields")
        if isinstance(pf, list) and pf:
            pending_foundry = pf
            break
    if not pending_foundry:
        # fall back to scanning the pack members directly
        for mf in sorted(project.glob(
                "phase3/stage4/foundry_handoff/*.json")):
            try:
                md = json.loads(mf.read_text(errors="replace"))
            except Exception:
                continue
            for k in md:
                if str(k).startswith("PENDING_FOUNDRY_"):
                    pending_foundry.append(
                        f"{mf.relative_to(project)}:{k}")

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
        # The authoritative sign-off gate per checklist row (row -> gate
        # program). Rows here are substance-gated, not presence-only: the LVS
        # row requires a genuine netgen match (not a POWER_PIN_ONLY waiver),
        # EM is real J-vs-Jmax, etc. These gates run in
        # `signoff_ladder_run --mode tapeout`.
        "gate_references": {
            it["name"]: it["gate"] for it in items if it.get("gate")
        },
        # #1744 — the ONE verdict on this checklist that is not ours. Emitted
        # unconditionally, and NOT_DETERMINED by default: the summary above
        # counts artefacts we produced, and counting only those is how "nobody
        # outside has looked at this" came to look identical to "an outside
        # party looked and was satisfied".
        "external_refusal": external_refusal,
        "open_waivers": waivers,
        "pending_foundry_items": pending_foundry,   # flow v2.3.1 P1-5
        "reviewer_todo": [
            f"Review waiver {w['ticket']}: {w['reason']}"
            for w in waivers.values()
            if w.get("ticket")
        ] + [
            f"PENDING_FOUNDRY open item (back-fill after foundry "
            f"reply): {x}" for x in pending_foundry
        ] + ([
            "EXTERNAL REFUSAL "
            f"{external_refusal['verdict']}: {external_refusal['why']}"
        ] if external_refusal["verdict"] != "PASS" else []),
        "notes": (
            "This checklist is a derived inventory of present artefacts. "
            "BLOCKER items missing here MUST be authored before tape-out. "
            "Rows carrying a `gate` are SUBSTANCE-gated, not presence-only: "
            "the LVS row requires a GENUINE netgen match (a POWER_PIN_ONLY "
            "waiver is NOT a tapeout pass), EM is real J-vs-Jmax (not the "
            "decap-count proxy), STA must carry OCV+recovery/removal+MPW "
            "rigor, every writable RAM needs an MBIST wrapper, and Caravel "
            "shuttle submissions must pass the mpw-precheck + a computed XOR. "
            "Those gates run in `signoff_ladder_run --mode tapeout` (see each "
            "row's `gate` / `gate_note`); this generator does not re-validate "
            "their content. Foundry-side acceptance of mask spec, WAT plan, "
            "scribe layout, corner test kit is also enforced by "
            "foundry_handoff_package_check (Step 38, v2.3)."
        ),
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        "verdict": payload["verdict"],
        "blockers_present": blockers_present,
        "blockers_total": blockers_total,
        # #1744 — printed beside the verdict, not buried in the file. A reader
        # who sees only READY_FOR_TAPEOUT has been told what OUR artefacts say
        # and nothing about what anyone outside would do with them.
        "external_refusal": external_refusal["verdict"],
        "out": str(out_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
