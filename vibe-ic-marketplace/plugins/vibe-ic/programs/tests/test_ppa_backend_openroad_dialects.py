#!/usr/bin/env python3
"""OpenROAD changes shape between builds, and the shapes are not compatible.

This file is the second half of the OpenROAD backend's contract: the version
dialects of the log, and the `-metrics` JSON, whose file format is not what its
extension suggests.

Every specimen here was transcribed from a real artefact. The counts quoted in
the docstrings come from a sweep of 103 `openroad.log` files spanning 12 distinct
OpenROAD builds and 4 `openroad.metrics.json` files; the sweep itself is not a
test because it reads paths outside the repository, but the shapes it found are.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa.backends import openroad as B            # noqa: E402


# ── the two detailed-placement dialects ─────────────────────────────────────
# Build 26Q3-155 and older: ONE line carrying three figures.
LOG_DIALECT_COMBINED = """\
OpenROAD 26Q3-155-g1bade74e72
[INFO IFP-0102] Core area:                        23224.320 um^2
[INFO IFP-0104] Effective utilization:                0.252
[INFO GPL-0019] Utilization:                    26.886 %
[INFO DPL-0006] Core area: 23224.32 um^2, Instances area: 5865.96 um^2, Utilization: 25.3%
[WARNING DPL-0006] Site aligned check failed (1).
[INFO DPL-0006] Core area: 23224.32 um^2, Instances area: 6660.66 um^2, Utilization: 28.7%
Design area 6661 um^2 29% utilization.
"""

# Build 26Q3-951 and newer: FOUR lines. DPL-0007/0008/0009 do not exist at all
# in the older build.
LOG_DIALECT_SPLIT = """\
OpenROAD 26Q3-951-g92b079b47a
[INFO IFP-0102] Core area:                        40751.693 um^2
[INFO IFP-0104] Effective utilization:                0.242
[INFO GPL-0019] Utilization:                    27.919 %
[INFO DPL-0006] Core area: 40751.69 um^2
[INFO DPL-0007] Movable instances area: 11465.53 um^2
[INFO DPL-0008] Fixed instances area within core: 1898.85 um^2
[INFO DPL-0009] Utilization: 32.8%
Design area 13364 um^2 33% utilization.
"""

# A shape nobody has seen. The point of the test is that it must NOT be guessed
# at: three numbers on a DPL-0006 line in an unknown order is exactly how a
# parser invents an area.
LOG_DIALECT_UNKNOWN = """\
OpenROAD 27Q1-1-gdeadbeef
[INFO DPL-0006] Utilization: 41.0%, Core: 1000.5 um^2, Instances: 410.2 um^2
"""

# The one real specimen of the global router's congestion table (sky130A, an
# open PDK, build 26Q3-1199). Column layout is fixed-width and the last row is
# an aggregate labelled `Total`.
LOG_CONGESTION = """\
OpenROAD 26Q3-1199-g193ee9ccfe
[INFO DRT-0194] Start detail routing.
[INFO GRT-0096] Final congestion report:
Layer         Resource        Demand        Usage (%)    Max H / Max V / Total Congestion
----------------------------------------------------------------------------------------
li1                  0             0            0.00%             0 /  0 /  0
met1            258243         19924            7.72%             3 /  0 / 60
met2            262244         23439            8.94%             0 /  2 / 33
----------------------------------------------------------------------------------------
Total          1146202         54580            4.76%             4 /  2 / 95

