#!/usr/bin/env python3
"""The OpenROAD backend must never turn a silence into a number.

Every test below is a property some other plausible implementation would break,
and most of them were written from a specimen that exists on a real run tree.
The four fixtures the PPA contract requires (`docs/PPA_INTERFACES.md` §7) are
laid out in that order: positive, negative, vacuous, mutation.

The fixtures are synthetic on purpose. A test that reads a run tree outside the
repository passes on the author's machine and is skipped everywhere else, and a
skipped test and a passing test print the same colour.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import canonical_json as cj              # noqa: E402
from _ppa.backends import openroad as B            # noqa: E402

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── specimens ───────────────────────────────────────────────────────────────
# Transcribed from real logs on a completed Phase-3 run. Figures are reprinted
# exactly as OpenROAD reprints them -- the reprint IS the thing under test.
LOG_MODERN = """\
OpenROAD 26Q3-984-g09d67f08f8
Features included (+) or not (-): -GPU +GUI -Python
[INFO IFP-0100] Die BBox:  (  0.000  0.000 ) ( 142.000 142.000 ) um
[INFO IFP-0101] Core BBox: ( 10.560 10.080 ) ( 121.440 120.960 ) um
[INFO IFP-0102] Core area:                        12294.374 um^2
[INFO IFP-0103] Total instances area:              4703.530 um^2
[INFO IFP-0104] Effective utilization:                0.383
[INFO IFP-0105] Number of instances:                    252
[INFO GPL-0019] Utilization:                    44.379 %
[INFO GPL-0021] Large instances area:            0.000 um^2
[INFO GPL-0041] Total routing overflow: 0.0000
[INFO GPL-0042] Number of overflowed tiles: 0 (0.00%)
[INFO DPL-0006] Core area: 12294.37 um^2
[INFO DPL-0007] Movable instances area: 5611.64 um^2
[INFO DPL-0008] Fixed instances area within core: 0.00 um^2
[INFO DPL-0009] Utilization: 45.6%
[INFO RSZ-0034] Found 7 slew violations.
[INFO DPL-0006] Core area: 12294.37 um^2
[INFO DPL-0007] Movable instances area: 7135.13 um^2
[INFO DPL-0008] Fixed instances area within core: 146.36 um^2
[INFO DPL-0009] Utilization: 59.2%
[INFO DRT-0194] Start detail routing.
[INFO DRT-0195] Start 0th optimization iteration.
[INFO DRT-0199]   Number of violations = 292.
Total wire length = 13033 um.
Total wire length on LAYER MET1 = 357 um.
Total wire length on LAYER MET2 = 7065 um.
Total number of vias = 2446.
[INFO DRT-0195] Start 1st optimization iteration.
[INFO DRT-0199]   Number of violations = 0.
[INFO DRT-0198] Complete detail routing.
Total wire length = 12704 um.
Total wire length on LAYER MET1 = 314 um.
Total wire length on LAYER MET2 = 6148 um.
Total number of vias = 2502.
[INFO ANT-0002] Found 0 net violations.
[INFO ANT-0001] Found 0 pin violations.
[INFO DPL-0001] Placed 288 filler instances.
Design area 12294 um^2 100% utilization.
"""

# The aborted run: a REAL shape (build 26Q3-1472, ~600 bytes, three of them on
# this host). Banner and ODB codes present; not one routing or placement figure.
LOG_ABORTED = """\
OpenROAD 26Q3-1472-g42cadea9df
Features included (+) or not (-): -GPU +GUI -Python
[INFO ODB-0227] LEF file: tiny.lef, created 1 layers, 1 library cells
[INFO ODB-0127] Reading DEF file: legal.def
[INFO ODB-0128] Design: top
[INFO ODB-0134] Finished DEF file: legal.def
CHECK_PLACEMENT_CLEAN SPARE 0
"""


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


# ── positive: green when it should be green ─────────────────────────────────
def test_positive_a_complete_log_yields_the_figures_it_states(tmp_path):
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    assert o.refusals == []
    assert o.ok
    assert o.tool_version == "26Q3-984-g09d67f08f8"

    def val(metric, **scope):
        hits = [r for r in o.records if r["metric"] == metric
                and all(r["scope"].get(k) == v for k, v in scope.items())]
        assert len(hits) == 1, f"{metric} {scope}: {len(hits)} records"
        assert hits[0]["status"] in ("MEASURED", "DERIVED"), hits[0]
        return hits[0]["value"]

    assert val("area.core.um2", stage="floorplan") == 12294.374
    assert val("area.instances.total.um2", stage="floorplan") == 4703.530
    assert val("design.instance.count", stage="floorplan") == 252
    assert val("area.instances.movable.um2", stage="detailed_placement") == 7135.13
    assert val("area.instances.placed.um2",
               stage="detailed_placement") == pytest.approx(7135.13 + 146.36)
    assert val("area.instances.fixed_in_core.um2",
               stage="detailed_placement") == 146.36
    assert val("route.via.count", stage="detailed_route") == 2502
    assert val("antenna.net.violation.count", stage="post_route") == 0
    assert val("drv.max_slew.violation.count.pre_repair", stage="post_place") == 7


def test_positive_the_last_figure_is_the_one_that_ships(tmp_path):
    """`re.search` returns the FIRST match and every iterative OpenROAD figure is
    reprinted. On the real run this specimen came from, first vs last wirelength
    was 13033 vs 12704 -- 2.6 % apart with no fixed sign -- and detailed
    placement printed six utilisations from 45.6 % up to 59.2 %."""
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    wl = [r for r in o.records if r["metric"] == "route.wirelength.um"]
    assert [r["value"] for r in wl] == [12704.0], "took the first, not the last"
    util = [r for r in o.records
            if r["metric"] == "utilization.detailed_placement.pct"]
    assert [r["value"] for r in util] == [59.2]
    drc = [r for r in o.records if r["metric"] == "route.drc.violation.count"]
    assert [r["value"] for r in drc] == [0], "292 is the state before repair"


def test_positive_the_record_says_the_figure_was_reprinted(tmp_path):
    """Taking the last silently would leave a reader unable to tell a figure
    stated once from one that moved five times. `source.occurrences` puts it in
    the document."""
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    wl = o.by_metric("route.wirelength.um")[0]
    assert wl["source"]["occurrences"] == 2
    assert wl["source"]["selection"] == "last"


def test_positive_per_layer_wirelength_comes_from_the_LAST_block(tmp_path):
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    by_layer = {r["scope"]["layer"]: r["value"]
                for r in o.by_metric("route.wirelength.by_layer.um")}
    assert by_layer == {"MET1": 314.0, "MET2": 6148.0}, \
        "these are the first block's 357/7065, not the shipped geometry's"


def test_positive_die_area_is_DERIVED_and_states_its_formula(tmp_path):
    """OpenROAD prints a die BBOX, not a die area. A computed number is DERIVED
    and must carry the formula, or nobody downstream can recompute it."""
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    die = o.one("area.die.um2")
    assert die["status"] == "DERIVED"
    assert die["value"] == pytest.approx(142.0 * 142.0)
    assert "IFP-0100" in die["formula"]
    assert die["scope"]["bbox_um"] == [0.0, 0.0, 142.0, 142.0]


def test_positive_every_record_can_be_traced_to_a_build_and_a_parser(tmp_path):
    """A number whose build is unknown cannot be compared with a number from
    another build, and OpenROAD's shape changes between builds."""
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    for r in o.records:
        s = r["source"]
        assert s["tool"] == "openroad"
        assert s["tool_commit"] == "26Q3-984-g09d67f08f8"
        assert s["sha256"].startswith("sha256:")
        assert s["parser"] == B.PARSER
        assert s["parser_sha256"].startswith("sha256:")


