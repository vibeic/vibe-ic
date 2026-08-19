#!/usr/bin/env python3
"""split_reds.py — the three-way split, BY NODE NAME.

Differences two `reds.json` files (base = clean origin/main, cand = the
assembled candidate) and prints every node in exactly one bucket:

  PRE_EXISTING   red on BOTH        -> not the candidate's
  INTRODUCED     red only on CAND   -> the candidate introduced it
  FIXED          red only on BASE   -> the candidate turned it green

REFUSES to classify a node whose file is BLIND on either side: if a file
produced no evidence in one tree, "red only on the other" is an artefact of
the missing evidence and not a finding. Those are printed as NOT DETERMINED
with the side that was blind, and never counted into the three buckets.
"""
import json, sys
from pathlib import Path

base = json.loads(Path(sys.argv[1]).read_text())
cand = json.loads(Path(sys.argv[2]).read_text())

blind_base = {b["file"]: b for b in base["blind"]}
blind_cand = {b["file"]: b for b in cand["blind"]}
B = {r["node"]: r for r in base["reds"]}
C = {r["node"]: r for r in cand["reds"]}

def bucket(node, r):
    f = r["file"]
    if f in blind_base or f in blind_cand:
        side = []
        if f in blind_base: side.append(f"base:{blind_base[f]['bucket']}")
        if f in blind_cand: side.append(f"cand:{blind_cand[f]['bucket']}")
        return "NOT_DETERMINED", ",".join(side)
    if node in B and node in C: return "PRE_EXISTING", ""
    if node in C: return "INTRODUCED", ""
    return "FIXED", ""

rows = []
for node in sorted(set(B) | set(C)):
    r = C.get(node) or B[node]
    b, why = bucket(node, r)
    rows.append({"node": node, "file": r["file"], "bucket": b, "why": why,
                 "kind": r["kind"], "message": r["message"]})

order = ["INTRODUCED", "PRE_EXISTING", "FIXED", "NOT_DETERMINED"]
print(f"base head {base['head'][:9]}  reds {len(B)}   |   cand head {cand['head'][:9]}  reds {len(C)}")
for b in order:
    sel = [r for r in rows if r["bucket"] == b]
    print(f"\n=== {b}  ({len(sel)}) ===")
    for r in sel:
        extra = f"   [{r['why']}]" if r["why"] else ""
        print(f"  {r['kind'].upper():7s} {r['node']}{extra}")
        if r["message"]:
            print(f"          {r['message'][0][:150]}")

# The BLIND files themselves, which carry no node names at all and so cannot
# appear above. A file with no evidence has UNKNOWN reds, never zero.
allblind = sorted(set(blind_base) | set(blind_cand))
if allblind:
    print(f"\n=== FILES WITH NO EVIDENCE — reds UNKNOWN, not zero  ({len(allblind)}) ===")
    for f in allblind:
        sides = []
        if f in blind_base: sides.append(f"base {blind_base[f]['bucket']}: {blind_base[f]['reason']}")
        if f in blind_cand: sides.append(f"cand {blind_cand[f]['bucket']}: {blind_cand[f]['reason']}")
        print(f"  {f}\n      " + "\n      ".join(sides))

Path(sys.argv[3]).write_text(json.dumps({"base": base["head"], "cand": cand["head"], "rows": rows,
    "blind_files": allblind}, indent=1) + "\n")
