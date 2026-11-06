import json
from pathlib import Path

import flow_ppa_handoff as handoff


def test_orfs_view_import_keeps_native_state_and_document_fixed_density(tmp_path):
    source = tmp_path / "native"
    final = source / "results/process/unit/base"
    final.mkdir(parents=True)
    for suffix in (".odb", ".def", ".v", ".sdc", ".gds", ".spef"):
        (final / ("6_final" + suffix)).write_text("DESIGN neutral ;\nEND DESIGN\n")
    (source / "design.json").write_text(json.dumps({"parameters": {
        "CELL_PAD_IN_SITES_GLOBAL_PLACEMENT": 2,
        "CELL_PAD_IN_SITES_DETAIL_PLACEMENT": 1,
        "CTS_CLUSTER_SIZE": 10, "CTS_CLUSTER_DIAMETER": 25,
        "_FR_LAYER_ADJUST": .2, "PLACE_DENSITY_LB_ADDON": .3}}))
    log = source / "logs/process/unit/base/3_3_place_gp.log"
    log.parent.mkdir(parents=True)
    log.write_text("global_placement -skip_io -density 0.61\n"
                   "Minimum Feasible Density 0.59\n"
                   "global_placement -density 0.64 -timing_driven\n")
    settings, _ = handoff.native_settings(source, "orfs")
    assert settings["PL_TARGET_DENSITY_PCT"] == 64
    assert settings["GPL_CELL_PADDING"] == 4
    assert settings["DPL_CELL_PADDING"] == 2
    project = tmp_path / "project"
    docs = project / "input/docs"
    docs.mkdir(parents=True)
    (docs / "constraints.md").write_text("PL_TARGET_DENSITY = 0.5\n")
    result = handoff.prepare_import(project, source, "orfs")
    assert "PL_TARGET_DENSITY_PCT" not in result["native_overrides"]
    assert result["document_fixed_settings_excluded"] == {"PL_TARGET_DENSITY_PCT": 64}
    state = json.loads(Path(result["native_state"]).read_text())
    assert state["metrics"] == {}
    assert "spef" not in state
    assert Path(result["original_spef"]).read_bytes() == (final / "6_final.spef").read_bytes()
    assert all(Path(path).is_file() for key, path in state.items() if key != "metrics")
    assert result["views"]["def"]["design"] == "neutral"


def test_librelane_settings_keep_project_constraints_and_native_padding(tmp_path):
    resolved = tmp_path / "runs/native/resolved.json"
    resolved.parent.mkdir(parents=True)
    resolved.write_text(json.dumps({"GPL_CELL_PADDING": 4, "CTS_SINK_CLUSTERING_SIZE": 8,
                                  "PNR_SDC_FILE": "/old-worker/constraints.sdc"}))
    settings, notes = handoff.native_settings(tmp_path, "librelane")
    assert settings == {"GPL_CELL_PADDING": 4, "CTS_SINK_CLUSTERING_SIZE": 8}
    assert any("PNR_SDC_FILE" in note for note in notes)
