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
    liberty = put(tree, "libs.ref/core/lib/active.lib",
                  "library(neutral) { cell(neutral_driver) {} }\n")
    pdk = runner.PdkConfig(
        name=tree.name, liberty=str(liberty), tech_lef=str(tech),
        cell_lef=str(cell), cell_gds=None, site="core", drc_deck=None,
        macro_lefs=[])
    put(project, declaration.SELF_TAPEOUT_REL, "fixture die declaration\n")
    floor = put(project, "phase3/stage3/pnr/floorplan.def",
                "DESIGN neutral ;\nCOMPONENTS 2 ;\n"
                "- u_logic core_buf ;\n- u_front input_pad ;\n"
                "END COMPONENTS\nEND DESIGN\n")
    put(project, "phase2/stage2/constraints/current.sdc",
        "create_clock -name system -period 12 [get_ports tick]\n")
    monkeypatch.setattr(runner, "_read_declared_pdk_target", lambda _: pdk.name)
    monkeypatch.setattr(runner, "_detect_pdk", lambda *_: pdk)
    calls = []

    def native(_project, tool, args, log):
        recipe = Path(args[-1]).read_text()
        loaded = set()
        for name in re.findall(r"(?m)^read_lef \{([^}]+)\}$", recipe):
            loaded.update(re.findall(r"(?m)^MACRO\s+(\S+)", Path(name).read_text()))
        section = floor.read_text().split("COMPONENTS", 1)[1].split("END COMPONENTS")[0]
        masters = set(re.findall(r"(?m)^\s*-\s+\S+\s+(\S+)", section))
        missing = masters - loaded
        timing_cells = set()
        for name in re.findall(r"(?m)^read_liberty \{([^}]+)\}$", recipe):
            timing_cells.update(re.findall(r"\bcell\s*\(\s*(\w+)\s*\)", Path(name).read_text()))
        sdc_text = "\n".join(Path(name).read_text() for name in
                             re.findall(r"(?m)^read_sdc \{([^}]+)\}$", recipe))
        missing_drivers = set(re.findall(r"-lib_cell\s+(\w+)", sdc_text)) - timing_cells
        calls.append(recipe)
        rc = 1 if missing or missing_drivers else 0
        text = ("[ERROR] unknown library masters: " + str(sorted(missing))
                if missing else "[ERROR] driver library cell not found: " + str(sorted(missing_drivers))
                if missing_drivers else f"CLOCK_PLAN_PDK {pdk.name}\n"
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


def test_sdc_library_driver_is_evaluated_after_current_liberty_load(setup):
    project, _, plan, _, pdk, calls = setup
    sdc = project / "phase2/stage2/constraints/current.sdc"
    sdc.write_text(sdc.read_text() + "set_driving_cell -lib_cell neutral_driver [all_inputs]\n")
    result, notes = emit(setup)
    assert result == str(plan), notes
    assert calls[0].index(f"read_liberty {{{pdk.liberty}}}") < calls[0].index("read_sdc ")
    assert gate.main([str(project)]) == 0


def test_unknown_sdc_driver_remains_a_native_refusal(setup):
    project, _, plan, _, _, _ = setup
    sdc = project / "phase2/stage2/constraints/current.sdc"
    sdc.write_text(sdc.read_text() + "set_driving_cell -lib_cell unknown_driver [all_inputs]\n")
    result, notes = emit(setup)
    assert result is None and not plan.exists()
    assert "CLOCK_PLAN_NATIVE_REFUSED" in notes[-1]


def test_library_change_invalidates_both_reuse_and_gate(setup):
    project, floor, plan, _, pdk, calls = setup
    assert emit(setup)[0] == str(plan)
    Path(pdk.liberty).write_text(Path(pdk.liberty).read_text() + "\n/* changed */\n")
    report = project / "clock_gate.json"
    assert gate.main([str(project), "--json", str(report)]) == 1
    assert "CURRENT_BYTES_CHANGED: pdk_liberty_0" in report.read_text()
    notes = []
    assert runner.emit_clock_plan(project, plan, floor, floor.parent, notes, pdk=pdk) == str(plan)
    assert len(calls) == 2
    assert gate.main([str(project)]) == 0


def test_library_set_change_rebuilds_and_binds_macro_timing(setup):
    project, floor, plan, io, pdk, calls = setup
    assert emit(setup)[0] == str(plan)
    macro = put(io.parents[3], "memory/lib/active.lib", "library(memory) { cell(memory_driver) {} }\n")
    pdk.macro_libs = [str(macro), str(macro)]
    notes = []
    assert runner.emit_clock_plan(project, plan, floor, floor.parent, notes, pdk=pdk) == str(plan)
    assert len(calls) == 2
    assert calls[-1].count(f"read_liberty {{{macro}}}") == 1
    assert any("CURRENT_PDK_LIBERTY_SET_CHANGED" in note for note in notes)
    assert current.entry(project, macro, external=True) in json.loads(plan.read_text())["current"]["inputs"].values()


def test_missing_or_mutating_liberty_cannot_publish_a_plan(setup, monkeypatch):
    _, _, plan, _, pdk, calls = setup
    native = current.run_native
    def changing(*args):
        result = native(*args)
        Path(pdk.liberty).write_text("library(replaced) {}\n")
        return result
    monkeypatch.setattr(current, "run_native", changing)
    result, notes = emit(setup)
    assert result is None and not plan.exists()
    assert "CLOCK_PLAN_INPUT_CHANGED: pdk_liberty_0" in notes[-1]
    assert len(calls) == 1
    Path(pdk.liberty).unlink()
    assert emit(setup)[0] is None
    assert len(calls) == 1


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


def test_reuse_refuses_when_pdk_adds_macro_lef(setup):
    project, floor, plan, io, pdk, calls = setup
    first = runner.emit_clock_plan(project, plan, floor, floor.parent, [],
                                   pdk=pdk)
    assert first == str(plan)
    macro = put(io.parents[3], "new_macro/lef/memory.lef",
                "MACRO memory\nEND memory\n")
    pdk.macro_lefs = [str(macro)]
    notes = []
    second = runner.emit_clock_plan(project, plan, floor, floor.parent, notes,
                                    pdk=pdk)
    assert second == str(plan), notes
    assert len(calls) == 2
    assert f"read_lef {{{macro}}}" in calls[-1]
    assert any("CURRENT_PDK_LEF_SET_CHANGED" in note for note in notes)


def test_reuse_refuses_when_pdk_identity_changes(setup):
    project, floor, plan, _io, pdk, calls = setup
    first = runner.emit_clock_plan(project, plan, floor, floor.parent, [],
                                   pdk=pdk)
    assert first == str(plan)
    pdk.name = "different_pdk"
    notes = []
    second = runner.emit_clock_plan(project, plan, floor, floor.parent, notes,
                                    pdk=pdk)
    assert second == str(plan), notes
    assert len(calls) == 2
    assert any("CURRENT_PDK_CHANGED" in note for note in notes)


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


def test_validated_reuse_returns_the_owned_path_without_rerunning_native(setup):
    project, floor, plan, _, pdk, calls = setup
    assert runner.emit_clock_plan(project, plan, floor, floor.parent, [],
                                  pdk=pdk) == str(plan)
    before = plan.read_bytes()
    notes = []
    assert runner.emit_clock_plan(project, plan, floor, floor.parent, notes,
                                  pdk=pdk) == str(plan), notes
    assert len(calls) == 1
    assert plan.read_bytes() == before
    assert "current native subject validated" in notes[-1]
    assert gate.main([str(project)]) == 0


def test_default_clock_row_accepts_cold_and_validated_reused_native_plan(
        setup, monkeypatch):
    project, _, plan, _, pdk, calls = setup
    # Step16 does not invoke this backend parameter transport. Its producer,
    # native-subject validation, retained writer and complete consumer stay real.
    monkeypatch.setattr(runner, "_backend_parameter_values", lambda *_: {})
    first = runner._default_pnr_rows(project, "neutral", pdk, "", ["16"])
    assert first.status == "PASS", first.detail
    assert first.extras["canonical_gate_checks"]["16"]["status"] == "PASS"
    before = plan.read_bytes()
    second = runner._default_pnr_rows(project, "neutral", pdk, "", ["16"])
    assert second.status == "PASS", second.detail
    assert second.extras["canonical_gate_checks"]["16"]["status"] == "PASS"
    assert len(calls) == 1
    assert plan.read_bytes() == before
    receipt = json.loads((project / "reports/phase3/default_steps/16/backend_result.json").read_text())
    assert receipt["verdict"] == "PASS"
    assert receipt["canonical_step_result"]["status"] == "PASS"
    assert receipt["gate_ledger"][0]["rc"] == 0


@pytest.mark.parametrize("changed", ["floorplan", "sdc", "log", "io"])
def test_invalid_reuse_never_returns_success_when_native_refresh_fails(
        setup, monkeypatch, changed):
    project, floor, plan, io, pdk, calls = setup
    assert runner.emit_clock_plan(project, plan, floor, floor.parent, [],
                                  pdk=pdk) == str(plan)
    before = plan.read_bytes()
    doc = json.loads(before)
    target = {"floorplan": floor,
              "sdc": project / "phase2/stage2/constraints/current.sdc",
              "log": project / doc["current"]["outputs"]["log"]["path"],
              "io": io}[changed]
    target.write_text(target.read_text() + "\n# changed original input or evidence\n")
    native = current.run_native

    def refused(*args):
        _, execution = native(*args)
        Path(args[-1]).write_text("native refresh failed\n")
        return 1, {**execution, "rc": 1}

    monkeypatch.setattr(current, "run_native", refused)
    notes = []
    assert runner.emit_clock_plan(project, plan, floor, floor.parent, notes,
                                  pdk=pdk) is None
    assert len(calls) == 2
    assert plan.read_bytes() == before
    assert any("NOT written" in note for note in notes)
    assert gate.main([str(project)]) == 1
