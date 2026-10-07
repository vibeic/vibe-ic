"""Step 16 reopens chip DEFs with the canonical pad-library masters.

These focused controls model the LEF/DEF load seam. Native acceptance is a
separate retained-checkpoint run; the model does not claim EDA measurement.
"""
import json
import re
from pathlib import Path

import _pad_ring as pads
import _physical_current as current
import _tapeout_declaration as declaration
import clock_plan_check as gate
import phase3_one_shot_runner as runner
from _hostpaths import require_repo
from _clock_plan_fixture import step7_fixture
import pytest


def put(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def setup(tmp_path, monkeypatch):
    project = tmp_path / "project"
    tree = tmp_path / "pdk_root/open_fixture"
    tech = put(tree, "libs.ref/core/techlef/tech.lef", "VERSION 5.8 ;\n")
    cell = put(tree, "libs.ref/core/lef/cells.lef", "MACRO core_buf\nEND core_buf\n")
    io = put(tree, "libs.ref/fixture_io/lef/pad.lef",
             "MACRO input_pad\n  CLASS PAD INPUT ;\nEND input_pad\n")
    pdk = runner.PdkConfig(
        name=tree.name, liberty="unused", tech_lef=str(tech),
        cell_lef=str(cell), cell_gds=None, site="core", drc_deck=None,
        macro_lefs=[])
    put(project, declaration.SELF_TAPEOUT_REL, "fixture die declaration\n")
    floor = put(project, "phase3/stage3/pnr/floorplan.def",
                "DESIGN neutral ;\nCOMPONENTS 2 ;\n"
                "- u_logic core_buf ;\n- u_front input_pad ;\n"
                "END COMPONENTS\nEND DESIGN\n")
    sdc = put(project, "phase2/stage2/constraints/current.sdc",
              "create_clock -name system -period 12 [get_ports tick]\n")
    monkeypatch.setattr(runner, "_read_declared_pdk_target", lambda _: pdk.name)
    monkeypatch.setattr(runner, "_detect_pdk", lambda *_: pdk)
    step7_fixture(monkeypatch, project, pdk, sdc)
    calls = []

    def native(_project, tool, args, log):
        recipe = Path(args[-1]).read_text()
        loaded = set()
        for name in re.findall(r"(?m)^read_lef \{([^}]+)\}$", recipe):
            loaded.update(re.findall(r"(?m)^MACRO\s+(\S+)", Path(name).read_text()))
        section = floor.read_text().split("COMPONENTS", 1)[1].split("END COMPONENTS")[0]
        masters = set(re.findall(r"(?m)^\s*-\s+\S+\s+(\S+)", section))
        missing = masters - loaded
        calls.append(recipe)
        rc = 1 if missing else 0
        text = ("[ERROR] unknown library masters: " + str(sorted(missing))
                if missing else f"CLOCK_PLAN_PDK {pdk.name}\n"
                "CLOCK_PLAN_NATIVE system|12|tick\nCLOCK_PLAN_DONE\n")
        Path(log).write_text(text)
        return rc, {"rc": rc, "argv": [tool, *args]}

    monkeypatch.setattr(current, "run_native", native)
    plan = project / "phase3/stage3/cts/clock_plan.json"
    return project, floor, plan, io, pdk, calls


def emit(setup):
    project, floor, plan, _, _, _ = setup
    notes = []
    result = runner.emit_clock_plan(project, plan, floor, floor.parent, notes)
    return result, notes


def test_chip_consumer_loads_and_binds_canonical_io_masters(setup):
    project, floor, plan, io, pdk, calls = setup
    assert runner._chip_path_requests_pad_ring(project)
    assert pads.discover_io_lefs(io.parents[4], pdk.name) == [io]
    result, notes = emit(setup)
    assert result == str(plan), notes
    recipe = calls[0]
    assert recipe.index(f"read_lef {{{io}}}") < recipe.index(f"read_def {{{floor}}}")
    assert pdk.macro_lefs == []  # the run-wide PDK object stays immutable
    record = json.loads(plan.read_text())["current"]
    assert current.entry(project, io, external=True) in record["inputs"].values()
    assert gate.main([str(project)]) == 0


def test_checked_in_io_view_requires_the_same_load_seam(setup):
    _, floor, plan, io, _, _ = setup
    root = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                        "tests", "fixtures", "u22_perc_sweep_lef_class",
                        "phase3", "stage3", "extracted")
    view = next(p for p in sorted(root.glob("*.lef"))
                if re.search(r"CLASS\s+PAD\b", p.read_text(), re.I))
    body = view.read_text()
    master = re.search(r"(?m)^MACRO\s+(\S+)", body).group(1)
    io.write_text(body)
    floor.write_text(floor.read_text().replace("input_pad", master))
    result, notes = emit(setup)
    assert result == str(plan), notes


