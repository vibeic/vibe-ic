#!/usr/bin/env python3
"""PROBE 2 for F1. Predicate: does an absence verdict name the SUBJECT OF THE
CONDITION THAT RAISED IT?

Probe 1 asked "does it name something the enclosing function iterated" and was
wrong: it attributed unrelated iterations from anywhere in a long function.
This walks from the refusal UP to the `if` that guards it and takes the subject
from that test only.
"""
import ast, re, sys
from pathlib import Path

ABSENCE = re.compile(r"_(NOT_FOUND|ABSENT|MISSING|NOT_PRESENT)$")


def parents(tree):
    p = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            p[id(ch)] = node
    return p


def guarding_if(node, par, byid):
    """The nearest enclosing If whose TEST decides this node is reached."""
    cur, prev = par.get(id(node)), node
    while cur is not None:
        if isinstance(cur, ast.If):
            # only if we came from the body/orelse, not from the test itself
            if any(prev is s or prev in ast.walk(s) for s in cur.body + cur.orelse):
                return cur
        prev, cur = cur, par.get(id(cur))
    return None


def names_in(node):
    out = set()
    for x in ast.walk(node):
        if isinstance(x, ast.Name):
            out.add(x.id)
        elif isinstance(x, ast.Attribute):
            out.add(x.attr)
    return out


def interpolated(call):
    out = set()
    for a in call.args[1:] + [k.value for k in call.keywords]:
        out |= names_in(a)
    return out


def main(root):
    named, unnamed, noguard, total = [], [], [], 0
    for p in sorted(Path(root).rglob("*.py")):
        if "/tests/" in str(p):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        par = parents(tree)
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call) or not n.args:
                continue
            a0 = n.args[0]
            if not (isinstance(a0, ast.Constant) and isinstance(a0.value, str)):
                continue
            if not ABSENCE.search(a0.value):
                continue
            total += 1
            g = guarding_if(n, par, None)
            rec = f"{p.name}:{n.lineno}  {a0.value}"
            if g is None:
                noguard.append(rec)
                continue
            subj = names_in(g.test)
            got = interpolated(n) & subj
            if got:
                named.append(rec + f"   <- {sorted(got)}")
            else:
                unnamed.append(rec + f"   guard subject: {sorted(subj)}")
    print(f"absence verdicts          : {total}")
    print(f"  names its guard subject : {len(named)}")
    print(f"  DOES NOT                : {len(unnamed)}")
    print(f"  no guarding `if`        : {len(noguard)}")
    print("\n-- WOULD BE REFUSED --")
    for r in unnamed:
        print("   ", r)
    print("\n-- NO GUARDING IF (rule does not apply) --")
    for r in noguard:
        print("   ", r)
    return 0


sys.exit(main(sys.argv[1]))
