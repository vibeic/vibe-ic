#!/usr/bin/env python3
"""corpus_cardinality_pin_scan.py — find assertions pinned to a CORPUS CENSUS.

THE LIE-SHAPE. A test asserts `len(rows) == 23` over whatever is published
under `benchmark-data/`. The 23 is not a property of the code under test; it is
the size of the publication set on the day it was typed. Publish a cell,
withdraw a cell, reorganise the tree — the assertion fires, and its message
says `23 != 22`, which tells the reader nothing about correctness. Worse, it
reads as a regression in whatever change happened to be in flight.

Measured on this repo: the #905 corpus reorganisations moved IC-level strays
into their published cells, and `test_issue377_l17_name_fuses_declared_signals`
went red at `fired == 16` with the checker byte-for-byte unchanged.

WHAT IT LOOKS FOR
  * `<countish> == <int>` and `<int> == <countish>`, incl. `assertEqual`
  * chained `a == b == <int>`
  * TUPLE-OF-COUNTS: `(a, b, c) == (35, 130, 64)` — added after this shape
    survived the first sweep and was found only when a two-arm control on a
    withdrawn cell went red.
...inside a test that reaches `benchmark-data/` directly or through a helper
or module constant in the same file.

WHAT A HIT IS AND IS NOT. This is a REPORTER, not a gate: it exits 0 whatever
it finds. Plenty of hits are load-bearing — a 32 that is an md5 hex length, a
`== 0` that means "zero offenders", a count over a `tmp_path` fixture the file
happens to sit beside. The judgement is: is the integer the PROPERTY, or is it
a stand-in for one? Fix the stand-ins; for a load-bearing number, derive it
from the collection it describes rather than typing it a second time.

Usage:
    python3 corpus_cardinality_pin_scan.py <tests_dir>
"""

from __future__ import annotations
import ast, re, sys
from pathlib import Path

TESTS = Path(sys.argv[1])
CORPUS_RE = re.compile(r"benchmark-data|benchmark_data|BENCHMARK_DATA")

COUNTISH_CALL = {"len", "sum"}
COUNTISH_NAME = re.compile(
    r"(^|_)(count|total|n|num|rows|cells|hits|fired|checked|examined|"
    r"seen|found|projects|entries|files|offenders|matches)($|_)", re.I)


def const_int(node):
    return (isinstance(node, ast.Constant) and isinstance(node.value, int)
            and not isinstance(node.value, bool))


def has_countish_call(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id in COUNTISH_CALL:
            return True
        if isinstance(n, ast.Attribute) and n.attr in ("count",):
            return True
    return False


def countish(node, counters):
    if has_countish_call(node):
        return True
    if isinstance(node, ast.Name):
        return node.id in counters or bool(COUNTISH_NAME.search(node.id))
    if isinstance(node, ast.Attribute):
        return bool(COUNTISH_NAME.search(node.attr))
    if isinstance(node, ast.Subscript):
        return countish(node.value, counters)
    return False


def counters_in(fn):
    """Names that accumulate: `x = 0` … `x += 1`, or `x = len(...)`/`sum(...)`."""
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
        if isinstance(n, ast.Assign) and has_countish_call(n.value):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
    return out


def main():
    rows = []
    for path in sorted(TESTS.glob("test_*.py")):
        src = path.read_text(errors="replace")
        if not CORPUS_RE.search(src):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.split("\n")
        # helpers in this file that reach the corpus
        corpus_helpers, funcs = set(), {}
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs[n.name] = n
                if CORPUS_RE.search(ast.get_source_segment(src, n) or ""):
                    corpus_helpers.add(n.name)
        # module-level corpus constants
        mod_const = set()
        for n in tree.body:
            if isinstance(n, ast.Assign) and CORPUS_RE.search(
                    ast.get_source_segment(src, n) or ""):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        mod_const.add(t.id)
        # close the helper set (depth 3)
        for _ in range(3):
            for name, fn in funcs.items():
                if name in corpus_helpers:
                    continue
                called = {c.func.id for c in ast.walk(fn)
                          if isinstance(c, ast.Call)
                          and isinstance(c.func, ast.Name)}
                used = {v.id for v in ast.walk(fn) if isinstance(v, ast.Name)}
                if called & corpus_helpers or used & mod_const:
                    corpus_helpers.add(name)

        for name, fn in funcs.items():
            if not name.startswith("test_"):
                continue
            called = {c.func.id for c in ast.walk(fn)
                      if isinstance(c, ast.Call)
                      and isinstance(c.func, ast.Name)}
            used = {v.id for v in ast.walk(fn) if isinstance(v, ast.Name)}
            seg = ast.get_source_segment(src, fn) or ""
            reaches = bool(called & corpus_helpers or used & mod_const
                           or CORPUS_RE.search(seg))
            if not reaches:
                continue
            ctrs = counters_in(fn)
            for n in ast.walk(fn):
                pin = None
                # TUPLE-OF-COUNTS: `(a, b, c) == (35, 130, 64)`. Missed by
                # the scalar rule below, and it is the shape that survives a
                # `len(...) == <int>` sweep — found only after one of them
                # broke a two-arm control.
                if isinstance(n, ast.Compare) and len(n.ops) == 1 \
                        and isinstance(n.ops[0], ast.Eq) \
                        and isinstance(n.left, ast.Tuple) \
                        and isinstance(n.comparators[0], ast.Tuple) \
                        and all(const_int(e) for e in n.comparators[0].elts) \
                        and n.comparators[0].elts \
                        and any(countish(e, ctrs) for e in n.left.elts):
                    rows.append((path.name, name, n.lineno,
                                 lines[n.lineno - 1].strip()[:150],
                                 tuple(e.value for e in n.comparators[0].elts)))
                    continue
                if isinstance(n, ast.Compare) and len(n.ops) >= 1:
                    operands = [n.left] + list(n.comparators)
                    for op, right in zip(n.ops, n.comparators):
                        if not isinstance(op, ast.Eq):
                            continue
                        for a, b in ((n.left, right), (right, n.left)):
                            if const_int(a) and countish(b, ctrs):
                                pin = a.value
                    # chained `a == b == 131`
                    if pin is None and len(operands) > 2:
                        ints = [o.value for o in operands if const_int(o)]
                        if ints and any(countish(o, ctrs) for o in operands):
                            pin = ints[0]
                elif isinstance(n, ast.Call) and isinstance(
                        n.func, ast.Attribute) and n.func.attr == "assertEqual" \
                        and len(n.args) >= 2:
                    for a, b in ((n.args[0], n.args[1]),
                                 (n.args[1], n.args[0])):
                        if const_int(a) and countish(b, ctrs):
                            pin = a.value
                if pin is None:
                    continue
                rows.append((path.name, name, n.lineno,
                             lines[n.lineno - 1].strip()[:150], pin))
    seen = set()
    for r in rows:
        key = (r[0], r[2])
        if key in seen:
            continue
        seen.add(key)
        print(f"{r[0]}::{r[1]}  L{r[2]}  pin={r[4]}\n    {r[3]}")
    print(f"\nTOTAL {len(seen)} pin(s) in "
          f"{len({r[0] for r in rows})} file(s)")


main()
