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

    THAT SECOND SOURCE IS THE PROBE WHOSE INFERENCE WAS WRONG, and it is
    left standing because its MEASUREMENT is correct and still supports the
    width claim. What it does NOT support is "the variable is inert" — the
    rows it watched are the ones the OTHER parameter drives. Read the next
    section before drawing anything from it.

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

RE-CONFIRMED INDEPENDENTLY on this commit's own base, not carried forward from
the correction's tree: the same `make_io_sites` -> `place_pad` -> `place_corners`
call shape librelane's `pad_cfg.tcl` uses, one OpenROAD process per (H, V, C)
triple, an open 5V IO cell library with a square corner cell, DEF orientations
read back from odb.

    at the defaults H=V=C=R0     SOUTH R0    NORTH MX    WEST MXR90  EAST R90
    H=R90  (V, C at default)     SOUTH R0    NORTH MX    WEST MX     EAST R180
    H=R180 (V, C at default)     SOUTH R0    NORTH MX    WEST MYR90  EAST R270
    V=R90  (H, C at default)     SOUTH R90   NORTH MYR90 WEST MXR90  EAST R90
    V=R180 (H, C at default)     SOUTH R180  NORTH MY    WEST MXR90  EAST R90
    V=MX   (H, C at default)     SOUTH MX    NORTH R0    WEST MXR90  EAST R90

  H moves W/E only; V moves S/N only. Held in OpenROAD 26Q3-1666, and the
  default row is identical in 26Q3-1535 — so the correction is a property of
  the placer, not of one build.

THIS REPOSITORY ALREADY FORBADE THE INFERENCE, IN WRITING, AND IT WAS MADE
ANYWAY. `metric_constant_across_differing_arms_is_not_measured` states the rule
this probe broke: across arms whose settings PROVABLY DIFFER, an axis holding
one value "is not evidence that the lever does not move it. It is evidence that
the axis was not measured under that lever." The probe ran four differing arms,
watched two of the four sides, saw one value on both, and published the
flattering reading. The rule lives in a metrics gate, so nothing applied it to a
claim about a config knob — but the doctrine is the same and it is older than
this mistake. A no-effect claim is only ever as wide as the set of outputs
observed, and this one was stated four sides wide from a two-side window.

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
    declared non-default          — refuse **rc 2, NOT DETERMINED**, naming
                                    the variable ACTUALLY declared and saying
                                    THIS STEP does not implement it. Never rc 0
                                    and never rc 1: "I cannot honour what you
                                    asked" is neither a pass nor a finding
                                    about the design. An author who sets a knob
                                    is entitled to be told it was not honoured
                                    here — not to be told, falsely, that it
                                    does nothing anywhere.

And the DEF carries the orientation the placer ACTUALLY produces on the
sides (`_pad_ring.SIDE_ORIENT`, all four), not the declared one, so the
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

IT WILL, HOWEVER, ADOPT WHAT THE PDK ALREADY DECLARED. Five of the thirteen
are not the project's to answer: `PAD_SITE_NAME`, `PAD_CORNER_SITE_NAME`,
`PAD_EDGE_SPACING`, `PAD_CORNER` and `PAD_FILLERS` are properties of the IO
CELL LIBRARY, and the PDK declares all five in the same `config.tcl` this step
already opens for `PAD_FAKE_SITES`. Asking an operator for a value that is on
disk is not caution; it is a question with a known answer. So they are adopted
from there via `_pad_ring.apply_pdk_declarations`, with the FILE AND LINE each
came from recorded in `pdk_declarations`, and a project that CONTRADICTS one is
REFUSED by name (`PAD_CONFIG_CONTRADICTS_PDK`) rather than silently overridden
in either direction. THE EIGHT ONLY THE PROJECT CAN ANSWER — the four side
lists, the three rotations, `SIGNAL_MAP` — still SKIP with exit 2, because five
of those eight ARE the pin-out. That is the honest size of the ask, and it was
thirteen.

WHERE THIS BEATS UPSTREAM
=========================
Their TCL `exit 1`s with a line on stderr and no record. Every refusal here is
a rule id and a message inside `reports/phase3/padring.json` — see
`_pad_ring`'s table of which of their exits became data.

`PAD_CORNER_SPACING_NOT_SITE_MULTIPLE` also publishes every positive count
that the same arithmetic says would fit when the declared pads have one
uniform width.  It does not choose one or alter the declaration.  When the
declared pads have different widths, count alone no longer determines their
total width, so the record says `NOT_DETERMINED` instead of inventing a list.

NOT PERFORMED HERE, and said in the artefact rather than left to be noticed:
bond pads and IO terminals. IO filler placement IS performed here because the
canonical flow has no later IO-filler step: the later OpenROAD
`filler_placement` inserts standard-cell row fillers, not PAD-class cells. A
PASS therefore means the emitted DEF contains the declared filler instances
and every adjacent ring cell actually touches.

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
import re
import sys
from math import gcd
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


