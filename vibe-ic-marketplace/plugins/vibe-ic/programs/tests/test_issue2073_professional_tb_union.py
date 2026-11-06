"""Issue #2073 — the Step-4 professional-TB verdict is the UNION of every
sibling suite, never whichever one happens to sort first.

Measured on a mixed analog/digital project (lane czacctb, #2064): an
analog-acceptance suite with 10
failures sat beside a 7-test green digital suite under
``phase2/stage1/sim_professional/*``. ``find_professional_tb_pass`` returned the
first passing sibling, so the gate published verdict PASS while the SAME
record's ``functional_test_denominator`` — which already summed the union —
read ``tests_run 17 / passed 7 / failed 10``.

The invariant this file defends is the one that was broken: a verdict may not
contradict its own denominator. Every assertion here is structural (synthetic
JUnit, no simulator) and chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _sim_results_bridge as SRB               # noqa: E402
import cpu_functional_oracle_waiver_check as ORACLE  # noqa: E402


def _junit(name: str, tests: int, failures: int = 0, errors: int = 0,
           skipped: int = 0) -> str:
    cases = "".join(
        f'<testcase classname="{name}" name="{name}_{i}">'
        + ("<failure message=\"declared behaviour failed\"/>"
           if i < failures else "")
        + "</testcase>"
        for i in range(tests))
    return ('<?xml version="1.0" encoding="utf-8"?>'
            f'<testsuites name="cocotb tests"><testsuite name="{name}" '
            f'errors="{errors}" failures="{failures}" skipped="{skipped}" '
            f'tests="{tests}">{cases}</testsuite></testsuites>')


def _suite(project: Path, name: str, xml: "str | None") -> Path:
    d = project / "phase2/stage1/sim_professional" / name
    d.mkdir(parents=True, exist_ok=True)
    if xml is not None:
        (d / "results.xml").write_text(xml)
    return d


# The measured shape: the FAILING sibling sorts FIRST, so the pre-fix loop
# `continue`d past it and credited the green one. Both orderings are covered.
_GREEN_7 = ("l10_unit_tb", _junit("l10_unit_tb", 7))
_RED_10 = ("analog_acceptance", _junit("analog_acceptance", 10, failures=10))


def _two_suite_project(tmp_path: Path) -> Path:
    for name, xml in (_GREEN_7, _RED_10):
        _suite(tmp_path, name, xml)
    return tmp_path


# --------------------------------------------------------------------------
# 1. The defect itself: a failing sibling can no longer be out-sorted.
# --------------------------------------------------------------------------
def test_a_failing_sibling_denies_the_pass(tmp_path):
    _two_suite_project(tmp_path)
    union = SRB.professional_tb_union(tmp_path)
    assert union["tests"] == 17 and union["passed"] == 7
    assert union["failures"] == 10 and union["errors"] == 0
    assert union["verdict"] == SRB.UNION_FAIL
    assert SRB.find_professional_tb_pass(tmp_path) is None


def test_the_failing_sibling_is_denied_in_either_sort_order(tmp_path):
    """The pre-fix reader was order-dependent, so the guard must be too: with
    the GREEN suite sorting first the loop returned on its very first
    iteration."""
    _suite(tmp_path, "a_green", _junit("a_green", 7))
    _suite(tmp_path, "z_red", _junit("z_red", 10, failures=10))
    assert SRB.find_professional_tb_pass(tmp_path) is None
    assert SRB.professional_tb_union(tmp_path)["verdict"] == SRB.UNION_FAIL


def test_an_erroring_sibling_denies_the_pass(tmp_path):
    """`errors` are testbenches that never ran — the union counts them too."""
    _suite(tmp_path, "a_green", _junit("a_green", 7))
    _suite(tmp_path, "z_err", _junit("z_err", 2, errors=2))
    assert SRB.find_professional_tb_pass(tmp_path) is None


# --------------------------------------------------------------------------
# 2. Every failure is NAMED, and every unmeasured suite is NAMED.
# --------------------------------------------------------------------------
def test_every_failing_sibling_is_named(tmp_path):
    _two_suite_project(tmp_path)
    _suite(tmp_path, "b_red", _junit("b_red", 3, failures=1))
    failing = SRB.professional_tb_union(tmp_path)["failing"]
    assert len(failing) == 2
    assert any("sim_professional/analog_acceptance/results.xml" in f
               for f in failing)
    assert any("sim_professional/b_red/results.xml" in f for f in failing)


def test_a_suite_that_produced_no_results_is_not_measured_by_name(tmp_path):
    _suite(tmp_path, "l10_unit_tb", _junit("l10_unit_tb", 7))
    _suite(tmp_path, "dut_core", None)          # generated, never ran
    union = SRB.professional_tb_union(tmp_path)
    assert [e["rel_dir"] for e in union["not_measured"]] == [
        "phase2/stage1/sim_professional/dut_core"]
    assert union["not_measured"][0]["reason"] == "produced no results.xml"
    assert "sim_professional/dut_core" in SRB.union_disclosure(union)
    # It is NOT counted as a pass and NOT counted as a failure.
    assert union["tests"] == 7 and union["failures"] == 0
    assert union["verdict"] == SRB.UNION_PASS


def test_an_unreadable_result_is_not_measured_not_skipped(tmp_path):
    """"Could not read it" is not "read it and it was empty"."""
    _suite(tmp_path, "l10_unit_tb", _junit("l10_unit_tb", 7))
    _suite(tmp_path, "broken", "not xml <<<")
    union = SRB.professional_tb_union(tmp_path)
    assert union["not_measured"] == [{
        "rel_dir": "phase2/stage1/sim_professional/broken",
        "reason": "results.xml is not a readable JUnit document"}]


def test_absent_and_not_measured_are_different_facts(tmp_path):
    assert SRB.professional_tb_union(tmp_path)["verdict"] == SRB.UNION_ABSENT
    _suite(tmp_path, "dut_core", None)
    assert (SRB.professional_tb_union(tmp_path)["verdict"]
            == SRB.UNION_NOT_MEASURED)


# --------------------------------------------------------------------------
# 3. The other direction: an all-green union IS a pass, and it is the UNION.
# --------------------------------------------------------------------------
def test_an_all_green_union_passes_with_the_union_counts(tmp_path):
    _suite(tmp_path, "l10_unit_tb", _junit("l10_unit_tb", 7))
    _suite(tmp_path, "analog_acceptance", _junit("analog_acceptance", 10))
    got = SRB.find_professional_tb_pass(tmp_path)
    assert got is not None
    assert got["tests"] == 17 and got["passed"] == 17
    assert got["failures"] == 0 and got["errors"] == 0
    assert got["rel_paths"] == [
        "phase2/stage1/sim_professional/analog_acceptance/results.xml",
        "phase2/stage1/sim_professional/l10_unit_tb/results.xml"]
    # `rel_path` stays a SINGLE real path: callers dereference it.
    assert (tmp_path / got["rel_path"]).is_file()


def test_a_single_suite_tree_is_unchanged(tmp_path):
    """NO-CHANGE CONTROL. Every assertion here holds on the pre-fix reader too
    — that is the point: the union may not disturb the one-suite answer. It is
    the only test in this file that is GREEN on both sides of the fix."""
    _suite(tmp_path, "dut_core", _junit("dut_core", 1))
    got = SRB.find_professional_tb_pass(tmp_path)
    assert got is not None
    assert got["rel_path"] == "phase2/stage1/sim_professional/dut_core/results.xml"
    assert got["tests"] == 1 and got["passed"] == 1
    assert got["failures"] == 0 and got["errors"] == 0 and got["skipped"] == 0
    assert got["suite_names"] == ["dut_core"]
    # …and a single FAILING suite is still None, exactly as before.
    _suite(tmp_path, "dut_core", _junit("dut_core", 1, failures=1))
    assert SRB.find_professional_tb_pass(tmp_path) is None


def test_a_single_suite_summary_carries_the_new_population_fields(tmp_path):
    _suite(tmp_path, "dut_core", _junit("dut_core", 1))
    got = SRB.find_professional_tb_pass(tmp_path)
    assert got["rel_paths"] == [
        "phase2/stage1/sim_professional/dut_core/results.xml"]
    assert got["not_measured"] == []


def test_an_all_skipped_union_is_vacuous_not_a_pass(tmp_path):
    _suite(tmp_path, "dut_core", _junit("dut_core", 1, skipped=1))
    union = SRB.professional_tb_union(tmp_path)
    assert union["verdict"] == SRB.UNION_VACUOUS
    assert SRB.find_professional_tb_pass(tmp_path) is None


# --------------------------------------------------------------------------
# 4. THE INVARIANT: the verdict may not contradict its own denominator.
# --------------------------------------------------------------------------
def _connectivity_bridge(project: Path) -> None:
    sim = project / "phase2/stage1/sim"
    sim.mkdir(parents=True, exist_ok=True)
    run = project / "phase2/stage1/sim_full_stack/generic_full_stack_run"
    run.mkdir(parents=True, exist_ok=True)
    (run / "full_stack.log").write_text("FULL_STACK_TB_INIT\nFULL_STACK_TB_DONE\n")
    (sim / "results.xml").write_text(
        "<results><verdict>CONNECTIVITY_PASS</verdict>"
        "<functional_verified>false</functional_verified>"
        "<capability_gap>cap:cpu_functional_oracle</capability_gap>"
        "<evidence>phase2/stage1/sim_full_stack/generic_full_stack_run/"
        "full_stack.log</evidence>"
        "<waiver_reason>class DEFERRED</waiver_reason></results>")


def test_the_gate_verdict_never_contradicts_its_own_denominator(tmp_path):
    _two_suite_project(tmp_path)
    _connectivity_bridge(tmp_path)
    report = tmp_path / "reports/phase2/gates/oracle.json"
    rc = ORACLE.main([str(tmp_path), "--json", str(report)])
    rec = json.loads(report.read_text())
    denom = rec["functional_test_denominator"]
    assert denom["tests_run"] == 17 and denom["tests_passed"] == 7
    assert denom["tests_failed"] == 10
    # THE MEASURED DEFECT: rc was 0 / verdict PASS beside this denominator.
    assert rc == 1 and rec["verdict"] == "INCOMPLETE"
    # …and the failing sibling is named in the sentence a reader gets.
    assert "sim_professional/analog_acceptance/results.xml" in rec["message"]


def test_an_all_green_union_still_supersedes_the_waiver(tmp_path):
    _suite(tmp_path, "l10_unit_tb", _junit("l10_unit_tb", 7))
    _suite(tmp_path, "analog_acceptance", _junit("analog_acceptance", 10))
    _connectivity_bridge(tmp_path)
    report = tmp_path / "reports/phase2/gates/oracle.json"
    rc = ORACLE.main([str(tmp_path), "--json", str(report)])
    rec = json.loads(report.read_text())
    assert rc == 0 and rec["verdict"] == "PASS"
    assert rec["functional_test_denominator"]["tests_run"] == 17
    assert rec["functional_test_denominator"]["tests_failed"] == 0
    # both transcripts are cited, not just the one that sorted first
    assert "sim_professional/l10_unit_tb/results.xml" in rec["message"]
    assert "sim_professional/analog_acceptance/results.xml" in rec["message"]




if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
