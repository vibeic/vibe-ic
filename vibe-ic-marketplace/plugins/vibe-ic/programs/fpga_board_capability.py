#!/usr/bin/env python3
"""fpga_board_capability.py — the shared FPGA-board-absence disclosure signal.

ORGANIC #607 established the predicate: `reports/phase2/fpga/
quartus_map_audit.json` carries `verdict == "SKIP"` and `sof_present ==
False` when the runner HONESTLY self-reports that no FPGA board was ever
part of this run (no DE10-class board-pin contract for this IC class, and/or
no Quartus on host). An UNDISCLOSED missing .sof (no audit file, a non-SKIP
verdict, or `sof_present` claimed True) returns False, so the caller's
natural FAIL/MISSING stands — this is a disclosed-skip predicate, not a
blanket "FPGA stuff is optional" switch.

Factored out of `flow_compliance_check.py` (which used it only for the
FPGA-board STEP ids in `_FPGA_BOARD_STEP_IDS`) so a standalone gate that is
NOT one of those steps — `rig_topology_disclosure_check.py` runs inside the
P0 structural-RTL umbrella, not as its own flow step — can consult the SAME
signal instead of hard-failing on a requirement (a hardware rig topology)
that is meaningless when no hardware is part of the run at all.

chip-AGNOSTIC: keyed on the runner's own SKIP self-report, never a chip
name, PDK SKU or vendor literal.
"""
from __future__ import annotations

import json
from pathlib import Path


def fpga_skip_disclosed(project: Path) -> bool:
    """True iff this run HONESTLY discloses a deliberate FPGA skip.

    See module docstring for the exact predicate. Never raises; an
    unreadable or absent audit file returns False (the conservative,
    fail-closed direction — silence is never treated as disclosure).
    """
    audit = project / "reports" / "phase2" / "fpga" / "quartus_map_audit.json"
    try:
        d = json.loads(audit.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(d, dict):
        return False
    return (str(d.get("verdict", "")).upper() == "SKIP"
            and d.get("sof_present") is False)
