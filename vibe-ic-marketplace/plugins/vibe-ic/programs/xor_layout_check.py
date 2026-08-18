#!/usr/bin/env python3
"""XOR layout sign-off gate — computed GDS-vs-golden XOR, not a hardcoded floor.

TAPEOUT-SIGNOFF P0#3 (XOR half). A Caravel / Open-MPW shuttle submission must
XOR-match the assembled GDS (e.g. `user_project_wrapper`, or the full-chip
`caravel`) against the golden reference geometry with ZERO residual delta —
EXCEPT deltas that live entirely inside a *documented* blackbox hard-macro
(whose internal geometry is legitimately abstracted away in the reference, so a
delta there is expected and reviewer-waivable).

Why this program exists
=======================
Today `programs/caravel_integration_runner.py` ASSERTS a "2/7 floor" by
comparing the precheck fail-set to a HARDCODED memory constant
(`KNOWN_2_OF_7_FLOOR = {"Consistency", "XOR"}`). That constant is a *memory* of
what one pilot happened to see — it is never actually COMPUTED against the
submission's own geometry, so it cannot tell a legitimate blackbox-macro XOR
delta from a real one. This program REPLACES that assumption with a real,
per-layer KLayout XOR:

  (a) EMIT the KLayout XOR script — the standard `pya`/DRC-style layer-by-layer
      boolean XOR: read both layouts, per-layer `Region ^ Region`, report the
      residual geometry area + polygon count per layer, and ATTRIBUTE each
      residual to the enclosing macro instance so the verdict step can apply a
      documented waiver. Allow-listed blackbox macros are discovered RECURSIVELY
      (any depth below `--top`), so a documented macro nested below the XOR top
      (e.g. `spm` several levels under `caravel`) is attributable and waivable —
      not a silent no-op — while residual OUTSIDE it still FAILs (§4.05).
  (b) PARSE a completed XOR report → verdict:
        - PASS               when there is ZERO residual delta, OR every residual
                             bucket lies inside a macro cell that the caller
                             EXPLICITLY put on the blackbox-macro allow-list
                             (`PASS_WITH_WAIVER`).
        - FAIL               listing the per-layer residual (layer + area + which
                             cell) for any residual that is NOT inside an
                             allow-listed macro — including residual outside every
                             macro (the sentinel bucket `__outside_macros__`) and
                             residual the report could not attribute at all.
        - INCOMPLETE (§4.05) when the report (or a GDS) is absent / unparseable /
                             the emit script reported it could not find the top
                             cell. Absent evidence is NEVER a fabricated PASS.

§4.05 honesty invariants (enforced + unit-tested)
=================================================
  * The blackbox-macro allow-list is an EXPLICIT input — a list of macro CELL
    names the submitter documents as legitimately abstracted. It is NEVER a
    hardcoded count / floor. An empty allow-list means every residual is a real
    delta.
  * A waiver may ONLY swallow residual the report ATTRIBUTES to an allow-listed
    macro. Residual outside every macro, residual attributed to a
    non-allow-listed cell, and residual with no attribution at all ALL still
    FAIL. A waiver can never launder a real, out-of-macro delta into a PASS.
  * Missing report / missing GDS / unparseable report → INCOMPLETE, never PASS.

Chip-AGNOSTIC: pure geometry + a caller-supplied cell-name allow-list; no
design-specific literal appears anywhere in this file.

CLI
===
  # (a) emit the KLayout XOR script for a live run
  python3 xor_layout_check.py --emit-script xor.py \
      --top user_project_wrapper \
      --layout assembled.gds --golden golden_caravel.gds \
      --report-out xor_report.json
  # then, live:  klayout -zz -b -r xor.py    (writes xor_report.json)

  # (b) parse the completed report into a verdict
  python3 xor_layout_check.py --report xor_report.json \
      --allow-macro sram_1kbyte_1rw_1kbyte_32x256_8 \
      --allow-macro <another_documented_blackbox_macro>

Exit codes:  0 = PASS / PASS_WITH_WAIVER,  1 = FAIL,  2 = INCOMPLETE.

Unit tests: `programs/tests/test_xor_layout_check.py`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EMITTED_BY = "vibe-ic plugin xor_layout_check v1"

# Sentinel bucket for residual geometry that lies inside NO named macro
# instance. It can never appear on a legitimate allow-list (it is not a real
# cell name), so residual here is ALWAYS a real, unwaivable delta.
OUTSIDE_SENTINEL = "__outside_macros__"


# ---------------------------------------------------------------------------
# (a) KLayout XOR script emitter
# ---------------------------------------------------------------------------
# Standard pya layer-by-layer boolean XOR. Runs live under
# `klayout -zz -b -r <script>` (same batch pattern as the DEF→GDS streamout in
# phase3_one_shot_runner._GDS_STREAMOUT_PY). Paths are embedded as literals for
# reproducibility; an env override is honoured so a harness can re-point them.
_XOR_SCRIPT_TEMPLATE = '''\
# Auto-generated by {emitted_by} — KLayout layer-by-layer XOR.
# Compares the assembled layout-under-test against the golden reference GDS,
# per-layer boolean XOR (Region ^ Region), and writes a JSON residual report
# attributing each residual to the enclosing macro instance so a downstream gate
# can apply an EXPLICIT blackbox-macro waiver allow-list. Allow-listed macros are
# discovered RECURSIVELY (any depth below --top), so a documented blackbox macro
# nested below the XOR top (e.g. `spm` several levels under `caravel`) is
# attributable and thus waivable — not a silent no-op.
import os, sys, json
import pya

TOP = os.environ.get("XOR_TOP", {top!r})
LUT = os.environ.get("XOR_LAYOUT", {layout!r})     # layout under test (assembled GDS)
GOLD = os.environ.get("XOR_GOLDEN", {golden!r})    # golden reference GDS
REPORT = os.environ.get("XOR_REPORT", {report!r})
OUTSIDE = {outside!r}
# Documented blackbox-macro waiver allow-list, threaded in from the caller. Used
# ONLY to (a) discover NESTED allow-listed macros recursively and (b) order the
# residual attribution so an allow-listed macro claims its residual FIRST. It is
# purely an attribution aid — the PASS/FAIL waiver decision stays in the verdict
# step (xor_layout_check.classify_report), never here.
ALLOW_MACROS = {allow_macros!r}


def _write(obj):
    with open(REPORT, "w") as fh:
        json.dump(obj, fh, indent=2)


def _load(path):
    ly = pya.Layout()
    ly.read(path)
    return ly


def _topcell(ly, name):
    c = ly.cell(name)
    if c is None:
        tops = ly.top_cells()
        c = tops[0] if tops else None
    return c


def _macro_region_in_top(layout, top_cell, macro_name):
    # Union (in TOP coordinates) of the bounding box of EVERY placement of the
    # cell named `macro_name` anywhere below `top_cell` — including placements
    # nested several levels down. This is what lets a waiver reach a documented
    # blackbox macro that sits below the XOR --top (e.g. `spm` under `caravel`),
    # so `--allow-macro spm` at `--top caravel` is no longer a silent no-op.
    # Returns an empty Region when the cell is absent or never instantiated
    # under the top (the verdict step's inert-allow-macro advisory then reports
    # that the waiver matched nothing).
    mcell = layout.cell(macro_name)
    if mcell is None:
        return pya.Region()
    target_idx = mcell.cell_index()
    reg = pya.Region()

    def _walk(cell, base):
        for inst in cell.each_inst():
            icell = inst.cell
            # Array-aware: accumulate the top->placement transform for each
            # array member. each_cplx_trans yields one transform per member;
            # fall back to the single complex transform on older KLayout builds.
            try:
                member_trans = list(inst.each_cplx_trans())
            except Exception:
                member_trans = [inst.cplx_trans]
            for et in member_trans:
                t = base * et
                if inst.cell_index == target_idx:
                    reg.insert(icell.bbox().transformed(t))
                else:
                    _walk(icell, t)

    _walk(top_cell, pya.ICplxTrans())
    reg.merge()
    return reg


lut = _load(LUT)
gold = _load(GOLD)
dbu = lut.dbu or 0.001

lut_top = _topcell(lut, TOP)
gold_top = _topcell(gold, TOP)
if lut_top is None or gold_top is None:
    # Honest failure: no anchor top cell → cannot XOR. The verdict step reads
    # `error` and returns INCOMPLETE (§4.05), never a fabricated PASS.
    _write({{"tool": "klayout-xor", "top": TOP,
             "layout_under_test": LUT, "golden_reference": GOLD,
             "error": "top cell not found in one/both layouts",
             "lut_top": lut_top.name if lut_top else None,
             "gold_top": gold_top.name if gold_top else None}})
    print("XOR_ERROR top-cell-not-found")
    sys.exit(3)

# Merged instance-bbox region per DIRECT child cell of the layout-under-test
# top (diagnostic attribution — names the enclosing block in a FAIL).
macro_boxes = {{}}
for inst in lut_top.each_inst():
    cn = inst.cell.name
    macro_boxes.setdefault(cn, pya.Region()).insert(inst.bbox())

# NESTED allow-listed macro discovery. For each documented blackbox macro on the
# waiver allow-list, union the bbox of EVERY placement anywhere below the top.
# The recursion also covers a direct placement, so it safely supersedes the
# direct-child box for an allow-listed macro; a macro not instantiated under the
# top yields an empty region and is skipped (surfaced later as an inert waiver).
for mname in ALLOW_MACROS:
    reg = _macro_region_in_top(lut, lut_top, mname)
    if not reg.is_empty():
        macro_boxes[mname] = reg

# Attribution order: allow-listed macros FIRST, then everything else. Combined
# with carving from `remaining` (per layer, below) this makes attribution a true
# PARTITION and guarantees a nested waivable macro claims the residual inside it
# BEFORE the enclosing (non-allow-listed) direct-child box. §4.05: residual
# OUTSIDE every allow-listed macro necessarily lands in a non-allow-listed bucket
# or the OUTSIDE sentinel, both of which FAIL — a waiver cannot swallow it.
allow_first = [c for c in sorted(macro_boxes.keys()) if c in ALLOW_MACROS]
rest = [c for c in sorted(macro_boxes.keys()) if c not in ALLOW_MACROS]
ordered_cells = allow_first + rest

# Union of (layer, datatype) present in EITHER layout.
layer_infos = {{}}
for ly in (lut, gold):
    for idx in ly.layer_indexes():
        info = ly.get_info(idx)
        layer_infos[(info.layer, info.datatype)] = info


def _region(ly, top_cell, info):
    idx = ly.find_layer(info)
    if idx is None:
        return pya.Region()
    return pya.Region(top_cell.begin_shapes_rec(idx))


report_layers = []
total_count = 0
total_area_dbu2 = 0
for key in sorted(layer_infos.keys()):
    info = layer_infos[key]
    ra = _region(lut, lut_top, info)
    rb = _region(gold, gold_top, info)
    xor = ra ^ rb
    xor.merge()
    cnt = xor.count()
    if cnt == 0:
        continue
    name = info.name if info.name else ("%d/%d" % (info.layer, info.datatype))
    by_cell = []
    remaining = xor.dup()
    # True PARTITION: carve each claimed region out of `remaining` so a residual
    # polygon is counted in exactly ONE bucket, iterating allow-listed macros
    # FIRST (see ordered_cells). §4.05: `inside` is the residual intersected with
    # the macro bbox ONLY, so an allow-listed macro can never claim residual
    # outside its own bbox; the leftover in `remaining` (outside every
    # allow-listed macro) lands in a non-allow-listed bucket or OUTSIDE — a FAIL.
    for cn in ordered_cells:
        inside = remaining.dup() & macro_boxes[cn]
        ic = inside.count()
        if ic:
            by_cell.append({{"cell": cn, "count": ic,
                             "area_um2": inside.area() * dbu * dbu}})
            remaining = remaining - macro_boxes[cn]
    rc = remaining.count()
    if rc:
        by_cell.append({{"cell": OUTSIDE, "count": rc,
                         "area_um2": remaining.area() * dbu * dbu}})
    total_count += cnt
    total_area_dbu2 += xor.area()
    report_layers.append({{"layer": name, "residual_count": cnt,
                           "residual_area_um2": xor.area() * dbu * dbu,
                           "by_cell": by_cell}})

report = {{"tool": "klayout-xor", "top": TOP,
          "layout_under_test": LUT, "golden_reference": GOLD, "dbu": dbu,
          "total_residual_count": total_count,
          "total_residual_area_um2": total_area_dbu2 * dbu * dbu,
          "layers": report_layers}}
_write(report)
print("XOR_REPORT_WRITTEN " + REPORT)
print("XOR_TOTAL_RESIDUAL_COUNT " + str(total_count))
'''


def emit_xor_script(top: str,
                    layout_under_test: str,
                    golden_reference: str,
                    report_out: str,
                    allow_macros: Optional[List[str]] = None) -> str:
    """Return the pya KLayout XOR script text (chip-AGNOSTIC).

    The script reads both layouts, computes a per-layer boolean XOR, attributes
    each residual to the enclosing macro instance, and writes a JSON report at
    `report_out`. Run it with `klayout -zz -b -r <script>`.

    `allow_macros` (the same documented blackbox-macro waiver allow-list passed
    to `evaluate`) is threaded into the script so it can discover NESTED
    allow-listed macros recursively (any depth below `top`) and order the
    residual attribution allow-listed-macros-first. This makes `--allow-macro M`
    effective even when `M` sits several levels below the XOR `--top` (the
    verdict/waiver decision itself still lives in `classify_report`, §4.05).
    """
    return _XOR_SCRIPT_TEMPLATE.format(
        emitted_by=EMITTED_BY,
        top=str(top),
        layout=str(layout_under_test),
        golden=str(golden_reference),
        report=str(report_out),
        outside=OUTSIDE_SENTINEL,
        allow_macros=list(allow_macros or []),
    )


def klayout_command_hint(script_path: str) -> str:
    """The shell command a wrapper runs to execute the emitted XOR script."""
    return (f"export QT_QPA_PLATFORM=offscreen && "
            f"klayout -zz -b -r {script_path}")


# ---------------------------------------------------------------------------
# (b) Completed-report parser → verdict
# ---------------------------------------------------------------------------
def classify_report(report: Dict[str, Any],
                    allow_macros: Optional[List[str]] = None,
                    ) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Classify a parsed XOR report dict into (verdict, waived, failing).

    verdict ∈ {PASS, PASS_WITH_WAIVER, FAIL}. `waived` lists residual buckets
    covered by the EXPLICIT allow-list; `failing` lists every real delta.

    §4.05 rules baked in:
      * only residual attributed to an allow-listed macro cell is waivable;
      * residual in the `__outside_macros__` sentinel bucket, residual on a
        non-allow-listed cell, and residual with NO `by_cell` attribution ALL
        fail — a waiver can never swallow an out-of-macro / unattributed delta;
      * a positive `total_residual_count` with no per-layer breakdown fails
        (conservatively: a delta we cannot attribute is not waivable).
    """
    allow = set(allow_macros or [])
    waived: List[Dict[str, Any]] = []
    failing: List[Dict[str, Any]] = []

    layers = report.get("layers") or []
    accounted = 0
    for layer in layers:
        lname = layer.get("layer", "<unknown-layer>")
        lcount = int(layer.get("residual_count", 0) or 0)
        larea = float(layer.get("residual_area_um2", 0.0) or 0.0)
        if lcount == 0:
            continue
        accounted += lcount
        by_cell = layer.get("by_cell") or []
        if not by_cell:
            # Residual with no attribution can NEVER be waived (§4.05).
            failing.append({
                "layer": lname, "cell": None,
                "count": lcount, "area_um2": larea,
                "reason": ("unattributed residual — report gives no by_cell "
                           "attribution, so no waiver can apply")})
            continue
        for bucket in by_cell:
            cell = bucket.get("cell")
            bcount = int(bucket.get("count", 0) or 0)
            barea = float(bucket.get("area_um2", 0.0) or 0.0)
            if bcount == 0:
                continue
            if cell and cell != OUTSIDE_SENTINEL and cell in allow:
                waived.append({"layer": lname, "cell": cell,
                               "count": bcount, "area_um2": barea})
            else:
                if cell == OUTSIDE_SENTINEL or not cell:
                    reason = ("residual outside every allow-listed blackbox "
                              "macro — a real geometry delta")
                else:
                    reason = (f"cell '{cell}' is not on the blackbox-macro "
                              "allow-list — a real geometry delta")
                failing.append({"layer": lname, "cell": cell,
                                "count": bcount, "area_um2": barea,
                                "reason": reason})

    # Guard: a report that CLAIMS a positive total but breaks nothing down is
    # a real delta we cannot attribute → fail (never silently PASS it).
    total = report.get("total_residual_count")
    if total is not None and int(total) > 0 and accounted == 0 and not failing:
        failing.append({
            "layer": "<unknown-layer>", "cell": None,
            "count": int(total), "area_um2":
                float(report.get("total_residual_area_um2", 0.0) or 0.0),
            "reason": ("report declares a positive total_residual_count but "
                       "no per-layer breakdown — cannot attribute or waive")})

    if failing:
        verdict = "FAIL"
    elif waived:
        verdict = "PASS_WITH_WAIVER"
    else:
        verdict = "PASS"
    return verdict, waived, failing