def test_positive_records_survive_the_canonical_serializer(tmp_path):
    """§3: `canonical_json` is the only serializer, and it refuses NaN and
    Infinity. A record that cannot be serialized cannot be hashed, and an
    unhashable record cannot be evidence."""
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    text = cj.dumps(o.document())
    assert json.loads(text)["records"]
    assert cj.digest_of(o.document()).startswith("sha256:")


# ── the units question the lane brief names explicitly ──────────────────────
def test_a_ratio_and_a_percent_are_not_the_same_metric(tmp_path):
    """One log states four utilisations in two units: IFP-0104 is a ratio in
    [0,1], GPL-0019 and DPL-0009 are percents, and the `Design area` line is an
    integer-rounded percent measured AFTER filler insertion. Collapsing them
    into one `utilization` would make 0.383 and 100 the same quantity."""
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    eff = o.one("utilization.floorplan.effective")
    assert (eff["unit"], eff["value"]) == ("1", 0.383)
    gpl = o.one("utilization.global_placement.pct")
    assert (gpl["unit"], gpl["value"]) == ("%", 44.379)
    dpl = o.one("utilization.detailed_placement.pct")
    assert (dpl["unit"], dpl["value"]) == ("%", 59.2)
    rpt = o.one("utilization.design_report.pct")
    assert (rpt["unit"], rpt["value"]) == ("%", 100.0)
    # ... and the 100 is kept away from the others by SCOPE, not by a comment.
    assert rpt["scope"]["fill"] == "post_fill"
    assert rpt["scope"]["rounding"] == "integer"
    assert rpt["scope"] != dpl["scope"]


