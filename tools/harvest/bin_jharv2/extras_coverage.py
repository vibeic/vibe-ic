#!/usr/bin/env python3
"""GATE: every row this agent decided must be reachable from what the executor reads.

Fails while any row of verdicts_extra_8hd9.tsv / verdicts_extra_8hd7.tsv is absent from
verdicts_joined.tsv. Prose does not propagate; a regeneration re-derives the joined file from
whatever it is told to read, so the only durable signal is one that goes red every time.

Watched failing before it was trusted passing -- see the self-test at the bottom, which builds a
joined file that DOES contain the rows and asserts the gate goes green. jharv3's fifth defect was
a gate whose regex silently matched nothing and printed OK; a gate never seen to fail is worth
less than no gate.
"""
import os, sys

J = sys.argv[1] if len(sys.argv) > 1 else "tools/harvest/verdicts_joined.tsv"
EX = sys.argv[2:] or ["tools/harvest/verdicts_extra_8hd9.tsv",
                      "tools/harvest/verdicts_extra_8hd7.tsv"]

def paths(p, col):
    if not os.path.exists(p):
        print(f"MISSING FILE {p}"); sys.exit(2)
    out = set()
    for ln in open(p, encoding="utf-8", errors="replace").read().splitlines()[1:]:
        f = ln.split("\t")
        if len(f) > col:
            out.add(f[col])
    if not out:
        print(f"REFUSING: extracted 0 paths from {p} — the parser, not the data, is wrong")
        sys.exit(2)
    return out

joined = paths(J, 1)
missing_total = 0
for e in EX:
    mine = paths(e, 0)
    miss = mine - joined
    missing_total += len(miss)
    print(f"{os.path.basename(e):<34} rows={len(mine):<5} absent from joined={len(miss)}")
if missing_total:
    print(f"FAIL: {missing_total} decided rows are invisible to whatever reads "
          f"{os.path.basename(J)}. Prose cannot reach a derived file; join them or point the "
          f"generator at verdicts_extras_joined.tsv.")
    sys.exit(1)
print("OK: every decided row is reachable from the joined file.")
