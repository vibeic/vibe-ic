"""v1.4.x — std-cell marker widened from DEF/LEF SIZE bbox to true library
extent, with a mandatory anti-masking guard (spm commercial PDK real-flow close-loop,
2026-07-16).

Root cause (proven on the real commercial-PDK std-cell library, all 256 residual DRC
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

Anti-masking guard (mandatory, waiver-adjacent): the painted region may only
ever land on qualified-cell geometry — never on real net-carrying content.
Right after the bare DEF+LEF read and before manual FEOL substitution copies
any cell's real geometry in, the only flat top-level shapes on other layers
are the DEF's ROUTED/SPECIALNETS wires, so intersecting the painted region
against every other layer's flat top-level shapes is a clean, chip-agnostic
over-waive detector.

FOLLOW-ON FIX (caravel commercial PDK dense-routing close-loop, 2026-07-17):
v1.4.42 checked only the ADDED (overhang) ring and, on a hit, reverted to the
old SIZE-box coverage. Two measured defects: (1) the marker exempts METAL too
(the deck derives `__metN__ = NOT METN DCTY` for MET1..8 exactly as it does the
FEOL layers), so painting it over ANY routed wire — SIZE-box interior included,
not just the overhang — carves that wire into min-width/-space slivers AND
waives its real DRC (a #511 over-waive); (2) the SIZE-box fallback still carved
(caravel real deck: no-marker 10 fails → SIZE-box paint 22 → true-extent paint
18). Fix: probe the ENTIRE painted region (SIZE-box ∪ true-extent) against
top-level nets, and on ANY overlap paint NOTHING for the layer — never the
SIZE-box fallback. All configured marker layers are resolved up front and
painted with the identical region (net probe excludes every marker layer) so
the deck's Artisan ⊆ DCTY0 consistency rule cannot fire from a paint mismatch.
Proven: caravel dense → guard skips → DRC == the no-marker baseline (no harm,
no over-waive); a net-free qualified-cell interior over-fire still CLEARS while
a real off-cell violation still FAILS.

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
    # Follow-on fix (caravel commercial PDK, dense-routing close-loop): the guard probes
    # the ENTIRE painted region (SIZE-box ∪ true-extent), not just the overhang
    # ring, against top-level net geometry — because the deck derives METAL the
    # same `__metN__ = NOT METN <marker>` way it derives FEOL, so a marker pixel
    # over a routed wire carves that wire (proven on caravel: no-marker 10 fails →
    # SIZE-box paint 22 → true-extent paint 18). On overlap it paints NOTHING —
    # NEVER the old SIZE-box fallback, which itself carved.
    assert "_paint_reg" in src and "_net_reg" in src
    assert "(_paint_reg & _net_reg)" in src
    assert "NOT painted" in src                    # skip, not revert
    assert "reverted to SIZE-bbox" not in src      # the harmful fallback is gone


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


def test_full_region_guard_passes_when_no_routing_is_under_the_marker():
    # Follow-on fix: the guard now probes the ENTIRE painted region (SIZE-box ∪
    # true-extent = `covered`), not merely the overhang ring. No routed-net box
    # anywhere near this instance -> guard passes and paints the FULL true extent.
    size_box = (0, 0, 528, 504)
    lib_box = (-22, -31, 550, 535)
    covered = _box_union(size_box, lib_box)
    net_boxes = [(2000, 2000, 2100, 2100)]   # far away, unrelated net
    leaked = any(_box_overlaps(covered, net) for net in net_boxes)
    assert leaked is False
    painted = covered if not leaked else None
    assert painted == covered                # paints the true extent, not size_box
    assert covered != size_box


def test_full_region_guard_skips_when_routing_runs_through_the_size_box_interior():
    # THE caravel bug this fix closes: a routed wire runs through the SIZE box
    # INTERIOR (not merely the overhang ring the old guard checked). The marker
    # exempts metal too, so painting it there would carve that wire. The old
    # guard's "revert to SIZE-box" fallback still carved it; the fixed guard
    # paints NOTHING for this layer.
    size_box = (0, 0, 528, 504)
    lib_box = (-22, -31, 550, 535)
    covered = _box_union(size_box, lib_box)
    net_boxes = [(100, 100, 200, 400)]       # a wire INSIDE the SIZE box
    leaked = any(_box_overlaps(covered, net) for net in net_boxes)
    assert leaked is True
    painted = covered if not leaked else None
    assert painted is None                    # SKIP entirely — never size_box
    assert painted != size_box


def test_full_region_guard_catches_overhang_routing_too():
    # The old overhang-ring-only guard still tripped on routing under the added
    # margin; the full-region guard must remain at least as strict there.
    size_box = (0, 0, 528, 504)
    lib_box = (-22, -31, 550, 535)
    covered = _box_union(size_box, lib_box)
    net_boxes = [(-30, 100, 10, 200)]         # under the LEFT overhang margin
    leaked = any(_box_overlaps(covered, net) for net in net_boxes)
    assert leaked is True
    painted = covered if not leaked else None
    assert painted is None


# ── _classify_svrf_fails: Mx.A.1's "marker_absent"/artisan label was right
#    by luck, not by valid criterion (the deck's OR(CUT,ANDNOT) recombination
#    to the un-split identity fires regardless of whether the second operand
#    is empty) — documented so a future rule with the same shape isn't
#    mis-classified in either direction. ──────────────────────────────────────

def test_all_marker_layers_resolved_up_front_and_painted_identically():
    # Multi-marker consistency: ALL configured marker layers are resolved up
    # front (`_marker_lis`) and painted with the SAME `_paint_reg`, so a deck's
    # "identity ⊆ don't-check" consistency rule (commercial PDK: Artisan ⊆ DCTY0, its
    # `COPY (Artisan andnot DCTY)` check) can never fire from a per-layer paint
    # mismatch. Proven necessary: painting 65/0 then letting 113/0's net probe
    # see the just-painted 65/0 as "net" would skip 113/0 and light up the
    # Artisan.CHECK consistency rule.
    src = p3._GDS_STREAMOUT_PY
    assert "_marker_lis" in src
    assert "_marker_li_set" in src
    assert "for _one, _li_m in _marker_lis" in src


def test_net_probe_excludes_every_marker_layer():
    # A marker layer carries no net — it is the marker we are about to paint —
    # so the net probe MUST exclude ALL marker layers (not just the current one),
    # else the first-painted marker blocks the second.
    src = p3._GDS_STREAMOUT_PY
    assert "if _oli in _marker_li_set" in src


def test_streamout_documents_metal_is_marker_exempted_too():
    # The load-bearing root cause: the deck derives METAL the same
    # `__metN__ = NOT METN <marker>` way as FEOL, so the marker is NOT a
    # FEOL-only exemption — painting it over a routed wire carves that wire.
    # This rationale must be on record in the guard comment.
    src = p3._GDS_STREAMOUT_PY
    assert "__met1__ = NOT MET1 DCTY" in src or "exempts metal too" in src


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