def _attributed_cells(report: Dict[str, Any]) -> set:
    """The set of macro CELL names the report attributed any residual to.

    Used to detect an INERT allow-list entry -- a macro the submitter put on the
    waiver allow-list that the report never attributed residual to (so the waiver
    matched nothing). The emit script now discovers allow-listed macros
    RECURSIVELY (any depth below --top), so an inert entry no longer means a
    wrong --top; it means either the macro is not instantiated under the top at
    all, or no residual fell inside its bounding box. Surfacing this keeps a
    submitter from believing a waiver applied when it did not (§4.05: never let
    an inert waiver look effective)."""
    seen: set = set()
    for layer in report.get("layers") or []:
        for bucket in layer.get("by_cell") or []:
            cell = bucket.get("cell")
            if cell and cell != OUTSIDE_SENTINEL:
                seen.add(cell)
    return seen


def _incomplete(top: Optional[str], layout: Optional[str],
                golden: Optional[str], allow_macros: List[str],
                reason: str) -> Dict[str, Any]:
    return {
        "verdict": "INCOMPLETE",
        "top": top,
        "layout_under_test": layout,
        "golden_reference": golden,
        "allow_macros": list(allow_macros or []),
        "incomplete_reason": reason,
        "emitted_by": EMITTED_BY,
    }


