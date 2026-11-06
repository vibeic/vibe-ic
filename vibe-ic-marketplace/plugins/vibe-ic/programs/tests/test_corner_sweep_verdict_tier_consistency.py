"""A real failing sweep must publish one consistent verdict through every seam.

The minimal native fixture retains the original counts, failed corner IDs,
values and statuses. Other fixtures are neutral inputs, not native evidence.
"""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

import pytest


FIXTURE = Path(__file__).parent / "fixtures/corner_sweep_verdict/native_spec_failure.json"


def stage(project, data, block="block_a"):
    path = project / "phase3/analog" / block / "corner_results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if data is not None else "{")


def passing():
    return {"total_corners": 9, "results_found": 9,
            "design_content": "structure_and_geometry",
            "corners": [{"name": f"point_{i}", "simulator_run": True} for i in range(9)],
            "spec_results": [{"spec": "quantity", "status": "PASS"}]}


def verdict(report):
    return report["passed"], report["summary"]["pass"], report["summary"]["verdict_tier"]












@pytest.mark.parametrize("tier", ["NOT_MEASURED", "NOT_APPLICABLE", "ENV_UNAVAILABLE", "INCOMPLETE", "FAIL"])
def test_frontdoor_nonpass_status_mapping_is_unchanged(tier):
    import analog_one_shot_runner as runner
    assert runner.verdict_tier(tier) == tier
