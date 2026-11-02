"""LVS schematic netlists come from the selected final LibreLane State."""
import json
from pathlib import Path

import pytest

import _prestream_native as native

PROGRAMS = Path(__file__).resolve().parent.parent


def project(tmp_path):
    for name in ("phase2/stage2/synth/unit_synth.v", "phase3/stage3/pnr/unit_pnr.v"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("module stale(); endmodule")
    netlist = tmp_path / "physical.v"
    netlist.write_text("module unit(); CELL u (); endmodule")
    state = tmp_path / "state_out.json"
    state.write_text(json.dumps({"nl": str(netlist)}))
    return netlist, state


def test_picks_the_declared_state_netlist_over_pnr_and_synth_aliases(tmp_path):
    netlist, _ = project(tmp_path)
    assert native.signoff_inputs(tmp_path, "netlist") == {"netlist": netlist}


def test_missing_state_netlist_does_not_use_existing_aliases(tmp_path):
    _, state = project(tmp_path)
    state.write_text("{}")
    with pytest.raises(ValueError, match="CURRENT_FINAL_STATE_VIEW_MISSING: nl"):
        native.signoff_inputs(tmp_path, "netlist")


def test_missing_state_netlist_file_does_not_use_existing_aliases(tmp_path):
    netlist, _ = project(tmp_path)
    netlist.unlink()
    with pytest.raises(ValueError, match="CURRENT_FINAL_STATE_VIEW_MISSING: nl"):
        native.signoff_inputs(tmp_path, "netlist")


def test_512_diff_inputs_doctrine_in_skill():
    skill = (PROGRAMS.parent / "skills" / "lvs-triage" / "SKILL.md").read_text()
    import re
    assert re.search(r"diff.*input", skill, re.I)
    assert re.search(r"field.*recipe.*runner", skill, re.I)
    assert "#508" in skill and "#509" in skill
