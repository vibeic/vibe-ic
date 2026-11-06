import json
from pathlib import Path
import re
import shutil
import subprocess
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


@pytest.mark.parametrize("time_unit,cap_unit,scale", [("ns", "pf", 1), ("ps", "ff", 1000)])
@pytest.mark.parametrize("original_fanout,original_slew,original_cap", [
    (None, None, None), (10, 2, .9), (.5, .00001, .01),
])
def test_supplied_sdc_enforces_declared_limits_without_weakening_original_rules(
        tmp_path, monkeypatch, original_fanout, original_slew, original_cap,
        time_unit, cap_unit, scale):
    sta = shutil.which("sta")
    if sta is None:
        pytest.skip("Native OpenSTA required for supplied-SDC electrical limits")
    install = tmp_path / "installed"
    write(install / "flow/platforms/process/config.mk", "")
    write(install / "tools/AutoTuner/src/autotuner/__init__.py", "")
    space = write(tmp_path / "space.json", "{}")
    liberty_text = f'''library (cells) {{
      delay_model : table_lookup;
      time_unit : "1{time_unit}";
      voltage_unit : "1V";
      current_unit : "1mA";
      capacitive_load_unit (1,{cap_unit});
      nom_voltage : 1; nom_temperature : 25; nom_process : 1;
      default_fanout_load : 1; default_max_fanout : 10;
      default_max_transition : {2 * scale};
      cell (buffer) {{
        pin (A) {{ direction : input; capacitance : {.2 * scale}; }}
        pin (Z) {{ direction : output; function : "A"; max_capacitance : {.9 * scale}; }}
      }}
    }}'''
    liberty = write(tmp_path / "cells.lib", liberty_text)
    netlist = write(tmp_path / "unit.v", '''module unit(input a, spare, output y, z);
      wire n;
      buffer u1(.A(a), .Z(n));
      buffer u2(.A(n), .Z(y));
      buffer u3(.A(n), .Z(z));
    endmodule''')
    original = [f"set_units -time {time_unit} -capacitance {cap_unit}",
                "set_max_fanout 0.25 [get_ports spare]",
                f"set_max_transition {0.000001 * scale:g} [get_ports spare]",
                f"set_max_capacitance {.8 * scale:g} [get_pins u2/Z]"]
    for value, command, objects in (
        (original_fanout, "set_max_fanout", "[current_design]"),
        (original_slew, "set_max_transition", "[current_design]"),
        (original_cap, "set_max_capacitance", "[get_pins u1/Z]"),
    ):
        if value is not None:
            original.append(f"{command} {value if command == 'set_max_fanout' else value * scale:g} {objects}")
    sdc = write(tmp_path / "original.sdc", "\n".join(original) + "\n")
    before = sdc.read_bytes()
    config = Config(DESIGN_NAME="unit", VERILOG_FILES=[str(netlist)],
                    CELL_LEFS=[str(write(tmp_path / "cells.lef"))], LIB={"typ": [str(liberty)]},
                    TECH_LEFS={"typ": str(write(tmp_path / "tech.lef"))},
                    PLACE_SITE="site", PNR_SDC_FILE=str(sdc))
    class Toolbox:
        def __init__(self, directory):
            pass
        def filter_views(self, config, mapping):
            return level3._files(mapping)
    native_modules(monkeypatch, toolbox=Toolbox)
    native, _, _ = level3._orfs_inputs(SimpleNamespace(config=config), {
        "MAX_FANOUT_CONSTRAINT": 1, "MAX_TRANSITION_CONSTRAINT": .001,
        "MAX_CAPACITANCE_CONSTRAINT": .1}, level3.Orfs(install, "process", space), tmp_path / "arm")
    translated = native / "flow/designs/process/unit/constraint.sdc"
    script = write(tmp_path / "check.tcl", f'''read_liberty {{{liberty}}}
read_verilog {{{netlist}}}
link_design unit
read_sdc {{{sdc}}}
puts "ORIGINAL_CAP_VIOLATIONS [sta::max_capacitance_violation_count]"
read_sdc {{{translated}}}
puts "NATIVE_FANOUT_VIOLATIONS [sta::max_fanout_violation_count]"
puts "NATIVE_CAP_VIOLATIONS [sta::max_capacitance_violation_count]"
create_clock -name subsequent -period {2 * scale:g} [get_ports a]
write_sdc -digits 9 {{{tmp_path / 'effective.sdc'}}}
set sta_report_default_digits 6
report_check_types -max_fanout -max_count 20 -verbose
foreach command {{set_cell_fanout_limit set_slew_limit_cell set_pin_capacitance_limit}} {{
  puts "REMAINING_TRACES [trace info execution ::sta::$command]"
}}
exit
''')
    process = subprocess.run([sta, "-no_init", "-no_splash", "-exit", str(script)],
                             capture_output=True, text=True, check=True)
    assert "Error" not in process.stdout + process.stderr, process.stdout + process.stderr
    original_violations = int(re.search(r"ORIGINAL_CAP_VIOLATIONS (\d+)", process.stdout)[1])
    assert original_violations == int(original_cap is not None and original_cap < .4)
    assert int(re.search(r"NATIVE_FANOUT_VIOLATIONS (\d+)", process.stdout)[1]) > 0
    assert int(re.search(r"NATIVE_CAP_VIOLATIONS (\d+)", process.stdout)[1]) > 0
    assert re.findall(r"REMAINING_TRACES(.*)", process.stdout) == [" ", " ", " "]
    effective = (tmp_path / "effective.sdc").read_text()
    for command, expected, objects in (
        ("set_max_fanout", min(original_fanout or 1, 1), r"\[current_design\]"),
        ("set_max_transition", min(original_slew or .001, .001), r"\[current_design\]"),
        ("set_max_capacitance", min(original_cap or .1, .1), r"\[get_pins \{u1/Z\}\]"),
        ("set_max_transition", .000001, r"\[get_ports \{spare\}\]"),
        ("set_max_capacitance", .8, r"\[get_pins \{u2/Z\}\]"),
    ):
        match = re.search(command + r" ([\d.eE+-]+) " + objects, effective)
        assert match, effective
        physical_value = float(match[1]) / (1 if command == "set_max_fanout" else scale)
        assert physical_value == pytest.approx(expected), effective
    clock = re.search(r"create_clock -name subsequent -period ([\d.eE+-]+)", effective)
    assert clock and float(clock[1]) / scale == pytest.approx(2), effective
    assert sdc.read_bytes() == before
    assert (translated.parent / "constraint-original.sdc").read_bytes() == before


