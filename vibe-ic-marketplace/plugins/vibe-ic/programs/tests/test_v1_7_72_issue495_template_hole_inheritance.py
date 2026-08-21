"""re #495 Stage 3 — the 20 "template holes" are one defect, not twenty.

class-tree.yaml has 31 nodes; templates/ has 14 files, 11 of which are nodes.
The issue asks whether the 20 template-less nodes should be POPULATED or
DELETED, on the grounds that mapping a class to one of them is "a silent no-op
that reads as success".

Measured, it was not a no-op at all — it was a DIFFERENT class's floor, and the
answer differed by consumer:

    gap_detect                      walks the parent chain   crypto-engine (7 keys)
    phase1_quality_parity_check     one template, then jump  generic-ic    (2 keys)
    layer_extension_presence_check  one template, then jump  any-ic        (0 keys)

`generic-ic` is not an ancestor of anything — it is an orphan template that is
not a node. So the answer is NEITHER populate nor delete: in an inheritance
tree "no template" already means "adds nothing beyond my parent", which is what
`digital-ic.yaml` says of itself in prose and what gap_detect has always done.
The two single-template consumers now do the same walk.

These tests drive the real resolvers and assert on observable results:

  1. all three consumers agree, for EVERY node in the tree;
  2. inheritance picks the nearest templated ancestor, not any ancestor;
  3. a class the tree does not contain still gets the NEUTRAL floor, so the
     unknown-class discipline is intact;
  4. the substitution is disclosed rather than silent;
  5. the corpus is unaffected (no tracked doc-set carries a template-less node),
     so this is a semantics repair with a measured zero delta;
  6. the three orphan templates have a declared disposition.
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
TOOLS = PLUGIN / "tools"
for p in (str(PROGRAMS), str(TOOLS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import _class_template_resolve as CTR            # noqa: E402
import phase1_quality_parity_check as Q          # noqa: E402
import layer_extension_presence_check as X       # noqa: E402
from phase1_engine import gap_detect as GD       # noqa: E402

TREE = yaml.safe_load((KB / "class-tree.yaml").read_text())
PARENTS = CTR.parent_of(KB)
NODES = sorted(PARENTS)
TEMPLATED = {p.stem for p in (KB / "templates").glob("*.yaml")}


def _floor_of(node_or_none):
    if not node_or_none:
        return {}
    f = KB / "templates" / f"{node_or_none}.yaml"
    if not f.is_file():
        return {}
    return (yaml.safe_load(f.read_text()) or {}).get("spec_floor") or {}


HOLE_NODES = sorted(n for n in NODES if n not in TEMPLATED)


@pytest.mark.parametrize("node", HOLE_NODES)
def test_all_three_consumers_agree_on_every_template_less_node(
        node: str) -> None:
    """The 20 holes: the floor must not depend on which gate asks."""
    expected = _floor_of(CTR.ancestor_with_template(node, KB))

    qt, _fb = Q.find_class_template(node, KB)
    q_floor = (qt or {}).get("spec_floor") or {}
    xt = X.load_class_template(node, KB)
    x_floor = (xt or {}).get("spec_floor") or {}
    g_floor = GD._spec_floor_from_chain(GD._parent_chain(node, TREE),
                                        KB / "templates")

    assert q_floor == expected, f"{node}: quality_parity floor diverges"
    assert x_floor == expected, f"{node}: layer_extension floor diverges"
    assert g_floor == expected, f"{node}: gap_detect floor diverges"


@pytest.mark.parametrize("node", sorted(TEMPLATED & set(NODES)))
def test_templated_nodes_are_scored_on_their_own_declared_floor(
        node: str) -> None:
    """A template that OMITS a parent's rule means it, and both single-template
    consumers must honour that."""
    expected = _floor_of(node)
    qt, _fb = Q.find_class_template(node, KB)
    assert ((qt or {}).get("spec_floor") or {}) == expected
    assert ((X.load_class_template(node, KB) or {}).get("spec_floor")
            or {}) == expected


def test_known_divergence_gap_detect_overrides_a_deliberate_omission() -> None:
    """DISCLOSED, distinct from the 20 holes, and deliberately NOT fixed here.

    `_spec_floor_from_chain` accumulates root->leaf with dict.update, so a rule
    a child OMITS is inherited from the parent anyway. There is no way in that
    scheme to say "my parent floors this and I do not". Exactly one node in the
    KB tries: `uart-peripheral.yaml` drops `L3_opcode_count_min` and writes the
    reason on the line where it would have gone —

        # No L3 opcode floor — UART carries arbitrary bytes, not opcodes.

    — and gap_detect re-imposes protocol-ic's `L3_opcode_count_min: 4` on top.
    The single-template consumers honour the omission. So the two semantics
    disagree on exactly one node, and the template's own comment says which one
    it wants.

    Not fixed in this stage: gap_detect's chain walk is the subject of the next
    stage, changing an inheritance rule is not a template hole, and gap_detect
    produces 0 gaps corpus-wide today so nothing is currently mis-scored. This
    test pins the divergence so it is a decision rather than a discovery.
    """
    own = _floor_of("uart-peripheral")
    accumulated = GD._spec_floor_from_chain(
        GD._parent_chain("uart-peripheral", TREE), KB / "templates")

    assert "L3_opcode_count_min" not in own, (
        "uart-peripheral.yaml now declares an L3 opcode floor — the divergence "
        "this test pins is gone; delete the test and the disposition note")
    assert accumulated.get("L3_opcode_count_min") == 4, (
        "gap_detect no longer inherits protocol-ic's opcode floor — the "
        "divergence is resolved; update this test deliberately")
    assert set(accumulated) - set(own) == {"L3_opcode_count_min"}, (
        "a SECOND deliberate omission is now being overridden; re-derive")

    # the divergence must stay confined to that one node
    others = []
    for n in sorted(TEMPLATED & set(NODES)):
        if n == "uart-peripheral":
            continue
        acc = GD._spec_floor_from_chain(GD._parent_chain(n, TREE),
                                        KB / "templates")
        if acc != _floor_of(n):
            others.append(n)
    assert not others, f"inheritance now overrides omissions on: {others}"


def test_inheritance_picks_the_NEAREST_templated_ancestor() -> None:
    # hash-function-csr -> hash-function (no tpl) -> crypto-engine (tpl)
    assert CTR.ancestor_with_template("hash-function-csr", KB) == "crypto-engine"
    # spi-peripheral -> protocol-ic (tpl), NOT digital-ic / any-ic
    assert CTR.ancestor_with_template("spi-peripheral", KB) == "protocol-ic"
    # dsp-block -> digital-ic (tpl, deliberately floorless)
    assert CTR.ancestor_with_template("dsp-block", KB) == "digital-ic"
    # a node WITH its own template still resolves to itself
    assert CTR.resolve("protocol-ic", KB)["how"] == CTR.OWN
    # the root has no ancestor
    assert CTR.ancestor_with_template("any-ic", KB) is None


def test_unknown_class_still_gets_the_neutral_floor() -> None:
    """The unknown-class discipline must survive the change.

    A class the tree does not contain must NOT inherit anything — there is
    nothing to inherit from — and must land on the neutral template.
    """
    r = CTR.resolve("not-a-node-at-all", KB)
    assert r["how"] == CTR.NEUTRAL
    assert r["used"] == "generic-ic"
    _tpl, fallback_applied = Q.find_class_template("not-a-node-at-all", KB)
    assert fallback_applied is True

    # and a template-less NODE is not reported as an unknown class
    _tpl2, fb2 = Q.find_class_template("hash-function", KB)
    assert fb2 is False, "inheritance must not masquerade as unknown-class"


def test_inheritance_is_disclosed_not_silent(tmp_path: Path) -> None:
    docs = tmp_path / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({}))

    res = Q.check(docs, KB, "hash-function")
    w = [x for x in res["warnings"]
         if x["rule"] == "class_floor_inherited_from_ancestor"]
    assert w, res["warnings"]
    assert w[0]["template_used"] == "crypto-engine"
    # an own-template class discloses nothing of the sort
    res2 = Q.check(docs, KB, "crypto-engine")
    assert not [x for x in res2["warnings"]
                if x["rule"] == "class_floor_inherited_from_ancestor"]


def test_no_tracked_doc_set_carries_a_template_less_node() -> None:
    """Pins the measured zero corpus delta for this stage.

    Every tracked doc-set resolves to a registry name, to `apb-peripheral`, or
    to nothing — never to one of the 20 template-less nodes. That is WHY this
    repair is a semantics fix with no score movement, and if a future corpus
    doc-set does carry one, this test says so instead of the change quietly
    starting to matter.
    """
    repo = PLUGIN.parents[2]
    bench = repo / "benchmark-data"
    if not bench.is_dir():
        pytest.skip("benchmark-data not present in this checkout")
    hole_nodes = {n for n in NODES if n not in TEMPLATED}
    hits = []
    for l1 in bench.rglob("L1_DATASHEET.json"):
        cp = Q._resolve_class_path_from_l1(l1.parent)
        if cp in hole_nodes:
            hits.append((str(l1.parent), cp))
    assert not hits, f"doc-sets now carrying a template-less node: {hits[:5]}"


def test_orphan_templates_have_a_declared_disposition() -> None:
    """Three templates are not nodes. Each must be deliberate, not residue."""
    orphans = sorted(TEMPLATED - set(NODES))
    assert orphans == ["analog-front-end", "cable-side-id-ic-maxim-style",
                       "generic-ic"], orphans

    disp = yaml.safe_load(
        (KB / "template-disposition.yaml").read_text())
    assert set(disp["orphan_templates"]) == set(orphans)
    for name, body in disp["orphan_templates"].items():
        assert body["disposition"] in {"keep_non_node", "keep_explicit_only"}
        assert body["reason"].strip()

    # every tree node is accounted for as own-template or inherit
    assert set(disp["nodes"]) == set(NODES)
    for name, body in disp["nodes"].items():
        expect = "own_template" if name in TEMPLATED else "inherit"
        assert body["disposition"] == expect, (
            f"{name}: disposition {body['disposition']!r} but templates/"
            f"{name}.yaml exists={name in TEMPLATED}")
        if expect == "inherit":
            assert body["inherits_from"] == CTR.ancestor_with_template(name, KB)