def test_area_is_a_quantity_and_utilization_is_a_ratio_of_it(tmp_path):
    """`Design area 12294 um^2 100% utilization` states BOTH, and the quantity
    is the core area while the ratio is post-filler. Reading the 100 as the
    design's utilisation would report a full chip; reading the 12294 as the cell
    area would report the core."""
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    assert o.one("area.design_report.um2")["unit"] == "um^2"
    assert o.one("utilization.design_report.pct")["unit"] == "%"
    assert o.one("area.design_report.um2")["value"] == 12294.0
    placed = [r for r in o.records if r["metric"] == "area.instances.placed.um2"
              and r["scope"]["stage"] == "detailed_placement"][0]
    assert placed["value"] == pytest.approx(7281.49)


# ── negative: RED when it should be red ─────────────────────────────────────
def test_negative_an_empty_report_is_not_zero_violations(tmp_path):
    """The single most expensive confusion this backend exists to prevent. An
    empty file must produce NO records at all -- not a document of zeros that
    reads exactly like a clean run."""
    o = B.parse_log(_write(tmp_path, "openroad.log", ""))
    assert o.records == []
    assert [r["code"] for r in o.refusals] == ["ARTEFACT_EMPTY"]
    assert not o.ok


def test_negative_a_missing_file_and_an_empty_one_are_different_verdicts(tmp_path):
    absent = B.parse_log(tmp_path / "nope.log")
    empty = B.parse_log(_write(tmp_path, "empty.log", "   \n"))
    assert absent.refusals[0]["code"] == "ARTEFACT_ABSENT"
    assert empty.refusals[0]["code"] == "ARTEFACT_EMPTY"
    assert absent.refusals[0]["code"] != empty.refusals[0]["code"]


def test_negative_a_stage_that_never_ran_is_NOT_MEASURED_never_zero(tmp_path):
    """A real shape: OpenROAD started, read the DEF, and stopped. Every routing
    and placement figure is absent because the step never happened -- which is
    NOT_MEASURED with a reason, and is emitted as a row rather than omitted (§2:
    a report prints the literal NOT_MEASURED row)."""
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_ABORTED))
    assert not o.ok
    assert o.records, "the rows must exist; omitting them hides the gap"
    for r in o.records:
        assert r["status"] in ("NOT_MEASURED", "INVALID"), r
        assert "value" not in r, f"{r['metric']} got a value out of a silence"
    drc = o.one("route.drc.violation.count")
    assert drc["status"] == "NOT_MEASURED"
    assert drc["reason"].startswith("STAGE_NOT_RUN")
    assert "DRT-0194" in drc["reason"]


def test_negative_no_metric_ever_carries_a_sentinel(tmp_path):
    """§2: 0, -1 and "" never mean 'not measured'. Enforced at construction so
    it cannot be reintroduced one metric at a time."""
    for text in (LOG_MODERN, LOG_ABORTED):
        o = B.parse_log(_write(tmp_path, "l.log", text))
        for r in o.records:
            if r["status"] in ("NOT_MEASURED", "NOT_APPLICABLE", "INVALID"):
                assert "value" not in r
                assert r["reason"]
            else:
                assert "reason" not in r
                assert r["value"] is not None


def test_negative_a_resizer_silence_is_not_zero_DRV(tmp_path):
    """OpenROAD prints `Found N <kind> violations` only when N > 0 -- measured:
    703 such lines across 103 real logs, not one with N=0, while the control
    `[INFO ANT-0002] Found 0 net violations` occurs 159 times. So the line's
    absence cannot be told from a genuine zero BY THIS ARTEFACT, and reporting 0
    would be inferring a number from a silence."""
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    cap = o.one("drv.max_capacitance.violation.count.pre_repair")
    assert cap["status"] == "INVALID"
    assert cap["reason"].startswith("ABSENCE_IS_NOT_ZERO")
    assert "value" not in cap
    # The one that WAS printed is measured, so the rule is not blanket refusal.
    assert o.one("drv.max_slew.violation.count.pre_repair")["value"] == 7


