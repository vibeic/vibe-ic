"""The floorplan must never place into the band the slot reserves for the ring.

THE MEASUREMENT THAT CREATED THIS FILE
======================================
A `spm` die floorplanned for the smallest slot, sealed by the PDK's own
generator, refused by the shuttle operator's own precheck container:

    KLayout DRC, operator's stage 14        BEFORE      AFTER (this fix)
      GR.4  guard-ring width                   794             0
      GR.2  guard-ring …                        19             0
      total                                   1177           360

The 360 that remain are coordinate-identical in the UNSEALED layout and are a
separate defect; this file is not about them.

The ring was not malformed. Measured three ways: the unsealed die alone gave
GR.4 = 0, the ring alone in isolation gave GR.4 = 0 on every metal layer, and
only their UNION gave 794. `GR.4` is `metal.not_outside(guard_ring_mk)
.width(12.um)` — `not_outside` selects any polygon merely TOUCHING the marker
band and measures that WHOLE polygon, so one 0.28 µm pin wire touching the band
is reported along its entire length.

What was in the band was the PINS: all 41, port-box edge distance 0.000 µm,
because OpenROAD `ppl` places IO pins on the DIE boundary and has no
core-boundary mode. Measured directly: with `-core_area` already set 442 µm
inside the die, standard-cell rows stopped 442 µm clear and metal fill put
0.000 µm² in the band — and all 41 pins were still flush on the die edge.

So the reserve is not the seal-ring step's to defend. The operator's template
pins BOTH `DIE_AREA` and `CORE_AREA` per slot, step 0.5ic ingested both, and
the floorplan read only the die.

NEGATIVE CONTROL, in both directions:
  * `test_reserved_slot_moves_the_floorplan_off_the_die_edge` FAILS against the
    pre-fix body, which emitted `-die_area "0 0 1936 2531"` for this input.
  * `test_a_project_with_no_slot_template_is_byte_identical` FAILS against a
    "fix" that offsets every floorplan, which would move every existing die.

chip-AGNOSTIC: every geometry number in the fixtures is written INTO the
fixture by the test. Nothing here reads a real PDK, foundry, node or SKU.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as R  # noqa: E402

SLOT_DIR = "input/submission_template/slots"
REPORT = "reports/phase1/submission_template.json"


def _slot_record(die, core, name="slot_a"):
    """A slot file in the shape step 0.5ic actually writes: its own RECORD."""
    def rect(r):
        return {"key": "DIE_AREA", "raw": list(r),
                "rect": [str(v) for v in r]}
    rec = {"slot": name, "die_area": rect(die)}
    if core is not None:
        rec["core_area"] = rect(core)
    return rec


def _project(tmp_path, slots, declared=None, raw_form=False):
    d = tmp_path / SLOT_DIR
    d.mkdir(parents=True)
    for name, (die, core) in slots.items():
        if raw_form:
            # The operator's own config spelling, which the same reader must
            # also understand — the ingester is not the only possible producer.
            body = {"DIE_AREA": list(die)}
            if core is not None:
                body["CORE_AREA"] = list(core)
        else:
            body = _slot_record(die, core, name)
        (d / f"{name}.yaml").write_text(json.dumps(body))
    if declared is not None:
        rep = tmp_path / REPORT
        rep.parent.mkdir(parents=True, exist_ok=True)
        rep.write_text(json.dumps({"ingest": {"declared_slot": declared}}))
    return tmp_path


# --------------------------------------------------------------------------- #
# the reserve itself
# --------------------------------------------------------------------------- #
def test_reserved_slot_moves_the_floorplan_off_the_die_edge(tmp_path):
    """The floorplan rect becomes the slot's CORE_AREA, not its DIE_AREA."""
    p = _project(tmp_path,
                 {"slot_a": ((0, 0, 1936, 2531), (442, 442, 1494, 2089))},
                 declared="slot_a")
    r = R._slot_floorplan_reserve(p)
    assert r["applies"] is True
    assert r["floorplan_rect_um"] == ["442", "442", "1494", "2089"]
    assert r["slot_die_um"] == ["1936", "2531"]
    assert r["reserve_um"] == {"left": "442", "bottom": "442",
                               "right": "442", "top": "442"}


def test_the_operators_own_config_spelling_is_understood_too(tmp_path):
    p = _project(tmp_path,
                 {"slot_a": ((0, 0, 100, 200), (10, 20, 90, 180))},
                 declared="slot_a", raw_form=True)
    r = R._slot_floorplan_reserve(p)
    assert r["applies"] is True
    assert r["floorplan_rect_um"] == ["10", "20", "90", "180"]
    assert r["reserve_um"] == {"left": "10", "bottom": "20",
                               "right": "10", "top": "20"}


