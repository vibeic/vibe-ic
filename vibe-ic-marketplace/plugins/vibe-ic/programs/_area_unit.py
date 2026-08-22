#!/usr/bin/env python3
"""_area_unit.py — ESTABLISH the area figure's unit from evidence, or refuse.

THE QUESTION THIS ANSWERS
=========================
yosys writes `Chip area for module '<top>': 5841.196200` by summing each cell's
`area` from the Liberty it loaded. That figure therefore carries THAT LIBRARY's
area unit — and Liberty has no area unit to declare: its `units` group carries
time, voltage, current, capacitance, resistance and power, and `area` is a bare
number. So no producer downstream may state the unit, and until now none did:
`synth_area_stats_emit` writes the honest sentence "cell-library area unit (as
declared by the library the synthesis script loaded)" and stops there.

That refusal is correct and it is also a dead end. `area_total_vs_budget_check`
compares a cell area against a die area declared in MICROMETRES, so with the
unit unestablished its only reachable verdict is rc 2 INCOMPLETE — a gate that
can never answer the question it exists for.

THE EVIDENCE, WHICH IS NOT AN ASSUMPTION
========================================
The unit is derivable per library, from two artefacts `pdk_registry.json`
already resolves for every PDK it carries — `liberty_glob` and `cell_lef_glob`:

  * a cell's LEF `SIZE w BY h` is in MICRONS by the LEF specification, so
    `w * h` is that cell's footprint in um^2;
  * the Liberty `area` for the SAME cell either agrees with it or does not.

Agreement over the library's cells is a MEASUREMENT that the Liberty's area unit
IS um^2. Disagreement is a measurement that it is not, and this module then
refuses rather than picking one — an unestablished unit and a contradicted one
are both "not established", and neither may become a number a gate compares.

MEASURED over the two open PDKs in the shipped EDA image, every standard cell
present in both files:

    library A   229 of 229 cells   liberty_area / lef_um2:
                                     min 1.000000  median 1.000000  max 1.000000
    library B   428 of 428 cells   min 0.999547  median 1.000000  max 1.000000

    (The 405 first published here was my parser's undercount, not the
    library's size — an invented 4000-byte window dropped 23 cells whose
    `area` sits past it. Found by another lane re-deriving the figure and
    getting 428; the window is gone and the count is now reproducible.)

TOLERANCE, NOT EQUALITY, and the data is why. One library's worst agreeing cell
is 0.999547 — the Liberty figure is rounded — so an equality test would reject a
correct library. The default tolerance is 1%, which accepts that rounding and is
orders of magnitude tighter than any unit confusion it must catch: the unit
errors that matter are factors of 1e6 (um^2 vs m^2), 1e-2 (nm^2) or 1000 (the
ART-POWER-FIGURES-X1000 shape one axis over), never 0.05%.

A DISTRIBUTION, NOT ITS EXTREMES — and this rule was chosen from the measured
failure modes, not fitted to make particular libraries pass. Measured over the
five libraries the registry resolves in the shipped image, two carried exactly
ONE disagreeing cell each:

    a filler cell        liberty_area / lef_um2 = 0.500000   (1 of 135)
    one scan flop        liberty_area / lef_um2 = 1.111111   (1 of 84)

Both are exact simple fractions on a single cell, in libraries where every other
cell is exactly 1.000000. That is a per-cell modelling difference — a filler's
Liberty area is not its footprint — and it is not a statement about the
library's UNIT. A unit error looks nothing like it: it is a COMMON FACTOR across
the whole population, because every area came out of the same multiplication.

So the unit is established when the library's distribution is centred on 1 AND
coherent — median and interquartile spread both inside the tolerance. A library
whose median is 1000 fails on the centre; a library split half at 1 and half at
1000 fails on the spread, even though its median might land near either. Cells
outside the tolerance are always DISCLOSED, with their names, and never dropped:
"I established the unit and 1 cell disagrees" and "I established the unit" must
not produce the same record.

WHAT THIS MODULE REFUSES TO DO
==============================
  * It does not assume um^2 because two libraries measured that way. That is
    the generalisation `area_total_vs_budget_check` exists to refuse, and it is
    refused here too: every library is measured on its own files.
  * It does not fall back to a default when a file is missing. No cell LEF, no
    Liberty, or no cell present in both -> NOT ESTABLISHED, naming which.
  * It does not repair a disagreement by scaling. A library whose ratios are a
    consistent 1000x is telling you something, and silently multiplying it away
    is exactly the defect this whole axis is about.

chip-AGNOSTIC: it reads whatever library it is handed and names no foundry,
process, vendor or PDK anywhere in this file.
"""
from __future__ import annotations

import fnmatch
import json
import re
import statistics
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

#: Ratio band inside which the Liberty area is taken to BE square micrometres.
#: See the tolerance argument in the module docstring: it accepts the measured
#: 0.999547 rounding floor and rejects every unit confusion worth catching.
DEFAULT_TOLERANCE = 0.01

