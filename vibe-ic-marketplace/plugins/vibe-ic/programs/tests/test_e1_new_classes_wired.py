"""v0.79 E1 — guard the 4 new K1/K3 classes from the k3_class_miner sweep.

The k3_class_miner pass over 234 open-source ICs surfaced 5 candidate
classes; 4 were genuinely distinct from existing K1 entries and added
in v0.79 Batch 5: debug-block, display-controller, protocol-bridge,
root-of-trust. (5th candidate "crypto-miner" was already covered by
hash-function-miner from the C1 split — see class-tree.yaml comment.)

This test guards against accidental deletion in either K1 or K3, and
asserts a minimum schema floor on the K3 stubs so the per-layer agents
have something to anchor against from day 1.
"""
from __future__ import annotations

import pytest
import yaml

from _plugin_tree import plugin_path


# flow #486: resolve in-plugin resources via the shared resolver so this
# works on both the source monorepo and the flattened install cache.
K1_PATH = plugin_path("agents", "class_kb", "class-tree.yaml")
K3_PATH = plugin_path("agents", "defaults", "class_reference.yaml")

# (class_name, expected_K1_parent_path)
E1_CLASSES = [
    ("debug-block",         ["any-ic", "digital-ic"]),
    ("display-controller",  ["any-ic", "digital-ic"]),
    ("protocol-bridge",     ["any-ic", "digital-ic", "protocol-ic"]),
    ("root-of-trust",       ["any-ic", "digital-ic"]),
]


@pytest.fixture(scope="module")
def k1_tree():
    return yaml.safe_load(K1_PATH.read_text())


@pytest.fixture(scope="module")
def k3_ref():
    return yaml.safe_load(K3_PATH.read_text())


def _walk_to(tree: dict, path: list[str]) -> dict | None:
    node = tree
    for step in path:
        if not isinstance(node, dict):
            return None
        node = node.get(step)
        if node is None:
            return None
        if "children" in node and step != path[-1]:
            node = node["children"]
    return node


@pytest.mark.parametrize("cls,parent_path", E1_CLASSES)
def test_e1_class_in_k1_tree_under_correct_parent(k1_tree, cls, parent_path):
    parent = _walk_to(k1_tree, parent_path)
    assert parent is not None, f"K1 parent path {parent_path} not found"
    children = parent.get("children", {})
    assert cls in children, (
        f"K1 class {cls} not found under {'/'.join(parent_path)}.children — "
        f"E1 wiring missing"
    )
    entry = children[cls]
    assert isinstance(entry, dict), f"K1.{cls} must be a dict"
    assert entry.get("description"), f"K1.{cls}.description missing"
    assert entry.get("examples"), (
        f"K1.{cls}.examples missing — must list at least one canonical IC"
    )


@pytest.mark.parametrize("cls,_", E1_CLASSES)
def test_e1_class_has_k3_stub(k3_ref, cls, _):
    assert cls in k3_ref, f"K3 class {cls} not present in class_reference.yaml"
    entry = k3_ref[cls]
    # Minimum stub floor — these are the fields the proposer + agent
    # prompts assume exist for every class.
    assert entry.get("reference"), f"{cls}.reference missing"
    assert entry.get("public_source"), f"{cls}.public_source missing"
    assert entry.get("typical_role"), f"{cls}.typical_role missing"
    assert entry.get("typical_pin_count"), f"{cls}.typical_pin_count missing"
    assert "typical_structure" in entry, (
        f"{cls}.typical_structure missing — required for per-layer agent anchoring"
    )


@pytest.mark.parametrize("cls,_", E1_CLASSES)
def test_e1_typical_structure_has_at_least_l1_and_one_more(k3_ref, cls, _):
    """Stubs are intentionally thin but must cover at least L1
    (datasheet pins) AND one additional layer so the agents see the
    class is a real IC class, not a placeholder."""
    ts = k3_ref[cls]["typical_structure"]
    assert isinstance(ts, dict), f"{cls}.typical_structure must be a dict"
    assert "L1_datasheet" in ts, f"{cls}.typical_structure.L1_datasheet missing"
    other_layers = [k for k in ts if k.startswith("L") and k != "L1_datasheet"]
    assert len(other_layers) >= 1, (
        f"{cls}.typical_structure has only L1 — stub floor is L1 + at least "
        f"one other layer (L3/L4/L8/L9 expected)"
    )


def test_e1_crypto_miner_intentionally_aliased_to_hash_function_miner(k1_tree):
    """The 5th miner candidate "crypto-miner" was intentionally NOT added
    to K1 because hash-function-miner already covers bitcoin-miner. This
    test guards the documented decision."""
    crypto_engine = _walk_to(k1_tree, ["any-ic", "digital-ic", "crypto-engine"])
    assert crypto_engine is not None
    hf_children = crypto_engine.get("children", {}).get(
        "hash-function", {}).get("children", {})
    assert "hash-function-miner" in hf_children, (
        "hash-function-miner missing — E1 decision relies on it covering "
        "the bitcoin-miner / crypto-miner case"
    )
    # And NO duplicate crypto-miner top-level under digital-ic
    digital = _walk_to(k1_tree, ["any-ic", "digital-ic"])
    assert "crypto-miner" not in digital.get("children", {}), (
        "crypto-miner accidentally added — should be aliased to "
        "hash-function-miner per E1 design note"
    )
