#!/usr/bin/env python3
"""_pad_ring — the pad-ring step's shared vocabulary: the CONFIG CONTRACT it
borrows from upstream, DEF/LEF reading, and the IO-cell-library probe.

WHERE THIS COMES FROM
=====================
Read out of the pinned image on 2026-08-20, not remembered:
`librelane/steps/openroad.py` (the pad-ring step class) and
`librelane/scripts/openroad/pad.tcl` + `common/pad_cfg.tcl` (where the
engineering actually is). What is borrowed is the SHAPE, and three things in
particular:

  1. THE CONFIG CONTRACT IS DECLARED AND NOTHING IS INFERRED. Upstream's pad
     placer reads a fixed set of variables and errors out on any one of them
     it cannot resolve. So does this. The variable names below are theirs,
     verbatim, so that a project that can drive their flow can drive this step
     and a reader can carry one config between the two.
  2. THE ALGORITHM IS WRITTEN DOWN BEFORE IT IS CODED. Their eight numbered
     steps are reproduced in `pad_ring_gen`, in their order, including the two
     that are REFUSALS.
  3. EVERY GEOMETRIC PRECONDITION THAT CAN BE VIOLATED HAS AN EXPLICIT EXIT.
     Their TCL has no warn-and-continue anywhere; neither does this.

WHERE WE GO FURTHER, AND WHY
============================
Their TCL `exit 1`s with a line on stderr and leaves no record. Six of their
refusals become MACHINE-READABLE here — a rule id and a message inside
`reports/phase3/padring.json` — so a refusal is a datum a later step can read
instead of a line in a log somebody has to still have:

    upstream `exit 1`                                   this rule
    ------------------------------------------------   -------------------------
    "No pad site <name> found."                         PAD_SITE_NOT_FOUND
    "Wrong class for pad site <name>: <c> (expected     PAD_SITE_CLASS_NOT_PAD
     PAD)."
    "No instance <name> found."                         PAD_INSTANCE_NOT_IN_BLOCK
    "Sum of cell widths for <side> is larger than the   PAD_RING_DOES_NOT_FIT
     width of this side."
    "The remaining area for the pads on the side (<x>)  PAD_CORNER_SPACING_NOT_SITE_MULTIPLE
     is not divisible by the minimum site width."
    (unset config variable -> TCL aborts on $::env)     PAD_CONFIG_VARIABLE_ABSENT

and two checks are OURS because upstream has no analogue:

    PADRING_DOES_NOT_ABUT   their `connect_by_abutment` forms the ring's
                            power/ground by cells TOUCHING — the supply is not
                            routed. A ring that places correctly and does not
                            abut is electrically nothing, and no placement
                            check notices. The abutment precondition is that
                            every gap in the ring walk be fillable by the
                            declared filler cells, which is exactly what their
                            "round down to the minimum site width" and their
                            corner-spacing refusal exist to guarantee. We
                            check the guarantee on the artefact.
    BTERM_WITHOUT_PAD       once a pad ring exists the pads ARE the design's
                            BTerms — upstream's chip flow deletes IO placement
                            outright saying so. Nothing upstream then checks
                            that every top-level port actually reached a pad.
    PAD_SITE_DECLARATION_AMBIGUOUS
                            a PDK tree may ship more than one IO library, and
                            each declares its own `PAD_FAKE_SITES`. Upstream
                            reads ONE library's config, so it never sees two.
                            This step discovers them, so it can, and two
                            declarations of one site name at two different
                            sizes is refused rather than resolved by file
                            order — the site width is what the whole spacing
                            arithmetic rounds to.

WHERE A PAD SITE IS DECLARED — TWO PDK VIEWS, NOT ONE
=====================================================
MEASURED 2026-08-22 in the current image, and this is the defect this module
was carrying: the IO cell library's LEFs may contain NO top-level `SITE`
declaration at all. On the one open PDK checked exhaustively, all 15 IO cell
LEFs carry only the `SITE <name> ;` REFERENCE form inside a MACRO — a name,
not a declaration. The distribution declares the site in its TECH view:

    <root>/<tree>/libs.tech/<flow>/<io library>/config.tcl
        set ::env(PAD_SITE_NAME)        "<name>"
        set ::env(PAD_CORNER_SITE_NAME) "<corner name>"
        # Note: This is needed if site definition are not in LEF
        dict set ::env(PAD_FAKE_SITES) "<name>" "<width_um>, <height_um>"

`PAD_FAKE_SITES` is upstream's own PDK-scoped variable — "A dict of fake pad
sites and their width and height tuple. Use this if the LEF does not include
the site definitions for the IO pads." — and upstream's placer consumes it
BEFORE its two site lookups, calling `make_fake_io_site` once per entry. This
module names 12 of upstream's 20 PDK-scoped `PAD_*` variables — the 8 geometric
ones in the contract above, the 3 it records as UNPERFORMED, and `PAD_FAKE_SITES`
itself, which this change adds. BEFORE this change it named 11 and omitted this
one; that is the whole defect, stated as a count. (RE-MEASURED 2026-08-22 by
counting `Variable("PAD_…")` in upstream's `pad_variables`: 20, not the 14 an
earlier draft of this paragraph asserted from our own `REQUIRED_VARS` count
without checking theirs. The 11/12 pair is measured the same way, on the
pre-fix and post-fix trees. Two tests in `test_pad_ring.py` keep this
paragraph honest: one checks its arithmetic closes, the other re-derives the
count from upstream's own `pad_variables` -- grep them for `header`.)
The other 8 it omits are file lists — LEFs, GDS, libs, CDLs, SPICE and
Verilog models — and bondpad dimensions, none of which this step performs.
`PAD_FAKE_SITES` is the one omission that cost anything: on every
distribution that declares its sites that way, the first lookup refused
`PAD_SITE_NOT_FOUND` against a PDK that had in fact declared the site.

MEASURED, not assumed, what the created site is: driving
`make_fake_io_site -name X -width W -height H` against a real tech LEF and
dumping the database yields `SITE X class=PAD w=W h=H` in a library the tool
names `FAKE_IO`. So a PDK-declared site is CLASS PAD carrying exactly the
declared size, and honouring the declaration does not weaken
`PAD_SITE_CLASS_NOT_PAD` — it is what the tool the check models does.

A DECLARATION IS STILL NOT AN INVENTION. Only the PDK may declare a site: this
module reads `PAD_FAKE_SITES` out of a PDK file and nowhere else. A project's
`pad_assignment.json` cannot declare one, there is no default size anywhere in
this file, and a site named by neither view is still `PAD_SITE_NOT_FOUND`.

THE CONFIG CONTRACT
===================
`phase3/stage3/pnr/pad_assignment.json`, one key per upstream variable:

    PAD_SOUTH / PAD_EAST / PAD_NORTH / PAD_WEST
        ordered lists of INSTANCE names. Instances, not signals and not cell
        types: upstream resolves each against the block and reads the master
        off the instance, so the pads must ALREADY EXIST in the netlist.
    PAD_SITE_NAME / PAD_CORNER_SITE_NAME
        SITE names in the IO library. Both must exist and both must be
        `CLASS PAD`.
    PAD_EDGE_SPACING              microns, die edge to the IO row.
    PAD_ROTATION_HORIZONTAL       orientation of the SOUTH row; the NORTH row
    PAD_ROTATION_VERTICAL         is its half turn. Likewise WEST -> EAST.
    PAD_ROTATION_CORNER           orientation of the SW corner; each following
                                  corner, going SW -> SE -> NE -> NW, is a
                                  further quarter turn clockwise. Stated here
                                  because it is a DERIVATION from a declared
                                  value, with a rule, and not a guess.
    PAD_CORNER                    the corner cell MASTER. Upstream's
                                  `place_corners` instantiates it; so does
                                  this, naming the instances `<master>_<POS>`.
    PAD_FILLERS                   filler cell masters.
    PAD_BONDPAD_NAME              optional, and NOT PLACED by this step.
    PAD_BONDPAD_OFFSETS           optional, and NOT PLACED by this step.
    PAD_PLACE_IO_TERMINALS        optional, and NOT PLACED by this step.
    SIGNAL_MAP                    OURS, and required here: instance -> the
                                  top-level BTerm that pad brings out.
                                  Upstream needs no such map because it never
                                  checks BTerm coverage. We do, so we need it.

NOTHING IN THIS FILE DERIVES AN ASSIGNMENT. MEASURED on this tree (grep over
`programs/`, `flow/`, `skills/` for a producer of any variable above): 0 hits.
The nearest artefact that exists is a per-signal SIDE table, and a side table
is not an assignment — it names no instance, fixes no order within a side,
declares no site, no rotation, no corner and no filler. The flow's synthesis
emits a bare core; no step instantiates an IO cell. So `pad_ring_gen` SKIPs,
naming the variables it went without, one by one.

THE IO CELL LIBRARY — FOUND, NOT DRAWN
======================================
Located by the layout convention PDK DISTRIBUTIONS use —
`<root>/<tree>/libs.ref/<library whose name carries the io token>/lef/*.lef` —
never by naming a process, a foundry or a library. RE-MEASURED 2026-08-22 by
sweeping every PDK tree the pinned image ships (names withheld; this is a
count, not an inventory):

    7 trees swept
    4 carry an IO cell library; 3 carry none
    of the 4, 2 declare their pad sites as LEF SITE records
             and 2 declare them in the TECH view, via `PAD_FAKE_SITES`
    0 declare them in neither, and 0 declare one site at two sizes

The count that was here before was right and the conclusion drawn from it was
not. It read: "only 2 ship the PAD-class SITE records ... the other 2 ship
masters and no site", and concluded "on half the IO libraries in the image,
upstream's own placer would exit 1 on its first lookup."

IT WOULD NOT. Upstream creates those sites from `PAD_FAKE_SITES` before its
first lookup ever runs, which is exactly what those 2 distributions declare and
what this module had not been reading. The libraries are not siteless; they
declare their sites in the other view and say so in a comment. That mistaken
sentence is what kept `PAD_SITE_NOT_FOUND` firing against PDKs that had
declared the site, so it is corrected here rather than deleted — the wrong
inference is the more useful record.

`PAD_SITE_NOT_FOUND` remains a real branch, on its true grounds: a site name
that NEITHER view declares. The sweep above is the standing evidence that it
fires on no real PDK in the image.

chip-AGNOSTIC: no chip, vendor, SKU, foundry, library or process-node literal.
The only fixed strings are DEF/LEF keywords, upstream's variable names, the
distribution path convention, and this flow's own relative paths.
"""
from __future__ import annotations

