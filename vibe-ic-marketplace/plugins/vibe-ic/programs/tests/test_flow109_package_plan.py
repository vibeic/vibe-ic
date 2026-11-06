"""Focused D06 producer/adapter controls."""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from programs.tests._hostpaths import require_repo


def _write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


def _context():
    return {"requested_step": "D06", "native_step_id": "flow109.D06",
            "resolved_row": {"id": "D06"}, "context_sha256": "b" * 64,
            "resolved_features": {"requires_dft": False, "requires_scan": False,
                                  "package_interface": True,
                                  "package_model_required": True}}










def test_checked_in_registry_routes_d06_to_real_pad_producer():
    registry = json.loads(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "flow109.json").read_text())
    row = next(item for item in registry["rows"] if item["id"] == "D06")
    dispatch = row["profiles"][0]["dispatch"]
    assert dispatch["adapter"] == "flow109_package_plan"
    assert dispatch["producer"] == "pad_assignment_gen.py:main"
    assert row["metric_acceptance_status"] == "IMPLEMENTED_BARE_DIE_NATIVE"
