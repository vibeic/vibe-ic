#!/usr/bin/env python3
"""A pinned population SIZE with no pin on its MEMBERS.

THIS GATE BLOCKS (rc=1) on a NEW one.

WHAT IT ASKS THE REPOSITORY
===========================
A pinned population count is invariant under any change that adds and removes
the same number of members. An arrival and a departure landing in one batch
leave the number identical, so the pin stays green while the population it
names has become a DIFFERENT SET, and a raw count read before and after tells
the reader nothing.

A count pin is a measurement only when the identities producing it are pinned
beside it.

THE POSITIVE CONTROL, driven through the repository's own accessor: the live
flow document yields 69 step ids; applying ONE departure and ONE arrival to a
copy of it yields 69 again. The count is UNCHANGED; the member set changed,
symmetric difference of exactly two ids. The blindness is ARITHMETIC, not
specific to that population.

It occurred, twice and in both directions: one lane found three coexisting
populations for one grid — 67, 68, and 68 in a published figure — against a
live 69, with the delta measured as two arrivals and one departure and the pins
"restated for the departure only". A second found a kind-by-kind pin stale in
the same move as its own sum, invisible because the sum asserted first.

THE PREDICATE
=============
A finding is a test module containing at least one COUNT PIN and no MEMBER
PIN.

A COUNT PIN is an integer literal `N >= 2` compared against `len(X)`, where X
is a LIVE RE-DERIVATION: it traces, in the same module, to a filesystem walk
(`glob` / `rglob` / `iterdir` / `listdir` / `walk`), a document load
(`safe_load` / `json.load`), or a call to a local function that does one of
those. An integer compared against a fixture the test itself just built is not
a population pin — it is the test stating its own input.

A MEMBER PIN is a comparison of a SET or a SORTED SEQUENCE against a literal
collection, anywhere in the same module.

The module, not the assertion, is the unit. Where several pins over one
population exist the coarsest asserts first, so a finer pin that went stale in
the same move is never reached; requiring one member pin per module is what
makes the population re-derivable instead of arguable.

WHAT THE REMEDY IS
==================
Pin the identities beside the count and compare them as a SET IN BOTH
DIRECTIONS, so a missing member and an extra member are named separately.
Where pinning identities is impractical, re-derive the count from the accessor
at assertion time and refuse a hand-written literal.

Do not place the membership assertion inside the branch that filters INTO the
population: that shape can only ever see a member arriving, never one leaving.

NOT A DUPLICATE of `corpus_cardinality_pin_scan`, which reports integers pinned
to the size of the PUBLISHED CORPUS and exits 0 whatever it finds. This asks a
different question of a different population — a live re-derivation of a
repository structure — and it blocks.

EXIT
====
  0  every module with a count pin also carries a member pin, or is inventoried
  1  a NEW count-only module, or a stale inventory row
  2  cannot determine
  3  bad invocation
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082

_INVENTORY_NAME = "population_pin_member_set_inventory.json"

#: Below 2 an integer is a presence test ("any at all"), not a population.
_MIN_POPULATION = 2

_LIVE_READS = ("glob", "rglob", "iterdir", "listdir", "walk", "safe_load",
               "load", "loads", "read_text")


def _repo_anchors(tree: ast.AST) -> Set[str]:
    """Names anchored to the CHECKOUT, via `Path(__file__)`.

    This is the discriminator that makes the rule usable. Without it, every
    `json.loads` of an artefact the test itself wrote into a temporary
    directory reads as a population pin — measured at 73 modules, where the
    real population is the handful that re-derive something from the
    REPOSITORY. A count over a fixture the test just built is the test stating
    its own input, and the docstring says so.
    """
    anchors: Set[str] = set()
    for _ in range(3):
        for n in ast.walk(tree):
            targets: List[ast.expr] = []
            value: Optional[ast.AST] = None
            if isinstance(n, ast.Assign):
                targets, value = list(n.targets), n.value
            elif isinstance(n, ast.AnnAssign) and n.value is not None:
                targets, value = [n.target], n.value
            if value is None:
                continue
            hit = False
            for sub in ast.walk(value):
                if isinstance(sub, ast.Name) and sub.id == "__file__":
                    hit = True
                    break
                if isinstance(sub, ast.Name) and sub.id in anchors:
                    hit = True
                    break
            if not hit:
                continue
            for t in targets:
                if isinstance(t, ast.Name):
                    anchors.add(t.id)
    return anchors


def _live_expression(node: ast.AST, anchors: Set[str]) -> Optional[str]:
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            attr = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else None)
            if attr not in _LIVE_READS:
                continue
            names = {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}
            if "__file__" in names or (names & anchors):
                return attr
    return None


def _live_names(tree: ast.AST, anchors: Set[str]) -> Dict[str, str]:
    """Names holding a live re-derivation -> how it was derived."""
    out: Dict[str, str] = {}
    live_funcs: Dict[str, str] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            how = _live_expression(fn, anchors)
            if how:
                live_funcs[fn.name] = how
    # A local ACCESSOR is a live name too. `len(step_ids()) == 69` never binds
    # the collection, and a tracker reading only assignments cannot see the
    # commonest shape of the pin.
    out.update(live_funcs)
    for _ in range(2):                      # one propagation round is enough
        for n in ast.walk(tree):
            targets: List[ast.expr] = []
            value: Optional[ast.AST] = None
            if isinstance(n, ast.Assign):
                targets, value = list(n.targets), n.value
            elif isinstance(n, ast.AnnAssign) and n.value is not None:
                targets, value = [n.target], n.value
            if value is None:
                continue
            how = _live_expression(value, anchors)
            if how is None:
                for sub in ast.walk(value):
                    if isinstance(sub, ast.Name):
                        if sub.id in live_funcs:
                            how = live_funcs[sub.id]
                            break
                        if sub.id in out:
                            how = out[sub.id]
                            break
            if how is None:
                continue
            for t in targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, how)
    return out


def _len_of_live(node: ast.AST, live: Dict[str, str],
                 anchors: Set[str]) -> Optional[str]:
    if not isinstance(node, ast.Call):
        return None
    if not (isinstance(node.func, ast.Name) and node.func.id == "len"):
        return None
    if not node.args:
        return None
    arg = node.args[0]
    how = _live_expression(arg, anchors)
    if how:
        return how
    for sub in ast.walk(arg):
        if isinstance(sub, ast.Name) and sub.id in live:
            return live[sub.id]
    return None


def _int_const(node: ast.AST) -> Optional[int]:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) \
            and not isinstance(node.value, bool):
        return node.value
    return None


def _count_pins(tree: ast.AST, live: Dict[str, str],
                anchors: Set[str]) -> List[dict]:
    pins: List[dict] = []

    def consider(a: ast.AST, b: ast.AST, line: int) -> None:
        n = _int_const(b)
        how = _len_of_live(a, live, anchors)
        if n is not None and how and n >= _MIN_POPULATION:
            pins.append({"line": line, "count": n, "derived_by": how})

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 \
                and isinstance(node.ops[0], ast.Eq):
            consider(node.left, node.comparators[0], node.lineno)
            consider(node.comparators[0], node.left, node.lineno)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("assertEqual", "assertEquals") \
                and len(node.args) >= 2:
            consider(node.args[0], node.args[1], node.lineno)
            consider(node.args[1], node.args[0], node.lineno)
    return pins


def _is_literal_collection(node: ast.AST, names: Optional[Set[str]] = None) -> bool:
    if names is not None and isinstance(node, ast.Name) and node.id in names:
        return True
    if isinstance(node, (ast.Set, ast.List, ast.Tuple, ast.Dict)):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in ("set", "frozenset", "sorted", "list"):
        return bool(node.args) and isinstance(
            node.args[0], (ast.Set, ast.List, ast.Tuple))
    return False


def _has_member_pin(tree: ast.AST) -> Optional[int]:
    """The line of any set-or-sorted comparison against a literal collection.

    Both sides are resolved through their bindings. The remedy is normally
    written as `got = set(step_ids())` / `expected = {...}` / `assert got ==
    expected`, and a test that reads only the comparison node sees two bare
    names and refuses the fix it asked for.
    """
    memberish_names: Set[str] = set()
    literal_names: Set[str] = set()
    for n in ast.walk(tree):
        targets: List[ast.expr] = []
        value: Optional[ast.AST] = None
        if isinstance(n, ast.Assign):
            targets, value = list(n.targets), n.value
        elif isinstance(n, ast.AnnAssign) and n.value is not None:
            targets, value = [n.target], n.value
        if value is None:
            continue
        for t in targets:
            if not isinstance(t, ast.Name):
                continue
            if _is_literal_collection(value):
                literal_names.add(t.id)
            f = value.func if isinstance(value, ast.Call) else None
            nm = f.id if isinstance(f, ast.Name) else (
                f.attr if isinstance(f, ast.Attribute) else None)
            if nm in ("set", "frozenset", "sorted") or isinstance(
                    value, (ast.Set, ast.SetComp)):
                memberish_names.add(t.id)

    def is_memberish(node: ast.AST) -> bool:
        if isinstance(node, ast.Name) and node.id in memberish_names:
            return True
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (
                f.attr if isinstance(f, ast.Attribute) else None)
            if name in ("set", "frozenset", "sorted"):
                return True
        return isinstance(node, (ast.Set, ast.SetComp))

    for node in ast.walk(tree):
        pair = None
        if isinstance(node, ast.Compare) and len(node.ops) == 1 \
                and isinstance(node.ops[0], ast.Eq):
            pair = (node.left, node.comparators[0], node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("assertEqual", "assertEquals",
                                       "assertSetEqual", "assertCountEqual") \
                and len(node.args) >= 2:
            pair = (node.args[0], node.args[1], node.lineno)
        if pair is None:
            continue
        a, b, line = pair
        for x, y in ((a, b), (b, a)):
            if is_memberish(x) and _is_literal_collection(y, literal_names):
                return line
    return None


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    parsed = 0
    with_pins = 0
    base = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs" / "tests"
    if not base.is_dir():
        return findings, {"test_modules": 0, "modules_with_a_count_pin": 0,
                          "count_only_modules": 0}
    for p in sorted(base.rglob("test_*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        parsed += 1
        anchors = _repo_anchors(tree)
        if not anchors:
            continue
        live = _live_names(tree, anchors)
        if not live:
            continue
        pins = _count_pins(tree, live, anchors)
        if not pins:
            continue
        with_pins += 1
        if _has_member_pin(tree) is not None:
            continue
        rel = p.relative_to(root).as_posix()
        findings.append({"file": rel, "pins": pins,
                         "first_pin_line": pins[0]["line"],
                         "n_pins": len(pins)})
    return findings, {"test_modules": parsed,
                      "modules_with_a_count_pin": with_pins,
                      "count_only_modules": len(findings)}


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--inventory", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] population_pin_without_its_member_set: no "
                  "repository root. NOT a pass.", file=sys.stderr)
            return 2
        findings, denom = scan(root)
        inv_path = Path(a.inventory) if a.inventory else \
            Path(__file__).resolve().parent / _INVENTORY_NAME
        rows = json.loads(inv_path.read_text(encoding="utf-8")).get("known", []) \
            if inv_path.exists() else []
        known = {r["key"] for r in rows}
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] population_pin_without_its_member_set: the "
              f"walk did not complete ({type(exc).__name__}: {exc}). NOT a "
              f"pass.", file=sys.stderr)
        return 2

    print(f"  test modules parsed:       {denom['test_modules']}")
    print(f"  modules with a count pin:  {denom['modules_with_a_count_pin']}")
    print(f"  count pins, no member pin: {denom['count_only_modules']}")
    print(f"  inventory rows applied:    {len(known)}")

    seen = {f["file"] for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[FAIL] {len(new)} module(s) pin a live population's SIZE and "
              f"never its MEMBERS:")
        for f in findings:
            if f["file"] in new:
                shown = ", ".join(
                    f"{p['count']} via {p['derived_by']} (line {p['line']})"
                    for p in f["pins"][:3])
                print(f"   {f['file']}  {f['n_pins']} pin(s): {shown}")
        print("\n  One arrival and one departure in a single batch leave the "
              "number identical.\n  Pin the identities beside the count and "
              "compare them as a set in BOTH\n  directions, or re-derive the "
              "count from the accessor at assertion time.")
    if stale:
        rc = 1
        print(f"\n[FAIL] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        print("[PASS] population_pin_without_its_member_set: every pinned "
              "population size has its member set pinned beside it.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
