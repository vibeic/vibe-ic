"""Native pre-placement repair of an unplaced mapped netlist.

No floorplan, timing exception or clock-period change is introduced. Statistics
are recomputed by a read/stat-only Yosys invocation on the actual output.
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
from pathlib import Path
from librelane.state import DesignFormat
from librelane.steps.openroad import ResizerStep
from librelane.steps.step import Step, StepError


@Step.factory.register()
class PostMapRepair(ResizerStep):
    id = "Vibeic.PostMapRepair"
    name = "Repair mapped netlist before placement"
    inputs = [DesignFormat.NETLIST]
    outputs = [DesignFormat.NETLIST]

    def get_script_path(self):
        return str(Path(__file__).with_suffix(".tcl"))

    def run(self, state_in, **kwargs):
        views, metrics = super().run(state_in, **kwargs)
        output = views.get(DesignFormat.NETLIST)
        if output is None:
            raise StepError("post-map repair produced no netlist")
        libs = self.toolbox.filter_views(self.config, self.config["CELL_LIBS"])
        if len(libs) != 1 or self.config.get("MACROS"):
            raise StepError("post-map statistics requires one standard-cell library and no macros")
        folder = Path(self.step_dir)
        reports = folder / "reports"
        reports.mkdir(exist_ok=True)
        def quoted(s):
            s = str(s)
            if any(c in s for c in ('\n', '\r', '"', '\\')):
                raise StepError("unsupported Yosys statistics path")
            return '"' + s + '"'
        top = self.config["DESIGN_NAME"]
        if not top.replace('_', 'a').isalnum() or not top[0].isalpha():
            raise StepError("unsupported Yosys statistics top identifier")
        script = folder / "statistics.ys"
        script.write_text(
            "read_liberty -lib " + quoted(libs[0]) + "\n" +
            "read_verilog " + quoted(output) + "\n" +
            "hierarchy -check -top " + top + "\n" +
            "tee -o " + quoted(reports / "stat.rpt") + " stat -liberty " + quoted(libs[0]) + "\n" +
            "tee -o " + quoted(reports / "stat.json") + " stat -json -liberty " + quoted(libs[0]) + "\n")
        argv = ["yosys", "-Q", "-T", "-s", str(script)]
        with (folder / "statistics.log").open("w") as log:
            result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, timeout=120)
        if result.returncode:
            raise StepError("post-map native statistics failed; see statistics.log")
        stat = json.loads((reports / "stat.json").read_text())
        modules = stat["modules"]
        module = modules.get("\\" + top) or modules.get(top)
        if len(modules) != 1 or not isinstance(module, dict):
            raise StepError("post-map statistics did not establish one flattened top")
        measured = {"design__instance__count": module["num_cells"],
                    "design__instance__area": module["area"]}
        # The before/after record is observation, never functional equivalence.
        record = {"schema": "vibeic.postmap-observation.v1", "statistics_argv": argv,
                  "input_sha256": hashlib.sha256(Path(state_in[DesignFormat.NETLIST]).read_bytes()).hexdigest(),
                  "output_sha256": hashlib.sha256(Path(output).read_bytes()).hexdigest(),
                  "statistics_library": str(libs[0]), "measured": measured,
                  "equivalence": "NOT_MEASURED", "timing_acceptance": "NOT_MEASURED"}
        (folder / "postmap.json").write_text(json.dumps(record, indent=2) + "\n")
        return views, {**metrics, **measured}
