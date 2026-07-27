"""_class_template_resolve.py — ONE source of truth for "which class template
applies to this class-tree node".  (re #495, Stage 3)

WHY THIS MODULE EXISTS
----------------------
`agents/class_kb/class-tree.yaml` has 31 nodes and `templates/` has 14 files,
11 of which are nodes. So 20 nodes have no template of their own, and the issue
reports that mapping a class to one of them is "a silent no-op that reads as
success".

Measured, it is worse than a no-op: it is a DIFFERENT class's floor. A
template-less node resolves three ways depending on which consumer asks —

    consumer                          mechanism                node `hash-function`
    tools/phase1_engine/gap_detect    walks the parent chain   crypto-engine  (7 floor keys)
    phase1_quality_parity_check       one template, then jump  generic-ic     (2 floor keys)
    layer_extension_presence_check    one template, then jump  any-ic         (0 floor keys)

`generic-ic` is not `hash-function`'s ancestor — it is an orphan template that
is not a node at all. So the two single-template consumers were substituting a
sibling's floor for an ancestor's, and doing it silently. It is not uniformly
lenient either: for `hash-function` / `spi-peripheral` / `i2c-peripheral` /
`protocol-bridge` the jump is LOOSER than the taxonomy (2 keys instead of 7-10),
while for `dsp-block` / `analog-mixed-ic` / `debug-block` / `network-controller`
/ `peripheral-timer` / `root-of-trust` / `display-controller` it is STRICTER
(the tree says inherit `digital-ic` or `any-ic`, both of which carry NO floor,
yet `generic-ic` imposes one).

WHAT "NO TEMPLATE" ACTUALLY MEANS
---------------------------------
In a tree whose entire purpose is inheritance, a node without its own template
means "adds no requirements beyond its parent". That is not a hole to be
filled — it is the tree's normal state, and it is already documented as
deliberate in the only two hand-written empty templates: `digital-ic.yaml` says
of itself "adds no new facts beyond any-ic (digital-ic is a pure categorical
intermediate in the class tree); its sole job is to keep the fallback walk
contiguous". `gap_detect._spec_floor_from_chain` has always read the tree this
way. So none of the 20 needs inventing: they need the other two consumers to
honour the inheritance that is already there.

THE NEUTRAL FALLBACK IS PRESERVED, AND NARROWED TO ITS REAL JOB
---------------------------------------------------------------
`generic-ic` remains the fallback for a class that is not in the tree AT ALL —
an unregistered name, a third-party class, a typo. That is what the "unknown
class must not inherit a protocol-specific floor" discipline was written for.
What changes is that it stops also standing in for classes the tree *does*
know, where an actual answer was available and was being discarded.

chip-AGNOSTIC: a walk over the taxonomy graph; no vendor / SKU / IC literal.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml
except ImportError:                                   # pragma: no cover
    yaml = None


# How a template was arrived at. Consumers surface this so the substitution is
# never silent again.
OWN = "own"                     # the node has its own template
INHERITED = "inherited"         # nearest ANCESTOR with a template, per the tree
NEUTRAL = "neutral_fallback"    # class is not in the tree — generic-ic / any-ic
NONE = "none"                   # nothing at all could be loaded


def _load_yaml(path: Path) -> Any:
    if yaml is None:                                  # pragma: no cover
        raise RuntimeError("PyYAML required; pip install pyyaml")
    with Path(path).open() as f:
        return yaml.safe_load(f)


def parent_of(class_kb_dir: Path) -> Dict[str, Optional[str]]:
    """Flatten class-tree.yaml to {node: parent}. Root maps to None.

    Same traversal `gap_detect._parent_chain` uses, so the two cannot disagree
    about the shape of the tree.
    """
    tree_file = Path(class_kb_dir) / "class-tree.yaml"
    if not tree_file.is_file():
        return {}
    tree = _load_yaml(tree_file)
    out: Dict[str, Optional[str]] = {}

    def rec(node: Dict[str, Any], parent: Optional[str]) -> None:
        if not isinstance(node, dict):
            return
        for name, body in node.items():
            if not isinstance(body, dict):
                continue
            out[name] = parent
            children = body.get("children")
            if isinstance(children, dict):
                rec(children, name)

    rec(tree, None)
    return out


def ancestor_with_template(class_path: str, class_kb_dir: Path) -> Optional[str]:
    """Nearest ancestor of ``class_path`` (exclusive) that HAS a template file.

    Returns None when ``class_path`` is not a tree node, or when no ancestor up
    to the root has a template. Cycle-safe.
    """
    kb = Path(class_kb_dir)
    tdir = kb / "templates"
    parents = parent_of(kb)
    if class_path not in parents:
        return None                       # not in the tree — caller goes neutral
    seen = {class_path}
    cur = parents.get(class_path)
    while cur is not None and cur not in seen:
        seen.add(cur)
        if (tdir / f"{cur}.yaml").is_file():
            return cur
        cur = parents.get(cur)
    return None


def resolve(class_path: str, class_kb_dir: Path,
            neutral_chain: tuple[str, ...] = ("generic-ic", "any-ic")
            ) -> Dict[str, Any]:
    """Resolve the template that applies to ``class_path``.

    Order, and the reason for it:

      1. the node's OWN template, if it has one — unchanged behaviour;
      2. otherwise, if the node IS in the tree, its nearest ANCESTOR with a
         template — this is what "no template" means in an inheritance tree,
         and what gap_detect has always done;
      3. otherwise the NEUTRAL chain — reserved for a class the tree does not
         contain at all, so an unknown class still cannot pick up a
         protocol-specific floor;
      4. otherwise nothing.

    Returns ``{"template", "used", "how"}``. ``used`` is the node whose template
    was loaded (None when nothing was); ``how`` is one of OWN / INHERITED /
    NEUTRAL / NONE, so every consumer can say WHY a floor applied.
    """
    kb = Path(class_kb_dir)
    tdir = kb / "templates"

    own = tdir / f"{class_path}.yaml"
    if own.is_file():
        return {"template": _load_yaml(own), "used": class_path, "how": OWN}

    anc = ancestor_with_template(class_path, kb)
    if anc:
        return {"template": _load_yaml(tdir / f"{anc}.yaml"),
                "used": anc, "how": INHERITED}

    for fb in neutral_chain:
        c = tdir / f"{fb}.yaml"
        if c.is_file():
            return {"template": _load_yaml(c), "used": fb, "how": NEUTRAL}

    return {"template": None, "used": None, "how": NONE}
