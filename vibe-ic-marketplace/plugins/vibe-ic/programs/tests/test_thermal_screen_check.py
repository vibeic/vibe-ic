#!/usr/bin/env python3
"""Tests for thermal_screen_check.py — power-density / Tj thermal screen.

Covers PASS (under limit), FAIL (over power-density limit; over Tj_max via
report and via θ_ja estimate), and the honest SKIP edges: absent /
not_computed / no-value power report, absent / degenerate die area, bad
JSON. Exit codes: 0 PASS / 1 FAIL / 2 IO-or-arg / 3 SKIP.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "thermal_screen_check.py"


def _run(*args) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), *[str(a) for a in args]]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


# ----------------------------------------------------------------- PASS

def test_pass_under_limit_json(tmp_path):
    rpt = _write(tmp_path / "power.json", {"total_power_w": 0.05})
    r = _run(rpt, "--die-area-mm2", "1.0", "--json", tmp_path / "out.json")
    assert r.returncode == 0
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["verdict"] == "PASS"
    assert rep["measured"]["power_density_w_per_mm2"] == 0.05


def test_pass_dynamic_plus_leakage_sum(tmp_path):
    rpt = _write(tmp_path / "power.json",
                 {"dynamic_power_w": 0.03, "leakage_power_w": 0.001})
    r = _run(rpt, "--die-area-mm2", "1.0")
    assert r.returncode == 0
    rep = json.loads(r.stdout)
    assert abs(rep["measured"]["total_power_w"] - 0.031) < 1e-9
    assert rep["measured"]["power_provenance"] == "dynamic_plus_leakage_sum"


def test_pass_die_area_from_def(tmp_path):
    # 1000um x 1000um at 1000 dbu/um = 1.0 mm^2
    _write(tmp_path / "fp.def",
           "UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 1000000 1000000 ) ;\n")
    rpt = _write(tmp_path / "power.json", {"total_power_w": 0.2})
    r = _run(rpt, "--die-source", tmp_path / "fp.def")
    assert r.returncode == 0
    rep = json.loads(r.stdout)
    assert rep["measured"]["die_area_mm2"] == 1.0
    assert rep["measured"]["power_density_w_per_mm2"] == 0.2


def test_pass_openroad_report_power_text(tmp_path):
    rpt = _write(tmp_path / "power.rpt",
                 "Group        Internal Switching Leakage    Total\n"
                 "Sequential   1.2e-03  4.5e-04   2.1e-08   1.6e-03  23.5%\n"
                 "Total        5.1e-03  1.7e-03   7.2e-08   6.8e-03 100.0%\n")
    r = _run(rpt, "--die-area-mm2", "0.02")
    assert r.returncode == 0
    rep = json.loads(r.stdout)
    # 6.8e-03 total, NOT the 100.0 percentage.
    assert abs(rep["measured"]["total_power_w"] - 6.8e-03) < 1e-9


def test_pass_tj_from_report_under_max(tmp_path):
    rpt = _write(tmp_path / "power.json",
                 {"total_power_w": 0.1, "tj_c": 85.0})
    r = _run(rpt, "--die-area-mm2", "1.0")
    assert r.returncode == 0
    assert json.loads(r.stdout)["measured"]["tj_c"] == 85.0


def test_pass_directory_discovery(tmp_path):
    _write(tmp_path / "reports" / "phase3" / "power.rpt",
           "Total Power = 5 mW\n")
    _write(tmp_path / "reports" / "phase3" / "floorplan.def",
           "UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 500000 500000 ) ;\n")
    # dir discovery finds power.rpt AND the DEF under the same dir.
    r = _run(tmp_path / "reports" / "phase3")
    assert r.returncode == 0


# ----------------------------------------------------------------- FAIL

def test_fail_over_power_density(tmp_path):
    rpt = _write(tmp_path / "power.json", {"total_power_w": 2.0})
    r = _run(rpt, "--die-area-mm2", "1.0")   # 2 W/mm^2 >= 1.0
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "FAIL"
    assert any("HOTSPOT power density" in f["message"] for f in rep["findings"])


def test_fail_tight_custom_limit(tmp_path):
    rpt = _write(tmp_path / "power.json", {"total_power_w": 0.3})
    assert _run(rpt, "--die-area-mm2", "1.0").returncode == 0            # 0.3 < 1.0
    assert _run(rpt, "--die-area-mm2", "1.0",
                "--limit-w-per-mm2", "0.2").returncode == 1              # 0.3 >= 0.2


def test_fail_tj_from_report_over_max(tmp_path):
    rpt = _write(tmp_path / "power.json",
                 {"total_power_w": 0.05, "junction_temp_c": 140.0})
    r = _run(rpt, "--die-area-mm2", "1.0")   # density ok, Tj 140 >= 125
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert any("junction temperature" in f["message"] for f in rep["findings"])


def test_fail_tj_estimate_from_theta_ja(tmp_path):
    # Tj = 25 + 0.5W * 250 C/W = 150 C >= 125
    rpt = _write(tmp_path / "power.json", {"total_power_w": 0.5})
    r = _run(rpt, "--die-area-mm2", "10", "--theta-ja", "250", "--ambient", "25")
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert rep["measured"]["tj_c"] == 150.0
    assert "estimate" in rep["measured"]["tj_provenance"]


# --------------------------------------------------- HONEST SKIP / §4.05

def test_skip_power_not_computed(tmp_path):
    """Open-PDK power_report_gen fallback with not_computed → SKIP, not PASS."""
    rpt = _write(tmp_path / "power.rpt",
                 "# Total Power: not_computed\n# Leakage Power: not_computed\n")
    r = _run(rpt, "--die-area-mm2", "1.0")
    assert r.returncode == 3
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "SKIP"
    assert rep["skip_reason"] == "power_not_computed"


def test_skip_no_die_area(tmp_path):
    rpt = _write(tmp_path / "power.json", {"total_power_w": 0.1})
    r = _run(rpt)                       # no die source at all
    assert r.returncode == 3
    assert json.loads(r.stdout)["skip_reason"] == "no_die_area"


def test_skip_degenerate_die_area(tmp_path):
    _write(tmp_path / "fp.def",
           "UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 0 0 ) ;\n")
    rpt = _write(tmp_path / "power.json", {"total_power_w": 0.1})
    r = _run(rpt, "--die-source", tmp_path / "fp.def")
    assert r.returncode == 3
    assert json.loads(r.stdout)["skip_reason"] == "degenerate_die_area"


def test_skip_absent_power_report_in_dir(tmp_path):
    (tmp_path / "reports").mkdir()
    _write(tmp_path / "reports" / "drc.rpt", "0 violations\n")
    r = _run(tmp_path)
    assert r.returncode == 3
    assert json.loads(r.stdout)["skip_reason"] == "power_report_absent"


def test_skip_bad_json(tmp_path):
    rpt = _write(tmp_path / "power.json", "{not valid,,,}")
    r = _run(rpt, "--die-area-mm2", "1.0")
    assert r.returncode == 3
    assert json.loads(r.stdout)["skip_reason"] == "power_report_bad_json"


def test_skip_never_conflated_with_pass(tmp_path):
    """A SKIP verdict never carries rc 0 — the §4.05 anti-vacuous-pass rule."""
    rpt = _write(tmp_path / "power.json", {"total_power_w": 0.001})
    r = _run(rpt)                       # missing die area → SKIP, not PASS
    assert r.returncode == 3
    assert json.loads(r.stdout)["verdict"] == "SKIP"


# ------------------------------------------------------------ IO / arg (rc 2)

def test_exit2_missing_power_path(tmp_path):
    assert _run(tmp_path / "nope.json", "--die-area-mm2", "1").returncode == 2


def test_exit2_bad_limit(tmp_path):
    rpt = _write(tmp_path / "power.json", {"total_power_w": 0.1})
    assert _run(rpt, "--die-area-mm2", "1",
                "--limit-w-per-mm2", "0").returncode == 2


def test_exit2_missing_die_source(tmp_path):
    rpt = _write(tmp_path / "power.json", {"total_power_w": 0.1})
    assert _run(rpt, "--die-source", tmp_path / "nope.def").returncode == 2