def test_core_consumer_does_not_require_an_io_library(setup, monkeypatch):
    project, floor, plan, _, _, _ = setup
    (project / declaration.SELF_TAPEOUT_REL).unlink()
    floor.write_text(floor.read_text().replace("input_pad", "core_buf"))
    step7_fixture(monkeypatch, project, setup[4],
                  project / "phase2/stage2/constraints/current.sdc")
    def unexpected(*_):
        raise AssertionError("core-only path queried IO views")
    monkeypatch.setattr(pads, "discover_io_lefs", unexpected)
    result, notes = emit(setup)
    assert result == str(plan), notes


def test_requested_io_library_absence_is_named_and_no_plan_is_written(setup):
    _, _, plan, io, _, calls = setup
    io.unlink()
    result, notes = emit(setup)
    assert result is None and not plan.exists()
    assert "CLOCK_PLAN_IO_LEFS_ABSENT" in notes[-1]
    assert calls == []


def test_existing_macro_views_are_retained_and_duplicate_io_is_read_once(setup):
    _, _, plan, io, pdk, calls = setup
    macro = put(io.parents[3], "other/lef/macro.lef", "MACRO memory\nEND memory\n")
    pdk.macro_lefs = [str(macro), str(io)]
    result, notes = emit(setup)
    assert result == str(plan), notes
    assert calls[0].count(f"read_lef {{{io}}}") == 1
    assert f"read_lef {{{macro}}}" in calls[0]
    assert pdk.macro_lefs == [str(macro), str(io)]


def test_wrong_tree_does_not_borrow_another_technology_io(setup):
    _, _, plan, io, pdk, _ = setup
    io.unlink()
    put(io.parents[4], "other_process/libs.ref/fixture_io/lef/pad.lef",
        "MACRO input_pad\nEND input_pad\n")
    result, notes = emit(setup)
    assert result is None and not plan.exists()
    assert "CLOCK_PLAN_IO_LEFS_ABSENT" in notes[-1]


def test_io_changed_during_native_execution_refuses_publication(setup, monkeypatch):
    _, _, plan, io, _, _ = setup
    native = current.run_native
    def changing(*args):
        result = native(*args)
        io.write_text(io.read_text() + "# changed during execution\n")
        return result
    monkeypatch.setattr(current, "run_native", changing)
    result, notes = emit(setup)
    assert result is None and not plan.exists()
    assert "CLOCK_PLAN_INPUT_CHANGED: pdk_lef_2" in notes[-1]


def test_io_changed_after_publication_is_refused_by_consumer(setup):
    project, _, plan, io, _, _ = setup
    result, notes = emit(setup)
    assert result == str(plan), notes
    io.write_text(io.read_text() + "# replaced after publication\n")
    report = project / "clock_gate.json"
    assert gate.main([str(project), "--json", str(report)]) == 1
    findings = json.loads(report.read_text())["findings"]
    assert any(f["rule"] == "CLOCK_PLAN_CURRENT_REFUSED"
               and "CURRENT_BYTES_CHANGED: pdk_lef_2" in f["message"] for f in findings)
