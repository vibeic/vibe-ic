"""Unit tests for analog_liberty_nonzero_delay_check.py.

Pins the deterministic Liberty non-degeneracy gate extracted from the
analog-hardmacro-gen "Do not generate Liberty with zero delays" rule.
Covers PASS (real non-zero timing), FAIL (area-only stub / all-zero /
missing / garbage), and the honest SKIP edge (no analog blocks).
"""
import importlib
import json

import pytest

mod = importlib.import_module("analog_liberty_nonzero_delay_check")


# --------------------------------------------------------------------------
# Pure analyzer unit tests
# --------------------------------------------------------------------------

LIB_REAL = """library(ldo_lib) {
  cell(ldo) {
    area : 10000 ;
    pin(vout) {
      timing() {
        related_pin : "en" ;
        cell_rise(scalar) { values("0.42"); }
        cell_fall(scalar) { values("0.51"); }
      }
    }
    cell_leakage_power : 0.0031 ;
  }
}"""

LIB_AREA_ONLY = """library(ldo_stub) {
  cell(ldo) {
    area : 10000 ;
  }
}"""

LIB_ALL_ZERO = """library(ldo_lib) {
  cell(ldo) {
    pin(vout) {
      timing() {
        cell_rise(scalar) { values("0.0"); }
        cell_fall(scalar) { values("0"); }
      }
    }
    cell_leakage_power : 0.0 ;
  }
}"""


class TestAnalyzer:
    def test_real_has_nonzero(self):
        has_timing, values, cell = mod.analyze_liberty(LIB_REAL)
        assert has_timing is True
        assert cell == "ldo"
        assert any(v != 0.0 for v in values)
        assert 0.42 in values and 0.51 in values

    def test_area_only_has_no_timing(self):
        has_timing, values, cell = mod.analyze_liberty(LIB_AREA_ONLY)
        assert has_timing is False
        assert values == []
        assert cell == "ldo"

    def test_all_zero_detected(self):
        has_timing, values, cell = mod.analyze_liberty(LIB_ALL_ZERO)
        assert has_timing is True
        assert all(v == 0.0 for v in values)


# --------------------------------------------------------------------------
# End-to-end fixtures
# --------------------------------------------------------------------------

def _mk(root, block, lib_text=None, corner=None, spec=True):
    a = root / "phase3" / "analog" / block
    a.mkdir(parents=True, exist_ok=True)
    if spec:
        (a / "spec.json").write_text(json.dumps({"block": block}))
    if corner is not None:
        (a / "corner_results.json").write_text(json.dumps(corner))
    if lib_text is not None:
        h = root / "phase3" / "analog" / "hardmacro" / block
        h.mkdir(parents=True, exist_ok=True)
        (h / f"{block}.lib").write_text(lib_text)


def test_pass_real_liberty(tmp_path):
    _mk(tmp_path, "ldo", LIB_REAL, corner={"_provenance": "real_ngspice"})
    res = mod.run_audit(tmp_path)
    assert res.passed is True
    assert "ldo" in res.summary["passed_blocks"]


def test_fail_area_only_stub(tmp_path):
    # The real A7 stub: area-only -> zero-delay defect -> FAIL.
    _mk(tmp_path, "ldo", LIB_AREA_ONLY)
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LIB_NO_TIMING" in {f.rule for f in res.findings}


def test_fail_all_zero_delay(tmp_path):
    _mk(tmp_path, "ldo", LIB_ALL_ZERO)
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LIB_ZERO_DELAY" in {f.rule for f in res.findings}


def test_fail_missing_lib(tmp_path):
    _mk(tmp_path, "ldo", lib_text=None)
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LIB_MISSING" in {f.rule for f in res.findings}


def test_fail_no_cell(tmp_path):
    _mk(tmp_path, "ldo", "library(x) {\n  /* no cell */\n}")
    res = mod.run_audit(tmp_path)
    assert res.passed is False
    assert "LIB_NO_CELL" in {f.rule for f in res.findings}


def test_skip_no_analog(tmp_path):
    res = mod.run_audit(tmp_path)
    assert res.passed is True
    assert res.summary.get("skipped") is True


def test_provenance_reported(tmp_path):
    _mk(tmp_path, "ldo", LIB_REAL, corner={"_provenance": "real_ngspice"})
    res = mod.run_audit(tmp_path)
    ok = [f for f in res.findings if f.rule == "LIB_NONZERO_OK"]
    assert ok and "real_ngspice" in ok[0].message


def test_main_cli_fail_exit_1(tmp_path):
    _mk(tmp_path, "ldo", LIB_AREA_ONLY)
    out = tmp_path / "rep.json"
    rc = mod.main([str(tmp_path), "--json", str(out)])
    assert rc == 1
    rep = json.loads(out.read_text())
    assert rep["passed"] is False


def test_main_cli_not_a_dir(tmp_path):
    rc = mod.main([str(tmp_path / "nope")])
    assert rc == 2
