from pathlib import Path

import librelane_contract as contract


def test_moved_native_views_resolve_in_the_current_run(tmp_path):
    project = tmp_path / "current"
    view = project / "phase3/librelane/sta/circuit.sdf"
    view.parent.mkdir(parents=True)
    view.write_text("native SDF output")
    assert contract.project_path(project, "/old/run/phase3/librelane/sta/circuit.sdf") == view
    assert contract.project_path(project, "phase3/librelane/sta/circuit.sdf") == view
    assert contract.project_path(project, view) == view


def test_external_technology_and_missing_views_are_not_renamed(tmp_path):
    project = tmp_path / "current"
    external = tmp_path / "technology/libs/models.lib"
    external.parent.mkdir(parents=True)
    external.write_text("native technology")
    assert contract.project_path(project, external) == external
    missing = Path("/old/run/phase3/librelane/sta/missing.sdf")
    assert contract.project_path(project, missing) == missing
