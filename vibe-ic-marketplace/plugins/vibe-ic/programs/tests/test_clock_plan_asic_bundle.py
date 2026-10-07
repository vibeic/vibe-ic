"""Native Step 16 consumes Step 7's complete, current ASIC constraint bundle."""
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import _path_layout as layout
import _physical_current as current
import clock_plan_check as gate
import phase3_one_shot_runner as runner
from _clock_plan_fixture import step7_fixture
from _hostpaths import require_repo


def put(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    project = tmp_path / "project"
    source = put(project, "input/constraints/intent.sdc",
                 "create_clock -name primary -period 12 [get_ports tick]\n"
                 "create_clock -name auxiliary -period 30 [get_ports aux]\n"
                 "set_input_delay 2 -clock primary [get_ports data]\n"
                 "set_output_delay 3 -clock primary [get_ports result]\n"
                 "set_false_path -from [get_ports reset]\n"
                 "set_max_fanout 4 [current_design]\n")
    fpga = put(project, "phase2/stage1/fpga/neutral.sdc",
               "create_clock -name fpga_only -period 20 [get_ports board_tick]\n"
               "derive_pll_clocks\nderive_clock_uncertainty\n")
    floor = put(project, "phase3/stage3/pnr/floorplan.def", "DESIGN neutral ;\nEND DESIGN\n")
    tech = put(project, "input/pdk/tech.lef", "VERSION 5.8 ;\n")
    cell = put(project, "input/pdk/cells.lef", "MACRO neutral\nEND neutral\n")
    liberty = put(project, "input/pdk/cells.lib", "library (neutral) {}\n")
    pdk = SimpleNamespace(name="open_fixture", tech_lef=str(tech),
                          cell_lef=str(cell), liberty=str(liberty), macro_lefs=[])
    monkeypatch.setattr(runner, "_read_declared_pdk_target", lambda _: pdk.name)
    monkeypatch.setattr(runner, "_detect_pdk", lambda *_: pdk)
    rec = step7_fixture(monkeypatch, project, pdk, source)
    executions = []

    def native(_project, tool, args, log):
        recipe = Path(args[-1]).read_text()
        sdcs = [Path(p) for p in re.findall(r"(?m)^read_sdc \{([^}]+)\}$", recipe)]
        texts = "\n".join(p.read_text() for p in sdcs)
        executions.append({"sdcs": sdcs, "text": texts})
        invalid = "derive_pll_clocks" in texts
        lines = [f"CLOCK_PLAN_PDK {pdk.name}"]
        for name, period, port in re.findall(
                r"create_clock -name (\S+) -period ([\d.]+) \[get_ports (\S+)\]", texts):
            lines.append(f"CLOCK_PLAN_NATIVE {name}|{period}|{port}")
        lines.append("[ERROR] invalid command derive_pll_clocks" if invalid else "CLOCK_PLAN_DONE")
        Path(log).write_text("\n".join(lines) + "\n")
        rc = int(invalid)
        return rc, {"rc": rc, "argv": [tool, *args]}

    monkeypatch.setattr(current, "run_native", native)
    plan = project / "phase3/stage3/cts/clock_plan.json"
    return project, source, fpga, floor, pdk, rec, plan, executions


def emit(bundle):
    project, _, _, floor, _, _, plan, _ = bundle
    notes = []
    result = runner.emit_clock_plan(project, plan, floor, floor.parent, notes)
    return result, notes


def check(bundle):
    project = bundle[0]
    report = project / "clock_gate.json"
    rc = gate.main([str(project), "--json", str(report)])
    return rc, json.loads(report.read_text())


def test_complete_source_bound_asic_bundle_preserves_fpga_and_all_constraints(bundle):
    project, source, fpga, _, _, rec, plan, executions = bundle
    before = hashlib.sha256(fpga.read_bytes()).hexdigest()
    assert layout.clock_plan_input_sdcs(project) == [project / rec["path"]]
    result, notes = emit(bundle)
    assert result == str(plan), notes
    assert executions[0]["sdcs"] == [project / rec["path"]]
    assert source.read_text() in executions[0]["text"]
    assert hashlib.sha256(fpga.read_bytes()).hexdigest() == before
    assert str(fpga.relative_to(project)) in rec["inputs"]
    assert check(bundle)[0] == 0
    assert {c["name"] for c in json.loads(plan.read_text())["clocks"]} == {"primary", "auxiliary"}


def test_checked_in_multiclock_artifact_is_retained_in_the_executed_bundle(bundle, monkeypatch):
    project, source, _, _, pdk, _, plan, executions = bundle
    artifact = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                            "calibration", "cal_two_clocks.sdc")
    body = artifact.read_text()
    # The model expects the uniform spelling of the fixture's declared clocks.
    source.write_text(body)
    step7_fixture(monkeypatch, project, pdk, source)
    result, notes = emit(bundle)
    assert result == str(plan), notes
    assert body in executions[0]["text"]