def evaluate(report_path: Optional[Path],
             allow_macros: Optional[List[str]] = None,
             top: Optional[str] = None,
             layout_under_test: Optional[Path] = None,
             golden_reference: Optional[Path] = None) -> Dict[str, Any]:
    """Load a completed XOR report and return the verdict dict.

    INCOMPLETE (never PASS) when the report is absent / unparseable, when the
    emit script recorded an `error` (e.g. top cell not found), or when a GDS
    the report references was supplied but is missing.
    """
    allow_macros = list(allow_macros or [])
    lut_s = str(layout_under_test) if layout_under_test else None
    gold_s = str(golden_reference) if golden_reference else None

    # A supplied-but-absent GDS is honest INCOMPLETE, not a PASS.
    for label, p in (("layout-under-test", layout_under_test),
                     ("golden-reference", golden_reference)):
        if p is not None and not Path(p).is_file():
            return _incomplete(top, lut_s, gold_s, allow_macros,
                               f"{label} GDS absent: {p}")

    if report_path is None or not Path(report_path).is_file():
        return _incomplete(top, lut_s, gold_s, allow_macros,
                           f"XOR report absent: {report_path}")
    try:
        data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 — any parse failure is INCOMPLETE
        return _incomplete(top, lut_s, gold_s, allow_macros,
                           f"XOR report unparseable: {e}")
    if not isinstance(data, dict):
        return _incomplete(top, lut_s, gold_s, allow_macros,
                           "XOR report is not a JSON object")
    if data.get("error"):
        return _incomplete(top, data.get("layout_under_test", lut_s),
                           data.get("golden_reference", gold_s), allow_macros,
                           f"XOR script reported error: {data.get('error')}")

    verdict, waived, failing = classify_report(data, allow_macros)

    # Advisory (never changes the verdict, §4.05): flag any allow-list entry the
    # report attributed NO residual to. The emit script discovers allow-listed
    # macros RECURSIVELY (any depth below --top), so when there IS residual an
    # inert entry means either the macro is not instantiated under the top or no
    # residual fell inside its bounding box (i.e. the residual is genuinely
    # OUTSIDE the macro). Surfacing it stops a submitter believing a waiver
    # applied when it did not.
    attributed = _attributed_cells(data)
    inert_allow_macros = [m for m in allow_macros if m not in attributed]
    has_residual = int(data.get("total_residual_count") or 0) > 0 or bool(failing) \
        or bool(waived)
    advisories: List[str] = []
    if inert_allow_macros and has_residual:
        advisories.append(
            "allow-macro(s) matched no residual bucket: "
            + ", ".join(inert_allow_macros)
            + f" -- at XOR top cell '{data.get('top', top)}' the emitted script "
            "discovers allow-listed macros RECURSIVELY (nested placements "
            "included), so an inert entry means either the macro is not "
            "instantiated under this top or no residual fell inside its bounding "
            "box. The waiver had no effect (expected when the residual is "
            "genuinely OUTSIDE the macro).")

    return {
        "verdict": verdict,
        "top": data.get("top", top),
        "layout_under_test": data.get("layout_under_test", lut_s),
        "golden_reference": data.get("golden_reference", gold_s),
        "allow_macros": allow_macros,
        "inert_allow_macros": inert_allow_macros,
        "advisories": advisories,
        "total_residual_count": data.get("total_residual_count"),
        "total_residual_area_um2": data.get("total_residual_area_um2"),
        "waived_residual": waived,
        "failing_residual": failing,
        "emitted_by": EMITTED_BY,
    }


