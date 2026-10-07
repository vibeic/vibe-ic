"""Accepted physical source controls for Steps16/31/37.5ip; no native claim."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _physical_current as current
import clock_plan_check as clock_gate
import phase3_one_shot_runner as runner
from _clock_plan_fixture import step7_fixture


def put(project, name, text):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def clock_project(tmp_path, monkeypatch):
    floor = put(tmp_path, "phase3/stage3/pnr/floorplan.def", "DESIGN neutral ;\nEND DESIGN\n")
    sdc = put(tmp_path, "phase2/stage2/constraints/current.sdc",
              "create_clock -name system -period 12 [get_ports tick]\n")
    tech = put(tmp_path, "input/pdk/tech.lef", "VERSION 5.8 ;\nEND LIBRARY\n")
    cell = put(tmp_path, "input/pdk/cell.lef", "MACRO neutral\nEND neutral\n")
    pdk = SimpleNamespace(name="open_fixture", tech_lef=str(tech), cell_lef=str(cell), macro_lefs=[])
    def native(project, tool, args, log):
        Path(log).write_text("CLOCK_PLAN_PDK open_fixture\nCLOCK_PLAN_NATIVE system|12|tick\nCLOCK_PLAN_DONE\n")
        return 0, {"rc": 0, "argv": [tool, *args]}
    monkeypatch.setattr(current, "run_native", native)
    monkeypatch.setattr(runner, "_read_declared_pdk_target", lambda p: pdk.name)
    monkeypatch.setattr(runner, "_detect_pdk", lambda *a: pdk)
    step7_fixture(monkeypatch, tmp_path, pdk, sdc)
    plan = tmp_path / "phase3/stage3/cts/clock_plan.json"
    notes = []
    assert runner.emit_clock_plan(tmp_path, plan, floor, floor.parent, notes) == str(plan), notes
    return tmp_path, plan, sdc


def gate(project):
    return clock_gate.main([str(project), "--json", str(project / "clock_check.json")])


def test_ordinary_clock_producer_is_consumed(clock_project):
    project, plan, _ = clock_project
    assert gate(project) == 0
    assert json.loads(plan.read_text())["current"]["step"] == "16"


@pytest.mark.parametrize("field,value", [("step", "19"), ("stage", "stage4"),
                                       ("tool", "python"), ("design", "other"),
                                       ("pdk", "wrong")])
def test_clock_context_mutation_refuses(clock_project, field, value):
    project, plan, _ = clock_project
    doc = json.loads(plan.read_text())
    doc["current"][field] = value
    plan.write_text(json.dumps(doc))
    assert gate(project) == 1


@pytest.mark.parametrize("mutation", ["sdc", "floorplan", "log", "execution", "values", "removed_producer"])
def test_clock_substantive_reverse(clock_project, mutation):
    project, plan, sdc = clock_project
    doc = json.loads(plan.read_text())
    if mutation == "sdc":
        sdc.write_text(sdc.read_text().replace("12", "15"))
    elif mutation == "floorplan":
        (project / "phase3/stage3/pnr/floorplan.def").write_text("DESIGN other ;\n")
    elif mutation == "log":
        (project / doc["current"]["outputs"]["log"]["path"]).write_text("no execution\n")
    elif mutation == "execution":
        doc["current"]["execution"]["rc"] = 9
    elif mutation == "values":
        doc["clocks"][0]["period_ns"] = 100
    else:
        doc.pop("current")
    plan.write_text(json.dumps(doc))
    assert gate(project) == 1


def test_no_sdc_never_produces_nominal_clock(clock_project):
    project, plan, sdc = clock_project
    sdc.unlink()
    plan.unlink()
    notes = []
    floor = project / "phase3/stage3/pnr/floorplan.def"
    assert runner.emit_clock_plan(project, plan, floor, floor.parent, notes) is None
    assert plan.exists() is False
    assert gate(project) == 1


def test_direct_producer_failure_precedence(tmp_path):
    row = runner.StepResult("drc", "FAIL", 0.0, "measured violation")
    result = current.direct_half(tmp_path, "neutral", SimpleNamespace(), "drc", lambda: row)
    assert result.status == "FAIL"


def test_current_inputs_are_in_scope(tmp_path):
    escaped = tmp_path.parent / "escaped_current.txt"
    escaped.write_text("outside")
    try:
        with pytest.raises(ValueError, match="CURRENT_PATH_ESCAPES"):
            current.entry(tmp_path, escaped)
    finally:
        escaped.unlink()


def test_ip_ordinary_producer_invokes_kit_consumer(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "_ip_delivery_declared_na", lambda p: (False, "", {}))
    def run(name, argv, t0, **kw):
        calls.append(Path(argv[1]).stem)
        return SimpleNamespace(returncode=0 if len(calls) == 1 else 1, stdout="fixture", stderr=""), None
    monkeypatch.setattr(runner, "_run_producer", run)
    row = runner.step_digital_hardmacro_gen(tmp_path)
    assert calls == ["digital_hardmacro_gen", "digital_hardmacro_check"]
    assert row.status == "FAIL"


def test_kit_gate_refuses_unbound_views(tmp_path):
    import digital_hardmacro_check as kit
    from test_digital_hardmacro_gen import make_project
    make_project(tmp_path)
    hm = tmp_path / "phase3/stage4/hardmacro"
    hm.mkdir()
    put(tmp_path, "phase3/stage4/hardmacro/macro_a.v", "module macro_a(); endmodule\n")
    result = kit.run_audit(tmp_path)
    assert result.passed is False
    assert "IP_KIT_CURRENT_REFUSED" in {f.rule for f in result.findings}
