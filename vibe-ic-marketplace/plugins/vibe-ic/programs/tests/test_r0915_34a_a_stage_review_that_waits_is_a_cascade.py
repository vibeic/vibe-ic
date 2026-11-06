"""A review declining because its stage is not green is a CASCADE, not a fault.

MEASURED 2026-09-15 (lane icspm3, R-0915-34(a)) on `spm` x gf180mcuD.
`stage_on_pass_review` is the gate of steps 2, 7, 14, 15, 37 and 39, all in
`advisory_program_exit_zero` slots. When the stage under review is not green it
returns rc 2 — correctly: it reviews a PASS. But it stated no class, so the
reader fell back to its fail-closed default and booked `EXECUTION_ERROR`, and
every one of those six steps inherited INCOMPLETE from a sentence about
somebody ELSE's step.

It looked. It read the register. It is WAITING. That is `BLOCKED_BY_UPSTREAM`,
and the class is now STATED in the field `report_reason_class` reads before any
prose recogniser (#2275 / #2276), together with the ROWS it waits on so a
reader can act on it.

THE NEGATIVE CONTROL IS THE POINT, and it is the neighbouring branch: a review
that truly COULD NOT RUN — no register, an unreadable one, or one carrying no
row for this stage — has established nothing, states nothing, and keeps the
fail-closed `EXECUTION_ERROR`. `_p0_declared_absent`'s rule in spirit: the
register must EXIST and say the rows are not green.

chip-AGNOSTIC: synthetic compliance registers in tmp_path.
"""
from __future__ import annotations

import json
import subprocess  # nosec B404 — a declared flow program
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import _flow_reason_taxonomy as R  # noqa: E402


def _register(tmp_path, rows, stage="stage1", name="c.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"steps": [
        {"id": i, "stage": stage, "status": st} for i, st in rows]}))
    return p


# ── the rows are named, not just the words ────────────────────────────────


# ── direction 1: waiting on a non-green row is BLOCKED_BY_UPSTREAM ────────


# ── direction 2: a review that truly cannot run is still a fault ──────────


def test_BLOCKED_BY_UPSTREAM_is_not_skip_eligible():
    """Accuracy only, as ruled: naming the cascade must not green anything."""
    assert R.BLOCKED_BY_UPSTREAM not in R.SKIP_ELIGIBLE
    assert R.record_verdict(R.BLOCKED_BY_UPSTREAM) == "BLOCKED"
