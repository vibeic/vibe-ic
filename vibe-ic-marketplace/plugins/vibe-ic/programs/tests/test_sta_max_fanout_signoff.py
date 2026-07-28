#!/usr/bin/env python3
"""TAPEOUT-SIGNOFF (DRV / max-fanout) — the sign-off STA must ACTUALLY ASK for
the max-fanout check, and must record that an EMPTY fanout table is not proof
of zero fanout violations.

Salvage of #315 (`114/fix/max-fanout-signoff-disclosure`).

MEASURED ON MAIN BEFORE THE FIX (`_report_check_types_tcl` + `extract_drv`):

    contains -max_slew        : True
    contains -max_capacitance : True
    contains -max_fanout      : False
    marker : SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew
             min_pulse_width max_capacitance
    DRV gate view -> queried=True  kinds_queried=['max_slew','max_capacitance']

So the sign-off STA was never asked for the fanout check, while
`sta_corner_record_completeness_check` R5 — whose own finding text names
"max_slew / max_capacitance / max_fanout" as the DRV set it guards — reported
the run as QUERIED and PASSED it. An unqueried fanout limit and a met one were
byte-identical in every report and every gate JSON of the run, which is exactly
the disease R5 exists to stop ("an unqueried DRV limit is indistinguishable
from a met one").

chip-AGNOSTIC: `-max_fanout` is a stock OpenSTA `report_check_types` flag; no
chip, vendor, SKU or PDK literal is involved, and no fanout LIMIT is fabricated
(emitting `set_max_fanout` stays gated on the design's own L9 declaration).
"""
from __future__ import annotations

import sys
from pathlib import Path

from _source_pin import func_src

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as R                    # noqa: E402
import sta_signoff_rigor_check as G                   # noqa: E402
import sta_corner_record_completeness_check as C      # noqa: E402

_RUNNER_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()


def test_signoff_check_types_requests_max_fanout() -> None:
    """The emitted TCL must ask OpenSTA for the max-fanout check.

    Without `-max_fanout` the sign-off STA structurally CANNOT report a fanout
    violation, so the check is UNMEASURED rather than clean.
    """
    tcl = R._report_check_types_tcl("/x/out.rpt")
    assert "-max_fanout" in tcl, (
        "sign-off report_check_types no longer requests -max_fanout; the "
        "max-fanout DRV check would be structurally unmeasurable again")
    # every pre-existing sign-off check type must survive alongside it
    for flag in ("-recovery", "-removal", "-max_slew", "-min_pulse_width",
                 "-max_capacitance", "-violators", "-max_count"):
        assert flag in tcl, f"sign-off check type {flag} was dropped"


def test_marker_names_max_fanout() -> None:
    """The authoritative marker must NAME max_fanout among the checks run.

    The marker is the ONLY tool-version-independent evidence a downstream gate
    has (OpenSTA 3.1.0 prints no literal check-type words), so a check missing
    from the marker is a check no gate can confirm ran.
    """
    assert "max_fanout" in R._SIGNOFF_CHECK_TYPES_MARKER, (
        "the check-types marker no longer names max_fanout, so a downstream "
        "gate cannot tell whether the fanout check was performed")
    assert R._SIGNOFF_CHECK_TYPES_MARKER.startswith(
        "SIGNOFF_CHECK_TYPES_REPORTED recovery removal"), (
        "the marker prefix changed — the rigor gate substring-matches it")


def test_unmeasured_is_not_zero_note_emitted() -> None:
    """An empty fanout table must be disclosed as NOT equal to zero violations."""
    helper = func_src(_RUNNER_SRC, "_report_check_types_tcl")
    assert "_SIGNOFF_MAX_FANOUT_NOTE" in helper, (
        "the max-fanout semantics note is no longer written into the sign-off "
        "report; silence could again be read as 0 violations")
    note = R._SIGNOFF_MAX_FANOUT_NOTE
    assert note.startswith("SIGNOFF_MAX_FANOUT_SEMANTICS")
    assert "UNMEASURED" in note.upper()
    tcl = R._report_check_types_tcl("/x/out.rpt")
    assert note in tcl, "the note is defined but never emitted"
    # It must be written ONLY on the success branch, beside the marker — a note
    # attached to a FAILED report_check_types would attest a check that errored.
    assert tcl.index(R._SIGNOFF_CHECK_TYPES_MARKER) < tcl.index(note)
    assert tcl.index("SIGNOFF_CHECK_TYPES_FAILED") < tcl.index(
        R._SIGNOFF_CHECK_TYPES_MARKER)


