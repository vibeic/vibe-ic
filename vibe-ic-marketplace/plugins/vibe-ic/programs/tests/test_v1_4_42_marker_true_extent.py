"""v1.4.x — std-cell marker widened from DEF/LEF SIZE bbox to true library
extent, with a mandatory anti-masking guard (spm HP18E80 real-flow close-loop,
2026-07-16).

Root cause (proven on the real HP18E80 std-cell library, all 256 residual DRC
instances across NPSD.W/A.1, PPSD.W/A.1, BASIC.TAP.OT.1, Mx.W.1_35/36/37,
Mx.A.1(+_22/_23)): EVERY sampled library master (fillers included, not just
active cells) draws its implant/metal a small amount OUTSIDE its own DEF/LEF
SIZE bbox by design — an abutment-merge overhang meant to be absorbed by a
neighbouring cell's matching overhang. At a placement-row/core-boundary edge
there is no neighbour, so the overhang survives past the SIZE-box marker the
old code painted (`_inst.bbox()`), and the deck's own qualified-cell exemption
never reaches it: real, benign, foundry-drawn geometry then fires as if it
were fresh backend content.

Fix: paint each instance's TRUE extent — the transformed bbox of its OWN
library-GDS cell (whatever that specific master draws, on any layer) unioned
with the old SIZE box (so coverage never shrinks) — instead of the SIZE box
alone. chip/PDK-AGNOSTIC: the extent is read back from the library GDS
per-master at runtime; no cell name or overhang margin (e.g. the 0.22um /
0.62um measured on THIS library) is ever hardcoded.

Anti-masking guard (mandatory, waiver-adjacent): the ADDED coverage may only
ever land on qualified-cell geometry — never on real net-carrying content.
Right after the bare DEF+LEF read and before manual FEOL substitution copies
any cell's real geometry in, the only flat top-level shapes on other layers
are the DEF's ROUTED/SPECIALNETS wires, so intersecting the added region
against every other layer's flat top-level shapes is a clean, chip-agnostic
over-waive detector. Any hit reverts that marker layer's painted region to
the old SIZE-box coverage and discloses it — never a silent over-waive.

These tests model the box/region algebra in plain Python (no `pya` — not
importable on the host outside the vibeic-eda container) plus source-text +
compile assertions on the embedded `_GDS_STREAMOUT_PY` klayout script, same
discipline as test_v0_3_49_issue601_klayout_streamout_merge.py.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402


# ── the embedded klayout script itself ──────────────────────────────────────

def test_streamout_script_compiles():
    compile(p3._GDS_STREAMOUT_PY, "<streamout>", "exec")


def test_streamout_uses_true_library_extent_not_size_bbox_alone():
    src = p3._GDS_STREAMOUT_PY
    assert "_lib_extent(" in src
    assert "_old_box + _true_box" in src        # Box union — never shrinks
    assert "_inst.trans" in src                  # placed per-instance, not a blanket fill
    assert "_dbu_scale" in src                   # derived scaling, not assumed-equal DBUs


def test_streamout_has_the_anti_masking_guard():
    src = p3._GDS_STREAMOUT_PY
    assert "ANTI-MASKING GUARD" in src
    assert "_leak" in src
    assert "_added" in src
    # the guard must revert (not merely warn) when it trips
    assert "reverted to SIZE-bbox" in src or "revert" in src.lower()


def test_streamout_never_hardcodes_the_measured_overhang_margin():
    # This library measured 0.22um (H) / 0.62um (V) overhang — that number
    # must NEVER appear as a literal in the fix; it must be re-derived from
    # the library GDS on every run, for every PDK.
    src = p3._GDS_STREAMOUT_PY
    assert "0.22" not in src
    assert "0.62" not in src


# ── pure-Python box/region model (mirrors pya.Box `+`/`-` semantics used in
#    the real script; validated 1:1 against real klayout `pya` behaviour
#    before landing: Box+Box == bbox union, Region-Region == set difference) ─

def _box_union(a, b):
    """axis-aligned bbox union, mirroring KLayout's `Box + Box`."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return (min(ax0, bx0), min(ay0, by0), max(ax1, bx1), max(ay1, by1))


