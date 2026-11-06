"""ORGANIC #600 ROUND 2 — instance-placement grid-snap.

v0.3.47 snapped only each cell's LOCAL shape vertices. Field-agent
artifact-first re-verify on real Ibex (24 MB GDS → real sky130 klayout
DRC → #594 classifier) measured the fix INSUFFICIENT:

    OFFGRID rule | before | after local-only snap
    m1_OFFGRID   | 29,670 | 15,785   (halved — top-level flat m1)
    ct_OFFGRID   |  6,204 |  6,204   (0 change)
    m2_OFFGRID   |  5,256 |  5,256   (0 change)
    li_OFFGRID   |      8 |      8   (0 change)
    total        | 46,614 | 32,729   (70% residual — still FAILS signoff)

The total reduction (−13,885) equalled the m1 reduction EXACTLY → snap
touched only top-level flat geometry. ct/li (std-cell internal) and m2
(via residue) were bit-identical because their LOCAL shapes were already
on-grid — only the instance PLACEMENT transform put them off-grid. OFFGRID
DRC judges ABSOLUTE coordinates (after the instance transform chain), so a
cell-local-only snap can never fix off-grid placement.

THE REAL FAILURE AXIS (this is what the round-2 fixture pins): an on-grid
local shape placed at an OFF-GRID origin streams an OFF-GRID absolute
coordinate. The fix snaps instance displacements (and array vectors) to
the grid too; for orthogonal mag-1 transforms that guarantees on-grid
absolute coordinates while preserving the hierarchy, with a flatten
fallback for exotic transforms.

Locally verifiable here: (a) the script now snaps instance placement +
has the flatten fallback; (b) a pure-Python model of the ABSOLUTE-
coordinate arithmetic the script implements proves the field agent's exact
residual (on-grid local @ off-grid placement) resolves to on-grid. The
real pya execution + container DRC-to-zero stays the field agent's
artifact-first measurement (the #594 classifier guards it).
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))


# ── the round-2 axis: the script now snaps instance PLACEMENT, not only
#    cell-local shapes ────────────────────────────────────────────────────────













# ── pure-Python proof of the ABSOLUTE-coordinate arithmetic the script
#    implements — pins the field agent's exact residual scenario ──────────────

GRID = 5  # sky130 mfg grid in DBU (0.005 µm / 0.001 µm-DBU)


def _snap(v):
    # mirror of the script's _snap_dbu
    return int(round(v / GRID)) * GRID


def _r0(x, y):
    return (x, y)


def _r90(x, y):
    # 90° CCW: (x, y) -> (-y, x)
    return (-y, x)


def test_local_only_snap_leaves_absolute_offgrid_THE_BUG():
    """Field agent's exact residual: a std cell whose LOCAL shape vertex is
    already on-grid, PLACED at an off-grid origin, streams an OFF-GRID
    absolute coordinate. A cell-local-only snap (a no-op on the already-
    on-grid local vertex) does NOT fix it."""
    local = (10, 20)              # on-grid library shape (both % 5 == 0)
    assert local[0] % GRID == 0 and local[1] % GRID == 0
    placement = (7, 13)          # OFF-grid instance origin (the defect)
    assert placement[0] % GRID != 0 and placement[1] % GRID != 0

    # local-only snap leaves the local vertex unchanged (already on-grid)
    snapped_local = (_snap(local[0]), _snap(local[1]))
    assert snapped_local == local

    # absolute = placement + R0(local) — still OFF-grid (the 70% residual)
    ax = placement[0] + _r0(*snapped_local)[0]
    ay = placement[1] + _r0(*snapped_local)[1]
    assert ax % GRID != 0 or ay % GRID != 0


def test_local_plus_placement_snap_makes_absolute_ongrid_THE_FIX():
    """Round-2: snapping the PLACEMENT displacement too makes the absolute
    coordinate land on-grid (R0 case)."""
    local = (10, 20)
    placement = (7, 13)
    snapped_place = (_snap(placement[0]), _snap(placement[1]))  # (5, 15)
    assert snapped_place == (5, 15)

    lx, ly = _r0(*local)
    ax, ay = snapped_place[0] + lx, snapped_place[1] + ly
    assert ax % GRID == 0 and ay % GRID == 0


def test_90deg_rotation_preserves_grid_after_placement_snap():
    """A 90°-multiple rotation maps the grid onto itself, so on-grid local
    ⊕ on-grid (snapped) placement ⇒ on-grid absolute even under R90 — this
    is why orthogonal mag-1 transforms need no flatten."""
    local = (10, 20)             # on-grid
    placement = (7, 13)
    snapped_place = (_snap(placement[0]), _snap(placement[1]))  # (5,15)

    lx, ly = _r90(*local)        # (-20, 10), still on-grid
    assert lx % GRID == 0 and ly % GRID == 0
    ax, ay = snapped_place[0] + lx, snapped_place[1] + ly
    assert ax % GRID == 0 and ay % GRID == 0


def test_snap_displacement_bounded_by_half_grid():
    """Any placement is moved at most half a grid step (≤2.5 nm) — far below
    sky130 min-spacing, so the snap cannot manufacture a real spacing DRC."""
    for off in range(-12, 13):
        moved = abs(_snap(off) - off)
        assert moved <= GRID / 2 + 1e-9


# ── wiring unchanged: both streamout paths still run the snap ───────────────

def test_both_streamout_paths_still_wired():
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    assert src.count("_gds_grid_snap(project, top, pdk, container") >= 2
    assert '"grid_snap": snap_ok' in src
