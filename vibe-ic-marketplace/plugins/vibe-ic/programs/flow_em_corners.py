from __future__ import annotations

import math
from pathlib import Path
import re

from librelane.steps import Step, StepError, StepException
from librelane.steps.openroad import IRDropReport

from em_current_density_check import native_limits
from flow_ir_corners import IRDropCorners


def current_density_metrics(report: str, nets: list[str]) -> dict:
    counts, utilization = [], []
    complete = bool(nets)
    native_failed = False
    for net in nets:
        block = re.search(rf"^=== EM_NET {re.escape(net)} ===\s*$(.*?)(?=^=== EM_NET |\Z)",
                          report, re.M | re.S)
        body = block.group(1) if block else ""
        fields = {name: re.search(pattern, body, re.M) for name, pattern in {
            "violations": r"^Violations\s*:\s*(\d+)\s*$",
            "utilization": r"^Worst utilization\s*:\s*(\S+)\s*%\s*$",
            "no_limit": r"^No J-limit \(skipped\)\s*:\s*(\d+)\s*$",
            "no_area": r"^No area \(skipped\)\s*:\s*(\d+)\s*$",
            "checked": r"^Segments checked\s*:\s*(\d+)\s*$",
            "verdict": r"^Verdict\s*:\s*(PASS|FAIL)\s*$",
        }.items()}
        count = int(fields["violations"][1]) if fields["violations"] else None
        native_failed |= bool(fields["verdict"] and fields["verdict"][1] == "FAIL")
        try:
            percent = float(fields["utilization"][1]) if fields["utilization"] else None
        except ValueError:
            percent = None
        if count is not None:
            counts.append(count)
        if percent is not None and math.isfinite(percent) and percent >= 0:
            utilization.append(percent)
        else:
            complete = False
        if (not all(fields.values()) or int(fields["no_limit"][1])
                or int(fields["no_area"][1]) or int(fields["checked"][1]) == 0
                or fields["verdict"][1] != ("FAIL" if count else "PASS")):
            complete = False
    metrics = {}
    if complete or any(counts):
        metrics["em_violations"] = sum(counts)
    if complete or any(value > 100 for value in utilization):
        metrics["em_worst_utilization_pct"] = max(utilization)
    if native_failed and not any(counts) and not any(value > 100 for value in utilization):
        raise StepError("Native current-density report verdict is FAIL without a numeric defect summary")
    return metrics


class CurrentDensityReport(IRDropReport):
    def get_script_path(self):
        return str(Path(self.step_dir) / "current_density.tcl")

    def run(self, state_in, **kwargs):
        root = Path(self.step_dir).resolve()
        lefs = self.toolbox.filter_views(self.config, self.config["TECH_LEFS"], timing_corner="nom_")
        if len(lefs) != 1:
            raise StepException("NOT_MEASURED: native EM needs the nominal PDK technology LEF")
        limits = native_limits(Path(lefs[0]).read_text(), 0.0, self.config["PDK"])
        if not limits.strip():
            raise StepException("NOT_MEASURED: PDK technology has no native current-density limits")
        limits_path = root / "em_limits_pdk.txt"
        limits_path.write_text(limits)
        kwargs, env = self.extract_env(kwargs)
        env["VIBEIC_IR_SCRIPT"] = IRDropReport.get_script_path(self)
        env["VIBEIC_EM_LIMITS_FILE"] = str(limits_path)
        Path(self.get_script_path()).write_text('''source $::env(_TCL_ENV_IN)
source $::env(VIBEIC_IR_SCRIPT)
puts "%OL_CREATE_REPORT em.rpt"
set index 0
foreach net [concat $::env(VDD_NETS) $::env(GND_NETS)] {
    puts "=== EM_NET $net ==="
    set args [list -net $net -em_limits_file $::env(VIBEIC_EM_LIMITS_FILE) \\
        -em_report [file join $::env(STEP_DIR) em-$index.csv] -allow_reuse]
    if {[dict exists $vsrc_files $net]} {
        lappend args -vsrc [dict get $vsrc_files $net]
    }
    check_current_density {*}$args
    incr index
}
puts "%OL_END_REPORT"
''')
        views, metrics = super().run(state_in, env=env, **kwargs)
        nets = list(self.config["VDD_NETS"]) + list(self.config["GND_NETS"])
        metrics.update(current_density_metrics((root / "em.rpt").read_text(), nets))
        return views, metrics


@Step.factory.register()
class EMCorners(IRDropCorners):
    id = "VibeIC.EMCorners"
    name = "Current density at maximum RC corners"
    long_name = name
    report_class = CurrentDensityReport

    def run(self, state_in, **kwargs):
        views, metrics = super().run(state_in, **kwargs)
        corners = [corner for corner in self.config["STA_CORNERS"] if corner.startswith("max_")]
        for name, reducer, failed in (
            ("em_violations", sum, lambda value: value > 0),
            ("em_worst_utilization_pct", max, lambda value: value > 100),
        ):
            values = [metrics[f"{name}__corner:{corner}"] for corner in corners
                      if f"{name}__corner:{corner}" in metrics]
            if len(values) == len(corners) or any(map(failed, values)):
                metrics[name] = reducer(values)
        return views, metrics
