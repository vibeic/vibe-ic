"""A hardened child must use its parent's natively elaborated parameters."""
import json
import os
from pathlib import Path
import site
import subprocess

import pytest

import flow_engine as engine
import flow_native_adapters as adapters
from test_flow_child_macro_views import project


def design(root, *, supplied=None, parent_parameters=None, instances=("BUS",), unknown=False):
    source = project(root)
    (source / "tile.v").write_text(
        "module compute_tile #(parameter WIDTH=3" + (", parameter TAG=1'bx" if unknown else "")
        + ")(input [WIDTH-1:0] a, output [WIDTH-1:0] z); assign z=~a; endmodule\n")
    body = ["module neutral_wrapper #(parameter BUS=9)(input [31:0] a, output [31:0] z);"]
    for index, width in enumerate(instances):
        body.append(f"wire [31:0] unused_{index}; compute_tile #(.WIDTH({width})) u{index}"
                    f"(.a(a), .z(unused_{index}));")
    body.append("assign z=a; endmodule\n")
    (source / "wrapper.v").write_text("\n".join(body))
    for name, values in [("child", supplied), ("wrapper", parent_parameters)]:
        path = source / (name + ".json")
        config = json.loads(path.read_text())
        config.pop("DEFAULT_CORNER", None)
        if values is not None:
            config["SYNTH_PARAMETERS"] = values
        path.write_text(json.dumps(config))
    return source


def execute(root, monkeypatch, *, synthesize=False):
    # Direct LibreLane step callers supply the environment for embedded Python.
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(site.getsitepackages()))
    native_run = adapters.Commands.run
    children, netlists = [], []

    def public(commands, argv, **kwargs):
        if argv[0] == "yosys":
            return native_run(commands, argv, **kwargs)
        assert Path(argv[1]).name == "vibe_ic_one_shot_runner.py"
        child = Path(argv[2])
        children.append(child)
        if synthesize:
            from librelane.flows import Flow
            from librelane.common import Toolbox
            from librelane.state import State, DesignFormat
            from librelane.steps import Step

            config = json.loads((child / "work/flow/native_overrides.json").read_text())
            config.update(VERILOG_FILES=[str(path) for path in (child / "input/rtl").glob("*.v")],
                          VERILOG_INCLUDE_DIRS=[str(child / "input/rtl")], PDK="sky130A")
            owner = Flow.factory.get("Classic")(config, design_dir=str(child))
            state = State()
            toolbox = Toolbox(str(child / "tool_tmp"))
            for name in ("Yosys.JsonHeader", "Yosys.Synthesis"):
                state = Step.factory.get(name)(owner.config, state).start(
                    toolbox=toolbox, step_dir=str(child / name))
            netlist = Path(state.get_by_df(DesignFormat.NETLIST))
            output = child / "netlist.json"
            result = native_run(commands, ["yosys", "-Q", "-T", "-p",
                f'read_verilog "{netlist}"; hierarchy -top compute_tile; proc; write_json "{output}"'])
            assert result.returncode == 0
            netlists.append(json.loads(output.read_text())["modules"]["compute_tile"])
        # This bounded control measures native synthesis, without fabricating
        # final physical views or a full public-child completion report.
        return subprocess.CompletedProcess(argv, 0, "", "bounded child-input control")

    monkeypatch.setattr(adapters.Commands, "run", public)
    result = adapters.execute(root, root / "step", {"adapter": "macro_views"},
                              {"delivery_target": "ip_hardmacro"})
    return result, children, netlists


@pytest.mark.parametrize("supplied,parent_parameters,instances,width", [
    (None, None, ("BUS",), 9),
    (["WIDTH=9"], None, ("BUS",), 9),
    (None, ["BUS=11"], ("BUS",), 11),
    (None, None, ("BUS", "BUS"), 9),
])
def test_parent_binding_reaches_native_child_netlist(tmp_path, monkeypatch, supplied,
                                                     parent_parameters, instances, width):
    design(tmp_path, supplied=supplied, parent_parameters=parent_parameters, instances=instances)
    result, children, netlists = execute(tmp_path, monkeypatch, synthesize=True)
    assert len(children) == len(netlists) == 1, result
    for port in ("a", "z"):
        assert len(netlists[0]["ports"][port]["bits"]) == width
    config = json.loads((children[0] / "work/flow/native_overrides.json").read_text())
    assert config["SYNTH_PARAMETERS"] == [f"WIDTH={width}"]
    assert engine.evaluate(engine.ToolResult(**result), []) == "NOT_MEASURED"
    assert "flow_engine.json" in result["detail"]


@pytest.mark.parametrize("supplied,instances,unknown,reason", [
    (["WIDTH=4"], ("BUS",), False, "SYNTH_PARAMETERS conflicts"),
    (None, ("BUS", "BUS+1"), False, "instances bind different parameter values"),
    (None, ("BUS",), True, "Unresolved parameter"),
])
def test_unresolved_or_conflicting_binding_never_hardens_defaults(tmp_path, monkeypatch,
                                                                 supplied, instances, unknown, reason):
    design(tmp_path, supplied=supplied, instances=instances, unknown=unknown)
    result, children, _ = execute(tmp_path, monkeypatch)
    assert engine.evaluate(engine.ToolResult(**result), []) == "NOT_MEASURED", result
    assert reason in result["detail"]
    assert children == []


def test_native_hierarchy_handles_source_paths_with_spaces(tmp_path, monkeypatch):
    root = tmp_path / "design with spaces"
    design(root)
    result, children, _ = execute(root, monkeypatch)
    assert len(children) == 1, result
    config = json.loads((children[0] / "work/flow/native_overrides.json").read_text())
    assert config["SYNTH_PARAMETERS"] == ["WIDTH=9"]


def test_missing_parent_parameter_metadata_does_not_use_child_defaults(tmp_path, monkeypatch):
    source = design(tmp_path)
    (source / "wrapper.v").write_text(
        "module neutral_wrapper(input [8:0] a, output [8:0] z); compute_tile u(.a(a), .z(z)); endmodule\n"
        "(* blackbox *) module compute_tile(input [8:0] a, output [8:0] z); endmodule\n")
    result, children, _ = execute(tmp_path, monkeypatch)
    assert engine.evaluate(engine.ToolResult(**result), []) == "NOT_MEASURED", result
    assert "did not resolve child parameters" in result["detail"] and "WIDTH" in result["detail"]
    assert children == []


def test_parent_uses_native_shared_macro_definition_context(tmp_path, monkeypatch):
    source = design(tmp_path)
    (source / "widths.v").write_text("`define BUS_WIDTH 9\n")
    wrapper = source / "wrapper.v"
    wrapper.write_text(wrapper.read_text().replace("parameter BUS=9", "parameter BUS=`BUS_WIDTH"))
    config = source / "wrapper.json"
    raw = json.loads(config.read_text())
    raw["VERILOG_FILES"] = [str(source / "widths.v"), str(wrapper)]
    config.write_text(json.dumps(raw))
    result, children, _ = execute(tmp_path, monkeypatch)
    assert len(children) == 1, result
    child_config = json.loads((children[0] / "work/flow/native_overrides.json").read_text())
    assert child_config["SYNTH_PARAMETERS"] == ["WIDTH=9"]
