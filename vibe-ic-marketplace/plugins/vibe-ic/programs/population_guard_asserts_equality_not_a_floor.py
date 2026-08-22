#!/usr/bin/env python3
"""A population guard that cannot fail: a literal asserted against its own size.

THIS GATE BLOCKS (rc=1) on a NEW one.

WHAT IT ASKS THE REPOSITORY
===========================
A population guard must be able to answer NO. When the collection it measures
is a LITERAL in the same scope and the bound is that literal's own length, the
assertion is a tautology: it passes for free, on every tree, forever. The
capture record names this shape exactly — "THE OBVIOUS WRONG GUARD, and one is
already in the tree: asserting the declared table against ITS OWN length. That
is self-consistency; it passes for free."

It is the brief's own doctrine turned on a guard rather than a test: a test
that cannot go red is not a test, and a denominator that cannot go red is not a
denominator.

THE PREDICATE
=============
A finding is `len(X) <op> N` where

  * `X` resolves, IN ITS OWN SCOPE, to a list/tuple/dict/set LITERAL,
  * that name is never mutated in that scope — no `append`, `extend`, `add`,
    `update`, `pop`, `remove`, `insert`, `clear`, no re-binding to a non-literal
    and no use as a loop target,
  * and the comparison is TRUE for the literal's own length: `== n` where the
    literal has n, `>= n` where it has at least n, `> n` where it has more.

SCOPE IS LOAD-BEARING, and getting it wrong is most of the false positives.
Tracking bindings module-wide reported `len(steps) > 0` as a tautology because
some OTHER function in the file binds `steps` to a one-element literal; the
assertion's own scope binds it from a tuple-unpack of a call. Per-scope
bindings took the finding count from 6 to 3 and removed every false positive.

A SET LITERAL OF NON-CONSTANTS IS A DISTINCTNESS ASSERTION, NOT A COUNT.
`len({G.RC_OK, G.RC_FAIL, G.RC_REFUSE}) == 3` says those three constants are
DIFFERENT, and it fails the moment two of them collide — which is the whole
point of writing it. It is not a tautology and is never flagged.

COVERAGE, MEASURED — the other half of the record is NOT covered
================================================================
The record's headline is broader: a guard over a DISCOVERED population must
assert set EQUALITY against the DECLARED table and print the symmetric
difference, never a lower bound. That half is not implemented here, and the
measurement says why.

    floor assertions over a discovered set (glob/walk), N >= 2      14
    of those, in a module that also holds a declared literal table   4

The 4 do not establish the relation the rule needs. A floor is the defect only
when a DECLARED table DRIVES the discovered population, and co-occurrence is
not that relation — the four modules' literal tables are lexical fixtures and
junk-fragment lists, unrelated to the discovered set. Worse, the best-known
candidate is arguably CORRECT: `test_ppa_layer_exit_contract.py:76` guards
`len(PPA_PROGRAMS) >= 14` over a fully parametrised glob, and its own comment
calls it "The denominator. An empty glob would make every parametrized arm
below vacuously green" — an emptiness guard over a set with no declared table
to drift against.

Separating the two needs the DRIVES relation, which is a dataflow question this
scan does not answer. The tautology half is exact, so it ships; the floor half
is named with its numbers so the next lane starts from the measurement.

EXIT
====
  0  no guard asserts a literal against its own size
  1  a NEW one, or a stale inventory row
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

_INVENTORY_NAME = "tautological_population_guard_inventory.json"

_MUTATORS = ("append", "extend", "add", "update", "pop", "remove", "clear",
             "insert", "sort", "reverse")


def _literal_len(node: ast.AST) -> Optional[int]:
    """The size of a collection literal, or None if it is not one.

    A SET of non-constants is a distinctness assertion, not a count.
    """
    if isinstance(node, ast.Set):
        if not all(isinstance(e, ast.Constant) for e in node.elts):
            return None
        return len({e.value for e in node.elts})
    if isinstance(node, (ast.List, ast.Tuple)):
        return len(node.elts)
    if isinstance(node, ast.Dict):
        return len(node.keys)
    return None


def _scope_bindings(scope: ast.AST) -> Tuple[Dict[str, int], Set[str]]:
    """(literal sizes, mutated names) bound in THIS scope, excluding nested."""
    lits: Dict[str, int] = {}
    mut: Set[str] = set()

    def visit(node: ast.AST, top: bool) -> None:
        for c in ast.iter_child_nodes(node):
            if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
                continue                     # a nested scope is its own subject
            if isinstance(c, ast.Assign):
                for t in c.targets:
                    if isinstance(t, ast.Name):
                        L = _literal_len(c.value)
                        if L is not None:
                            lits[t.id] = L
                        else:
                            mut.add(t.id)
                    elif isinstance(t, (ast.Tuple, ast.List)):
                        for e in t.elts:
                            if isinstance(e, ast.Name):
                                mut.add(e.id)
            if isinstance(c, ast.AugAssign) and isinstance(c.target, ast.Name):
                mut.add(c.target.id)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) \
                    and c.func.attr in _MUTATORS \
                    and isinstance(c.func.value, ast.Name):
                mut.add(c.func.value.id)
            if isinstance(c, ast.For) and isinstance(c.target, ast.Name):
                mut.add(c.target.id)
            visit(c, False)

    visit(scope, True)
    return lits, mut


def _tautology(op: ast.cmpop, size: int, bound: int) -> bool:
    if isinstance(op, ast.Eq):
        return size == bound
    if isinstance(op, ast.GtE):
        return size >= bound
    if isinstance(op, ast.Gt):
        return size > bound
    return False


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    parsed = 0
    measured = 0
    base = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
            / "tests")
    if not base.is_dir():
        return findings, {"test_modules": 0, "literal_length_assertions": 0,
                          "tautologies": 0}
    seen: Set[Tuple[str, int]] = set()
    for f in sorted(base.rglob("test_*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        parsed += 1
        rel = f.relative_to(root).as_posix()
        scopes: List[ast.AST] = [tree] + [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for sc in scopes:
            lits, mut = _scope_bindings(sc)
            for n in ast.walk(sc):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and n is not sc:
                    continue
                if not (isinstance(n, ast.Compare) and len(n.ops) == 1):
                    continue
                left, right = n.left, n.comparators[0]
                if not (isinstance(left, ast.Call)
                        and isinstance(left.func, ast.Name)
                        and left.func.id == "len" and left.args):
                    continue
                a = left.args[0]
                if isinstance(a, ast.Name):
                    if a.id in mut:
                        continue
                    size = lits.get(a.id)
                else:
                    size = _literal_len(a)
                if size is None:
                    continue
                measured += 1
                if not (isinstance(right, ast.Constant)
                        and isinstance(right.value, int)):
                    continue
                if not _tautology(n.ops[0], size, right.value):
                    continue
                if (rel, n.lineno) in seen:
                    continue
                seen.add((rel, n.lineno))
                try:
                    text = ast.unparse(n)
                except Exception:            # noqa: BLE001
                    text = "<expr>"
                findings.append({"file": rel, "line": n.lineno,
                                 "assertion": text[:80], "literal_size": size})
    return findings, {"test_modules": parsed,
                      "literal_length_assertions": measured,
                      "tautologies": len(findings)}


def _key(f: dict) -> str:
    return f"{f['file']}::{f['assertion']}"


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
            print("[CANNOT DETERMINE] population_guard_asserts_equality_not_a_"
                  "floor: no repository root. NOT a pass.", file=sys.stderr)
            return 2
        findings, denom = scan(root)
        if denom["test_modules"] == 0:
            print("[CANNOT DETERMINE] population_guard_asserts_equality_not_a_"
                  "floor: no tests/ under that root. NOT a pass.",
                  file=sys.stderr)
            return 2
        inv_path = Path(a.inventory) if a.inventory else \
            Path(__file__).resolve().parent / _INVENTORY_NAME
        rows = json.loads(inv_path.read_text(encoding="utf-8")).get("known", []) \
            if inv_path.exists() else []
        known = {r["key"] for r in rows}
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] population_guard_asserts_equality_not_a_"
              f"floor: the walk did not complete ({type(exc).__name__}: {exc}). "
              f"NOT a pass.", file=sys.stderr)
        return 2

    print(f"  test modules parsed:            {denom['test_modules']}")
    print(f"  len() over an unmutated literal:{denom['literal_length_assertions']:5d}")
    print(f"  guards that cannot fail:        {denom['tautologies']}")
    print(f"  inventory rows applied:         {len(known)}")

    seen = {_key(f) for f in findings}
    new = sorted(seen - known)
    stale = sorted(known - seen)
    rc = 0
    if new:
        rc = 1
        print(f"\n[FAIL] {len(new)} population guard(s) assert a literal "
              f"against its own size:")
        for f in findings:
            if _key(f) in new:
                print(f"   {f['file']}:{f['line']}  {f['assertion']}"
                      f"   (the literal holds {f['literal_size']})")
        print("\n  This passes for free, on every tree, forever. Assert the "
              "literal against the\n  POPULATION it is supposed to describe — "
              "as a set, in both directions — or\n  delete the guard; a "
              "denominator that cannot go red is not a denominator.")
    if stale:
        rc = 1
        print(f"\n[FAIL] {len(stale)} inventory row(s) match nothing:")
        for k in stale:
            print(f"   {k}")
    if rc == 0:
        print("[PASS] population_guard_asserts_equality_not_a_floor: no guard "
              "asserts a literal against its own size.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