_REPORT_BODY = (
    "=== SETUP (max-RC corner, liberty=/pdk/x.lib) ===\n"
    "   0.42   slack (MET)\n"
    "worst slack max 0.42\n"
    "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
    # ORGANIC #540 — the worst-path marker the emitter writes between the slack
    # lines and the check-types tables. Built from the runner's own constant so
    # this fixture cannot drift from what the emitter actually emits. Its
    # position is the emitted one: report_checks runs BEFORE report_check_types,
    # so the marker lands ahead of the DRV tables and cannot hold one open.
    f"{R._SIGNOFF_WORST_PATHS_MARKER}max group_path_count=3\n"
    "max slew\n"
    "----------\n"
    "Pin                    Limit    Slew   Slack\n"
    "_x/A                    1.50    0.90    0.60 (MET)\n"
)


def _signoff_report(with_note: bool = True) -> str:
    """A sign-off report body shaped like what THIS emitter produces.

    `with_note=False` keeps the fixture buildable against a runner that has no
    semantics note, so the DRV-kinds guard below FAILS ON THE BEHAVIOUR (the
    marker not naming max_fanout) and not on a missing attribute.
    """
    tail = f"{R._SIGNOFF_CHECK_TYPES_MARKER}\n"
    if with_note:
        tail += f"{R._SIGNOFF_MAX_FANOUT_NOTE}\n"
    return _REPORT_BODY + tail


def test_drv_gate_now_sees_max_fanout_as_queried() -> None:
    """END-TO-END: the DRV gate must record max_fanout among the kinds queried.

    This is the consumer proof — `sta_corner_record_completeness_check` learns
    which DRV kinds ran from the marker alone. Before the fix `kinds_queried`
    was `['max_slew', 'max_capacitance']` on a PASSING run whose R5 text
    claimed max_fanout coverage.
    """
    drv = C.extract_drv(_signoff_report(with_note=False))
    assert drv["queried"] is True
    assert "max_fanout" in drv["kinds_queried"], (
        f"the DRV gate cannot see the fanout check: {drv['kinds_queried']}")
    # the kinds that already worked must keep working
    for kind in ("max_slew", "max_capacitance"):
        assert kind in drv["kinds_queried"]


def test_semantics_note_is_not_miscounted_as_a_violator() -> None:
    """The disclosure line must not perturb the DRV violation count.

    `extract_drv` ends an open DRV table at the first line carrying NO digit
    and counts a row whose trailing column is negative. The note is therefore
    kept digit-free: a note that changed a violation count would be a gate
    lying about the design instead of about the check.
    """
    assert not any(ch.isdigit() for ch in R._SIGNOFF_MAX_FANOUT_NOTE), (
        "the semantics note gained a digit — it can now be parsed as a DRV "
        "table row / keep a table open past its end")
    drv = C.extract_drv(_signoff_report())
    assert drv["violations"] == {}, drv
    assert drv["total"] == 0


def test_marker_stays_backward_compatible_with_rigor_gate() -> None:
    """Appending a check type must not break the existing rigor gate.

    The gate substring-matches the captured type list, so the pre-existing
    recovery / removal / min-pulse-width detection must still hold on a report
    carrying the NEW marker.
    """
    verdict = G.evaluate(_signoff_report())
    assert verdict["verdict"] == "PASS", verdict
    assert verdict["recovery_checked"] and verdict["removal_checked"]
    assert verdict["min_pulse_width_checked"]