def verdict_exit_code(verdict: str) -> int:
    """0 = PASS / PASS_WITH_WAIVER, 1 = FAIL, 2 = INCOMPLETE."""
    if verdict in ("PASS", "PASS_WITH_WAIVER"):
        return 0
    if verdict == "FAIL":
        return 1
    return 2  # INCOMPLETE (or anything unexpected) is never a success


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="XOR layout sign-off gate — computed GDS-vs-golden XOR "
                    "with an explicit blackbox-macro waiver allow-list.")
    mode = p.add_argument_group("mode (choose one)")
    mode.add_argument("--emit-script", type=Path,
                      help="Emit the KLayout XOR pya script to this path.")
    mode.add_argument("--report", type=Path,
                      help="Parse a COMPLETED XOR report JSON into a verdict.")

    p.add_argument("--top", default="",
                   help="Top cell to XOR (e.g. user_project_wrapper / caravel).")
    p.add_argument("--layout", type=Path, default=None,
                   help="Assembled layout-under-test GDS.")
    p.add_argument("--golden", type=Path, default=None,
                   help="Golden reference GDS.")
    p.add_argument("--report-out", type=Path, default=Path("xor_report.json"),
                   help="[emit] Where the emitted script will write its report.")
    p.add_argument("--allow-macro", action="append", default=[], dest="allow_macros",
                   help="[report] A blackbox-macro CELL name whose internal "
                        "geometry is documented as abstracted (repeatable). "
                        "NEVER a count — an explicit, per-submission waiver.")
    p.add_argument("--out-json", type=Path, default=None,
                   help="Write the verdict/emit summary JSON here (else stdout).")
    args = p.parse_args(argv)

    if args.emit_script:
        if not args.top:
            print("ERROR: --emit-script requires --top", file=sys.stderr)
            return 2
        for label, gp in (("--layout", args.layout), ("--golden", args.golden)):
            if gp is not None and not Path(gp).is_file():
                print(f"WARN: {label} GDS not present yet: {gp} "
                      "(script still emitted; run it once the GDS exists)",
                      file=sys.stderr)
        script = emit_xor_script(
            args.top,
            str(args.layout) if args.layout else "assembled.gds",
            str(args.golden) if args.golden else "golden.gds",
            str(args.report_out),
            allow_macros=args.allow_macros)
        args.emit_script.parent.mkdir(parents=True, exist_ok=True)
        args.emit_script.write_text(script, encoding="utf-8")
        summary = {
            "mode": "emit",
            "script": str(args.emit_script),
            "top": args.top,
            "layout_under_test": str(args.layout) if args.layout else None,
            "golden_reference": str(args.golden) if args.golden else None,
            "report_out": str(args.report_out),
            "allow_macros": list(args.allow_macros or []),
            "command_hint": klayout_command_hint(str(args.emit_script)),
            "emitted_by": EMITTED_BY,
        }
        out = json.dumps(summary, indent=2)
        if args.out_json:
            args.out_json.write_text(out + "\n", encoding="utf-8")
        else:
            print(out)
        return 0

    if args.report:
        result = evaluate(
            args.report, args.allow_macros,
            top=args.top or None,
            layout_under_test=args.layout,
            golden_reference=args.golden)
        out = json.dumps(result, indent=2)
        if args.out_json:
            args.out_json.write_text(out + "\n", encoding="utf-8")
        else:
            print(out)
        return verdict_exit_code(result["verdict"])

    p.error("choose a mode: --emit-script <path> or --report <path>")
    return 2  # pragma: no cover — argparse.error exits


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