import os
import re
from math import gcd
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ── this step's slots in the flow tree ──────────────────────────────────────
FLOORPLAN_DEF_REL = "phase3/stage3/pnr/floorplan.def"
PADRING_DEF_REL = "phase3/stage3/pnr/padring.def"
PADRING_SKIPPED_REL = "phase3/stage3/pnr/padring.SKIPPED.txt"
REPORT_REL = "reports/phase3/padring.json"
#: WHAT THIS MODULE MIRRORS FROM UPSTREAM, AND WHAT PINS IT THERE
#:
#: The docstring above says this module borrows upstream's shape — its variable
#: names verbatim, its eight numbered steps in their order. A borrowing stated
#: only in prose drifts silently: the along-the-row extent was taken from the
#: ORIENTED footprint here while upstream measures the MASTER, and on a real
#: ring that was a 4.4x error that surfaced as an unrelated refusal. Our side of
#: that invariant is pinned (`test_a_vertical_side_sums_the_master_width_not_
#: its_height`). THEIRS WAS NOT, so an upstream change would land here as a
#: divergence nothing asks about.
#:
#: `pinned_by` names a test that reads the UPSTREAM artefact. It is machine-
#: readable so `upstream_mirror_is_pinned_check` can require it rather than
#: trust that somebody wrote one.
UPSTREAM_MIRROR: Dict[str, str] = {
    "upstream": "librelane/scripts/openroad/common/pad_cfg.tcl",
    "mirrors": (
        "the per-side pad arithmetic: the fit sum and the along-the-row step. "
        "Upstream measures a cell in exactly two places and BOTH read the "
        "master's width, on all four sides; there is no getHeight anywhere in "
        "its side arithmetic."),
    "pinned_by": (
        "tests/test_upstream_mirror_pad_cfg.py"
        "::test_upstream_side_arithmetic_measures_the_master_width"),
}


ASSIGNMENT_REL = "phase3/stage3/pnr/pad_assignment.json"

SCHEMA = "vibe-ic/padring/1"
VERDICTS: Tuple[str, ...] = ("PASS", "SKIP", "FAIL")

#: An `absent_condition_reason`-grade disclosure. The flow refuses a skip
#: reason shorter than this on a gate CLAUSE; a skip a PROGRAM writes is the
#: same promise and is held to the same bar.
MIN_REASON_CHARS = 40

SIDES: Tuple[str, ...] = ("S", "E", "N", "W")           # upstream's order
CORNER_POSITIONS: Tuple[str, ...] = ("SW", "SE", "NE", "NW")


#: Upstream's variable name for each side.
SIDE_VAR = {"S": "PAD_SOUTH", "E": "PAD_EAST",
            "N": "PAD_NORTH", "W": "PAD_WEST"}
HORIZONTAL_SIDES = ("S", "N")
VERTICAL_SIDES = ("E", "W")

#: Every variable a run must declare. Absence of any one is
#: `PAD_CONFIG_VARIABLE_ABSENT` — upstream's TCL aborts on the unset `$::env`.
REQUIRED_VARS: Tuple[str, ...] = (
    "PAD_SOUTH", "PAD_EAST", "PAD_NORTH", "PAD_WEST",
    "PAD_SITE_NAME", "PAD_CORNER_SITE_NAME",
    "PAD_EDGE_SPACING",
    "PAD_ROTATION_HORIZONTAL", "PAD_ROTATION_VERTICAL", "PAD_ROTATION_CORNER",
    "PAD_CORNER", "PAD_FILLERS",
    "SIGNAL_MAP",
)

#: Declared, honoured by upstream, and NOT PERFORMED by this step. Recorded so
#: the omission is in the artefact rather than left for a reader to notice.
UNPERFORMED_VARS: Tuple[str, ...] = (
    "PAD_BONDPAD_NAME", "PAD_BONDPAD_OFFSETS", "PAD_PLACE_IO_TERMINALS",
)

