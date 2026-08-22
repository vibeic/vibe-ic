#!/usr/bin/env python3
"""pad_ring_gen — step 15.5ic's producer: place a DECLARED pad ring by
upstream's own algorithm, or name the config variables it went without.

WHERE THIS SITS, AND WHY IT IS BEFORE ROUTING
=============================================
Once a pad ring exists the pads ARE the design's BTerms. Upstream's chip flow
says so by DELETION — it substitutes its IO-placement step to `None` with the
note "No pin placement necessary -> pads are the BTerms", and inserts the pad
ring immediately after the power connections are set. Step 15.5ic is that
position in this flow: after floorplan/PDN, before routing.

THE ALGORITHM, WRITTEN DOWN BEFORE IT IS CODED
==============================================
Taken from upstream's pad config TCL, whose own numbered comment reads, for
every side:

    1. Sum up all pad widths for the side
    2. If that value is larger than the side, throw an error
    3. Subtract that value from the side width
    4. Divide this value by the number of pads for this side + 1
    5. Round this value DOWN to the minimum site width (the pad spacing)
    6. Multiply by the number of pads minus one, subtract from the side width
    7. Divide by two — this is the spacing from pads to corners
    8. Throw an error if that spacing is not a multiple of the minimum site
       width

Steps 2 and 8 are REFUSALS, and they are the whole reason the ring can abut:
every gap in it comes out a whole number of minimum-filler widths. Around that
sit four more refusals — an unresolvable pad site, a site whose class is not
`PAD`, an instance the block does not contain, and (ours) a declared master
the PDK's IO library does not carry. There is no warn-and-continue in
upstream's file and there is none here.

Order of operations is theirs as well: sites resolved, pads placed per side at
an absolute position, corners placed, and then — the step people forget —
`connect_by_abutment`. THE RING'S SUPPLY IS NOT ROUTED. It is formed by cells
touching. So this program computes every gap in the ring walk and refuses a
ring whose gaps the declared filler cells cannot close, and records the gaps
so the later filler step has its input.

THE ALONG-THE-ROW EXTENT IS THE MASTER'S WIDTH, ON ALL FOUR SIDES
=================================================================
This program used to take each pad's along-the-row extent from the ORIENTED
footprint, so a side whose declared rotation did not swap the axes summed the
master's HEIGHT. Two independent sources say that is wrong, and neither of them
is the outcome:

    upstream `pad_cfg.tcl` measures a cell in exactly two places and BOTH are
    `[[$inst getMaster] getWidth]`, for all four sides including the vertical
    ones — the fit sum, and the along-the-row step
    `cur_pos + space_between_pads_min_filler + $width`. There is no
    `getHeight` anywhere in its side arithmetic.

    MEASURED, four SEPARATE OpenROAD processes (26Q3-1165), one per
    `PAD_ROTATION_VERTICAL` value so no row from an earlier pass could be
    reused by a later one:
        ROTV = R0 / R90 / R180 / MX
        WEST -> orient MXR90, EAST -> orient R90
        75 um along the row, 350 um into the die, IDENTICAL in all four.

The correction is right whichever way it moves a verdict — it was made on the
strength of those two sources, not because a ring then fits. On a real ring it
happened to be a 4.4x error: 19 x 350 = 6650 um against a 1500 um side, which
refused a ring upstream places.

`PAD_ROTATION_VERTICAL` IS NOT HONOURED HERE, AND SAYS SO OUT LOUD
==================================================================
THIS SECTION SAID "IS INERT" AND "the placer does not read it" AND BOTH WERE
WRONG. Re-measured 2026-08-22: `-rotation_horizontal` moves WEST and EAST, and
`-rotation_vertical` moves SOUTH and NORTH — the parameters are named for the
ROW AXIS, not the side. The original probe varied PAD_ROTATION_VERTICAL while
watching only WEST and EAST, so it correctly saw nothing change and the wrong
conclusion was drawn. The placer DOES read it; THIS STEP does not implement it.
That is a weaker claim and the true one, and it makes the refusal below MORE
justified rather than less: the value would have had an effect, and we would
not have produced it.

Silently ignoring a declared value is the defect; claiming a variable does
nothing when it does is a different one. So it degrades loudly in BOTH
directions:

    at librelane's default `R0`   — indistinguishable from never having set it
                                    — PROCEED, and carry
                                    `rotation_vertical_not_honoured` in the
                                    report,
                                    with the measurement, in EVERY report
                                    including the skips. A disclosure only
                                    present on the happy path is not one.
    declared non-default          — refuse **rc 2, NOT DETERMINED**, naming the
                                    variable and saying the placer ignores it.
                                    Never rc 0 and never rc 1: "I cannot
                                    honour what you asked" is neither a pass
                                    nor a finding about the design. An author
                                    who sets a knob is entitled to be told the
                                    knob does nothing.

And the DEF carries the orientation the placer ACTUALLY produces on the
vertical sides (`_pad_ring.VERTICAL_SIDE_ORIENT`), not the declared one, so the
footprint a DEF reader derives matches the geometry this step recorded. An
artefact that disagrees with itself is worse than either half alone.

WHAT THIS PROGRAM WILL NOT DO
=============================
It will not invent the config. The variables in `_pad_ring.REQUIRED_VARS` are
upstream's, they name INSTANCES that must already exist in the netlist, and
NOTHING UPSTREAM OF THIS STEP IN THIS FLOW PRODUCES ANY OF THEM. Choosing them
would mean choosing which package pin each signal leaves on — a decision with
a bond diagram behind it — and a plausible guess is indistinguishable in the
artefact from a real pin-out. So when the config is absent this program SKIPs,
exits 2, and its report names the absent variables ONE BY ONE.

WHERE THIS BEATS UPSTREAM
=========================
Their TCL `exit 1`s with a line on stderr and no record. Every refusal here is
a rule id and a message inside `reports/phase3/padring.json` — see
`_pad_ring`'s table of which of their exits became data.

NOT PERFORMED HERE, and said in the artefact rather than left to be noticed:
IO filler placement (upstream's chip flow inserts filler as its own later
step; the gaps are recorded instead, and `fillers_placed` is null and never
0), bond pads, and IO terminals. Each declared-but-unperformed variable is
echoed into the report's `unperformed` block.

EXIT
    0  PASS — a pad ring was placed and written.
    2  SKIP — a required input is absent; the report names it. Non-zero on
       purpose: the flow reads exit 2 as its "could not measure" tier, not as
       a plain pass, and `padring.def` is still an unproduced declared output.
    1  FAIL — an input exists but is not usable, or the declared ring cannot
       be placed on, or abut around, the declared die.

chip-AGNOSTIC: no chip, vendor, SKU, foundry or process-node literal.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _atomic_artefact import write_json as atomic_write_json
from _atomic_artefact import write_text as atomic_write_text

import _pad_ring as PR

PROGRAM = "pad_ring_gen"

#: The answer to "what would have to be declared upstream for this step to do
#: real work". Data, not a log line, so a reader of the report gets it too.
UPSTREAM_DECLARATION_REQUIRED: Tuple[str, ...] = (
    f"A step upstream of 15.5ic must emit `{PR.ASSIGNMENT_REL}` declaring "
    f"every variable in {list(PR.REQUIRED_VARS)}. The names are upstream's, "
    f"so a config that drives their pad placer drives this step unchanged.",
    "(1) PAD_SOUTH / PAD_EAST / PAD_NORTH / PAD_WEST are ordered lists of "
    "INSTANCE names, and upstream resolves each against the block and reads "
    "the master off the instance. So the netlist handed to this step must "
    "already INSTANTIATE the IO cells. This flow's synthesis emits a bare "
    "core; no step instantiates one.",
    "(2) PAD_SITE_NAME / PAD_CORNER_SITE_NAME must name PAD-class SITEs the "
    "PDK declares — in EITHER of the two views a distribution uses: a "
    "top-level SITE record in the IO library's LEFs, or a PAD_FAKE_SITES "
    "entry in the IO library's tech-view config, which is upstream's own PDK "
    "variable for `the LEF does not include the site definitions for the IO "
    "pads`. Measured: only half the IO libraries in the pinned image ship a "
    "LEF SITE record, and the ones that do not declare their sites the other "
    "way. A name declared by neither view is still refused.",
    "(3) PAD_EDGE_SPACING, PAD_ROTATION_HORIZONTAL / _VERTICAL / _CORNER, "
    "PAD_CORNER and PAD_FILLERS complete the geometry. Without a filler the "
    "ring cannot abut, and abutment is what carries its supply.",
    "(4) SIGNAL_MAP is this flow's addition: instance -> the top-level BTerm "
    "that pad brings out. Upstream needs none because it never checks that "
    "every port reached a pad; this step does.",
    "Until those are declared this step has no input, and a ring generated "
    "without them would be an invented pin-out, not a measurement.",
)

#: Which of upstream's `exit 1`s this program renders as data.
UPSTREAM_REFUSALS_MADE_MACHINE_READABLE: Tuple[Tuple[str, str], ...] = (
    ("PAD_CONFIG_VARIABLE_ABSENT", "the TCL aborts on an unset $::env(...)"),
    ("PAD_SITE_NOT_FOUND", '"No pad site <name> found."'),
    ("PAD_SITE_CLASS_NOT_PAD",
     '"Wrong class for pad site <name>: <c> (expected PAD)."'),
    ("PAD_INSTANCE_NOT_IN_BLOCK", '"No instance <name> found."'),
    ("PAD_RING_DOES_NOT_FIT",
     '"Sum of cell widths for <side> is larger than the width of this side."'),
    ("PAD_CORNER_SPACING_NOT_SITE_MULTIPLE",
     '"The remaining area for the pads on the side (<x>) is not divisible by '
     'the minimum site width."'),
)


#: `PAD_ROTATION_VERTICAL` is NOT honoured by this step, and this is the
#: evidence, carried in the report so a reader is told rather than left to find
#: out. It is NOT "inert" — an earlier version of this constant said so and was
#: wrong; see `reason`.
ROTATION_VERTICAL_NOT_HONOURED: Dict[str, Any] = {
    "variable": "PAD_ROTATION_VERTICAL",
    "honoured": False,
    "reason": (
        "this step does not implement it. RE-MEASURED 2026-08-22 in OpenROAD "
        "26Q3-1581, holding one rotation parameter and varying the other while "
        "watching all four sides: `-rotation_horizontal` moves WEST and EAST "
        "(the VERTICAL sides) and `-rotation_vertical` moves SOUTH and NORTH "
        "(the HORIZONTAL sides). The parameters are named for the ROW AXIS, "
        "not the side. The placer therefore DOES honour this variable, on the "
        "N/S rows; this step places N/S at the orientation the placer produces "
        "at librelane's default and implements no other. That is why a "
        "declared non-default is refused rather than ignored: the value would "
        "have had an effect and this step would not have produced it. (The "
        "history of this record's own earlier, wrong claim is in the module "
        "docstring, not here — an artefact field should state what is true "
        "now, not carry a correction a machine has to parse around.)"),
    "measured_orientation": {"W": "MXR90", "E": "R90"},
    "librelane_default": PR.ROTATION_DEFAULT,
    "what_this_step_does": (
        "emits the orientation the placer produces, so the DEF does not "
        "contradict its own geometry. A run that DECLARES a non-default value "
        "is refused NOT_DETERMINED rather than silently ignored — an author "
        "who sets a knob is entitled to be told the knob is not honoured "
        "HERE, which is a different and truer statement than telling them it "
        "does nothing."),
}


#: What this step declares it does NOT do. In the artefact rather than left
#: for a reader to notice, and `fillers_placed` stays null rather than 0.
UNPERFORMED: Dict[str, str] = {
    "io_filler_placement": (
        "not performed by this step — upstream's chip flow inserts filler as "
        "its own later step; the per-gap sizes this ring needs are in "
        "`abutment.gaps`. `fillers_placed` is null, never 0: an absent "
        "placement is not a placement of none"),
}


def _finding(severity: str, rule: str, message: str) -> Dict[str, str]:
    return {"severity": severity, "rule": rule, "message": message}


def _report(verdict: str, reason: str, **kw: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "schema": PR.SCHEMA,
        "program": PROGRAM,
        "verdict": verdict,
        "reason": reason,
        "missing_inputs": [],
        "required_upstream_declaration": list(UPSTREAM_DECLARATION_REQUIRED),
        "upstream_refusals_made_machine_readable": [
            {"rule": r, "upstream_exit_1": m}
            for r, m in UPSTREAM_REFUSALS_MADE_MACHINE_READABLE],
        "config_variables_required": list(PR.REQUIRED_VARS),
        "inputs": {"floorplan_def": None, "pad_assignment": None},
        "io_cell_library": {"resolved": False, "lefs": [], "n_masters": 0,
                            "n_sites": 0, "pad_class_sites": []},
        "config": None,
        "die": None,
        "padring_def": None,
        "pads": [],
        "corners": [],
        "abutment": None,
        "fillers_declared": [],
        "fillers_placed": None,
        "spacing": None,
        "unperformed": dict(UNPERFORMED),
        "rotation_vertical_not_honoured": dict(ROTATION_VERTICAL_NOT_HONOURED),
        "bterms": None,
        "findings": [],
    }
    out.update(kw)
    return out


def _write(project: Path, json_arg: Optional[str],
           report: Dict[str, Any]) -> None:
    dest = Path(json_arg) if json_arg else (project / PR.REPORT_REL)
    if not dest.is_absolute():
        dest = (Path.cwd() / dest).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(dest, report)


def _skip_marker(project: Path, reason: str) -> None:
    """A sibling that says, in the artefact tree, why no DEF is here.

    The step declares `padring.def` as a required output and this branch does
    not produce one — deliberately. The flow reads the step as MISSING, which
    is the honest verdict for a chip whose pad ring was never generated. The
    marker exists so a reader standing in `pnr/` learns why without having to
    find the report.
    """
    dest = project / PR.PADRING_SKIPPED_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(dest, reason.rstrip("\n") + "\n")


# ── placement: upstream's eight steps, in upstream's order ─────────────────
def _place(die: PR.Def, cfg: Dict[str, Any], lib: PR.IoLibrary,
           site_wh: Dict[str, Tuple[int, int]]
           ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]],
                      Dict[str, Any], Dict[str, Dict[str, int]],
                      List[Dict[str, str]]]:
    """Returns (pads, corners, abutment, spacing, findings).

    A finding of severity ERROR means the ring is refused, exactly as
    upstream's `exit 1` refuses it — with the difference that the refusal ends
    up in the report.
    """
    findings: List[Dict[str, str]] = []
    units = die.units
    llx, lly, urx, ury = die.box
    edge = int(round(cfg["edge_spacing_um"] * units))
    site_w, _site_h = site_wh["pad"]
    corner_sw, corner_sh = site_wh["corner"]

    # corners: the declared rotation is the SW corner's; each following
    # corner, going SW -> SE -> NE -> NW, is a further quarter turn clockwise.
    corners: List[Dict[str, Any]] = []
    cmaster = cfg["corner_master"]
    for i, pos in enumerate(PR.CORNER_POSITIONS):
        orient = PR.rotate_cw(cfg["rotation"]["PAD_ROTATION_CORNER"], i)
        dx, dy = PR.footprint(lib.masters[cmaster], orient, units)
        corners.append({
            "instance": f"{cmaster}_{pos}", "master": cmaster,
            "position": pos, "orient": orient,
            "x": (llx + edge) if pos in ("SW", "NW") else (urx - edge - dx),
            "y": (lly + edge) if pos in ("SW", "SE") else (ury - edge - dy),
            "width_dbu": dx, "height_dbu": dy,
        })

    # The vertical sides take the orientation the placer ACTUALLY produces,
    # measured, not the declared one — see `_pad_ring.VERTICAL_SIDE_ORIENT`.
    # `PAD_ROTATION_VERTICAL` does not reach this dict because it does not
    # reach the tool either; `main` refuses before here if a run DECLARED a
    # non-default value, so nobody is silently ignored.
    side_orient = {
        "S": cfg["rotation"]["PAD_ROTATION_HORIZONTAL"],
        "N": PR.rotate_cw(cfg["rotation"]["PAD_ROTATION_HORIZONTAL"], 2),
        "W": PR.VERTICAL_SIDE_ORIENT["W"],
        "E": PR.VERTICAL_SIDE_ORIENT["E"],
    }
    side_width = {
        "S": (urx - llx) - 2 * edge - 2 * corner_sw,
        "N": (urx - llx) - 2 * edge - 2 * corner_sw,
        "E": (ury - lly) - 2 * edge - 2 * corner_sh,
        "W": (ury - lly) - 2 * edge - 2 * corner_sh,
    }

    pads: List[Dict[str, Any]] = []
    spacing: Dict[str, Dict[str, int]] = {}
    for side in PR.SIDES:
        insts = cfg["sides"][side]
        orient = side_orient[side]
        axis = "x" if side in PR.HORIZONTAL_SIDES else "y"
        # 1. sum the pad widths for the side. THE MASTER'S WIDTH, ON EVERY
        #    SIDE — never the oriented footprint's extent.
        #
        #    Upstream measures a cell in exactly two places and both are
        #    `[[$inst getMaster] getWidth]`, for all four sides including the
        #    vertical ones: the fit sum, and the along-the-row step
        #    `cur_pos + space_between_pads_min_filler + $width`. There is no
        #    `getHeight` anywhere in its side arithmetic. The tool agrees when
        #    asked: a vertical-side pad is placed 75 um along the row and
        #    350 um into the die for EVERY value of PAD_ROTATION_VERTICAL.
        #
        #    Taking the ORIENTED extent here summed the master's HEIGHT on a
        #    vertical side whose declared rotation did not swap the axes — a
        #    4.4x error on a real ring (19 x 350 = 6650 against a 1500 um
        #    side), refusing a ring upstream places. This is a correction to
        #    match the tool and upstream, and it is right whichever way it
        #    moves a verdict.
        sizes = [lib.masters[die.components[i].master] for i in insts]
        along = [int(round(w * units)) for w, _h in sizes]
        into = [int(round(h * units)) for _w, h in sizes]
        total = sum(along)
        avail = side_width[side]
        # 2. if that value is larger than the side, throw an error
        if total > avail:
            findings.append(_finding(
                "ERROR", "PAD_RING_DOES_NOT_FIT",
                f"{PR.SIDE_VAR[side]}: the sum of cell widths is {total} DEF "
                f"unit(s) and the side is {avail} — the declared ring is "
                f"{total - avail} unit(s) wider than the declared die"))
            continue
        # 3. subtract
        space_for_fill = avail - total
        n = len(insts)
        if n == 0:
            spacing[side] = {"space_for_fill": space_for_fill,
                             "between": 0, "to_corner": space_for_fill}
            continue
        # 4-5. divide by n+1 and round DOWN to the minimum site width
        between = (space_for_fill // (n + 1) // site_w) * site_w
        # 6-7. the remainder, halved, is the pad-to-corner spacing
        rest = space_for_fill - between * (n - 1)
        to_corner, odd = divmod(rest, 2)
        # 8. refuse a corner spacing that is not a multiple of the site width
        if odd or to_corner % site_w:
            findings.append(_finding(
                "ERROR", "PAD_CORNER_SPACING_NOT_SITE_MULTIPLE",
                f"{PR.SIDE_VAR[side]}: the remaining area for the pads on "
                f"the side is {rest / 2} DEF unit(s), which is not a multiple "
                f"of the minimum site width {site_w} — the gap between the "
                f"corner and the first pad could then not be closed by filler "
                f"cells, and a ring that does not abut carries no supply"))
            continue
        spacing[side] = {"space_for_fill": space_for_fill,
                         "between": between, "to_corner": to_corner}

        cur = (llx if axis == "x" else lly) + to_corner + edge + \
            (corner_sw if axis == "x" else corner_sh)
        for order, (inst, a, i_ext) in enumerate(zip(insts, along, into)):
            if axis == "x":
                x, y = cur, (lly + edge if side == "S" else ury - edge - i_ext)
            else:
                x, y = (llx + edge if side == "W" else urx - edge - i_ext), cur
            pads.append({
                "instance": inst, "master": die.components[inst].master,
                "signal": cfg["signal_map"][inst],
                "side": side, "order": order,
                "x": x, "y": y, "orient": orient,
                "width_dbu": (a if axis == "x" else i_ext),
                "height_dbu": (i_ext if axis == "x" else a),
            })
            cur += between + a

    abut = _abutment(die, pads, corners, cfg, lib)
    if not abut["abuts"]:
        findings.append(_finding(
            "ERROR", "PADRING_DOES_NOT_ABUT",
            f"{len(abut['unfillable'])} gap(s) in the ring cannot be closed "
            f"by the declared filler cell(s) {cfg['fillers']} "
            f"(widths {abut['filler_widths_dbu']} DEF units): "
            f"{abut['unfillable'][:6]} — the ring's power and ground are "
            f"formed by cells TOUCHING, not by routing, so a ring that does "
            f"not abut is electrically nothing"))
    return pads, corners, abut, spacing, findings


def _abutment(die: PR.Def, pads: List[Dict[str, Any]],
              corners: List[Dict[str, Any]], cfg: Dict[str, Any],
              lib: PR.IoLibrary) -> Dict[str, Any]:
    """Walk each side corner->pads->corner and size every gap.

    This is `connect_by_abutment` made checkable: a gap the declared fillers
    cannot tile exactly is a break in the ring's supply.
    """
    units = die.units
    widths = sorted({int(round(lib.masters[f][0] * units))
                     for f in cfg["fillers"] if f in lib.masters})
    by_pos = {c["position"]: c for c in corners}
    ends = {"S": ("SW", "SE"), "N": ("NW", "NE"),
            "W": ("SW", "NW"), "E": ("SE", "NE")}
    gaps: Dict[str, List[int]] = {}
    unfillable: List[str] = []
    for side in PR.SIDES:
        axis = "x" if side in PR.HORIZONTAL_SIDES else "y"
        key, ext = (("x", "width_dbu") if axis == "x"
                    else ("y", "height_dbu"))
        lo, hi = (by_pos[p] for p in ends[side])
        chain = [(lo[key], lo[key] + lo[ext], lo["instance"])]
        chain += sorted(((p[key], p[key] + p[ext], p["instance"])
                         for p in pads if p["side"] == side))
        chain.append((hi[key], hi[key] + hi[ext], hi["instance"]))
        side_gaps: List[int] = []
        for (_a0, a1, an), (b0, _b1, bn) in zip(chain, chain[1:]):
            g = b0 - a1
            side_gaps.append(g)
            if not PR.gap_is_fillable(g, widths):
                unfillable.append(f"{side}:{an}->{bn}={g}")
        gaps[side] = side_gaps
    return {"checked": True, "abuts": not unfillable, "gaps": gaps,
            "unfillable": unfillable, "filler_widths_dbu": widths}


def _emit_def(die: PR.Def, pads: List[Dict[str, Any]],
              corners: List[Dict[str, Any]]) -> str:
    pts = " ".join(f"( {x} {y} )" for x, y in die.diearea)
    rows = [f"- {c['instance']} {c['master']} + FIXED "
            f"( {c['x']} {c['y']} ) {c['orient']} ;" for c in corners]
    rows += [f"- {p['instance']} {p['master']} + FIXED "
             f"( {p['x']} {p['y']} ) {p['orient']} ;" for p in pads]
    return "\n".join([
        "VERSION 5.8 ;", 'DIVIDERCHAR "/" ;', 'BUSBITCHARS "[]" ;',
        f"DESIGN {die.design or 'top'} ;",
        f"UNITS DISTANCE MICRONS {die.units} ;",
        f"DIEAREA {pts} ;", "",
        f"COMPONENTS {len(rows)} ;", *rows, "END COMPONENTS", "",
        "END DESIGN", "",
    ])


# ── main ────────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None,
                    help=f"report destination (default {PR.REPORT_REL})")
    ap.add_argument("--io-lef", action="append", default=None,
                    help="IO cell library LEF; repeatable. Default: probe the "
                         "PDK distribution.")
    ap.add_argument("--pdk-root", default=None)
    ap.add_argument("--pdk", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{PROGRAM}] project dir not found: {project}", file=sys.stderr)
        return 1

    fp_path = project / PR.FLOORPLAN_DEF_REL
    asg_path = project / PR.ASSIGNMENT_REL
    lefs = ([Path(p) for p in args.io_lef] if args.io_lef
            else PR.discover_io_lefs(args.pdk_root, args.pdk))
    # The PDK's TECH view, which is where a distribution whose IO LEFs carry
    # no top-level SITE record declares its pad sites. Discovered from the PDK
    # regardless of `--io-lef`: a caller may hand this step the LEFs it wants
    # the masters read out of, but only the PDK may declare a site.
    site_decls = PR.discover_io_site_declarations(args.pdk_root, args.pdk)
    lib = PR.IoLibrary(lefs, site_decls)

    # ── the SKIP branch: name the absent variables one by one ──────────────
    missing: List[Dict[str, Any]] = []
    if not fp_path.is_file():
        missing.append({"input": "floorplan DEF", "path": PR.FLOORPLAN_DEF_REL})
    if not asg_path.is_file():
        missing.append({"input": "pad ring config", "path": PR.ASSIGNMENT_REL,
                        "variables_absent": list(PR.REQUIRED_VARS)})
    else:
        # THE SPLIT BETWEEN SKIP AND FAIL, stated once. A config file that
        # declares NOTHING is an ABSENT INPUT — the state this flow is in
        # today — and it SKIPs. A config file that declares SOME of the
        # contract is a MALFORMED DECLARATION: somebody wrote it, it is
        # wrong, and it FAILs below with the variable named. Collapsing the
        # two would let a half-written config buy the same exit code as a
        # flow that never had one.
        try:
            raw = json.loads(asg_path.read_text(errors="replace"))
        except (ValueError, OSError):
            raw = None
        if isinstance(raw, dict):
            gone = [v for v in PR.REQUIRED_VARS
                    if raw.get(v) is None or raw.get(v) == ""]
            if len(gone) == len(PR.REQUIRED_VARS):
                missing.append({"input": "pad ring config",
                                "path": PR.ASSIGNMENT_REL,
                                "variables_absent": gone})
    if not lib.resolved:
        missing.append({"input": "PDK IO cell library",
                        "path": "<PDK_ROOT>/<tree>/libs.ref/*io*/lef/*.lef"})

    if missing:
        parts = []
        for m in missing:
            p = f"`{m['path']}` ({m['input']})"
            if m.get("variables_absent"):
                p += (" — every declared variable is absent: "
                      + ", ".join(m["variables_absent"]))
            parts.append(p)
        reason = (
            f"SKIPPED: step 15.5ic has no pad ring to generate because "
            f"{len(missing)} required input(s) are absent: {'; '.join(parts)}. "
            f"This program does not derive a pad ring config: the side "
            f"variables name INSTANCES that must already exist in the "
            f"netlist, and choosing them would mean choosing which package "
            f"pin each signal leaves on. See `required_upstream_declaration` "
            f"in this report."
        )
        rep = _report("SKIP", reason, missing_inputs=missing,
                      io_cell_library=lib.as_dict(),
                      inputs={"floorplan_def": (PR.FLOORPLAN_DEF_REL
                                                if fp_path.is_file() else None),
                              "pad_assignment": (PR.ASSIGNMENT_REL
                                                 if asg_path.is_file() else None)},
                      findings=[_finding("INFO", "REQUIRED_INPUT_ABSENT",
                                         "; ".join(parts))])
        _write(project, args.json, rep)
        _skip_marker(project, reason)
        print(f"=== {PROGRAM} ({project.name}) ===")
        print("  verdict: SKIP")
        for m in missing:
            print(f"  absent input: {m['path']}  ({m['input']})")
            for v in m.get("variables_absent", []):
                print(f"      absent variable: {v}")
        print(f"  no padring.def was written — see {PR.PADRING_SKIPPED_REL} "
              f"and {PR.REPORT_REL}")
        return 2

    inputs = {"floorplan_def": PR.FLOORPLAN_DEF_REL,
              "pad_assignment": PR.ASSIGNMENT_REL}

    def _fail(rule: str, message: str, **kw: Any) -> int:
        rep = _report("FAIL", f"{rule}: {message}", inputs=inputs,
                      io_cell_library=lib.as_dict(),
                      findings=[_finding("ERROR", rule, message)], **kw)
        _write(project, args.json, rep)
        print(f"=== {PROGRAM} ({project.name}) ===")
        print("  verdict: FAIL")
        print(f"  {rule}: {message}")
        return 1

    try:
        die = PR.read_def(fp_path)
    except (PR.DefError, OSError) as exc:
        return _fail("FLOORPLAN_DEF_UNREADABLE",
                     f"{PR.FLOORPLAN_DEF_REL}: {exc}")
    die_rec = {"units": die.units, "diearea": [list(p) for p in die.diearea],
               "box": list(die.box), "n_corners": die.n_die_corners}
    if die.n_die_corners != len(PR.CORNER_POSITIONS):
        # A rectilinear die needs one corner cell per vertex, and the config
        # contract has one PAD_CORNER and four named positions — it cannot
        # express that ring. Refused rather than approximated by a rectangle,
        # which would place metal where the die is not.
        return _fail(
            "DIE_IS_NOT_RECTANGULAR",
            f"{PR.FLOORPLAN_DEF_REL} declares a {die.n_die_corners}-corner "
            f"DIEAREA. This step places a ring with one corner cell per die "
            f"corner and the config contract names {len(PR.CORNER_POSITIONS)} "
            f"positions {list(PR.CORNER_POSITIONS)}, so the declared ring "
            f"does not describe this die",
            die=die_rec)

    try:
        cfg = PR.validate_assignment(json.loads(
            asg_path.read_text(errors="replace")))
    except PR.AssignmentError as exc:
        return _fail(exc.rule, f"{PR.ASSIGNMENT_REL}: {exc.message}",
                     die=die_rec)
    except (ValueError, OSError) as exc:
        return _fail("PAD_CONFIG_MALFORMED",
                     f"{PR.ASSIGNMENT_REL}: {exc}", die=die_rec)

    # ── the declared rotation this step CANNOT honour ─────────────────────
    # rc 2, NOT rc 0 and NOT rc 1. "I cannot honour what you asked" is not a
    # pass and it is not a finding about the design — it is the flow's
    # could-not-measure tier, which is exactly what this is. A run that leaves
    # the variable at librelane's default is indistinguishable from a run that
    # never set it, so it proceeds and is TOLD, in
    # `rotation_vertical_not_honoured`.
    declared_rotv = PR.normalise_orient(
        cfg["rotation"]["PAD_ROTATION_VERTICAL"])
    if declared_rotv != PR.normalise_orient(PR.ROTATION_DEFAULT):
        raw = json.loads(asg_path.read_text(errors="replace")).get(
            "PAD_ROTATION_VERTICAL")
        reason = (
            f"NOT DETERMINED: this run DECLARES PAD_ROTATION_VERTICAL={raw!r}, "
            f"a value other than librelane's default "
            f"{PR.ROTATION_DEFAULT!r}, which this step does not implement. "
            f"{ROTATION_VERTICAL_NOT_HONOURED['reason']} Placing the ring anyway "
            f"would silently give you the orientation you did not ask for, "
            f"and reporting PASS would say the declaration was honoured. "
            f"Neither is true, so no ring is placed and no verdict is claimed. "
            f"Remove the declaration, or set it to {PR.ROTATION_DEFAULT!r}, to "
            f"proceed on the placer's own measured orientation "
            f"({ROTATION_VERTICAL_NOT_HONOURED['measured_orientation']}).")
        rep = _report("SKIP", reason, inputs=inputs,
                      io_cell_library=lib.as_dict(), die=die_rec,
                      missing_inputs=[{
                          "input": "a pad rotation the placer can honour",
                          "path": PR.ASSIGNMENT_REL,
                          "variables_absent": ["PAD_ROTATION_VERTICAL"]}],
                      findings=[_finding(
                          "INFO", "PAD_ROTATION_VERTICAL_NOT_HONOURED",
                          reason)])
        _write(project, args.json, rep)
        _skip_marker(project, reason)
        print(f"=== {PROGRAM} ({project.name}) ===")
        print("  verdict: SKIP (NOT DETERMINED)")
        print(f"  PAD_ROTATION_VERTICAL_NOT_HONOURED: declared {raw!r}, "
              f"placer ignores it")
        return 2

    cfg_rec = {
        "PAD_SITE_NAME": cfg["site"],
        "PAD_CORNER_SITE_NAME": cfg["corner_site"],
        "PAD_EDGE_SPACING": cfg["edge_spacing_um"],
        "PAD_CORNER": cfg["corner_master"],
        "PAD_FILLERS": cfg["fillers"],
        "rotation": cfg["rotation"],
        "pads_per_side": {PR.SIDE_VAR[s]: len(cfg["sides"][s])
                          for s in PR.SIDES},
    }
    # Filled by the site lookups below, so the artefact says which PDK view
    # each of the two sites was resolved from rather than leaving a reader to
    # go and look.
    cfg_rec["site_source"] = {}

    # upstream: the two site lookups, and their two class checks, first.
    #
    # Both PDK views are consulted — see `_pad_ring`'s header. Two IO
    # libraries in one tree declaring one site name at two sizes is refused
    # before either lookup, because the site width is what every gap in the
    # ring is rounded to and picking it by file order would put the ring's
    # abutment on a directory listing.
    if lib.site_declaration_conflicts:
        names = sorted(lib.site_declaration_conflicts)
        return _fail(
            "PAD_SITE_DECLARATION_AMBIGUOUS",
            f"{len(names)} pad site(s) are declared at more than one size by "
            f"the PDK tech views this run resolved: "
            f"{lib.as_dict()['site_declaration_conflicts']} — the site width "
            f"is what the ring's spacing arithmetic rounds to, so this step "
            f"refuses rather than resolve it by the order the files were "
            f"read",
            die=die_rec, config=cfg_rec)
    site_wh: Dict[str, Tuple[int, int]] = {}
    site_src: Dict[str, str] = {}
    for key, name, var in (("pad", cfg["site"], "PAD_SITE_NAME"),
                           ("corner", cfg["corner_site"],
                            "PAD_CORNER_SITE_NAME")):
        site = lib.resolve_site(name)
        if site is None:
            return _fail(
                "PAD_SITE_NOT_FOUND",
                f"{var}={name!r} is declared by neither PDK view this run "
                f"resolved: {len(lib.sites)} LEF SITE record(s) from "
                f"{len(lefs)} LEF(s) and {len(lib.declared_sites)} tech-view "
                f"declaration(s) from {len(lib.site_declarations)} config "
                f"file(s). PAD-class sites available: "
                f"{lib.pad_class_site_names()}",
                die=die_rec, config=cfg_rec)
        site_src[var] = str(site["source"])
        cfg_rec["site_source"] = site_src
        if site["class"] != "PAD":
            return _fail(
                "PAD_SITE_CLASS_NOT_PAD",
                f"{var}={name!r} has CLASS {site['class'] or '(none)'!r}, "
                f"expected PAD",
                die=die_rec, config=cfg_rec)
        if not site["size"]:
            return _fail(
                "PAD_SITE_NOT_FOUND",
                f"{var}={name!r} declares no SIZE, so the minimum site width "
                f"the spacing arithmetic rounds to does not exist",
                die=die_rec, config=cfg_rec)
        site_wh[key] = (int(round(site["size"][0] * die.units)),
                        int(round(site["size"][1] * die.units)))
        if "declared_in" in site:
            site_src[var] += f" ({site['declared_in']})"
    if site_wh["pad"][0] <= 0:
        return _fail("PAD_SITE_NOT_FOUND",
                     f"PAD_SITE_NAME={cfg['site']!r} has width 0, and the "
                     f"spacing arithmetic rounds to it",
                     die=die_rec, config=cfg_rec)

    # upstream: every ordered instance must be IN THE BLOCK.
    not_in_block = [i for i in cfg["instance_side"]
                    if i not in die.components]
    if not_in_block:
        return _fail(
            "PAD_INSTANCE_NOT_IN_BLOCK",
            f"{len(not_in_block)} ordered pad instance(s) are not COMPONENTS "
            f"of {PR.FLOORPLAN_DEF_REL}: {sorted(not_in_block)[:8]} — the "
            f"side variables name instances the netlist must already carry, "
            f"and this step does not create them",
            die=die_rec, config=cfg_rec)

    wanted = sorted({die.components[i].master for i in cfg["instance_side"]}
                    | {cfg["corner_master"]} | set(cfg["fillers"]))
    absent = [m for m in wanted if m not in lib.masters]
    if absent:
        return _fail(
            "PAD_MASTER_NOT_IN_PDK_IO_LIBRARY",
            f"{len(absent)} master(s) are not in the PDK IO cell library this "
            f"run resolved ({len(lib.masters)} master(s) from {len(lefs)} "
            f"LEF(s)): {absent[:8]} — this step places PDK IO cells and does "
            f"not draw pads, so a master it cannot look up is refused rather "
            f"than given an invented footprint",
            die=die_rec, config=cfg_rec)

    pads, corners, abut, spacing, findings = _place(die, cfg, lib, site_wh)
    errors = [f for f in findings if f["severity"] == "ERROR"]
    if errors:
        rep = _report("FAIL", f"{errors[0]['rule']}: {errors[0]['message']}",
                      inputs=inputs, io_cell_library=lib.as_dict(),
                      die=die_rec, config=cfg_rec, pads=pads, corners=corners,
                      abutment=abut, spacing=spacing,
                      fillers_declared=cfg["fillers"], findings=findings)
        _write(project, args.json, rep)
        print(f"=== {PROGRAM} ({project.name}) ===")
        print("  verdict: FAIL")
        for f in errors:
            print(f"  {f['rule']}: {f['message']}")
        return 1

    covered = {p["signal"] for p in pads}
    uncovered = sorted(set(die.pins) - covered)
    bterms = {"total": len(die.pins),
              "covered": len(set(die.pins) & covered),
              "uncovered": uncovered,
              "pad_signals_not_a_floorplan_bterm": sorted(
                  covered - set(die.pins))}
    if uncovered:
        return _fail(
            "BTERM_WITHOUT_PAD",
            f"{len(uncovered)} of {len(die.pins)} floorplan BTerm(s) reach no "
            f"pad: {uncovered[:8]} — once a pad ring exists the pads ARE the "
            f"BTerms, so a port that reaches no pad reaches no package pin. "
            f"Upstream has no analogue of this check",
            die=die_rec, config=cfg_rec, pads=pads, corners=corners,
            abutment=abut, spacing=spacing, bterms=bterms,
            fillers_declared=cfg["fillers"])

    dest = project / PR.PADRING_DEF_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(dest, _emit_def(die, pads, corners))

    notes = list(findings)
    if bterms["pad_signals_not_a_floorplan_bterm"]:
        notes.append(_finding(
            "INFO", "PAD_SIGNAL_NOT_A_FLOORPLAN_BTERM",
            f"{len(bterms['pad_signals_not_a_floorplan_bterm'])} pad "
            f"signal(s) are not PINS in the floorplan DEF: "
            f"{bterms['pad_signals_not_a_floorplan_bterm'][:8]} — supply pads "
            f"legitimately carry a net the DEF need not list as a PIN, so "
            f"this is recorded and not refused"))
    unperformed = dict(UNPERFORMED)
    for var, val in cfg["unperformed"].items():
        unperformed[var] = (f"declared as {val!r} and NOT performed by this "
                            f"step")
    rep = _report(
        "PASS",
        f"placed {len(pads)} pad(s) and {len(corners)} corner cell(s) from "
        f"`{PR.ASSIGNMENT_REL}` onto the die declared by "
        f"`{PR.FLOORPLAN_DEF_REL}`, by upstream's own spacing algorithm; "
        f"every gap in the ring is closable by the declared filler cells",
        inputs=inputs, io_cell_library=lib.as_dict(), die=die_rec,
        config=cfg_rec, padring_def=PR.PADRING_DEF_REL, pads=pads,
        corners=corners, abutment=abut, spacing=spacing,
        fillers_declared=cfg["fillers"],
        unperformed=unperformed, bterms=bterms, findings=notes)
    _write(project, args.json, rep)
    print(f"=== {PROGRAM} ({project.name}) ===")
    print("  verdict: PASS")
    print(f"  pads:    {len(pads)}   corners: {len(corners)}")
    print(f"  abuts:   {abut['abuts']}  (filler widths "
          f"{abut['filler_widths_dbu']} DEF units)")
    print(f"  bterms:  {bterms['covered']}/{bterms['total']} covered")
    print(f"  wrote:   {PR.PADRING_DEF_REL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
