from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from librelane.common import GenericDictEncoder, Toolbox
from librelane.flows import Flow
from librelane.state import State
from librelane.steps import Step, StepException
from librelane.steps.openroad import IRDropReport


@Step.factory.register()
class IRDropCorners(IRDropReport):
    id = "VibeIC.IRDropCorners"
    name = "IR drop at maximum RC corners"
    long_name = name
    report_class = IRDropReport

    def run(self, state_in, **kwargs):
        corners = [corner for corner in self.config["STA_CORNERS"] if corner.startswith("max_")]
        if not corners:
            raise StepException("NOT_MEASURED: STA_CORNERS has no maximum RC corner")
        root = Path(self.step_dir).resolve()
        summaries, metrics = {}, {}
        for corner in corners:
            config = self.config.copy(DEFAULT_CORNER=corner)
            libraries = self.toolbox.filter_views(config, config["LIB"])
            voltage = self.toolbox.get_lib_voltage(str(libraries[0])) if libraries else None
            if voltage is None or not math.isfinite(float(voltage)) or voltage <= 0:
                raise StepException(f"NOT_MEASURED: supply voltage is missing for {corner}")
            emitted = {}

            class ObservedIRDrop(self.report_class):
                def run(self, *args, **kwargs):
                    views, updates = super().run(*args, **kwargs)
                    emitted.update(updates)
                    return views, updates

            native = ObservedIRDrop(config, state_in)
            destination = root / corner
            destination.mkdir(parents=True, exist_ok=True)
            working_directory = Path.cwd()
            try:
                os.chdir(destination)
                native.start(toolbox=self.toolbox, step_dir=str(destination), **kwargs)
            finally:
                os.chdir(working_directory)
            if "ir__drop__worst" not in emitted:
                raise StepException(f"NOT_MEASURED: native IR report has no worst drop for {corner}")
            percentage = float(emitted["ir__drop__worst"]) / float(voltage) * 100
            emitted["ir__drop__worst__pct"] = percentage
            metrics.update({f"{key}__corner:{corner}": value for key, value in emitted.items()})
            summaries[corner] = {"voltage": voltage, "metrics": emitted,
                                 "report": str(destination / "irdrop.rpt")}
        metrics["ir__drop__worst"] = max(row["metrics"]["ir__drop__worst"] for row in summaries.values())
        metrics["ir__drop__worst__pct"] = max(row["metrics"]["ir__drop__worst__pct"] for row in summaries.values())
        (root / "ir_corners.json").write_text(json.dumps(summaries, cls=GenericDictEncoder, indent=2) + "\n")
        return {}, metrics


def execute(project, directory, tool, route, *, state=None, config=None):
    from types import SimpleNamespace
    from librelane.config import Config
    from flow_engine import NativeChain, ToolResult

    if state is None or not config:
        return ToolResult(detail="IR analysis needs captured native State and configuration.").__dict__
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    kind = "Chip" if route["delivery_target"] in {"gds", "shippable_gds", "foundry_handoff"} else "Classic"
    chain = NativeChain(Path(project), route)
    chain.owner = SimpleNamespace(config=Config(config),
        gating_config_vars=Flow.factory.get(kind).gating_config_vars)
    chain.state, chain.config = state, dict(config)
    chain.toolbox = Toolbox(str(directory / "tool_tmp"))
    result = chain.execute(directory, tool)
    static = result.metrics.get("ir__drop__worst__pct")
    if static is not None:
        result.metrics["ir__drop__static__worst__pct"] = static
    drop = result.metrics.get("vibeic__ir_dynamic__drop__worst")
    scaled = result.metrics.get("vibeic__ir_dynamic__scaled_static_bound")
    reason = ""
    if drop is None:
        reason = "Native transient IR produced no dynamic drop."
    elif scaled != 0:
        reason = "Native transient IR is a scaled static bound; dynamic response was not measured."
    else:
        libraries = chain.toolbox.filter_views(chain.owner.config, chain.owner.config["LIB"])
        voltage = chain.toolbox.get_lib_voltage(str(libraries[0])) if libraries else None
        if voltage is None or not math.isfinite(float(voltage)) or voltage <= 0:
            reason = "Native transient IR has no supply voltage for its selected corner."
        else:
            percentage = float(drop) / float(voltage) * 100
            result.metrics["ir__drop__dynamic__worst__pct"] = percentage
            result.metrics["ir__drop__worst__pct"] = max(static, percentage) if static is not None else percentage
    if reason:
        dynamic = next((row for row in result.native_steps if row["name"] == "Vibeic.TransientIR"), None)
        if dynamic is None:
            dynamic = {"name": "Vibeic.TransientIR", "ran": False, "exit_code": None}
            result.native_steps.append(dynamic)
        if dynamic.get("status") != "FAIL":
            detail = dynamic.get("detail", "")
            dynamic.update(status="NOT_MEASURED", detail=detail + (" " if detail else "") + reason)
        result.detail += " " + reason
    return result.__dict__


def main():
    parser = argparse.ArgumentParser(description="Run native IR drop at configured maximum RC corners")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project, output = args.project.resolve(), args.output.resolve()
    config = json.loads(args.config.read_text())
    state = State.load(json.loads(args.state.read_text()))
    owner = Flow.factory.get("Chip")(config, design_dir=str(project), pdk_root=os.environ.get("PDK_ROOT"))
    output.mkdir(parents=True, exist_ok=True)
    toolbox = Toolbox(str(output / "tool_tmp"))
    step = IRDropCorners(owner.config, state)
    working_directory = Path.cwd()
    try:
        os.chdir(output)
        step.start(toolbox=toolbox, step_dir=str(output))
    finally:
        os.chdir(working_directory)


if __name__ == "__main__":
    main()
