#!/usr/bin/env python3
"""The two MULTI-CORNER sign-off STA reports must say what stage they describe.

THE DEFECT, AS THE TIMING LANE MEASURED IT
==========================================
`grep -n 'puts .*STA_BASIS' programs/phase3_one_shot_runner.py` at `bb90724dc`::

    34252:  STA_BASIS: POST_ROUTE_SPEF   <- _emit_spef_sta        (SINGLE corner)
    34935:  STA_BASIS: {basis}           <- _emit_multi_corner_sta
    38644:  STA_BASIS: {basis}           <- _emit_aging_sta_report
    the multi-corner SPEF emitter   -> 0 occurrences
    the multi-corner process-OCV emitter -> 0 occurrences

The single-corner report disclosed its stage. The two reports that carry the
ACTUAL SIGN-OFF CORNERS -- `sta_spef_multicorner.rpt` and
`sta_mcorner_ocv.rpt` -- disclosed nothing, so `_ppa/timing.py::_stage_for`
recorded `stage: null` plus a reason for every row it read out of them. It
refuses to infer a stage from a filename on purpose: the moment a pre-layout
report lands in the same directory, an inferred stage would let an estimate be
compared against sign-off evidence. So the fix belongs in the step's own tool,
which is what this file pins.

HOW THIS PROVES IT
==================
By PRODUCING the reports, not by reading the emitter's source. Each emitter
writes a real `.tcl`; the fake `_docker_exec` here runs that `.tcl` through a
real `tclsh` with the STA verbs stubbed out (`unknown` returns the empty
string), so `open`/`puts`/`close`/`catch` are the genuine article and the
`.rpt` on disk afterwards is the emitter's own bytes. The assertions are made
on that file, and then the file is handed to the real downstream reader
(`_ppa.backends.opensta` -> `_ppa.timing._stage_for`) to show the `stage: null`
row is gone.

THE OCV STAMP IS NOT A COPY OF THE SINGLE-CORNER ONE. That emitter's SPEF is
per corner and may be absent, so the stanza stamps `POST_ROUTE_NO_SPEF` when it
read no parasitics and `PRE_LAYOUT_ESTIMATE` when it also fell back to the
synth netlist. Rounding either up to `POST_ROUTE_SPEF` would be the flattering
lie the stamp exists to prevent, and all three cases are covered below.

Chip-, PDK- and vendor-AGNOSTIC: the fixture PDK names no foundry, node or SKU.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

from _ppa import timing as _ppa_timing  # noqa: E402
from _ppa.backends import opensta as _opensta  # noqa: E402

_TCLSH = shutil.which("tclsh")

pytestmark = pytest.mark.skipif(
    _TCLSH is None,
    reason="tclsh is not installed, so the STA decks this runner emits were "
           "NOT executed and no report was produced in this session. This is "
           "a SKIP and not a pass: nothing here looked.")

TOP = "core_top"














# ======================================================================
# REPORT 1 — sta_spef_multicorner.rpt
# ======================================================================










# ======================================================================
# REPORT 2 — sta_mcorner_ocv.rpt
# ======================================================================














# ======================================================================
# THE CONSEQUENCE — the downstream reader that had to record stage=null
# ======================================================================


def test_the_reader_still_degrades_loudly_on_a_report_with_no_stamp():
    """CONTROL. The stage is read from the stamp and never from the filename,
    so an unstamped report must still come back null-with-a-reason. If this
    ever goes green-by-inference the fix above has been undone somewhere
    downstream."""
    report = _opensta.parse_report(
        "=== SETUP (max-RC corner, SPEF=max, liberty=/pdk/x.lib) ===\n"
        "worst slack max -1.71\n",
        path="sta_spef_multicorner.rpt")
    stage, gap = _ppa_timing._stage_for(report)
    assert stage is None
    assert gap and "STA_BASIS" in gap
