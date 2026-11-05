from __future__ import annotations


import re


from typing import Dict, Iterable, List, Optional, Sequence, Tuple


ROUTED_CELL_GRAMMAR = re.compile(r"^v\d+(?:\.\d+)*_(?P<pdk>.+)$")


ROUTED_DEF_GATE_LABELS = (
    "macro OBS not crossed ({cell})",
    "DRC PASS is not vacuous ({cell})",
    "inner FAILs reach the verdict ({cell})",
    "new tool diagnostic id ({cell})",
)


def routed_cell_identity(design: str, version_dir: str) -> Optional[str]:
    """``("spm", "v1.14.88_gf180mcuD")`` -> ``"spm/gf180mcuD"``.

    None when the version directory does not state a PDK -- a cell with no
    PDK has no identity in the (design, pdk) model, and the producer refuses
    it UNDETERMINED rather than guess one. The PDK is everything after the
    first ``_`` that follows the dotted version, so a PDK name may itself
    carry ``-`` or ``_`` (``ihp-sg13g2``).
    """
    m = ROUTED_CELL_GRAMMAR.match(version_dir)
    if m is None:
        return None
    return f"{design}/{m.group('pdk')}"


PROCESS_STATES = ("PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS")