# The distribution convention the IO library is found by. `libs.ref` is the
# reference-view directory every open PDK distribution in the pinned image
# uses; `io` is the generic word for the cell class, not a name.
_LIBS_REF = "libs.ref"
_IO_LIB_TOKEN = "io"

# The TECH view the same distributions declare a pad SITE in, when their LEFs
# do not. `libs.tech` is the reference-view directory's sibling every open PDK
# in the pinned image ships; the flow directory under it is not named here —
# every one is scanned, and only a file that actually declares the upstream
# variable contributes anything.
_LIBS_TECH = "libs.tech"
_SITE_DECL_FILE = "config.tcl"


# ── orientations ────────────────────────────────────────────────────────────
#: The placer's spelling -> the DEF spelling. Both are accepted on input so a
#: config written for upstream is readable here unchanged.
ORIENT_ALIASES = {
    "R0": "N", "R90": "W", "R180": "S", "R270": "E",
    "MY": "FN", "MYR90": "FE", "MX": "FS", "MXR90": "FW",
}
DEF_ORIENTS: Tuple[str, ...] = ("N", "S", "E", "W", "FN", "FS", "FE", "FW")

#: One quarter turn CLOCKWISE. Unmirrored cells walk N->E->S->W; mirrored ones
#: walk FN->FW->FS->FE, because a mirror reverses the sense of a rotation.
_CW90 = {"N": "E", "E": "S", "S": "W", "W": "N",
         "FN": "FW", "FW": "FS", "FS": "FE", "FE": "FN"}

#: Orientations whose footprint is the master's SIZE with the axes swapped.
_ROTATED = ("E", "W", "FE", "FW")

#: What the placer ACTUALLY orients a pad to ON EVERY SIDE, in DEF spelling.
#:
#: RE-MEASURED 2026-08-22, OpenROAD 26Q3-1581, at librelane's default rotations,
#: all four sides observed in one process and cross-checked by holding one
#: rotation parameter and varying the other:
#:
#:     SOUTH R0    -> N        WEST  MXR90 -> FW
#:     NORTH MX    -> FS       EAST  R90   -> W
#:
#: THE NORTH ENTRY IS THE CORRECTION. This step used to compute NORTH as
#: `rotate_cw(PAD_ROTATION_HORIZONTAL, 2)`, which at the default yields S
#: (R180). The placer produces MX -> FS. Same bounding box, MIRRORED rather
#: than rotated, so a DEF reader deriving pin positions gets a different cell.
#: Part 3 of the flow owner's ruling -- "the DEF must not contradict itself,
#: write the orientation the tool actually produces" -- was applied to the
#: vertical sides and missed here.
#:
#: RE-CONFIRMED on a SECOND build before landing, because a value carried
#: forward under the word "measured" is what produced the claim this file
#: exists to correct: identical in OpenROAD 26Q3-1666, and the default row
#: identical again in 26Q3-1535. Three builds, one answer -- a property of the
#: placer, not of one release.
#:
#: AND IT IS RE-DERIVABLE, WHICH THE ORIGINAL CLAIM WAS NOT. In
#: `tests/test_pad_ring.py`, the test named
#:     test_the_shipped_orientations_are_what_the_placer_produces
#: runs upstream's own call shape against whatever IO library is installed and
#: compares the tool's answer with this dict. Change a value here without the
#: placer agreeing and that test says so, in the tool's own words.
SIDE_ORIENT: Dict[str, str] = {
    "S": ORIENT_ALIASES["R0"],
    "N": ORIENT_ALIASES["MX"],
    "W": ORIENT_ALIASES["MXR90"],
    "E": ORIENT_ALIASES["R90"],
}

#: What the placer ACTUALLY orients each CORNER to, in DEF spelling, at
#: librelane's default `PAD_ROTATION_CORNER`.
#:
#: MEASURED 2026-08-22, OpenROAD 26Q3-1581, `place_corners` after
#: `make_io_sites -rotation_corner R0`:
#:
#:     SW  R0   -> N        NE  R180 -> S
#:     SE  MY   -> FN       NW  MX   -> FS
#:
#: THE PLACER ALTERNATES ROTATION AND MIRROR: R0, MY, R180, MX. This step used
#: to walk `rotate_cw(PAD_ROTATION_CORNER, i)` -- N, E, S, W -- a PURE
#: ROTATION, so SE and NW were wrong: E where the tool writes FN, W where it
#: writes FS. Same bounding box for a square corner cell, mirrored rather than
#: rotated, so the fit arithmetic cannot see it and a DEF reader can. Two of
#: four corners, in every ring this step has ever written.
#:
#: Re-confirmed on 26Q3-1666 before landing, and re-derived on every run of
#: the placer test named above -- which fails on THIS dict alone, with the
#: sides left correct, so the corner half cannot hide behind them.
CORNER_ORIENT: Dict[str, str] = {
    "SW": ORIENT_ALIASES["R0"],
    "SE": ORIENT_ALIASES["MY"],
    "NE": ORIENT_ALIASES["R180"],
    "NW": ORIENT_ALIASES["MX"],
}

#: librelane's declared default for all three pad rotations
#: (`librelane/config/flow.py`, `default="R0"` on each). A run whose config
#: carries this value is indistinguishable from a run that set nothing, which
#: is exactly how it should be treated.
ROTATION_DEFAULT = "R0"


def normalise_orient(token: object) -> Optional[str]:
    """A DEF orientation, from either spelling, or None if unrecognised."""
    t = str(token or "").strip().upper()
    t = ORIENT_ALIASES.get(t, t)
    return t if t in DEF_ORIENTS else None


def rotate_cw(orient: str, quarters: int) -> str:
    for _ in range(quarters % 4):
        orient = _CW90[orient]
    return orient


def footprint(size_um: Tuple[float, float], orient: str,
              units: int) -> Tuple[int, int]:
    """A master's footprint on the die, in DEF units, once oriented."""
    w = int(round(size_um[0] * units))
    h = int(round(size_um[1] * units))
    return (h, w) if orient in _ROTATED else (w, h)


