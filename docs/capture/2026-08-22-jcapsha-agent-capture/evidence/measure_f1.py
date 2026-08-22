#!/usr/bin/env python3
"""Measure: how many *_NOT_FOUND refusals name the SEARCH SPACE they covered?"""
import ast, sys, re
from pathlib import Path

ROOT = Path(sys.argv[1])
CODE = re.compile(r"^[A-Z][A-Z0-9_]*_NOT_FOUND$")

# source-naming: the message must reference a place that was READ, not just a hit count
SRC_WORDS = re.compile(r"path|dir|file|lef|view|source|root|search|glob|tree|config|lib|scan|under|from ", re.I)

rows = []
for p in sorted(ROOT.glob("*.py")):
    try:
        tree = ast.parse(p.read_text(errors="replace"))
    except SyntaxError:
        continue
    src = p.read_text(errors="replace").splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        args = list(node.args)
        if not args:
            continue
        a0 = args[0]
        if not (isinstance(a0, ast.Constant) and isinstance(a0.value, str) and CODE.match(a0.value)):
            continue
        msg = args[1] if len(args) > 1 else None
        if msg is None:
            for kw in node.keywords:
                if kw.arg in ("message", "detail", "msg", "why"):
                    msg = kw.value
        msg_src = ast.unparse(msg) if msg is not None else ""
        has_interp = isinstance(msg, ast.JoinedStr)
        names_source = bool(SRC_WORDS.search(msg_src))
        rows.append((p.name, a0.value, node.lineno, has_interp, names_source, msg_src[:150]))

tot = len(rows)
named = sum(1 for r in rows if r[4])
print(f"population: {tot} *_NOT_FOUND refusal sites in {ROOT}")
print(f"message names a SOURCE-ish token: {named}/{tot}")
print(f"message has NO interpolation at all: {sum(1 for r in rows if not r[3])}/{tot}")
print()
print("--- sites whose message names NO source token ---")
for r in rows:
    if not r[4]:
        print(f"  {r[0]}:{r[2]}  {r[1]}")
        print(f"      {r[5]}")
