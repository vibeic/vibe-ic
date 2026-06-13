"""v0.2.69 utilization zero-quantization honesty regressions.

Root-cause chain exposed by the real-corpus sweep: OpenROAD's
`report_design_area` prints INTEGER-rounded utilization, so a design
whose true core utilization is below 0.5% prints "0% utilization"; the
metal-fill density emitter recorded that quantized 0 as a fabricated-
precision "0.0%" (mislabelled "std-cell row utilization"), and
utilization_band_check then classified the report as corrupt
(UTIL_NONPOSITIVE FAIL) — a false fire on a legitimately finished
design (routed DEF + GDS present).

Defenses pinned here:
  * emitter: a parsed 0 from report_design_area is recorded as
    `row_utilization_pct: null` + `utilization_below_report_precision:
    true` (never a fabricated "0.0"), and the label says core-area
    utilization (what report_design_area actually reports);
  * check: literal 0 → WARN UTIL_ZERO_UNRESOLVED (precision floor),
    rc=0; corruption FAIL is reserved for negative / >100 values.

chip-AGNOSTIC: tool-output-shape rules, no chip-class literals.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import utilization_band_check as u  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_P3_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()


# ── check: 0 is a precision floor, not corruption ──────────────────────────

def test_classify_zero_warns_unresolved():
    verdict, findings = u.classify(0.0, "reports/density.rpt")
    assert verdict == "WARN"
    assert any(f.category == "UTIL_ZERO_UNRESOLVED" for f in findings)
    assert all(f.severity != "ERROR" for f in findings)


def test_classify_negative_still_fails():
    verdict, findings = u.classify(-0.01, "x")
    assert verdict == "FAIL"
    assert any(f.category == "UTIL_NONPOSITIVE" for f in findings)


def test_observed_corpus_shape_no_longer_false_fails(tmp_path):
    # the exact density.rpt shape the audited project carried
    p = tmp_path / "reports" / "density.rpt"
    p.parent.mkdir(parents=True)
    p.write_text(
        "# Metal-fill / density report — OpenROAD filler_placement\n"
        "# (ORGANIC-20260531 Step 34). Tool: openroad.\n"
        "# filler instances placed: 0\n"
        "# std-cell row utilization (post-fill): 0.0%\n")
    verdict, _ = u.classify(*u.read_utilization(tmp_path))
    assert verdict != "FAIL"


def test_strict_zero_still_rc0(tmp_path):
    # --strict gates NO_DATA, not the quantized-0 WARN
    p = tmp_path / "reports" / "density.rpt"
    p.parent.mkdir(parents=True)
    p.write_text("# utilization: 0.0%\n")
    assert u.main([str(tmp_path), "--strict"]) == 0


# ── emitter: source pins ───────────────────────────────────────────────────

def test_emitter_nulls_quantized_zero():
    # #510 renamed the report_design_area variable util_pct → core_util_pct
    # (it is CORE-area utilization, not row fill); the quantized-zero
    # nulling logic is unchanged, only the name.
    i = _P3_SRC.index("util_below_precision = (core_util_pct == 0)")
    window = _P3_SRC[i - 800:i + 800]
    assert "core_util_pct = None" in window
    assert "below report precision" in window


def test_emitter_label_is_core_area_not_row_fill():
    assert '"utilization_below_report_precision": util_below_precision' \
        in _P3_SRC
    assert "core-area utilization (report_design_area" in _P3_SRC
    # the old fabricated-precision label is gone from the emitter
    assert '# std-cell row utilization (post-fill): "' not in _P3_SRC
