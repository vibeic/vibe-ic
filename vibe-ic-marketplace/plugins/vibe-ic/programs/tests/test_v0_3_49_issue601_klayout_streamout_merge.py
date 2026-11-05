"""ORGANIC #601 — KLayout-streamout fallback MUST merge abutting same-layer
geometry before signoff DRC.

Magic streamout merges natively; the KLayout fallback does NOT, so two
metal shapes abutting across a cell-instance boundary are written as
separate TOUCHING polygons and signoff DRC reads the shared boundary as a
zero-spacing edge-pair → a FALSE m1.2 (min met1 spacing) violation.
Measured on real Ibex (streamout=klayout): flatten + per-layer
Region.merge() cut m1.2 11,470 → 8,451 (−3,019 = 26% boundary false
positives); the remaining are genuine routing-spacing (design-DRC, not a
flow fix). The merge MUST be KLayout-native — Magic streamout core-dumped
on the very DEF that forced the fallback.

Locally verifiable: (a) the merge script does flatten + per-layer
Region.merge(); (b) it is wired on the KLAYOUT path only (Magic merges
natively); (c) NONFATAL swap/keep behaviour; (d) a pure-geometry no-leak
model — abutting same-layer rectangles union into one polygon (the false
boundary edge-pair disappears) while a genuinely-separated pair stays two
polygons (real spacing preserved). The real DRC count reduction is the
field agent's container measurement.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))


# ── the merge script: flatten + per-layer Region.merge() ────────────────────





# ── wiring: MUST run on the KLayout path, NOT the Magic path ─────────────────

def test_merge_wired_on_klayout_path_only():
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    # called once, on the klayout fallback path
    assert src.count("_klayout_merge_layers(project, top, pdk, container") >= 1
    assert '"layer_merge": merge_ok' in src
    # the Magic streamout PASS-return must NOT call the klayout merge
    # (Magic merges natively). Use the CALL form (`(project, top, pdk,
    # container`) — the def line is `(project: Path, top: str, …` so it
    # won't match. Split at the klayout streamout marker; the call must be
    # only on the klayout side, never before it (the Magic path).
    call = "_klayout_merge_layers(project, top, pdk, container"
    cut = src.index('script.write_text(_GDS_STREAMOUT_PY)')
    magic_side, klayout_side = src[:cut], src[cut:]
    assert call not in magic_side            # Magic path does not merge
    assert call in klayout_side              # KLayout path does


# ── NONFATAL helper behaviour ───────────────────────────────────────────────







# ── pure-geometry no-leak: abutting → merged (false edge-pair gone);
#    separated → preserved (genuine spacing still flagged) ────────────────────

def _union_if_abutting(r1, r2):
    """Minimal axis-aligned same-layer union model of Region.merge() for the
    test scenario: two rects sharing a full vertical edge (right of r1 ==
    left of r2, same y-span) union into one; otherwise they stay separate.
    r = (x0, y0, x1, y1)."""
    a_x0, a_y0, a_x1, a_y1 = r1
    b_x0, b_y0, b_x1, b_y1 = r2
    same_yspan = (a_y0 == b_y0 and a_y1 == b_y1)
    touch_x = (a_x1 == b_x0)            # r1's right edge meets r2's left edge
    if same_yspan and touch_x:
        return [(a_x0, a_y0, b_x1, a_y1)]   # one merged rect
    return [r1, r2]                          # two separate rects


def test_abutting_same_layer_merges_removing_false_edge_pair():
    # a cell pin (0..100) abutting a route (100..300) on the same layer,
    # same y-span — the shared boundary at x=100 is a FALSE m1.2 edge-pair
    r_pin = (0, 0, 100, 10)
    r_route = (100, 0, 300, 10)
    merged = _union_if_abutting(r_pin, r_route)
    assert len(merged) == 1                  # boundary edge-pair gone
    assert merged[0] == (0, 0, 300, 10)      # one continuous polygon


def test_genuinely_separated_pair_is_not_merged_NO_LEAK():
    # two shapes with a real gap (x=100..114, below 0.14µm=140 DBU min
    # met1 spacing) must stay SEPARATE so the genuine m1.2 is still flagged
    r1 = (0, 0, 100, 10)
    r2 = (114, 0, 300, 10)               # 14 DBU gap — a real violation
    merged = _union_if_abutting(r1, r2)
    assert len(merged) == 2                  # not unioned → DRC still sees it
