"""D03 native config resolution and ciel pin controls (in the EDA image)."""
from __future__ import annotations

import json

from programs.tests._hostpaths import require_repo




def test_checked_in_registry_routes_default_d03_to_adapter():
    registry = json.loads(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "flow109.json").read_text())
    row = next(item for item in registry["rows"] if item["id"] == "D03")
    dispatch = row["profiles"][0]["dispatch"]
    assert dispatch["adapter"] == "flow109_technology_qualification"
    assert dispatch["acceptance_scope"] == "existing_native_component_only"
    assert row["metric_acceptance_status"] == "IMPLEMENTED"
    assert "librelane_contract" not in row["source_components"]
