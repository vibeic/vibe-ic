#!/usr/bin/env python3
"""Extract each row's anchored head — the whole point of putting it there — so drift is one pass.

Rows say either "[worktree HEAD when judged: <sha> ...]" or "[no worktree HEAD: ... pruned ...]".
The second kind has no head to drift; it is reported separately rather than silently skipped.
"""
import re, sys
pat = re.compile(r"worktree HEAD when judged: ([0-9a-f]{7,})")
n = pruned = 0
for path in sys.argv[1:]:
    for ln in open(path, encoding="utf-8", errors="replace").read().splitlines()[1:]:
        f = ln.split("\t")
        if len(f) < 3:
            continue
        m = pat.search(f[2])
        if m:
            print(f"{f[0]}\t{m.group(1)}\t{f[1]}")
            n += 1
        elif "no worktree HEAD" in f[2]:
            pruned += 1
assert n > 0, "extracted no anchors — the parser, not the data, is wrong"
print(f"#anchored={n} pruned_no_head={pruned}", file=sys.stderr)
