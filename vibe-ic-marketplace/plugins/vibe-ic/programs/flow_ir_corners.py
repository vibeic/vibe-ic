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

            class ObservedIRDrop(IRDropReport):
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
