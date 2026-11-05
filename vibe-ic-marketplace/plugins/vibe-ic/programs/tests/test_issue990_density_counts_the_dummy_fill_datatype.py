#!/usr/bin/env python3
"""vibe-ic#990 — the density producer could not see dummy fill.

THE DEFECT
==========
`_METAL_DENSITY_KLAYOUT_RECIPE` kept ONE (gds_layer, datatype) per metal layer:

    if metal_re.match(name) and "NET" in purpose.upper():
        metal_layers.setdefault(name.lower(), (gl, gd))

— the first routing/NET row of the LEF/DEF layermap. The PDK's own KLayout
density deck counts routing PLUS a separate dummy-fill datatype. #988 measured
both paths on the published run's own GDS against that run's own deck:

    layer     gate      PDK's own deck   delta
    li1       0.511625  0.511625         0.00e+00
    met1..5   …         …                0.00e+00

Agreement on all six layers — and #988 recorded why it proves nothing:

    measured 0 shapes on 36/28, 41/28, 34/28, 51/28 and 68..72/99

That layout carries no fill, so the two paths CANNOT disagree on this corpus,
and any fix here is unfalsifiable without a layout that has some. On a filled
run the producer under-counts by exactly the fill area — the area inserted to
SATISFY the rule — and in the direction that pushes a result toward the
disputed 0.35 floor.

WHAT MAKES THIS FALSIFIABLE
===========================
`tests/fixtures/density_fill/filled.gds` is a real GDSII stream carrying fill
shapes on a datatype the routing row does not name:

    die bbox            100 x 100 um   = 10000.0 um2
    routing (68/20)     200 + 200      =   400.0 um2   -> density 0.04
    dummy fill (68/36)  500 + 300      =   800.0 um2   -> delta    0.08
                                                   counted total   0.12

Every number a test below asserts is that arithmetic. The RECIPE THE RUNNER
EMITS is executed verbatim against that stream (`pya` supplied by the fixture's
narrow stand-in — no klayout, no container and no PDK tree exists on the host
this was written on; see the fixture module for what that costs).

WHAT IS NOT TOUCHED
===================
No density BOUND moves. #988 left step 34 ORACLE-DISPUTED deliberately and this
change does not adjudicate it: `layers_routing_only` publishes the pre-fix
number beside the new one so an earlier run stays reconcilable, and the gate's
windows, the registry and `metal_layer_density_check` are untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_FIXTURE_DIR = _PROGRAMS / "tests" / "fixtures" / "density_fill"
for _p in (str(_PROGRAMS), str(_FIXTURE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gds_fixture as F  # noqa: E402

#: The map this runner SYNTHESIZES when a PDK ships no streamout layermap —
#: one row bundling every purpose onto the routing datatype. It is the shape
#: the measured run used, and the case where ONLY the deck can reveal fill.






# ── the fixture is what it says it is ───────────────────────────────────────

def test_the_committed_stream_still_matches_its_generator():
    """A binary fixture nobody can regenerate is a fixture that rots into a
    number people trust. The bytes on disk are the generator's output."""
    assert F.GDS.read_bytes() == F.build_gds(), (
        f"{F.GDS} no longer matches gds_fixture.build_gds(); re-run "
        f"`python3 {F.HERE}/gds_fixture.py`")


def test_the_fixture_really_carries_fill_shapes_on_their_own_datatype():
    """The load-bearing property. Without shapes on a SECOND datatype the two
    selections agree by construction and every test below is vacuous — which is
    exactly the state of the measured corpus (#988: 0 fill shapes)."""
    shapes, dbu, _cell = F.read_gds(F.GDS)
    routing = (F.METAL_GDS_LAYER, F.ROUTING_DATATYPE)
    fill = (F.METAL_GDS_LAYER, F.FILL_DATATYPE)
    assert routing in shapes and fill in shapes, sorted(shapes)
    assert routing != fill
    scale = dbu * dbu
    assert F.union_area_dbu(shapes[routing]) * scale == pytest.approx(
        F.ROUTING_AREA_UM2)
    assert F.union_area_dbu(shapes[fill]) * scale == pytest.approx(
        F.FILL_AREA_UM2)
    assert F.FILL_AREA_UM2 > 0


# ── the two paths, and their disagreement ───────────────────────────────────













# ── it must not move anything on the corpus that HAS no fill ────────────────