# ── DEF ─────────────────────────────────────────────────────────────────────
_UNITS_RE = re.compile(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", re.M)
_DIEAREA_RE = re.compile(r"^\s*DIEAREA\s+(.*?);", re.M | re.S)
_POINT_RE = re.compile(r"\(\s*(-?\d+)\s+(-?\d+)\s*\)")
_COMPONENT_RE = re.compile(r"^-\s+(?P<inst>\S+)\s+(?P<master>\S+)\b(?P<tail>.*)$",
                           re.S)
_PLACEMENT_RE = re.compile(
    r"\+\s*(?P<status>PLACED|FIXED|COVER|UNPLACED)"
    r"(?:\s*\(\s*(?P<x>-?\d+)\s+(?P<y>-?\d+)\s*\)\s*(?P<orient>\w+))?")


class DefError(ValueError):
    """The DEF could not be read as a DEF. Never swallowed into a verdict."""


class Component:
    __slots__ = ("instance", "master", "status", "x", "y", "orient")

    def __init__(self, instance, master, status, x, y, orient):
        self.instance, self.master, self.status = instance, master, status
        self.x, self.y, self.orient = x, y, orient

    @property
    def placed(self) -> bool:
        return (self.status in ("PLACED", "FIXED", "COVER")
                and self.x is not None and self.y is not None)

    def as_dict(self) -> Dict[str, object]:
        return {"instance": self.instance, "master": self.master,
                "status": self.status, "x": self.x, "y": self.y,
                "orient": self.orient}


class Def:
    """The four DEF facts this step needs, and nothing else."""

    def __init__(self, units, diearea, components, pins, design):
        self.units = units
        self.diearea = diearea
        self.components = components
        self.pins = pins
        self.design = design

    @property
    def box(self) -> Tuple[int, int, int, int]:
        xs = [p[0] for p in self.diearea]
        ys = [p[1] for p in self.diearea]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def n_die_corners(self) -> int:
        """Corner cells a ring on THIS die needs.

        A DEF states a rectangular die as two points and a rectilinear one as
        its vertices. Derived from the die the run declares, never a constant.
        """
        return 4 if len(self.diearea) == 2 else len(self.diearea)


def _section(text: str, name: str) -> str:
    start = re.search(rf"^\s*{name}\s+\d+\s*;", text, re.M)
    if not start:
        return ""
    end = re.search(rf"^\s*END\s+{name}\b", text[start.end():], re.M)
    return (text[start.end():start.end() + end.start()] if end
            else text[start.end():])


def parse_def(text: str) -> Def:
    """Parse the DEF facts this step uses. Raises `DefError` on a non-DEF."""
    m_units = _UNITS_RE.search(text)
    if not m_units:
        raise DefError("no `UNITS DISTANCE MICRONS` record")
    m_die = _DIEAREA_RE.search(text)
    if not m_die:
        raise DefError("no `DIEAREA` record")
    pts = [(int(a), int(b)) for a, b in _POINT_RE.findall(m_die.group(1))]
    if len(pts) < 2:
        raise DefError(f"`DIEAREA` declares {len(pts)} point(s), needs >= 2")

    components: Dict[str, Component] = {}
    for entry in _section(text, "COMPONENTS").split(";"):
        entry = entry.strip()
        if not entry.startswith("-"):
            continue
        m = _COMPONENT_RE.match(entry)
        if not m:
            continue
        pl = _PLACEMENT_RE.search(m.group("tail"))
        components[m.group("inst")] = Component(
            m.group("inst"), m.group("master"),
            pl.group("status") if pl else "UNPLACED",
            int(pl.group("x")) if pl and pl.group("x") else None,
            int(pl.group("y")) if pl and pl.group("y") else None,
            pl.group("orient") if pl else None)

    pins: List[str] = []
    for entry in _section(text, "PINS").split(";"):
        entry = entry.strip()
        if entry.startswith("-") and entry[1:].split():
            pins.append(entry[1:].split()[0])

    m_design = re.search(r"^\s*DESIGN\s+(\S+)\s*;", text, re.M)
    return Def(int(m_units.group(1)), pts, components, pins,
               m_design.group(1) if m_design else None)


def read_def(path: Path) -> Def:
    return parse_def(path.read_text(errors="replace"))


def nearest_side(cx: float, cy: float,
                 box: Tuple[int, int, int, int]) -> str:
    """Which die edge a point sits nearest. Ties resolve S > E > N > W.

    The only geometric claim the gate makes about a placed pad, and it is made
    from the pad's CENTRE — an origin-based answer would call every cell in
    the ring `S` or `W`, because a DEF origin is a cell's lower-left corner.
    """
    llx, lly, urx, ury = box
    d = {"N": abs(ury - cy), "E": abs(urx - cx),
         "S": abs(cy - lly), "W": abs(cx - llx)}
    return min(SIDES, key=lambda s: (d[s], SIDES.index(s)))


# ── LEF ─────────────────────────────────────────────────────────────────────
_MACRO_RE = re.compile(r"^\s*MACRO\s+(\S+)", re.M)
_SITE_DECL_RE = re.compile(r"^\s*SITE\s+(\S+)\s*$", re.M)
_SIZE_RE = re.compile(r"^\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;", re.M)
_CLASS_RE = re.compile(r"^\s*CLASS\s+([A-Za-z_]+)", re.M)


def parse_lef_macros(text: str) -> Dict[str, Tuple[float, float]]:
    """`{macro: (width_um, height_um)}` for every MACRO carrying a SIZE."""
    out: Dict[str, Tuple[float, float]] = {}
    hits = list(_MACRO_RE.finditer(text))
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        # Bound the body at this macro's own END. Without it a SITE declared
        # between two MACROs would lend the first macro its SIZE.
        stop = re.compile(rf"^\s*END\s+{re.escape(m.group(1))}\b",
                          re.M).search(text, m.end(), end)
        if stop:
            end = stop.start()
        s = _SIZE_RE.search(text, m.end(), end)
        if s:
            out[m.group(1)] = (float(s.group(1)), float(s.group(2)))
    return out


def parse_lef_sites(text: str) -> Dict[str, Dict[str, object]]:
    """`{site: {"class": str, "size": (w_um, h_um)}}` for standalone SITEs.

    Only the top-level `SITE <name>` declaration form is read; the `SITE
    <name> ;` reference inside a MACRO names a site, it does not declare one.
    """
    out: Dict[str, Dict[str, object]] = {}
    hits = list(_SITE_DECL_RE.finditer(text))
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        body = text[m.end():end]
        stop = re.search(rf"^\s*END\s+{re.escape(m.group(1))}\b", body, re.M)
        if stop:
            body = body[:stop.start()]
        s = _SIZE_RE.search(body)
        c = _CLASS_RE.search(body)
        out[m.group(1)] = {
            "class": (c.group(1).upper() if c else ""),
            "size": ((float(s.group(1)), float(s.group(2))) if s else None),
        }
    return out


#: `dict set ::env(PAD_FAKE_SITES) "<site>" "<width_um>, <height_um>"`, the
#: one form the distributions in the image write. Both the quoted and the
#: braced Tcl word forms are accepted because both are the same Tcl word.
_FAKE_SITE_RE = re.compile(
    r"^[^\S\n]*dict\s+set\s+::env\(\s*PAD_FAKE_SITES\s*\)\s+"
    r"(?P<q1>[\"{])(?P<name>[^\"}\s]+)[\"}]\s+"
    r"(?P<q2>[\"{])\s*(?P<w>[0-9]+(?:\.[0-9]*)?)\s*,"
    r"\s*(?P<h>[0-9]+(?:\.[0-9]*)?)\s*[\"}]",
    re.M)


def parse_pad_site_declarations(text: str) -> Dict[str, Tuple[float, float]]:
    """`{site: (width_um, height_um)}` for every `PAD_FAKE_SITES` entry.

    Upstream's own PDK variable, read verbatim. A file that declares none
    contributes nothing — absence is reported by absence, never by a size this
    function chose.
    """
    out: Dict[str, Tuple[float, float]] = {}
    for m in _FAKE_SITE_RE.finditer(text):
        out[m.group("name")] = (float(m.group("w")), float(m.group("h")))
    return out


def _pdk_trees(pdk_root: Optional[str] = None,
               pdk: Optional[str] = None) -> List[Path]:
    """The PDK trees a run may read from, or an empty list for NOT RESOLVED."""
    root_s = pdk_root if pdk_root is not None else os.environ.get("PDK_ROOT")
    if not root_s:
        return []
    root = Path(root_s)
    if not root.is_dir():
        return []
    name = pdk if pdk is not None else os.environ.get("PDK")
    if name:
        # A NAMED tree that does not resolve is NOT RESOLVED. Falling back to
        # "then scan every tree in the root" was measured to turn a bad name
        # into a 130-master table drawn from six unrelated processes, which
        # would have corroborated a master no run could ever have used.
        tree = root / name
        return [tree] if tree.is_dir() else []
    return sorted(p for p in root.iterdir() if p.is_dir())


def discover_io_lefs(pdk_root: Optional[str] = None,
                     pdk: Optional[str] = None) -> List[Path]:
    """Locate the PDK's IO cell library LEFs by distribution convention.

    An empty list means NOT RESOLVED. That is reported as a state of its own
    rather than returned as an empty master table: an empty table and an
    absent library are different facts, and a pad whose master cannot be
    looked up has not been shown to be a PDK cell rather than a drawn one.
    """
    lefs: List[Path] = []
    for tree in _pdk_trees(pdk_root, pdk):
        ref = tree / _LIBS_REF
        if not ref.is_dir():
            continue
        for lib in sorted(ref.iterdir()):
            if lib.is_dir() and _IO_LIB_TOKEN in lib.name.lower():
                lefs.extend(sorted((lib / "lef").glob("*.lef")))
    return lefs


def discover_io_site_declarations(pdk_root: Optional[str] = None,
                                  pdk: Optional[str] = None) -> List[Path]:
    """Locate the PDK TECH-view files that DECLARE a pad site.

    The sibling of `discover_io_lefs`, and it exists because the LEF view is
    not the only place a distribution declares a pad SITE — see this module's
    header. Same tree resolution, same `io` token on the library directory,
    and only files that actually name upstream's variable are returned, so a
    tree that declares nothing yields an empty list rather than a file whose
    contents would have to be interpreted.
    """
    found: List[Path] = []
    for tree in _pdk_trees(pdk_root, pdk):
        tech = tree / _LIBS_TECH
        if not tech.is_dir():
            continue
        for flow in sorted(p for p in tech.iterdir() if p.is_dir()):
            for lib in sorted(p for p in flow.iterdir() if p.is_dir()):
                if _IO_LIB_TOKEN not in lib.name.lower():
                    continue
                cfg = lib / _SITE_DECL_FILE
                if not cfg.is_file():
                    continue
                try:
                    text = cfg.read_text(errors="replace")
                except OSError:
                    continue
                if parse_pad_site_declarations(text):
                    found.append(cfg)
    return found


#: `set ::env(<VAR>) "<value>"` in a PDK TECH-view config, with Tcl's
#: backslash line continuation. A COMMENTED line is not a declaration, so the
#: pattern is anchored to the start of the line with only whitespace before
#: `set` — upstream's own file carries five commented `set ::env(PAD_*)` lines
#: and reading one of them would put a variable into a config the PDK
#: deliberately left unset.
_PAD_ENV_RE = re.compile(
    r"^[ \t]*set[ \t]+::env\((?P<var>PAD_[A-Z_0-9]+)\)[ \t]+"
    r"\"(?P<value>(?:[^\"\\]|\\.)*)\"",
    re.M | re.S)


#: A Tcl substitution — `$name`, `$::env(...)`, or a `[...]` command. MEASURED
#: in the pinned image: one open PDK writes its corner master as
#: `"$::env(PAD_CELL_LIBRARY)__cor"`. That string is not a cell name; only Tcl
#: knows what it becomes. Copying it into a config would put a master no
#: library carries into an artefact that reads like a real one, so a value
#: carrying a substitution is NOT a literal declaration and this parser does
#: not return one — see `parse_pad_env_unresolved`, which returns exactly those
#: so the omission is reportable instead of silent.
_TCL_SUBST_RE = re.compile(r"[$\[]")


def _pad_env_matches(text: str):
    for m in _PAD_ENV_RE.finditer(text):
        # Tcl's line continuation inside a quoted string: backslash-newline
        # plus the run of whitespace that follows it is one separator.
        value = re.sub(r"\\\s*\n\s*", " ", m.group("value")).strip()
        yield m.group("var"), value, text.count("\n", 0, m.start()) + 1


def parse_pad_env_declarations(text: str) -> Dict[str, Tuple[str, int]]:
    """`{variable: (value, line number)}` for every `set ::env(PAD_*)` a PDK
    TECH-view config declares as a LITERAL string.

    The line number is carried so a value can be cited to the file and line
    that states it rather than asserted. A variable this file does not declare
    is ABSENT from the mapping — there is no default here; a `dict create`
    form (upstream's own spelling for a table, not a scalar) declares no scalar
    and is not returned; and neither is a value carrying a Tcl substitution.
    """
    return {var: (value, line) for var, value, line in _pad_env_matches(text)
            if not _TCL_SUBST_RE.search(value)}


def parse_pad_env_unresolved(text: str) -> Dict[str, Tuple[str, int]]:
    """The declarations `parse_pad_env_declarations` LEFT OUT because their
    value carries a Tcl substitution this program cannot expand.

    Returned so a caller can say "the PDK declares this variable in terms I
    cannot resolve" instead of the variable simply going missing. An unread
    declaration and an absent one are different facts.
    """
    return {var: (value, line) for var, value, line in _pad_env_matches(text)
            if _TCL_SUBST_RE.search(value)}


def discover_io_library_configs(pdk_root: Optional[str] = None,
                                pdk: Optional[str] = None) -> List[Path]:
    """Locate every PDK TECH-view config that DECLARES a pad variable.

    The sibling of `discover_io_site_declarations`, and it differs in exactly
    one way: that one returns files declaring a SITE, this one returns files
    declaring ANY `PAD_*` scalar, because a distribution may state the
    orientation convention and the corner master in a file that declares no
    fake site. Same tree resolution and same `io` token on the library
    directory; a tree that declares nothing yields an empty list.
    """
    found: List[Path] = []
    for tree in _pdk_trees(pdk_root, pdk):
        tech = tree / _LIBS_TECH
        if not tech.is_dir():
            continue
        for flow in sorted(p for p in tech.iterdir() if p.is_dir()):
            for lib in sorted(p for p in flow.iterdir() if p.is_dir()):
                if _IO_LIB_TOKEN not in lib.name.lower():
                    continue
                cfg = lib / _SITE_DECL_FILE
                if not cfg.is_file():
                    continue
                try:
                    text = cfg.read_text(errors="replace")
                except OSError:
                    continue
                if (parse_pad_env_declarations(text)
                        or parse_pad_env_unresolved(text)):
                    found.append(cfg)
    return found


# ── the PDK-adoption layer ──────────────────────────────────────────────────
#: The five variables of `REQUIRED_VARS` that are properties of the IO CELL
#: LIBRARY rather than of the project: the two site names, the corner and
#: filler MASTERS, and the die-edge-to-IO-row distance. Every one of them is
#: answered by the same `libs.tech/*/*io*/config.tcl` this module already opens
#: for `PAD_FAKE_SITES` — `parse_pad_env_declarations` returns them today and
#: nothing consumed them, so the file transcribed two of the answers into its
#: own header and still asked an operator for all five.
#:
#: THE DOCTRINE IS THE ONE THIS MODULE ALREADY STATES FOR SITES, unchanged:
#: only the PDK may declare these, they are read out of a PDK file and nowhere
#: else, and there is no default for any of them anywhere in this file. What
#: is added is that a declaration is USED rather than transcribed, and that a
#: project CONTRADICTING one is REFUSED instead of silently preferred.
#:
#: WHAT IS DELIBERATELY NOT HERE is the other eight: the four side lists, the
#: three rotations and `SIGNAL_MAP`. Five of those eight ARE the package
#: pin-out, and a pin-out this program chose would be indistinguishable in the
#: artefact from one somebody decided. They stay the caller's SKIP branch.
#:
#: The three rotations are the near miss and are excluded on their own
#: grounds: `pad_assignment_gen.PDK_DELEGATED_VARS` DOES delegate them, because
#: that program answers "what did the design's documents leave to the PDK" for
#: a config it then WRITES. This tuple answers a different question — "what may
#: this step adopt into a config somebody else wrote" — and a rotation adopted
#: here would be adopted into a step that has measured it cannot honour a
#: non-default one (see `SIDE_ORIENT`). `PDK_DECLARED_VARS` is therefore a
#: strict subset of `PDK_DELEGATED_VARS`, and
#: `test_the_adoption_set_is_a_subset_of_what_the_generator_delegates` says so
#: rather than leaving the two tuples to drift.
PDK_DECLARED_VARS: Tuple[str, ...] = (
    "PAD_SITE_NAME", "PAD_CORNER_SITE_NAME", "PAD_EDGE_SPACING",
    "PAD_CORNER", "PAD_FILLERS",
)

#: Variables upstream spells as one whitespace-separated Tcl word and this
#: flow's config contract spells as a list. Splitting on whitespace is a
#: TRANSCRIPTION between two file formats; no element is added, dropped or
#: reordered.
PDK_LIST_VARS: Tuple[str, ...] = ("PAD_FILLERS",)

#: The ONE Tcl substitution resolved here, and the reason it can be: upstream
#: sets `PAD_CELL_LIBRARY` to the library whose config it is loading, so the
#: expansion is the name of the DIRECTORY the file sits in — read off the
#: path, not guessed. MEASURED in the pinned image: one open PDK writes its
#: corner master as `"$::env(PAD_CELL_LIBRARY)__cor"`, which
#: `parse_pad_env_declarations` correctly refuses to return as a literal and
#: `parse_pad_env_unresolved` hands over instead.
#:
#: Anything ELSE still carrying a `$` or a `[` after this one expansion is NOT
#: adopted. It is recorded in `rejected` with the raw text, because "the PDK
#: said nothing" and "the PDK said something this step could not expand" are
#: different facts and only the second one names a file to go and read.
_CELL_LIB_REF = "$::env(PAD_CELL_LIBRARY)"


def _pdk_library_name(cfg: Path) -> str:
    """The IO cell library a TECH-view config belongs to: its directory.

    `discover_io_library_configs` finds these at
    `<tree>/libs.tech/<flow>/<library>/config.tcl` and matches the `io` token
    on `<library>`, so the parent directory IS the library name — the same
    string upstream's `PAD_CELL_LIBRARY` holds while it loads that file.
    """
    return cfg.parent.name


def _coerce_declared(var: str, value: str) -> object:
    return [tok for tok in value.split() if tok] if var in PDK_LIST_VARS \
        else value


class PdkDeclarations:
    """What the PDK itself declares for `PDK_DECLARED_VARS`, and what it did
    not get to declare.

    Built on this module's EXISTING parser — `parse_pad_env_declarations` for
    the literals and `parse_pad_env_unresolved` for the values carrying a Tcl
    substitution — so there is exactly one `set ::env(PAD_*)` reader in this
    file and the line number that reader already carries is used, rather than
    a second parser that would have to be kept agreeing with the first.

    Four states, kept apart because they are four different facts:

        values      adopted — one PDK file declared it, resolvably
        sources     `<file>:<line>` each adopted value came from. The LINE is
                    carried because a config.tcl declares six variables and a
                    reader sent to the file still has to find the one that
                    was read
        conflicts   two IO libraries declared it differently. NOT adopted:
                    resolving that by directory order would pick a master or a
                    spacing out of a directory listing, which is the same
                    error `site_declaration_conflicts` refuses one level down
        rejected    declared, but not usable — a substitution this module does
                    not expand, or a master name the IO library does not
                    carry. Recorded WITH its reason rather than dropped
    """

    def __init__(self, files: Sequence[Path] = (),
                 masters: Optional[Dict[str, Tuple[float, float]]] = None):
        self.files: List[Path] = list(files)
        self.values: Dict[str, object] = {}
        self.sources: Dict[str, str] = {}
        self.conflicts: Dict[str, List[Dict[str, object]]] = {}
        self.rejected: Dict[str, str] = {}
        self.files_read: List[str] = []

        for cfg in self.files:
            try:
                text = cfg.read_text(errors="replace")
            except OSError:
                continue
            self.files_read.append(str(cfg))
            for var, value, line in self._candidates(cfg, text):
                self._offer(cfg, var, value, line, masters)

    # -- reading -----------------------------------------------------------
    def _candidates(self, cfg: Path, text: str):
        """`(var, coerced value, line)` for every `PDK_DECLARED_VARS` entry
        this file resolvably declares; the unresolvable ones go to `rejected`
        on the way past."""
        literals = parse_pad_env_declarations(text)
        for var in PDK_DECLARED_VARS:
            if var in literals:
                raw, line = literals[var]
                if raw:
                    yield var, _coerce_declared(var, raw), line
                continue
            unresolved = parse_pad_env_unresolved(text).get(var)
            if unresolved is None:
                continue                       # absent: reported by absence
            raw, line = unresolved
            expanded = raw.replace(_CELL_LIB_REF, _pdk_library_name(cfg))
            if _TCL_SUBST_RE.search(expanded):
                self.rejected[var] = (
                    f"declared in {cfg}:{line} as {raw!r}, whose value still "
                    f"carries a Tcl substitution after the one expansion this "
                    f"step performs — only Tcl knows what it becomes, and a "
                    f"master name with a '$' in it would be looked up, not "
                    f"found, and refused three steps later with the PDK "
                    f"blamed for it")
                continue
            yield var, _coerce_declared(var, expanded), line

    def _offer(self, cfg: Path, var: str, value: object, line: int,
               masters: Optional[Dict[str, Tuple[float, float]]]) -> None:
        if masters is not None and var in ("PAD_CORNER", "PAD_FILLERS"):
            named = ([value] if isinstance(value, str)
                     else list(value))  # type: ignore[arg-type]
            unknown = [m for m in named if m not in masters]
            if unknown:
                self.rejected[var] = (
                    f"declared in {cfg}:{line} as {value!r}, but the IO cell "
                    f"library carries no master named "
                    f"{', '.join(repr(u) for u in unknown)} — a declaration "
                    f"this step cannot resolve to a cell is not adopted")
                return
        source = f"{cfg}:{line}"
        if var in self.conflicts:
            self.conflicts[var].append({"value": value, "declared_in": source})
            return
        if var not in self.values:
            self.values[var] = value
            self.sources[var] = source
            return
        if self.values[var] != value:
            # Two IO libraries, two answers. NEITHER is adopted.
            self.conflicts[var] = [
                {"value": self.values[var],
                 "declared_in": self.sources[var]},
                {"value": value, "declared_in": source}]
            self.values.pop(var, None)
            self.sources.pop(var, None)

    # -- reporting ---------------------------------------------------------
    def as_dict(self) -> Dict[str, object]:
        return {"files_read": list(self.files_read),
                "adopted": {k: self.values[k] for k in sorted(self.values)},
                "sources": {k: self.sources[k] for k in sorted(self.sources)},
                "conflicts": {k: self.conflicts[k]
                              for k in sorted(self.conflicts)},
                "rejected": {k: self.rejected[k]
                             for k in sorted(self.rejected)},
                "declarable": list(PDK_DECLARED_VARS)}


#: A site the PDK's TECH view declares is CLASS PAD. Not a preference:
#: MEASURED by driving `make_fake_io_site` and dumping the database — see this
#: module's header. Named so the constant carries the reason.
DECLARED_SITE_CLASS = "PAD"

#: Which PDK view a resolved site came from. Carried into the artefact so a
#: reader can tell a site that was READ from one that was DECLARED.
SITE_SOURCE_LEF = "libs.ref LEF SITE declaration"
SITE_SOURCE_DECLARED = "libs.tech PAD_FAKE_SITES declaration"


class IoLibrary:
    """The masters an IO cell library ships and the PAD-class sites the PDK
    declares for it — across BOTH views the distributions use.

    `sites` stays exactly what it was: the LEF view. `declared_sites` is the
    tech view. `resolve_site` is the only lookup callers should use, and it
    prefers the LEF, which carries real geometry, over a declaration.
    """

    def __init__(self, lefs: Sequence[Path],
                 site_declarations: Sequence[Path] = ()):
        self.lefs = list(lefs)
        self.masters: Dict[str, Tuple[float, float]] = {}
        self.sites: Dict[str, Dict[str, object]] = {}
        for lef in self.lefs:
            try:
                text = lef.read_text(errors="replace")
            except OSError:
                continue
            self.masters.update(parse_lef_macros(text))
            self.sites.update(parse_lef_sites(text))

        self.site_declarations = list(site_declarations)
        self.declared_sites: Dict[str, Dict[str, object]] = {}
        #: site -> the differing declarations found for it. A PDK tree may
        #: ship more than one IO library; upstream reads one config and never
        #: sees a second, so this disagreement is ours to refuse. Resolving it
        #: by file order would pick the site width the whole spacing
        #: arithmetic rounds to out of a directory listing.
        self.site_declaration_conflicts: Dict[str, List[Dict[str, object]]] = {}
        for cfg in self.site_declarations:
            try:
                text = cfg.read_text(errors="replace")
            except OSError:
                continue
            for name, size in parse_pad_site_declarations(text).items():
                rec = {"class": DECLARED_SITE_CLASS, "size": size,
                       "declared_in": str(cfg)}
                prev = self.declared_sites.get(name)
                if prev is None:
                    self.declared_sites[name] = rec
                elif tuple(prev["size"] or ()) != size:      # type: ignore[arg-type]
                    self.site_declaration_conflicts.setdefault(
                        name, [dict(prev)]).append(rec)

    @property
    def resolved(self) -> bool:
        return bool(self.masters)

    def resolve_site(self, name: str) -> Optional[Dict[str, object]]:
        """The site `name`, from whichever PDK view declares it, or None.

        LEF first: where a library ships a real SITE record that record is the
        geometry, and a declaration alongside it would be the redundant copy.
        """
        site = self.sites.get(name)
        if site is not None:
            return {"class": site["class"], "size": site["size"],
                    "source": SITE_SOURCE_LEF}
        declared = self.declared_sites.get(name)
        if declared is not None:
            return {"class": declared["class"], "size": declared["size"],
                    "source": SITE_SOURCE_DECLARED,
                    "declared_in": declared["declared_in"]}
        return None

    def pad_class_site_names(self) -> List[str]:
        """Every PAD-class site this run can resolve, from either view."""
        return sorted(
            {n for n, s in self.sites.items() if s["class"] == "PAD"}
            | set(self.declared_sites))

    def as_dict(self) -> Dict[str, object]:
        return {"resolved": self.resolved,
                "lefs": [str(p) for p in self.lefs],
                "n_masters": len(self.masters),
                "n_sites": len(self.sites),
                "pad_class_sites": sorted(
                    n for n, s in self.sites.items() if s["class"] == "PAD"),
                "site_declarations": [str(p) for p in self.site_declarations],
                "n_declared_sites": len(self.declared_sites),
                "declared_pad_class_sites": sorted(self.declared_sites),
                "pad_class_sites_resolvable": self.pad_class_site_names(),
                "site_declaration_conflicts": {
                    n: [dict(r, size=list(r["size"])) for r in recs]
                    for n, recs in self.site_declaration_conflicts.items()}}


# ── abutment ────────────────────────────────────────────────────────────────
def gap_is_fillable(gap: int, filler_widths: Sequence[int]) -> bool:
    """Can `gap` DEF units be tiled exactly by the declared filler cells?

    This is the executable form of `connect_by_abutment`: the ring's supply is
    not routed, it is formed by cells touching, so a gap no filler set can
    close is a ring that is electrically nothing. A zero gap already abuts.

    Exact for any filler set: a non-negative integer combination of the widths
    exists only if the gap is a multiple of their gcd, and for gaps below the
    conductor bound the combination is searched for outright.
    """
    if gap < 0:
        return False
    if gap == 0:
        return True
    widths = sorted({w for w in filler_widths if w > 0})
    if not widths:
        return False
    g = 0
    for w in widths:
        g = gcd(g, w)
    if gap % g:
        return False
    # Reduce by the gcd first. A ring whose only filler is one site wide then
    # answers in one modulo instead of a million-entry table, and the search
    # below runs on the reduced problem, which is the same problem.
    gap //= g
    widths = sorted({w // g for w in widths})
    if len(widths) == 1:
        return gap % widths[0] == 0
    # Above `max(w)**2` every value is representable (the Frobenius bound for
    # a two-element set, which upper-bounds any superset containing it), so
    # the search only ever runs on the small remainder.
    if gap > max(widths) ** 2:
        return True
    reach = [False] * (gap + 1)
    reach[0] = True
    for i in range(1, gap + 1):
        for w in widths:
            if w <= i and reach[i - w]:
                reach[i] = True
                break
    return reach[gap]


# ── the config contract ─────────────────────────────────────────────────────
class AssignmentError(ValueError):
    """The declared config is not the declared contract."""

    def __init__(self, rule: str, message: str):
        super().__init__(message)
        self.rule = rule
        self.message = message


#: How a project value and a PDK declaration are compared, PER VARIABLE. Not
#: one rule for all five, because the five are not one kind of thing:
#: `PAD_EDGE_SPACING` is a NUMBER written as a string, so "26", 26 and 26.0 are
#: one declaration and refusing a project for the spelling would be refusing it
#: for nothing; `PAD_FILLERS` is a SET of masters whose declaration order is
#: the greedy order `gap_is_fillable` chooses for itself anyway. Everything
#: else is a name, and a name is itself.
def _declarations_agree(var: str, project: object, pdk: object) -> bool:
    if var == "PAD_EDGE_SPACING":
        try:
            return float(project) == float(pdk)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return str(project).strip() == str(pdk).strip()
    if var in PDK_LIST_VARS:
        if isinstance(project, str):
            project = project.split()
        if not isinstance(project, (list, tuple)):
            return False
        pdk_list = (pdk.split() if isinstance(pdk, str)
                    else list(pdk))  # type: ignore[arg-type]
        return set(map(str, project)) == set(map(str, pdk_list))
    return str(project).strip() == str(pdk).strip()


def apply_pdk_declarations(
        obj: Dict[str, object],
        decls: "PdkDeclarations") -> Tuple[Dict[str, object], List[str]]:
    """Fill the PDK-declared variables the project left out, and REFUSE the
    ones it contradicts. Returns `(merged config, adopted variable names)`.

    The whole doctrine, in three lines of behaviour:

      * the project said NOTHING and the PDK declared it -> ADOPTED, with the
        file and line recorded in the report. Not an invention: the value came
        out of a PDK file and there is no default for it anywhere in this
        module.
      * the project said the SAME thing -> left exactly as the project wrote
        it, and NOT counted as adopted. A project is not overwritten by a value
        it already agrees with, and a report that called that an adoption would
        overstate what the PDK supplied.
      * the project said something ELSE -> `PAD_CONFIG_CONTRADICTS_PDK`.

    The third is the one that pays. Before this, `PAD_EDGE_SPACING` was checked
    only for being a non-negative number of microns, so a project could declare
    a spacing the PDK contradicts, place a ring on it, and find out at the
    shuttle's pad-mask stage — a refusal several steps and one gate away from
    the two numbers that disagree, with nothing in any artefact naming them.

    A variable in `decls.conflicts` or `decls.rejected` is in NEITHER branch:
    it was not adopted, so there is nothing to fill and nothing to contradict.
    That is deliberate. Refusing a project against a declaration this step
    itself declined to resolve would charge the project for the PDK's
    ambiguity.
    """
    merged = dict(obj)
    adopted: List[str] = []
    for var in PDK_DECLARED_VARS:
        if var not in decls.values:
            continue
        declared = decls.values[var]
        have = merged.get(var)
        if have is None or have == "" or have == []:
            merged[var] = declared
            adopted.append(var)
            continue
        if not _declarations_agree(var, have, declared):
            raise AssignmentError(
                "PAD_CONFIG_CONTRADICTS_PDK",
                f"{var}={have!r} contradicts the PDK's own declaration "
                f"{declared!r} in {decls.sources.get(var)} — this variable is "
                f"a property of the IO cell library, not of the project, and "
                f"a ring placed on the project's value would be refused by "
                f"the shuttle against the library's")
    return merged, adopted


def validate_assignment(obj: object) -> Dict[str, object]:
    """Refuse anything the contract does not fully declare.

    Every refusal here is a MALFORMED DECLARATION, not an absent one: the
    project said it had a config. Absence is the caller's SKIP branch and
    never reaches this function.
    """
    if not isinstance(obj, dict):
        raise AssignmentError("PAD_CONFIG_MALFORMED",
                              "the pad config is not a JSON object")
    absent = [v for v in REQUIRED_VARS
              if obj.get(v) is None or obj.get(v) == ""]
    if absent:
        raise AssignmentError(
            "PAD_CONFIG_VARIABLE_ABSENT",
            f"{len(absent)} required config variable(s) are not declared: "
            f"{absent} — upstream's placer aborts on the first unset one, and "
            f"a value this program invented would be a pin-out nobody chose")

    seen: Dict[str, str] = {}
    for side in SIDES:
        var = SIDE_VAR[side]
        insts = obj[var]
        if not isinstance(insts, list):
            raise AssignmentError(
                "PAD_SIDE_NOT_A_LIST",
                f"{var} is {type(insts).__name__}, not an ordered list of "
                f"instance names")
        for inst in insts:
            if not isinstance(inst, str) or not inst.strip():
                raise AssignmentError(
                    "PAD_SIDE_NOT_A_LIST",
                    f"{var} holds an entry that is not an instance name: "
                    f"{inst!r}")
            if inst in seen:
                raise AssignmentError(
                    "PAD_INSTANCE_DUPLICATED",
                    f"instance {inst!r} is ordered on {seen[inst]} and on "
                    f"{var} — a pad has one side")
            seen[inst] = var
    if not seen:
        raise AssignmentError(
            "PAD_CONFIG_VARIABLE_ABSENT",
            f"all four side lists are empty in {ASSIGNMENT_REL} "
            f"({', '.join(SIDE_VAR[s] for s in SIDES)}) — a ring of no pads "
            f"assigns nothing, and an empty set is not a pad ring")

    rots = {}
    for var in ("PAD_ROTATION_HORIZONTAL", "PAD_ROTATION_VERTICAL",
                "PAD_ROTATION_CORNER"):
        o = normalise_orient(obj[var])
        if o is None:
            raise AssignmentError(
                "PAD_ROTATION_UNKNOWN",
                f"{var}={obj[var]!r} is not an orientation "
                f"({list(DEF_ORIENTS)} or the placer's R0/R90/R180/R270/"
                f"MX/MY/MXR90/MYR90 spelling)")
        rots[var] = o

    try:
        edge = float(obj["PAD_EDGE_SPACING"])
    except (TypeError, ValueError):
        raise AssignmentError(
            "PAD_CONFIG_MALFORMED",
            f"PAD_EDGE_SPACING={obj['PAD_EDGE_SPACING']!r} is not a number "
            f"of microns")
    if edge < 0:
        raise AssignmentError("PAD_CONFIG_MALFORMED",
                              f"PAD_EDGE_SPACING={edge} is negative")

    fillers = obj["PAD_FILLERS"]
    if not isinstance(fillers, list) or not fillers or \
            not all(isinstance(f, str) and f.strip() for f in fillers):
        raise AssignmentError(
            "PAD_CONFIG_MALFORMED",
            "PAD_FILLERS is not a non-empty list of master names — without a "
            "filler cell the ring cannot abut, and abutment is what carries "
            "its supply")

    smap = obj["SIGNAL_MAP"]
    if not isinstance(smap, dict) or not smap:
        raise AssignmentError(
            "PAD_CONFIG_MALFORMED",
            "SIGNAL_MAP is not a non-empty object mapping each pad instance "
            "to the top-level BTerm it brings out")
    unmapped = sorted(set(seen) - set(smap))
    if unmapped:
        raise AssignmentError(
            "PAD_CONFIG_MALFORMED",
            f"{len(unmapped)} ordered pad instance(s) are absent from "
            f"SIGNAL_MAP: {unmapped[:8]} — a pad that brings out no named "
            f"port cannot be checked against the design's BTerms")

    return {
        "sides": {s: list(obj[SIDE_VAR[s]]) for s in SIDES},
        "instance_side": seen,
        "site": str(obj["PAD_SITE_NAME"]),
        "corner_site": str(obj["PAD_CORNER_SITE_NAME"]),
        "edge_spacing_um": edge,
        "rotation": rots,
        "corner_master": str(obj["PAD_CORNER"]),
        "fillers": list(fillers),
        "signal_map": dict(smap),
        "unperformed": {v: obj.get(v) for v in UNPERFORMED_VARS
                        if obj.get(v) is not None},
    }
