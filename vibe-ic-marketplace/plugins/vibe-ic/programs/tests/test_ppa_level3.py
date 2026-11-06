import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

import ppa_level3 as level3


def write(path, value="native content\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    return path


def native_modules(monkeypatch, flow=None, toolbox=None):
    package = ModuleType("librelane")
    flows = ModuleType("librelane.flows")
    flows.Flow = flow
    common = ModuleType("librelane.common")
    common.Toolbox = toolbox
    monkeypatch.setitem(sys.modules, "librelane", package)
    monkeypatch.setitem(sys.modules, "librelane.flows", flows)
    monkeypatch.setitem(sys.modules, "librelane.common", common)


def test_supervised_child_receives_argv_cwd_env_and_keeps_failure(tmp_path):
    script = write(tmp_path / "child.py", '''import json,os,sys
from pathlib import Path
Path('observed.json').write_text(json.dumps({
    'args':sys.argv[1:],'cwd':os.getcwd(),'value':os.environ['LEVEL3_FIXTURE'],
    'tmp':os.environ['TMPDIR']}))
print('native stdout')
print('native stderr',file=sys.stderr)
sys.exit(7)
''')
    scratch = tmp_path / "scratch"
    result = level3._command([sys.executable, str(script), "literal argument", "$unexpanded"],
                             tmp_path, tmp_path / "native.log", {"LEVEL3_FIXTURE": "present",
                             "FLEET_SCRATCH": str(scratch)})
    observed = json.loads((tmp_path / "observed.json").read_text())
    assert observed["args"] == ["literal argument", "$unexpanded"]
    assert observed["cwd"] == str(tmp_path)
    assert observed["value"] == "present"
    assert Path(observed["tmp"]).parent == scratch
    assert not Path(observed["tmp"]).exists()
    assert not list(scratch.iterdir())
    assert result.rc == 7
    assert "native stdout" in (tmp_path / "native.log").read_text()
    assert "native stderr" in (tmp_path / "native.log").read_text()


def test_snapshot_keeps_documents_rtl_constraints_and_drops_generated_choices(tmp_path):
    project = tmp_path / "project"
    kept = ["input/docs/spec.md", "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
            "phase2/stage1/rtl/unit.v", "phase3/stage3/pnr/constraint.sdc"]
    for name in kept:
        write(project / name)
    declaration = {"top_module": "unit", "FP_CORE_UTIL": 90, "SYNTH_STRATEGY": "DELAY 4"}
    write(project / "plugin_output/declaration.json", json.dumps(declaration))
    for name in ("work/flow/native_overrides.json", "reports/metrics.json", "input/flow109/result.json"):
        write(project / name)
    level3._snapshot(project, tmp_path / "snapshot")
    assert all((tmp_path / "snapshot" / name).read_text() == (project / name).read_text() for name in kept)
    assert json.loads((tmp_path / "snapshot/plugin_output/declaration.json").read_text()) == {"top_module": "unit"}
    assert not (tmp_path / "snapshot/work").exists()
    assert not (tmp_path / "snapshot/reports").exists()
    assert not (tmp_path / "snapshot/input/flow109").exists()
    assert json.loads((project / "plugin_output/declaration.json").read_text()) == declaration


def test_export_preserves_all_native_corners_and_publishes_only_complete_views(tmp_path):
    project, native, destination = [tmp_path / name for name in ("project", "native", "handoff")]
    write(project / "input/docs/spec.md", "original constraints\n")
    completed = {key: write(native / key / (key + ".dat"), key)
                 for key in ("settings", "odb", "def", "netlist", "reports", "metrics")}
    for key in ("sdc", "liberty", "spef"):
        completed[key] = {corner: write(native / corner / (key + ".dat"), corner + key)
                          for corner in ("fast", "slow")}
    best = level3._export(completed, project, destination, native)
    assert best == level3.NativeBest(destination / "index.json", native)
    index = json.loads(best.index.read_text())
    assert set(index) == {"documents", "settings", "odb", "def", "netlist", "sdc", "liberty", "spef", "reports", "metrics"}
    for key, paths in index.items():
        for path in paths if isinstance(paths, list) else [paths]:
            assert not Path(path).is_absolute()
            assert (destination / path).is_file()
    for key in ("sdc", "liberty", "spef"):
        assert {(destination / path).read_text() for path in index[key]} == {"fast" + key, "slow" + key}
    assert json.loads((destination / "job.json").read_text()) == {"keep_run": True}
    completed["spef"] = []
    with pytest.raises(level3._Unavailable, match="spef"):
        level3._export(completed, project, tmp_path / "incomplete", native)
    assert not (tmp_path / "incomplete/index.json").exists()


class Config(dict):
    def copy(self, **changes):
        return Config({**self, **changes})


def test_failed_attractive_synthesis_candidate_is_never_exported(tmp_path, monkeypatch):
    candidates = [SimpleNamespace(id="sta-AREA 0", config=Config(SYNTH_STRATEGY="AREA 0"),
                  state_out=SimpleNamespace(metrics={"design__instance__area": 1})),
                  SimpleNamespace(id="sta-AREA 1", config=Config(SYNTH_STRATEGY="AREA 1"),
                  state_out=SimpleNamespace(metrics={"design__instance__area": 2})),
                  SimpleNamespace(id="sta-AREA 2", config=Config(SYNTH_STRATEGY="AREA 2"), state_out=None)]
    search = SimpleNamespace(step_objects=candidates, start=lambda **kwargs: None)
    native_modules(monkeypatch, SimpleNamespace(factory=SimpleNamespace(get=lambda tool: lambda config: search)))
    attempted = []
    def complete(owner, config, project, root):
        attempted.append(config["SYNTH_STRATEGY"])
        if config["SYNTH_STRATEGY"] == "AREA 0":
            raise RuntimeError("native hold violation")
        return {"settings": [], "reports": [], "odb": "native selected odb"}
    monkeypatch.setattr(level3, "_ll_complete", complete)
    result = level3._librelane(SimpleNamespace(config=Config()), {}, tmp_path, "SynthesisExploration", tmp_path)
    assert attempted == ["AREA 0", "AREA 1"]
    assert result["odb"] == "native selected odb"
    assert "synthesis area" in json.loads((tmp_path / "selection.json").read_text())["criterion"]


@pytest.mark.parametrize("tool,fixed", [("SynthesisExploration", {"SYNTH_STRATEGY": "AREA 1"}),
                                       ("Optimizing", {"FP_CORE_UTIL": 44})])
def test_native_search_cannot_override_document_fixed_values(tmp_path, monkeypatch, tool, fixed):
    native_modules(monkeypatch)
    with pytest.raises(level3._Unavailable, match="document-fixed"):
        level3._librelane(SimpleNamespace(config=Config()), fixed, tmp_path, tool, tmp_path)


def test_optimizing_retains_native_winning_strategy_and_utilization(tmp_path, monkeypatch):
    selected = Config(SYNTH_STRATEGY="DELAY 1", FP_CORE_UTIL=40)
    search = SimpleNamespace(step_objects=[SimpleNamespace(id="gpl-lowutl", config=selected,
                             state_out=object())], start=lambda **kwargs: None)
    native_modules(monkeypatch, SimpleNamespace(factory=SimpleNamespace(get=lambda tool: lambda config: search)))
    def complete(owner, config, project, root):
        assert config == selected
        return {"settings": [], "reports": []}
    monkeypatch.setattr(level3, "_ll_complete", complete)
    level3._librelane(SimpleNamespace(config=Config(SYNTH_STRATEGY="AREA 0", FP_CORE_UTIL=50)),
                      {}, tmp_path, "Optimizing", tmp_path)


def test_document_fixed_orfs_translation_keeps_sdc_and_native_defaults(tmp_path, monkeypatch):
    install = tmp_path / "installed"
    write(install / "flow/platforms/process/config.mk", "export PLACE_DENSITY ?= 0.61\n")
    write(install / "tools/AutoTuner/src/autotuner/__init__.py", "")
    space = write(tmp_path / "space.json", json.dumps({"CORE_UTILIZATION": {"minmax": [20, 80]},
                  "PLACE_DENSITY": {"minmax": [.3, .8]}, "_SDC_CLK_PERIOD": {"minmax": [1, 20]},
                  "CELL_PAD_IN_SITES_GLOBAL_PLACEMENT": {"minmax": [0, 4]}}))
    sdc = write(tmp_path / "original.sdc", "create_clock -period 8.25 [get_ports clk]\n")
    liberty = write(tmp_path / "view.lib")
    tech = write(tmp_path / "tech.lef")
    config = Config(DESIGN_NAME="unit", VERILOG_FILES=[str(write(tmp_path / "unit.v"))],
                    CELL_LEFS=[str(write(tmp_path / "cells.lef"))], LIB={"typ": [str(liberty)]},
                    TECH_LEFS={"typ": str(tech)}, PLACE_SITE="site", PNR_SDC_FILE=str(sdc))
    class Toolbox:
        def __init__(self, directory):
            pass
        def filter_views(self, config, mapping):
            return level3._files(mapping)
    native_modules(monkeypatch, toolbox=Toolbox)
    root = tmp_path / "arm"
    native, output_space, libs = level3._orfs_inputs(SimpleNamespace(config=config),
        {"FP_CORE_UTIL": 44, "CLOCK_PERIOD": 8.25}, level3.Orfs(install, "process", space), root)
    translated = (native / "flow/designs/process/unit/config.mk").read_text()
    dimensions = json.loads(output_space.read_text())
    assert "CORE_UTILIZATION = 44" in translated
    assert "PLACE_DENSITY =" not in translated
    assert "LIB_FILES = " + str(liberty) in translated
    assert "CORE_UTILIZATION" not in dimensions
    assert "_SDC_CLK_PERIOD" not in dimensions
    assert "PLACE_DENSITY" in dimensions
    assert (output_space.parent / dimensions["_SDC_FILE_PATH"]).read_bytes() == sdc.read_bytes()
    assert libs == [liberty]
    assert (install / "flow/platforms/process/config.mk").read_text() == "export PLACE_DENSITY ?= 0.61\n"


def test_native_child_records_missing_dependency(tmp_path, monkeypatch):
    def missing(*args):
        raise ImportError("native package absent")
    monkeypatch.setattr(level3, "_prepare", missing)
    job = write(tmp_path / "job.json", json.dumps({"root": str(tmp_path), "project": str(tmp_path),
                "route": "ip", "pdk_root": str(tmp_path)}))
    assert level3._native(job) == 2
    assert json.loads((tmp_path / "incomplete.json").read_text()) == {
        "status": "NOT_MEASURED", "reason": "native package absent"}


@pytest.mark.parametrize("setting,metric", [
    ("MAX_TRANSITION_CONSTRAINT", "design__max_slew_violation__count"),
    ("MAX_CAPACITANCE_CONSTRAINT", "design__max_cap_violation__count"),
])
def test_declared_electrical_violation_cannot_pass_when_native_checker_warns(tmp_path, setting, metric):
    write(tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", json.dumps({"fields": {
        "constraint_declarations": [{"kind": "flow_setting", "token": setting, "value": .25}]}}))
    with pytest.raises(RuntimeError, match=setting + "=0.25"):
        level3._declared_checks(tmp_path, {}, {metric: 1})
    with pytest.raises(level3._Unavailable, match="No native metric"):
        level3._declared_checks(tmp_path, {}, {})
    level3._declared_checks(tmp_path, {}, {metric: 0})


def test_output_boundary_rejects_external_directory_without_creating_it(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    output = tmp_path / "outside"
    with pytest.raises(ValueError, match="vibe-ic-temp/runs"):
        level3.run(tmp_path, output=output, route="ip", pdk_root=tmp_path)
    assert not output.exists()
