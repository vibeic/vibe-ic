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

import pytest

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
    # The synthetic producer supplies placed conductor geometry separately,
    # as the real Step-25 OpenROAD producer does.
    if args and Path(args[0]).name == "em_segments.csv":
        geom = Path(args[0]).with_name("em_pg_geometry.tsv")
        if geom.is_file():
            cmd.extend(("--pg-geometry", str(geom)))
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
    geom = ("net\tlayer\tx0_um\ty0_um\tx1_um\ty1_um\tsource\n" +
            "".join(f"{net}\t{layer}\t0\t-0.07\t1\t0.07\tpg_port\n"
                    for net in ("unknown", "VPWR")
                    for layer in ("met1", "met2")))
    _write(tmp_path / "em_pg_geometry.tsv", geom)
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


@pytest.mark.parametrize("case,current,expected_rc", [
    ("forward", 6.2e-6, 0),
    ("reverse", 6.2e-6, 0),
    ("over_limit", 6.2e-5, 1),
    ("multiple_cuts_do_not_divide_current", 6.2e-5, 1),
    ("unknown_endpoint", 6.2e-5, 3),
    ("missing_via", 6.2e-5, 3),
    ("missing_cut_limit", 6.2e-5, 3),
    ("ambiguous_cut", 6.2e-5, 3),
    ("ambiguous_unlimited_cut", 6.2e-5, 3),
    ("stacked_via_is_not_one_cut", 6.2e-5, 3),
])
def test_psm_metal_endpoints_need_explicit_unique_cut_authority(
        tmp_path, case, current, expected_rc):
    # Source-control fixture: PSM's native grammar uses two metal endpoints,
    # while the authority publishes cut current per area on a third named layer.
    # The arbitrary names deliberately carry no inferable layer numbering.
    routing = """
LAYER lower
  TYPE ROUTING ;
  DCCURRENTDENSITY AVERAGE 0.67 ;
END lower
LAYER upper
  TYPE ROUTING ;
  DCCURRENTDENSITY AVERAGE 0.67 ;
END upper
"""
    cut = """
LAYER bridge
  TYPE CUT ;
  DCCURRENTDENSITY AVERAGE 0.18 ;
END bridge
"""
    via = """
VIA native_bridge DEFAULT
  LAYER lower ;
  RECT -0.19 -0.13 0.19 0.13 ;
  LAYER bridge ;
  RECT -0.13 -0.13 0.13 0.13 ;
  LAYER upper ;
  RECT -0.19 -0.14 0.19 0.14 ;
END native_bridge
"""
    if case == "missing_via":
        via = ""
    elif case == "missing_cut_limit":
        cut = cut.replace("  DCCURRENTDENSITY AVERAGE 0.18 ;\n", "")
    elif case.startswith("ambiguous"):
        other = cut.replace("bridge", "other_bridge")
        if case == "ambiguous_unlimited_cut":
            other = other.replace("  DCCURRENTDENSITY AVERAGE 0.18 ;\n", "")
        cut += other
        via += via.replace("native_bridge", "second_native_bridge").replace(
            "LAYER bridge", "LAYER other_bridge")
    elif case == "multiple_cuts_do_not_divide_current":
        via = via.replace("  LAYER upper ;", "  RECT 0.39 -0.13 0.65 0.13 ;\n  LAYER upper ;")
    elif case == "stacked_via_is_not_one_cut":
        routing += routing.split("LAYER upper", 1)[0].replace("lower", "third")
        cut += cut.replace("bridge", "second_bridge")
        via = via.replace("END native_bridge", "  LAYER second_bridge ;\n  RECT 0 0 0.26 0.26 ;\n  LAYER third ;\n  RECT 0 0 0.26 0.26 ;\nEND native_bridge")
    layer0, layer1 = (("upper", "lower") if case == "reverse"
                      else ("lower", "other") if case == "unknown_endpoint"
                      else ("lower", "upper"))
    sys.path.insert(0, str(PROG.parent))
    import em_current_density_check as E
    table = E.parse_lef_jmax(routing + cut + via)
    # The producer's native row binds this actual cross section. An array's
    # current is compared as I/area, never divided by an assumed cut count.
    segment = {"net": "VPWR", "layer0": layer0, "layer1": layer1,
               "current_A": current, "native_layer": "bridge",
               "native_area_um2": 0.0676, "native_cuts": 1}
    row = E._screen_segment(segment, table, 0.1, 2.0)
    expected = "unscreened" if expected_rc == 3 else "ok" if expected_rc == 0 else "offender"
    assert row["status"] == expected, row
    if expected_rc == 3:
        assert row["reason"] == "via_cut_layer_not_in_jmax_reference"
    else:
        assert row["layer"] == "bridge"
        assert row["basis"] == "areal"
        assert row["current_A"] == current
        assert row["cross_section_area_um2"] == pytest.approx(0.0676)
        assert row["limit"] == pytest.approx(0.18e-3)
        assert row["value"] == pytest.approx(current / 0.0676)


