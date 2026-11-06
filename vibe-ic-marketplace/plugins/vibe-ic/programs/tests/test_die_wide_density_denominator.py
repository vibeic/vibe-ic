#!/usr/bin/env python3
"""The per-layer density measurement, over the DIE and counting the FILL.

TWO DEFECTS, MEASURED TOGETHER, ON THE SAME REPORT
===================================================
`reports/phase3/metal_density.json` for a landed gf180mcuD 0.5x0.5-slot run
(spm, 2026-08) said this about the flow's own streamed GDS:

    "die_area_um2": 1732693.41
    "metal2": 0.003636
    "layers_datatype_delta": {"metal2": 0.0}
    "layer_gds_specs": {"metal1": [[34,0],[34,10]], ...}
    "datatype_discovery": {"specs_from_layermap": 10, "specs_from_deck": 0,
                           "deck_files_read": 40}

Both statements were false about the die, and each for its own reason.

1. THE DENOMINATOR WAS THE CORE. `die_area_um2` was the bounding box of the
   streamed geometry, which on a slot submission is the routed CORE — measured,
   1052 x 1647 um, 35.4 % of the 1936 x 2531 um die. The PDK's own density deck
   divides by `extent.sized(0.0).area`, the whole die. A number arithmetically
   correct over the core is simply not an answer to a rule written over the die.

2. THE FILL WAS NOT COUNTED AT ALL. Measured on that same GDS, per (layer,
   datatype): metal2 routing 6299.9 um2, metal2 DUMMY 744035.9 um2. The report
   published 0.003636 — the routing alone — and `layers_datatype_delta: 0.0`,
   i.e. "this layout has no dummy fill", about a layout the same flow had just
   filled. #990 taught the discovery to read the PDK's deck, but only in the
   `NAME = input(L, D)` binding form. gf180mcuD's deck registers its layers
   through a helper instead — `extract_single_layer_from_design.call(
   :metal1_dummy, 34, 4)` — so 40 deck files yielded `specs_from_deck: 0`.

The two errors pointed the same way and hid each other: a numerator ~12x too
small over a denominator ~2.8x too small still looks like a plausible density,
and both lived in the same file, so no consumer could reconcile them. The
external checker was the only thing that ever contradicted it: the operator's
precheck failed the same GDS on M2.4 at 18.2 % over the die.

Every test below breaks one of those and requires the failure.
"""
from __future__ import annotations

import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
_FIXTURE_DIR = _PROGRAMS / "tests" / "fixtures" / "density_fill"
for _p in (str(_PROGRAMS), str(_FIXTURE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)







# ── 1. the denominator ──────────────────────────────────────────────────────









# ── 2. the deck binding form the discovery could not read ───────────────────












# ── 3. the wiring: the declared die must reach the recipe ───────────────────

def test_the_runner_passes_the_declared_die_and_omits_it_otherwise():
    """CT-03 WIDENED THE AUTHORITY AND NOT THE PROPERTY. This used to read
    `_slot_geometry` directly, which made "there is a slot" stand in for "the
    DEF's DIEAREA is not the die". That stopped being the same fact the moment
    the RING path also handed OpenROAD the core as `-die_area`, so the source
    now reads `declared_die_rect`, which answers for the slot path (unchanged,
    slot first) AND the ring path. The property asserted here is the one it
    always was: the declared die reaches the recipe, and is OMITTED — never
    passed empty — when there is none."""
    src = _PROGRAMS.joinpath("phase3_one_shot_runner.py").read_text()
    assert "_dens_die, _dens_die_basis = declared_die_rect(project)" in src
    assert "-rd die={_dens_die[0]},{_dens_die[1]}," in src
    # OMITTED, not passed empty: `-rd die=` with nothing after it is a
    # malformed KLayout argument, and the recipe already treats an absent `die`
    # global as "measure the bounding box".
    assert 'if _dens_die else ""' in src
    # …and an undetermined die is DISCLOSED in the report's own notes rather
    # than being a silent fall-through to the bounding box.
    assert "the die rectangle is NOT_DETERMINED" in src
