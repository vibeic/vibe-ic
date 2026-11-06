#!/usr/bin/env python3
"""Die-wide dummy fill: the fill frame must be the DIE, not the layout bbox.

WHAT THIS DEFENDS, and where the bar comes from
-----------------------------------------------
Not this repo's opinion. The shuttle operator's own precheck container
(`ghcr.io/wafer-space/gf180mcu-precheck`, image digest
sha256:f6c0cb88efce8769ec87de5a2035ada731fd8fffb1b3e5e1968078f6dd191c2f), run
2026-08-20 against a sealed gf180mcuD 0.5x0.5-slot die this flow produced,
returned rc=1 with 8 KLayout density errors — DCF.1b, PL.8, M1.4, M2.4, M3.4,
M4.4, M5.4, MT.3 — every one reported against the whole die polygon
(0,0;1936,2531).

The fill was not missing. The flow's own `cmp_fill_emit.json` for that run reads
`metal2 0.0036 -> 0.4330, "reached": true`, and its `metal_density.json` reads
`"die_area_um2": 1732693` — which is the CORE bbox, 35.4 % of the 4900016 um2
die. Measured over the DIE instead, the same layers were COMP 3.04 %, Poly2
0.12 %, Metal1 8.26 %, Metal2 18.21 %, Metal3 17.97 %, Metal4 18.45 %,
Metal5 18.48 %, against floors of 25/14/30/30/30/30/30 in the PDK's own
`density.rb`. The fill was scoped to the wrong rectangle and nothing measured
the right one.

Running the PDK's OWN generator (`libs.tech/klayout/tech/scripts/fill_all.rb`)
over the sealed die took those to 26.38 / 29.35 / 31.97 / 41.92 / 48.10 /
48.28 / 37.46 % and the precheck's density stage to `{"total": 0}`.

Every test below breaks something the change defends and requires the failure:

  * the generator filled a frame that does not cover the die -> FAIL, naming
    the fraction it did cover, NOT a fill reported as die-wide
  * the generator exited 0 having written nothing            -> FAIL (this
    PDK's sibling `sealring.py` was measured doing exactly that)
  * the generator wrote a layout that gained no area         -> FAIL
  * the PDK ships no density filler                          -> DISCLOSED SKIP,
                                                                rc 2, naming
                                                                every location
                                                                searched
  * the step is not wired into both stream-out paths, or runs before the seal
    ring                                                     -> the ordering
                                                                assertions redden
"""
from __future__ import annotations

import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_DRIVER = _PROGRAMS / "density_fill" / "pdk_fill_driver.rb"


# ── the engines this program ships beside itself ────────────────────────────



def test_the_driver_loads_the_pdk_script_and_carries_no_fill_geometry():
    """The driver's whole job is to give the PDK script's globals their types.

    If it ever grows a fill cell, a pitch or a keep-out, the flow has started
    reimplementing foundry data instead of calling the foundry's generator —
    and the fill would then be this repo's opinion about a design manual it has
    never read.
    """
    rb = _DRIVER.read_text()
    assert "load script" in rb
    assert "$input" in rb and "$output" in rb and "$threads" in rb
    for reimplementation in ("fill_region", "row_step", "column_step",
                             "DBox::new", "TilingProcessor"):
        assert reimplementation not in rb, reimplementation




# ── resolution: an absence must NAME where it looked ────────────────────────





# ── the fake runner: everything below drives the real control flow ──────────







DIE = [0.0, 0.0, 1936.0, 2531.0]
CORE = [441.97, 442.0, 1494.0, 2089.0]














# ── the wiring: the step must run, in both paths, AFTER the seal ring ───────











# ── ONE WRITER PER DUMMY LAYER ──────────────────────────────────────────────

_SIBLINGS = ("fill_comp.rb", "fill_poly2.rb", "fill_metal.rb")
#: What each of the generator's passes writes. The program must DISCOVER this
#: by running them, never be told it: which layer families a PDK ships, what it
#: calls the scripts and which layers each one writes are all PDK data.
_PASS_LAYERS = {"fill_comp.rb": [22], "fill_poly2.rb": [30],
                "fill_metal.rb": [34, 36, 42, 46, 81]}








def test_the_driver_skips_a_pass_through_rubys_own_bookkeeping():
    """The skip must not edit, copy or re-implement any PDK file: a path already
    in `$LOADED_FEATURES` is simply not required again."""
    rb = _DRIVER.read_text()
    assert "$LOADED_FEATURES" in rb
    assert "VIBEIC_FILL_SKIP" in rb
    assert "File.expand_path" in rb
    # and a name the PDK does not ship must be refused, not silently ignored —
    # a typo'd skip would otherwise run the pass it was meant to leave out.
    assert "which the PDK does not ship" in rb




# ── vibe-ic#2107: the engine is CHECKED on the host and OPENED in the container ──
#
# The program shipped a host `Path.is_file()` guard over its two engines and
# then handed those same host paths to a KLayout that, on every normal flow
# run, lives inside a container. The plugin tree is not one of the mounts the
# repo's own `tools/vibeic-eda/restart-eda.sh` creates (lines 194-195 bind the
# designs directory and nothing else), so the guard passed, the open failed,
# and the run recorded
#
#   state  = FAIL
#   reason = could not measure the die BEFORE filling: the density measurement
#            wrote no report (rc=1): ERROR: Unable to open file:
#            .../programs/density_fill/die_density_measure.py (errno=2)
#   runner = container:<name>:klayout
#
# — a die-density number that is NOT_MEASURED-by-the-plugin reading as a
# non-PASS of the layout. The two tests below are the two directions: the
# engines must be reachable where KLayout runs, and an engine that genuinely
# cannot be reached there must FAIL by name rather than skip or pass.