@pytest.mark.parametrize("authority,area,expected", [
    ("lef", 0.2028, "offender"),
    ("lef", None, "unscreened"),
    ("json_per_cut", None, "ok"),
])
def test_cut_scalar_area_units_differ_from_explicit_per_cut_json(authority, area, expected):
    sys.path.insert(0, str(PROG.parent))
    import em_current_density_check as E
    # Identical numeric scalars carry different dimensions; 62uA is above
    # .18mA/um^2 * .2028um^2, but below an explicit .18mA per-cut limit.
    table = (E.parse_lef_jmax("LAYER bridge\n TYPE CUT ;\n DCCURRENTDENSITY AVERAGE 0.18 ;\nEND bridge\n")
             if authority == "lef" else E.parse_json_jmax({"layers": {
                 "bridge": {"kind": "cut", "jmax_mA_per_cut": 0.18}}}))
    row = E._screen_segment({"net": "VPWR", "layer0": "lower", "layer1": "bridge",
                             "current_A": 6.2e-5, "native_layer": "bridge",
                             "native_area_um2": area, "native_cuts": 3}, table, 0.1, 2.0)
    assert row["status"] == expected, row
    if authority == "lef" and area:
        assert row["basis"] == "areal"
        assert row["density_A_per_um2"] == pytest.approx(6.2e-5 / area)
    elif authority == "json_per_cut":
        assert row["basis"] == "per_cut"
        assert row["limit_A_per_cut"] == pytest.approx(0.18e-3)


