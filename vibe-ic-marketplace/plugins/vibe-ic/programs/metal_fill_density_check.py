#!/usr/bin/env python3
"""Verify metal fill was inserted, and judge any PER-LAYER density it carries.

WHAT THIS GATE DOES AND DOES NOT MEASURE
----------------------------------------
It reads the fill artefacts (filled.def / metal_fill.done) and the fill
emitter's own reports/density.{json,rpt}, and it substantiates that the fill
achieved SOMETHING (fillers placed, or the DEF grew, or rows were already
full, or an attested sparse-die skip).

A BYTE-IDENTICAL filled.def is judged separately and more strictly, ABOVE that
ladder (#364): nothing was emitted, so no signal from the ladder may excuse it.
The only two exemptions are an ATTESTED sparse-die skip (#684) and fill that was
already inserted at PnR — and the second requires fill cells MEASURED PRESENT in
the routed.def baseline, not merely a high row utilization, because row-util
counts logic and fill together and so cannot tell "already filled" from "never
filled". See the §4.05 note at the check itself.

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
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


_MIN_DENSITY = 20.0
_MAX_DENSITY = 80.0

# A physical ROW-FILL cell master. chip-AGNOSTIC by construction: it matches
# the LEF/DEF physical-cell NAMING CONVENTION (a `fill`/`filler`/`decap`/`dcap`
# token), never a vendor, PDK, SKU or chip literal. Every open PDK names its
# row fillers this way — `<prefix>_fill_1`, `<prefix>__fill_2`, `FILLER_4`,
# `DECAP8` all match on the same generic token, and no PDK name appears in
# this program. `filler_placement` is what inserts both fill and decap into
# row gaps, so both are counted. Same convention already used by
# `decap_route_short_guard._DECAP_RE`.
# Longest alternatives first so `FILLER`/`FILLCAP` are not cut short at `FILL`.
_FILL_MASTER_RE = re.compile(r"(?:^|[^A-Za-z])(filler|fillcap|fill|decap|dcap)"
                             r"(?:[^A-Za-z]|$)", re.I)

# `- <instName> <masterName> ...` inside the DEF COMPONENTS section.
_DEF_COMPONENT_RE = re.compile(r"^\s*-\s+(\S+)\s+(\S+)")


def baseline_fill_instance_count(routed_def: Path) -> Optional[int]:
    """Count ROW-FILL cell instances already present in the PnR baseline DEF.

    Returns None when the DEF cannot be read or carries no COMPONENTS section —
    "not measured" and "measured zero" must never look alike (§4.05), because
    the byte-identical exemption below is granted ONLY on a measured non-zero
    count. Streams the file and stops at `END COMPONENTS`, so a multi-hundred-MB
    routed DEF is never read into memory.
    """
    if not routed_def.is_file():
        return None
    n = 0
    in_components = False
    saw_components = False
    try:
        with routed_def.open("r", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if not in_components:
                    if s.startswith("COMPONENTS"):
                        in_components = True
                        saw_components = True
                    continue
                if s.startswith("END COMPONENTS"):
                    break
                m = _DEF_COMPONENT_RE.match(line)
                if m and _FILL_MASTER_RE.search(m.group(2)):
                    n += 1
    except OSError:
        return None
    return n if saw_components else None


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
    # it is proof that THIS STEP emitted nothing. The exemptions are (a) the
    # ATTESTED sparse-die skip (#684), where producing no fill is the recorded
    # engineering decision, and (b) FILL ALREADY DONE AT PnR — when the
    # standard-cell filler ran DURING PnR (filler_placement runs after
    # detailed_route) the routed.def baseline ALREADY CARRIES the fill cells, so
    # a LATER standalone fill step correctly places 0 and emits a
    # byte-identical filled.def. Without (b), every design whose fill is
    # inserted at PnR-time (the common open-flow shape) FAILs the completion
    # audit despite being fully filled.
    #
    # §4.05 NO-LEAK — exemption (b) is a RELAXATION, so its evidence must be
    # the thing it claims, measured, and it is deliberately a CONJUNCTION:
    #
    #   * `rows_already_full` ALONE CANNOT CARRY IT. row_utilization_pct is
    #     computed by the runner as sum(area of every CORE*-class instance) /
    #     row area — LOGIC cells and FILL cells TOGETHER (phase3_one_shot_
    #     runner's odb block: `if {[string match "CORE*" [$_m getType]]}`).
    #     A densely-placed design with ZERO fill cells therefore also reads
    #     >= 95, so keying the exemption on row-util alone lets the one design
    #     class that most needs FILL_NOOP — dense rows, no fill ever inserted —
    #     pass while the gate ASSERTS "fill is present in the baseline". That
    #     is a claim the gate would never have checked. Reproduced as a
    #     negative control in test_v0_2_75_metal_fill_substance.
    #   * So the exemption ALSO requires fill cells to be MEASURED PRESENT in
    #     the routed.def baseline (baseline_fill_instance_count > 0), which is
    #     the direct evidence for "already filled" rather than a proxy for it.
    #   * NOT MEASURABLE IS NOT EXEMPT (fail-closed): an unreadable DEF or one
    #     with no COMPONENTS section returns None, not 0, and no exemption is
    #     granted.
    # Measured ONLY on the byte-identical path: the scan streams the DEF's
    # COMPONENTS section, and that path is the only one whose verdict depends on
    # the count. A normal (grown) filled.def never pays for the scan.
    baseline_fill_n = (baseline_fill_instance_count(routed_def)
                       if stats.get("filled_byte_identical") else None)
    stats["baseline_fill_instances"] = baseline_fill_n
    fill_present_in_baseline = (isinstance(baseline_fill_n, int)
                                and baseline_fill_n > 0)
    stats["fill_present_in_baseline"] = fill_present_in_baseline
    fill_done_at_pnr = rows_already_full and fill_present_in_baseline
    stats["fill_done_at_pnr"] = fill_done_at_pnr
    if (stats.get("filled_byte_identical") and not sparse_fill_attested
            and not fill_done_at_pnr):
        findings.append(Finding(
            "ERROR", "FILL_NOOP",
            "metal fill emitted NOTHING: filled.def is BYTE-IDENTICAL to "
            "routed.def. `metal_fill.done` and an in-window per-layer "
            "density reading cannot substantiate a fill that produced not "
            "one byte — the deck's floor is per-layer over the whole die "
            "(#364)"))
    elif (stats.get("filled_byte_identical") and fill_done_at_pnr
            and not sparse_fill_attested):
        # Transparent disclosure: byte-identical is EXPECTED here (fill already
        # placed at PnR); recorded so a reader is not left to infer it. The
        # MEASURED instance count is stated, so the "fill is present" claim is
        # backed by the number that was actually counted rather than asserted.
        findings.append(Finding(
            "INFO", "FILL_DONE_AT_PNR",
            f"filled.def is byte-identical to routed.def, rows are already "
            f"full (row_utilization_pct={row_util}) AND the routed.def "
            f"baseline already carries {baseline_fill_n} row-fill cell "
            f"instance(s) — the standard-cell fill was inserted during PnR "
            f"(filler_placement after detailed_route), so the standalone fill "
            f"step correctly added nothing. Fill is present in the routed.def "
            f"baseline, not missing.",
            details=f"baseline_fill_instances={baseline_fill_n}"))
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
            # #364 — the evidence the byte-identical exemption was granted on,
            # in a MACHINE-READABLE field rather than only inside a finding's
            # prose. `.get` because the NO_FILL early return never measures
            # them. `baseline_fill_instances: null` means NOT MEASURED, which is
            # not the same as 0 and never buys the exemption.
            "baseline_fill_instances": stats.get("baseline_fill_instances"),
            "fill_done_at_pnr": stats.get("fill_done_at_pnr", False),
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

    # vibe-ic#1080 — `report["summary"]` is already the machine-readable form
    # of what this gate measured, so the wiring is to HAND IT OVER rather than
    # to compute anything new. Filtered to scalars per value, not all-or-
    # nothing: the flat schema refuses a non-scalar, and one unexpected list
    # would otherwise drop the whole file and leave this step looking wired
    # while emitting nothing (measured on step 17 while writing this).
    import step_metrics as _sm  # noqa: PLC0415
    _sm.emit_best_effort(project_dir, "34", {
        k: v for k, v in report["summary"].items()
        if v is None or isinstance(v, (bool, int, float, str))
    }, domain="design")

    out = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    print(out)
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
