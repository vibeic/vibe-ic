"""Native alternate signoff routes consume the selected State views."""
import json
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

import phase3_one_shot_runner as runner
from _finished_gds_fixture import publish_finished_gds


def _subject(tmp_path):
    views = {}
    for name in ("gds", "def", "nl"):
        path = tmp_path / "native" / ("final." + name)
        path.parent.mkdir(exist_ok=True)
        path.write_text("DESIGN unit ;\nEND DESIGN\n" if name == "def" else name)
        views[name] = path
    (tmp_path / "state_out.json").write_text(json.dumps({
        name: str(path) for name, path in views.items()}))
    publish_finished_gds(tmp_path)
    aliases = tmp_path / "phase3/stage3/pnr"
    aliases.mkdir(parents=True)
    for name in ("unit.gds", "unit.def", "unit_pnr.v"):
        (aliases / name).write_text("stale alias")
    return views


def _pdk(**options):
    return runner.PdkConfig(name="open_fixture", liberty="unused", tech_lef="unused",
                            cell_lef="unused", cell_gds=None, site="unit",
                            drc_deck=None, **options)


@pytest.mark.parametrize("violations,expected", [(0, "PASS"), (1, "FAIL")])
def test_svrf_drc_and_cell_cfg_receive_state_gds_and_def(tmp_path, monkeypatch, violations, expected):
    views = _subject(tmp_path)
    monkeypatch.setattr(runner, "_tool_in_path", lambda *args: False)
    monkeypatch.setattr(runner, "_svrfdrc_bin_container", lambda *args: "svrfdrc")
    monkeypatch.setattr(runner, "_svrfdrc_supports_threads", lambda *args: False)
    monkeypatch.setattr(runner, "_svrfdrc_supports_cell_aware_feol", lambda *args: True)
    monkeypatch.setattr(runner, "_to_container_path", lambda path, container: path)
    cfg_paths, commands = [], []

    def cfg(*args, **kwargs):
        cfg_paths.append(kwargs["routed_def"])
        return None

    def native(container, command, **kwargs):
        commands.append(command)
        argv = shlex.split(command)
        Path(argv[3]).write_text(("FAIL" if violations else "PASS") + " SPACE.M1 rule -> " + str(violations))
        return 0, "", ""

    monkeypatch.setattr(runner, "_build_cell_aware_feol_cfg", cfg)
    monkeypatch.setattr(runner, "_docker_exec", native)
    result = runner.step_drc(tmp_path, "unit", _pdk(calibre_drc="deck.rule"), "image", _direct=True)
    assert result.status == expected, result.detail
    assert shlex.split(commands[0])[2] == str(views["gds"])
    assert cfg_paths == [views["def"]]


def test_klayout_extracts_state_gds_and_ignores_private_copy(tmp_path, monkeypatch):
    views = _subject(tmp_path)
    views["gds"].with_suffix(".lvs.gds").write_text("unbound private copy")
    library = tmp_path / "cells.gds"
    library.write_text("library")
    pdk = _pdk()
    pdk.cell_gds = str(library)
    monkeypatch.setattr(runner, "_tool_in_path", lambda *args: True)
    monkeypatch.setattr(runner, "_to_container_path", lambda path, container: path)
    commands = []

    class Extracted(Exception):
        pass

    def native(container, command, *args, **kwargs):
        commands.append(command)
        if " extract " in command:
            assert " extract " + str(views["gds"]) + " " in command
            assert ".lvs.gds" not in command
            raise Extracted
        return 0, "", ""

    monkeypatch.setattr(runner, "_declared_session_exec", native)
    with pytest.raises(Extracted):
        runner._run_klayout_lvs(tmp_path, "unit", pdk, "image", views["nl"], 0,
                                gds_path=views["gds"])
    assert len(commands) == 2


@pytest.mark.parametrize("status,expected", [("MATCH", "PASS"), ("MISMATCH", "FAIL")])
def test_device_lvs_receives_state_views_over_aliases(tmp_path, monkeypatch, status, expected):
    views = _subject(tmp_path)
    registry = {"device_lvs_program": "asap7_finfet_lvs.py", "cdl_netlist": "cells/cells.cdl",
                "klayout_lvs_tech": "native.lyt", "container_path": "/pdk"}
    monkeypatch.setattr(runner, "_pdk_registry_entry", lambda name: registry)
    monkeypatch.setattr(runner, "_tool_in_path", lambda *args: True)
    monkeypatch.setattr(runner, "_to_container_path", lambda path, container: path)
    commands = []

    def native(container, command, **kwargs):
        commands.append(command)
        return 0, 'A7_DESIGN_LVS ' + json.dumps({"verdict": status, "power_shorts": 0}), ""

    monkeypatch.setattr(runner, "_docker_exec", native)
    result = runner.step_lvs(tmp_path, "unit", SimpleNamespace(name="open_fixture", calibre_lvs=None),
                              "image", _direct=True)
    assert result.status == expected, result.detail
    argv = shlex.split(commands[0])
    assert argv[argv.index("design") + 1] == str(views["gds"])
    assert argv[argv.index("--gate-netlist") + 1] == str(views["nl"])
    assert argv[argv.index("--def") + 1] == str(views["def"])
