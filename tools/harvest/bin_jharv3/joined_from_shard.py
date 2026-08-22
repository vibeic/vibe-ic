#!/usr/bin/env python3
"""Make verdicts_joined.tsv actually DERIVED, for one shard at a time.

    usage: joined_from_shard.py --shard c [--dry-run]

WHY. `verdicts_joined.tsv` is what a downstream executor reads, and every file on
this branch calls it derived from the three per-shard deliverables. It is not. Its
shard-C rows were re-judged separately against main `a00f53f20`, which is stale, and
they disagree with `verdicts_shard_c.tsv` on six paths -- three of them in the
direction that deletes a directory the shard file says holds unlanded work:

    /home/reyerchu/_jd3                      shard RECOVER   joined LANDED
    /home/reyerchu/_a1456                    shard RECOVER   joined LANDED
    /home/reyerchu/AI_IC_design/wt_jwire2    shard RECOVER   joined LANDED

`joined_parity.py` has been red on exactly this since it was written, and a peer's
JOINED_DELETION_AUDIT.md re-measured all three independently and agreed the shard
file is right. Nobody had made the consumable agree, because hand-editing it would
not hold: it regenerates and the disagreement comes back silently.

So this does not edit rows. It DERIVES them: for every joined row belonging to the
named shard, the verdict and evidence are replaced by that shard's file, joined on
(host, path) -- never on path alone, because six paths on this fleet exist on more
than one host holding different work, and a path-only join silently picks one.

SCOPE, AND WHY IT IS ONE SHARD. Shards A and B are their agents' deliverables. This
takes the letter as an argument and touches nothing else, so shard C's rows can be
made honest tonight without overwriting a judgement that is not mine. Run it with
--shard a or --shard b when those owners are ready.

FAILING CLOSED. Any joined row of the named shard with no (host, path) match in the
roster, or no path in the verdicts file, is a loud exit naming it. A partial rewrite
that silently drops rows is worse than no rewrite.
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
HARV = os.path.abspath(os.path.join(HERE, ".."))


def read_tsv(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines:
        sys.exit(f"FAIL: {path} is empty")
    return lines[0].split("\t"), [l.split("\t") for l in lines[1:] if l]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", required=True, choices=list("abc"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    jpath = os.path.join(HARV, "verdicts_joined.tsv")
    jhdr, jrows = read_tsv(jpath)
    for c in ("host", "path", "verdict", "evidence", "shard"):
        if c not in jhdr:
            sys.exit(f"FAIL: verdicts_joined.tsv has no {c!r} column")
    H, P, V, E, S = (jhdr.index(c) for c in ("host", "path", "verdict", "evidence", "shard"))

    rhdr, rrows = read_tsv(os.path.join(HARV, f"_harv_shard_{a.shard}.tsv"))
    roster = {(r[rhdr.index("host")], r[rhdr.index("path")]) for r in rrows}

    vhdr, vrows = read_tsv(os.path.join(HARV, f"verdicts_shard_{a.shard}.tsv"))
    verdicts = {r[0]: (r[1], r[2]) for r in vrows if len(r) == 3}

    changed, same, missing = [], 0, []
    for r in jrows:
        if not r[S].startswith(a.shard):
            continue
        key = (r[H], r[P])
        if key not in roster:
            missing.append(f"joined row {key} is marked shard {r[S]} but is not in "
                           f"_harv_shard_{a.shard}.tsv")
            continue
        if r[P] not in verdicts:
            missing.append(f"joined row {key} has no row in verdicts_shard_{a.shard}.tsv")
            continue
        nv, ne = verdicts[r[P]]
        if (r[V], r[E]) == (nv, ne):
            same += 1
            continue
        changed.append((r[H], r[P], r[V], nv))
        r[V], r[E] = nv, ne

    if missing:
        for m in missing:
            print(m)
        sys.exit(f"\nFAIL: {len(missing)} row(s) could not be derived. Refusing to write a "
                 f"partial rewrite -- a silently dropped row is how the executor loses one.")

    print(f"shard {a.shard}: {same} row(s) already agreed, {len(changed)} rewritten")
    for h, p, old, new in changed:
        flag = "  <-- WAS DELETION-BOUND" if old in ("LANDED", "ABANDON") and new == "RECOVER" else ""
        print(f"  .{h} {p}: {old} -> {new}{flag}" if old != new else f"  .{h} {p}: evidence only")
    if a.dry_run:
        print("\n--dry-run: nothing written")
        return 0
    with open(jpath, "w", encoding="utf-8") as fh:
        fh.write("\t".join(jhdr) + "\n")
        for r in jrows:
            fh.write("\t".join(r) + "\n")
    print(f"\nwrote {jpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
