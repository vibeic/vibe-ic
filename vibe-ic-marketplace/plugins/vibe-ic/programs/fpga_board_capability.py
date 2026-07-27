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
    return _skip_shape(d)


def _read_audit(project: Path):
    audit = project / "reports" / "phase2" / "fpga" / "quartus_map_audit.json"
    try:
        d = json.loads(audit.read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _skip_shape(d: dict) -> bool:
    return (str(d.get("verdict", "")).upper() == "SKIP"
            and d.get("sof_present") is False)


def fpga_absent_from_run(project: Path) -> bool:
    """True iff this run discloses the FPGA path was NEVER ATTEMPTED.

    STRICTLY NARROWER THAN `fpga_skip_disclosed`, and the two are deliberately
    separate rather than one tightened predicate.

    `verdict: SKIP` is emitted for EVERY non-PASS cause alike — the writer sets
    `sof_present` from `step.status == "PASS"`, so a step that ran and was
    blocked lands in the same bucket as a step that never ran. MEASURED over
    the 32 published audits:

        20  evidence "fpga_compile not run"                 never attempted
        12  evidence "qsf missing — caller must produce it"  ATTEMPTED, blocked

    The second group is somebody's bug. Which predicate is right depends
    entirely on WHAT IS BEING WAIVED:

      * DEFERRING A STEP that cannot complete is reasonable either way — the
        step cannot run whether the tool was absent or a prerequisite was
        missing. That is `fpga_skip_disclosed`, unchanged, and the #607/#663
        contract it carries stays exactly as it was.
      * WAIVING A DOCUMENTATION REQUIREMENT on the grounds that no hardware is
        part of this run needs the stronger claim. "The compile was blocked by
        a file the caller owed" is not "there is no board", and reading it that
        way waives a requirement on the strength of a defect — in 12 of 32
        published cells.

    A legacy audit with no `skip_reason` has not disclosed which it is and gets
    the fail-closed answer. Silence is never disclosure.
    """
    d = _read_audit(project)
    if d is None or not _skip_shape(d):
        return False
    return d.get("skip_reason") == "not_attempted"