def test_an_asymmetric_reserve_is_carried_per_side(tmp_path):
    """The reserve is four numbers. A template that is not square in its
    margins must not be averaged into one."""
    p = _project(tmp_path,
                 {"slot_a": ((0, 0, 1000, 2000), (30, 40, 950, 1900))},
                 declared="slot_a")
    r = R._slot_floorplan_reserve(p)
    assert r["reserve_um"] == {"left": "30", "bottom": "40",
                               "right": "50", "top": "100"}


# --------------------------------------------------------------------------- #
# every refusal — a half-understood reserve MOVES THE DIE, so none of these
# may fall back to "no reserve" silently: each carries its reason.
# --------------------------------------------------------------------------- #
def test_no_slot_template_at_all_leaves_the_floorplan_alone(tmp_path):
    assert R._slot_floorplan_reserve(tmp_path) is None


def test_more_than_one_slot_and_no_declaration_refuses_to_choose(tmp_path):
    p = _project(tmp_path, {
        "slot_a": ((0, 0, 100, 100), (10, 10, 90, 90)),
        "slot_b": ((0, 0, 200, 200), (10, 10, 190, 190)),
    })
    r = R._slot_floorplan_reserve(p)
    assert r["applies"] is False
    assert "none declared" in r["reason"]
    assert sorted(r["slots_available"]) == ["slot_a", "slot_b"]


def test_exactly_one_ingested_slot_needs_no_separate_declaration(tmp_path):
    p = _project(tmp_path, {"slot_a": ((0, 0, 100, 100), (10, 10, 90, 90))})
    r = R._slot_floorplan_reserve(p)
    assert r["applies"] is True
    assert "the only slot ingested" in r["slot_source"]


def test_a_slot_with_no_core_area_is_refused_not_assumed(tmp_path):
    p = _project(tmp_path, {"slot_a": ((0, 0, 100, 100), None)},
                 declared="slot_a")
    r = R._slot_floorplan_reserve(p)
    assert r["applies"] is False
    assert "CORE_AREA" in r["reason"]


def test_a_core_that_touches_the_die_edge_reserves_nothing(tmp_path):
    """Zero on one side is not a reserve — it is the defect, spelled as data."""
    p = _project(tmp_path, {"slot_a": ((0, 0, 100, 100), (0, 10, 90, 90))},
                 declared="slot_a")
    r = R._slot_floorplan_reserve(p)
    assert r["applies"] is False
    assert "not strictly inside" in r["reason"]


def test_a_declared_slot_with_no_ingested_file_is_named(tmp_path):
    p = _project(tmp_path, {"slot_a": ((0, 0, 100, 100), (10, 10, 90, 90))},
                 declared="slot_zzz")
    r = R._slot_floorplan_reserve(p)
    assert r["applies"] is False
    assert "slot_zzz" in r["reason"]


# --------------------------------------------------------------------------- #
# the emitted TCL
# --------------------------------------------------------------------------- #
def test_a_project_with_no_slot_template_is_byte_identical():
    """The reserve must be invisible to every design that declares no slot."""
    assert R._pnr_floorplan_die_block(1500, 1500, 10, 1480, 1480) == (
        'initialize_floorplan -die_area "0 0 1500 1500" \\\n'
        '                      -core_area "10 10 1480 1480"')


def test_the_reserved_block_carries_the_offset_on_both_rects():
    assert R._pnr_floorplan_die_block(1052, 1647, 10, 1032, 1627, 442, 442) == (
        'initialize_floorplan -die_area "442 442 1494 2089" \\\n'
        '                      -core_area "452 452 1474 2069"')


def test_a_die_resize_may_not_re_anchor_a_reserved_floorplan():
    """The retry loop rewrites this block. Before the origin was captured, the
    rewrite regex only matched `0 0 …`, so on a reserved die a resize either
    silently did nothing or wrote the die back onto the ring."""
    tcl = ('pre\n'
           + R._pnr_floorplan_die_block(1052, 1647, 10, 1032, 1627, 442, 442)
           + ' \\\n                      -site S\npost\n')
    out = R._rewrite_pnr_floorplan_die(tcl, 900, 1400, 10, 880, 1380, 442, 442)
    assert '-die_area "442 442 1342 1842"' in out
    assert '-core_area "452 452 1322 1822"' in out
    assert '-site S' in out            # the continuation survives
    assert '"0 0' not in out


def test_the_legacy_rewrite_is_unchanged():
    tcl = ('pre\n' + R._pnr_floorplan_die_block(1500, 1500, 10, 1480, 1480)
           + ' \\\n                      -site S\npost\n')
    out = R._rewrite_pnr_floorplan_die(tcl, 2000, 2000, 10, 1980, 1980)
    assert '-die_area "0 0 2000 2000"' in out
    assert '-core_area "10 10 1980 1980"' in out
