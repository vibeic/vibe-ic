"""tests/test_analog_oracle_compare.py — v1.6.604

Deterministic regression tests for `programs/analog_oracle_compare.py`.

The comparator is the user-asked-for "make analog result deterministic"
gate: given Plugin-emitted `analog/<block>/{spec.json, topology.md,
*.sp, corner_results.json}` + an oracle spec table extracted from the
reference, the program emits a per-block + overall PASS /
PASS_WITH_NOTES / FAIL verdict. Re-running on the same artefacts MUST
yield byte-identical output.

These tests cover:
* numeric tolerance band (rel_pct + abs_floor)
* topology Jaccard threshold
* netlist device-count + subckt-name match
* A4 corner sweep vs oracle vout target
* GDS file-exists sanity
* per-block + overall verdict roll-up
* determinism (two runs = identical JSON)

Chip-AGNOSTIC. All fixtures are minimal synthetic JSON / SPICE / md
shapes — no chip-class literal anywhere.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
PLUGIN_ROOT = _HERE.parents[2]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

comp = importlib.import_module("programs.analog_oracle_compare")


# ---------------------------------------------------------------------------
# numeric tolerance — _cmp_numeric
# ---------------------------------------------------------------------------

def test_cmp_numeric_within_rel_pct_passes():
    tol = {"rel_pct": 5.0, "abs_floor": 0.0}
    r = comp._cmp_numeric("vout_target", 1.80, 1.78, tol)
    assert r.verdict == "PASS"
    assert r.delta_pct is not None and r.delta_pct < 2.0


def test_cmp_numeric_outside_rel_pct_fails():
    tol = {"rel_pct": 5.0, "abs_floor": 0.0}
    r = comp._cmp_numeric("vout_target", 1.80, 2.50, tol)
    assert r.verdict == "FAIL"
    assert r.delta_pct is not None and r.delta_pct > 25.0


def test_cmp_numeric_abs_floor_rescues_small_absolute_diff():
    """Even with a big rel_pct on a small oracle target, the
    abs_floor rule should rescue absolute differences below the
    floor."""
    tol = {"rel_pct": 5.0, "abs_floor": 1.0}
    # Plugin=10, oracle=1, abs_diff=9 — rel_pct=900% (fails), but
    # abs_floor=1 also fails. PASS only when abs_diff<=floor OR
    # rel_pct ok.
    r = comp._cmp_numeric("iq", 1.5, 1.0, tol)  # abs_diff=0.5 <= 1.0
    assert r.verdict == "PASS"


def test_cmp_numeric_missing_oracle_skips():
    r = comp._cmp_numeric("psrr", 80.0, None,
                          {"rel_pct": 30.0, "abs_floor": 0.0})
    assert r.verdict == "SKIP_MISSING_ORACLE"


def test_cmp_numeric_missing_plugin_skips():
    r = comp._cmp_numeric("psrr", None, 80.0,
                          {"rel_pct": 30.0, "abs_floor": 0.0})
    assert r.verdict == "SKIP_MISSING_PLUGIN"


# ---------------------------------------------------------------------------
# topology — Jaccard
# ---------------------------------------------------------------------------

def test_topology_full_overlap_passes():
    plugin_md = ("LDO topology: pmos pass device + error_amp + "
                 "feedback_divider + compensation cap.")
    tol = {"topology_jaccard_min": 0.5}
    r = comp._compare_topology(
        plugin_md,
        {"device_classes": ["pfet", "error_amp",
                            "feedback_divider", "compensation",
                            "cap"]},
        tol)
    assert r["verdict"] == "PASS"
    assert r["jaccard"] >= 0.5


def test_topology_no_overlap_fails():
    plugin_md = "schmitt trigger inverter + RC delay"
    r = comp._compare_topology(
        plugin_md,
        {"device_classes": ["error_amp", "pass_device",
                            "feedback_divider"]},
        {"topology_jaccard_min": 0.5})
    assert r["verdict"] == "FAIL"


def test_topology_missing_oracle_skips():
    r = comp._compare_topology("pmos amp",
                               {"device_classes": []},
                               {"topology_jaccard_min": 0.5})
    assert r["verdict"] == "SKIP_MISSING_ORACLE"


# ---------------------------------------------------------------------------
# netlist — device counts + subckt
# ---------------------------------------------------------------------------

_SP_FIXTURE_LDO = """\
* synthetic LDO subckt
.subckt user_ldo vdd vss vin vout en
Mp0 vout vmid vdd vdd pfet w=20u l=0.5u
Mp1 vmid en vdd vdd pfet w=4u l=0.5u
Mn0 vmid vfb vss vss nfet w=2u l=0.5u
Mn1 vfb vfb vss vss nfet w=2u l=0.5u
R0 vout vfb 10k
R1 vfb vss 10k
C0 vmid vss 5p
.ends
"""


def test_netlist_counts_match_oracle_passes():
    oracle_net = {
        "top_module_name": "user_ldo",
        "total_devices": 7,
        "by_class": {"pfet": 2, "nfet": 2, "res": 2, "cap": 1},
    }
    r = comp._compare_netlist(
        _SP_FIXTURE_LDO, oracle_net,
        {"netlist_per_class_pct": 60.0,
         "netlist_per_class_floor": 2,
         "netlist_total_pct": 50.0})
    assert r["verdict"] in ("PASS", "PASS_WITH_NOTES")
    assert r["plugin_total"] == 7
    assert r["subckt_match"] is True


def test_netlist_count_mismatch_fails():
    oracle_net = {
        "top_module_name": "different_subckt",
        "total_devices": 50,
        "by_class": {"pfet": 20, "nfet": 20, "res": 5, "cap": 5},
    }
    r = comp._compare_netlist(
        _SP_FIXTURE_LDO, oracle_net,
        {"netlist_per_class_pct": 20.0,
         "netlist_per_class_floor": 1,
         "netlist_total_pct": 20.0})
    assert r["verdict"] == "FAIL"


def test_netlist_missing_plugin_skips():
    r = comp._compare_netlist(
        "", {"top_module_name": "x",
             "total_devices": 5,
             "by_class": {"nfet": 5}},
        {"netlist_per_class_pct": 60.0,
         "netlist_per_class_floor": 2,
         "netlist_total_pct": 50.0})
    assert r["verdict"] == "SKIP_MISSING_PLUGIN"


# ---------------------------------------------------------------------------
# A4 corner sweep vs oracle target
# ---------------------------------------------------------------------------

def test_a4_corner_within_tolerance_passes():
    corner = {"corners": [{"vout": 1.79}, {"vout": 1.81},
                          {"vout": 1.80}]}
    r = comp._compare_a4(
        corner, {"vout_target": 1.80},
        {"vout_target": {"rel_pct": 5.0, "abs_floor": 0.05}})
    assert r["verdict"] == "PASS"
    assert r["pass_corners"] == 3 and r["fail_corners"] == 0


def test_a4_mixed_corners_yields_pass_with_notes():
    corner = {"corners": [{"vout": 1.80}, {"vout": 2.50}]}
    r = comp._compare_a4(
        corner, {"vout_target": 1.80},
        {"vout_target": {"rel_pct": 5.0, "abs_floor": 0.05}})
    assert r["verdict"] == "PASS_WITH_NOTES"


def test_a4_all_corners_far_off_fails():
    corner = {"corners": [{"vout": 0.50}, {"vout": 0.40}]}
    r = comp._compare_a4(
        corner, {"vout_target": 1.80},
        {"vout_target": {"rel_pct": 5.0, "abs_floor": 0.05}})
    assert r["verdict"] == "FAIL"


def test_a4_flat_shape_also_consumed():
    """Comparator accepts both `{"corners": [...]}` and flat
    `{"vout": x}` shapes."""
    r = comp._compare_a4(
        {"vout": 1.795}, {"vout_target": 1.80},
        {"vout_target": {"rel_pct": 5.0, "abs_floor": 0.05}})
    assert r["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# Per-block roll-up
# ---------------------------------------------------------------------------

def test_roll_up_any_fail_means_fail():
    assert comp._roll_up(["PASS", "PASS", "FAIL", "PASS"]) == "FAIL"


def test_roll_up_all_skip_means_skip():
    assert comp._roll_up(["SKIP_MISSING_ORACLE", "SKIP_MISSING_PLUGIN",
                          "SKIP"]) == "SKIP"


def test_roll_up_mixed_skip_and_pass_means_pass_with_notes():
    assert comp._roll_up(["PASS", "SKIP_MISSING_ORACLE",
                          "PASS"]) == "PASS_WITH_NOTES"


def test_roll_up_all_pass_means_pass():
    assert comp._roll_up(["PASS", "PASS", "PASS"]) == "PASS"


# ---------------------------------------------------------------------------
# End-to-end run() — determinism + JSON shape
# ---------------------------------------------------------------------------

def _setup_project_with_one_block(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    bdir = project / "phase3" / "analog" / "ldo"
    bdir.mkdir(parents=True)
    (bdir / "spec.json").write_text(json.dumps({
        "vout_target": 1.80, "psrr": 80.0, "iq": 100e-6}))
    (bdir / "topology.md").write_text(
        "LDO: pmos pass device + error_amp + feedback_divider + cap")
    (bdir / "ldo.sp").write_text(_SP_FIXTURE_LDO)
    (bdir / "corner_results.json").write_text(json.dumps({
        "corners": [{"vout": 1.795}, {"vout": 1.805}]}))
    oracle_dir = project / "phase3" / "analog"
    oracle = {
        "_meta": {"auditor": "test"},
        "blocks": {
            "ldo": {
                "spec": {"vout_target": 1.80, "psrr": 84.3,
                         "iq": 128e-6},
                "topology": {"device_classes": ["pfet", "error_amp",
                                                 "feedback_divider",
                                                 "cap"]},
                "netlist": {"top_module_name": "user_ldo",
                            "total_devices": 7,
                            "by_class": {"pfet": 2, "nfet": 2,
                                         "res": 2, "cap": 1}},
                "gds": None,
            }
        }
    }
    (oracle_dir / "oracle_specs.json").write_text(json.dumps(oracle))
    return project


def test_end_to_end_run_produces_per_block_verdict(tmp_path):
    project = _setup_project_with_one_block(tmp_path)
    result = comp.run(project)
    assert result["overall_verdict"] in ("PASS", "PASS_WITH_NOTES")
    assert "ldo" in result["blocks"]
    b = result["blocks"]["ldo"]
    assert b["spec_match"]["verdict"] in ("PASS", "PASS_WITH_NOTES")
    assert b["topology_match"]["verdict"] == "PASS"
    assert b["netlist_match"]["verdict"] in ("PASS", "PASS_WITH_NOTES")
    assert b["a4_match"]["verdict"] == "PASS"


def test_end_to_end_emits_json_and_md(tmp_path):
    project = _setup_project_with_one_block(tmp_path)
    comp.run(project)
    out_json = project / "reports" / "analog_oracle_compare.json"
    out_md = project / "reports" / "analog_oracle_compare.md"
    assert out_json.is_file()
    assert out_md.is_file()
    j = json.loads(out_json.read_text())
    assert j["overall_verdict"] is not None
    md = out_md.read_text()
    assert "Analog Oracle Compare Report" in md
    assert "ldo" in md


def test_end_to_end_is_deterministic_across_two_runs(tmp_path):
    """Same input → same JSON output (byte-equivalent JSON content
    after pretty-printing). This is the determinism guarantee."""
    project = _setup_project_with_one_block(tmp_path)
    r1 = comp.run(project)
    r2 = comp.run(project)
    # The _meta path equality is project-dir-fixed; the content
    # should match identically.
    s1 = json.dumps(r1, sort_keys=True)
    s2 = json.dumps(r2, sort_keys=True)
    assert s1 == s2


def test_main_returns_nonzero_only_on_fail(tmp_path):
    project = _setup_project_with_one_block(tmp_path)
    # Tweak fixture so a4 fails
    (project / "phase3" / "analog" / "ldo" / "corner_results.json").write_text(
        json.dumps({"corners": [{"vout": 0.5}, {"vout": 0.4}]}))
    rc = comp.main([str(project)])
    assert rc == 2


def test_main_returns_zero_on_pass_with_notes(tmp_path):
    project = _setup_project_with_one_block(tmp_path)
    rc = comp.main([str(project)])
    assert rc == 0
