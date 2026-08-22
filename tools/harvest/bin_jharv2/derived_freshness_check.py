#!/usr/bin/env python3
"""verdicts_extras_joined.tsv is DERIVED from the two extra shard files. Nothing stops the sources
from moving without it, and nothing did: I edited four evidence strings and shipped the stale
derived file in the same commit. That is the FIFTH time this session a source was refreshed and its
derived artefact was not, so the fix is a gate, not another regeneration.

Rows are keyed by (host, path), NOT path: 1084 source rows hold 1081 distinct paths, because the
same path exists on two different hosts. A path-keyed comparison silently drops three rows and then
reports agreement -- the same class of error as keying corrections by path alone.

Compares verdict AND evidence. A verdict-only check passes while the evidence says the opposite,
which is exactly the failure it exists to catch.
"""
import csv, sys, os

def read(p, cols):
    with open(p) as f:
        rows = list(csv.reader(f, delimiter='\t'))
    if not rows: raise SystemExit(f"{p}: empty")
    return rows[0], rows[1:]

def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'tools/harvest'
    joined = os.path.join(base, 'verdicts_extras_joined.tsv')
    srcs = [(os.path.join(base, 'verdicts_extra_8hd9.tsv'), '105'),
            (os.path.join(base, 'verdicts_extra_8hd7.tsv'), '102')]
    _, jr = read(joined, 5)
    jd = {}
    for r in jr:
        if len(r) >= 5: jd[(r[0], r[1])] = (r[2], r[3])
    sd = {}
    for p, host in srcs:
        _, rr = read(p, 3)
        for r in rr:
            if len(r) >= 3: sd[(host, r[0])] = (r[1], r[2])
    missing  = sorted(k for k in sd if k not in jd)
    extra    = sorted(k for k in jd if k not in sd)
    vdiff    = sorted(k for k in sd if k in jd and sd[k][0] != jd[k][0])
    ediff    = sorted(k for k in sd if k in jd and sd[k][1] != jd[k][1])
    print(f"  source rows (host,path) : {len(sd)}")
    print(f"  derived rows            : {len(jd)}")
    print(f"  missing from derived    : {len(missing)}")
    print(f"  present only in derived : {len(extra)}")
    print(f"  verdict mismatches      : {len(vdiff)}")
    print(f"  evidence mismatches     : {len(ediff)}")
    bad = missing + extra + vdiff + ediff
    for k in bad[:10]:
        print(f"     {k[0]} {k[1]}")
    if not sd:
        print("  *** the source set is EMPTY -- this check would pass on any derived file ***")
        return 2
    return 1 if bad else 0

if __name__ == '__main__':
    sys.exit(main())
