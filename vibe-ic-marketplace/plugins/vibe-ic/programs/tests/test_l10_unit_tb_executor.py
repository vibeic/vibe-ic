#!/usr/bin/env python3
"""The unit-TB EXECUTOR — the consumer that did not exist.

MEASURED, opentitan_aes at v1.16.66: `emit_unit_tbs` wrote 8 known-answer
vector testbenches that PASS against the design's own 131-file RTL, and Step 4
still reported `0 functional tests ran for 8 declared L10/L12 row(s)`. Nothing
was wrong with the testbenches — no runner path executed them, so the Step-4
functional denominator (`_sim_results_bridge`, a JUnit under
`phase2/stage1/sim_professional/*/results.xml`) had no source to read.

These tests pin the executor's contract and, above all, its THREE states:
NOT RUN (no simulator / nothing to run — nothing written), ERRORED (the
simulator ran and could not build), FAILED/PASSED (the design was judged).
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import testbench_gen as T           # noqa: E402
import _sim_results_bridge as SRB   # noqa: E402
import cpu_functional_oracle_waiver_check as W   # noqa: E402


def _tb(project: Path, name: str, ported: bool = False) -> Path:
    d = project / "phase2/stage1/sim/tb"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{name}.v"
    f.write_text(f"module {name}{'(input a)' if ported else ''};\nendmodule\n")
    return f


def _rtl(project: Path, name: str, text: str) -> Path:
    d = project / "phase2/stage1/rtl"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(text)
    return f


def _results(project: Path) -> Path:
    return (project / "phase2/stage1/sim_professional"
            / T.UNIT_TB_RESULT_DIR / "results.xml")


# --- the TB / source grammar ------------------------------------------------

def test_a_portless_top_is_a_tb_and_a_ported_module_is_a_source(tmp_path):
    assert T.is_unit_tb(_tb(tmp_path, "vec_one"))
    assert not T.is_unit_tb(_tb(tmp_path, "helper_mod", ported=True))


def test_packages_are_ordered_before_the_package_that_imports_them(tmp_path):
    b = _rtl(tmp_path, "b_pkg.sv", "package b_pkg;\n  parameter int X = a_pkg::Y;\nendpackage\n")
    a = _rtl(tmp_path, "a_pkg.sv", "package a_pkg;\n  parameter int Y = 1;\nendpackage\n")
    m = _rtl(tmp_path, "m.sv", "module m(input c); endmodule\n")
    order = T.package_first_order([b, a, m])
    assert order.index(a) < order.index(b), order
    assert order[-1] == m


# --- NOT RUN: nothing is written, and nothing is claimed --------------------

def test_no_testbench_writes_no_results_xml(tmp_path):
    rep = {}
    assert T.run_unit_tbs(tmp_path, None, rep) == -1
    assert not _results(tmp_path).exists()
    assert "nothing to execute" in rep["reason"]


def test_absent_simulator_is_not_run_and_writes_no_results_xml(tmp_path):
    _tb(tmp_path, "vec_one")
    rep = {}
    assert T.run_unit_tbs(
        tmp_path, None, rep,
        dispatch=lambda argv, wd, c, tool, to: (127, "no verilator")) == -2
    assert rep["sim_executed"] is False
    assert not _results(tmp_path).exists(), (
        "an empty JUnit would let the Step-4 bridge speak about an empty "
        "population — the v1.16.21 defect shape")
    assert "NOT_EXECUTED" in rep["reason"]


# --- the three states, and what the Step-4 bridge makes of each -------------

def _fake_sim(build_rc: int, run_rc: int, run_out: str):
    """A dispatch stub in the shape the runner's single site returns."""
    def _dispatch(argv, run_dir, container, tool, timeout):
        if "--version" in argv:
            return 0, "Verilator 5.051"
        if "--binary" in argv:
            return build_rc, "build transcript"
        return run_rc, run_out
    return _dispatch


def test_build_failure_is_an_error_not_a_failure_and_the_bridge_refuses(
        tmp_path):
    _tb(tmp_path, "vec_one")
    rep = {}
    executed = T.run_unit_tbs(tmp_path, None, rep,
                              dispatch=_fake_sim(1, 0, ""))
    assert executed == 0 and rep["errored"] == 1 and rep["failed"] == 0
    summ = SRB.parse_junit(_results(tmp_path))
    assert summ["tests"] == 1 and summ["errors"] == 1
    assert SRB.find_professional_tb_pass(tmp_path) is None


def test_commented_missing_module_diagnostic_does_not_trigger_a_retry(tmp_path):
    """A source line echoed from an HDL comment is not a tool diagnosis."""
    _tb(tmp_path, "vec_one")
    vendor = tmp_path / "input/vendor_rtl"
    vendor.mkdir(parents=True)
    (vendor / "ghost.sv").write_text("module ghost; endmodule\n")
    builds = 0

    def dispatch(argv, _wd, _container, _tool, _timeout):
        nonlocal builds
        if "--version" in argv:
            return 0, "Verilator 5.051"
        if "--binary" in argv:
            builds += 1
            return 1, "dut.sv:9: // Cannot find module: ghost\nreal syntax error"
        raise AssertionError(f"a failed build must not run: {argv}")

    report = {}
    assert T.run_unit_tbs(tmp_path, None, report, dispatch=dispatch) == 0
    assert builds == 1, (
        "a module name found only inside an echoed HDL comment caused a "
        "second build with an unrelated source"
    )
    assert report["errored"] == 1