def test_negative_a_post_repair_DRV_residual_is_refused_not_invented(tmp_path):
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    res = o.one("drv.residual.violation.count")
    assert res["status"] == "NOT_MEASURED"
    assert "NO_SUCH_FIGURE" in res["reason"]
    assert "opensta" in res["reason"]


def test_negative_a_macro_area_is_refused_not_substituted(tmp_path):
    """`[INFO GPL-0021] Large instances area` answers a different question, so it
    is emitted under its own name and the macro area says why it is absent."""
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    macro = o.one("area.macro.um2")
    assert macro["status"] == "NOT_MEASURED"
    assert "GPL-0021" in macro["reason"]
    assert o.one("area.instances.large.um2")["value"] == 0.0


def test_negative_a_WARNING_DPL_0006_is_not_a_core_area(tmp_path):
    """A real line on this host: `[WARNING DPL-0006] Site aligned check failed
    (1).` A regex keyed on the message number alone would read the `(1)` as a
    figure."""
    text = LOG_ABORTED + "[WARNING DPL-0006] Site aligned check failed (1).\n"
    o = B.parse_log(_write(tmp_path, "openroad.log", text))
    for r in o.records:
        if r["metric"] == "area.core.um2":
            assert r["status"] != "MEASURED", r


def test_negative_a_log_from_something_else_is_refused(tmp_path):
    o = B.parse_log(_write(tmp_path, "x.log", "hello\nthis is not a tool log\n"))
    assert o.records == []
    assert o.refusals[0]["code"] == "NOT_AN_OPENROAD_LOG"


def test_negative_a_record_that_breaks_the_contract_cannot_be_built():
    """The guard rails themselves. Each of these is a shape somebody writes when
    they are in a hurry, and each would put a number where a reason belongs."""
    sc, src = {"stage": "x"}, {"path": "p"}
    with pytest.raises(B.RecordError):
        B._record("m", "NOT_MEASURED", "1", sc, src, value=0, reason="r")
    with pytest.raises(B.RecordError):
        B._record("m", "NOT_MEASURED", "1", sc, src)                 # no reason
    with pytest.raises(B.RecordError):
        B._record("m", "MEASURED", "1", sc, src)                     # no value
    with pytest.raises(B.RecordError):
        B._record("m", "MEASURED", "1", sc, src, value=float("nan"))
    with pytest.raises(B.RecordError):
        B._record("m", "DERIVED", "1", sc, src, value=1.0)           # no formula
    with pytest.raises(B.RecordError):
        B._record("m", "PROBABLY_FINE", "1", sc, src, value=1.0)


def test_negative_one_refuses_to_pick_a_winner_from_a_conflict(tmp_path):
    """`area.core.um2` legitimately appears twice -- floorplan and detailed
    placement state it separately. A helper that returned the first would turn a
    two-source disagreement into a fact."""
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    assert len(o.by_metric("area.core.um2")) == 2
    with pytest.raises(KeyError):
        o.one("area.core.um2")


# ── vacuous: missing input gives rc=2 with a marker ─────────────────────────
def _cli(*args, cwd):
    return _pr.run(
        [sys.executable, "-m", "_ppa.backends.openroad", *args],
        capture_output=True, text=True, cwd=str(cwd))


@pytest.fixture(scope="module")
def programs_dir():
    return pathlib.Path(__file__).resolve().parents[1]


def test_vacuous_absent_input_exits_2_with_a_marker(programs_dir, tmp_path):
    """rc=2, not 0 and not 1. A gate whose declared invocation exits 0 on absent
    input can never fail; one that exits 1 reports a finding about silicon it
    never looked at."""
    r = _cli("--log", str(tmp_path / "nope.log"), cwd=programs_dir)
    assert r.returncode == 2, r.stderr
    assert "[CANNOT CHECK]" in r.stderr
    assert "ARTEFACT_ABSENT" in r.stderr


def test_vacuous_empty_input_exits_2_with_a_marker(programs_dir, tmp_path):
    p = _write(tmp_path, "openroad.log", "")
    r = _cli("--log", str(p), cwd=programs_dir)
    assert r.returncode == 2, r.stderr
    assert "[CANNOT CHECK]" in r.stderr
    assert "ARTEFACT_EMPTY" in r.stderr


def test_vacuous_a_readable_log_that_establishes_nothing_exits_2(programs_dir,
                                                                tmp_path):
    """'I read it and there was nothing to measure' is also a 2, and it says so
    on stderr. Returning 0 here is how a run that measured nothing gets counted
    as a clean measurement."""
    p = _write(tmp_path, "openroad.log", LOG_ABORTED)
    r = _cli("--log", str(p), cwd=programs_dir)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[CANNOT CHECK]" in r.stderr