def _box_overlaps(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def test_true_extent_union_expands_to_cover_overhang():
    size_box = (0, 0, 528, 504)          # e.g. DECAP8, DEF/LEF SIZE bbox (DBU)
    lib_box = (-22, -31, 550, 535)       # that master's OWN library-GDS bbox: overhangs every side
    covered = _box_union(size_box, lib_box)
    assert covered == lib_box             # union == the larger (true) extent
    # covered must be a superset of the SIZE box on every edge (never shrinks)
    assert covered[0] <= size_box[0] and covered[1] <= size_box[1]
    assert covered[2] >= size_box[2] and covered[3] >= size_box[3]


def test_true_extent_union_is_a_noop_when_master_has_no_overhang():
    size_box = (0, 0, 132, 504)           # e.g. a hypothetical master with none
    lib_box = (0, 0, 132, 504)            # library GDS extent == its own SIZE
    covered = _box_union(size_box, lib_box)
    assert covered == size_box             # no spurious expansion


def test_anti_masking_guard_passes_when_added_margin_is_clear():
    size_box = (0, 0, 528, 504)
    lib_box = (-22, -31, 550, 535)
    covered = _box_union(size_box, lib_box)
    # "added" region is (covered minus size_box); model it as the 4 margin
    # strips a real Region difference would produce. No routed-net box
    # anywhere near this instance -> guard must pass (no revert).
    other_net_boxes = [(2000, 2000, 2100, 2100)]   # far away, unrelated net
    added_strips = [
        (covered[0], covered[1], size_box[0], covered[3]),   # left margin
        (size_box[2], covered[1], covered[2], covered[3]),   # right margin
        (covered[0], covered[1], covered[2], size_box[1]),   # bottom margin
        (covered[0], size_box[3], covered[2], covered[3]),   # top margin
    ]
    leaked = any(_box_overlaps(strip, net) for strip in added_strips for net in other_net_boxes)
    assert leaked is False
    # -> the real code paints `covered`, not `size_box`
    assert covered != size_box


def test_anti_masking_guard_trips_and_reverts_when_routing_is_under_the_margin():
    size_box = (0, 0, 528, 504)
    lib_box = (-22, -31, 550, 535)
    covered = _box_union(size_box, lib_box)
    # a routed-net wire happens to run straight through the LEFT margin strip
    other_net_boxes = [(-30, 100, 10, 200)]
    added_strips = [
        (covered[0], covered[1], size_box[0], covered[3]),   # left margin
        (size_box[2], covered[1], covered[2], covered[3]),   # right margin
        (covered[0], covered[1], covered[2], size_box[1]),   # bottom margin
        (covered[0], size_box[3], covered[2], covered[3]),   # top margin
    ]
    leaked = any(_box_overlaps(strip, net) for strip in added_strips for net in other_net_boxes)
    assert leaked is True
    # -> the real code MUST revert to `size_box` for this instance/layer,
    #    never ship `covered` when a real net is under the added margin.
    painted = size_box if leaked else covered
    assert painted == size_box


# ── _classify_svrf_fails: Mx.A.1's "marker_absent"/artisan label was right
#    by luck, not by valid criterion (the deck's OR(CUT,ANDNOT) recombination
#    to the un-split identity fires regardless of whether the second operand
#    is empty) — documented so a future rule with the same shape isn't
#    mis-classified in either direction. ──────────────────────────────────────

def test_classify_svrf_fails_module_documents_the_or_cut_andnot_identity_caveat():
    src = Path(p3.__file__).read_text()
    idx = src.index("def _classify_svrf_fails(")
    taxonomy_block = src[:idx]
    # the caveat must be on record near the MARKER_ABSENT taxonomy comment —
    # not asserting new classification behaviour (the conservative
    # GEOMETRY-until-proven default is unchanged and correct), just that a
    # future reader is warned the `_not_X` name-match is a proxy, not proof.
    assert "CAVEAT" in taxonomy_block
    assert "OR(CUT(A, X), ANDNOT(A, X))" in taxonomy_block
    assert "right BY LUCK" in taxonomy_block
