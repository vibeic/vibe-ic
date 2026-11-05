"""One exclusion policy reaches cell inserters and counts their real DEFs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import librelane_cts_hold as C
import librelane_contract as L
import phase3_one_shot_runner as R
import excluded_master_census_check as EMC








def test_cts_hold_overlay_merges_the_run_policy_with_pdk_exclusions(
        tmp_path, monkeypatch):
    monkeypatch.setattr(L, "emit_config", lambda *_a, **_k: {
        "EXTRA_EXCLUDED_CELLS": ["famx__probe_1"]})
    monkeypatch.setattr(C, "_switch_knobs", lambda _p: {})
    expected = ["famx__dly_1", "famx__probe_1"]
    args = (R, tmp_path, "famxD", {}, 3, "declared", tmp_path / "scratch")
    try:
        got = C.overlay(*args, excluded_cells=["famx__dly_1"])
    except TypeError:
        got = C.overlay(*args)  # main's actual value, not an import failure
    assert got.get("EXTRA_EXCLUDED_CELLS", ([],))[0] == expected




def _fixture(tmp_path: Path, *, design: str, bad: bool):
    project = tmp_path / design
    project.mkdir(parents=True)
    master = "famx__dly_1" if bad else "famx__buf_1"
    layout = project / "stage.def"
    layout.write_text(
        "VERSION 5.8 ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "ROW row0 site 0 0 N DO 10 BY 1 STEP 100 0 ;\n"
        f"COMPONENTS 2 ;\n- u_core famx__logic_1 + PLACED ( 0 0 ) N ;\n"
        f"- u_cell {master} + PLACED ( 100 0 ) N ;\n"
        "END COMPONENTS\nEND DESIGN\n")
    config = project / "step.json"
    config.write_text(json.dumps({"EXTRA_EXCLUDED_CELLS": ["famx__dly_1"]}))
    state = project / "state_out.json"
    state.write_text(json.dumps({"def": str(layout)}))
    return config, state


def _audit(config: Path, state: Path):
    checker = getattr(R, "_emc", None)
    if checker is None:
        return {"verdict": "NOT_MEASURED", "excluded_count": None}
    assert checker is EMC, "the runner must use the tested census producer"
    return checker.audit(config, state, "OpenROAD.ResizerTimingPostCTS")


def test_second_design_clean_and_bad_cell_are_both_counted(tmp_path):
    clean = _fixture(tmp_path, design="logic_a", bad=False)
    bad = _fixture(tmp_path, design="logic_b", bad=True)
    assert _audit(*clean)["verdict"] == "PASS"
    result = _audit(*bad)
    assert result["verdict"] == "FAIL" and result["excluded_count"] == 1
    assert result["excluded_instances"][0]["instance"] == "u_cell"


def test_unreadable_def_is_not_an_empty_clean_census(tmp_path):
    config, state = _fixture(tmp_path, design="logic_c", bad=False)
    Path(json.loads(state.read_text())["def"]).unlink()
    assert _audit(config, state)["verdict"] == "NOT_MEASURED"


def test_reverse_mutation_removing_policy_exposes_the_bad_master(tmp_path):
    config, state = _fixture(tmp_path, design="logic_d", bad=True)
    assert _audit(config, state)["verdict"] == "FAIL"
    config.write_text(json.dumps({"EXTRA_EXCLUDED_CELLS": []}))
    assert _audit(config, state)["verdict"] == "PASS"
