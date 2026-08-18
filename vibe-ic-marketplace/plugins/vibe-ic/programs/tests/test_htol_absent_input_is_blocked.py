#!/usr/bin/env python3
"""vibe-ic#220 — an absent HTOL result must read as BLOCKED, never SKIP.

Reliability qualification (HTOL) is owed once silicon has been fabricated. The
gate used to return `verdict=SKIP` when phase3/stage5_manufacturing/
htol_results.json was absent, and "SKIP" reads as "nothing to do here" — but an
unperformed reliability qual is not nothing to do, it is an unanswered question.
The gate now names the missing input and returns BLOCKED with a non-zero rc,
while a genuinely-complete attestation still PASSes (the alarm must still be
able NOT to ring).

chip-AGNOSTIC: synthetic numeric fixture, no chip/PDK/vendor literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import htol_attestation_check as HTOL  # noqa: E402


def _mk(tmp_path: Path, results: dict | None) -> Path:
    proj = tmp_path / "proj"
    mfg = proj / "phase3" / "stage5_manufacturing"
    mfg.mkdir(parents=True, exist_ok=True)
    if results is not None:
        (mfg / "htol_results.json").write_text(json.dumps(results))
    return proj


# --------------------------------------------------------- the #220 fix
def test_absent_htol_is_blocked_not_skip(tmp_path):
    proj = _mk(tmp_path, None)
    rep = HTOL.audit(proj)
    assert rep["verdict"] == "BLOCKED", rep
    assert rep["verdict"] != "SKIP"
    assert rep["rc"] == 2
    assert "missing_input" in rep and "htol_results.json" in rep["missing_input"]


def test_absent_htol_main_exits_nonzero(tmp_path):
    proj = _mk(tmp_path, None)
    assert HTOL.main([str(proj)]) == 2


# ------------------------------------------------- alarm can still ring
def test_complete_attestation_still_passes(tmp_path):
    proj = _mk(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                          "failures": 0})
    rep = HTOL.audit(proj)
    assert rep["verdict"] == "PASS", rep
    assert rep["rc"] == 0


def test_failure_during_htol_still_fails(tmp_path):
    proj = _mk(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                          "failures": 1})
    rep = HTOL.audit(proj)
    assert rep["verdict"] == "FAIL", rep
    assert rep["rc"] == 1
