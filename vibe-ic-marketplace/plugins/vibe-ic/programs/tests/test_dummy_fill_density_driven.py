"""Density-driven multi-phase dummy-metal fill reaches the deck's declared
per-layer min_density where the legacy single-grid fill fell short.

The audited rot (real commercial-PDK subservient sign-off, phase3 GDS): the
config-driven dummy-METAL fill placed a SINGLE fixed grid (tile at pitch,
tiles fully clear of live metal). On a routing layer whose thin routes chop
the die into pockets that the one grid phase can not align to, the whole-die
fill fell just short of the deck minimum — MET3 reached density 0.2845 vs the
`PDF.D.6.1_3  DENSITY MET3_DUD < 0.3` full-chip minimum, firing the ONLY DRC
violation in an otherwise 4532/4533-clean run (MET1 0.3656 / MET2 0.3064 /
MET4 0.4383 all cleared; only MET3 under-filled).

The fix makes the fill DENSITY-DRIVEN: after the legacy base grid (phase 0,
reproduced byte-for-byte) the layer is topped up with phase-shifted grids that
drop tiles into the grid-misaligned pockets the base grid missed, stopping the
instant the layer reaches its declared `min_density`. Every pass keeps a tile
only when it is a full `margin` from live metal AND a full `gap` (= pitch -
tile, the base grid's own proven-legal neighbour spacing) from already-placed
fill, so densifying never merges tiles into wide-metal nor crowds spacing —
the sign-off deck re-checks the filled GDS with every rule live.

chip-AGNOSTIC: pure geometry + the PDK bridge's own per-layer targets. No
vendor / PDK / design literal appears in the fill logic or here.

This test carries a faithful pure-Python model of the shipped tile-keeping
rule (exact axis-aligned box arithmetic mirroring KLayout `select_inside(frame
- live.sized(margin) - placed.sized(gap))`) so the property is proven on
controlled synthetic geometry with NOTHING hardcoded — the densities are
measured, and the target is chosen strictly between them — plus source-text
invariants that pin the density-driven multi-phase logic into the shipped
`_GDS_DUMMY_FILL_PY` so a regression that reverts to a single grid fails here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as p3  # noqa: E402


# --------------------------------------------------------------------------
# faithful pure-Python model of the shipped fill's per-tile keep rule
# --------------------------------------------------------------------------
def _overlap(a, b):
    """True iff axis-aligned boxes a,b share interior area (edge touch = no)."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _grow(box, d):
    x0, y0, x1, y1 = box
    return (x0 - d, y0 - d, x1 + d, y1 + d)


def _fill(die, routes, *, tile, pitch, margin, min_density, multiphase):
    """Return (density, placed_boxes). Mirrors _GDS_DUMMY_FILL_PY:
      * a tile is kept iff it is inside the margin-inset die frame, clear of
        every live route grown by `margin`, and clear of every already-placed
        tile grown by `gap` (= pitch - tile);
      * within a phase, grid tiles are committed together (grid pitch supplies
        their mutual spacing); later phases see them as placed;
      * with a target, phase-shifted grids top up until it is met; with no
        target (or `multiphase=False`) only the legacy base grid runs.
    """
    D0x, D0y, D1x, D1y = die
    die_area = float((D1x - D0x) * (D1y - D0y))
    gap = max(1, pitch - tile)
    fr0x, fr0y, fr1x, fr1y = D0x + margin, D0y + margin, D1x - margin, D1y - margin
    route_halos = [_grow(r, margin) for r in routes]

    phases = [(margin, margin)]
    if multiphase:
        for f in (0.5, 0.25, 0.75):
            off = int(pitch * f)
            phases += [(margin + off, margin + off),
                       (margin + off, margin),
                       (margin, margin + off)]

    placed = []
    for (x0, y0) in phases:
        placed_halos = [_grow(pb, gap) for pb in placed]
        phase_kept = []
        x = D0x + x0
        while x + tile <= D1x - margin:
            y = D0y + y0
            while y + tile <= D1y - margin:
                bx = (x, y, x + tile, y + tile)
                inside = (bx[0] >= fr0x and bx[1] >= fr0y
                          and bx[2] <= fr1x and bx[3] <= fr1y)
                if (inside
                        and not any(_overlap(bx, h) for h in route_halos)
                        and not any(_overlap(bx, h) for h in placed_halos)):
                    phase_kept.append(bx)
                y += pitch
            x += pitch
        placed.extend(phase_kept)
        area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in placed)
        dens = area / die_area if die_area else 0.0
        if not min_density or dens >= min_density:
            break
    area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in placed)
    return (area / die_area if die_area else 0.0), placed


# A routing layer whose thin routes cluster at the OUTER edges of pairs of
# base-grid columns: each pair's two base tiles are rejected (a route halo
# clips each), but the pair's centre stays clear a full tile wide — a pocket
# grid-MISALIGNED to the base phase, so the single base grid under-fills it and
# only a phase-shifted grid recovers it. This is the toy analogue of the real
# irregular routing that left MET3 at 0.2845. Nothing here is vendor/PDK
# specific — it is pure grid geometry.
_DIE = (0, 0, 400, 400)
_TILE, _PITCH, _MARGIN = 14, 19, 7


