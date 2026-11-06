"""Native route measurements retain their limits without a skip-log passport."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flow109_route_check as route


def _native_results(project, *, threshold=None, wire_max="9.5", drc=0, critical=0):
    states = {
        "Checker.TrDRC": {"route__drc_errors": drc},
        "Odb.ReportDisconnectedPins": {
            "design__disconnected_pin__count": critical,
            "design__critical_disconnected_pin__count": critical,
        },
        "Checker.DisconnectedPins": {"design__critical_disconnected_pin__count": critical},
        "Odb.ReportWireLength": {"route__wirelength__max": wire_max},
        "Checker.WireLength": {"route__wirelength__max": wire_max},
    }
    rows, configs = [], {}
    for index, step in enumerate(route.STEPS):
        folder = project / "native" / str(index)
        folder.mkdir(parents=True)
        (folder / "state_out.json").write_text(json.dumps({"metrics": states[step]}))
        config = folder / "config.json"
        config.write_text(json.dumps({"WIRE_LENGTH_THRESHOLD": threshold}))
        configs[step] = config
        rows.append({"step": step, "case": str(folder.relative_to(project)),
                     "status": "PASS", "metrics": states[step]})
    (project / rows[1]["case"] / "full_disconnected_pins_table.txt").write_text(
        "Instance Pin Critical\n")
    (project / rows[3]["case"] / "wire_lengths.csv").write_text(
        "net,length_um\nroute_net," + str(wire_max) + "\n")
    return rows, configs


def test_unset_native_wire_limit_needs_no_invocation_marker(tmp_path):
    rows, configs = _native_results(tmp_path)
    assert not list(tmp_path.rglob("invocation.log"))
    result = route._consume(tmp_path, rows, configs, {})
    assert result["status"] == "PASS"
    assert result["wire_length_check"]["status"] == "NOT_APPLICABLE"
    assert result["measurements"]["wire_length_max_um"] == "9.5"
    assert result["measurements"]["wire_length_threshold_um"] is None


@pytest.mark.parametrize("wire_max, expected", [("9.5", "PASS"), ("10", "PASS"), ("10.1", "FAIL")])
def test_declared_native_wire_limit_keeps_its_original_comparison(tmp_path, wire_max, expected):
    rows, configs = _native_results(tmp_path, threshold="10", wire_max=wire_max)
    result = route._consume(tmp_path, rows, configs, {})
    assert result["status"] == expected
    assert result["wire_length_check"]["status"] == expected
    assert result["wire_length_check"]["threshold_um"] == "10"
    assert ("route_check.wire_length_threshold" in result["failed_obligations"]) == (expected == "FAIL")


@pytest.mark.parametrize("step, obligation", [
    ("Checker.TrDRC", "route_check.route_short_overlap_errors"),
    ("Checker.WireLength", "route_check.wire_length_threshold"),
])
def test_native_checker_failure_is_preserved_without_a_wire_limit(tmp_path, step, obligation):
    rows, configs = _native_results(tmp_path)
    next(row for row in rows if row["step"] == step)["status"] = "FAIL"
    result = route._consume(tmp_path, rows, configs, {})
    assert result["status"] == "FAIL"
    assert obligation in result["failed_obligations"]


@pytest.mark.parametrize("drc, critical, obligation", [
    (3, 0, "route_check.route_short_overlap_errors"),
    (0, 2, "route_check.disconnected_required_pins"),
])
def test_measured_route_defects_still_fail_with_no_declared_wire_limit(tmp_path, drc, critical, obligation):
    rows, configs = _native_results(tmp_path, drc=drc, critical=critical)
    result = route._consume(tmp_path, rows, configs, {})
    assert result["status"] == "FAIL"
    assert obligation in result["failed_obligations"]


def test_missing_wire_measurement_is_not_an_unset_limit_waiver(tmp_path):
    rows, configs = _native_results(tmp_path)
    folder = tmp_path / rows[-1]["case"]
    (folder / "state_out.json").write_text(json.dumps({"metrics": {}}))
    with pytest.raises(route.RouteCheckError, match="route__wirelength__max"):
        route._consume(tmp_path, rows, configs, {})


def test_native_critical_pin_disagreement_remains_an_error(tmp_path):
    rows, configs = _native_results(tmp_path)
    folder = tmp_path / rows[1]["case"]
    (folder / "state_out.json").write_text(json.dumps({"metrics": {
        "design__disconnected_pin__count": 1,
        "design__critical_disconnected_pin__count": 1,
    }}))
    with pytest.raises(route.RouteCheckError, match="D42_NATIVE_METRIC_DISAGREEMENT"):
        route._consume(tmp_path, rows, configs, {})
