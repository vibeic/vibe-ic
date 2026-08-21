#!/usr/bin/env python3
"""The mutation fixture, and why this lane needs a harness instead of a revert.

WHY THE ORDINARY MUTATION CONTROL DOES NOT WORK HERE
====================================================
The standard control is: revert the change, and a named test goes red. That
control assumes the change EDITED something. This lane is entirely NEW files, so
reverting it deletes `_ppa/metrics.py` AND every test that pins it, and pytest
reports the result as `no tests ran` -- zero failures. That is precisely the
measurement trap this repository has paid for: "the run finished with no
failures" and "the run never started" both print zero, and a reverted-new-file
lane produces the second while looking like the first.

So the control is inverted. Instead of removing the code and looking for a red
test, this file KEEPS the tests and BREAKS THE CODE, one guard at a time, in a
copy -- and asserts that the invariant stops holding. Each mutation below is a
plausible simplification somebody could make next month while "cleaning up",
and each one, if it survived, would make a real defect readable as a clean
result.

A mutation that does NOT change the answer is a guard that is not doing
anything, and this file fails on that too: `test_every_mutation_is_detected`
asserts each mutation actually applied (the string was found) before asserting
it changed the verdict.
"""
import importlib.util
import pathlib
import shutil
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import metrics as M  # noqa: E402

_PPA = pathlib.Path(__file__).resolve().parents[1] / "_ppa"

SCOPE_SYNTH = {"stage": "synthesis"}
SCOPE_ROUTE = {"stage": "post_route_extracted", "process": "ss"}
SRC = {"path": "sta.rpt", "tool": "opensta"}


def load_mutant(tmp_path, old, new, name):
    """`_ppa.metrics` with one guard replaced, importable in isolation.

    Raises if `old` is not present -- a mutation that silently applied to
    nothing would make this whole file pass by doing nothing, which is the same
    defect it exists to catch, one level up.
    """
    pkg = tmp_path / f"_ppa_mut_{name}"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy(_PPA / "canonical_json.py", pkg / "canonical_json.py")
    src = (_PPA / "metrics.py").read_text(encoding="utf-8")
    assert old in src, (
        f"mutation {name!r} did not apply: the source no longer contains the "
        f"text it mutates. The guard may have been renamed or removed, and "
        f"this harness must not pass by mutating nothing.")
    (pkg / "metrics.py").write_text(src.replace(old, new, 1), encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        spec = importlib.util.spec_from_file_location(
            f"_ppa_mut_{name}.metrics", pkg / "metrics.py",
            submodule_search_locations=[str(pkg)])
        # the package itself must exist first, for the relative import
        pspec = importlib.util.spec_from_file_location(
            f"_ppa_mut_{name}", pkg / "__init__.py",
            submodule_search_locations=[str(pkg)])
        pmod = importlib.util.module_from_spec(pspec)
        sys.modules[f"_ppa_mut_{name}"] = pmod
        pspec.loader.exec_module(pmod)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"_ppa_mut_{name}.metrics"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(tmp_path))


def a_sentinel_record():
    rec = M.not_measured("power.total_mw", "no VCD", SCOPE_ROUTE)
    rec["value"] = 0
    return rec


# --------------------------------------------------------------------------

def test_mutation_dropping_the_sentinel_guard_lets_zero_mean_not_measured(tmp_path):
    """Pinned by test_ppa_metrics.py::
    test_a_non_measurement_may_not_carry_a_value_at_all"""
    assert "VALUE_ON_A_NON_MEASUREMENT" in [c for c, _ in
                                            M.validate(a_sentinel_record())]
    mut = load_mutant(
        tmp_path,
        '        if has_value:\n            found = rec["value"]',
        '        if False:\n            found = rec["value"]',
        "sentinel")
    # the mutant accepts a NOT_MEASURED row carrying 0 -- an implied zero that
    # every consumer downstream reads as a measurement of zero.
    assert mut.validate(a_sentinel_record()) == []


def test_mutation_keying_the_index_by_metric_name_merges_two_facts(tmp_path):
    """Pinned by test_ppa_metrics.py::
    test_two_records_with_the_same_metric_and_different_scope_are_two_facts"""
    synth = M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC)
    route = M.measured("area.die_um2", 15400.0, "um^2", SCOPE_ROUTE, SRC)
    assert M.record_key(synth) != M.record_key(route)
    mut = load_mutant(
        tmp_path,
        'return (str(rec.get("metric", "")), scope_digest(rec.get("scope") or {}))',
        'return (str(rec.get("metric", "")), "")',
        "key")
    # under the mutant a synthesis area and a post-route area are one fact, and
    # the index refuses the second as a conflict instead of holding both.
    assert mut.record_key(synth) == mut.record_key(route)
    idx = mut.MetricIndex()
    idx.add(synth)
    with pytest.raises(mut.MetricError):
        idx.add(route)


def test_mutation_letting_compare_ignore_scope_picks_a_winner(tmp_path):
    """Pinned by test_ppa_metrics.py::test_compare_refuses_across_differing_scope
    and by test_ppa_measurement_check.py::
    test_compare_across_differing_scope_is_UNDETERMINED_not_a_winner"""
    synth = M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC)
    route = M.measured("area.die_um2", 15400.0, "um^2", SCOPE_ROUTE, SRC)
    assert M.compare(synth, route, better="lower")["verdict"] == \
        M.CMP_DIFFERENT_SCOPE
    mut = load_mutant(tmp_path, "    if da != db:", "    if False:", "scope")
    out = mut.compare(synth, route, better="lower")
    # THE DEFECT, in one line: the smaller number wins, and both rows say
    # `area.die_um2`, so no reader downstream can see that one of them is a
    # synthesis estimate and the other is a routed die.
    assert out["verdict"] == mut.CMP_OK
    assert out["winner"] == "a"


