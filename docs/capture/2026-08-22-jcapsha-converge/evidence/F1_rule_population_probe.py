#!/usr/bin/env python3
"""PROBE, NOT SHIPPED. Measures the population of the corrected F1 rule:

  an absence verdict must interpolate THE COLLECTION IT ITERATED --
  the actual list of things opened -- not a count of it.

Question this answers: on today's corpus, how many absence verdicts would
this rule accept, and how many would it refuse? A rule that refuses most of
them cannot ship today, and that number is the finding, not an obstacle.
"""
import ast, sys, re
from pathlib import Path

ABSENCE = re.compile(r"_(NOT_FOUND|ABSENT|MISSING|NOT_PRESENT)$")
SEARCHY = ("glob", "rglob", "iterdir", "walk", "listdir", "scandir",
           "finditer", "findall", "read_text", "open", "discover", "resolve_")


def enclosing_scopes(tree):
    """map node -> nearest enclosing FunctionDef"""
    out = {}
    def walk(node, fn):
        for ch in ast.iter_child_nodes(node):
            nf = ch if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            out[id(ch)] = fn
            walk(ch, nf)
    walk(tree, None)
    return out


def searched_names(fn):
    """Names that denote something the scope ITERATED or OPENED."""
    names = set()
    if fn is None:
        return names
    for n in ast.walk(fn):
        if isinstance(n, (ast.For, ast.AsyncFor)):
            for x in ast.walk(n.iter):
                if isinstance(x, ast.Name):
                    names.add(x.id)
                if isinstance(x, ast.Attribute):
                    names.add(x.attr)
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for g in n.generators:
                for x in ast.walk(g.iter):
                    if isinstance(x, ast.Name):
                        names.add(x.id)
        if isinstance(n, ast.Compare):
            for op, cmp in zip(n.ops, n.comparators):
                if isinstance(op, (ast.In, ast.NotIn)):
                    for x in ast.walk(cmp):
                        if isinstance(x, ast.Name):
                            names.add(x.id)
        if isinstance(n, ast.Call):
            f = n.func
            tail = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else "")
            if any(tail.startswith(s) or tail == s for s in SEARCHY):
                # the receiver and the assignment target both count
                for x in ast.walk(n):
                    if isinstance(x, ast.Name):
                        names.add(x.id)
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and isinstance(n.value, ast.Call):
                    f = n.value.func
                    tail = f.attr if isinstance(f, ast.Attribute) else (
                        f.id if isinstance(f, ast.Name) else "")
                    if any(tail.startswith(s) or tail == s for s in SEARCHY):
                        names.add(t.id)
    return names


def interpolated(call):
    """Names the refusal's message interpolates."""
    out = set()
    for a in call.args[1:]:
        for x in ast.walk(a):
            if isinstance(x, ast.Name):
                out.add(x.id)
            if isinstance(x, ast.Attribute):
                out.add(x.attr)
    return out


def main(root):
    carries, bare, nosearch, total = [], [], [], 0
    for p in sorted(Path(root).rglob("*.py")):
        if "/tests/" in str(p):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        scopes = enclosing_scopes(tree)
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call) or not n.args:
                continue
            a0 = n.args[0]
            if not (isinstance(a0, ast.Constant) and isinstance(a0.value, str)):
                continue
            if not ABSENCE.search(a0.value):
                continue
            total += 1
            fn = scopes.get(id(n))
            while fn is not None and not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = scopes.get(id(fn))
            searched = searched_names(fn)
            got = interpolated(n) & searched
            rec = f"{p.name}:{n.lineno}  {a0.value}"
            if got:
                carries.append(rec + f"   <- {sorted(got)}")
            elif not searched:
                nosearch.append(rec)
            else:
                bare.append(rec + f"   (scope searched: {sorted(searched)[:4]})")
    print(f"absence verdicts                     : {total}")
    print(f"IN SCOPE (a collection was searched) : {len(carries)+len(bare)}")
    print(f"  carry the collection               : {len(carries)}")
    print(f"  WOULD BE REFUSED                   : {len(bare)}")
    print(f"OUT OF SCOPE (nothing iterated)      : {len(nosearch)}")
    print("\n-- WOULD BE REFUSED (in scope, does not name what it searched) --")
    for r in bare:
        print("   ", r)
    print("\n-- OUT OF SCOPE: absence of ONE named thing, no search --")
    for r in nosearch:
        print("   ", r)
    return 0


sys.exit(main(sys.argv[1]))
