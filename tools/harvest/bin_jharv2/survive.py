#!/usr/bin/env python3
"""Survivability, resolved against ORIGIN from one machine, in jharv3's three-way vocabulary.

Two corrections are baked in and both were found the hard way:

1. `KEEP/DROP` does not answer the executor's question. Removing a worktree directory does not
   remove its commits -- unless nothing else points at them.
2. Measuring that ON a host reads that HOST'S view of origin, not origin. A clone that never
   fetched a branch calls its commit local-only when origin has held it all along; 161 rows
   here would have carried that false warning. The split is therefore resolved once, on a clone
   holding all 627 origin refs, from heads collected host-side.
"""
import os

_MAP = {}
_p = "/home/reyerchu/_shb/survivability_norm.tsv"
if os.path.exists(_p):
    for _l in open(_p, encoding="utf-8", errors="replace").read().splitlines():
        f = _l.split("\t")
        if len(f) >= 4:
            _MAP[(f[1], f[0])] = (f[2], f[3])

def survivability(host, wt):
    hit = _MAP.get((host, wt))
    if not hit:
        return ""
    kind, ref = hit
    if kind == "ON_REMOTE":
        return (" [ON_REMOTE — safe to delete: its head is on origin (%s), so the commit survives "
                "the directory, the clone and the machine]" % ref)
    if kind == "ON_LOCAL_REF_ONLY":
        return (" [ON_LOCAL_REF_ONLY — its head is on a local branch but on NO remote, so it "
                "survives only as long as THIS CLONE does, and whole clones have been deleted "
                "during this triage. Push it before removing anything.]")
    if kind == "UNREFERENCED":
        return (" [UNREFERENCED — **DELETING THIS DIRECTORY DESTROYS THE COMMIT**: its head is on "
                "no ref at all, so the worktree's own HEAD is the only pointer to it.]")
    if kind == "COMMIT_ABSENT":
        return (" [survivability UNDETERMINED: this checkout has no resolvable HEAD, so there is "
                "no commit to preserve or lose — the files on disk are all there is.]")
    return ""