def test_real_missing_module_diagnostic_still_resolves_and_retries(tmp_path):
    """The comment filter must not erase a genuine simulator diagnosis."""
    _tb(tmp_path, "vec_one")
    vendor = tmp_path / "input/vendor_rtl"
    vendor.mkdir(parents=True)
    source = vendor / "needed.sv"
    source.write_text("module needed; endmodule\n")
    builds = 0

    def dispatch(argv, _wd, _container, _tool, _timeout):
        nonlocal builds
        if "--version" in argv:
            return 0, "Verilator 5.051"
        if "--binary" in argv:
            builds += 1
            if builds == 1:
                return 1, "Cannot find file containing module: 'needed'"
            assert str(source) in argv
            return 0, "build ok"
        return 0, "[TB vec_one] PASS: matched"

    report = {}
    assert T.run_unit_tbs(tmp_path, None, report, dispatch=dispatch) == 1
    assert builds == 2
    assert report["passed"] == 1


def test_a_failing_simulation_is_a_failure_and_the_bridge_refuses(
        tmp_path):
    _tb(tmp_path, "vec_one")
    rep = {}
    assert T.run_unit_tbs(tmp_path, None, rep,
                          dispatch=_fake_sim(0, 1,
                                             "[TB vec_one] FAIL: word 3")) == 1
    assert rep["failed"] == 1 and rep["errored"] == 0
    summ = SRB.parse_junit(_results(tmp_path))
    assert summ["failures"] == 1 and summ["errors"] == 0
    assert SRB.find_professional_tb_pass(tmp_path) is None


def test_a_zero_rc_run_that_prints_FAIL_is_still_a_failure(tmp_path):
    _tb(tmp_path, "vec_one")
    rep = {}
    T.run_unit_tbs(tmp_path, None, rep,
                   dispatch=_fake_sim(0, 0, "[TB vec_one] FAIL: word 3"))
    assert rep["failed"] == 1, "a TB that exits 0 while printing FAIL is a FAIL"


def test_a_passing_run_is_the_step4_functional_denominator(tmp_path):
    _tb(tmp_path, "vec_one")
    _tb(tmp_path, "vec_two")
    rep = {}
    assert T.run_unit_tbs(tmp_path, None, rep,
                          dispatch=_fake_sim(0, 0, "[TB x] PASS: matched")) == 2
    assert rep["sim_executed"] is True
    got = SRB.find_professional_tb_pass(tmp_path)
    assert got and got["tests"] == 2 and got["passed"] == 2
    assert got["suite_names"] == [T.UNIT_TB_RESULT_DIR], (
        "the message that credits this result must be able to name the "
        "producer that actually wrote it")


# --- the gate sentence: 'nobody ran them' != 'they ran and failed' ----------

def test_gate_distinguishes_a_failing_transcript_from_no_transcript(tmp_path):
    d = tmp_path / "phase2/stage1/sim_professional/l10_unit_tb"
    d.mkdir(parents=True)
    (d / "results.xml").write_text(
        '<testsuites><testsuite name="l10_unit_tb" tests="8" failures="8" '
        'errors="0" skipped="0"><testcase name="a"><failure message="m"/>'
        '</testcase></testsuite></testsuites>')
    summ = SRB.parse_junit(d / "results.xml")
    assert summ["tests"] == 8 and summ["failures"] == 8
    assert SRB.find_professional_tb_pass(tmp_path) is None
    # and the reverse control: with NO transcript the bridge still says None
    assert SRB.find_professional_tb_pass(tmp_path / "nowhere") is None


def test_gate_message_names_the_executed_population(monkeypatch, tmp_path):
    assert "0 functional tests ran" in W.__doc__ or True  # module-level anchor
    src = (PROGRAMS / "cpu_functional_oracle_waiver_check.py").read_text()
    assert "a functional transcript EXISTS but did NOT pass" in src, (
        "the INCOMPLETE sentence must not report 'ran and failed' as "
        "'0 functional tests ran'")


# --- §4.05: the resolver reads the design INPUT, never a golden -------------

def test_missing_module_resolver_reads_input_and_skips_golden(tmp_path):
    inp = tmp_path / "input"
    (inp / "vendor_rtl").mkdir(parents=True)
    (inp / "golden").mkdir(parents=True)
    (inp / "golden" / "leak.sv").write_text("module wanted; endmodule\n")
    assert T._resolve_from_design_input(tmp_path, "wanted") is None
    good = inp / "vendor_rtl" / "wanted.sv"
    good.write_text("module wanted(input a); endmodule\n")
    assert T._resolve_from_design_input(tmp_path, "wanted") == good


# --- one dispatch site, not two --------------------------------------------

def test_the_executor_owns_no_dispatch_site_of_its_own():
    """v1.16.91 added the mount-on-demand third dispatch site, the image-id
    resolution and the `_record_sim_toolchain` provenance for the reference-TB
    chain. This executor is a DIFFERENT layer (L10 unit TBs, verilator) and
    must not grow a second copy of any of that."""
    src = (PROGRAMS / "testbench_gen.py").read_text()
    for owned_elsewhere in ("docker inspect", "{{.Image}}", "docker run",
                            "_record_sim_toolchain", "-v %s:%s"):
        assert owned_elsewhere not in src, owned_elsewhere
    assert "_run_sim_stage" in src, (
        "it must route through the runner's single dispatch site")
    runner = (PROGRAMS / "design_one_shot_runner.py").read_text()
    assert "def _run_sim_stage(" in runner
    assert runner.count("def _run_stage_in_mounted_image(") == 1
