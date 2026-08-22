#!/usr/bin/env python3
"""Broad: every CALL whose source text contains a *_NOT_FOUND literal."""
import ast, sys, re
from pathlib import Path
ROOT = Path(sys.argv[1])
CODE = re.compile(r"\b([A-Z][A-Z0-9_]*_NOT_FOUND)\b")
SRC_WORDS = re.compile(r"path|dir\b|file|lef|view|source|root|search|glob|tree|config|libs?\b|scan|under|resolved", re.I)
rows=[]
for p in sorted(ROOT.glob("*.py")):
    txt = p.read_text(errors="replace")
    if "_NOT_FOUND" not in txt: continue
    try: tree = ast.parse(txt)
    except SyntaxError: continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call): continue
        try: s = ast.unparse(node)
        except Exception: continue
        m = CODE.search(s)
        if not m: continue
        # skip nested duplicates: only innermost call carrying the code
        if any(isinstance(c, ast.Call) and CODE.search(ast.unparse(c)) for c in ast.iter_child_nodes(node) if isinstance(c, ast.Call)):
            pass
        rows.append((p.name, node.lineno, m.group(1), SRC_WORDS.search(s) is not None, s.replace("\n"," ")[:200]))
# dedupe by (file,line,code)
seen=set(); ded=[]
for r in rows:
    k=(r[0],r[1],r[2])
    if k in seen: continue
    seen.add(k); ded.append(r)
print(f"population (calls carrying a *_NOT_FOUND literal): {len(ded)}")
print(f"names a source token: {sum(1 for r in ded if r[3])}/{len(ded)}")
print()
for r in ded:
    flag = "OK " if r[3] else "NO "
    print(f"{flag} {r[0]}:{r[1]} {r[2]}")
