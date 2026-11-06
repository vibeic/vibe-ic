"""Connect analog physical rows to native State and earlier tool products."""
from __future__ import annotations

from pathlib import Path
import json
from types import SimpleNamespace
import vibeic_temp


NATIVE = {
    "die_floorplan_and_macros": {"steps": ["OpenROAD.Floorplan", "Odb.ManualMacroPlacement"]},
    "io_pad_ring_and_power_distribution": {"steps": ["OpenROAD.PadRing", "OpenROAD.GeneratePDN"]},
    "routed_candidate_physical_checks": {"steps": ["KLayout.DRC", "Magic.SpiceExtraction", "Netgen.LVS"]},
    "antenna_checks": {"steps": ["OpenROAD.CheckAntennas", "KLayout.Antenna", "Checker.KLayoutAntenna"]},
    "candidate_parasitic_extraction": {"steps": ["Magic.RCX"]},
    "candidate_electromigration": {"steps": ["VibeIC.EMCorners"], "imports": ["flow_em_corners"]},
    "stream_out": {"steps": ["Magic.StreamOut", "KLayout.StreamOut", "KLayout.XOR", "Checker.XOR"]},
    "final_geometry_rc_and_pex": {"steps": ["Magic.RCX"]},
}


def _result(detail, *, metrics=None, reports=(), ran=False, status="NOT_MEASURED", reused=False):
    return {"status": status, "detail": detail, "metrics": metrics or {},
            "outputs": list(map(str, reports)), "native_ran": ran, "reused_native": reused}


def _earlier_state(project, name):
    """Read the nearest earlier native State, using the public table's order."""
    table = json.loads((Path(__file__).parents[1] / "flow/steps.json").read_text())["steps"]
    preceding = []
    for row in table:
        if row["name"] == name:
            break
        preceding.append(row["name"])
    for previous in reversed(preceding):
        states = sorted([*(path for parent in (project / "steps", vibeic_temp.current_run())
                           for path in (parent / previous).glob("**/state_out.json")),
                         *(project / "reports/native").glob(f"*/{previous}/**/state_out.json")],
                        key=lambda path: path.stat().st_mtime_ns, reverse=True)
        for path in states:
            config = path.with_name("config.json")
            if config.is_file():
                from librelane.state import State
                return State.load(json.loads(path.read_text())), json.loads(config.read_text())
    return None, {}


def _native(project, directory, tool, route, state, config):
    from librelane.common import Toolbox
    from librelane.config import Config
    from librelane.flows import Flow
    from flow_engine import NativeChain, evaluate

    chain = NativeChain(project, route)
    kind = "Chip" if route["delivery_target"] in {"gds", "shippable_gds", "foundry_handoff"} else "Classic"
    chain.owner = SimpleNamespace(config=Config(config),
        gating_config_vars=Flow.factory.get(kind).gating_config_vars)
    chain.state, chain.config = state, dict(config)
    chain.toolbox = Toolbox(str(directory / "tool_tmp"))
    result = chain.execute(directory, tool)
    return {**_result(result.detail or "Native physical result against the unchanged row limits.",
                   metrics=result.metrics, reports=result.reports, ran=result.ran,
                   status=evaluate(result, [])), "exit_code": result.exit_code,
            "native_steps": result.native_steps, "tool_seconds": result.tool_seconds}


def _power(project):
    path = project / "steps/analog_reliability/result.json"
    if path.is_file():
        previous = json.loads(path.read_text())
        rails = previous.get("native_metrics", {}).get("rails")
        if rails:
            return _result("Earlier native rail measurements are reported; delivery-level mission and load coverage are not measured.",
                metrics={"rails": rails}, reports=[path], ran=bool(previous.get("tool_ran")), reused=True)
    return _result("No native analog delivery supply-current waveform or document-derived mission/load measurement was produced by earlier steps.")


def execute(name, project, directory, run, *, state=None, config=None, route=None):
    project, directory = Path(project), Path(directory)
    config, route = config or {}, route or {}
    if name == "candidate_power_analysis":
        return _power(project)
    if name == "candidate_signal_integrity":
        return _result("No coupled analog extraction and document-derived aggressor/victim transient testbench were produced by earlier steps.")
    if name == "final_electrical_analysis":
        return _result("No final analog delivery SPICE mission testbench was generated from the L documents and final native parasitics.")
    produced_state, produced_config = _earlier_state(project, name)
    state = produced_state if produced_state is not None else state
    config = config or produced_config
    if state is None:
        return _result("Native physical State has not been produced by earlier steps; analog macro views, placement and routing remain unavailable.")
    if not config:
        return _result("Native PDK and tool configuration has not been produced from the L documents.")
    if not route.get("delivery_target"):
        return _result("The public runner's delivery selection is unavailable.")
    if name == "candidate_ir_drop":
        from flow_ir_corners import execute as ir
        static = "VibeIC.IRDropCorners" if route["delivery_target"] in {"gds", "shippable_gds", "foundry_handoff"} else "OpenROAD.IRDropReport"
        tool = {"steps": [static, "Vibeic.TransientIR"],
                "imports": ["flow_ir_corners", "librelane_plugins.librelane_plugin_vibeic.ir_drop"]}
        result = ir(project, directory, tool, route, state=state, config=config)
        from flow_engine import ToolResult, evaluate
        return {**_result(result.get("detail", "Native IR report"), metrics=result.get("metrics"),
                       reports=result.get("reports", []), ran=result.get("ran", False),
                       status=evaluate(ToolResult(**result), [])), "exit_code": result.get("exit_code"),
                "native_steps": result.get("native_steps", []), "tool_seconds": result.get("tool_seconds", 0)}
    return _native(project, directory, NATIVE[name], route, state, config)
