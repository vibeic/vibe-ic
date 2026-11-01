"""A topology emitted by the real producer reuses until its source changes."""
import json
from pathlib import Path

import pytest

import analog_a2_topology_emit as a2
import analog_one_shot_runner as runner


def _emit_topology(project):
    spec = {"order": 2., "osr": 512., "enob": 14., "vref": 1.,
            "vdd": 1.2, "vindiff": 1., "fclk": 1., "fclk_min": 1.,
            "fclk_max": 1., "ciff": 1., "designed_coefficients": 1.,
            "a1": .25, "a2": .25, "b1": .25, "b2": 0.,
            "c0": 1., "c1": 1., "c2": 1., "k0": 0., "feedback_delay": 0.,
            "cs1_ff": 100., "ci1_ff": 400.,
            "cf1_ff": 100.}
    measured = {"cap_area_ff_per_um2": 1.5, "cap_perim_ff_per_um": 0.,
                "rsheet_ohm_per_sq": 260., "k_prime_n_ua_per_v2": 328.,
                "vth_n_extracted_v": .197}
    bdir = project / "phase3/analog/neutral"
    bdir.mkdir(parents=True)
    spec_path = bdir / "spec.json"
    spec_path.write_text(json.dumps({"specs": [
        {"name": key, "target": value} for key, value in spec.items()]}))
    ir = a2.build_ir("neutral", "delta_sigma", {}, a2.LIBRARY["delta_sigma"],
                     spec, str(spec_path), project, None, {},
                     measured_params=measured)
    (bdir / "topology.json").write_text(json.dumps(ir))
    return ir


def test_real_producer_topology_is_reused(tmp_path):
    ir = _emit_topology(tmp_path)
    decision = runner.producer_reuse_decision(
        tmp_path, "neutral", "A2_topology_select")
    assert decision["artefact"] == ir["_provenance"]["producer_fingerprint"]
    assert decision["reuse"] is True, decision


@pytest.mark.parametrize("dependency", [
    "analog_a2_topology_emit.py", "analog_ciff.py", "analog_ota1_options.py",
    "_analog_producer_fingerprint.py", "analog_ota_bias.py",
])
def test_changed_producer_dependency_invalidates_real_topology(
        tmp_path, monkeypatch, dependency):
    source = Path(a2.__file__).resolve().parent
    shadow = tmp_path / "programs"
    shadow.mkdir()
    for name in ("analog_a2_topology_emit.py", "analog_ciff.py",
                 "analog_ota1_options.py", "_analog_producer_fingerprint.py",
                 "analog_ota_bias.py"):
        (shadow / name).write_bytes((source / name).read_bytes())
    monkeypatch.setattr(a2, "__file__", str(shadow / "analog_a2_topology_emit.py"))
    monkeypatch.setattr(runner, "PROGRAMS_DIR", shadow)
    project = tmp_path / "project"
    _emit_topology(project)
    assert runner.producer_reuse_decision(
        project, "neutral", "A2_topology_select")["reuse"] is True

    changed = shadow / dependency
    changed.write_bytes(changed.read_bytes() + b"\n# dependency changed\n")
    decision = runner.producer_reuse_decision(
        project, "neutral", "A2_topology_select")
    assert decision["reuse"] is False, decision
    assert decision["live"] != decision["artefact"]


@pytest.mark.parametrize("dependency", ["analog_mos_geometry.py", "analog_ota_bias.py"])
def test_real_a3_artifact_reuses_until_its_dependency_changes(tmp_path, monkeypatch, dependency):
    from _analog_producer_fixture import A1, A2, A3, block, make_project, run_prog, stage_custom_pdk
    import analog_a3_netlist_emit as a3

    project = make_project(tmp_path / "project", [block("supply", "ldo", [
        {"name": "Vout", "target": 1.8, "unit": "V"},
        {"name": "Vref", "target": .9, "unit": "V"}])])
    stage_custom_pdk(project, a3.DEFAULT_PDK)
    for program in (A1, A2, A3):
        result = run_prog(program, project)
        assert result.returncode == 0, result.stdout + result.stderr
    assert runner.producer_reuse_decision(project, "supply", "A3_netlist_gen")["reuse"] is True

    source = Path(a3.__file__).resolve().parent
    shadow = tmp_path / "programs"
    shadow.mkdir()
    for name in ("analog_a3_netlist_emit.py", "analog_a2_topology_emit.py",
                 "analog_ciff.py", "analog_ota1_options.py", "analog_ota_bias.py",
                 "analog_mos_geometry.py", "_analog_producer_fingerprint.py"):
        (shadow / name).write_bytes((source / name).read_bytes())
    monkeypatch.setattr(runner, "PROGRAMS_DIR", shadow)
    assert runner.producer_reuse_decision(project, "supply", "A3_netlist_gen")["reuse"] is True
    changed = shadow / dependency
    changed.write_bytes(changed.read_bytes() + b"\n# dependency control\n")
    decision = runner.producer_reuse_decision(project, "supply", "A3_netlist_gen")
    assert decision["reuse"] is False, decision
