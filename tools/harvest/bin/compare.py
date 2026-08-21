#!/usr/bin/env python3
"""compare.py <before.tsv> <after.tsv> -- what the fetch changed.

Scope: the extra-clone worktrees (everything whose repo is NOT ~/vibe-ic). Rows are
matched on (host, path). A worktree absent from AFTER is reported as GONE/not
re-measured rather than silently dropped.
"""
import sys, csv
def load(p):
    rows = list(csv.reader(open(p, newline=""), delimiter="\t"))
    hdr, rows = rows[0], rows[1:]
    I = {k: i for i, k in enumerate(hdr)}
    out = {}
    for r in rows:
        g = lambda k: r[I[k]] if I[k] < len(r) else ""
        out[(g("host"), g("path"))] = {k: g(k) for k in hdr}
    return out

B, A = load(sys.argv[1]), load(sys.argv[2])
isx = lambda d: d["repo"] != "/home/reyerchu/vibe-ic"
bx = {k: v for k, v in B.items() if isx(v)}
ax = {k: v for k, v in A.items() if isx(v)}

def tally(d):
    t = {"RECOVER": 0, "LANDED": 0, "ABANDON": 0}
    for v in d.values(): t[v["verdict"]] = t.get(v["verdict"], 0) + 1
    return t

both = sorted(set(bx) & set(ax))
gone = sorted(set(bx) - set(ax))
new  = sorted(set(ax) - set(bx))
changed = [k for k in both if bx[k]["verdict"] != ax[k]["verdict"]]

print(f"BEFORE extra-clone worktrees: {len(bx)}   {tally(bx)}")
print(f"AFTER  extra-clone worktrees: {len(ax)}   {tally(ax)}")
print(f"matched {len(both)} | not re-measured (clone or tree deleted) {len(gone)} | new {len(new)}")
print(f"VERDICT CHANGED: {len(changed)}")
print()
tb, ta = tally({k: bx[k] for k in both}), tally({k: ax[k] for k in both})
print("on the matched set only:")
for v in ("RECOVER", "LANDED", "ABANDON"):
    print(f"  {v:<8} {tb[v]:>4} -> {ta[v]:>4}   ({ta[v]-tb[v]:+d})")
print()
if changed:
    print("EVERY worktree whose verdict changed:")
    print()
    hdr = f"{'host':<5} {'worktree':<44} {'before':<9} {'after':<9} {'nadd b->a':<14} {'rule b->a':<11} subject"
    print(hdr); print("-" * len(hdr))
    for k in sorted(changed, key=lambda k: (ax[k]["verdict"], -int(ax[k]["code_add"] or 0))):
        b, a = bx[k], ax[k]
        p = b["path"].replace("/home/reyerchu/", "~/")
        print(f"{k[0]:<5} {p:<44} {b['verdict']:<9} {a['verdict']:<9} "
              f"{b['nadd']+'->'+a['nadd']:<14} {b['rule']+'->'+a['rule']:<11} {a['subject'][:52]}")
if gone:
    print()
    print(f"not re-measured ({len(gone)}) -- clone or worktree deleted between rounds:")
    for k in gone[:60]:
        print(f"  {k[0]}  {bx[k]['path'].replace('/home/reyerchu/','~/'):<46} was {bx[k]['verdict']}")
    if len(gone) > 60: print(f"  ... and {len(gone)-60} more")
