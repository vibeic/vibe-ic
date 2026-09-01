#!/usr/bin/env python3
"""digital_hardmacro_check.py — the gate of record for flow step 37.5ip.

ENFORCEMENT: advisory here — this gate is not in
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES``; no one-shot runner invokes
it inline at all. It runs when ``flow_compliance_check`` evaluates step 37.5ip's
``program_exit_zero`` clause, so its rc IS that step's verdict — "advisory"
names the RUNNER channel it is absent from, not a verdict this gate cannot
reach. Declared because vibe-ic#886 counts an undeclared AUDIT_ONLY gate as an
enforcement decision nobody made; wiring it into the runner would change what a
real run blocks on, which is the flow owner's call and is recorded, not taken
here. Kept in the first 4 kB: `declared_intent` reads only `text[:4000]`.

Step 37.5ip is where the two paths part. A chip is FABRICATED; an IP is
DELIVERED. What is delivered is not a die — it is a kit of FOUR VIEWS of one
macro:

    phase3/stage4/hardmacro/<name>.lef   so somebody else can PLACE it
    phase3/stage4/hardmacro/<name>.lib   so somebody else can TIME it
    phase3/stage4/hardmacro/<name>.v     so somebody else can SIMULATE it
    phase3/stage4/hardmacro/<name>.gds   the layout the other three abstract

UPSTREAM SAYS THIS STEP IS THE RIGHT IDEA, BY DELETION
======================================================
Measured out of the pinned image, not remembered. `librelane/flows/chip.py` is
`class Chip(Classic)` plus one substitution table, and that table is the entire
difference between shipping an IP and shipping a chip. Two of its entries:

    "OpenROAD.IOPlacement": None,   # "No pin placement necessary -> pads are
                                    #  the BTerms"
    "Magic.WriteLEF":       None,   # "This is not a macro, there's no need to
                                    #  write a LEF"

THE CHIP FLOW TURNS THE LEF WRITE OFF. So the LEF write is precisely what makes
the Classic flow an IP-DELIVERY flow: LibreLane says by DELETION exactly what
step 37.5ip says by ADDITION — the LEF is the IP path's terminal, not a chip's.
This flow had no digital IP terminal at all, so nothing it produced digitally
could be placed by anyone.

WHERE THIS GATE GOES BEYOND UPSTREAM
====================================
Upstream WRITES the LEF and stops. `Magic.WriteLEF` (`magic.py:234`,
inputs `[GDS, DEF]`, outputs `[LEF]`, script `scripts/magic/lef.tcl`) has three
knobs and no checker: `MAGIC_LEF_WRITE_USE_GDS`, `MAGIC_WRITE_FULL_LEF`,
`MAGIC_WRITE_LEF_PINONLY`. NOTHING in LibreLane afterwards asks whether the
views AGREE. The disagreements this gate refuses and upstream cannot see:

    LEF pin      vs Liberty pin       — placed but untimed, or timed but
                                        unplaceable
    LEF pin      vs Verilog port      — routed to a connection no testbench
                                        can drive
    LEF SIZE     vs GDS bbox          — the placer reserves an outline the
                                        body overflows
    LEF frame    vs GDS lower-left    — right size, wrong place
    MACRO/cell/module/GDS-top name    — instantiated by name, resolving to
                                        different cells
    LEF PIN      vs its own geometry  — a pin name with no routable area

AND THE SUPPLY PINS ARE THE SHARPEST CASE. `scripts/magic/lef.tcl` contains,
verbatim:

    lef nocheck $::env(VDD_NETS) $::env(GND_NETS)

Magic is EXPLICITLY TOLD NOT TO CHECK the power and ground nets before writing
them into the LEF. So upstream's own abstract writer performs no verification
at all on exactly the pins whose mis-declaration merges supply domains — the
measured downstream consequence being an extracted netlist with 4448 references
to a single `VSS` net and no `VDD` at all. This gate compares the PG set
between the LEF and the Liberty, which is a comparison nothing upstream makes.

THE `-pinonly` KNOB IS A CORRECTNESS KNOB, AND THE GATE TREATS IT AS ONE
=======================================================================
`lef.tcl` writes `lef write … -hide [-pinonly]`. With `-pinonly`, ONLY
port-labelled areas are pins and the rest of each net on that layer becomes an
OBSTRUCTION; without it, the labelled port AND the connected metal on the same
layer are the pin. Set it wrong and the next designer's router either cannot
reach the pin or shorts to the internal net — a kit that looks complete and
fails in somebody else's chip, which is this gate's whole subject. What a
delivered LEF can be held to on its own:

  * BLOCKING — a pin with NO `RECT`/`POLYGON` under any `PORT` is a name with
    no place; the router is told the pin exists and given nowhere to land.
  * BLOCKING — pin geometry lying WHOLLY outside the declared outline; the
    placer reserves the outline and nothing else.
  * ADVISORY — pins declared, real GDS geometry, and NO `OBS` section at all:
    the signature of a LEF written with neither `-hide` nor `-pinonly`, which
    tells the router the macro's interior is free space. It is a SIGNATURE and
    not a proof (mapping a LEF layer name onto a GDS layer number needs the
    tech LEF, which a kit does not carry), so it is `NOT DETERMINED`, carried
    on the verdict word, and never silently accepted as clean.

AND THE REFUSAL IS A DATUM. LibreLane's own refusals `exit 1` with a printed
message and no machine-readable record. Every verdict here — including every
NOT DETERMINED — is written into the JSON report the flow's gate declares.

WHY THIS GATE IS NOT "DO THE FOUR FILES EXIST"
==============================================
The analog path has had this terminal since A8, and A8's own history is the
argument. `analog_hardmacro_check` began life asking `exists() and st_size !=
0` of the GDS, and MEASURED: 500 bytes of non-GDS noise beside a valid
LEF/LIB/V produced `[PASS] analog_hardmacro_check` + HARDMACRO_COMPLETE, while
the sibling A5 gate rejected the identical bytes. `analog_lef_gds_outline_check`
was then written because a LEF claiming a 100x100 abstract over a GDS whose
polygons span 250x80 sails through every presence check — and it in turn was
extended because a pair that agrees on WIDTH and HEIGHT can still be 30 um out
of REGISTRATION, which is silicon-fatal and silent (measured, IHP SG13G2:
`SIZE 556.810 BY 158.400` exact, `bbox (-0.620,-30.320)` — the placer reserves
the LEF outline and routes to LEF pin locations while the streamed body sits
30.32 um lower, on top of eight rows of legally placed standard cells; the
extractor then collapsed the whole supply system into ONE net).

A kit that LOOKS complete and mis-places or mis-times in somebody else's chip
is worse than a missing view: a missing view is refused at the door, a
disagreeing view is integrated. So the question this gate asks is not "are
there four files" but:

    DO THE FOUR VIEWS DESCRIBE THE SAME THING?

and it asks it along the four axes on which they can disagree:

    IDENTITY   LEF `MACRO n` == LIB `cell (n)` == V `module n` == GDS top cell
    EXTENT     LEF `SIZE w BY h ;` == GDS bounding box (within --tol-pct)
    FRAME      the lower-left the LEF declares (FOREIGN / ORIGIN / LEF default)
               == the GDS top-cell bounding-box lower-left (within --tol-um)
    INTERFACE  LEF PIN set == LIB pin set == V port set

SHARED PARSERS, NOT COPIED ONES
===============================
The LEF `SIZE` / `ORIGIN` / `FOREIGN` readers and the hierarchical GDSII
bounding-box walk are IMPORTED from `analog_lef_gds_outline_check`, and the GDS
geometry-record count from `analog_a5_layout_check` via the same route the A8
gate uses. Two gates that certify the same file type must not be able to drift
apart on it — that is the rule `analog_hardmacro_check` already records in its
own docstring, and re-typing those parsers here would break it on the day one
side is fixed.

IS `analog_lef_gds_outline_check` REUSABLE AS A WHOLE? — NO, AND WHY
====================================================================
Asked, and answered by reading it. Its PARSERS are reusable and are reused.
Its GATE is not, for two reasons that are both about WHERE it looks and not
about what it knows:

  1. Its discovery layer is keyed on the analog tree: it needs
     `phase3/analog/analog_block_list.json` to enumerate blocks and reads
     `phase3/analog/hardmacro/<block>/<block>.lef` — a per-block subdirectory.
     The digital deliverable step 37.5ip declares is FLAT
     (`phase3/stage4/hardmacro/*.lef`) and has no block list, because a digital
     IP is one macro and not a list of analog blocks.
  2. Its "nothing to examine" branch is `no analog block list -> VACUOUS_PASS`.
     On a digital IP project that branch is reached by CONSTRUCTION — there is
     never an analog block list — so pointing step 37.5ip at it would produce a
     gate that answers VACUOUS on 100% of the population it exists to judge.

It also does not answer the INTERFACE or IDENTITY axes at all; those are this
gate's own work (`analog_hardmacro_pinname_consistency_check` is the analog
sibling for the interface half, and is likewise analog-tree-keyed).

WHAT A "NOTHING TO CHECK" ANSWER COSTS HERE
===========================================
An absent `phase3/stage4/hardmacro/` is NOT a pass. It is rc 2 with the
`NOT_DETERMINED` verdict and a named reason: this project delivered no IP kit,
so nothing about one has been established. A silent green over an empty set is
the defect this repository hunts, and it is the one this gate would be most
tempting to commit — the digital hardmacro directory is empty on every project
that has ever run this flow.

THE TWO NARROW EXCEPTIONS, STATED SO THEY CANNOT WIDEN
======================================================
1. POWER/GROUND PINS NEED NOT APPEAR IN THE VERILOG VIEW. A Verilog
   simulation view of a hard macro conventionally carries the LOGICAL
   interface only; supplies are physical and live in the LEF (`USE POWER` /
   `USE GROUND`) and the Liberty (`pg_pin`). The exception is exactly that
   wide and no wider: LEF and Liberty must still agree on the PG set EXACTLY,
   and a supply name the Verilog DOES declare must still be one the LEF knows.
   Every omitted PG port is named in the report; nothing is silent.

2. BUSES ARE COMPARED BY BASE NAME. The three views spell a bus in three
   incompatible ways — LEF enumerates `PIN a[0]`, `PIN a[1]`; Liberty groups
   `bus (a)`; Verilog ranges `input [1:0] a`. Bit-level equality across those
   spellings is not decidable without a Liberty `bus_type` resolution and a
   Verilog range evaluation, so the comparable unit is the base name, taken by
   stripping the LEF's OWN declared `BUSBITCHARS` (defaulting to both `[]` and
   `<>` when it declares none). This is a STATED granularity limit, not a
   silent one: a pin present in one view and absent from another is caught; a
   bus that is 8 bits in one view and 16 in another is NOT, and the report
   says so in `interface.granularity`.

TIMING CHARACTERISATION IS DISCLOSED, NOT ASSUMED
=================================================
A Liberty whose every timing number is zero makes the integration STA vacuous
— every path through the macro has zero delay, so it can never violate setup
or hold. `analog_liberty_nonzero_delay_check` calls that a FAIL on the analog
side. Here it is a DISCLOSED PASS TIER (`PASS_TIMING_UNCHARACTERISED`) carried
on the verdict word and in the report, because step 37.5ip declares no
characterisation step to produce the numbers, and a gate that fails a design
for the absence of a step the flow never declares is failing the flow, not the
design. It is a tier and not a plain PASS precisely so it cannot read as one.

Usage:
    python3 digital_hardmacro_check.py <project_dir> [--json <out>]
                                       [--tol-pct 2.0] [--tol-um 0.01]

Exit codes:
    0 = PASS — every delivered kit's four views agree.
        PASS_OBSTRUCTION_NOT_DETERMINED and PASS_TIMING_UNCHARACTERISED are
        their own disclosed tiers, ranked in that order, also rc 0.
    1 = FAIL — a view is missing / empty / hollow, or two views disagree
        about identity, extent, frame or interface.
    2 = NOT_DETERMINED — no digital hardmacro package exists to examine, or
        an argument / fatal IO error. NEVER a statement that the kit is good.

chip-AGNOSTIC: no chip, vendor, SKU, process-node or pin-name literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import _path_layout as _pl
import _vacuous_exit as _vx
from _atomic_artefact import write_text as atomic_write_text

# ── SHARED PARSERS ────────────────────────────────────────────────────────
# Imported, never re-typed. Guarded the way `analog_hardmacro_check` guards
# its geometry import: a checker must never be silently disarmed by an
# ImportError, so an unavailable parser is a hard error AT USE TIME, not a
# quietly skipped predicate.
try:
    from analog_lef_gds_outline_check import (
        parse_lef_size,
        parse_lef_frame_ll,
        parse_gds_bbox_extent,
        _parse_structures,
    )
except ImportError:  # pragma: no cover - programs/ is always on sys.path
    parse_lef_size = None       # type: ignore[assignment]
    parse_lef_frame_ll = None   # type: ignore[assignment]
    parse_gds_bbox_extent = None  # type: ignore[assignment]
    _parse_structures = None    # type: ignore[assignment]

try:
    from analog_a5_layout_check import _gds_geometry_count
except ImportError:  # pragma: no cover
    _gds_geometry_count = None  # type: ignore[assignment]

try:
    from analog_liberty_nonzero_delay_check import analyze_liberty
except ImportError:  # pragma: no cover
    analyze_liberty = None      # type: ignore[assignment]


GATE = "digital_hardmacro_check"
VERSION = "1.0.0"

#: LEF `SIZE` vs GDS width/height, per cent. Same default as the analog
#: outline gate — the two answer the same question about the same file pair.
DEFAULT_TOL_PCT = 2.0
#: LEF frame vs GDS bounding-box lower-left, microns. ABSOLUTE, not a
#: percentage: a frame offset is a displacement, and a percentage would
#: license a displacement bigger than a standard-cell row on a big macro
#: while forbidding a legal grid rounding on a small one.
DEFAULT_TOL_UM = 0.01

VIEW_EXTS = (".lef", ".lib", ".gds", ".v")

#: The same four views written as the paths step 37.5ip DECLARES, so the set
#: this program searches is stated in the vocabulary the flow uses rather than
#: only as a suffix filter.
#:
#: WHY BOTH FORMS EXIST (measured 2026-08-20)
#: ------------------------------------------
#: Discovery itself must stay `iterdir()` + `suffix.lower()`: a kit that ships
#: `CORE.LEF` is a kit, and `Path.glob("*.lef")` is case-SENSITIVE on Linux, so
#: globbing alone would make an upper-case delivery invisible — the failure
#: mode where a check reports "no kit" about a kit that is right there.
#:
#: But a suffix filter names no path, and dimension 4 asks a fair question of
#: every gate: does the program actually read what the step declares? It could
#: resolve `*.lef`, `*.lib` and `*.gds` only from PROSE in this docstring, and
#: could not resolve `phase3/stage4/hardmacro/*.v` at all. Three of the four
#: were being credited to a comment. These globs are used below to say which
#: declared view was searched for and not found, so the answer stops depending
#: on what the documentation happens to mention.
#:
#: WRITTEN OUT, not built with an f-string over ``VIEW_EXTS``: a comprehension
#: produces the same four strings at runtime and NO literal in the source, so
#: any reader that works from the text — dimension 4, a grep, a person — still
#: could not tell which paths this program opens. The assertion below keeps the
#: two forms from drifting.
DECLARED_VIEW_GLOBS = (
    "phase3/stage4/hardmacro/*.lef",
    "phase3/stage4/hardmacro/*.lib",
    "phase3/stage4/hardmacro/*.gds",
    "phase3/stage4/hardmacro/*.v",
)
assert tuple(g.rsplit("*", 1)[-1] for g in DECLARED_VIEW_GLOBS) == VIEW_EXTS, (
    "DECLARED_VIEW_GLOBS and VIEW_EXTS name different view sets")


def unmatched_view_globs(project: Path) -> List[str]:
    """Which declared view path matched NOTHING under `project`.

    Case-insensitive, to agree with `discover_packages`: `*.lef` here also
    accounts for `CORE.LEF`.
    """
    out: List[str] = []
    for pattern in DECLARED_VIEW_GLOBS:
        ext = pattern.rsplit("*", 1)[-1].lower()
        base = project / pattern.rsplit("/", 1)[0]
        hit = base.is_dir() and any(
            q.is_file() and q.suffix.lower() == ext for q in base.iterdir())
        if not hit:
            out.append(pattern)
    return out



def _require(obj, what: str):
    """Return `obj`, or raise if the shared parser it names is unavailable.

    Deliberately NOT caught in main(): an uncaught exception exits 1, which
    `flow_compliance_check` reads as FAIL. Returning rc 2 would be read as
    VACUOUS_PASS — silently green — which is the failure mode a disarmed
    predicate produces and this gate exists to end.
    """
    if obj is None:
        raise RuntimeError(
            f"{what} unavailable; {GATE} cannot evaluate its own predicate")
    return obj


# ── comment stripping, shared by the Verilog and Liberty readers ───────────
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def strip_comments(text: str) -> str:
    """Remove `/* … */` and `// …`. Both languages use exactly these forms,
    and a mention inside one must never stand in for a declaration."""
    return _LINE_COMMENT_RE.sub(" ", _BLOCK_COMMENT_RE.sub(" ", text))


# ── LEF ───────────────────────────────────────────────────────────────────
_LEF_MACRO_RE = re.compile(r"(?m)^\s*MACRO\s+(\S+)")
#: `MACRO n … END n`, name back-referenced so the block cannot run past its own
#: END into the next macro. Pin parsing is scoped to this block: an unscoped
#: scan over the whole file merges two macros' interfaces into one set.
_LEF_MACRO_BLOCK_RE = re.compile(
    r"(?m)^[ \t]*MACRO\s+(?P<name>\S+)[ \t]*$(?P<body>.*?)"
    r"^[ \t]*END\s+(?P=name)[ \t]*$", re.S)
#: Pin geometry. A `PIN` carries its routable area as `RECT`/`POLYGON` inside
#: one or more `PORT` groups. UPSTREAM CONTEXT (`librelane/scripts/magic/
#: lef.tcl`, read out of the pinned image): the LEF is written by
#: `lef write … -hide [-pinonly]`, and `-pinonly` marks ONLY port-LABELLED
#: areas as pins while the rest of the net on that layer becomes an
#: OBSTRUCTION. That knob decides whether the next designer's router can
#: reach this pin at all, so "does this pin have any routable area" is a
#: correctness question and not a cosmetic one.
_LEF_RECT_RE = re.compile(
    r"\bRECT\s+([-+0-9.]+)\s+([-+0-9.]+)\s+([-+0-9.]+)\s+([-+0-9.]+)\s*;",
    re.IGNORECASE)
_LEF_POLYGON_RE = re.compile(r"\bPOLYGON\s+([-+0-9.\s]+?);", re.IGNORECASE)
_LEF_OBS_RE = re.compile(r"(?m)^[ \t]*OBS\b")
#: Removes a `FOREIGN … ;` statement so the shared frame reader falls through
#: to its ORIGIN / LEF-default branch. See `origin_ll` in `parse_lef`.
_LEF_FOREIGN_STRIP_RE = re.compile(r"\bFOREIGN\b[^;]*;", re.IGNORECASE)
_LEF_BUSBITCHARS_RE = re.compile(
    r"BUSBITCHARS\s+\"(..)\"\s*;", re.IGNORECASE)
#: A PIN block: `PIN <n> … END <n>`. Non-greedy body, name back-referenced so
#: the block cannot run past its own END into the next pin.
_LEF_PIN_BLOCK_RE = re.compile(
    r"(?m)^[ \t]*PIN\s+(?P<name>\S+)[ \t]*$(?P<body>.*?)"
    r"^[ \t]*END\s+(?P=name)[ \t]*$", re.S)
_LEF_USE_RE = re.compile(r"\bUSE\s+(\w+)\s*;", re.IGNORECASE)
_LEF_DIRECTION_RE = re.compile(
    r"\bDIRECTION\s+(INPUT|OUTPUT|INOUT|FEEDTHRU)\s*;", re.IGNORECASE)
_PG_USES = {"power", "ground"}


def lef_bus_chars(lef_text: str) -> str:
    """The bus delimiters this LEF DECLARES, or both conventional pairs.

    Read from the file rather than assumed: `BUSBITCHARS "<>" ;` is legal LEF
    and a gate that hard-codes `[]` would compare `a<0>` against `a` as two
    different pins on such a kit."""
    m = _LEF_BUSBITCHARS_RE.search(lef_text)
    if m:
        return m.group(1)
    return "[]<>"


def base_name(pin: str, bus_chars: str = "[]<>") -> str:
    """Bus base name: everything before the first declared bus-open char.

    `a[3]` -> `a`, `a<3>` -> `a`, `clk` -> `clk`. Lower-cased, because the
    tool flows that consume these three views are case-insensitive on net
    names and a case-only difference is reported as an IDENTITY finding
    rather than silently splitting one pin into two."""
    name = pin.strip()
    opens = bus_chars[0::2] if len(bus_chars) >= 2 else "["
    for ch in set(opens) | {"[", "<"}:
        idx = name.find(ch)
        if idx > 0:
            name = name[:idx]
    return name.lower()


def pin_geometry(pin_body: str) -> List[tuple]:
    """Every routable area a PIN body declares, as (llx, lly, urx, ury) um.

    `RECT` directly; `POLYGON` reduced to its bounding box, which is all this
    gate asks of it (is there routable area, and is it inside the outline).
    """
    out: List[tuple] = []
    for m in _LEF_RECT_RE.finditer(pin_body):
        x1, y1, x2, y2 = (float(m.group(i)) for i in (1, 2, 3, 4))
        out.append((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))
    for m in _LEF_POLYGON_RE.finditer(pin_body):
        nums = [float(t) for t in m.group(1).split()]
        xs, ys = nums[0::2], nums[1::2]
        if len(xs) >= 3 and len(xs) == len(ys):
            out.append((min(xs), min(ys), max(xs), max(ys)))
    return out


def parse_lef(lef_text: str, stem: str = "") -> Dict[str, object]:
    """Everything this gate reads out of a LEF, in one pass.

    Returns `{"macro": <name|None>, "size": (w,h)|None, "frame": (llx,lly,src),
    "signal": set, "pg": set, "raw": {base: [spelled…]},
    "direction": {base: input|output|inout|feedthru|mixed|""}}`.
    """
    macro_m = _LEF_MACRO_RE.search(lef_text)
    macro = macro_m.group(1) if macro_m else None
    bus_chars = lef_bus_chars(lef_text)

    # Scope every pin question to ONE macro's body. `stem` is the name the kit
    # is filed under; preferring the block that matches it means a LEF that
    # happens to carry a second macro is read as the one it is named for, and
    # the naming problem itself is left to the IDENTITY axis rather than being
    # silently merged into the interface.
    blocks = list(_LEF_MACRO_BLOCK_RE.finditer(lef_text))
    chosen = None
    for b in blocks:
        if stem and b.group("name") == stem:
            chosen = b
            break
    if chosen is None and blocks:
        chosen = blocks[0]
    scope = chosen.group("body") if chosen is not None else lef_text
    if chosen is not None:
        macro = chosen.group("name")

    signal: Set[str] = set()
    pg: Set[str] = set()
    pg_kind: Dict[str, str] = {}
    raw: Dict[str, List[str]] = {}
    direction_values: Dict[str, Set[str]] = {}
    geom_by_pin: Dict[str, List[tuple]] = {}
    for m in _LEF_PIN_BLOCK_RE.finditer(scope):
        spelled = m.group("name")
        b = base_name(spelled, bus_chars)
        raw.setdefault(b, []).append(spelled)
        body = m.group("body")
        direction_m = _LEF_DIRECTION_RE.search(body)
        if direction_m:
            direction_values.setdefault(b, set()).add(
                direction_m.group(1).lower())
        use_m = _LEF_USE_RE.search(body)
        if use_m and use_m.group(1).lower() in _PG_USES:
            pg.add(b)
            # WHICH RAIL, not merely that it is one. `USE POWER` vs
            # `USE GROUND` is the only place the LEF says so, and it is the
            # half of the supply declaration that `lef nocheck` guarantees
            # Magic did not verify.
            pg_kind[b] = use_m.group(1).lower()
        else:
            signal.add(b)
        geom_by_pin.setdefault(b, []).extend(pin_geometry(body))
    # A base name spelled once as POWER and once as SIGNAL is a defect in the
    # LEF itself; count it as PG so the PG/LIB comparison surfaces it rather
    # than letting it hide in the (larger) signal set.
    signal -= pg
    directions = {
        base: (next(iter(values)) if len(values) == 1 else "mixed")
        for base, values in direction_values.items()
    }
    return {"macro": macro,
            "size": _require(parse_lef_size, "parse_lef_size")(scope
                                                              or lef_text),
            "frame": _require(parse_lef_frame_ll,
                              "parse_lef_frame_ll")(scope or lef_text),
            # The macro box in the macro's OWN coordinates: the same shared
            # reader, asked with the FOREIGN statement removed so it returns
            # its ORIGIN / LEF-default answer. Two DIFFERENT questions with
            # one parser, rather than one question with two answers.
            "origin_ll": _require(parse_lef_frame_ll, "parse_lef_frame_ll")(
                _LEF_FOREIGN_STRIP_RE.sub(" ", scope or lef_text))[:2],
            "signal": signal, "pg": pg, "pg_kind": pg_kind, "raw": raw,
            "direction": directions,
            "geometry": geom_by_pin,
            "macro_count": len(blocks),
            "has_obs": bool(_LEF_OBS_RE.search(scope)),
            "bus_chars": bus_chars}


# ── Liberty ───────────────────────────────────────────────────────────────
_LIB_CELL_RE = re.compile(
    r"(?:^|[^\w])cell\s*\(\s*[\"']?(?P<name>[^)\s\"']+)[\"']?\s*\)",
    re.IGNORECASE)
_LIB_PIN_RE = re.compile(
    r"(?:^|[^\w])(?P<kind>pg_pin|bus|pin)\s*\(\s*[\"']?"
    r"(?P<name>[^)\s\"',]+)[\"']?\s*\)\s*\{", re.IGNORECASE)
#: `pg_type : primary_ground ;` inside a pg_pin group. The rail a supply pin
#: belongs to is stated NOWHERE ELSE in a Liberty, and a `pg_pin` that omits
#: it does not say which supply it is.
_LIB_PG_TYPE_RE = re.compile(
    r"\bpg_type\s*:\s*([A-Za-z_]+)\s*;", re.IGNORECASE)


def parse_liberty(lib_text: str, bus_chars: str = "[]<>") -> Dict[str, object]:
    """`{"cell": <name|None>, "signal": set, "pg": set}` from a Liberty view.

    Comments are stripped FIRST. The predicate is the DECLARATION being
    PRESENT, never the bad token being absent: `analog_hardmacro_check`
    records the measurement where a Liberty containing only
    `/* the release was cancelled */` satisfied a bare `"cell" in text`
    substring test on the letters inside "cancelled"."""
    text = strip_comments(lib_text)
    cell_m = _LIB_CELL_RE.search(text)
    signal: Set[str] = set()
    pg: Set[str] = set()
    pg_type: Dict[str, str] = {}
    matches = list(_LIB_PIN_RE.finditer(text))
    for i, m in enumerate(matches):
        b = base_name(m.group("name"), bus_chars)
        if m.group("kind").lower() == "pg_pin":
            pg.add(b)
            # Scoped to THIS pg_pin's group: from its `{` up to the start of
            # the next pin/bus/pg_pin declaration, so a `pg_type` belonging
            # to the following group is never read as this one's.
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            tm = _LIB_PG_TYPE_RE.search(text, m.end(), end)
            pg_type[b] = tm.group(1).lower() if tm else ""
        else:
            signal.add(b)
    signal -= pg
    return {"cell": cell_m.group("name") if cell_m else None,
            "signal": signal, "pg": pg, "pg_type": pg_type}


# ── Verilog ───────────────────────────────────────────────────────────────
_V_MODULE_RE = re.compile(
    r"(?:^|[^\w$])module\s+(?P<name>\\\S+|[A-Za-z_][\w$]*)"
    r"(?P<rest>.*?)\bendmodule\b", re.S)
#: The port list is the parenthesised group that ends at the header `;`.
#: GREEDY up to that `;` on purpose: a parameterised header
#: (`module m #(parameter W=8) (input [W-1:0] a);`) has TWO groups, and a
#: non-greedy read stops at the first `)` — inside the parameter list, whose
#: contents declare no direction and so yield an empty interface.
_V_HEADER_PORTS_RE = re.compile(r"\((?P<ports>[^;]*)\)\s*;", re.S)
#: Keywords that can never be a port NAME. Without this exclusion the name
#: list runs past its own declaration into the NEXT one: measured on the
#: ordinary ANSI header `input wire clk, output wire [1:0] dout`, the reader
#: returned {clk, output, wire} — it had swallowed the following direction
#: keyword as a port and lost `dout` entirely.
_V_NON_NAME_KW = (r"(?:input|output|inout|wire|reg|logic|signed|unsigned"
                  r"|supply0|supply1|tri|wand|wor)\b")
_V_NAME = r"(?:\\\S+|[A-Za-z_][\w$]*)"
#: One `input`/`output`/`inout` declaration and its COMMA-SEPARATED name list.
#: `input wire [7:0] a, b;` declares BOTH a and b — a reader that takes only
#: the first name loses `b` and then reports it missing from the Verilog view.
_V_PORT_DECL_RE = re.compile(
    r"\b(?P<dir>input|output|inout)\b"
    r"(?P<attrs>(?:\s+(?:wire|reg|logic|signed|unsigned))*)"
    r"(?P<range>(?:\s*\[[^\]]*\])*)"
    r"(?P<names>"
    rf"(?:\s*(?!{_V_NON_NAME_KW}){_V_NAME}\s*,)*"
    rf"\s*(?!{_V_NON_NAME_KW}){_V_NAME})")
_V_IDENT_RE = re.compile(r"\\\S+|[A-Za-z_][\w$]*")
_V_SUPPLY_RE = re.compile(r"\b(?:supply0|supply1)\b")


def parse_verilog(v_text: str, bus_chars: str = "[]<>") -> Dict[str, object]:
    """`{"module": <name|None>, "ports": set, "style": "ansi"|"non-ansi"|""}`.

    BOTH header styles are read. A hardmacro blackbox view is written either
    way in the wild, and a reader that only understands the ANSI form returns
    an EMPTY port set for a legal non-ANSI view — which this gate would then
    report as "every pin is missing from the Verilog", a false FAIL that would
    get the gate weakened rather than the kit fixed.
    """
    m = _V_MODULE_RE.search(strip_comments(v_text))
    if not m:
        return {"module": None, "ports": set(), "style": ""}
    name = m.group("name")
    rest = m.group("rest")
    hm = _V_HEADER_PORTS_RE.search(rest)
    header = hm.group("ports") if hm else ""
    body = rest[hm.end():] if hm else rest

    ports: Set[str] = set()
    style = ""
    # ANSI: directions live INSIDE the header parentheses.
    for pm in _V_PORT_DECL_RE.finditer(header):
        style = "ansi"
        for nm in _V_IDENT_RE.finditer(pm.group("names")):
            ports.add(base_name(nm.group(0), bus_chars))
    if not ports:
        # non-ANSI: the header is a bare name list and the directions are
        # declared in the body.
        for pm in _V_PORT_DECL_RE.finditer(body):
            for nm in _V_IDENT_RE.finditer(pm.group("names")):
                ports.add(base_name(nm.group(0), bus_chars))
        if ports:
            style = "non-ansi"
        elif header.strip():
            # A header with names but no direction anywhere is not a usable
            # interface; report the names so the disagreement is concrete
            # rather than reporting an empty set.
            for nm in _V_IDENT_RE.finditer(header):
                ports.add(base_name(nm.group(0), bus_chars))
            style = "header-only"
    return {"module": name, "ports": ports, "style": style}


# ── GDS ───────────────────────────────────────────────────────────────────
def gds_top_cells(raw: bytes) -> List[str]:
    """Names of the structures no other structure references.

    Same walk `parse_gds_bbox_extent` uses to pick its top, via the same
    imported parser, so the name this gate compares and the box it measures
    can never come from two different notions of "top"."""
    structs, _, seen_header = _require(_parse_structures,
                                       "_parse_structures")(raw)
    if not seen_header or not structs:
        return []
    referenced = {sn for st in structs.values() for sn, _ in st["refs"]}
    tops = [n for n in structs if n not in referenced]
    return sorted(tops) if tops else sorted(structs)


def gds_geometry_records(path: Path) -> int:
    """Geometry/placement record count — the SAME predicate A5 and A8 use.

    Size is not evidence that a layout exists: `analog_hardmacro_check`
    records the measurement where 500 bytes of non-GDS noise passed a
    non-empty test while the sibling gate rejected the identical bytes."""
    count = _require(_gds_geometry_count, "_gds_geometry_count")
    try:
        return count(path.read_bytes())
    except OSError:
        return 0


# ── findings ──────────────────────────────────────────────────────────────
@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    macro: str = ""
    file: str = ""


@dataclass
class Result:
    program: str = GATE
    version: str = VERSION
    passed: bool = True
    verdict_tier: str = "PASS"
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def hardmacro_dir(project: Path) -> Path:
    """`phase3/stage4/hardmacro` — the flat directory step 37.5ip declares.

    Derived from `_path_layout.phase3_stage4_dir` rather than spelled again,
    so a future move of stage4 moves this gate with it."""
    return _pl.phase3_stage4_dir(project) / "hardmacro"


def discover_packages(hm_dir: Path) -> Dict[str, Dict[str, Path]]:
    """`{stem: {ext: path}}` over the four declared extensions.

    Keyed on the UNION of stems, so a kit that ships three of four views is
    discovered (and then reported incomplete) rather than being invisible for
    want of the very view it is missing."""
    found: Dict[str, Dict[str, Path]] = {}
    if not hm_dir.is_dir():
        return found
    for p in sorted(hm_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in VIEW_EXTS:
            found.setdefault(p.stem, {})[p.suffix.lower()] = p
    return found


def _pct_delta(a: float, b: float) -> float:
    if a == 0 and b == 0:
        return 0.0
    denom = max(abs(a), abs(b))
    return abs(a - b) / denom * 100.0 if denom else 0.0


def check_package(name: str, views: Dict[str, Path], project: Path,
                  tol_pct: float, tol_um: float) -> Tuple[bool, List[Finding],
                                                          dict]:
    """Verdict for ONE delivered kit. Returns (ok, findings, detail)."""
    F: List[Finding] = []
    detail: dict = {"macro": name, "views": {}}

    def cite(p: Path) -> str:
        try:
            return str(p.relative_to(project))
        except ValueError:
            return str(p)

    # ── 1. every view present, and none of them empty ─────────────────────
    missing = [e for e in VIEW_EXTS if e not in views]
    for e in missing:
        F.append(Finding(
            rule="VIEW_MISSING", severity="ERROR", macro=name,
            message=(f"macro '{name}': no `{e}` view. A kit is delivered so "
                     f"somebody else can place ({'.lef'}), time ({'.lib'}), "
                     f"simulate ({'.v'}) and stream ({'.gds'}) it; the "
                     f"missing view is the one thing they cannot do.")))
    empty = []
    for e, p in sorted(views.items()):
        try:
            size = p.stat().st_size
        except OSError:
            size = -1
        detail["views"][e] = {"path": cite(p), "bytes": size}
        if size <= 0:
            empty.append(e)
            F.append(Finding(
                rule="VIEW_EMPTY", severity="ERROR", macro=name,
                file=cite(p),
                message=(f"macro '{name}': `{e}` view is {size} bytes. An "
                         f"empty view is a placeholder that reads as a "
                         f"delivery.")))
    if missing or empty:
        detail["status"] = "INCOMPLETE"
        return False, F, detail

    lef_p, lib_p, gds_p, v_p = (views[".lef"], views[".lib"],
                                views[".gds"], views[".v"])
    try:
        lef_text = lef_p.read_text(errors="replace")
        lib_text = lib_p.read_text(errors="replace")
        v_text = v_p.read_text(errors="replace")
        gds_raw = gds_p.read_bytes()
    except OSError as exc:
        F.append(Finding(rule="VIEW_UNREADABLE", severity="ERROR", macro=name,
                         message=f"macro '{name}': {exc}"))
        detail["status"] = "UNREADABLE"
        return False, F, detail

    lef = parse_lef(lef_text, name)
    bus_chars = str(lef["bus_chars"])
    lib = parse_liberty(lib_text, bus_chars)
    ver = parse_verilog(v_text, bus_chars)

    ok = True

    # ── 2. each view must actually BE that view ───────────────────────────
    if not lef["macro"]:
        ok = False
        F.append(Finding(rule="LEF_NO_MACRO", severity="ERROR", macro=name,
                         file=cite(lef_p),
                         message=(f"macro '{name}': LEF declares no "
                                  f"`MACRO <name>` — nothing to place.")))
    if not lib["cell"]:
        ok = False
        F.append(Finding(rule="LIB_NO_CELL", severity="ERROR", macro=name,
                         file=cite(lib_p),
                         message=(f"macro '{name}': Liberty declares no "
                                  f"`cell (<name>)` group outside comments — "
                                  f"nothing to time.")))
    if not ver["module"]:
        ok = False
        F.append(Finding(rule="V_NO_MODULE", severity="ERROR", macro=name,
                         file=cite(v_p),
                         message=(f"macro '{name}': Verilog declares no "
                                  f"`module <name>` outside comments — "
                                  f"nothing to simulate.")))
    geom_records = gds_geometry_records(gds_p)
    detail["gds_geometry_records"] = geom_records
    if geom_records <= 0:
        ok = False
        F.append(Finding(
            rule="GDS_NO_GEOMETRY", severity="ERROR", macro=name,
            file=cite(gds_p),
            message=(f"macro '{name}': GDS carries no BOUNDARY/PATH/SREF/"
                     f"AREF/BOX record ({gds_p.stat().st_size} bytes of "
                     f"padding, garbage or an empty library) — not a "
                     f"layout. Size is not evidence of geometry.")))

    tops = gds_top_cells(gds_raw) if geom_records > 0 else []
    detail["gds_top_cells"] = tops

    # ── 3. IDENTITY — four views, one thing ───────────────────────────────
    names = {"lef.MACRO": lef["macro"], "lib.cell": lib["cell"],
             "v.module": ver["module"]}
    detail["identity"] = dict(names)
    detail["identity"]["gds.top"] = tops[0] if len(tops) == 1 else tops
    stated = {k: v for k, v in names.items() if v}
    if len(set(stated.values())) > 1:
        ok = False
        F.append(Finding(
            rule="IDENTITY_DISAGREE", severity="ERROR", macro=name,
            message=(f"macro '{name}': the views name different things — "
                     + ", ".join(f"{k}={v!r}" for k, v in sorted(stated.items()))
                     + ". A kit whose views disagree about WHICH cell they "
                       f"describe will be instantiated by name and resolve to "
                       f"three different cells.")))
    elif stated and tops:
        one = next(iter(set(stated.values())))
        if one not in tops:
            ok = False
            F.append(Finding(
                rule="IDENTITY_GDS_DISAGREE", severity="ERROR", macro=name,
                file=cite(gds_p),
                message=(f"macro '{name}': the abstract views name {one!r} "
                         f"and the GDS top cell(s) are {tops!r}. The layout "
                         f"streamed into somebody else's chip is looked up by "
                         f"that name.")))

    # ── 4. EXTENT — LEF SIZE vs GDS bounding box ──────────────────────────
    size = lef["size"]
    box = parse_gds_bbox_extent(gds_raw) if geom_records > 0 else None
    detail["lef_size_um"] = list(size) if size else None
    detail["gds_bbox_um"] = list(box) if box else None
    if size is None:
        ok = False
        F.append(Finding(
            rule="LEF_NO_SIZE", severity="ERROR", macro=name, file=cite(lef_p),
            message=(f"macro '{name}': LEF declares no `SIZE w BY h ;`. The "
                     f"outline is the area a placer RESERVES for this macro; "
                     f"a LEF that does not state one cannot be placed.")))
    elif box is None:
        if geom_records > 0:
            ok = False
            F.append(Finding(
                rule="GDS_NO_BBOX", severity="ERROR", macro=name,
                file=cite(gds_p),
                message=(f"macro '{name}': GDS carries geometry records but "
                         f"no extractable bounding box (missing/zero UNITS, "
                         f"or a degenerate extent) — the LEF outline cannot "
                         f"be cross-checked against anything.")))
    else:
        llx, lly, urx, ury = box
        gw, gh = urx - llx, ury - lly
        dw, dh = _pct_delta(size[0], gw), _pct_delta(size[1], gh)
        detail["extent_delta_pct"] = {"w": round(dw, 6), "h": round(dh, 6)}
        if dw > tol_pct or dh > tol_pct:
            ok = False
            F.append(Finding(
                rule="OUTLINE_MISMATCH", severity="ERROR", macro=name,
                file=cite(lef_p),
                message=(f"macro '{name}': LEF SIZE {size[0]:.4f} x "
                         f"{size[1]:.4f} um vs GDS bbox {gw:.4f} x {gh:.4f} "
                         f"um — delta {dw:.2f}% / {dh:.2f}% exceeds "
                         f"{tol_pct}%. The placer reserves the LEF outline; a "
                         f"body wider than its abstract overlaps whatever was "
                         f"legally placed next to it.")))
        # ── 5. FRAME — the registration half ──────────────────────────────
        ex, ey, src = lef["frame"]
        detail["frame"] = {"expected_ll_um": [ex, ey], "source": src,
                           "gds_ll_um": [llx, lly]}
        offx, offy = llx - ex, lly - ey
        detail["frame"]["offset_um"] = [round(offx, 6), round(offy, 6)]
        if abs(offx) > tol_um or abs(offy) > tol_um:
            ok = False
            F.append(Finding(
                rule="REGISTRATION_MISMATCH", severity="ERROR", macro=name,
                file=cite(lef_p),
                message=(f"macro '{name}': the LEF places its frame's "
                         f"lower-left at ({ex:.4f}, {ey:.4f}) um (per {src}) "
                         f"and the GDS bounding box starts at ({llx:.4f}, "
                         f"{lly:.4f}) um — offset ({offx:.4f}, {offy:.4f}) um "
                         f"exceeds {tol_um} um. Width and height are the two "
                         f"numbers a misregistered pair still agrees on: the "
                         f"outline is the right SIZE in the wrong PLACE, and "
                         f"the placer routes to LEF pin locations while the "
                         f"body sits somewhere else.")))

    # ── 6. INTERFACE — one pin set, three spellings ───────────────────────
    sig_lef, pg_lef = set(lef["signal"]), set(lef["pg"])
    sig_lib, pg_lib = set(lib["signal"]), set(lib["pg"])
    v_ports = set(ver["ports"])
    detail["interface"] = {
        "granularity": "base-name (bus bits are not compared individually)",
        "bus_chars": bus_chars,
        "lef_signal": sorted(sig_lef), "lef_pg": sorted(pg_lef),
        "lib_signal": sorted(sig_lib), "lib_pg": sorted(pg_lib),
        "v_ports": sorted(v_ports), "v_style": ver["style"],
        "lef_pg_kind": dict(sorted(lef.get("pg_kind", {}).items())),
        "lib_pg_type": dict(sorted(lib.get("pg_type", {}).items())),
    }

    if not (sig_lef or pg_lef):
        ok = False
        F.append(Finding(
            rule="LEF_NO_PIN", severity="ERROR", macro=name, file=cite(lef_p),
            message=(f"macro '{name}': LEF declares no `PIN <n> … END <n>` "
                     f"block. A macro with no pins cannot be connected to "
                     f"anything.")))

    for a_name, a_set, b_name, b_set, rule in (
            ("LEF", sig_lef, "Liberty", sig_lib, "SIGNAL_PIN_DISAGREE"),
            ("LEF", pg_lef, "Liberty", pg_lib, "PG_PIN_DISAGREE")):
        only_a, only_b = sorted(a_set - b_set), sorted(b_set - a_set)
        if only_a or only_b:
            ok = False
            F.append(Finding(
                rule=rule, severity="ERROR", macro=name,
                message=(f"macro '{name}': {a_name} and {b_name} disagree "
                         f"about the interface — only in {a_name}: "
                         f"{only_a or '[]'}; only in {b_name}: "
                         f"{only_b or '[]'}. The placer connects what the LEF "
                         f"exposes and STA times what the Liberty declares; "
                         f"a pin only one of them knows is either unconnected "
                         f"or untimed.")))

    # ── 6b. WHICH RAIL each supply pin is ─────────────────────────────
    # THE NAME SETS AGREEING IS NOT THE SUPPLIES AGREEING. `PG_PIN_DISAGREE`
    # above compares only WHICH supply pins exist; two views can list the
    # same two names and still disagree about which of them is ground. That
    # is not hypothetical: MEASURED on a real kit produced by this flow's own
    # producer, a LEF declaring `USE POWER` on one pin and `USE GROUND` on
    # the other was paired with a Liberty declaring BOTH as `primary_power`,
    # and every clause in this gate was green over it. A Liberty that calls
    # ground a power rail merges the two supply domains for every consumer
    # that reads it — and `scripts/magic/lef.tcl`'s `lef nocheck $VDD_NETS
    # $GND_NETS` means the producer of the LEF half was explicitly told not
    # to check these very pins, so no tool upstream of here looks at all.
    _LIB_RAIL = {"primary_power": "power", "backup_power": "power",
                 "internal_power": "power", "pwell": "ground",
                 "primary_ground": "ground", "backup_ground": "ground",
                 "internal_ground": "ground", "nwell": "power",
                 "deepnwell": "power", "deeppwell": "ground"}
    lef_kind = lef.get("pg_kind", {}) or {}
    lib_type = lib.get("pg_type", {}) or {}
    rail_conflict, rail_unstated = [], []
    for b in sorted(pg_lef & pg_lib):
        a = (lef_kind.get(b) or "").lower()
        d = (lib_type.get(b) or "").lower()
        if not d:
            rail_unstated.append(b)
            continue
        mapped = _LIB_RAIL.get(d)
        if mapped is None:
            # An unknown pg_type is NOT read as agreement. It is reported as
            # undetermined, under the same rule, so a token this gate does
            # not model cannot pass by being unrecognised.
            rail_unstated.append(b)
            continue
        if a and mapped != a:
            rail_conflict.append((b, a, d))
    if rail_conflict or rail_unstated:
        ok = False
        parts = []
        if rail_conflict:
            parts.append("; ".join(
                f"'{b}': LEF says USE {a.upper()}, Liberty says pg_type {d}"
                for b, a, d in rail_conflict))
        if rail_unstated:
            parts.append(
                f"supply pin(s) {rail_unstated} carry a Liberty `pg_pin` "
                f"whose `pg_type` is absent or is a token this gate does not "
                f"model, so which rail they are was NOT established")
        F.append(Finding(
            rule="PG_TYPE_DISAGREE", severity="ERROR", macro=name,
            file=cite(lib_p),
            message=(f"macro '{name}': the LEF and the Liberty name the same "
                     f"supply pins and disagree about WHICH RAIL they are — "
                     f"{'. '.join(parts)}. A ground declared as a power rail "
                     f"merges the two supply domains in every tool that reads "
                     f"this Liberty, and Magic's own LEF writer is told "
                     f"`lef nocheck` on exactly these pins, so nothing before "
                     f"this gate looked.")))

    # Verilog: every port it declares must be a pin the LEF knows; every
    # SIGNAL pin must appear. PG may be omitted — narrow, stated exception.
    v_unknown = sorted(v_ports - sig_lef - pg_lef)
    v_missing_sig = sorted(sig_lef - v_ports)
    pg_absent = sorted(pg_lef - v_ports)
    detail["interface"]["v_pg_ports_absent"] = pg_absent
    if v_unknown:
        ok = False
        F.append(Finding(
            rule="V_PORT_NOT_IN_LEF", severity="ERROR", macro=name,
            file=cite(v_p),
            message=(f"macro '{name}': Verilog declares port(s) {v_unknown} "
                     f"that the LEF exposes as neither signal nor supply. "
                     f"Simulation will drive a connection the physical macro "
                     f"has nowhere to make.")))
    if v_missing_sig:
        ok = False
        F.append(Finding(
            rule="V_MISSING_SIGNAL_PIN", severity="ERROR", macro=name,
            file=cite(v_p),
            message=(f"macro '{name}': signal pin(s) {v_missing_sig} are in "
                     f"the LEF and absent from the Verilog view. The kit will "
                     f"be placed and routed with a connection the simulation "
                     f"model cannot see, so no testbench can ever exercise "
                     f"it.")))
    if pg_absent:
        F.append(Finding(
            rule="V_PG_PORTS_ABSENT", severity="INFO", macro=name,
            message=(f"macro '{name}': supply pin(s) {pg_absent} are declared "
                     f"in the LEF and the Liberty and not in the Verilog "
                     f"view. That is the convention for a logical simulation "
                     f"model and is accepted here; it is recorded so the "
                     f"exception is visible and cannot widen.")))

    # ── 7. REACHABILITY — the `-pinonly` correctness axis ─────────────────
    # UPSTREAM, MEASURED (`librelane/scripts/magic/lef.tcl` in the pinned
    # image): the LEF is produced by `lef write … [-hide] [-pinonly]`, and
    # `MAGIC_WRITE_LEF_PINONLY` decides whether a labelled port PLUS the
    # connected metal on that layer is the pin, or whether only the labelled
    # patch is the pin and the rest of the net becomes an OBSTRUCTION. Get it
    # wrong and the next designer's router either cannot reach the pin or
    # shorts to the internal net. Upstream ships the knob and checks NOTHING
    # about the result; these are the parts of that outcome a delivered LEF
    # can be held to on its own.
    geom = lef["geometry"]
    no_area = sorted(b for b in (sig_lef | pg_lef) if not geom.get(b))
    detail["interface"]["pins_without_routable_area"] = no_area
    if no_area:
        ok = False
        F.append(Finding(
            rule="PIN_NO_ROUTABLE_AREA", severity="ERROR", macro=name,
            file=cite(lef_p),
            message=(f"macro '{name}': pin(s) {no_area} are declared with no "
                     f"RECT or POLYGON under any PORT — a name with no place. "
                     f"The router is told the pin exists and given nowhere to "
                     f"land on it, so the connection cannot be made no matter "
                     f"how the macro is placed.")))

    if size is not None:
        # THE MACRO'S OWN FRAME, NOT THE GDS FRAME. A LEF PIN rect is
        # expressed relative to the macro ORIGIN; `FOREIGN` states where the
        # GDS STREAM sits relative to that origin and moves no pin. Using the
        # FOREIGN-derived lower-left here reported every pin of a correctly
        # registered kit as stranded — measured on the fixture whose
        # `FOREIGN macro_a 0 -30.32` legitimately explains a 30 um stream
        # offset. `lef["origin_ll"]` is the ORIGIN/LEF-default answer from the
        # SAME shared parser, asked without the FOREIGN statement in view.
        fx, fy = lef["origin_ll"]
        bx0, by0, bx1, by1 = fx, fy, fx + size[0], fy + size[1]
        stranded = []
        for b in sorted(geom):
            for (x0, y0, x1, y1) in geom[b]:
                # ENTIRELY outside — no overlap at all. Deliberately not a
                # tolerance test: a pin legitimately reaches, and often
                # overhangs, the macro edge, so anything short of "shares no
                # area with the outline at all" would refuse correct kits.
                if x1 <= bx0 or x0 >= bx1 or y1 <= by0 or y0 >= by1:
                    stranded.append((b, [x0, y0, x1, y1]))
        if stranded:
            ok = False
            detail["interface"]["stranded_pin_geometry"] = [
                {"pin": b, "rect_um": r} for b, r in stranded]
            F.append(Finding(
                rule="PIN_GEOMETRY_OUTSIDE_OUTLINE", severity="ERROR",
                macro=name, file=cite(lef_p),
                message=(f"macro '{name}': pin geometry lies wholly outside "
                         f"the declared outline "
                         f"({bx0:.4f},{by0:.4f})-({bx1:.4f},{by1:.4f}) um: "
                         + "; ".join(f"{b} at {r}" for b, r in stranded[:4])
                         + ". The placer reserves the outline and nothing "
                           f"else; area outside it belongs to whatever is "
                           f"placed there next.")))

    # OBSTRUCTIONS — ADVISORY, and here is exactly why it is not BLOCKING.
    # Whether the internal nets were correctly obstructed is a question about
    # the GDS's layers, and this gate cannot map a LEF layer name onto a GDS
    # layer number without the tech LEF. What IS decidable from the kit alone
    # is that a macro carrying real layout declares NO obstruction at all —
    # the signature of a LEF written with neither `-hide` nor `-pinonly`,
    # which tells the router the inside of the macro is free space. It is a
    # signature and not a proof (a leaf macro whose every shape is a pin
    # legitimately has no OBS), so it is DISCLOSED on the verdict word and
    # never fails the step.
    detail["obstructions_declared"] = bool(lef["has_obs"])
    obs_undetermined = bool(geom and not lef["has_obs"] and geom_records > 0)
    detail["obstruction_policy_determined"] = not obs_undetermined
    if obs_undetermined:
        F.append(Finding(
            rule="OBSTRUCTION_POLICY_NOT_DETERMINED", severity="WARNING",
            macro=name, file=cite(lef_p),
            message=(f"macro '{name}': the LEF declares pins and no `OBS` "
                     f"section while the GDS carries "
                     f"{geom_records} geometry record(s). Either this macro "
                     f"genuinely has no shape to obstruct, or it was written "
                     f"without an abstraction policy and the router will "
                     f"treat its interior as free space and short to the "
                     f"internal nets. This gate cannot tell those apart from "
                     f"the kit alone — NOT DETERMINED, disclosed, never "
                     f"silently accepted.")))

    # ── 8. timing characterisation — DISCLOSED, not assumed ───────────────
    # `analyze_liberty` returns (has_timing, numbers, cell_name). Having a
    # timing attribute is NOT the same as carrying a delay: the documented
    # stub `cell(x) { area : 10000 ; }` has neither, and an all-zero NLDM
    # table has the attribute and no delay. Non-degenerate requires BOTH —
    # the same two-part predicate `analog_liberty_nonzero_delay_check` applies
    # to its own findings, read off the same helper so the two cannot drift.
    has_timing, values, why = True, [], ""
    if analyze_liberty is not None:
        try:
            has_timing, values, _cell = analyze_liberty(lib_text)
        except Exception as exc:  # pragma: no cover - defensive
            has_timing, values = True, [1.0]
            why = f"Liberty could not be analysed: {exc}"
    nonzero = [v for v in values if v == v and v != 0]
    lib_ok = bool(has_timing and nonzero)
    if not why:
        if not has_timing:
            why = "no timing-bearing attribute at all"
        elif not nonzero:
            why = f"{len(values)} timing number(s), every one of them zero"
    detail["liberty_timing"] = {"non_degenerate": lib_ok,
                                "numbers_seen": len(values),
                                "nonzero_numbers": len(nonzero),
                                "reason": why}
    if not lib_ok:
        F.append(Finding(
            rule="LIB_TIMING_UNCHARACTERISED", severity="WARNING", macro=name,
            file=cite(lib_p),
            message=(f"macro '{name}': the Liberty carries no non-zero timing "
                     f"number ({why}). Integration STA over this kit is "
                     f"vacuous — every path through the macro has zero delay, "
                     f"so it can never violate setup or hold. Signed off in "
                     f"the PASS_TIMING_UNCHARACTERISED tier, never as a plain "
                     f"PASS.")))

    detail["status"] = "PASS" if ok else "FAIL"
    detail["timing_uncharacterised"] = not lib_ok
    detail["obstruction_not_determined"] = obs_undetermined
    return ok, F, detail


def run_audit(project: Path, tol_pct: float = DEFAULT_TOL_PCT,
              tol_um: float = DEFAULT_TOL_UM) -> Result:
    result = Result()
    hm_dir = hardmacro_dir(project)
    packages = discover_packages(hm_dir)

    if not packages:
        # NOTHING TO CHECK IS NOT A PASS. rc 2, named reason, and the verdict
        # word says what was and was not established.
        result.verdict_tier = "NOT_DETERMINED"
        result.findings.append(Finding(
            rule="NO_HARDMACRO_PACKAGE", severity="INFO",
            message=(f"`{hm_dir.name}/` under phase3/stage4 holds no "
                     f"{'/'.join(VIEW_EXTS)} view. Searched and found nothing "
                     f"for: {', '.join(unmatched_view_globs(project))}. "
                     f"Step 37.5ip is the cell/IP "
                     f"path TERMINAL: what it delivers is the kit, so with no "
                     f"kit on disk NOTHING about one has been established — "
                     f"this is NOT a statement that the IP is deliverable.")))
        result.summary = {
            "skipped": True, "reason": "no_hardmacro_package",
            "hardmacro_dir": str(hm_dir),
            "hardmacro_dir_exists": hm_dir.is_dir(),
            "searched_and_absent": unmatched_view_globs(project),
            "packages": [], "verdict_tier": "NOT_DETERMINED",
            "pass": True,
        }
        return result

    details, failed, uncharacterised, undetermined = [], [], [], []
    for name in sorted(packages):
        ok, findings, detail = check_package(
            name, packages[name], project, tol_pct, tol_um)
        result.findings.extend(findings)
        details.append(detail)
        if not ok:
            failed.append(name)
            continue
        if detail.get("timing_uncharacterised"):
            uncharacterised.append(name)
        if detail.get("obstruction_not_determined"):
            undetermined.append(name)

    result.passed = not failed
    # THE TIER WORD RIDES THE VERDICT AND MUST NOT CONTRADICT IT. The default
    # is the plain-PASS word; on a refusal a consumer reading `verdict_tier`
    # alone would otherwise read "PASS" out of a report whose `passed` is
    # false.
    if failed:
        result.verdict_tier = "FAIL"
    # RANKED, and the ranking is an argument: an axis this gate could not
    # DETERMINE is a stronger caveat than one it determined to be absent. A
    # kit whose obstruction policy is unknown may be wrong in somebody else's
    # router; a kit whose Liberty carries no delay is knowably uncharacterised.
    if result.passed and undetermined:
        result.verdict_tier = "PASS_OBSTRUCTION_NOT_DETERMINED"
    elif result.passed and uncharacterised:
        result.verdict_tier = "PASS_TIMING_UNCHARACTERISED"
    result.summary = {
        "skipped": False,
        "reason": "",
        "hardmacro_dir": str(hm_dir),
        "total_packages": len(packages),
        "complete": len(packages) - len(failed),
        "failed": failed,
        "timing_uncharacterised": uncharacterised,
        "obstruction_not_determined": undetermined,
        "tol_pct": tol_pct,
        "tol_um": tol_um,
        "packages": details,
        "verdict_tier": result.verdict_tier,
        "pass": result.passed,
    }
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=GATE, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path,
                    help="project root (holds phase3/stage4/hardmacro/)")
    ap.add_argument("--json", default=None, help="write the JSON report here")
    ap.add_argument("--tol-pct", type=float, default=DEFAULT_TOL_PCT,
                    help=(f"max LEF-SIZE-vs-GDS-bbox delta %% "
                          f"(default {DEFAULT_TOL_PCT})"))
    ap.add_argument("--tol-um", type=float, default=DEFAULT_TOL_UM,
                    help=(f"max LEF-frame-vs-GDS-bbox registration offset in "
                          f"microns (default {DEFAULT_TOL_UM})"))
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return _vx.RC_VACUOUS

    result = run_audit(args.project_dir, args.tol_pct, args.tol_um)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(asdict(result), indent=2,
                                          ensure_ascii=False) + "\n")

    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)
    pass_token = (result.verdict_tier
                  if result.verdict_tier.startswith("PASS_") else "PASS")

    if not args.json:
        print(_vx.verdict_line(GATE, result.passed, skipped, reason,
                               pass_token=pass_token))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        # LAST, SHORT, on every path the gate can leave by — including the
        # `--json` path, which is the ONLY path the FLOW ever takes.
        _vx.announce_vacuous(GATE, reason)

    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
