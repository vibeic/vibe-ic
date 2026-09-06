#!/usr/bin/env python3
"""_declared_die — ONE derivation of the die, for every program that needs it.

THE DEFECT (vibe-ic#2058 FP-15, from FP-08 measured by lane czspmfp).
Nine programs read a DEF's `DIEAREA` and call the result "the die". On a SLOT
run that is false: `ppl place_pins` places pins on the DIE boundary and has no
core-boundary mode, so the rectangle OpenROAD is handed as `-die_area` is the
PLACEABLE CORE and the DEF's `DIEAREA` states that core. MEASURED and recorded
in `signoff_metrics_aggregate._die_bbox`: 1052 x 1647 um stated as the die of a
1936 x 2531 um slot. Every consumer of that number — a die area, a power
density, a tap-coverage region, a pad-ring rectangle, a pin side — has been
computing against the core on every slot run since that fix landed.

THE ONE AUTHORITY. `reports/phase3/floorplan_rectangles.json`, which
`phase3_one_shot_runner.step_pnr` writes on every run:

    {"die_rect_um": [x0, y0, x1, y1],
     "die_source": "<how the run settled on it>",
     "floorplan_rect_um": [...] | null,
     "floorplan_rect_is_the_die": true | false}

It is the same record `signoff_metrics_aggregate._declared_die_rect_um` and
`phase3_one_shot_runner.declared_die_rect` already read, so this module adds a
consumer rather than a second opinion. The path constant is spelled in three
places for the reason `signoff_metrics_aggregate` states — importing a 2.7 MB
runner to read one path is worse. Two of the three are pinned against each
other by `test_ct03_floorplan_rect_and_tapeout_declarations.py:236`; this third
one is pinned against BOTH by `tests/test_one_derivation_of_the_die.py::
test_the_three_spellings_of_the_record_path_agree`, because a constant nobody
compares is a constant that drifts.

WHAT AN ABSENT RECORD IS. NOT_MEASURED, by name. A tree written before the
record existed, or a bare DEF handed to a checker with no run around it, has
not told anyone what its die is. `resolve()` therefore ALWAYS returns whether
the answer is DECLARED, and a caller that goes on to use the DEF rectangle has
to publish that it did:

    r = resolve(project, def_rect_um=...)
    r.rect            the rectangle to use, or None when neither source spoke
    r.is_declared     True only when the run's own record answered
    r.basis           one sentence naming which source and why — for the report

MEASURED CONTROL. spm x gf180mcuD (lane czspmfp, image label 0.3.46) is a
NON-slot run: its record says `die_rect_um [0, 0, 3162, 3162]` and
`floorplan_rect_is_the_die: true`, and every DEF it wrote carries
`DIEAREA ( 0 0 ) ( 6324000 6324000 )` at `UNITS DISTANCE MICRONS 2000` — the
same 3162 x 3162 um. On such a run this module returns the DEF's own answer and
nothing any consumer computes may move.

chip-AGNOSTIC: one relative artefact path and the DEF grammar. No design, PDK,
vendor or dimension literal.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

#: The record `phase3_one_shot_runner.step_pnr` writes on every run.
FLOORPLAN_RECTANGLES_REL = "reports/phase3/floorplan_rectangles.json"

#: Both DEF spellings, and a rectilinear polygon DIEAREA (>2 points) whose
#: bounding box is the die outline. Matching to the `;` so a multi-line
#: rectilinear record is read whole rather than truncated at the first corner.
_DIEAREA_RE = re.compile(r"(?m)^\s*DIEAREA\b([^;]*);")
_INT_RE = re.compile(r"-?\d+")
_UNITS_RE = re.compile(r"(?m)^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)")

#: What `source` can say. Named constants so a consumer's report cannot spell
#: the tier three different ways.
DECLARED = "DECLARED_DIE_RECORD"
DEF_FALLBACK = "DEF_DIEAREA_FALLBACK"
NOT_MEASURED = "NOT_MEASURED"


@dataclass
class DieRect:
    """The die, and — always — where it came from."""
    rect: Optional[Tuple[float, float, float, float]]
    source: str
    basis: str
    record_rel: str = FLOORPLAN_RECTANGLES_REL
    record_present: bool = False
    floorplan_rect_um: Optional[List[float]] = None
    floorplan_rect_is_the_die: Optional[bool] = None
    def_rect_um: Optional[List[float]] = None

    @property
    def is_declared(self) -> bool:
        return self.source == DECLARED

    @property
    def measured(self) -> bool:
        return self.rect is not None

    def width_um(self) -> Optional[float]:
        return None if self.rect is None else self.rect[2] - self.rect[0]

    def height_um(self) -> Optional[float]:
        return None if self.rect is None else self.rect[3] - self.rect[1]

    def area_um2(self) -> Optional[float]:
        w, h = self.width_um(), self.height_um()
        return None if w is None or h is None else w * h

    def as_dict(self) -> dict:
        return {"die_rect_um": list(self.rect) if self.rect else None,
                "die_source": self.source,
                "die_basis": self.basis,
                "die_record": self.record_rel,
                "die_record_present": self.record_present,
                "floorplan_rect_um": self.floorplan_rect_um,
                "floorplan_rect_is_the_die": self.floorplan_rect_is_the_die,
                "def_diearea_um": self.def_rect_um}


def _usable(rect: Any) -> bool:
    return (isinstance(rect, (list, tuple)) and len(rect) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    for v in rect)
            and rect[2] > rect[0] and rect[3] > rect[1])


def def_diearea_um(def_text: str) -> Optional[List[float]]:
    """The DEF's own DIEAREA in MICRONS, or None. NOT the die — see resolve()."""
    m = _DIEAREA_RE.search(def_text)
    if not m:
        return None
    nums = [int(n) for n in _INT_RE.findall(m.group(1))]
    if len(nums) < 4 or len(nums) % 2:
        return None
    xs, ys = nums[0::2], nums[1::2]
    u = _UNITS_RE.search(def_text)
    dbu = float(u.group(1)) if u and int(u.group(1)) > 0 else 1000.0
    rect = [min(xs) / dbu, min(ys) / dbu, max(xs) / dbu, max(ys) / dbu]
    return rect if _usable(rect) else None


