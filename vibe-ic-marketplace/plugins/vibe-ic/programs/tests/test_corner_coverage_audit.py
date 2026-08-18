#!/usr/bin/env python3
"""Unit tests for corner_coverage_audit.py"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import corner_coverage_audit as cca


def run_cli(tmp_path, files_dict):
    proj = tmp_path / "project"
    proj.mkdir(parents=True, exist_ok=True)
    for name, content in files_dict.items():
        p = proj / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable,
           str(Path(__file__).resolve().parent.parent / "corner_coverage_audit.py"),
           "--project-dir", str(proj), "--out-dir", str(out)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    report_file = out / "corner_coverage_audit_report.json"
    report = json.loads(report_file.read_text()) if report_file.exists() else None
    return res, report


class TestTTOnly:
    def test_tt_only_warns(self, tmp_path):
        files = {"synth.log": "read_liberty /pdk/gf180mcu__tt_1p80v_25c.lib\n"}
        res, report = run_cli(tmp_path, files)
        assert report is not None
        assert report["coverage_level"] == "MINIMAL"
        assert report["verdict"] == "WARNING"


class TestBasicCoverage:
    def test_ss_tt_ff_passes(self, tmp_path):
        files = {
            "libs/ss_0p72v_125c.lib": "library(ss) {}",
            "libs/tt_0p80v_25c.lib": "library(tt) {}",
            "libs/ff_0p88v_m40c.lib": "library(ff) {}",
        }
        res, report = run_cli(tmp_path, files)
        assert report is not None
        assert report["coverage_level"] in ("BASIC", "FULL")
        assert report["verdict"] == "PASS"
        procs = report["process_corners"]
        assert "SS" in procs and "TT" in procs and "FF" in procs


class TestFullPVT:
    def test_full_pvt_matrix(self, tmp_path):
        files = {}
        for proc in ("ss", "tt", "ff"):
            for volt in ("0p72v", "0p80v", "0p88v"):
                for temp in ("m40c", "25c", "125c"):
                    name = f"libs/{proc}_{volt}_{temp}.lib"
                    files[name] = f"library({proc}_{volt}_{temp}) {{}}"
        res, report = run_cli(tmp_path, files)
        assert report is not None
        assert report["coverage_level"] == "FULL"
        assert report["verdict"] == "PASS"


class TestNoFiles:
    def test_empty_project(self, tmp_path):
        files = {"readme.md": "nothing here"}
        res, report = run_cli(tmp_path, files)
        assert report is not None
        assert report["coverage_level"] == "NONE"


class TestSKY130Naming:
    def test_sky130_lib_names(self, tmp_path):
        files = {
            "sky130_fd_sc_hd__ss_100C_1v60.lib": "library(sky130_ss) {}",
            "sky130_fd_sc_hd__tt_025C_1v80.lib": "library(sky130_tt) {}",
            "sky130_fd_sc_hd__ff_n40C_1v95.lib": "library(sky130_ff) {}",
        }
        res, report = run_cli(tmp_path, files)
        assert report is not None
        procs = report["process_corners"]
        assert "SS" in procs and "FF" in procs


class TestSTAReport:
    def test_sta_report_corners(self, tmp_path):
        files = {
            "reports/sta_ss_setup.rpt": "Corner: ss_0p72v_125c\nWNS: -0.050\n",
            "reports/sta_ff_hold.rpt": "Corner: ff_0p88v_m40c\nWNS: 0.100\n",
        }
        res, report = run_cli(tmp_path, files)
        assert report is not None
        procs = report["process_corners"]
        assert "SS" in procs and "FF" in procs


class TestSDCMultiCorner:
    def test_sdc_mcmm(self, tmp_path):
        files = {
            "constraints/top.sdc": (
                "create_corner ss_corner\n"
                "create_corner tt_corner\n"
                "create_corner ff_corner\n"
            ),
        }
        res, report = run_cli(tmp_path, files)
        assert report is not None
        procs = report["process_corners"]
        assert "SS" in procs and "TT" in procs and "FF" in procs


class TestCornerExtraction:
    def test_gf180_filename(self):
        evs = cca.extract_corner_from_string(
            "gf180mcu_fd_sc_mcu7t5v0__ss_1p62v_125c.lib",
            "liberty_filename", "test.lib")
        assert len(evs) >= 1
        assert evs[0].process == "SS"

    def test_tt_only(self):
        evs = cca.extract_corner_from_string(
            "typical_1p80v_25c.lib", "liberty_filename", "test.lib")
        assert len(evs) >= 1
        assert evs[0].process == "TT"

    def test_no_corner(self):
        evs = cca.extract_corner_from_string(
            "readme.md", "other", "readme.md")
        assert len(evs) == 0


class TestNormalization:
    def test_voltage(self):
        assert cca.normalize_voltage("0p72") == "0.72V"
        assert cca.normalize_voltage("1p8") == "1.80V"

    def test_temperature(self):
        assert cca.normalize_temperature("m40") == "-40C"
        assert cca.normalize_temperature("125") == "125C"


class TestReturnCodes:
    def test_warning_returns_one(self, tmp_path):
        files = {"synth.log": "read_liberty tt_lib.lib\n"}
        res, _ = run_cli(tmp_path, files)
        assert res.returncode == 1

    def test_pass_returns_zero(self, tmp_path):
        files = {
            "libs/ss.lib": "library(ss) {}",
            "libs/tt.lib": "library(tt) {}",
            "libs/ff.lib": "library(ff) {}",
        }
        res, _ = run_cli(tmp_path, files)
        assert res.returncode == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
