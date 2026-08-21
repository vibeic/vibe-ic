#!/usr/bin/env python3
"""Tests for em_current_density_check.py — REAL EM current-density sign-off.

Covers the four required cases:
  (a) synthetic EM report all under Jmax               → PASS
  (b) one segment over Jmax                            → FAIL (names net/layer/
                                                          density-vs-limit)
  (c) absent EM report                                 → SKIPPED, never PASS
  (d) absent Jmax table                                → SKIPPED, never PASS

Plus the tech-LEF Jmax path and the "report present but nothing maps to a
Jmax layer" §4.05 negative. rc contract: 0 PASS / 1 FAIL / 2 arg / 3 SKIPPED.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "em_current_density_check.py"

# A per-width Jmax of 2.8 mA/um on met1 (t=0.35um) mirrors sky130 metal.
JMAX = {
    "layers": {
        "met1": {"kind": "routing", "thickness_um": 0.35, "width_um": 0.14,
                 "jmax_mA_per_um": 2.8},
        "met2": {"kind": "routing", "thickness_um": 0.35, "width_um": 0.14,
                 "jmax_A_per_um2": 8.0e-3},
        "via1": {"kind": "cut", "jmax_mA_per_cut": 0.29},
    }
}

# sky130-style tech-LEF fragment (routing + cut layers with DCCURRENTDENSITY).
TECH_LEF = """
LAYER met1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  WIDTH 0.14 ;
  THICKNESS 0.35 ;
  DCCURRENTDENSITY AVERAGE 2.8 ; # mA/um Iavg_max
END met1

LAYER via1
  TYPE CUT ;
  DCCURRENTDENSITY AVERAGE 0.29 ; # mA per via
