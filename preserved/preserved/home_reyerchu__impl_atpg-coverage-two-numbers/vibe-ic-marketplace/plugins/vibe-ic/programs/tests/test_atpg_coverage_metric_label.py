"""Two numbers, one word: the ATPG coverage-metric label gate.

THE MEASURED DEFECT
-------------------
One design, one run, one coverage.json. The ATPG runner's console printed

    fault_atpg_run: stuck-at coverage=61.70%  target=95.00%

while the sign-off gate reading the SAME artefact printed

    measured stuck-at coverage 90.04% < effective target 95.00%

Neither number is wrong. 61.70 is RAW FAULT coverage (detected / total) and
90.04 is TEST coverage (detected / (total - ATPG-untestable)). What was wrong
is the WORD: "stuck-at coverage" names the FAULT MODEL, and both metrics are
stuck-at numbers, so it disambiguates nothing. Read across two rounds the pair
is a 28-point regression that never happened. The same shape is frozen in this
repo's checked-in evidence: the caravel tree's human .rpt says 60.53 and the
gate says 89.59.

THE RULE
--------
A coverage figure emitted to a human NAMES ITS METRIC, and one word never
carries both numbers in one run.  Enforced by
`dft_atpg_coverage_check --repo` over every source file where the RAW and TEST
vocabularies coexist; rendered by the single sanctioned
`dft_signoff_common.fmt_coverage`.

WHAT THESE TESTS ARE FOR
------------------------
`test_prefix_producer_line_is_caught` carries the pre-fix emission lines
VERBATIM. It is the negative control: with the fix reverted the gate must FAIL
on exactly those lines. Delete the fix and this test goes red; without it a
green suite would prove only that the gate finds nothing.

`test_correctly_labelled_shipped_programs_stay_clean` is the reverse control.
`dft_test_coverage.py` and `transition_fault_atpg_run.py` were ALREADY labelling
their figures before this rule existed and are untouched by it. A rule that
fired on them would be a rule that fires on everything, and a zero finding
count reached by narrowing until nothing is left would take the real defect
with it.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = _load("dft_atpg_coverage_check")
dsc = _load("dft_signoff_common")


# ── the pre-fix emission sites, copied byte-for-byte ───────────────────
# fault_atpg_run.py before the fix — the console line and the .rpt line that
# together produced the 61.70-vs-90.04 pair.
_PREFIX_PRODUCER = '''
def emit(report, coverage_ratio, min_coverage, cov_out):
    cov = report.get("coverage_pct", 0.0)
    target = report.get("target_pct", 0.0)
    print(f"fault_atpg_run: stuck-at coverage={cov:.2f}%  target={target:.2f}%  "
          f"stuck_at_ge_target={report.get('stuck_at_ge_target', False)}")
    rpt = (
        f"Stuck-at %    : {coverage_ratio:.2f}\\n"
        f"Target (min)  : {min_coverage:.2f}\\n"
        f"(coverage metadata: {cov_out})\\n"
    )
    test_coverage_pct = report.get("test_coverage_pct")
    return rpt, test_coverage_pct
'''

# The same two figures after the fix — each carries its metric.
_FIXED_PRODUCER = '''
def emit(report, coverage_ratio, min_coverage, cov_out):
    cov = report.get("coverage_pct", 0.0)
    target = report.get("target_pct", 0.0)
    print(f"fault_atpg_run: stuck-at raw fault coverage={cov:.2f}%  "
          f"target={target:.2f}%")
    rpt = (
        f"Stuck-at raw fault coverage %  : {coverage_ratio:.2f}\\n"
        f"Target (min)  : {min_coverage:.2f}\\n"
        f"(coverage metadata: {cov_out})\\n"
    )
    test_coverage_pct = report.get("test_coverage_pct")
    return rpt, test_coverage_pct
'''


# ── 1. NEGATIVE CONTROL, both directions ───────────────────────────────

def test_prefix_producer_line_is_caught():
    """The byte-identical pre-fix emissions FAIL, naming both sites."""
    found = gate.scan_source_text(_PREFIX_PRODUCER, "pre_fix.py")
    labels = [f["label"].strip() for f in found]
    assert len(found) == 2, f"expected both pre-fix figures flagged, got {found}"
    assert all(f["rule"] == "UNLABELLED_COVERAGE_FIGURE" for f in found)
    assert "fault_atpg_run: stuck-at coverage=" in labels
    assert "Stuck-at %    :" in labels


def test_fixed_producer_line_is_clean():
    """The SAME two figures, each carrying its metric, PASS."""
    assert gate.scan_source_text(_FIXED_PRODUCER, "post_fix.py") == []


def test_shipped_producer_is_clean_and_still_in_scope():
    """The shipped fault_atpg_run is clean — and is still SCANNED.

    A file that fell out of scope would also report zero findings; this asserts
    the zero is a measurement, not an absence."""
    report = gate.scan_repo()
    in_scope = {f["file"] for f in report["files_in_scope"]}
    assert "programs/fault_atpg_run.py" in in_scope
    assert "programs/dft_atpg_coverage_check.py" in in_scope
    assert report["findings"] == [], report["findings"]
    assert report["verdict"] == "PASS"


# ── 2. REVERSE CONTROL: legitimate emissions must STILL pass ───────────

def test_correctly_labelled_shipped_programs_stay_clean():
    """Two programs that already named their metric, untouched by this rule."""
    report = gate.scan_repo()
    in_scope = {f["file"] for f in report["files_in_scope"]}
    for already_correct in ("programs/dft_test_coverage.py",
                            "programs/transition_fault_atpg_run.py"):
        assert already_correct in in_scope, (
            f"{already_correct} carries both metric vocabularies and must be "
            f"scanned — otherwise its clean result proves nothing")
        assert not [f for f in report["findings"]
                    if f["file"] == already_correct]


@pytest.mark.parametrize("src", [
    # A THRESHOLD is not a measurement of this design; the raw-vs-test
    # ambiguity does not apply to a bar.
    'def f(t): print(f"Minimum stuck-at coverage % required: {t:.2f}%")',
    'def f(foundry_floor): print(f"ATPG coverage gated at {foundry_floor:.0f}%")',
    # A path, a count and a module name are not coverage figures.
    'def f(cov_out): print(f"(coverage metadata: {cov_out})")',
    'def f(a, b): print(f"Covered / Total: {a} / {b}")',
    # Rendered through the one sanctioned renderer: metric supplied at run time.
    'def f(v, m): print(f"stuck-at coverage {fmt_coverage(v, m)}")',
])
def test_legitimate_emissions_do_not_fire(src):
    assert gate.scan_source_text(src, "ok.py") == []


def test_line_coverage_programs_are_out_of_scope():
    """Line / branch / functional coverage is a different quantity on a
    different axis; dragging it in would be a false positive."""
    in_scope = {f["file"] for f in gate.scan_repo()["files_in_scope"]}
    for other_axis in ("programs/verilator_coverage_measure.py",
                       "programs/rtl_unit_test_coverage_check.py",
                       "programs/coverage_closure.py"):
        assert other_axis not in in_scope


# ── 3. THE SECOND CLAUSE: one word may not carry the other number ──────

def test_label_that_contradicts_its_value_is_caught():
    src = ('def f(rep): print(f"test coverage {rep[\'coverage_pct\']:.2f}%")')
    found = gate.scan_source_text(src, "swapped.py")
    assert [f["rule"] for f in found] == ["LABEL_CONTRADICTS_VALUE"], found
    assert found[0]["expression_metric"] == dsc.METRIC_RAW


def test_two_figures_on_one_line_each_keep_their_own_word():
    src = ('def f(r): print(f"raw fault coverage {r[\'raw_coverage_pct\']:.2f}% '
           'vs test coverage {r[\'test_coverage_pct\']:.2f}%")')
    assert gate.scan_source_text(src, "pair.py") == []


# ── 4. THE RENDERER REFUSES RATHER THAN DEFAULTS ───────────────────────

def test_fmt_coverage_labels_both_metrics():
    assert dsc.fmt_coverage(60.5336, dsc.METRIC_RAW) == "raw fault coverage 60.53%"
    assert dsc.fmt_coverage(89.5897, dsc.METRIC_TEST) == "test coverage 89.59%"
    assert dsc.fmt_coverage(None, dsc.METRIC_TEST) == "test coverage (not measured)"


def test_fmt_coverage_refuses_an_unknown_metric():
    """Defaulting a metric would re-create the defect under a new name."""
    with pytest.raises(ValueError):
        dsc.fmt_coverage(90.04, "stuck-at coverage")


def test_metric_of_field_is_none_when_the_name_does_not_decide():
    assert dsc.metric_of_field("test_coverage_pct") == dsc.METRIC_TEST
    assert dsc.metric_of_field("coverage_pct") == dsc.METRIC_RAW
    # `measured_coverage_pct` holds whichever metric was selected at run time.
    assert dsc.metric_of_field("measured_coverage_pct") is None


# ── 5. THE GATE CARRIES THE METRIC INTO ITS OWN SENTENCES ──────────────

def test_gate_names_the_metric_it_judged():
    """The 90.04 half of the pair: the gate's verdict prose must say WHICH."""
    res = gate.evaluate({"tool": "fault", "coverage_pct": 61.70,
                         "test_coverage_pct": 90.04, "target_pct": 95.0,
                         "stuck_at_ge_target": False}, None)
    assert res["measured_coverage_pct"] == 90.04
    assert res["raw_coverage_pct"] == 61.70
    assert res["measured_metric"] == dsc.METRIC_TEST
    joined = " ".join(res["reasons"])
    assert "test coverage 90.04%" in joined, joined
    # and the raw number is never emitted under the same word
    assert "stuck-at coverage 90.04" not in joined


def test_gate_does_not_call_a_raw_number_test_coverage():
    """No test_coverage_pct in the artefact -> the measured number is RAW, and
    the prose must not call it TEST."""
    res = gate.evaluate({"tool": "fault", "coverage_pct": 61.70,
                         "target_pct": 95.0}, None)
    assert res["measured_metric"] == dsc.METRIC_RAW
    joined = " ".join(res["reasons"])
    assert "raw fault coverage 61.70%" in joined, joined
    assert "test coverage 61.70" not in joined


def test_rpt_fallback_declares_which_metric_it_read():
    """A number recovered from prose keeps the axis it was on."""
    assert gate._parse_rpt_measured("Stuck-at %    : 60.53\n") == (
        60.53, dsc.METRIC_RAW)
    assert gate._parse_rpt_measured(
        "Stuck-at raw fault coverage %  : 60.53\n"
        "Stuck-at test coverage %      : 89.59\n") == (89.59, dsc.METRIC_TEST)