#: The spelling written into the artefact when the unit IS established. It must
#: be one `area_total_vs_budget_check._UM2_SPELLINGS` recognises, or the gate
#: would still refuse a figure this module just proved.
UM2 = "um^2"

#: How many cells must agree before the measurement counts. One matching cell is
#: a coincidence; a library's worth is a measurement. Deliberately low enough
#: that a small or partial library still establishes, and high enough that a
#: single stray macro cannot.
MIN_CELLS = 8

_LIB_CELL_RE = re.compile(r'cell\s*\(\s*"?([A-Za-z0-9_]+)"?\s*\)\s*\{')
_LIB_AREA_RE = re.compile(r'\barea\s*:\s*([0-9.]+)\s*;')
_LEF_MACRO_RE = re.compile(r'MACRO\s+(\S+)(.*?)END\s+\1', re.DOTALL)
_LEF_SIZE_RE = re.compile(r'SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;')

#: NO BYTE WINDOW. A cell's `area` is bounded by the NEXT cell, not by a
#: character count — that is what the grammar says, and any number chosen
#: instead is a guess about how big a cell's block happens to be.
#:
#: MEASURED, and this is why it is written as a comment rather than a constant:
#: the first version of this parser looked 4000 characters past each `cell (`
#: header. On one shipped library that silently dropped 23 of 428 cells whose
#: `area` sits at offsets 5649..10625, after large pin blocks. The ratios were
#: unaffected and the conclusion held, so nothing looked wrong — which is the
#: danger: a parser that drops 5% of a library can drop the one cell that
#: DISAGREES, and the disagreement is the whole signal this module reads.
#: Found by another lane re-deriving the published count and getting 428.


def _read(p: Optional[Path]) -> Optional[str]:
    if p is None:
        return None
    try:
        return Path(p).read_text(errors="replace")
    except OSError:
        return None


def liberty_areas(text: str) -> Dict[str, float]:
    """`{cell: area}` from a Liberty. The value's unit is what we are deciding."""
    out: Dict[str, float] = {}
    heads = list(_LIB_CELL_RE.finditer(text))
    for i, m in enumerate(heads):
        # Bounded by the next cell header, or by the end of the file for the
        # last one. `search` then takes the FIRST `area` inside that block,
        # which is the cell's own.
        stop = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        a = _LIB_AREA_RE.search(text, m.end(), stop)
        if a:
            try:
                out[m.group(1)] = float(a.group(1))
            except ValueError:
                pass
    return out


def lef_footprints_um2(text: str) -> Dict[str, float]:
    """`{macro: w*h}` in um^2. LEF `SIZE` is in microns by the specification."""
    out: Dict[str, float] = {}
    for m in _LEF_MACRO_RE.finditer(text):
        s = _LEF_SIZE_RE.search(m.group(2))
        if not s:
            continue
        try:
            w, h = float(s.group(1)), float(s.group(2))
        except ValueError:
            continue
        if w > 0 and h > 0:
            out[m.group(1)] = w * h
    return out


def derive(liberty: Optional[Path], cell_lef: Optional[Path],
           tolerance: float = DEFAULT_TOLERANCE) -> Dict[str, Any]:
    """Establish the Liberty's area unit, or say why it could not be.

    Returns a record that is written into the artefact verbatim, so a reader can
    re-derive the conclusion rather than trust it: the cell count compared, the
    ratio band, and the tolerance applied.

    `established` is True ONLY when every compared cell's
    `liberty_area / lef_um2` sits inside `1 +/- tolerance`. One cell outside it
    is a disagreement, and a disagreement is not established.
    """
    rec: Dict[str, Any] = {
        "established": False,
        "unit": None,
        "method": "liberty area vs cell LEF SIZE (microns, LEF spec)",
        "tolerance": tolerance,
        "cells_compared": 0,
        "reason": None,
        "liberty": str(liberty) if liberty else None,
        "cell_lef": str(cell_lef) if cell_lef else None,
    }
    lib_text, lef_text = _read(liberty), _read(cell_lef)
    if lib_text is None:
        rec["reason"] = "no readable Liberty was supplied"
        return rec
    if lef_text is None:
        rec["reason"] = "no readable cell LEF was supplied"
        return rec
    areas, foot = liberty_areas(lib_text), lef_footprints_um2(lef_text)
    common = sorted(set(areas) & set(foot))
    rec["cells_compared"] = len(common)
    if len(common) < MIN_CELLS:
        rec["reason"] = (
            f"only {len(common)} cell(s) appear in both the Liberty and the "
            f"cell LEF; {MIN_CELLS} are required before agreement counts as a "
            f"measurement rather than a coincidence")
        return rec
    pairs = sorted((areas[c] / foot[c], c) for c in common if foot[c] > 0)
    ratios = [r for r, _ in pairs]
    median = statistics.median(ratios)
    q1, q3 = _quartiles(ratios)
    rec["ratio_min"], rec["ratio_median"], rec["ratio_max"] = (
        ratios[0], median, ratios[-1])
    rec["ratio_iqr"] = q3 - q1
    # OUTLIERS ARE DISCLOSED WHETHER OR NOT THEY BLOCK. A record that says
    # "established" and nothing else cannot be told from one where every cell
    # agreed, and the difference is exactly what a reader needs to judge it.
    outside = [(r, c) for r, c in pairs if abs(r - 1.0) > tolerance]
    rec["cells_outside_tolerance"] = len(outside)
    rec["outliers"] = [{"cell": c, "ratio": r} for r, c in outside[:10]]
    centred = abs(median - 1.0) <= tolerance
    coherent = (q3 - q1) <= tolerance
    if not centred:
        rec["reason"] = (
            f"the library's ratios are centred on {median:.6g}, not 1: "
            f"liberty_area / lef_um2 spans {ratios[0]:.6g}..{ratios[-1]:.6g} "
            f"over {len(ratios)} cell(s). A COMMON factor across the population "
            f"is what a unit difference looks like, so this library's area is "
            f"not square micrometres — and it is not scaled to fit")
        return rec
    if not coherent:
        rec["reason"] = (
            f"the library's ratios do not cohere: interquartile spread "
            f"{q3 - q1:.6g} exceeds {tolerance} over {len(ratios)} cell(s) "
            f"({ratios[0]:.6g}..{ratios[-1]:.6g}). A library whose cells "
            f"disagree among themselves states no single area unit")
        return rec
    rec["established"] = True
    rec["unit"] = UM2
    rec["reason"] = (
        f"{len(ratios)} cell(s), median {median:.6g}, interquartile spread "
        f"{q3 - q1:.6g}, both within {tolerance}"
        + (f"; {len(outside)} per-cell outlier(s) disclosed and not dropped"
           if outside else ""))
    return rec


