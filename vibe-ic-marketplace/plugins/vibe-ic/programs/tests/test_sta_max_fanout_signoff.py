#!/usr/bin/env python3
"""TAPEOUT-SIGNOFF (DRV / max-fanout) — the sign-off STA must ACTUALLY ASK for
the max-fanout check, and must record that an EMPTY fanout table is not proof
of zero fanout violations.

ORGANIC subservient x sky130A. Re-derived from raw artefacts of
`converge_1.5.69_sky130A`:

  * the shipped sign-off STA TCL ran
    `report_check_types -recovery -removal -max_slew -min_pulse_width
     -max_capacitance -violators` — **`-max_fanout` was never requested**, so
    NO report and NO gate JSON in the whole run mentions fanout at all;
  * meanwhile the design's OWN acceptance plan (L7) demands
    "max_slew / max_cap / max_fanout viols = 0" against a reference baseline of
    13 max_fanout violations.

So the acceptance criterion was UNMEASURABLE, and an absent table could be read
as a clean zero. That is a checks-that-lie-by-omission defect of exactly the
same family as the `-violators` fix directly above it in the runner.

chip-AGNOSTIC: `-max_fanout` is a stock OpenSTA `report_check_types` flag; no
chip, vendor, SKU or PDK literal is involved, and no fanout LIMIT is fabricated
(emitting a cap stays gated on the design's own L9 declaration).
"""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import func_src

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import sta_signoff_rigor_check as G  # noqa: E402

_RUNNER = _PROGRAMS / "phase3_one_shot_runner.py"


def _runner_src() -> str:
    return _RUNNER.read_text()


def test_signoff_check_types_requests_max_fanout() -> None:
    """The emitted TCL must ask OpenSTA for the max-fanout check.

    Regression guard: without `-max_fanout` the sign-off STA structurally
    CANNOT report a fanout violation, so the check is unmeasured rather than
    clean.
    """
    helper = func_src(_runner_src(), "_report_check_types_tcl")
    assert "-max_fanout" in helper, (
        "sign-off report_check_types no longer requests -max_fanout; the "
        "max-fanout DRV check would be structurally unmeasurable again"
    )
    # the other sign-off check types must survive alongside it
    for flag in ("-recovery", "-removal", "-max_slew", "-min_pulse_width",
                 "-max_capacitance", "-violators"):
        assert flag in helper, f"sign-off check type {flag} was dropped"


def test_marker_names_max_fanout() -> None:
    """The authoritative marker must NAME max_fanout among the checks run."""
    src = _runner_src()
    i = src.index("_SIGNOFF_CHECK_TYPES_MARKER = (")
    marker_block = src[i:i + 400]
    assert "max_fanout" in marker_block, (
        "the check-types marker no longer names max_fanout, so a downstream "
        "gate cannot tell whether the fanout check was performed"
    )


def test_unmeasured_is_not_zero_note_emitted() -> None:
    """An empty fanout table must be disclosed as NOT equal to zero violations."""
    src = _runner_src()
    assert "_SIGNOFF_MAX_FANOUT_NOTE" in src, "the semantics note was removed"
    helper = func_src(src, "_report_check_types_tcl")
    assert "_SIGNOFF_MAX_FANOUT_NOTE" in helper, (
        "the max-fanout semantics note is no longer written into the sign-off "
        "report; silence could again be read as 0 violations"
    )
    i = src.index("_SIGNOFF_MAX_FANOUT_NOTE = (")
    note = src[i:i + 500]
    assert "UNMEASURED" in note.upper()


def test_marker_stays_backward_compatible_with_rigor_gate() -> None:
    """Appending a check type must not break the existing rigor gate.

    The gate substring-matches the captured type list, so the pre-existing
    recovery / removal / min-pulse-width detection must still hold on a report
    carrying the NEW marker.
    """
    src = _runner_src()
    i = src.index("_SIGNOFF_CHECK_TYPES_MARKER = (")
    # rebuild the literal the runner will emit (concatenated string parts)
    marker_block = src[i:i + 400]
    parts = [ln.split('"')[1] for ln in marker_block.splitlines()
             if ln.count('"') >= 2]
    marker = "".join(parts)
    assert marker.startswith("SIGNOFF_CHECK_TYPES_REPORTED ")

    report = (
        "   0.42   slack (MET)\n"
        "worst slack max 0.42\n"
        "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
        f"{marker}\n"
    )
    verdict = G.evaluate(report)
    assert verdict["verdict"] == "PASS", (
        f"rigor gate regressed on the new marker: {verdict}"
    )
