"""Ordinary sizing API for an existing bias formula, without circuit-specific values."""
import json

import pytest

from _analog_producer_fixture import A2, A3, bdir, read_json, run_prog
from test_analog_ciff import _project


def emit(project, knobs=None):
    folder = bdir(project, "mod_alpha")
    if knobs is not None:
        (folder / "sizing_inputs.json").write_text(json.dumps({"knobs": knobs}))
    result = run_prog(A2, project)
    return folder, result


def cards(folder):
    return {line.split()[0]: line for line in (folder / "mod_alpha.sp").read_text().splitlines()
            if line.startswith("x")}


def test_default_and_explicit_two_have_identical_device_cards(tmp_path):
    snapshots = []
    for name, knobs in [("default", None), ("explicit", {"slew_design_margin": 2.0})]:
        project = _project(tmp_path / name, order=2, ciff=0)
        folder, result = emit(project, knobs)
        assert result.returncode == 0, result.stdout + result.stderr
        result = run_prog(A3, project)
        assert result.returncode == 0, result.stdout + result.stderr
        snapshots.append(cards(folder))
    assert snapshots[0] == snapshots[1]


def test_positive_margin_changes_only_bias_resistor_card(tmp_path):
    snapshots = []
    for name, margin in [("base", 2.0), ("sized", 4.0)]:
        project = _project(tmp_path / name, order=2, ciff=0)
        folder, result = emit(project, {"slew_design_margin": margin})
        assert result.returncode == 0, result.stdout + result.stderr
        result = run_prog(A3, project)
        assert result.returncode == 0, result.stdout + result.stderr
        snapshots.append(cards(folder))
    assert snapshots[0].keys() == snapshots[1].keys()
    assert {name for name in snapshots[0] if snapshots[0][name] != snapshots[1][name]} == {"xr_ib"}


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True, "invalid"])
def test_invalid_margin_remains_a_named_refusal(tmp_path, value):
    project = _project(tmp_path, order=2, ciff=0)
    folder, result = emit(project, {"slew_design_margin": value})
    assert result.returncode == 2
    gap = read_json(folder / "topology_gap.json")
    assert "knob slew_design_margin must be a finite positive number" in json.dumps(gap)


def test_unknown_knob_remains_refused(tmp_path):
    project = _project(tmp_path, order=2, ciff=0)
    folder, result = emit(project, {"unknown_margin": 4.0})
    assert result.returncode == 2
    assert "unknown sizing knob" in json.dumps(read_json(folder / "topology_gap.json"))