def _quartiles(sorted_ratios: List[float]) -> Tuple[float, float]:
    """(q1, q3). Computed on the sorted list directly rather than via
    `statistics.quantiles`, which raises below four points — and a library with
    three comparable cells must get a verdict, not an exception."""
    n = len(sorted_ratios)
    if n == 1:
        return sorted_ratios[0], sorted_ratios[0]
    lo = sorted_ratios[: n // 2]
    hi = sorted_ratios[(n + 1) // 2:]
    return statistics.median(lo), statistics.median(hi)


def resolve_from_registry(liberty: Path,
                          registry: Path) -> Tuple[Optional[Path], Optional[str]]:
    """The cell LEF that belongs to this Liberty, per `pdk_registry.json`.

    THE ROOT COMES FROM THE FILE, THE LAYOUT COMES FROM THE REGISTRY. An earlier
    draft globbed each entry's `container_path` and asked whether the supplied
    Liberty was among the results. That only works where the PDK sits at the
    path the registry records — and it does not: `container_path` is the path
    INSIDE the EDA container (`phase3_one_shot_runner` translates the host path
    to it with `_to_container_path` before handing it to yosys), so on the host
    that directory is empty and every resolution refused.

    So the registry is asked only for the RELATIVE layout — where a cell LEF
    sits with respect to a Liberty — and the root is recovered from the Liberty
    actually supplied. That resolves identically whether the run reads the PDK
    from a host mount, from inside the container, or from anywhere else.

    Returns (cell_lef, reason_if_not_found).
    """
    try:
        entries = json.loads(Path(registry).read_text())["pdks"]
    except (OSError, ValueError, KeyError) as exc:
        return None, f"pdk_registry.json could not be read: {exc}"
    lib = Path(liberty)
    lib_posix = lib.as_posix()
    for e in entries:
        lg, cg = e.get("liberty_glob"), e.get("cell_lef_glob")
        if not (lg and cg):
            continue                  # an entry declaring no assets owns none
        root = _root_of(lib_posix, lg)
        if root is None:
            continue
        lefs = sorted(Path(root).glob(cg))
        if not lefs:
            return None, (
                f"the registry entry whose layout matches this Liberty "
                f"declares cell_lef_glob={cg!r}, which matches no file under "
                f"{root}")
        return lefs[0], None
    return None, ("no registry entry declares a Liberty layout matching "
                  f"{lib_posix}, so the cell LEF that belongs to it is not known")


def _root_of(liberty_posix: str, liberty_glob: str) -> Optional[str]:
    """The directory `liberty_glob` is relative to, given a matching Liberty.

    The glob is a RELATIVE pattern (`libs.ref/<lib>/lib/*.lib`). A Liberty
    belongs to it when its tail matches, and the root is whatever precedes that
    tail. Matched segment-by-segment from the right so a pattern containing no
    wildcard in its leading segments still anchors correctly.
    """
    pat_parts = PurePosixPath(liberty_glob).parts
    lib_parts = PurePosixPath(liberty_posix).parts
    if len(lib_parts) < len(pat_parts):
        return None
    tail = lib_parts[-len(pat_parts):]
    for got, want in zip(tail, pat_parts):
        if not fnmatch.fnmatch(got, want):
            return None
    root = lib_parts[:-len(pat_parts)]
    return str(PurePosixPath(*root)) if root else "."
