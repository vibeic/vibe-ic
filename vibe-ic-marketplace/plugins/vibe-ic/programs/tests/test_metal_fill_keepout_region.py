"""metal_fill — a KEEP-OUT region, and the control that proves it is load-bearing.

WHAT WENT WRONG WITHOUT IT
--------------------------
The fill engine fills the whole measured area. That is right while the die is
only the routed core, and wrong the moment anything else is drawn on it. A seal
ring is added AFTER routing; it carries a marker layer with its own
metal-clearance rule; and dummy fill is metal like any other.

MEASURED (2026-08-20, one sealed 0.5x0.5-slot die, this PDK's own sign-off
deck): filling the sealed die with no keep-out took DRC 1177 -> 18686, and the
entire delta was ONE rule -- the guard-ring-marker-to-metal clearance --
19 -> 17528. No density rule regressed; every other rule count was
bit-identical. The same fill on the SAME die WITHOUT the ring added zero
violations, which is the control that isolates the ring as the cause.

THE CONTROL HERE
----------------
`test_fill_lands_in_the_band_without_a_keepout` is the negative arm: it asserts
that the engine, given no keep-out, DOES put fill inside the band. If a future
change makes the engine avoid that band for some other reason, this test fails
and the positive test below stops proving anything -- which is exactly what a
bidirectional control is for.

The denominator is deliberately NOT shrunk by the keep-out: the foundry density
rule measures coverage over the whole die INCLUDING the band, so measuring over
a smaller area would report a density the deck will not agree with.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ENGINE = Path(__file__).resolve().parents[1] / "metal_fill" / "metal_fill.py"
_MARKER = (167, 5)          # this PDK's guard-ring marker; an INPUT, not a constant
_KEEPOUT_UM = 10.0          # its metal clearance, from the PDK's own deck
_DIE = 400.0                # um
_RING = 10.0                # um-wide marker band at the die edge


def _klayout():
    for exe in ("klayout", "strmrun"):
        try:
            if subprocess.run([exe, "-v"], capture_output=True,
                              timeout=60).returncode == 0:
                return exe
        except (OSError, subprocess.SubprocessError):
            continue
    return None


_KL = _klayout()
pytestmark = pytest.mark.skipif(
    _KL is None,
    reason="no host KLayout — the fill engine is a KLayout batch script")


_BUILD = r'''
import pya, os
ly = pya.Layout(); ly.dbu = 0.001
top = ly.create_cell("KO")
U = 1000
die = int(%(die)f * U); ring = int(%(ring)f * U)
# one thin wire so the layer is not empty, far from the band
top.shapes(ly.layer(34, 0)).insert(pya.Box(int(190*U), int(190*U), int(190.5*U), int(210*U)))
# the marker: a ring-shaped polygon at the die edge (outer box minus inner box)
outer = pya.Region(pya.Box(0, 0, die, die))
inner = pya.Region(pya.Box(ring, ring, die - ring, die - ring))
for p in (outer - inner).each():
    top.shapes(ly.layer(%(mk_l)d, %(mk_d)d)).insert(p)
ly.write(os.environ["OUT"])
'''


_COUNT = r'''
import pya, os
ly = pya.Layout(); ly.read(os.environ["GDS"]); top = ly.top_cell()
def reg(n, d):
    li = ly.find_layer(n, d)
    return pya.Region(top.begin_shapes_rec(li)) if li is not None else pya.Region()
mk = reg(%(mk_l)d, %(mk_d)d).merged()
band = mk.sized(int(%(ko)f / ly.dbu))
fill = reg(34, 4)
print("IN_BAND", (fill & band).count())
print("TOTAL", fill.count())
'''


def _run(script: str, env: dict, tmp_path: Path, name: str) -> str:
    p = tmp_path / name
    p.write_text(script)
    e = dict(os.environ); e.update(env)
    cp = subprocess.run([_KL, "-b", "-r", str(p)], capture_output=True,
                        text=True, timeout=1800, env=e)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    return cp.stdout


def _cfg(tmp_path: Path, keepout) -> Path:
    cfg = {
        "boundary_layer": None,
        "window_um": None,
        "max_passes": 4,
        "mfg_grid_um": 0.005,
        "fill_datatype": None,
        "keepout": keepout,
        "layers": [{"name": "metal1", "layer": [34, 0], "target": 0.20,
                    "max": 0.95, "space": 0.98, "space_to_metal": 2.0,
                    "width": 3.37, "fill_datatype": 4}],
    }
    p = tmp_path / ("cfg_%s.json" % ("ko" if keepout else "none"))
    p.write_text(json.dumps(cfg))
    return p


def _fill(tmp_path: Path, keepout, tag: str):
    src = tmp_path / "in.gds"
    _run(_BUILD % {"die": _DIE, "ring": _RING,
                   "mk_l": _MARKER[0], "mk_d": _MARKER[1]},
         {"OUT": str(src)}, tmp_path, "build.py")
    out = tmp_path / ("out_%s.gds" % tag)
    rep = tmp_path / ("rep_%s.json" % tag)
    _run(_ENGINE.read_text(),
         {"FILL_GDS": str(src), "FILL_CONFIG": str(_cfg(tmp_path, keepout)),
          "FILL_OUT": str(out), "FILL_REPORT": str(rep)},
         tmp_path, "engine_%s.py" % tag)
    counts = _run(_COUNT % {"mk_l": _MARKER[0], "mk_d": _MARKER[1],
                            "ko": _KEEPOUT_UM},
                  {"GDS": str(out)}, tmp_path, "count_%s.py" % tag)
    got = {k: int(v) for k, v in
           (ln.split() for ln in counts.splitlines()
            if ln.startswith(("IN_BAND", "TOTAL")))}
    return got, json.loads(rep.read_text())


def test_fill_lands_in_the_band_without_a_keepout(tmp_path):
    """NEGATIVE ARM. Without a keep-out the engine fills the band — so the
    positive test below is testing something that can actually fail."""
    got, _ = _fill(tmp_path, [], "none")
    assert got["TOTAL"] > 0, "the fixture gave the engine nothing to do"
    assert got["IN_BAND"] > 0, (
        "the engine put NO fill in the marker band even with no keep-out — the "
        "positive test can no longer prove the keep-out is what excludes it")


def test_keepout_empties_the_band_and_does_not_shrink_the_denominator(tmp_path):
    got, rep = _fill(tmp_path, [{"layer": list(_MARKER),
                                 "space_um": _KEEPOUT_UM}], "ko")
    assert got["IN_BAND"] == 0, "fill inside the declared keep-out region"
    assert got["TOTAL"] > 0, "the keep-out suppressed the whole fill"
    # The keep-out is DISCLOSED, with what it actually found.
    assert rep["keepout"] and rep["keepout"][0]["shapes"] > 0
    # ...and the density is still stated over the whole die, not the fillable
    # part of it: the foundry rule measures the whole die.
    lay = rep["layers"][0]
    assert lay["density_after"] > lay["density_before"]


def test_absent_keepout_layer_keeps_out_nothing_and_says_so(tmp_path):
    """A declared layer that carries no geometry must not silently behave like
    a keep-out that worked. It keeps out nothing, and the report says shapes=0."""
    got, rep = _fill(tmp_path, [{"layer": [999, 0], "space_um": _KEEPOUT_UM}],
                     "absent")
    assert got["IN_BAND"] > 0
    assert rep["keepout"][0]["shapes"] == 0
