"""v0.3.9 — #510: metal-fill density used CORE-area utilization where the
rows-already-full path needs ROW-area utilization. The runner's density
writer parsed report_design_area (CORE-util = logic area / core area) and
stored it under `row_utilization_pct`; a legitimately full design (rows
tiled with PnR fillers/decap/tap, but sparse logic → low core-util ~39%)
was mis-flagged under-filled vs its true ~99.4% row-util.

Fix:
  * the metal-fill TCL now emits an odb measurement
    `ROW_UTILIZATION_PCT <occupied CORE-master area / placement-row area>`;
  * `_v0_3_9_parse_row_utilization` parses it; the writer stores the TRUE
    row-util under `row_utilization_pct` and the report_design_area number
    separately under `core_utilization_pct` — neither axis mislabeled;
  * the fill gate (already reading `row_utilization_pct >= 95`) now sees
    the right number; FILL_NOT_LARGER stays a WARNING (a fully-tiled
    design legitimately can't grow filled.def).

Tests pin the parser, the row/core separation, and the gate's two
directions (rows-full → PASS; genuinely under-filled with room → FAIL).
Chip-AGNOSTIC.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402
import metal_fill_density_check as MFD  # noqa: E402


# ── writer-side: odb ROW_UTILIZATION_PCT parse ───────────────────────

def test_parse_row_util_value():
    assert R._v0_3_9_parse_row_utilization(
        "DESIGN AREA\nROW_UTILIZATION_PCT 99.998\n") == 99.998


def test_parse_row_util_na_is_none():
    assert R._v0_3_9_parse_row_utilization(
        "ROW_UTILIZATION_PCT NA (no rows)\n") is None


def test_parse_row_util_absent_is_none():
    assert R._v0_3_9_parse_row_utilization("no measurement here\n") is None


def test_parse_row_util_last_occurrence_wins():
    # pre-fill + post-fill both print; the post-fill (last) value wins.
    assert R._v0_3_9_parse_row_utilization(
        "ROW_UTILIZATION_PCT 12.5\nfill\nROW_UTILIZATION_PCT 99.4\n") == 99.4


# ── gate-side: rows-full PASS vs under-filled FAIL ───────────────────

def _mk(tmp_path: Path, density: dict, *, filled_eq_routed=True):
    # canonical layout: pnr under phase3/stage3/pnr, density under reports/
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text("DESIGN routed ;\n" * 100)
    fill = "DESIGN filled ;\n" * (100 if filled_eq_routed else 130)
    (pnr / "filled.def").write_text(fill)
    (pnr / "metal_fill.done").write_text("done\n")
    rp = tmp_path / "reports"
    rp.mkdir(parents=True, exist_ok=True)
    (rp / "density.json").write_text(json.dumps(density))
    return tmp_path


def test_rows_full_zero_fillers_filled_eq_routed_passes(tmp_path):
    # the exact #510 shape: rows 99.998% full, 0 new fillers,
    # filled.def == routed.def, low core-util → PASS (no ERROR).
    proj = _mk(tmp_path, {
        "tool": "openroad-filler_placement",
        "filler_instances": 0,
        "row_utilization_pct": 99.998,
        "core_utilization_pct": 39.0,
    }, filled_eq_routed=True)
    findings, _ = MFD.audit(proj)
    errs = [f for f in findings if f.severity == "ERROR"]
    assert errs == [], [f.category for f in errs]
    # the filled==routed note is at most a WARNING.
    assert all(f.severity != "ERROR" for f in findings
               if f.category == "FILL_NOT_LARGER")


def test_low_core_util_does_not_pass_a_genuinely_underfilled_design(tmp_path):
    # a design that is genuinely under-filled: low ROW-util AND 0 fillers
    # AND no growth → still FAIL (the fix must not blanket-pass on low
    # numbers; it keys on ROW-util, and this row-util is low).
    proj = _mk(tmp_path, {
        "tool": "openroad-filler_placement",
        "filler_instances": 0,
        "row_utilization_pct": 41.0,
        "core_utilization_pct": 39.0,
    }, filled_eq_routed=True)
    findings, _ = MFD.audit(proj)
    assert any(f.severity == "ERROR" and f.category == "FILL_NO_SUBSTANCE"
               for f in findings)


def test_core_util_not_consulted_for_rows_full(tmp_path):
    # even with a HIGH core-util but a LOW row-util present, the gate must
    # key on row-util (here low) → FAIL; proves core-util can't sneak a
    # pass and row-util is authoritative.
    proj = _mk(tmp_path, {
        "filler_instances": 0,
        "row_utilization_pct": 50.0,
        "core_utilization_pct": 99.0,
    }, filled_eq_routed=True)
    findings, _ = MFD.audit(proj)
    assert any(f.category == "FILL_NO_SUBSTANCE" for f in findings)


def test_placed_fillers_passes(tmp_path):
    proj = _mk(tmp_path, {
        "filler_instances": 2352,
        "row_utilization_pct": 99.4,
        "core_utilization_pct": 40.0,
    }, filled_eq_routed=False)
    findings, _ = MFD.audit(proj)
    assert all(f.severity != "ERROR" for f in findings)
