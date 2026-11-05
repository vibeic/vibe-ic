from __future__ import annotations

import json
from pathlib import Path

from librelane.steps import Step
from librelane_plugins.librelane_plugin_vibeic import InsertSpareCells

from spare_cell_coverage_check import evaluate_coverage


@Step.factory.register()
class SpareCells(InsertSpareCells):
    id = "VibeIC.SpareCells"
    name = "Insert and measure ECO spare cells"

    def run(self, state_in, **kwargs):
        views, metrics = super().run(state_in, **kwargs)
        record = json.loads(Path(self._report_path()).read_text())
        coverage = evaluate_coverage(record)
        metrics.update(
            spare_density_fraction=record["actual_density"],
            spare_distribution_errors=int(not coverage["distribution_ok"]),
            spare_tie_connectivity_errors=int(not coverage["tie_off_ok"]),
            spare_planned_mismatch=abs(len(record["instances"]) - record["measured"]["inserted"]),
        )
        return views, metrics
