#!/usr/bin/env python3
"""Establish "none deleted, no assertion relaxed" by PARSING, not by asserting it.

The publishing agent made this point against a claim of mine and was right: a
sentence about a diff is the claim a reader most wants to skip verifying, and
numstat cannot tell "docstring only" from "behaviour changed by the same number
of lines". The same distrust belongs on my own strongest unverified sentence.

Counts are NECESSARY AND NOT SUFFICIENT -- an assertion can be rewritten weaker
at an unchanged count -- so this compares the assert EXPRESSIONS structurally,
and then the whole function with its docstring stripped.

Usage:  no_test_was_weakened.py <base.py> <tip.py>
Exit:   0 nothing weakened   1 something was   2 could not read a revision
"""
import ast, sys

def funcs(path):
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except OSError as e:
        print(f"NOT VERIFIED: {e}")
        raise SystemExit(2)
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_"):
            stripped = ast.parse(ast.unparse(n)).body[0]
            if (stripped.body and isinstance(stripped.body[0], ast.Expr)
                    and isinstance(stripped.body[0].value, ast.Constant)
                    and isinstance(stripped.body[0].value.value, str)):
                stripped.body = stripped.body[1:]
            out[n.name] = {
                "asserts": [ast.dump(x.test, annotate_fields=False)
                            for x in ast.walk(n) if isinstance(x, ast.Assert)],
                "code": ast.dump(stripped, annotate_fields=False),
            }
    return out

base, tip = funcs(sys.argv[1]), funcs(sys.argv[2])
if not base:
    print("NOT VERIFIED: the base revision parsed to ZERO tests -- an empty "
          "denominator is not a pass (#564)")
    raise SystemExit(2)

deleted  = sorted(set(base) - set(tip))
fewer    = [k for k in base if k in tip
            and len(tip[k]["asserts"]) < len(base[k]["asserts"])]
rewritten= [k for k in base if k in tip
            and base[k]["asserts"] != tip[k]["asserts"]]
touched  = [k for k in base if k in tip and base[k]["code"] != tip[k]["code"]]

print(f"base tests {len(base)}  ->  tip tests {len(tip)}  (+{len(set(tip)-set(base))})")
print(f"  deleted ................... {deleted or 'none'}")
print(f"  fewer assertions .......... {fewer or 'none'}")
print(f"  assertion REWRITTEN ....... {rewritten or 'none'}")
print(f"  any code change at all .... {touched or 'none'}")
bad = deleted or fewer or rewritten
print("\n" + ("PASS: no pre-existing test was deleted, shortened or rewritten"
              if not bad else "FAIL: see above"))
raise SystemExit(1 if bad else 0)
