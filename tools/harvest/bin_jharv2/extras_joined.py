#!/usr/bin/env python3
"""Emit my four files' rows in verdicts_joined.tsv's schema.

jharv3's delivery point: verdicts_joined.tsv is what a downstream executor reads, and it is
DERIVED. Prose in RESCUE.md cannot reach that consumer, and neither can a TSV the generator does
not read. 1084 of my rows -- every row of the two extras files -- are absent from it, including
877 RECOVERs holding content that is not on main. This puts them in the consumer's schema so
joining them is a one-line change for whoever owns the generator, instead of a rewrite.
"""
import os

OUT = "/home/reyerchu/_harvb/verdicts_extras_joined.tsv"
SRC = [("105", "/home/reyerchu/_harvb/verdicts_extra_8hd9.tsv",        "extra-8hd9"),
       ("102", "/home/reyerchu/_harvd_local/verdicts_extra_8hd7.tsv",  "extra-8hd7")]

rows = []
for host, path, shard in SRC:
    if not os.path.exists(path):
        continue
    for ln in open(path, encoding="utf-8", errors="replace").read().splitlines()[1:]:
        f = ln.split("\t")
        if len(f) < 3:
            continue
        rows.append((host, f[0], f[1], f[2], shard))

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("host\tpath\tverdict\tevidence\tshard\n")
    for r in rows:
        fh.write("\t".join(r) + "\n")
print(OUT, len(rows), "rows")
