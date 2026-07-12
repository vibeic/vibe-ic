"""Tests for the professional_tb sim-results bridge (2026-07-13).

Covers:
  * _sim_results_bridge.parse_junit / find_professional_tb_pass (pure parser)
  * cpu_functional_oracle_waiver_check: a real professional_tb PASS SUPERSEDES
    the connectivity-DEFERRED waiver (rc=3 → rc=0 real functional PASS).

Pure/structural (no container): drives on synthetic JUnit + connectivity XML.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import _sim_results_bridge as SRB  # noqa: E402
import cpu_functional_oracle_waiver_check as W  # noqa: E402

# A real cocotb JUnit PASS (failures=0, errors=0, one test).
_JUNIT_PASS = (
    "<?xml version='1.0' encoding='utf-8'?>\n"
    '<testsuites name="cocotb tests"><testsuite name="tb_spm" errors="0" '
    'failures="0" skipped="0" tests="1" time="0.42">'
    '<testcase classname="tb_spm" name="professional_stream_test" '
    'time="0.42"/></testsuite></testsuites>'
)
_JUNIT_FAIL = _JUNIT_PASS.replace('failures="0"', 'failures="2"')
_JUNIT_VACUOUS = _JUNIT_PASS.replace('tests="1"', 'tests="0"').replace(
    "<testcase classname=\"tb_spm\" name=\"professional_stream_test\" "
    "time=\"0.42\"/>", "")
# The connectivity bridge (NOT JUnit) — must NEVER be read as a functional PASS.
_CONNECTIVITY = (
    "<results><verdict>CONNECTIVITY_PASS</verdict>"
    "<functional_verified>false</functional_verified>"
    "<verification_track>generic_full_stack</verification_track>"
    "<capability_gap>cap:cpu_functional_oracle</capability_gap>"
    "<evidence>phase2/stage1/sim_full_stack/generic_full_stack_run/full_stack.log</evidence>"
    "<waiver_reason>class 'digital_arithmetic_primitive' — DEFERRED"
    "</waiver_reason></results>"
)


# ----- parse_junit --------------------------------------------------

def test_parse_junit_pass(tmp_path):
    p = tmp_path / "results.xml"
    p.write_text(_JUNIT_PASS)
    s = SRB.parse_junit(p)
    assert s == {"tests": 1, "failures": 0, "errors": 0, "skipped": 0,
                 "passed": 1}


def test_parse_junit_connectivity_bridge_is_none(tmp_path):
    # The <results><verdict> connectivity bridge is not JUnit — None.
    p = tmp_path / "results.xml"
    p.write_text(_CONNECTIVITY)
    assert SRB.parse_junit(p) is None


def test_parse_junit_missing_or_garbage_is_none(tmp_path):
    assert SRB.parse_junit(tmp_path / "nope.xml") is None
    bad = tmp_path / "bad.xml"
    bad.write_text("not xml <<<")
    assert SRB.parse_junit(bad) is None


# ----- find_professional_tb_pass ------------------------------------

def _plant(project: Path, xml: str, top: str = "spm") -> Path:
    d = project / "phase2" / "stage1" / "sim_professional" / top
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.xml").write_text(xml)
    return project


def test_find_professional_tb_pass_real(tmp_path):
    _plant(tmp_path, _JUNIT_PASS)
    got = SRB.find_professional_tb_pass(tmp_path)
    assert got is not None
    assert got["failures"] == 0 and got["tests"] == 1 and got["passed"] == 1
    assert got["rel_path"] == "phase2/stage1/sim_professional/spm/results.xml"


def test_find_professional_tb_pass_failing_is_none(tmp_path):
    _plant(tmp_path, _JUNIT_FAIL)
    assert SRB.find_professional_tb_pass(tmp_path) is None


def test_find_professional_tb_pass_vacuous_is_none(tmp_path):
    _plant(tmp_path, _JUNIT_VACUOUS)
    assert SRB.find_professional_tb_pass(tmp_path) is None


def test_find_professional_tb_pass_absent_is_none(tmp_path):
    assert SRB.find_professional_tb_pass(tmp_path) is None


# ----- waiver supersede ---------------------------------------------

def _plant_connectivity_bridge(project: Path):
    sim = project / "phase2" / "stage1" / "sim"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "results.xml").write_text(_CONNECTIVITY)
    ev = (project / "phase2" / "stage1" / "sim_full_stack"
          / "generic_full_stack_run")
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "full_stack.log").write_text("... FULL_STACK_TB_DONE ...\n")


def test_waiver_without_professional_tb_stays_waived(tmp_path):
    # No professional_tb → the honest connectivity waiver is issued (rc=3).
    _plant_connectivity_bridge(tmp_path)
    code, msg = W._evaluate(tmp_path)
    assert code == 3, msg
    assert "PASS_WITH_WAIVERS" in msg


def test_professional_tb_pass_supersedes_waiver(tmp_path):
    # Real professional_tb PASS → the waiver is superseded by a real functional
    # PASS (rc=0), so Step 4 is credited as a genuine functional PASS.
    _plant_connectivity_bridge(tmp_path)
    _plant(tmp_path, _JUNIT_PASS)
    code, msg = W._evaluate(tmp_path)
    assert code == 0, msg
    assert "ACHIEVED by the professional" in msg
    assert "SUPERSEDED" in msg


def test_forged_waiver_still_fails_even_without_professional(tmp_path):
    # Anti-fabrication intact: a connectivity waiver whose evidence transcript
    # never reached FULL_STACK_TB_DONE still FAILs (rc=1), professional absent.
    sim = tmp_path / "phase2" / "stage1" / "sim"
    sim.mkdir(parents=True, exist_ok=True)
    sim_res = _CONNECTIVITY  # evidence file will be empty/missing
    (sim / "results.xml").write_text(sim_res)
    ev = (tmp_path / "phase2" / "stage1" / "sim_full_stack"
          / "generic_full_stack_run")
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "full_stack.log").write_text("ran but no done marker\n")
    code, msg = W._evaluate(tmp_path)
    assert code == 1, msg


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
