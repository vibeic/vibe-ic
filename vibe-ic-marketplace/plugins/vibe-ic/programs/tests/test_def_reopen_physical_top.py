#!/usr/bin/env python3
"""Fresh-session DEF consumers use the cell named by the DEF itself."""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402


class _Pdk:
    """Small neutral PdkConfig surface used by streamout and extraction."""

    def __init__(self):
        self.name = "fixture"
        self.macro_lefs, self.macro_gds = [], []
        self.tech_lef = "/pdk/tech.lef"
        self.cell_lef = "/pdk/cells.lef"
        self.cell_gds = "/pdk/cells.gds"
        self.lefdef_layermap = None
        self.calibre_drc = self.drc_deck = None
        self.stdcell_marker_layer = self.dummy_fill = None
        self.same_net_heal = self.port_label_restore = None


def _write_def(path: Path, design: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "VERSION 5.8 ;\n"
        f"DESIGN {design} ;\n"
        "UNITS DISTANCE MICRONS 1000 ;\n"
        "DIEAREA ( 0 0 ) ( 100000 100000 ) ;\n"
        "COMPONENTS 1 ;\n"
        "- u_cell LIB_CELL + FIXED ( 0 0 ) N ;\n"
        "END COMPONENTS\n"
        "END DESIGN\n")
    return path


def _project(tmp_path: Path, design: str):
    pnr = p3._pl.pnr_dir(tmp_path)
    _write_def(pnr / "logical_core.def", design)
    return tmp_path, pnr


def _capture(monkeypatch):
    seen = {}

    def _exec(container, cmd, *args, **kwargs):
        seen["cmd"] = cmd
        return 1, "tool transcript", ""

    monkeypatch.setattr(p3, "_docker_exec", _exec)
    monkeypatch.setattr(p3, "_tool_in_path", lambda *_: True)
    monkeypatch.setattr(p3, "_to_container_path", lambda path, _: str(path))
    return seen


def test_magic_loads_physical_top_but_preserves_logical_paths(
        tmp_path, monkeypatch):
    """Value-bearing control: inspect the exact command sent to Magic."""
    project, pnr = _project(tmp_path, "package_top")
    seen = _capture(monkeypatch)
    p3._magic_def_to_gds(
        project, "logical_core", _Pdk(), "container",
        pnr / "logical_core.gds")
    assert "TOP=package_top " in seen["cmd"], seen["cmd"]
    assert f"DEF={pnr / 'logical_core.def'}" in seen["cmd"]
    assert f"GDS_OUT={pnr / 'logical_core.gds'}" in seen["cmd"]


def test_agreeing_def_is_a_no_op_for_magic_argv(tmp_path, monkeypatch):
    project, pnr = _project(tmp_path, "logical_core")
    seen = _capture(monkeypatch)
    p3._magic_def_to_gds(
        project, "logical_core", _Pdk(), "container",
        pnr / "logical_core.gds")
    assert "TOP=logical_core " in seen["cmd"], seen["cmd"]


def test_magic_persists_the_transcript_per_output(tmp_path, monkeypatch):
    project, pnr = _project(tmp_path, "logical_core")
    _capture(monkeypatch)
    p3._magic_def_to_gds(
        project, "logical_core", _Pdk(), "container",
        pnr / "logical_core.gds")
    first = pnr / "logical_core.magic_stream_out.log"
    assert first.read_text().startswith("tool transcript")
    p3._magic_def_to_gds(
        project, "logical_core", _Pdk(), "container",
        pnr / "logical_core.restream.gds")
    assert (pnr / "logical_core.restream.magic_stream_out.log").is_file()
    assert first.read_text().startswith("tool transcript")


def test_klayout_receives_the_same_physical_top(tmp_path, monkeypatch):
    project, _ = _project(tmp_path, "package_top")
    seen = _capture(monkeypatch)
    monkeypatch.setattr(p3, "_vacuous_on_unrouted", lambda *a, **k: None)
    monkeypatch.setattr(
        p3, "_magic_def_to_gds", lambda *a, **k: (False, "forced fallback"))
    result = p3.step_gds(project, "logical_core", _Pdk(), "container")
    assert result.status == "FAIL"
    assert "TOP=package_top " in seen["cmd"], seen["cmd"]