[ERROR GRT-0232] Routing congestion too high. Check the congestion heatmap in the GUI.
[INFO GRT-0012] Found 35 antenna violations.
"""


def _w(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def _dpl(o, metric):
    hits = [r for r in o.records if r["metric"] == metric
            and r["scope"]["stage"] == "detailed_placement"]
    assert len(hits) == 1, f"{metric}: {len(hits)} detailed-placement records"
    return hits[0]


# ── positive: both dialects are understood, and say which they were ─────────
def test_the_old_one_line_dialect_is_parsed(tmp_path):
    o = B.parse_log(_w(tmp_path, "openroad.log", LOG_DIALECT_COMBINED))
    assert o.dialects["detailed_placement"] == "DPL-0006-combined"
    assert _dpl(o, "area.core.um2")["value"] == 23224.32
    assert _dpl(o, "area.instances.placed.um2")["value"] == 6660.66   # last
    assert _dpl(o, "utilization.detailed_placement.pct")["value"] == 28.7


def test_the_new_four_line_dialect_is_parsed(tmp_path):
    o = B.parse_log(_w(tmp_path, "openroad.log", LOG_DIALECT_SPLIT))
    assert o.dialects["detailed_placement"] == "DPL-0006/0007/0008/0009-split"
    assert _dpl(o, "area.core.um2")["value"] == 40751.69
    assert _dpl(o, "area.instances.movable.um2")["value"] == 11465.53
    assert _dpl(o, "area.instances.fixed_in_core.um2")["value"] == 1898.85
    assert _dpl(o, "utilization.detailed_placement.pct")["value"] == 32.8


def test_the_old_dialect_does_not_fake_the_field_it_lacks(tmp_path):
    """The one-line dialect does not separate fixed from movable instance area.
    Reporting the movable figure as the fixed one, or reporting 0, would each be
    an invented number."""
    o = B.parse_log(_w(tmp_path, "openroad.log", LOG_DIALECT_COMBINED))
    for metric in ("area.instances.fixed_in_core.um2",
                   "area.instances.movable.um2"):
        rec = _dpl(o, metric)
        assert rec["status"] == "NOT_MEASURED", metric
        assert "value" not in rec
        assert "DIALECT_DOES_NOT_STATE_IT" in rec["reason"]


def test_the_dialect_that_matched_is_recorded_in_the_document(tmp_path):
    """A number's meaning depends on which dialect produced it, so the document
    has to carry that and not only the build string."""
    for text, want in ((LOG_DIALECT_COMBINED, "DPL-0006-combined"),
                       (LOG_DIALECT_SPLIT, "DPL-0006/0007/0008/0009-split")):
        doc = B.parse_log(_w(tmp_path, "l.log", text)).document()
        assert doc["dialects"]["detailed_placement"] == want
        assert doc["tool_version"]


def test_each_dialects_records_carry_its_own_build(tmp_path):
    a = B.parse_log(_w(tmp_path, "a.log", LOG_DIALECT_COMBINED))
    b = B.parse_log(_w(tmp_path, "b.log", LOG_DIALECT_SPLIT))
    assert a.tool_version == "26Q3-155-g1bade74e72"
    assert b.tool_version == "26Q3-951-g92b079b47a"
    assert {r["source"]["tool_commit"] for r in a.records} == {a.tool_version}
    assert {r["source"]["tool_commit"] for r in b.records} == {b.tool_version}


# ── negative: an unknown dialect is refused, not guessed ────────────────────
def test_an_unrecognised_dialect_is_refused_by_name(tmp_path):
    """The lane rule: refuse a shape you do not recognise rather than guess a
    field. The offending line is quoted so whoever adds the next dialect can see
    what to add."""
    o = B.parse_log(_w(tmp_path, "openroad.log", LOG_DIALECT_UNKNOWN))
    codes = [r["code"] for r in o.refusals]
    assert "DPL_DIALECT_UNRECOGNISED" in codes
    assert o.dialects["detailed_placement"] == "UNRECOGNISED"
    ref = [r for r in o.refusals if r["code"] == "DPL_DIALECT_UNRECOGNISED"][0]
    assert ref["marker"] == "[REFUSE]"
    assert "Utilization: 41.0%" in ref["detail"]
    for metric in ("area.core.um2", "area.instances.placed.um2",
                   "area.instances.movable.um2",
                   "utilization.detailed_placement.pct"):
        rec = _dpl(o, metric)
        assert rec["status"] == "INVALID"
        assert "value" not in rec, "a field was guessed out of an unknown shape"


def test_a_warning_line_is_not_a_dialect(tmp_path):
    """`[WARNING DPL-0006] Site aligned check failed (1).` sits between two real
    DPL-0006 lines in the combined-dialect specimen. It must not be mistaken for
    either a figure or a third dialect."""
    o = B.parse_log(_w(tmp_path, "openroad.log", LOG_DIALECT_COMBINED))
    assert o.refusals == []
    assert _dpl(o, "area.core.um2")["value"] == 23224.32


# ── the global router's congestion table ────────────────────────────────────
def test_the_congestion_table_is_parsed_per_layer_and_in_total(tmp_path):
    o = B.parse_log(_w(tmp_path, "openroad.log", LOG_CONGESTION))
    usage = {r["scope"]["layer"]: r["value"]
             for r in o.by_metric("route.congestion.usage.pct")}
    assert usage == {"li1": 0.0, "met1": 7.72, "met2": 8.94, "Total": 4.76}
    demand = {r["scope"]["layer"]: r["value"]
              for r in o.by_metric("route.congestion.demand.count")}
    assert demand["met1"] == 19924
    assert demand["Total"] == 54580
    total = [r for r in o.by_metric("route.congestion.usage.pct")
             if r["scope"]["layer"] == "Total"][0]
    assert total["scope"]["aggregate"] is True, \
        "the aggregate row must not be comparable with a per-layer row"
    per_layer = [r for r in o.by_metric("route.congestion.usage.pct")
                 if r["scope"]["layer"] == "met1"][0]
    assert per_layer["scope"]["aggregate"] is False


def test_congestion_overflow_columns_keep_their_own_names(tmp_path):
    """`Max H / Max V / Total Congestion` are three different quantities. One
    `overflow` metric would have to pick one and lose the others."""
    o = B.parse_log(_w(tmp_path, "openroad.log", LOG_CONGESTION))
    def at(metric, layer):
        return [r["value"] for r in o.by_metric(metric)
                if r["scope"]["layer"] == layer][0]
    assert at("route.congestion.max_h.count", "met1") == 3
    assert at("route.congestion.max_v.count", "met2") == 2
    assert at("route.congestion.total_congestion.count", "met1") == 60
    assert at("route.congestion.total_congestion.count", "Total") == 95


def test_a_log_without_a_congestion_table_says_the_stage_never_ran(tmp_path):
    """Most builds on this host print no GRT table at all. Absent must be a
    reason, never a zero-congestion report."""
    o = B.parse_log(_w(tmp_path, "openroad.log", LOG_DIALECT_SPLIT))
    for metric in ("route.congestion.usage.pct",
                   "route.congestion.total_congestion.count"):
        recs = o.by_metric(metric)
        assert recs and all(r["status"] == "NOT_MEASURED" for r in recs)
        assert all("value" not in r for r in recs)
        assert all("STAGE_NOT_RUN" in r["reason"] for r in recs)


# ── the -metrics JSON, which is not a JSON object ───────────────────────────
# Transcribed from a real `openroad.metrics.json`: OpenROAD appends a block at
# each internal checkpoint, so keys repeat. The file below is exactly the shape
# of the real one, shortened.
METRICS_JSON_REAL_SHAPE = """{
\t"detailedroute__antenna__violating__nets": 5,
\t"detailedroute__antenna__violating__pins": 6,
\t"detailedroute__route__drc_errors": 395,
\t"detailedroute__route__wirelength": 40194,
\t"detailedroute__route__vias": 4055,
\t"utilization__before__dpl": 4.94959,
\t"detailedroute__antenna__violating__nets": 0,
\t"detailedroute__antenna__violating__pins": 0,
\t"detailedroute__route__drc_errors": 0,
\t"detailedroute__route__wirelength": 39925,
\t"detailedroute__route__vias": 4079,
\t"utilization__before__dpl": 1.67797,
\t"global_route__wirelength": 54633,
\t"global_route__vias": 3460,
\t"flow__errors__count": 0,
\t"flow__warnings__count": 21,
\t"global_route__fastroute__run_s": 0,
\t"a__key__nobody__mapped": 17
}"""

# Another tool's metrics document. It also uses `__`-separated keys, which is
# why the signature check exists at all.
METRICS_JSON_FOREIGN = """{
  "klayout__drc_error__count": 361,
  "klayout__zero_area_polygons__count": 0,
  "magic__drc_error__count": 1698
}"""


def test_the_metrics_json_is_an_append_log_and_the_last_value_wins(tmp_path):
    """Measured on four real runs: 247 key/value pairs for 89 distinct keys.
    `json.load` keeps the last by CPython dict semantics -- an accident, not a
    contract. A reader that kept the first would report 5 antenna net violations
    on a design that ends with 0."""
    o = B.parse_metrics_json(_w(tmp_path, "m.json", METRICS_JSON_REAL_SHAPE))
    assert o.refusals == []
    assert o.one("antenna.net.violation.count")["value"] == 0        # first: 5
    assert o.one("antenna.pin.violation.count")["value"] == 0        # first: 6
    assert o.one("route.drc.violation.count")["value"] == 0          # first: 395
    assert o.one("utilization.before_detailed_placement.pct")["value"] == 1.67797


def test_the_repeat_count_is_written_into_the_record(tmp_path):
    """Otherwise the duplicate keys are invisible to everyone downstream and the
    document claims a figure was stated once."""
    o = B.parse_metrics_json(_w(tmp_path, "m.json", METRICS_JSON_REAL_SHAPE))
    assert o.one("antenna.net.violation.count")["source"]["occurrences"] == 2
    assert o.one("flow.warning.count")["source"]["occurrences"] == 1
    diag = [d for d in o.diagnostics if d["code"] == "METRICS_JSON_SHAPE"][0]
    assert diag["distinct_keys"] < diag["pairs"]
    assert diag["duplicated_keys"] == diag["pairs"] - diag["distinct_keys"]


def test_the_same_metric_from_two_stages_stays_two_records(tmp_path):
    """`global_route__wirelength` and `detailedroute__route__wirelength` are the
    same metric at different stages. §2: two numbers are comparable only if
    their scope matches."""
    o = B.parse_metrics_json(_w(tmp_path, "m.json", METRICS_JSON_REAL_SHAPE))
    wl = {r["scope"]["stage"]: r["value"] for r in o.by_metric("route.wirelength.um")}
    assert wl == {"detailed_route": 39925, "global_route": 54633}


def test_an_unmapped_key_is_counted_not_guessed(tmp_path):
    """A key whose unit could not be established from evidence is reported, not
    turned into a metric. `global_route__fastroute__run_s` is seconds and is not
    a PPA figure; `a__key__nobody__mapped` is unknown."""
    o = B.parse_metrics_json(_w(tmp_path, "m.json", METRICS_JSON_REAL_SHAPE))
    diag = [d for d in o.diagnostics
            if d["code"] == "METRICS_JSON_UNMAPPED_KEYS"][0]
    assert "a__key__nobody__mapped" in diag["keys"]
    assert "global_route__fastroute__run_s" in diag["keys"]
    assert diag["count"] == len(diag["keys"]) >= 2
    assert not any(r["value"] == 17 for r in o.records
                   if r["status"] == "MEASURED")


def test_a_key_this_document_lacks_is_a_reason_not_a_zero(tmp_path):
    o = B.parse_metrics_json(_w(tmp_path, "m.json", METRICS_JSON_REAL_SHAPE))
    rec = o.one("antenna.diode.count")
    assert rec["status"] == "NOT_MEASURED"
    assert rec["reason"].startswith("KEY_ABSENT")
    assert "value" not in rec


def test_another_tools_metrics_file_is_refused(tmp_path):
    """`klayout__`/`magic__` keys prove the document belongs to a different
    tool. Parsing it as OpenROAD's would attribute a number to the wrong engine,
    which is worse than not having it."""
    o = B.parse_metrics_json(_w(tmp_path, "m.json", METRICS_JSON_FOREIGN))
    assert o.records == []
    assert o.refusals[0]["code"] == "METRICS_JSON_FOREIGN_TOOL"
    assert o.refusals[0]["marker"] == "[REFUSE]"


def test_a_metrics_file_with_no_openroad_signature_is_refused(tmp_path):
    o = B.parse_metrics_json(_w(tmp_path, "m.json", '{"total": 1, "ok": true}'))
    assert o.records == []
    assert o.refusals[0]["code"] == "METRICS_JSON_UNRECOGNISED_SHAPE"


def test_an_unparseable_metrics_file_is_not_an_empty_one(tmp_path):
    broken = B.parse_metrics_json(_w(tmp_path, "b.json", "{not json"))
    empty = B.parse_metrics_json(_w(tmp_path, "e.json", ""))
    absent = B.parse_metrics_json(tmp_path / "nope.json")
    assert broken.refusals[0]["code"] == "METRICS_JSON_UNPARSEABLE"
    assert empty.refusals[0]["code"] == "ARTEFACT_EMPTY"
    assert absent.refusals[0]["code"] == "ARTEFACT_ABSENT"
    assert broken.records == empty.records == absent.records == []


def test_a_non_numeric_metric_value_is_INVALID_not_dropped(tmp_path):
    text = json.dumps({"detailedroute__route__drc_errors": "many",
                       "flow__warnings__count": 3})
    o = B.parse_metrics_json(_w(tmp_path, "m.json", text))
    rec = o.one("route.drc.violation.count")
    assert rec["status"] == "INVALID"
    assert "NON_NUMERIC" in rec["reason"]
    assert o.one("flow.warning.count")["value"] == 3


def test_a_boolean_is_not_a_count(tmp_path):
    """`True` is an `int` in Python and would silently become the number 1."""
    text = json.dumps({"detailedroute__route__drc_errors": True,
                       "flow__warnings__count": 0})
    o = B.parse_metrics_json(_w(tmp_path, "m.json", text))
    assert o.one("route.drc.violation.count")["status"] == "INVALID"


# ── the two sources together ────────────────────────────────────────────────
def test_a_run_directory_reads_both_sources_and_reconciles_neither(tmp_path):
    """Measured on four independent runs of one build, the log and the metrics
    JSON DISAGREE about wirelength and via count -- reproducibly, in the same
    direction. A backend that picked a winner would delete the evidence that
    there was ever a question, so both records are emitted and
    `_ppa/contract.py` rules on the conflict."""
    (tmp_path / "openroad.log").write_text(
        "OpenROAD 26Q3-1535-g543c33894f\n"
        "[INFO DRT-0194] Start detail routing.\n"
        "[INFO DRT-0199]   Number of violations = 0.\n"
        "Total wire length = 39887 um.\n"
        "Total number of vias = 4046.\n")
    (tmp_path / "openroad.metrics.json").write_text(METRICS_JSON_REAL_SHAPE)
    o = B.parse_run(tmp_path)

    same_scope = [r for r in o.by_metric("route.wirelength.um")
                  if r["scope"]["stage"] == "detailed_route"]
    assert sorted(r["value"] for r in same_scope) == [39887.0, 39925]
    assert len({r["source"]["path"] for r in same_scope}) == 2, \
        "the two numbers must be attributable to different artefacts"
    # ... and the JSON's records get the build the LOG identified, because the
    # metrics file does not carry one.
    assert o.tool_version == "26Q3-1535-g543c33894f"
    for r in o.records:
        assert r["source"]["tool_commit"] == "26Q3-1535-g543c33894f"


def test_a_run_directory_without_a_metrics_json_still_works(tmp_path):
    """Most builds write no metrics file. That is a diagnostic, not a refusal."""
    (tmp_path / "openroad.log").write_text(
        "OpenROAD 26Q3-984-g09d67f08f8\n"
        "[INFO IFP-0102] Core area:                        12294.374 um^2\n")
    o = B.parse_run(tmp_path)
    assert o.refusals == []
    assert o.ok
    assert any(d["code"] == "METRICS_JSON_NOT_PRESENT" for d in o.diagnostics)


def test_a_run_directory_that_is_not_one_is_refused(tmp_path):
    o = B.parse_run(tmp_path / "nope")
    assert o.records == []
    assert o.refusals[0]["code"] == "RUN_DIR_ABSENT"


def test_the_two_dialects_instance_area_fields_are_NOT_the_same_quantity(tmp_path):
    """The trap this backend was one edit away from shipping.

    The old dialect's `Instances area` is movable PLUS fixed; the new dialect's
    `Movable instances area` is movable ALONE. Mapping them onto one metric puts
    11465.53 where 13364.38 belongs. Each log settles it against its own printed
    utilisation, so the check needs no truth from outside the artefact:

        combined:  6660.66 / 23224.32              = 28.68 %, log prints 28.7 %
        split:    11465.53 / 40751.69              = 28.14 %, log prints 32.8 %
                 (11465.53 + 1898.85) / 40751.69   = 32.79 %, log prints 32.8 %
    """
    def ratio(o):
        placed = _dpl(o, "area.instances.placed.um2")["value"]
        core = _dpl(o, "area.core.um2")["value"]
        util = _dpl(o, "utilization.detailed_placement.pct")["value"]
        return 100.0 * placed / core, util

    got, printed = ratio(B.parse_log(_w(tmp_path, "a.log", LOG_DIALECT_COMBINED)))
    assert got == pytest.approx(printed, abs=0.05)

    split = B.parse_log(_w(tmp_path, "b.log", LOG_DIALECT_SPLIT))
    got, printed = ratio(split)
    assert got == pytest.approx(printed, abs=0.05)
    # ... and the split dialect's total is DERIVED, so a reader can recompute it.
    total = _dpl(split, "area.instances.placed.um2")
    assert total["status"] == "DERIVED"
    assert total["value"] == pytest.approx(11465.53 + 1898.85)
    assert "DPL-0007" in total["formula"] and "DPL-0008" in total["formula"]
    # The movable figure ALONE would not reproduce the printed utilisation, so
    # this test is not vacuous: the two fields really are distinguishable here.
    movable_only = 100.0 * _dpl(split, "area.instances.movable.um2")["value"] / \
        _dpl(split, "area.core.um2")["value"]
    assert abs(movable_only - printed) > 4.0
