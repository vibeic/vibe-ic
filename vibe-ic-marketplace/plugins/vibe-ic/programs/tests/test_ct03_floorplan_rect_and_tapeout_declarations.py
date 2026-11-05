#!/usr/bin/env python3
"""The floorplan rectangle that is not the die, and the four declarations
`tapeout_precheck` could not get an answer to.

MEASURED (host 8HD-6, image `ghcr.io/vibeic/vibeic-eda@sha256:06537f7e…`, own
label 0.3.46; base = main v1.17.67 + lane czspmtail).

1. CT-03 — `ppl place_pins` HAS NO CORE-BOUNDARY MODE.
   spm x gf180mcuD, run 3, `phase3/stage3/pnr/pnr.tcl`::

       initialize_floorplan -die_area  "0 0 3162 3162" \\
                            -core_area "381 381 2400 2400"

   `routed.def` then carried `DIEAREA ( 0 0 ) ( 6324000 6324000 )` at
   `UNITS DISTANCE MICRONS 2000` — 0..3162 um — while its 514 ROW records ran
   from y=384.16 um to y=2395.12 um. Every antenna-violating pin came out at
   y=3161.48 um: **762 um outside the last row, with zero components in that
   band.** `repair_antenna` inserts a diode where a ROW is, so every marker on
   those nets carried `DIODES_AREA 0` and no iteration of the repair loop could
   reach them. The residual was a FLOORPLAN fact, not the router's.

   The slot path already fixes exactly this, by handing OpenROAD the CORE as
   `-die_area` so the ring band lies outside the die the pin placer knows
   about. Applying the same shape to a design whose OWN PAD RING pins the die
   moves the DEF's `DIEAREA` off the die — which is why the run now RECORDS
   both rectangles and every consumer that needs the die is handed it.

2. THE FOUR QUESTIONS BEHIND THE DATABASE UNIT (rbspm RB-08 remainder).
   Same run, `reports/phase3/general_precheck.json`::

       KLayout.CheckTopLevel   NOT_DETERMINED  `top_cell` was not declared
       KLayout.CheckSize       NOT_DETERMINED  `deliverable` was not declared
       General.SealRing        NOT_DETERMINED  `seal_ring_required` ...
       General.ForbiddenLayers NOT_DETERMINED  `forbidden_layers` ...

   A NOT_DETERMINED rung is a NON-PASS, so `tapeout_precheck` was unreachable
   for every self-tape-out however correct the die. Each of the four is now
   derived from an artefact the consuming rung does NOT measure — the rule that
   separates a real comparison from a check against its own input — or reported
   NOT_DETERMINED naming the artefact it went without.
"""
from __future__ import annotations

import sys
from pathlib import Path


PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import general_precheck as gp               # noqa: E402
import _tapeout_declaration as td           # noqa: E402


# ───────────────────────── 1. the CT-03 pin rectangle ──────────────────────













# ─────────── 2. the emitted TCL: both branches, both directions ────────────









# ─────────────────── 3. the die rectangle record and its reader ─────────────

















# ─────────────── 4. the metrics aggregate stops quoting the core ────────────

_DEF = ("VERSION 5.8 ;\nDESIGN spm ;\nUNITS DISTANCE MICRONS 2000 ;\n"
        "DIEAREA ( 762000 762000 ) ( 4800000 4800000 ) ;\nEND DESIGN\n")








# ───────────────────── 5. `deliverable`, and its deadlock ──────────────────









# ───────────────────────── 6. `forbidden_layers` ───────────────────────────







# ─────────────────────── 7. the publisher, end to end ──────────────────────

























def test_the_precheck_still_refuses_a_declaration_that_contradicts_the_layout():
    """`declare top_cell X while the GDS top is Y -> FAIL naming both`."""
    ev = gp._blank(gp.LADDER[2])
    gp._step_top_level(ev, {"top_cells": ["spm"]}, "somebody_elses_top")
    assert ev.verdict == gp.FAIL
    assert "'spm'" in ev.evidence
    assert "somebody_elses_top" in ev.evidence
    assert "not this design" in ev.evidence


def test_the_precheck_passes_the_rung_once_the_derivation_has_answered_it():
    ev = gp._blank(gp.LADDER[2])
    gp._step_top_level(ev, {"top_cells": ["spm"]}, "spm")
    assert ev.verdict == gp.PASS


def test_the_size_rung_reaches_a_verdict_on_the_published_trio():
    """Before: `deliverable` unanswered -> NOT_DETERMINED, and the two
    rectangles behind it were never even reached."""
    ev = gp._blank(gp.LADDER[3])
    geom = {"bbox_um": [0.0, 0.0, 3162.0, 3162.0], "dbu_um": 0.001,
            "bbox_complete": True, "width_um": 3162.0, "height_um": 3162.0}
    gp._step_size(ev, geom, td.DELIVERABLE_DIE, [0, 0], [0, 0, 3162, 3162])
    assert ev.verdict == gp.PASS


def test_the_size_rung_refuses_a_stream_that_is_not_the_declared_die():
    """THE OTHER DIRECTION — the hollow-die shape. A stream whose extent is
    the CORE instead of the die is exactly what CT-03 makes possible if the
    die-wide fill is not told the die, so the rung must catch it."""
    ev = gp._blank(gp.LADDER[3])
    geom = {"bbox_um": [381.0, 381.0, 2400.0, 2400.0], "dbu_um": 0.001,
            "bbox_complete": True, "width_um": 2019.0, "height_um": 2019.0}
    gp._step_size(ev, geom, td.DELIVERABLE_DIE, [0, 0], [0, 0, 3162, 3162])
    assert ev.verdict == gp.FAIL
    assert "381" in ev.evidence and "2019" in ev.evidence