def declared(project: Path) -> Tuple[Optional[List[float]], str, dict]:
    """(rect_um, why, the whole record) from the run's own floorplan record."""
    p = Path(project) / FLOORPLAN_RECTANGLES_REL
    if not p.is_file():
        return None, f"{FLOORPLAN_RECTANGLES_REL} is absent", {}
    try:
        rec = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        return None, f"{FLOORPLAN_RECTANGLES_REL} is unreadable ({exc})", {}
    if not isinstance(rec, dict):
        return None, f"{FLOORPLAN_RECTANGLES_REL} is not an object", {}
    rect = rec.get("die_rect_um")
    if not _usable(rect):
        return None, (f"{FLOORPLAN_RECTANGLES_REL} carries no usable "
                      f"`die_rect_um` ({rect!r})"), rec
    return [float(v) for v in rect], str(
        rec.get("die_source") or "the run's own floorplan record"), rec


def resolve(project: Optional[Path],
            def_text: Optional[str] = None,
            def_rect_um: Optional[Sequence[float]] = None,
            allow_def_fallback: bool = True) -> DieRect:
    """THE DIE, and a `basis` a report must publish verbatim.

    `allow_def_fallback=False` is for a consumer whose answer is only as good
    as the die — a power density, a coverage region, a ring rectangle. It gets
    `rect=None` and `source=NOT_MEASURED` rather than a confident number about
    the core, and the caller reports NOT_MEASURED naming the record.
    """
    drect = (list(def_rect_um) if def_rect_um is not None and _usable(def_rect_um)
             else (def_diearea_um(def_text) if def_text else None))
    if project is None:
        why = "no project directory was given, so the run's own record could not be read"
        rec: dict = {}
        rect = None
    else:
        rect, why, rec = declared(Path(project))
    if rect is not None:
        return DieRect(rect=(rect[0], rect[1], rect[2], rect[3]),
                       source=DECLARED,
                       basis=f"the run's declared die rectangle — {why}",
                       record_present=True,
                       floorplan_rect_um=rec.get("floorplan_rect_um"),
                       floorplan_rect_is_the_die=rec.get(
                           "floorplan_rect_is_the_die"),
                       def_rect_um=drect)
    if drect is not None and allow_def_fallback:
        return DieRect(
            rect=(drect[0], drect[1], drect[2], drect[3]),
            source=DEF_FALLBACK,
            basis=(f"the DEF's own DIEAREA, because {why}. On a SLOT run "
                   f"DIEAREA states the PLACEABLE CORE and not the die, so "
                   f"this number is the die only if this run placed no slot"),
            record_present=bool(rec), def_rect_um=drect)
    return DieRect(
        rect=None, source=NOT_MEASURED,
        basis=(f"the die was NOT MEASURED: {why}"
               + ("" if drect is None else
                  ". The DEF's DIEAREA was deliberately not used in its place "
                  "— on a SLOT run it states the placeable core")),
        record_present=bool(rec), def_rect_um=drect)
