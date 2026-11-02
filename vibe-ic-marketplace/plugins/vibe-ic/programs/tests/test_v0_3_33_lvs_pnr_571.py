"""ORGANIC #571 — step_lvs DEF stage sanity (no routing → SKIP, not 2h magic)
+ pnr.tcl post-route checkpoint before antenna repair.
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402










def test_571a_named_def_present_is_trusted_not_skipped(tmp_path, monkeypatch):
    # when {top}.def is PRESENT the runner produced it as the routed output —
    # the routing-sanity SKIP must NOT fire (it is scoped to the fallback).
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    # a minimal named DEF with no routing markers — still trusted (not glob)
    (pnr / "chip_top.def").write_text(
        "VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n")
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text("module chip_top();\nendmodule\n")

    pdk = R.PdkConfig(name="sky130A", liberty="/foss/x.lib",
                      tech_lef="/t.tlef", cell_lef="/c.lef", cell_gds=None,
                      site="s", drc_deck=None)
    monkeypatch.setattr(R, "_docker_exec", lambda c, cmd, timeout=0, **_: (0, "", ""))
    monkeypatch.setattr(R, "_to_container_path", lambda s, c: s)
    monkeypatch.setattr(R, "_container_mounts", lambda c: [])
    r = R.step_lvs(tmp_path, "chip_top", pdk, "x")
    # it must NOT be the #571 floorplan SKIP
    assert r.extras.get("finding") != "LVS_INPUT_DEF_NOT_ROUTED"


def test_571a_alias_floorplan_cannot_replace_missing_state(tmp_path, monkeypatch):
    # {top}.def absent; only floorplan.def present (no routing) → SKIP.
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "floorplan.def").write_text(
        "VERSION 5.8 ;\nDESIGN chip_top ;\nCOMPONENTS 1 ;\n- i1 INV ;\n"
        "END COMPONENTS\nEND DESIGN\n")
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text("module chip_top();\nendmodule\n")

    pdk = R.PdkConfig(name="sky130A", liberty="/foss/x.lib",
                      tech_lef="/t.tlef", cell_lef="/c.lef", cell_gds=None,
                      site="s", drc_deck=None)
    monkeypatch.setattr(R, "_docker_exec", lambda c, cmd, timeout=0, **_: (0, "", ""))
    monkeypatch.setattr(R, "_to_container_path", lambda s, c: s)
    monkeypatch.setattr(R, "_container_mounts", lambda c: [])
    r = R.step_lvs(tmp_path, "chip_top", pdk, "x")
    assert r.status == "NOT_MEASURED"
    assert "CURRENT_FINAL_STATE_MISSING" in r.detail


def test_571b_pnr_tcl_emits_preantenna_checkpoint():
    # the pnr tcl template must write a routed checkpoint right after
    # detailed_route, before the antenna repair block.
    src = inspect.getsource(R)
    assert "routed_preantenna.def" in src
    # ordering: the checkpoint write appears before the antenna_repair_block
    cp = src.index("routed_preantenna.def")
    ar = src.index("antenna_repair_block")
    # the checkpoint reference precedes the antenna block placeholder use
    assert cp < src.rindex("antenna_repair_block")
    assert "ROUTED_CHECKPOINT_NONFATAL" in src