#: The upstream text this step's arithmetic is PINNED to, checked by
#: `upstream_reimplementation_pin_check`. A citation in a comment is prose a
#: human reads; a pin is a claim a machine can lose.
#:
#: Both defects this step was corrected for were the same shape: our
#: re-derivation and upstream's computation were never compared by anything.
#: The first read one PDK view where upstream reads two; the second took a
#: cell's along-the-row extent from its oriented footprint where upstream takes
#: the master's width. Each anchor below is EXACT TEXT rather than a line
#: number, because a line number drifts and still looks precise.
UPSTREAM_PINS: Tuple[Dict[str, str], ...] = (
    {"upstream": "librelane/scripts/openroad/common/pad_cfg.tcl",
     "anchor": "set width  [expr [[$inst getMaster] getWidth] / $units]",
     "quantity": "a pad's along-the-row extent is its MASTER'S WIDTH",
     "why": "this binding is what makes the two anchors below width-valued. "
            "Without it upstream could rebind the same name to the height and "
            "both of them would still read as present."},
    {"upstream": "librelane/scripts/openroad/common/pad_cfg.tcl",
     "anchor": "incr sum_of_cell_widths $width",
     "quantity": "the per-side FIT SUM is the sum of master widths, on every "
                 "side including the vertical ones",
     "why": "taking the ORIENTED extent here summed the master's height on a "
            "vertical side -- 19 x 350 um against a 1500 um side, refusing a "
            "ring upstream places."},
    {"upstream": "librelane/scripts/openroad/common/pad_cfg.tcl",
     "anchor": "set cur_pos [expr $cur_pos + $space_between_pads_min_filler "
               "+ $width]",
     "quantity": "the ALONG-THE-ROW STEP between adjacent pads is the master's "
                 "width, on every side",
     "why": "the fit sum and the placement step must measure the same "
            "quantity, or a ring that fits is laid out overlapping."},
    {"upstream": "librelane/scripts/openroad/common/io.tcl",
     "anchor": "if { [info exists ::env(PAD_FAKE_SITES)] } {",
     "quantity": "the tech-view site declaration is consumed BEFORE the two "
                 "site lookups, so a site declared there is found",
     "why": "this step read only the LEF view and refused a site the PDK had "
            "declared in the other one. The refusal was about where we looked."},
    {"upstream": "librelane/config/flow.py",
     "anchor": '"PAD_FAKE_SITES",',
     "quantity": "the tech-view declaration is a declared, PDK-scoped variable "
                 "of the same upstream config contract this step borrows",
     "why": "it is a documented part of the contract, not a workaround "
            "somebody left in a PDK tree."},
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


#: Optional package operations this step still does not perform. IO filler
#: placement is deliberately absent from this table: a PASS now materialises
#: those cells in `padring.def` and records every instance.
UNPERFORMED: Dict[str, str] = {}


def _finding(severity: str, rule: str, message: str,
             **extra: Any) -> Dict[str, Any]:
    finding: Dict[str, Any] = {
        "severity": severity, "rule": rule, "message": message,
    }
    finding.update(extra)
    return finding


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
        # What the PDK declared for itself, present on EVERY verdict including
        # the ones reached before the PDK was read. An absent key and an empty
        # one are different facts to a reader diffing two reports, and only
        # the empty one says "this step looked and the PDK declared nothing".
        "pdk_declarations": {"files_read": [], "adopted": {}, "sources": {},
                             "conflicts": {}, "rejected": {},
                             "declarable": list(PR.PDK_DECLARED_VARS)},
        "config": None,
        "die": None,
        "padring_def": None,
        "pads": [],
        "corners": [],
        "fillers": [],
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
def _feasible_uniform_pad_counts(side_available: int, pad_width: int,
                                 site_width: int) -> List[int]:
    """Every positive uniform-pad count that passes steps 1-8.

    This is the same integer arithmetic `_place` applies below, evaluated for
    each count that physically fits.  It is guidance, never a repair: the
    caller still has to declare the actual pad instances and signal map, and
    the original refusal remains blocking until that declaration itself is
    feasible.
    """
    if side_available < 0 or pad_width <= 0 or site_width <= 0:
        return []
    feasible: List[int] = []
    for count in range(1, side_available // pad_width + 1):
        space_for_fill = side_available - count * pad_width
        between = (space_for_fill // (count + 1) // site_width) * site_width
        rest = space_for_fill - between * (count - 1)
        to_corner, odd = divmod(rest, 2)
        if not odd and to_corner % site_width == 0:
            feasible.append(count)
    return feasible


def _place(die: PR.Def, cfg: Dict[str, Any], lib: PR.IoLibrary,
           site_wh: Dict[str, Tuple[int, int]]
           ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]],
                      Dict[str, Any], Dict[str, Dict[str, int]],
                      List[Dict[str, Any]]]:
    """Returns (pads, corners, abutment, spacing, findings).

    A finding of severity ERROR means the ring is refused, exactly as
    upstream's `exit 1` refuses it — with the difference that the refusal ends
    up in the report.
    """
    findings: List[Dict[str, Any]] = []
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
        # MEASURED, not rotated from the declared value: the placer
        # alternates rotation and mirror (R0, MY, R180, MX). A pure
        # rotate_cw walk gave E and W where the tool writes FN and FS.
        orient = PR.CORNER_ORIENT[pos]
        dx, dy = PR.footprint(lib.masters[cmaster], orient, units)
        corners.append({
            "instance": f"{cmaster}_{pos}", "master": cmaster,
            "position": pos, "orient": orient,
            "x": (llx + edge) if pos in ("SW", "NW") else (urx - edge - dx),
            "y": (lly + edge) if pos in ("SW", "SE") else (ury - edge - dy),
            "width_dbu": dx, "height_dbu": dy,
        })

    # The vertical sides take the orientation the placer ACTUALLY produces,
    # measured, not the declared one — see `_pad_ring.SIDE_ORIENT`.
    # `PAD_ROTATION_VERTICAL` does not reach this dict because it does not
    # reach the tool either; `main` refuses before here if a run DECLARED a
    # non-default value, so nobody is silently ignored.
    # ALL FOUR SIDES come from the placer's measured orientation, not from the
    # declared rotation variables. NORTH used to be
    # `rotate_cw(PAD_ROTATION_HORIZONTAL, 2)` -> S at the default, where the
    # placer produces MX -> FS: same bbox, MIRRORED not rotated, so a DEF
    # reader derives different pin positions. Part 3 of the ruling applied to
    # W/E and missed N.
    side_orient = dict(PR.SIDE_ORIENT)
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
        # THE `odd` REFUSAL IS A DELIBERATE DIVERGENCE FROM UPSTREAM. Do not
        # "fix" it back. `pad_cfg.tcl` computes
        #     space_side = round((space_for_fill - filler*(n-1)) / 2 * 1000)/1000
        # in MICRONS, so a remainder that will not halve evenly becomes a
        # fractional micron. This step works in INTEGER DEF UNITS, where that
        # value cannot be expressed: an odd remainder has no halving into two
        # EQUAL gaps, and silently taking the floor would put the ring one DEF
        # unit off-centre with no record of it. Refusing is stricter than the
        # tool this step models, and it is the same rule read in a unit system
        # that cannot round.
        #
        # COMPARED STEP BY STEP against pad_cfg.tcl 2026-08-22 in
        # ghcr.io/vibeic/vibeic-eda:0.3.16: of its eight steps, seven are
        # identical here -- including step 5-6, where this step floors twice and
        # upstream once, which is not a difference because
        # floor(floor(a)/w) == floor(a/w) for integer w. Step 7 is the only
        # divergence and this comment is it.
        # 8. refuse a corner spacing that is not a multiple of the site width
        if odd or to_corner % site_w:
            widths = sorted(set(along))
            guidance_fields: Dict[str, Any] = {
                "current_pad_count": n,
                "side_available_dbu": avail,
                "minimum_site_width_dbu": site_w,
                "declared_pad_widths_dbu": widths,
            }
            if len(widths) == 1 and widths[0] > 0:
                feasible = _feasible_uniform_pad_counts(
                    avail, widths[0], site_w)
                guidance_fields.update({
                    "declared_uniform_pad_width_dbu": widths[0],
                    "feasible_pad_counts": feasible,
                    "feasible_pad_counts_basis": "uniform_declared_pad_width",
                })
                guidance = (
                    f" With the declared side/corner/edge geometry, uniform "
                    f"pad width {widths[0]} DEF unit(s), and site width "
                    f"{site_w}, the feasible positive per-side counts are "
                    f"{feasible}; the current count {n} is not in that set.")
            else:
                guidance_fields.update({
                    "declared_uniform_pad_width_dbu": None,
                    "feasible_pad_counts": None,
                    "feasible_pad_counts_basis": "NOT_DETERMINED",
                    "feasible_pad_counts_reason": (
                        "count alone does not determine total pad width when "
                        "the declared pads have different widths"),
                })
                guidance = (
                    " Feasible per-side counts are NOT DETERMINED from count "
                    f"alone because the declared pads have widths {widths} "
                    "DEF unit(s); changing the count without naming which "
                    "masters remain would guess the total width.")
            findings.append(_finding(
                "ERROR", "PAD_CORNER_SPACING_NOT_SITE_MULTIPLE",
                f"{PR.SIDE_VAR[side]}: the remaining area for the pads on "
                f"the side is {rest / 2} DEF unit(s), which is not a multiple "
                f"of the minimum site width {site_w} — the gap between the "
                f"corner and the first pad could then not be closed by filler "
                f"cells, and a ring that does not abut carries no supply."
                f"{guidance}", **guidance_fields))
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


def _filler_plan(gap: int, master_widths: Dict[str, int]
                 ) -> Optional[List[str]]:
    """Return a deterministic exact tiling of ``gap`` with PAD fillers.

    The boolean coin-problem check is insufficient for a physical result: the
    chosen cells must be named and emitted.  Dijkstra over residues modulo the
    widest filler finds the smallest representable prefix for the target
    residue; the remainder is filled with that widest master.  Runtime is
    bounded by the reduced widest filler, not by die width.
    """
    if gap < 0:
        return None
    if gap == 0:
        return []
    by_width: Dict[int, str] = {}
    for master, width in master_widths.items():
        if width > 0 and width not in by_width:
            by_width[width] = master
    if not by_width:
        return None
    scale = 0
    for width in by_width:
        scale = gcd(scale, width)
    if gap % scale:
        return None
    target = gap // scale
    coins = sorted((width // scale, master)
                   for width, master in by_width.items())
    modulus, widest_master = coins[-1]
    if modulus == 1:
        return [widest_master] * target

    import heapq
    infinity = target + modulus * modulus + 1
    dist = [infinity] * modulus
    prev: List[Optional[Tuple[int, str]]] = [None] * modulus
    dist[0] = 0
    queue = [(0, 0)]
    while queue:
        total, residue = heapq.heappop(queue)
        if total != dist[residue]:
            continue
        for width, master in coins:
            nxt = (residue + width) % modulus
            candidate = total + width
            if candidate < dist[nxt]:
                dist[nxt] = candidate
                prev[nxt] = (residue, master)
                heapq.heappush(queue, (candidate, nxt))
    residue = target % modulus
    if dist[residue] > target:
        return None
    plan: List[str] = []
    while residue:
        step = prev[residue]
        if step is None:
            return None
        residue, master = step
        plan.append(master)
    plan.extend([widest_master] * ((target - dist[target % modulus]) // modulus))
    plan.sort(key=lambda master: (-master_widths[master], master))
    return plan


def _place_fillers(die: PR.Def, pads: List[Dict[str, Any]],
                   corners: List[Dict[str, Any]], cfg: Dict[str, Any],
                   lib: PR.IoLibrary
                   ) -> Tuple[List[Dict[str, Any]], Dict[str, List[int]],
                              List[Dict[str, str]]]:
    """Materialise PAD filler instances in every corner/pad gap."""
    units = die.units
    llx, lly, urx, ury = die.box
    edge = int(round(cfg["edge_spacing_um"] * units))
    master_widths = {
        master: int(round(lib.masters[master][0] * units))
        for master in cfg["fillers"] if master in lib.masters}
    by_pos = {c["position"]: c for c in corners}
    ends = {"S": ("SW", "SE"), "N": ("NW", "NE"),
            "W": ("SW", "NW"), "E": ("SE", "NE")}
    occupied = set(die.components) | {
        str(rec["instance"]) for rec in corners + pads}
    fillers: List[Dict[str, Any]] = []
    findings: List[Dict[str, str]] = []
    residual: Dict[str, List[int]] = {}
    for side in PR.SIDES:
        axis = "x" if side in PR.HORIZONTAL_SIDES else "y"
        key, ext = (("x", "width_dbu") if axis == "x"
                    else ("y", "height_dbu"))
        lo, hi = (by_pos[pos] for pos in ends[side])
        chain = [(lo[key], lo[key] + lo[ext], lo["instance"])]
        chain += sorted((p[key], p[key] + p[ext], p["instance"])
                        for p in pads if p["side"] == side)
        chain.append((hi[key], hi[key] + hi[ext], hi["instance"]))
        chain.sort()
        side_fillers: List[Dict[str, Any]] = []
        for gap_i, ((_a0, a1, an), (b0, _b1, bn)) in enumerate(
                zip(chain, chain[1:])):
            gap = b0 - a1
            plan = _filler_plan(gap, master_widths)
            if plan is None:
                findings.append(_finding(
                    "ERROR", "PADRING_FILLER_PLAN_MISSING",
                    f"side {side}: no exact physical filler plan among the "
                    f"declared master candidates {master_widths!r} for the "
                    f"{gap} DEF unit gap between {an!r} and {bn!r}"))
                continue
            cursor = a1
            for fill_i, master in enumerate(plan):
                orient = PR.SIDE_ORIENT[side]
                width, height = PR.footprint(lib.masters[master], orient,
                                             units)
                along = width if axis == "x" else height
                base = f"vibeic_iofill_{side}_{gap_i}_{fill_i}"
                instance = base
                suffix = 1
                while instance in occupied:
                    instance = f"{base}_{suffix}"
                    suffix += 1
                occupied.add(instance)
                if axis == "x":
                    x = cursor
                    y = lly + edge if side == "S" else ury - edge - height
                else:
                    x = llx + edge if side == "W" else urx - edge - width
                    y = cursor
                rec = {
                    "instance": instance, "master": master, "side": side,
                    "gap_index": gap_i, "order": fill_i,
                    "x": x, "y": y, "orient": orient,
                    "width_dbu": width, "height_dbu": height,
                }
                fillers.append(rec)
                side_fillers.append(rec)
                cursor += along
            if cursor != b0:
                findings.append(_finding(
                    "ERROR", "PADRING_FILLER_PLAN_RESIDUAL",
                    f"side {side}: filler plan for {an!r}->{bn!r} ends at "
                    f"{cursor}, expected {b0} (residual {b0 - cursor})"))

        physical = list(chain)
        physical += [(rec[key], rec[key] + rec[ext], rec["instance"])
                     for rec in side_fillers]
        physical.sort()
        residual[side] = [b0 - a1 for (_a0, a1, _an),
                          (b0, _b1, _bn) in zip(physical, physical[1:])]
    return fillers, residual, findings


def pad_terminal_bterms(pads: List[Dict[str, Any]],
                        pin_ports: Dict[str, Dict[str, List[Any]]],
                        terminals: Dict[str, str],
                        masters_um: Dict[str, Tuple[float, float]],
                        units: int
                        ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Where each padded signal's BTerm BELONGS: on its pad's own terminal.

    THE DECISION THIS IMPLEMENTS. A chip-top IO port IS the pad terminal. The
    flow used to keep the floorplan's die-edge BTerm for a port that a pad now
    drives, and then asked the detailed router to reach it — MEASURED on one
    chip-path run: 38 x `[ERROR DRT-0073] No access point for <pad>/<pin>`,
    detailed routing never completed, `routed.def` carried 567 signal nets and
    no interconnect, and the streamout was 106 bytes. There is no such wire on
    a padframed die: the port net terminates ON the bond pad, under the pad's
    own obstruction, which is exactly why no access point exists. So the BTerm
    is placed COINCIDENT with the pad's terminal rectangle and the router is
    left with the core side of the net, which is the part that is really
    routed.

    THE PIN IS NOT ALWAYS CALLED `PAD`. `terminals` is the PDK's own
    `PAD_PLACE_IO_TERMINALS` map; one open 5 V library presents `ASIG5V` on
    its analog pad. A master absent from it, or a pin absent from the LEF, or
    an orientation `orient_rect` cannot map, moves NOTHING and is reported —
    a BTerm placed where the terminal probably is would be a wire that does
    not exist.

    The largest rectangle of the pin is chosen when a pin has several: it is
    the one an access point is most likely to land in, and choosing by file
    order would choose it silently.
    """
    moves: List[Dict[str, Any]] = []
    notes: List[Dict[str, str]] = []
    for pad in pads:
        master = str(pad["master"])
        signal = str(pad.get("signal") or "")
        if not signal:
            continue
        pin = terminals.get(master)
        if not pin:
            notes.append(_finding(
                "WARNING", "PAD_TERMINAL_PIN_UNDECLARED",
                f"the PDK's PAD_PLACE_IO_TERMINALS does not name a terminal "
                f"for {master}, so {signal!r} keeps the floorplan's own BTerm"))
            continue
        rects = (pin_ports.get(master) or {}).get(pin) or []
        if not rects:
            notes.append(_finding(
                "WARNING", "PAD_TERMINAL_GEOMETRY_ABSENT",
                f"{master} declares terminal {pin} and its LEF carries no "
                f"PORT rectangle for it, so {signal!r} keeps its BTerm"))
            continue
        size = masters_um.get(master)
        if size is None:
            notes.append(_finding(
                "WARNING", "PAD_TERMINAL_MASTER_SIZE_ABSENT",
                f"{master} has no LEF SIZE, so its terminal cannot be placed"))
            continue
        layer, rect = max(
            rects, key=lambda lr: ((lr[1][2] - lr[1][0]) * (lr[1][3] - lr[1][1]),
                                   lr[0]))
        try:
            x1, y1, x2, y2 = PR.orient_rect(rect, str(pad["orient"]), size)
        except KeyError:
            notes.append(_finding(
                "WARNING", "PAD_ORIENTATION_UNMAPPED",
                f"{pad['instance']} is placed {pad['orient']!r}, which this "
                f"step cannot map a terminal rectangle through; {signal!r} "
                f"keeps its BTerm"))
            continue
        ox, oy = int(pad["x"]), int(pad["y"])
        moves.append({
            "signal": signal, "instance": pad["instance"], "master": master,
            "terminal": pin, "layer": layer,
            "origin": [ox, oy],
            # ABSOLUTE, in DEF units. `orient_rect` returns the rectangle in
            # the PLACED cell's own frame, whose lower-left corner is exactly
            # the DEF placement point, so the origin is added here and the
            # entry writes the offsets back out relative to it.
            "rect_dbu": [ox + int(round(x1 * units)), oy + int(round(y1 * units)),
                         ox + int(round(x2 * units)), oy + int(round(y2 * units))],
        })
    return moves, notes


def _pin_entry(header: str, move: Dict[str, Any]) -> str:
    """One DEF PIN entry whose PORT is the pad terminal, FIXED at the pad."""
    ox, oy = move["origin"]
    x1, y1, x2, y2 = move["rect_dbu"]
    return (f"{header}\n"
            f"      + PORT\n"
            f"        + LAYER {move['layer']} "
            f"( {x1 - ox} {y1 - oy} ) ( {x2 - ox} {y2 - oy} )\n"
            f"        + FIXED ( {ox} {oy} ) N ;")


def _rewrite_pins(source_text: str,
                  moves: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    """Re-place the BTerm of every signal a pad drives; leave the rest alone.

    A port NO pad drives keeps the floorplan's die-edge pin byte-for-byte —
    the core-only path has no pad ring and must be untouched by this.
    """
    if not moves:
        return source_text, []
    section = re.search(
        r"(?ms)^(?P<indent>\s*)PINS\s+\d+\s*;(?P<body>.*?)"
        r"^(?P<endindent>\s*)END\s+PINS\b", source_text)
    if section is None:
        raise PR.DefError("floorplan DEF has no PINS section")
    by_signal = {m["signal"]: m for m in moves}
    entries: List[str] = []
    rewritten: List[str] = []
    for raw in section.group("body").split(";"):
        body = raw.strip()
        if not body:
            continue
        m = re.match(r"^-\s+(\S+)", body)
        move = by_signal.get(m.group(1)) if m else None
        if move is None:
            entries.append("    " + body + " ;")
            continue
        header = body.split("+ PORT", 1)[0].rstrip()
        entries.append(_pin_entry("    " + header, move))
        rewritten.append(m.group(1))
    replacement = (f"PINS {len(entries)} ;\n" + "\n".join(entries)
                   + "\nEND PINS")
    return (source_text[:section.start()] + replacement
            + source_text[section.end():]), rewritten


def _emit_def(die: PR.Def, pads: List[Dict[str, Any]],
              corners: List[Dict[str, Any]], fillers: List[Dict[str, Any]],
              source_text: str,
              bterm_moves: Optional[List[Dict[str, Any]]] = None) -> str:
    """Return the complete floorplan DEF with ring placements applied.

    `padring.def` is a routing hand-off, not a placement-only sidecar.  The
    former emitter rebuilt a tiny DEF containing only pad/corner COMPONENTS;
    it silently dropped every standard-cell component, PIN, NET, ROW, TRACK
    and SPECIALNET from `floorplan.def`.  No router could consume that file
    without losing the design.  Preserve every source section byte-for-byte,
    replacing only the named pad COMPONENT entries and adding corner entries.
    """
    section = re.search(
        r"(?ms)^(?P<indent>\s*)COMPONENTS\s+\d+\s*;(?P<body>.*?)"
        r"^(?P<endindent>\s*)END\s+COMPONENTS\b",
        source_text,
    )
    if section is None:
        raise PR.DefError("floorplan DEF has no COMPONENTS section")

    placed = {str(x["instance"]): x for x in corners + pads + fillers}
    entries: List[str] = []
    seen = set()
    for raw in section.group("body").split(";"):
        body = raw.strip()
        if not body:
            continue
        m = re.match(r"^-\s+(\S+)\s+(\S+)\b", body, re.S)
        if m and m.group(1) in placed:
            rec = placed[m.group(1)]
            body = (f"- {rec['instance']} {rec['master']} + FIXED "
                    f"( {rec['x']} {rec['y']} ) {rec['orient']}")
            seen.add(m.group(1))
        entries.append(body + " ;")
    for rec in corners + pads + fillers:
        if rec["instance"] in seen:
            continue
        entries.append(
            f"- {rec['instance']} {rec['master']} + FIXED "
            f"( {rec['x']} {rec['y']} ) {rec['orient']} ;")

    replacement = (f"COMPONENTS {len(entries)} ;\n"
                   + "\n".join(entries)
                   + "\nEND COMPONENTS")
    out = (source_text[:section.start()] + replacement
           + source_text[section.end():])
    out, _moved = _rewrite_pins(out, bterm_moves or [])
    return out


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

    # What the PDK declares for itself. Same discipline as the site table one
    # line up: read from the PDK and nowhere else, `--io-lef` cannot supply it,
    # and the masters the library actually carries are handed in so a
    # declaration naming a cell that is not there is REJECTED here rather than
    # adopted and refused three steps later with the PDK blamed for it.
    decls = PR.PdkDeclarations(
        PR.discover_io_library_configs(args.pdk_root, args.pdk),
        masters=lib.masters)
    pdk_supplied = sorted(decls.values)

    # ── the SKIP branch: name the absent variables one by one ──────────────
    missing: List[Dict[str, Any]] = []
    if not fp_path.is_file():
        missing.append({"input": "floorplan DEF", "path": PR.FLOORPLAN_DEF_REL})
    if not asg_path.is_file():
        # WHAT IS STILL ABSENT IS NOT THE WHOLE CONTRACT. Five of the thirteen
        # are properties of the IO cell library and the PDK declares them in
        # the file this step already opens; listing those five back to an
        # operator as questions to answer is asking for a value that is on
        # disk. What is reported absent is what only the project can answer.
        missing.append({"input": "pad ring config", "path": PR.ASSIGNMENT_REL,
                        "variables_absent": [v for v in PR.REQUIRED_VARS
                                             if v not in decls.values],
                        "variables_from_pdk": pdk_supplied})
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
                # THE SKIP/FAIL SPLIT IS UNCHANGED and is still decided on the
                # PROJECT's own object: a config declaring SOME of the contract
                # is malformed and FAILs below, whether or not the PDK could
                # have supplied the rest. What the PDK declares changes only
                # which variables are REPORTED as still undecided — the
                # difference between telling an operator to answer thirteen
                # questions and telling them to answer the ones only they can.
                missing.append({"input": "pad ring config",
                                "path": PR.ASSIGNMENT_REL,
                                "variables_absent": [v for v in gone
                                                     if v not in decls.values],
                                "variables_from_pdk": pdk_supplied})
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
                      pdk_declarations=decls.as_dict(),
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
            for v in m.get("variables_from_pdk", []):
                print(f"      from PDK:        {v} "
                      f"({decls.sources.get(v)})")
        print(f"  no padring.def was written — see {PR.PADRING_SKIPPED_REL} "
              f"and {PR.REPORT_REL}")
        return 2

    inputs = {"floorplan_def": PR.FLOORPLAN_DEF_REL,
              "pad_assignment": PR.ASSIGNMENT_REL}

    def _fail(rule: str, message: str, **kw: Any) -> int:
        rep = _report("FAIL", f"{rule}: {message}", inputs=inputs,
                      io_cell_library=lib.as_dict(),
                      pdk_declarations=decls.as_dict(),
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
        raw_cfg = json.loads(asg_path.read_text(errors="replace"))
        # ADOPTION HAPPENS BEFORE VALIDATION, and it has to. `PAD_CORNER` left
        # out of the project's config is `PAD_CONFIG_VARIABLE_ABSENT` to
        # `validate_assignment`, so a config the PDK could complete would be
        # refused for a variable the PDK answers. Ordering it the other way
        # would make the adoption unreachable on exactly the configs it exists
        # for. A CONTRADICTION raised here is an `AssignmentError` like any
        # other and lands in the same `_fail` below, with its own rule.
        if isinstance(raw_cfg, dict):
            raw_cfg, adopted_vars = PR.apply_pdk_declarations(raw_cfg, decls)
        else:
            adopted_vars = []
        cfg = PR.validate_assignment(raw_cfg)
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
    # BOTH rotation variables, not just the vertical one. They are named for
    # the ROW AXIS: -rotation_horizontal moves W/E and -rotation_vertical moves
    # S/N. This step implements neither, so a declared non-default on EITHER is
    # refused. Refusing only one of them was an artefact of the probe that
    # measured only one.
    _rot_var = None
    for _v in ("PAD_ROTATION_VERTICAL", "PAD_ROTATION_HORIZONTAL",
               "PAD_ROTATION_CORNER"):
        if PR.normalise_orient(cfg["rotation"][_v]) != PR.normalise_orient(
                PR.ROTATION_DEFAULT):
            _rot_var = _v
            break
    if _rot_var is not None:
        raw = json.loads(asg_path.read_text(errors="replace")).get(_rot_var)
        reason = (
            f"NOT DETERMINED: this run DECLARES {_rot_var}={raw!r}, "
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
                      io_cell_library=lib.as_dict(),
                      pdk_declarations=decls.as_dict(), die=die_rec,
                      missing_inputs=[{
                          "input": "a pad rotation this step implements",
                          "path": PR.ASSIGNMENT_REL,
                          "variables_absent": [_rot_var]}],
                      findings=[_finding(
                          "INFO", f"{_rot_var}_NOT_HONOURED", reason)])
        _write(project, args.json, rep)
        _skip_marker(project, reason)
        print(f"=== {PROGRAM} ({project.name}) ===")
        print("  verdict: SKIP (NOT DETERMINED)")
        # The console line says what the record says. It used to claim the
        # placer disregards the variable, which is false; this line is the
        # half a human reads, so the correction has to reach it too.
        print(f"  {_rot_var}_NOT_HONOURED: declared {raw!r}, "
              f"not implemented by this step")
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
        # Which of the five PDK-scoped variables this run did NOT get from the
        # project. Recorded here, next to the values themselves, and not only
        # in `pdk_declarations`, so a reader of the config block can see that
        # a value came from the PDK without cross-referencing another block.
        # A variable the project declared and the PDK agrees with is NOT here:
        # nothing was adopted, the project's own word stands.
        "adopted_from_pdk": list(adopted_vars),
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
                      pdk_declarations=decls.as_dict(),
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

    fillers, residual_gaps, filler_findings = _place_fillers(
        die, pads, corners, cfg, lib)
    findings.extend(filler_findings)
    abut["planned_gaps"] = abut["gaps"]
    abut["gaps"] = residual_gaps
    abut["abuts"] = not any(
        gap != 0 for gaps in residual_gaps.values() for gap in gaps)
    errors = [f for f in findings if f["severity"] == "ERROR"]
    if errors or not abut["abuts"]:
        if not errors:
            findings.append(_finding(
                "ERROR", "PADRING_DOES_NOT_ABUT",
                "one or more physical gaps remain after IO filler placement"))
            errors = [findings[-1]]
        rep = _report(
            "FAIL", f"{errors[0]['rule']}: {errors[0]['message']}",
            inputs=inputs, io_cell_library=lib.as_dict(),
            pdk_declarations=decls.as_dict(), die=die_rec,
            config=cfg_rec, pads=pads, corners=corners, fillers=fillers,
            abutment=abut, spacing=spacing,
            fillers_declared=cfg["fillers"],
            fillers_placed=len(fillers), findings=findings)
        _write(project, args.json, rep)
        print(f"=== {PROGRAM} ({project.name}) ===")
        print("  verdict: FAIL")
        for finding in errors:
            print(f"  {finding['rule']}: {finding['message']}")
        return 1

    # THE CHIP-TOP IO PORT IS THE PAD TERMINAL — see `pad_terminal_bterms`.
    # Computed from the placed ring and the library's own terminal map, so it
    # is decided here and only here; the deck reads the DEF and no new
    # argument crosses into it.
    pin_ports: Dict[str, Dict[str, List[Any]]] = {}
    for lef in lefs:
        try:
            pin_ports.update(PR.parse_lef_pin_ports(
                Path(lef).read_text(errors="replace")))
        except OSError:
            continue
    corner_master = decls.values.get("PAD_CORNER")
    prefix = (corner_master.split("__", 1)[0] + "__"
              if isinstance(corner_master, str) and "__" in corner_master
              else None)
    bterm_moves, bterm_notes = pad_terminal_bterms(
        pads, pin_ports,
        PR.io_terminals(PR.discover_io_library_configs(
            args.pdk_root, args.pdk), prefix),
        lib.masters, die.units)
    findings.extend(bterm_notes)
    bterms["placed_on_pad_terminal"] = [m["signal"] for m in bterm_moves]
    bterms["kept_at_the_die_edge"] = sorted(
        set(die.pins) - {m["signal"] for m in bterm_moves})

    dest = project / PR.PADRING_DEF_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        routed_input = _emit_def(
            die, pads, corners, fillers,
            fp_path.read_text(errors="replace"), bterm_moves)
    except (PR.DefError, OSError) as exc:
        return _fail(
            "PADRING_ROUTING_HANDOFF_UNWRITABLE",
            f"{PR.FLOORPLAN_DEF_REL}: {exc} — the ring cannot be handed to "
            "routing without preserving the complete floorplan DEF",
            die=die_rec, config=cfg_rec, pads=pads, corners=corners,
            fillers=fillers, fillers_placed=len(fillers),
            abutment=abut, spacing=spacing, bterms=bterms,
            fillers_declared=cfg["fillers"])
    atomic_write_text(dest, routed_input)

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
        f"placed {len(pads)} pad(s), {len(corners)} corner cell(s), and "
        f"{len(fillers)} IO filler cell(s) from "
        f"`{PR.ASSIGNMENT_REL}` onto the die declared by "
        f"`{PR.FLOORPLAN_DEF_REL}`, by upstream's own spacing algorithm; "
        f"every adjacent ring cell physically touches in the emitted DEF",
        inputs=inputs, io_cell_library=lib.as_dict(),
        pdk_declarations=decls.as_dict(), die=die_rec,
        config=cfg_rec, padring_def=PR.PADRING_DEF_REL, pads=pads,
        corners=corners, fillers=fillers, abutment=abut, spacing=spacing,
        fillers_declared=cfg["fillers"],
        fillers_placed=len(fillers),
        unperformed=unperformed, bterms=bterms, findings=notes)
    _write(project, args.json, rep)
    print(f"=== {PROGRAM} ({project.name}) ===")
    print("  verdict: PASS")
    print(f"  pads:    {len(pads)}   corners: {len(corners)}")
    print(f"  fillers: {len(fillers)}")
    print(f"  abuts:   {abut['abuts']}  (filler widths "
          f"{abut['filler_widths_dbu']} DEF units)")
    print(f"  bterms:  {bterms['covered']}/{bterms['total']} covered")
    if adopted_vars:
        print(f"  from PDK: {', '.join(adopted_vars)}")
        for v in adopted_vars:
            print(f"      {v} = {cfg_rec.get(v)!r}  ({decls.sources.get(v)})")
    print(f"  wrote:   {PR.PADRING_DEF_REL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
