#!/usr/bin/env python3
"""Verify metal fill was inserted, and judge any PER-LAYER density it carries.

WHAT THIS GATE DOES AND DOES NOT MEASURE
----------------------------------------
It reads the fill artefacts (filled.def / metal_fill.done) and the fill
emitter's own reports/density.{json,rpt}, and it substantiates that the fill
achieved SOMETHING (fillers placed, or the DEF grew, or rows were already
full, or an attested sparse-die skip).

The foundry's per-LAYER CMP density window is a different measurement, and
this gate applies it only when the density artefact actually carries per-layer
numbers. The OpenROAD filler_placement report normally does NOT: it carries
row/core utilization, which is not metal density. The summary used to report
``density_checked: true`` for that case — true only in the sense that a file
was opened — so a run in which not one per-layer density value was ever
examined read as though the density rule had been verified. Measured on the
real spm x ihp-sg13g2 run: layers_ok=0, layers_bad=0, pass=true, and
``density_checked: true``. The summary now says both things separately
(``density_artefact_read`` vs ``per_layer_density_verified``) and states, in a
NAMED INFO finding, who does judge the per-layer rule when this gate does not —
INCLUDING that today no flow gate does: `metal_layer_density_check` (the correct
judge of reports/phase3/metal_density.json) is reachable only through
`signoff_ladder_run`, which no flow step invokes. Wiring it is a separate,
measured change: over the 17 benchmark-data/ic project snapshots it resolves a
report on 10 and FAILs all 10 — 4 of them only against the DISCLOSED GENERIC
default window, because those runs declare no PDK. Making this step red on a
generic stand-in window is not a fix, so the CLAIM is corrected here and the
wiring is left to that change.
"""
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

    # `density_artefact_read` = a density artefact was opened (the old
    # `density_checked`, renamed because that name asserted a per-layer
    # verification the flag never carried). `per_layer_density_verified` is
    # derived after the parse: True only when at least one real per-layer CMP
    # density value was examined against the window.
    stats = {"fill_marker": False, "filled_larger": None,
             "density_artefact_read": False, "per_layer_density_verified": False,
             "layers_ok": 0, "layers_bad": 0,
             "filled_byte_identical": None}

    if not filled_def.exists() and not fill_done.exists():
        findings.append(Finding("ERROR", "NO_FILL",
                                "Neither pnr/filled.def nor pnr/metal_fill.done found"))
        return findings, stats
    stats["fill_marker"] = True

    if filled_def.exists() and routed_def.exists():
        filled_sz = filled_def.stat().st_size
        routed_sz = routed_def.stat().st_size
        stats["filled_larger"] = filled_sz > routed_sz
        # #364 — BYTE-IDENTITY is an unambiguous no-op: metal fill emitted
        # nothing at all. Measured on spm x gf180mcuD (plugin 1.6.7):
        # filled.def and routed.def identical at 472,921 B, zero FILLWIRES,
        # `metal_fill.done` present, step-34 PASS, and the shipped GDS then
        # measured 6 whole-die density violations (M1-MT under the deck's
        # per-layer floor). It passed because the ERROR-level substance test
        # can be satisfied by an IN-WINDOW per-layer density reading, while
        # the rule it stands in for is per-layer over the WHOLE DIE — an
        # escape hatch whose evidence is measured at a different scope than
        # the thing it excuses. No window measurement can substantiate fill
        # that produced not one byte, so this is recorded separately and
        # (below) no hatch may bypass it.
        stats["filled_byte_identical"] = (
            filled_sz == routed_sz
            and _same_bytes(filled_def, routed_def))
        if filled_sz <= routed_sz:
            findings.append(Finding("WARNING", "FILL_NOT_LARGER",
                                    f"filled.def ({filled_sz}B) is not larger than "
                                    f"routed.def ({routed_sz}B) — fill may be missing"))

    filler_n = None
    row_util = None
    if density_json.exists():
        stats["density_artefact_read"] = True
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
            # v0.3.9 — #510: core_utilization_pct is metadata (the
            # report_design_area axis), NOT a per-layer metal density —
            # exclude it so the legacy dict-of-layers fallback never
            # misreads it as an in-window "layer".
            _META_KEYS = {"filler_instances", "row_utilization_pct",
                          "core_utilization_pct",
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
        stats["density_artefact_read"] = True
        if density_rpt.stat().st_size == 0:
            findings.append(Finding("WARNING", "EMPTY_RPT",
                                    "density.rpt is empty"))

    # The honest per-layer answer, derived from what was ACTUALLY examined —
    # not from whether a file existed.
    stats["per_layer_density_verified"] = (
        stats["layers_ok"] + stats["layers_bad"]) > 0
    if stats["density_artefact_read"] and not stats["per_layer_density_verified"]:
        # NAMED, non-blocking. An earlier wording of this finding said the
        # per-layer rule "is judged by ... metal_layer_density_check", which
        # invited the reader to believe some gate downstream catches what this
        # one did not. Traced: `metal_layer_density_check` is called by
        # `signoff_ladder_run` alone, NO flow step invokes signoff_ladder_run,
        # and `tapeout_checklist_gen` only NAMES it as the row's authority in a
        # note — it never executes it. So the disclosure now states the
        # reachability as it is, including the part that is a gap.
        findings.append(Finding(
            "INFO", "PER_LAYER_DENSITY_NOT_VERIFIED_HERE",
            "the density artefact carries no per-layer metal CMP density "
            f"(0 layer values examined; window [{_MIN_DENSITY}%, "
            f"{_MAX_DENSITY}%] not applied by this gate) — it carries the "
            "OpenROAD filler_placement row/core utilization instead. Where the "
            "per-layer rule IS judged: the foundry's own KLayout sign-off DRC "
            "deck (met_min_ca_density), where the PDK ships one. Where it is "
            "NOT: reports/phase3/metal_density.json is the per-layer "
            "measurement, and no flow step judges it — metal_layer_density_"
            "check is reachable only through signoff_ladder_run, which no flow "
            "step invokes, and tapeout_checklist_gen carries the file as an "
            "ADVISORY reviewer row naming that gate without running it. This "
            "step's PASS therefore does not mean the per-layer window was "
            "checked by anything in this flow.",
            details="per_layer_density_verified=false"))

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
    # #684 round-8 — a 0-filler result is LEGITIMATE (not FILL_NO_SUBSTANCE)
    # when the runner DELIBERATELY skipped the full-die decap/fill tiling on a
    # sub-threshold sparse fixed wrapper (attested in sparse_die_skip.json).
    # Density-fill over empty silicon that carries no signals achieves
    # nothing; the skip is the attested engineering decision. §4.05 NO-LEAK: a
    # NON-sparse design with 0 fillers and no growth has NO attestation → it
    # still FAILs FILL_NO_SUBSTANCE.
    sparse_fill_attested = _sparse_die_fill_skip_attested(project_dir)
    stats["sparse_die_fill_skip_attested"] = sparse_fill_attested
    # #364 — checked BEFORE the substance ladder and outside it: a byte
    # identical filled.def is not a weak signal to be weighed against others,
    # it is proof that nothing was emitted. The exemptions are (a) the ATTESTED
    # sparse-die skip (#684), where producing no fill is the recorded
    # engineering decision, and (b) ROWS ALREADY FULL — when the standard-cell
    # filler ran DURING PnR (filler_placement runs after detailed_route), the
    # routed.def baseline already carries every fill cell (row_utilization_pct
    # >= 95), so a LATER standalone fill step correctly places 0 and emits a
    # byte-identical filled.def. That is fill DONE, not fill MISSING — the same
    # rows_already_full signal the FILL_NO_SUBSTANCE ladder below already
    # accepts as legitimate substance. Without this, every design whose fill is
    # inserted at PnR-time (the common open-flow shape; measured on spm ×
    # ihp-sg13g2 = 1257 sg13g2_fill_* instances already in routed.def, rows
    # 100%) FAILs the completion audit despite being fully filled.
    if (stats.get("filled_byte_identical") and not sparse_fill_attested
            and not rows_already_full):
        findings.append(Finding(
            "ERROR", "FILL_NOOP",
            "metal fill emitted NOTHING: filled.def is BYTE-IDENTICAL to "
            "routed.def. `metal_fill.done` and an in-window per-layer "
            "density reading cannot substantiate a fill that produced not "
            "one byte — the deck's floor is per-layer over the whole die "
            "(#364)"))
    elif (stats.get("filled_byte_identical") and rows_already_full
            and not sparse_fill_attested):
        # Transparent disclosure: byte-identical is EXPECTED here (fill already
        # placed at PnR); recorded so a reader is not left to infer it.
        findings.append(Finding(
            "INFO", "FILL_DONE_AT_PNR",
            f"filled.def is byte-identical to routed.def AND rows are already "
            f"full (row_utilization_pct={row_util}) — the standard-cell fill "
            f"was inserted during PnR (filler_placement after detailed_route), "
            f"so the standalone fill step correctly added nothing. Fill is "
            f"present in the routed.def baseline, not missing."))
    if placed_fillers and stats["filled_larger"] is False:
        # contradiction: claims fillers but the DEF didn't grow
        findings.append(Finding(
            "ERROR", "FILL_CLAIM_CONTRADICTION",
            f"density.json claims {filler_n} fillers placed but "
            f"filled.def is not larger than routed.def (#445)"))
    else:
        substance = (per_layer_ok or rows_already_full or sparse_fill_attested
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


def _same_bytes(a: Path, b: Path, chunk: int = 1 << 20) -> bool:
    """True iff two files have identical content. Streamed, so a large DEF is
    not read into memory; any read error returns False (a check that cannot
    read the files must not claim they are identical)."""
    try:
        with a.open("rb") as fa, b.open("rb") as fb:
            while True:
                ca, cb = fa.read(chunk), fb.read(chunk)
                if ca != cb:
                    return False
                if not ca:
                    return True
    except OSError:
        return False


def _sparse_die_fill_skip_attested(project_dir: Path) -> bool:
    """True iff the runner wrote reports/phase3/sparse_die_skip.json attesting
    a DELIBERATE sparse-die fill skip (#684). Read-only, fail-safe (any error
    → False, so a missing/garbage attestation never relaxes the gate).
    chip-AGNOSTIC."""
    try:
        p = _pl.reports_phase3_dir(project_dir) / "sparse_die_skip.json"
    except Exception:
        p = project_dir / "reports" / "phase3" / "sparse_die_skip.json"
    try:
        if p.is_file():
            data = json.loads(p.read_text(errors="replace"))
            return bool(isinstance(data, dict) and data.get("fill_skipped"))
    except Exception:
        pass
    return False


def build_report(findings: List[Finding], stats: dict,
                 project_dir: str) -> dict:
    return {
        "program": "metal_fill_density_check",
        "version": "1.0.0",
        "project_dir": project_dir,
        "summary": {
            "fill_marker": stats["fill_marker"],
            # Two separate facts. `density_artefact_read` is the old
            # `density_checked` under a name that does not claim more than it
            # knows; `per_layer_density_verified` is the claim a reader was
            # previously invited to draw from it.
            "density_artefact_read": stats["density_artefact_read"],
            "per_layer_density_verified": stats["per_layer_density_verified"],
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