def test_mutation_rendering_only_rows_with_values_hides_the_gap(tmp_path):
    """Pinned by test_ppa_metrics.py::
    test_the_report_prints_the_absent_row_literally"""
    idx = M.MetricIndex()
    idx.add(M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC))
    expected = [{"metric": "area.die_um2", "scope": SCOPE_SYNTH},
                {"metric": "timing.setup.wns_ns", "scope": SCOPE_ROUTE}]
    assert "timing.setup.wns_ns" in M.format_coverage(M.coverage(idx, expected))
    mut = load_mutant(
        tmp_path,
        "    for row in cov.rows:\n        scope = ",
        "    for row in [r for r in cov.rows if r.outcome == COVERED]:\n"
        "        scope = ",
        "render")
    midx = mut.MetricIndex()
    midx.add(M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC))
    text = mut.format_coverage(mut.coverage(midx, expected))
    # the header still says "2 expected", and the body shows one row. A reader
    # skimming the body sees one fact and no hole.
    assert "timing.setup.wns_ns" not in text


def test_mutation_aggregating_rc_with_max_promotes_a_refusal(tmp_path):
    """Pinned by test_ppa_metrics.py::
    test_adding_a_record_can_never_subtract_a_finding

    The exact defect this repository already shipped in
    `ppa_head_to_head_check`: rc 2 is the LARGER integer and the WEAKER
    verdict, so max() over exit codes turns a refusal into an undetermined --
    and `flow_compliance_check` maps rc 2 to VACUOUS_PASS.
    """
    idx = M.MetricIndex()
    idx.add(M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC))
    idx.add(M.not_measured("power.total_mw", "no VCD", SCOPE_ROUTE))
    expected = [{"metric": "area.die_um2", "scope": SCOPE_SYNTH},
                {"metric": "power.total_mw", "scope": SCOPE_ROUTE},
                {"metric": "timing.setup.wns_ns", "scope": SCOPE_ROUTE}]
    assert M.coverage_rc(M.coverage(idx, expected)) == 1
    mut = load_mutant(
        tmp_path,
        "        if this == 1:\n            return 1\n"
        "        if this == 2:\n            rc = 2\n    return rc",
        "        rc = max(rc, this)\n    return rc",
        "aggregate")
    midx = mut.MetricIndex()
    midx.add(M.measured("area.die_um2", 12000.0, "um^2", SCOPE_SYNTH, SRC))
    midx.add(M.not_measured("power.total_mw", "no VCD", SCOPE_ROUTE))
    # ADDING the declared-absent row SUBTRACTED the refusal.
    assert mut.coverage_rc(mut.coverage(midx, expected)) == 2


def test_mutation_returning_empty_for_an_unreadable_document(tmp_path):
    """Rule 9. Pinned by test_ppa_metrics.py::
    test_an_unreadable_document_is_not_an_empty_one"""
    with pytest.raises(M.MetricError):
        M.records_from_document({"schema": "something.else.v1"})
    mut = load_mutant(
        tmp_path,
        '    raise MetricError(\n        "UNRECOGNISED_DOCUMENT",',
        '    return []\n    raise MetricError(\n        "UNRECOGNISED_DOCUMENT",',
        "unreadable")
    # "I could not read it" and "I read it and it was empty" are now the same
    # answer to every caller.
    assert mut.records_from_document({"schema": "something.else.v1"}) == []


def test_mutation_coverage_without_a_denominator_reports_a_vacuous_hundred(tmp_path):
    """Pinned by test_ppa_metrics.py::test_coverage_refuses_an_empty_expectation_set"""
    with pytest.raises(M.MetricError):
        M.coverage(M.MetricIndex(), [])
    mut = load_mutant(
        tmp_path,
        '        raise MetricError(\n            "NO_EXPECTATION_SET",',
        '        return Coverage([], [])\n        raise MetricError(\n'
        '            "NO_EXPECTATION_SET",',
        "denominator")
    cov = mut.coverage(mut.MetricIndex(), [])
    # a complete coverage report over a population nobody enumerated
    assert cov.complete and mut.coverage_rc(cov) == 0


def test_every_mutation_above_names_a_test_that_pins_it():
    """The list, so a guard cannot be added here without a test pinning it in
    the ordinary suite -- this harness proves guards are load-bearing, it is
    not a substitute for testing them."""
    here = pathlib.Path(__file__).read_text(encoding="utf-8")
    for name in ("test_a_non_measurement_may_not_carry_a_value_at_all",
                 "test_two_records_with_the_same_metric_and_different_scope",
                 "test_compare_refuses_across_differing_scope",
                 "test_the_report_prints_the_absent_row_literally",
                 "test_adding_a_record_can_never_subtract_a_finding",
                 "test_an_unreadable_document_is_not_an_empty_one",
                 "test_coverage_refuses_an_empty_expectation_set"):
        assert name in here
    suite = (pathlib.Path(__file__).parent / "test_ppa_metrics.py").read_text()
    for name in ("test_a_non_measurement_may_not_carry_a_value_at_all",
                 "test_compare_refuses_across_differing_scope",
                 "test_the_report_prints_the_absent_row_literally",
                 "test_adding_a_record_can_never_subtract_a_finding",
                 "test_an_unreadable_document_is_not_an_empty_one",
                 "test_coverage_refuses_an_empty_expectation_set"):
        assert f"def {name}(" in suite, f"{name} is not in the ordinary suite"
