#!/usr/bin/env python3
"""Every ref a row NAMES must be live on origin per ls-remote — checked with a real parser.

The first version of this check was one line of awk using `match(s, re, arr)`, which is a GNU
extension: under mawk it silently matched nothing and reported "0 refs named, 0 dead" for files
that named 236 bad refs. An auditor that finds nothing and an auditor that runs on nothing look
identical from the outside, so this one asserts it actually extracted something.
"""
import re, subprocess, sys

live = set()
for ln in subprocess.run(["git", "-C", "/home/reyerchu/vibe-ic", "ls-remote", "--heads", "origin"],
                         capture_output=True, text=True).stdout.splitlines():
    p = ln.split()
    if len(p) == 2:
        live.add(p[1].replace("refs/heads/", ""))
assert live, "ls-remote returned nothing — refusing to audit against an empty authority"

pat = re.compile(r"reachable from `([^`]+)`")
bad = tot = 0
for path in sys.argv[1:]:
    named = 0
    dead = []
    for ln in open(path, encoding="utf-8", errors="replace").read().splitlines()[1:]:
        f = ln.split("\t")
        if len(f) < 3:
            continue
        for m in pat.finditer(f[2]):
            r = m.group(1)
            named += 1
            short = r[len("origin/"):] if r.startswith("origin/") else r
            if r in ("origin/HEAD", "HEAD") or short not in live:
                dead.append((f[0], r))
    tot += named
    bad += len(dead)
    print(f"{path.split('/')[-1]:<38} refs named={named:<5} not live on origin={len(dead)}")
    for p_, r in dead[:5]:
        print(f"     DEAD {r}  {p_}")
assert tot > 0, "extracted zero refs from every file — the parser, not the data, is wrong"
print(f"TOTAL refs named={tot} dead={bad}")
