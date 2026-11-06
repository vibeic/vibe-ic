"""A topology emitted by the real producer reuses until its source changes."""

import pytest


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
