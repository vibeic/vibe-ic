"""re #495 Stage 2 — the registry -> class-tree mapping, and its honesty.

`programs/ic_class_registry.json` (13 snake_case names) and
`agents/class_kb/class-tree.yaml` (31 kebab-case nodes) share no names, so a
`class_path` written by the registry side is unresolvable by the tree side.
Each registry entry now declares `class_tree_node` plus a `class_tree_node_status`
saying what that declaration is WORTH.

The status is the load-bearing part, and the point of these tests is that it
cannot drift into a comfortable lie: every value is re-derived here from the KB
on disk and compared against what the entry claims. A `mapped` entry whose
template quietly loses its `spec_floor`, or a `mapped_template_missing` entry
whose template later appears, fails here rather than silently changing what the
floor means.

The mapping is DECLARED, not APPLIED — measured over the 201 tracked doc-sets,
applying it adds 21 findings of which 0 are defects. The final test pins that
non-application, so wiring it becomes a deliberate act with a failing test
attached rather than a quiet one-line change.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"
KB = PLUGIN / "agents" / "class_kb"
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

REGISTRY = json.loads((PROGRAMS / "ic_class_registry.json").read_text())
ENTRIES = REGISTRY["classes"]

VALID_STATUS = {"mapped", "mapped_floorless", "mapped_template_missing",
                "unmappable"}


def _tree_nodes() -> set[str]:
    tree = yaml.safe_load((KB / "class-tree.yaml").read_text())
    out: set[str] = set()

    def rec(node):
        for name, body in node.items():
            if not isinstance(body, dict):
                continue
            out.add(name)
            if isinstance(body.get("children"), dict):
                rec(body["children"])

    rec(tree)
    return out


def _template_floor(node: str):
    """Return (template_exists, has_spec_floor)."""
    f = KB / "templates" / f"{node}.yaml"
    if not f.is_file():
        return False, False
    doc = yaml.safe_load(f.read_text()) or {}
    return True, bool(doc.get("spec_floor"))


NODES = _tree_nodes()


def test_every_registry_entry_declares_a_mapping() -> None:
    missing = [c["name"] for c in ENTRIES
               if "class_tree_node" not in c
               or "class_tree_node_status" not in c
               or not (c.get("class_tree_node_basis") or "").strip()]
    assert not missing, f"entries with no declared mapping/basis: {missing}"


@pytest.mark.parametrize("entry", ENTRIES, ids=[c["name"] for c in ENTRIES])
def test_declared_status_matches_the_kb_on_disk(entry: dict) -> None:
    node = entry["class_tree_node"]
    status = entry["class_tree_node_status"]
    assert status in VALID_STATUS, f"{entry['name']}: bad status {status!r}"

    if status == "unmappable":
        assert node is None, f"{entry['name']}: unmappable must carry node=null"
        return

    assert isinstance(node, str) and node, entry["name"]
    assert node in NODES, (
        f"{entry['name']}: declared node {node!r} is not in class-tree.yaml")

    has_tpl, has_floor = _template_floor(node)
    if status == "mapped_template_missing":
        assert not has_tpl, (
            f"{entry['name']}: declared template-missing but "
            f"templates/{node}.yaml now EXISTS — the mapping is no longer "
            f"inert, so the status must be re-derived")
    elif status == "mapped_floorless":
        assert has_tpl, f"{entry['name']}: {node} has no template"
        assert not has_floor, (
            f"{entry['name']}: declared floorless but templates/{node}.yaml "
            f"now carries a spec_floor — this class would start being scored")
    elif status == "mapped":
        assert has_tpl and has_floor, (
            f"{entry['name']}: declared mapped but templates/{node}.yaml "
            f"exists={has_tpl} has_spec_floor={has_floor}")


def test_resolver_returns_the_declaration_and_fails_closed() -> None:
    from ic_class_profile import class_tree_node_for

    r = class_tree_node_for("crypto_accelerator")
    assert r["registry_matched"] is True
    assert r["node"] == "crypto-engine"
    assert r["status"] == "mapped"
    assert r["basis"]

    # unmappable entries surface node=None WITH a reason
    r = class_tree_node_for("bare_fpga")
    assert r["registry_matched"] is True
    assert r["node"] is None
    assert r["status"] == "unmappable"
    assert "no silicon target" in r["basis"] or "NO silicon" in r["basis"]

    # a synonym resolves to the same entry
    assert class_tree_node_for("aes_core")["node"] == "crypto-engine"

    # an unknown name must not look like a mapping
    r = class_tree_node_for("not-a-registered-class")
    assert r == {"node": None, "status": "unregistered", "basis": "",
                 "registry_matched": False}


def test_registry_class_path_is_disclosed_not_silently_downgraded(
        tmp_path: Path) -> None:
    """A registry-named class_path must SAY that the tree could not resolve it."""
    import phase1_quality_parity_check as Q

    docs = tmp_path / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps(
        {"class_path": "crypto_accelerator"}))

    res = Q.check(docs, KB, "crypto_accelerator")
    rules = {w["rule"] for w in res["warnings"]}
    assert "registry_class_not_in_class_tree" in rules, res["warnings"]
    w = next(w for w in res["warnings"]
             if w["rule"] == "registry_class_not_in_class_tree")
    assert w["class_tree_node"] == "crypto-engine"
    assert w["class_tree_node_status"] == "mapped"

    # a genuine class-tree name must NOT be reported as a registry class
    res2 = Q.check(docs, KB, "crypto-engine")
    assert "registry_class_not_in_class_tree" not in {
        w["rule"] for w in res2["warnings"]}


def test_mapping_is_declared_but_not_applied(tmp_path: Path) -> None:
    """The declaration must not silently change what gets scored.

    Applying it was measured over all 201 tracked doc-sets: +21 findings, of
    which 11 sit on floors no doc-set in the corpus can satisfy and 10 on
    fields the document explicitly declares absent from its source. Zero are
    defects. Until the floors read the honest-absence sentinels, resolution
    must stay where it is.
    """
    import phase1_quality_parity_check as Q

    docs = tmp_path / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps(
        {"class_path": "crypto_accelerator"}))

    # the resolver still returns the REGISTRY name, not the mapped node
    assert Q._resolve_class_path_from_l1(docs) == "crypto_accelerator"
    # and the floor used is the neutral fallback, not crypto-engine's
    res = Q.check(docs, KB, Q._resolve_class_path_from_l1(docs))
    assert res["template_used"] == "generic-ic", res["template_used"]