@pytest.mark.parametrize("damage,expected", [
    ("none", "PASS"), ("over_limit", "FAIL"),
    ("node", "NOT_MEASURED"), ("current", "NOT_MEASURED"),
    ("layer", "NOT_MEASURED"), ("area", "NOT_MEASURED"),
    ("no_limit", "NOT_MEASURED"), ("missing_row", "NOT_MEASURED"),
    ("bound_native_diagonal", "PASS"),
    ("rounded_native_diagonal", "PASS"),
    ("inconsistent_native_diagonal", "NOT_MEASURED"),
])
def test_native_cut_area_reaches_the_gate_only_on_the_same_bound_segment(
        tmp_path, monkeypatch, damage, expected):
    import em_current_density_check as E
    project = tmp_path / "project"
    rpt = project / "reports/phase3"
    rpt.mkdir(parents=True)
    tech = rpt / "native.tlef"
    tech.write_text("LAYER wireA\n TYPE ROUTING ;\n WIDTH 1 ;\n THICKNESS 1 ;\n DCCURRENTDENSITY AVERAGE 1 ;\nEND wireA\n"
                    "LAYER cutA\n TYPE CUT ;\n DCCURRENTDENSITY AVERAGE 0.18 ;\nEND cutA\n"
                    "LAYER wireB\n TYPE ROUTING ;\n THICKNESS 1 ;\n DCCURRENTDENSITY AVERAGE 1 ;\nEND wireB\n"
                    "VIA native_cut\n LAYER wireA ;\n RECT -0.2 -0.2 0.2 0.2 ;\n LAYER cutA ;\n RECT -0.13 -0.13 0.13 0.13 ;\n LAYER wireB ;\n RECT -0.2 -0.2 0.2 0.2 ;\nEND native_cut\n")
    (rpt / "em.json").write_text(json.dumps({"tool": "openroad-psm", "native_rc": 0,
        "verdict": "MEASURED", "nets_analysed": ["PWR"]}))
    (rpt / "em_openroad_density.json").write_text(json.dumps({"verdict": "MEASURED",
        "execution": {"native_rc": 0}, "authority": {"snapshot": str(tech)},
        "pdk": {"name": "neutral"}, "power_basis": {"complete": True}, "nets": {"PWR": {}}}))
    header = "Node0 Layer,Node0 X location,Node0 Y location,Node1 Layer,Node1 X location,Node1 Y location,Current\n"
    density_header = "Layer,Node0 X,Node0 Y,Node1 X,Node1 Y,Current(A),Area(um^2),J(A/um^2),Jlimit(A/um^2),Ratio,Status,Cuts,Basis\n"
    current = 6.2e-5 if damage == "over_limit" else 1e-6
    area = 0.2028
    psm_rows = ["wireA,0,0,wireA,1,0,0.000001", f"wireA,0,0,wireB,0,0,{current}"]
    row = ["cutA", "0", "0", "0", "0", str(current), str(area), str(current / area),
           str(0.18e-3 * 0.9), str(current / area / (0.18e-3 * 0.9)),
           "VIOLATED" if damage == "over_limit" else "OK", "3", "AREAL"]
    if damage == "node": row[1] = "1"
    if damage == "current": row[5] = str(current * 2)
    if damage == "layer": row[0] = "wireA"
    if damage == "area": row[6] = "0"
    if damage == "no_limit": row[8:11] = ["0", "0", "NO_LIMIT"]; row[12] = "NO_LIMIT"
    density_rows = ["wireA,0,0,1,0,0.000001,1,0.000001,0.0009,0.001111111,OK,0,AREAL"]
    if damage != "missing_row": density_rows.append(",".join(row))
    if damage.endswith("native_diagonal"):
        i, a, j = (("1.374e-10", "1.2420e-1", "1.107e-9")
                   if damage != "bound_native_diagonal" else ("0.000001", "1", "0.000001"))
        if damage == "inconsistent_native_diagonal": j = "1.300e-9"
        psm_rows = [f"wireA,0,0,wireA,1,1,{i}"]
        density_rows = [f"wireA,0,0,1,1,{i},{a},{j},0.0009,{float(j) / 0.0009},OK,0,AREAL"]
    (rpt / "em_segments_PWR.csv").write_text(header + "\n".join(psm_rows) + "\n")
    (rpt / "em_segments.csv").write_text("Net," + header + "\n".join("PWR," + row for row in psm_rows) + "\n")
    (rpt / "em_openroad_density_PWR.csv").write_text(density_header + "\n".join(density_rows) + "\n")
    geometry = rpt / "em_pg_geometry.tsv"
    geometry.write_text("net\tlayer\tx0_um\ty0_um\tx1_um\ty1_um\tsource\nPWR\twireA\t0\t-0.5\t2\t0.5\tspecial_wire\n")
    verdict, report = E.evaluate(rpt / "em_segments.csv", None, None, 0.1, 2.0, None, 20,
                                 pg_geometry_path=geometry)
    assert verdict == expected, report
    assert report["pass"] is (expected == "PASS")
    if expected == "PASS":
        assert report["summary"]["segments_screened"] == (1 if damage.endswith("native_diagonal") else 2)
        assert report["summary"]["segments_unscreened"] == 0
        if damage.endswith("native_diagonal"):
            assert report["worst_segments"][0]["width_source"] == "bound_native_current_density"
    if expected == "FAIL":
        assert report["offender_count"] == 1
        assert report["offenders"][0]["layer"] == "cutA"
        assert report["offenders"][0]["cross_section_area_um2"] == pytest.approx(area)
