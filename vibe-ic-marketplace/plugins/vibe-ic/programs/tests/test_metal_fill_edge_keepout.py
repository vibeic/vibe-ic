"""metal_fill — the fill must keep OUT of the die-edge band the seal / scribe
ring occupies.

MEASURED (0.5x0.5-slot die, 2026-08-20). The engine's only keep-out was
`drawn.sized(space_to_metal)` — same-layer spacing to circuit metal — which
says nothing about the ring band. Two runs of the SAME fill config:

    fill the SEALED die   -> sign-off DRC 1177 -> 18686
    fill the UNSEALED die -> every metal layer reaches target, ZERO new items

The whole difference is dummy squares landing in the ring band. A foundry
guard-ring rule reads `metal.not_outside(guard_ring_mk).width()`, and
`not_outside` selects any polygon merely TOUCHING the marker band and then
measures that WHOLE polygon — so one dummy square in the band is reported.

The PDK's own fill script never had the problem: it declares
`space_to_scribe_line` and subtracts `_frame - _frame.sized(-<that>)` before it
fills anything. So the engine gains the same concept, with the number READ from
the PDK (see `metal_fill_config_gen.parse_scribe_keepout_um`) rather than
invented, plus a general `exclude_layers` for declared marker keep-outs.

Two kinds of proof here:
  * SOURCE INVARIANTS — the subtraction is actually in the shipped engine and
    is actually threaded from the config, so a refactor that drops it fails.
  * PROVE-BY-RUN — the REAL engine, in the real KLayout, on a synthetic
    NDA-clean die, with a POSITIVE CONTROL: the same fixture filled with the
    keep-out DISABLED must put fill in the band (otherwise a test that sees an
    empty band proves nothing), and filled with it ENABLED must put none there
    while still filling the interior.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _klayout_launch as kl  # noqa: E402

ENGINE = PROGRAMS / "metal_fill" / "metal_fill.py"
FIXGEN = PROGRAMS / "metal_fill" / "gen_fixtures.py"


# ── source invariants ──────────────────────────────────────────────────────
def test_engine_subtracts_the_exclusion_from_the_fillable_area():
    src = ENGINE.read_text(encoding="utf-8")
    assert "fillable = fillable - excl" in src, \
        "the die-edge / marker keep-out is no longer subtracted from the fill"
    # and it is built from the CONFIG, not from a literal
    assert '_edge_exclusion_um' in src and '_exclude_layers' in src
    assert 'spec.get("_edge_exclusion_um")' in src


def test_config_keys_are_threaded_per_layer_with_override():
    src = ENGINE.read_text(encoding="utf-8")
    assert 'cfg.get("edge_exclusion_um")' in src
    assert 'cfg.get("exclude_layers")' in src
    # a layer may override the global value
    assert 'spec.get("edge_exclusion_um")' in src


def test_no_vendor_or_design_literal_in_the_keepout_logic():
    """chip/PDK-AGNOSTIC: the band width and the marker layers are CALLER
    numbers. Scoped to the keep-out block itself — the module docstring
    elsewhere legitimately cites a PDK by name when recording a measurement."""
    src = ENGINE.read_text(encoding="utf-8")
    i = src.index("DIE-EDGE / MARKER KEEP-OUT")
    block = src[i:src.index("excl.merge()", i)].lower()
    for bad in ("gf180", "sky130", "spm", "sg13", "asap7", "nangate", "167"):
        assert bad not in block, \
            f"vendor/design literal {bad!r} leaked into the keep-out logic"


# ── prove-by-run ───────────────────────────────────────────────────────────
_MEASURE = r'''
import json, os, pya
ly = pya.Layout(); ly.read(os.environ["M_GDS"])
top = ly.top_cell()
dbu = ly.dbu
band = float(os.environ["M_BAND"])
die = pya.Region(top.begin_shapes_rec(ly.layer(0, 0))).bbox()
b = int(round(band / dbu))
inner = pya.Box(die.left + b, die.bottom + b, die.right - b, die.top - b)
ring = pya.Region(die) - pya.Region(inner)
fill = pya.Region(top.begin_shapes_rec(ly.layer(34, 4))).merged()
out = {"in_band_um2": (fill & ring).area() * dbu * dbu,
       "in_core_um2": (fill & pya.Region(inner)).area() * dbu * dbu}
open(os.environ["M_OUT"], "w").write(json.dumps(out))
'''


def _cfg(tmp: Path, edge: float) -> Path:
    p = tmp / f"cfg_{edge}.json"
    p.write_text(json.dumps({
        "boundary_layer": [0, 0],
        "edge_exclusion_um": edge,
        "window_um": None,
        "max_passes": 4,
        "mfg_grid_um": 0.005,
        "layers": [{"name": "m", "layer": [34, 0], "target": 0.30,
                    "max": 0.95, "space": 0.5, "space_to_metal": 0.5,
                    "width": 2.0, "fill_datatype": 4}],
    }))
    return p


BAND = 10.0


@pytest.fixture(scope="module")
def _run():
    runner = kl.find_runner()
    if runner is None:
        pytest.skip("no KLayout runner available (host or EDA container)")
    tmp = Path(tempfile.mkdtemp(prefix="mf_keepout_", dir=str(PROGRAMS.parent)))
    if not runner.covers(tmp):
        pytest.skip(f"KLayout runner cannot see {tmp}")
    fix = tmp / "fixture.gds"
    rc, out, err = runner.run(FIXGEN, {"FILL_OUT": str(fix)},
                              path_keys=("FILL_OUT",))
    if not fix.is_file():
        pytest.skip(f"fixture generation unavailable: rc={rc} {(out + err)[-200:]}")

    def _one(edge):
        gds = tmp / f"filled_{edge}.gds"
        rep = tmp / f"rep_{edge}.json"
        runner.run(ENGINE, {"FILL_GDS": str(fix), "FILL_CONFIG": str(_cfg(tmp, edge)),
                            "FILL_OUT": str(gds), "FILL_REPORT": str(rep)},
                   path_keys=("FILL_GDS", "FILL_CONFIG", "FILL_OUT", "FILL_REPORT"))
        assert gds.is_file(), f"engine produced no layout for edge={edge}"
        ms = tmp / f"measure_{edge}.py"
        ms.write_text(_MEASURE)
        mo = tmp / f"measure_{edge}.json"
        runner.run(ms, {"M_GDS": str(gds), "M_BAND": str(BAND), "M_OUT": str(mo)},
                   path_keys=("M_GDS", "M_OUT"))
        assert mo.is_file(), f"measurement did not run for edge={edge}"
        return json.loads(mo.read_text()), json.loads(rep.read_text())

    try:
        yield {"control": _one(0.0), "keepout": _one(BAND)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_positive_control_without_keepout_fill_DOES_reach_the_band(_run):
    """Without this, an empty band under the keep-out proves nothing — the
    fixture might simply never fill there."""
    meas, _ = _run["control"]
    assert meas["in_band_um2"] > 0.0, \
        "the control put no fill in the band, so the keep-out test is vacuous"


def test_keepout_leaves_the_band_completely_empty(_run):
    meas, _ = _run["keepout"]
    assert meas["in_band_um2"] == 0.0, \
        f"fill landed in the {BAND}um die-edge band: {meas['in_band_um2']} um2"


def test_keepout_still_fills_the_interior(_run):
    """The keep-out must cost the band, not the fill."""
    meas, rep = _run["keepout"]
    assert meas["in_core_um2"] > 0.0
    layer0 = rep["layers"][0]
    assert layer0["edge_exclusion_um"] == BAND
    assert layer0["excluded_area_um2"] > 0.0
