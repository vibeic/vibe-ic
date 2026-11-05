#!/usr/bin/env python3
"""lvs_layout_view_census — name every placed master that the LVS extraction read as a full library layout instead of the abstract the flow supplied.

WHY
===
Step 31 extracts the layout from the routed DEF with Magic: `lef read` of the
tech LEF, the standard-cell LEF and every macro/IO LEF the place-and-route
read, then `def read`.  A placed master that none of those LEFs defines is not
an error to Magic: it searches its cell path and loads the library's full
`.mag` layout instead, announcing it only as::

    Cell <master> read from path <dir>

MEASURED on spm x gf180mcuD (IC path, deliverable DIE), 2026-09-29: an LVS
re-run whose process had not run place-and-route carried no IO LEF reads, so
Magic loaded all 44 pad-ring masters from `libs.ref/gf180mcu_fd_io/mag` (886
such lines; 0 in the run whose LVS matched).  The extracted netlist gained 51
transistor-level IO sub-circuits, both power-aware compares reported a
mismatch, and the plain compare crashed netgen (rc 139).  The layout netgen
was given was not the layout the flow means to compare.

A compare over such an extraction is not evidence either way, so the caller
stops before netgen and reports NOT_MEASURED naming the masters.

INTERFACE
=========
`def_component_masters(def_text)`  → the master names placed in COMPONENTS.
`masters_read_from_library(log_text, masters)` → {master: path} for every
placed master Magic loaded from a library path.  Pure; reads nothing itself.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, Iterable, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Magic's own message when it resolves a cell by searching its cell path
#: (`DBCellRead`, magic 8.3): the cell was NOT defined by any LEF/DEF read.
_READ_FROM_PATH = re.compile(r"^Cell (\S+) read from path (\S[^\r\n]*?)\s*$", re.M)
_COMPONENT = re.compile(r"^\s*-\s+\S+\s+(\S+)")


def def_component_masters(def_text: str) -> Set[str]:
    """Master names of the DEF's COMPONENTS section (placed instances)."""
    masters: Set[str] = set()
    inside = False
    for line in def_text.splitlines():
        head = line.strip()
        if head.startswith("COMPONENTS "):
            inside = True
            continue
        if head.startswith("END COMPONENTS"):
            break
        if inside:
            m = _COMPONENT.match(line)
            if m:
                masters.add(m.group(1))
    return masters


def masters_read_from_library(log_text: str,
                              masters: Iterable[str]) -> Dict[str, str]:
    """Map placed masters to the full layouts Magic loaded."""
    placed = set(masters)
    return {m.group(1): m.group(2) for m in _READ_FROM_PATH.finditer(log_text)
            if m.group(1) in placed}