END via1
"""

CSV_HEADER = ("Node0 Layer,Node0 X location,Node0 Y location,"
              "Node1 Layer,Node1 X location,Node1 Y location,Current\n")


def _run(*args) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), *[str(a) for a in args]]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


def _jmax(tmp_path) -> Path:
    return _write(tmp_path / "jmax.json", JMAX)


def _csv(tmp_path, rows) -> Path:
    body = CSV_HEADER + "".join(
        f"{l},0,0,{l},1,0,{c}\n" for (l, c) in rows)
    return _write(tmp_path / "em_segments.csv", body)


# --------------------------------------------------------------- (a) PASS

def test_all_under_jmax_pass(tmp_path):
    # met1 Jmax per-width = 2.8mA/um = 2.8e-3 A/um. width=0.14um →
    # limit current ~= 3.92e-4 A. Currents here are ~1e-5 A → far under.
    csv = _csv(tmp_path, [("met1", 1.0e-5), ("met1", 3.0e-5), ("met2", 2.0e-5)])
    r = _run(csv, "--jmax", _jmax(tmp_path), "--json", tmp_path / "o.json")
    assert r.returncode == 0, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "PASS"
    assert rep["pass"] is True
    assert rep["summary"]["segments_screened"] == 3
    assert rep["summary"]["worst_case_lifetime_ratio"] is not None


def test_all_under_jmax_pass_via_tech_lef(tmp_path):
    csv = _csv(tmp_path, [("met1", 1.0e-5), ("met1", 2.0e-5)])
    lef = _write(tmp_path / "tech.lef", TECH_LEF)
    r = _run(csv, "--tech-lef", lef, "--json", tmp_path / "o.json")
    assert r.returncode == 0, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "PASS"
    assert "met1" in rep["summary"]["jmax_layers"]


# --------------------------------------------------------------- (b) FAIL

def test_one_segment_over_jmax_fail(tmp_path):
    # met1 limit current ≈ 2.8e-3 * 0.14 = 3.92e-4 A. 5e-4 A is over.
    csv = _csv(tmp_path, [("met1", 1.0e-5), ("met1", 5.0e-4), ("met2", 2.0e-5)])
    r = _run(csv, "--jmax", _jmax(tmp_path), "--net", "VPWR",
             "--json", tmp_path / "o.json")
    assert r.returncode == 1, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["pass"] is False
    assert rep["offender_count"] >= 1
    off = rep["offenders"][0]
    # must name net + layer + density-vs-limit
    assert off["net"] == "VPWR"
    assert off["layer"] == "met1"
    assert off["utilization"] >= (1.0 - rep["margin"])
    assert off["limit"] > 0 and off["value"] >= off["limit"] * (1.0 - rep["margin"])
    msg = " ".join(f["message"] for f in rep["findings"]
                   if f["rule"] == "EM_CURRENT_DENSITY_OVER_JMAX")
    assert "met1" in msg and "VPWR" in msg and "Jmax" in msg


# ------------------------------------------- (c) §4.05: absent EM report

def test_absent_em_report_skipped_not_pass(tmp_path):
    missing = tmp_path / "does_not_exist"  # nothing discovered
    r = _run(missing, "--jmax", _jmax(tmp_path), "--json", tmp_path / "o.json")
    assert r.returncode == 3, r.stdout          # SKIPPED, never PASS
    assert r.returncode != 0
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "SKIPPED"
    assert rep["pass"] is False
    assert rep["skip_reason"] == "em_report_absent"


def test_empty_dir_em_report_skipped(tmp_path):
    empty = tmp_path / "reports"
    empty.mkdir()
    r = _run(empty, "--jmax", _jmax(tmp_path))
    assert r.returncode == 3, r.stdout
    assert '"verdict": "SKIPPED"' in r.stdout
    assert '"pass": false' in r.stdout


# ------------------------------------------- (d) §4.05: absent Jmax table

def test_absent_jmax_table_skipped_not_pass(tmp_path):
    csv = _csv(tmp_path, [("met1", 1.0e-5)])   # a real, all-under report
    r = _run(csv, "--json", tmp_path / "o.json")  # NO --jmax / --tech-lef
    assert r.returncode == 3, r.stdout          # SKIPPED (no reference), not PASS
    assert r.returncode != 0
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "SKIPPED"
    assert rep["pass"] is False
    assert rep["skip_reason"] == "jmax_reference_absent"


def test_jmax_path_missing_file_skipped(tmp_path):
    csv = _csv(tmp_path, [("met1", 1.0e-5)])
    r = _run(csv, "--jmax", tmp_path / "nope.json")
    assert r.returncode == 3, r.stdout
    assert '"verdict": "SKIPPED"' in r.stdout


def test_lef_without_current_density_skipped(tmp_path):
    csv = _csv(tmp_path, [("met1", 1.0e-5)])
    lef = _write(tmp_path / "bare.lef",
                 "LAYER met1\n  TYPE ROUTING ;\n  WIDTH 0.14 ;\nEND met1\n")
    r = _run(csv, "--tech-lef", lef)
    assert r.returncode == 3, r.stdout   # no DCCURRENTDENSITY → no reference


# --------------------------- §4.05: report+jmax present but nothing maps

def test_report_present_but_no_layer_match_skipped(tmp_path):
    # Segments only on met9, Jmax only knows met1/met2/via1 → cannot judge.
    csv = _csv(tmp_path, [("met9", 1.0e-5), ("met9", 2.0e-5)])
    r = _run(csv, "--jmax", _jmax(tmp_path), "--json", tmp_path / "o.json")
    assert r.returncode == 3, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "SKIPPED"
    assert rep["pass"] is False
    assert rep["skip_reason"] == "no_segment_maps_to_jmax_reference"


# --------------------------- extra: via/cut per-cut screening + JSON input

def test_via_cut_over_limit_fail_json_segments(tmp_path):
    # via1 per-cut limit = 0.29mA = 2.9e-4 A; 4e-4 A over.
    seg = _write(tmp_path / "em.json", {
        "power_nets": ["VPWR"],
        "segments": [
            {"net": "VPWR", "layer0": "met1", "layer1": "via1",
             "current_A": 4.0e-4},
        ],
    })
    r = _run(seg, "--jmax", _jmax(tmp_path), "--json", tmp_path / "o.json")
    assert r.returncode == 1, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["offenders"][0]["basis"] == "per_cut"


def test_margin_makes_marginal_segment_fail(tmp_path):
    # Choose a current at ~85% of Jmax; margin 0.2 requires <80% → FAIL.
    # met1 limit current = 2.8e-3 * 0.14 = 3.92e-4 A; 85% = 3.332e-4 A.
    csv = _csv(tmp_path, [("met1", 3.332e-4)])
    r = _run(csv, "--jmax", _jmax(tmp_path), "--margin", "0.2",
             "--json", tmp_path / "o.json")
    assert r.returncode == 1, r.stdout
    rep = json.loads((tmp_path / "o.json").read_text())
    assert rep["verdict"] == "FAIL"
    # same segment PASSES with margin 0.0 (still strictly under Jmax)
    r2 = _run(csv, "--jmax", _jmax(tmp_path), "--margin", "0.0")
    assert r2.returncode == 0, r2.stdout


def test_bad_margin_arg_error(tmp_path):
    csv = _csv(tmp_path, [("met1", 1.0e-5)])
    r = _run(csv, "--jmax", _jmax(tmp_path), "--margin", "1.5")
    assert r.returncode == 2
