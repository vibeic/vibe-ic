"""Regression test for v0.61 Bug #1 — L8R silent drop.

v0.60 `_walk_leaves` heuristic: when a dict's values are all scalars
AND len > 1, yield (prefix, whole_dict) as a single record. At top
level (`prefix == ""`), this collided with the caller's
`if not leaf_path: continue` guard and silently dropped any layer
whose top-level keys were all scalars (typical for L8R: clock
frequency, polarities, fifo depth, etc).

v0.61 fix: heuristic only fires when prefix is non-empty.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

from tools.phase1_engine.ingest import (  # noqa: E402
    _walk_leaves,
    from_existing_docs,
    from_structured_yaml,
)


# ---------------------------------------------------------------------------
# _walk_leaves directly — top level vs nested
# ---------------------------------------------------------------------------
def test_walk_leaves_top_level_all_scalar_dict_recurses():
    """Top-level all-scalar dict must NOT be yielded as one record."""
    obj = {"clock_frequency_hz": 50_000_000, "reset_polarity": "low"}
    leaves = list(_walk_leaves(obj))
    paths = sorted(p for p, _ in leaves)
    assert paths == ["clock_frequency_hz", "reset_polarity"], (
        f"top-level dict should produce per-key facts, got: {leaves}"
    )


def test_walk_leaves_nested_all_scalar_dict_emits_record():
    """Nested all-scalar dict {min,typ,max,unit} stays as one record."""
    obj = {"supply": {"min": 4.5, "typ": 5.0, "max": 5.5, "unit": "V"}}
    leaves = list(_walk_leaves(obj))
    # Should be exactly one fact: ("supply", {min,typ,max,unit})
    assert len(leaves) == 1
    path, value = leaves[0]
    assert path == "supply"
    assert value == {"min": 4.5, "typ": 5.0, "max": 5.5, "unit": "V"}


def test_walk_leaves_top_level_scalar_list_recurses():
    """Top-level all-scalar list must NOT be dropped."""
    obj = ["a", "b", "c"]
    leaves = list(_walk_leaves(obj))
    # Should produce per-index facts, not a single record
    paths = sorted(p for p, _ in leaves)
    assert paths == ["[0]", "[1]", "[2]"]


def test_walk_leaves_nested_scalar_list_emits_record():
    """Nested all-scalar list stays as one inline list fact."""
    obj = {"opcodes": [0x70, 0x71, 0x72]}
    leaves = list(_walk_leaves(obj))
    assert len(leaves) == 1
    path, value = leaves[0]
    assert path == "opcodes"
    assert value == [0x70, 0x71, 0x72]


def test_walk_leaves_single_key_dict_still_recurses():
    """The >1 key guard means a single-key dict always recurses."""
    obj = {"only_key": 42}
    leaves = list(_walk_leaves(obj))
    assert leaves == [("only_key", 42)]


# ---------------------------------------------------------------------------
# from_structured_yaml — end-to-end with all-scalar L8R
# ---------------------------------------------------------------------------
def test_l8r_all_scalar_layer_extracts_facts(tmp_path):
    """A spec.yaml whose L8R is purely scalar must produce L8R facts."""
    spec = {
        "ic_name": "MY_WDT",
        "class_path": "apb-peripheral",
        "L1": {"ic_name": "MY_WDT"},
        "L8R": {
            "clock_frequency_hz": 50_000_000,
            "reset_polarity": "low",
            "irq_count": 1,
            "address_alignment": 4,
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    fg = from_structured_yaml(spec_path)
    l8r_paths = sorted(f.path for f in fg.facts if f.path.startswith("L8R"))
    assert l8r_paths == [
        "L8R.address_alignment",
        "L8R.clock_frequency_hz",
        "L8R.irq_count",
        "L8R.reset_polarity",
    ], f"L8R facts dropped, got: {l8r_paths}"


def test_l8r_with_nested_record_still_groups_record(tmp_path):
    """Mixed L8R: top-level scalars + nested record. Both must survive."""
    spec = {
        "ic_name": "X",
        "class_path": "any-ic",
        "L8R": {
            "clock_frequency_hz": 50_000_000,
            "supply": {"min": 4.5, "typ": 5.0, "max": 5.5, "unit": "V"},
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec))

    fg = from_structured_yaml(spec_path)
    paths = {f.path: f.value for f in fg.facts if f.path.startswith("L8R")}
    assert "L8R.clock_frequency_hz" in paths
    assert paths["L8R.clock_frequency_hz"] == 50_000_000
    # Nested supply still grouped as one record (heuristic still fires
    # on nested levels)
    assert "L8R.supply" in paths
    assert paths["L8R.supply"] == {"min": 4.5, "typ": 5.0, "max": 5.5, "unit": "V"}


# ---------------------------------------------------------------------------
# from_existing_docs — same fix applies on the round-trip path
# ---------------------------------------------------------------------------
def test_existing_docs_all_scalar_layer_extracts_facts(tmp_path):
    """Re-ingest from L*.json with all-scalar layer must round-trip."""
    import json
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "clock_frequency_hz": 50_000_000,
        "reset_polarity": "low",
    }))
    fg = from_existing_docs(docs)
    paths = sorted(f.path for f in fg.facts if f.path.startswith("L8R"))
    assert paths == ["L8R.clock_frequency_hz", "L8R.reset_polarity"]