def test_supplied_sdc_failure_removes_temporary_native_traces(tmp_path):
    sta = shutil.which("sta")
    if sta is None:
        pytest.skip("Native OpenSTA required for supplied-SDC trace cleanup")
    original = write(tmp_path / "original.sdc", "error {original deck failure}\n")
    translated = tmp_path / "constraint.sdc"
    level3._orfs_sdc(original, {"MAX_FANOUT_CONSTRAINT": 1}, translated)
    script = write(tmp_path / "failure.tcl", f'''catch {{source {{{translated}}}}} message
puts "ORIGINAL_ERROR $message"
foreach command {{set_cell_fanout_limit set_slew_limit_cell set_pin_capacitance_limit}} {{
  puts "REMAINING_TRACES [trace info execution ::sta::$command]"
}}
puts "REMAINING_NAMESPACE [namespace exists ::level3_sdc]"
exit
''')
    process = subprocess.run([sta, "-no_init", "-no_splash", "-exit", str(script)],
                             capture_output=True, text=True, check=True)
    assert "ORIGINAL_ERROR original deck failure" in process.stdout
    assert re.findall(r"REMAINING_TRACES(.*)", process.stdout) == [" ", " ", " "]
    assert "REMAINING_NAMESPACE 0" in process.stdout


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