def test_lvs_receives_the_same_physical_top(tmp_path, monkeypatch):
    project, pnr = _project(tmp_path, "package_top")
    netlist = pnr / "logical_core_pnr.v"
    netlist.write_text("module package_top(); endmodule\n")
    seen = _capture(monkeypatch)
    result = p3._run_extraction_lvs(
        project, "logical_core", _Pdk(), "container",
        pnr / "logical_core.def", netlist, "/dev/null", "/dev/null", 0.0)
    assert result.status == "FAIL"
    assert "TOP=package_top " in seen["cmd"], seen["cmd"]
    provenance = p3._pl.extracted_dir(project) / "extraction_top_resolution.json"
    assert provenance.is_file()
    assert '"physical_top": "package_top"' in provenance.read_text()


def test_headerless_def_falls_back_to_the_logical_top(tmp_path, monkeypatch):
    pnr = p3._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "logical_core.def").write_text("VERSION 5.8 ;\n")
    seen = _capture(monkeypatch)
    p3._magic_def_to_gds(
        tmp_path, "logical_core", _Pdk(), "container",
        pnr / "logical_core.gds")
    assert "TOP=logical_core " in seen["cmd"], seen["cmd"]


def test_drc_deck_receives_the_def_physical_top(tmp_path, monkeypatch):
    project, pnr = _project(tmp_path, "package_top")
    (pnr / "logical_core.gds").write_bytes(b"layout")
    pdk = _Pdk()
    pdk.drc_deck = "/pdk/rules.drc"
    seen = {}

    def _deck(gds, report, top, *args):
        seen["top"] = top
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("<report-database><items/></report-database>\n")
        return 0, "", ""

    monkeypatch.setattr(p3, "_vacuous_on_unrouted", lambda *a, **k: None)
    monkeypatch.setattr(p3, "_tool_in_path", lambda *_: True)
    monkeypatch.setattr(p3, "_klayout_deck_exec", _deck)
    result = p3.step_drc(project, "logical_core", pdk, "container")
    assert result.status == "PASS", result.detail
    assert seen["top"] == "package_top", seen
    assert result.extras["physical_top"] == "package_top"


def test_pad_ring_hierarchy_audit_starts_at_the_def_physical_top(
        tmp_path, monkeypatch):
    project, pnr = _project(tmp_path, "package_top")
    for name in ("padring.def", "routed.def"):
        _write_def(pnr / name, "package_top")
    reports = project / "reports" / "phase3"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "padring.json").write_text(json.dumps({
        "producer": {
            "pads": [{"instance": "u_cell", "master": "LIB_CELL"}],
            "corners": [],
            "fillers": [],
        }
    }))
    (pnr / "pnr.tcl").write_text(
        "puts {PADRING_ROUTING_CONSUMED: fixture}\n"
        "global_placement\n"
        "detailed_route\n")
    (pnr / "openroad.log").write_text("PADRING_ROUTING_CONSUMED: fixture\n")
    gds = pnr / "logical_core.gds"
    gds.write_bytes(b"layout")
    seen = {}

    def _references(path, top):
        seen["top"] = top
        return {"LIB_CELL": 1}

    monkeypatch.setattr(p3, "_gds_reference_counts", _references)
    gds_result = p3.StepResult(
        "gds", "PASS", 0.0, "fixture", [str(gds)],
        extras={"streamout_engine": "fixture"})
    result = p3.step_pad_ring_final_evidence(
        project, "logical_core", gds_result)
    assert result.status == "PASS", result.detail
    assert seen["top"] == "package_top", seen
    payload = json.loads((reports / "pad_ring_route_evidence.json").read_text())
    assert payload["logical_top"] == "logical_core"
    assert payload["physical_top"] == "package_top"