def _clustered_routes():
    routes = []
    k = 2
    while _MARGIN + (k + 1) * _PITCH + _TILE < _DIE[2] - _MARGIN:
        xk = _MARGIN + k * _PITCH
        # A: far-left sliver of column k  -> rejects column k's base tile
        routes.append((xk, 0, xk + 1, _DIE[3]))
        # B: far-right sliver of column k+1 -> rejects column k+1's base tile,
        # leaving the ~tile-wide centre [xk+8, xk+25] clear for an offset tile.
        routes.append((xk + 2 * _PITCH - 6, 0, xk + 2 * _PITCH - 5, _DIE[3]))
        k += 4
    return routes


_ROUTES = _clustered_routes()


def test_multiphase_beats_single_grid():
    d_legacy, _ = _fill(_DIE, _ROUTES, tile=_TILE, pitch=_PITCH,
                        margin=_MARGIN, min_density=0.0, multiphase=False)
    d_multi, _ = _fill(_DIE, _ROUTES, tile=_TILE, pitch=_PITCH,
                       margin=_MARGIN, min_density=1.0, multiphase=True)
    # densification strictly adds fill in the grid-misaligned pockets.
    assert d_multi > d_legacy, (d_legacy, d_multi)


def test_reaches_target_the_single_grid_misses():
    d_legacy, _ = _fill(_DIE, _ROUTES, tile=_TILE, pitch=_PITCH,
                        margin=_MARGIN, min_density=0.0, multiphase=False)
    d_multi, _ = _fill(_DIE, _ROUTES, tile=_TILE, pitch=_PITCH,
                       margin=_MARGIN, min_density=1.0, multiphase=True)
    # a deck minimum the LEGACY grid fails but the multi-phase fill clears.
    target = (d_legacy + d_multi) / 2.0
    assert d_legacy < target <= d_multi
    dens, _ = _fill(_DIE, _ROUTES, tile=_TILE, pitch=_PITCH, margin=_MARGIN,
                    min_density=target, multiphase=True)
    assert dens >= target


def test_density_driven_stops_at_target_not_max():
    # once the target is met the fill stops — it does not over-fill to the max.
    d_multi_max, _ = _fill(_DIE, _ROUTES, tile=_TILE, pitch=_PITCH,
                           margin=_MARGIN, min_density=1.0, multiphase=True)
    d_legacy, _ = _fill(_DIE, _ROUTES, tile=_TILE, pitch=_PITCH,
                        margin=_MARGIN, min_density=0.0, multiphase=False)
    target = (d_legacy + d_multi_max) / 2.0
    dens, _ = _fill(_DIE, _ROUTES, tile=_TILE, pitch=_PITCH, margin=_MARGIN,
                    min_density=target, multiphase=True)
    assert target <= dens < d_multi_max + 1e-9


def test_spacing_safe_no_wide_metal():
    # every placed tile keeps its tile size (never merges = no wide-metal) and
    # stays >= gap from every other tile and >= margin from every live route.
    gap = _PITCH - _TILE
    _, placed = _fill(_DIE, _ROUTES, tile=_TILE, pitch=_PITCH, margin=_MARGIN,
                      min_density=1.0, multiphase=True)
    assert len(placed) > 0
    for b in placed:
        assert (b[2] - b[0]) == _TILE and (b[3] - b[1]) == _TILE
    for r in _ROUTES:
        h = _grow(r, _MARGIN)
        assert not any(_overlap(b, h) for b in placed)
    # no two tiles come closer than `gap` (grow one by gap-1 -> still no overlap)
    for i, a in enumerate(placed):
        ah = _grow(a, gap - 1)
        for b in placed[i + 1:]:
            assert not _overlap(ah, b)


def test_no_target_is_legacy_single_pass():
    # byte-compat: with no declared min_density the multi-phase path must break
    # after the base grid, i.e. be identical to the legacy single grid.
    d_legacy, boxes_legacy = _fill(_DIE, _ROUTES, tile=_TILE, pitch=_PITCH,
                                   margin=_MARGIN, min_density=0.0,
                                   multiphase=False)
    d_none, boxes_none = _fill(_DIE, _ROUTES, tile=_TILE, pitch=_PITCH,
                               margin=_MARGIN, min_density=0.0, multiphase=True)
    assert d_none == d_legacy
    assert sorted(boxes_none) == sorted(boxes_legacy)


# --------------------------------------------------------------------------
# source-text invariants: pin the density-driven multi-phase logic into the
# shipped fill script so a regression to a single fixed grid fails here.
# --------------------------------------------------------------------------
def test_shipped_fill_script_is_density_driven():
    src = p3._GDS_DUMMY_FILL_PY
    assert 'min_density' in src, "fill script must read the declared min_density"
    assert 'pitch - tile' in src, "fill-to-fill spacing floor must be pitch-tile"
    # phase-shifted top-up grids beyond the single base grid.
    assert 'phases' in src and '0.5' in src and '0.25' in src
    # the legacy base grid is still phase 0.
    assert '(margin, margin)' in src
    # stops when the declared density target is reached.
    assert 'dens >= min_density' in src


def test_shipped_fill_script_still_reports_and_terminates():
    src = p3._GDS_DUMMY_FILL_PY
    assert 'DUMMY_FILL %s tiles=%d density=%.4f' in src
    assert 'DUMMY_FILL_DONE' in src