def test_vacuous_a_bad_invocation_is_3_not_a_design_finding(programs_dir,
                                                            tmp_path):
    for args in ((), ("--log", "a", "--run-dir", "b")):
        r = _cli(*args, cwd=programs_dir)
        assert r.returncode == 3, (args, r.returncode, r.stderr)


def test_vacuous_a_good_log_exits_0(programs_dir, tmp_path):
    """The positive control for every rc test above: the instrument CAN return
    0, so a 2 means something."""
    p = _write(tmp_path, "openroad.log", LOG_MODERN)
    out = tmp_path / "rec.json"
    r = _cli("--log", str(p), "--json", str(out), cwd=programs_dir)
    assert r.returncode == 0, r.stderr
    doc = json.loads(out.read_text())
    assert doc["tool"] == "openroad"
    assert any(x["status"] == "MEASURED" for x in doc["records"])


def test_the_backend_never_exits_1(programs_dir, tmp_path):
    """rc=1 is a claim about silicon and a parser has none to make. Swept over
    every pathological input this module can be handed."""
    cases = {
        "absent.log": None,
        "empty.log": "",
        "junk.log": "not a log at all\n",
        "aborted.log": LOG_ABORTED,
        "good.log": LOG_MODERN,
        "binary.log": "\x00\x01\x02 not text\n",
    }
    for name, text in cases.items():
        p = tmp_path / name
        if text is not None:
            p.write_text(text)
        r = _cli("--log", str(p), cwd=programs_dir)
        assert r.returncode != 1, f"{name} exited 1: {r.stderr}"
        assert r.returncode in (0, 2, 3), (name, r.returncode)


# ── mutation: revert the change and a NAMED test goes red ───────────────────
# The three properties below are the ones whose loss would be silent. Each is
# named here so a future author reverting the corresponding line knows which
# test is supposed to catch them.
#
#   _last() -> re.search()                  breaks test_mutation_first_match_
#                                           would_report_a_different_design
#   the status machinery -> value 0         breaks test_mutation_a_default_zero_
#                                           is_indistinguishable_from_clean
#   the shared router reader -> a local one breaks test_mutation_the_router_
#                                           count_has_one_implementation
def test_mutation_first_match_would_report_a_different_design(tmp_path):
    """Pin the exact numbers a first-match parser would produce, so the
    difference is a failing assertion and not a 2 % drift nobody notices."""
    o = B.parse_log(_write(tmp_path, "openroad.log", LOG_MODERN))
    assert o.one("route.wirelength.um")["value"] == 12704.0     # first: 13033.0
    assert o.one("route.via.count")["value"] == 2502            # first: 2446
    assert o.one("route.drc.violation.count")["value"] == 0     # first: 292
    assert o.one("utilization.detailed_placement.pct")["value"] == 59.2  # 45.6
    assert o.one("area.instances.movable.um2")["value"] == 7135.13  # first: 5611.64


def test_mutation_a_default_zero_is_indistinguishable_from_clean(tmp_path):
    """The aborted log and a genuinely clean run must not produce the same
    document. If any absent figure ever defaults to 0, this goes red."""
    aborted = B.parse_log(_write(tmp_path, "a.log", LOG_ABORTED))
    clean = B.parse_log(_write(tmp_path, "b.log", LOG_MODERN))
    assert cj.sha256(aborted.document()) != cj.sha256(clean.document())
    assert not any(r.get("value") == 0 for r in aborted.records)
    assert sum(1 for r in aborted.records
               if r["status"] in ("MEASURED", "DERIVED")) == 0
    assert sum(1 for r in clean.records
               if r["status"] in ("MEASURED", "DERIVED")) > 0


def test_mutation_the_router_count_has_one_implementation():
    """`signoff_audit` and `phase3_one_shot_runner` read the router's DRC
    trajectory through `_signoff_drc_format`. A private copy here could drift
    and produce a second answer to one question -- so the shared reader is
    imported, and this pins that it is the one in use."""
    import re as _re

    import _signoff_drc_format
    assert B.router_iter_counts is _signoff_drc_format.router_iter_counts
    # ... and no private regex here has quietly become a second reader. Checked
    # on the COMPILED patterns rather than on the source text, so that naming
    # the message code in a docstring stays allowed and only real code counts.
    local = [name for name, obj in vars(B).items()
             if isinstance(obj, _re.Pattern) and "DRT-0199" in obj.pattern]
    assert local == [], f"a local copy of the router regex is back: {local}"
