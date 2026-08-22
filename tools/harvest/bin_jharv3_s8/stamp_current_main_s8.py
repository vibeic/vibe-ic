#!/usr/bin/env python3
"""Stamp every shard-C row with what it measures against CURRENT origin/main.

WHY. contract_check.py reports, correctly, that N rows "do not cite current main
ae78abb28 -- a provenance gap". Every row in the file was re-judged this session
against ae78abb285 and only two moved, but a reader of ONE row cannot see that:
the row still cites a4caccefe and nothing in it says whether that is stale. The
gap is closed by writing the per-row measurement INTO the row, with its own
numbers, not by a blanket sentence -- a stamp that says the same thing on every
row proves nothing about any of them.

The row whose value is an untracked file has no tree to re-judge, and says so.

Refuses rather than half-writing: shape, row count and per-path uniqueness are
checked first, and a note containing a tab or newline is refused because it would
silently reshape the TSV.
"""
import sys
from collections import Counter

SRC = "verdicts_shard_c.tsv"
RAW = "raw_rejudge_current_main_s8_jharv3.tsv"
NEW_MAIN = "ae78abb285630636b2f305f2ed4aef13f92201ed"
OLD_MAIN = "a4caccefeab577a5337f1854c9c857e4d7a2bd42"
ALREADY = {"/home/reyerchu/AI_IC_design/wt_jwire2", "/home/reyerchu/_ld/wt"}

meas = {}
with open(RAW, encoding="utf-8") as f:
    f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        meas[p[0]] = {"head": p[2], "n": p[3], "old": p[4], "new": p[5], "st": p[6]}
if len(meas) != 110:
    sys.exit(f"REFUSING: raw sweep has {len(meas)} rows, not 110")

COMMON = (
    "Re-swept with bin_jharv3_s8/rejudge_vs_current_main.sh, judged by CONTENT against main's "
    "HISTORY -- every (path,blob) pair in the tree must be a pair main has held AT THAT PATH -- "
    "never against main's tip, which cannot separate landed work from unlanded work in a repo "
    "that squash-lands. Report: REJUDGE_shard_c_s8_current_main_jharv3.md."
)

def note(path, verdict, m):
    if m["st"] == "NO_HEAD":
        return (
            f"  ***NOT RE-JUDGED BY CONTENT THIS SESSION, AND THAT IS THE HONEST STATE 2026-08-22T19:1xZ "
            f"(jharv3, eighth session). Shard C's other 109 rows were re-swept against current "
            f"origin/main {NEW_MAIN} (v1.11.70), 673 commits past the {OLD_MAIN[:9]} this file was written "
            f"against. This row could not be: its value is an untracked file, so it has no judged HEAD and "
            f"no tree to compare. Nothing about it is claimed to be fresh. The missing input is a re-read of "
            f"the file on its host.***"
        )
    if verdict == "LANDED":
        return (
            f"  ***RE-JUDGED AGAINST CURRENT MAIN, VERDICT UNCHANGED 2026-08-22T19:1xZ (jharv3, eighth "
            f"session). Main moved {OLD_MAIN[:9]} -> {NEW_MAIN} (v1.11.70), 673 commits, so this row's "
            f"citation of {OLD_MAIN[:9]} is no longer current. Re-measured: this head's tree holds "
            f"{m['n']} files and EVERY one of their (path,blob) pairs is a pair origin/main's HISTORY has "
            f"held at that path -- {m['new']} that main never held, against current main. A LANDED cannot "
            f"regress here and that is measured, not assumed: every one of the 38994 (path,blob) pairs main's "
            f"history held at {OLD_MAIN[:9]} is still among the 40565 it holds at {NEW_MAIN[:9]} -- 0 lost, "
            f"1571 gained. {COMMON}***"
        )
    if m["new"] == "0":
        return (
            f"  ***RE-JUDGED AGAINST CURRENT MAIN, VERDICT UNCHANGED 2026-08-22T19:1xZ (jharv3, eighth "
            f"session). Main moved {OLD_MAIN[:9]} -> {NEW_MAIN} (v1.11.70), 673 commits. This head's "
            f"{m['n']}-file tree holds 0 pairs main's history never held -- under the OLD main too, so main's "
            f"advance changed nothing here. The COMMITTED side of this row was already landed and the row "
            f"never rested on it: its value is the working tree, as the notes above set out. {COMMON}***"
        )
    return (
        f"  ***RE-JUDGED AGAINST CURRENT MAIN, VERDICT UNCHANGED 2026-08-22T19:1xZ (jharv3, eighth "
        f"session). Main moved {OLD_MAIN[:9]} -> {NEW_MAIN} (v1.11.70), 673 commits, so this row's citation "
        f"of {OLD_MAIN[:9]} is no longer current and the question is whether its work landed in that window. "
        f"It did not: this head's tree holds {m['n']} files, of which {m['new']} (path,blob) pairs are content "
        f"origin/main's HISTORY has NEVER held at that path -- {m['old']} against the old main, so main's "
        f"advance took none of it. {COMMON}***"
    )

rows = []
with open(SRC, encoding="utf-8") as f:
    header = f.readline()
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) != 3:
            sys.exit(f"REFUSING: row has {len(p)} fields, not 3")
        rows.append(p)
if len(rows) != 110:
    sys.exit(f"REFUSING: expected 110 rows, found {len(rows)}")
c = Counter(r[0] for r in rows)
dupes = [k for k, v in c.items() if v != 1]
if dupes:
    sys.exit(f"REFUSING: duplicate paths {dupes}")

stamped = 0
for r in rows:
    if r[0] in ALREADY:
        continue
    m = meas.get(r[0])
    if m is None:
        sys.exit(f"REFUSING: no measurement for {r[0]}")
    if m["st"] != "NO_HEAD" and m["head"] not in r[2]:
        sys.exit(f"REFUSING: {r[0]} evidence does not name the head {m['head']} the sweep judged")
    n = note(r[0], r[1], m)
    if "\t" in n or "\n" in n:
        sys.exit("REFUSING: note contains a tab or newline")
    if "eighth session" in r[2]:
        sys.exit(f"REFUSING: {r[0]} already carries an eighth-session note")
    r[2] += n
    stamped += 1

if stamped != 108:
    sys.exit(f"REFUSING: stamped {stamped}, expected 108")

with open(SRC, "w", encoding="utf-8") as f:
    f.write(header)
    for r in rows:
        f.write("\t".join(r) + "\n")
print(f"rows={len(rows)} stamped={stamped} skipped_already_flipped={len(ALREADY)} "
      f"verdicts={dict(Counter(r[1] for r in rows))}")