@pytest.mark.parametrize("mutation", ["deck", "record", "missing", "escaped", "pdk"])
def test_invalid_asic_record_never_falls_back_to_fpga_or_a_stage_snapshot(bundle, mutation):
    project, _, _, _, _, rec, plan, executions = bundle
    path = project / "phase2/stage2/constraints/asic_sdc.json"
    if mutation == "deck":
        (project / rec["path"]).write_text("create_clock -name forged -period 1 [get_ports tick]\n")
    elif mutation == "missing":
        path.unlink()
    else:
        doc = json.loads(path.read_text())
        if mutation == "record":
            doc["schema"] = "wrong"
        elif mutation == "escaped":
            doc["path"] = "../../external.sdc"
        else:
            doc["pdk"] = "other_process"
        path.write_text(json.dumps(doc))
    result, notes = emit(bundle)
    assert result is None and not plan.exists(), notes
    assert "CLOCK_PLAN_ASIC_SDC" in notes[-1]
    assert executions == []


@pytest.mark.parametrize("mutation", ["deck", "record", "missing", "escaped"])
def test_invalid_record_after_publication_returns_a_gate_refusal(bundle, mutation):
    project, _, _, _, _, rec, plan, _ = bundle
    assert emit(bundle)[0] == str(plan)
    path = project / "phase2/stage2/constraints/asic_sdc.json"
    if mutation == "deck":
        (project / rec["path"]).write_text("# replaced deck\n")
    elif mutation == "missing":
        path.unlink()
    else:
        doc = json.loads(path.read_text())
        doc["schema" if mutation == "record" else "path"] = "invalid"
        path.write_text(json.dumps(doc))
    assert check(bundle)[0] == 1


@pytest.mark.parametrize("relative", ["input/constraints/intent.sdc", "phase2/stage1/fpga/neutral.sdc"])
def test_current_step7_source_change_blocks_native_execution(bundle, relative):
    project, _, _, _, _, _, plan, executions = bundle
    path = project / relative
    path.write_text(path.read_text() + "# source changed\n")
    result, notes = emit(bundle)
    assert result is None and not plan.exists()
    assert "inputs changed since step 7" in notes[-1]
    assert executions == []


def test_source_change_during_measurement_refuses_publication(bundle, monkeypatch):
    _, source, _, _, _, _, plan, _ = bundle
    native = current.run_native
    def changing(*args):
        result = native(*args)
        source.write_text(source.read_text() + "# raced native execution\n")
        return result
    monkeypatch.setattr(current, "run_native", changing)
    result, notes = emit(bundle)
    assert result is None and not plan.exists()
    assert "inputs changed since step 7" in notes[-1]


def test_source_change_after_publication_is_refused_by_real_consumer(bundle):
    _, source, _, _, _, _, plan, _ = bundle
    assert emit(bundle)[0] == str(plan)
    source.write_text(source.read_text() + "# replaced source\n")
    rc, report = check(bundle)
    assert rc == 1
    assert any(f["rule"] == "CLOCK_PLAN_CURRENT_REFUSED"
               and "inputs changed since step 7" in f["message"] for f in report["findings"])


def test_changed_source_cannot_reuse_a_cached_plan(bundle):
    _, source, _, _, _, _, plan, executions = bundle
    assert emit(bundle)[0] == str(plan)
    original = plan.read_bytes()
    source.write_text(source.read_text() + "# changed after cached measurement\n")
    result, notes = emit(bundle)
    assert result is None and "inputs changed since step 7" in "\n".join(notes)
    assert len(executions) == 1 and plan.read_bytes() == original
    assert check(bundle)[0] == 1


def test_direct_native_entry_cannot_substitute_an_unbound_deck(bundle):
    project, source, _, floor, pdk, _, plan, executions = bundle
    with pytest.raises(ValueError, match="CLOCK_PLAN_ASIC_SDC_SET_CHANGED"):
        current.clock_plan(project, plan, floor, [source], pdk)
    assert executions == [] and not plan.exists()


def test_declared_pdk_change_refuses_a_cached_measurement(bundle, monkeypatch):
    _, _, _, _, _, _, plan, _ = bundle
    assert emit(bundle)[0] == str(plan)
    monkeypatch.setattr(runner, "_read_declared_pdk_target", lambda _: "other_process")
    monkeypatch.setattr(runner, "_detect_pdk", lambda *_: SimpleNamespace(name="other_process"))
    assert check(bundle)[0] == 1


def test_resolved_pdk_identity_accepts_a_declaration_alias(bundle, monkeypatch):
    _, _, _, _, _, _, plan, _ = bundle
    monkeypatch.setattr(runner, "_read_declared_pdk_target", lambda _: "fixture_family")
    assert emit(bundle)[0] == str(plan)
    assert check(bundle)[0] == 0


def test_a_changed_source_record_refreshes_even_with_identical_sdc_bytes(bundle, monkeypatch):
    project, source, _, _, pdk, rec, plan, _ = bundle
    assert emit(bundle)[0] == str(plan)
    put(project, "phase1/generated_docs/L8_TIMING_WAVEFORM.json", '{"note":"new source context"}\n')
    fresh = step7_fixture(monkeypatch, project, pdk, source)
    assert fresh["sha256"] == rec["sha256"]
    result, notes = emit(bundle)
    assert result == str(plan), notes
    assert "ASIC source record changed" in "\n".join(notes)
    assert check(bundle)[0] == 0
