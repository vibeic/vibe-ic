#!/usr/bin/env python3
"""Second append of this session: the two RECOVER rows whose HEAD had drifted.
Append-only; refuses if a verdict token would change or a path matches != 1 row."""
import sys, hashlib
TSV = "/home/reyerchu/_harv_priv/wt/tools/harvest/verdicts_shard_c.tsv"
MAIN = "a4caccefeab577a5337f1854c9c857e4d7a2bd42"
STAMP = "2026-08-22T06:20Z (jharv3, fifth session)"

def drift_recover(old, new, tree, subject, where, anchor, anchor_note):
    return (f"  ***HEAD DRIFT RE-MEASURED {STAMP}, {where}: this directory's HEAD has MOVED since "
        f"judging, {old[:12]} -> {new[:12]} (\"{subject}\"), so the head this row cites is not the head "
        f"on disk. RECOVER still holds, re-derived AT THE NEW HEAD by content: the new head's whole "
        f"snapshot is tree {tree[:12]}, which is NOT one of the 2944 distinct tree hashes reachable from "
        f"origin/main {MAIN[:9]} -- this directory holds a snapshot main does not have. It is clean on "
        f"disk (0 tracked modifications, 0 untracked files, `git status --porcelain -uall`), so its whole "
        f"content is that snapshot. PRESERVATION AT THE NEW HEAD, checked against origin now: {new[:12]} "
        f"is contained by the live origin branch {anchor} ({anchor_note}), read with `git ls-remote` and "
        f"verified by walking that ref, not from refs/remotes. Recover with: git fetch origin {anchor} && "
        f"git checkout {new}.***")

CORR = {
 "/home/reyerchu/AI_IC_design/wt_jwire2": drift_recover(
    "a00f53f2094812041c8aa6094f27058bc1b14ddd", "4b1285a1865e644aa475d49f5787d20a6aa7bda4",
    "f8b97313740e04d9adac9776194cd5f3cd609cc5",
    "hygiene(#1347,#731,#712): wire two orphan checkers where their verdict can refuse",
    "measured on .121 through the .102 hop, read-only, no fetch in that shared clone",
    "fix/jwire2-hygiene-wiring",
    "that branch's current tip IS this head; the branch was force-pushed earlier today, which is why "
    "its existence was not taken for containment"),
 "/home/reyerchu/_gf180_priv/wt": drift_recover(
    "d830ba32dcbaa4c4c1bda37e5991f6e455056f36", "5240ead2c7ee91bdafedf86c8fb634f169461a64",
    "08a4b5ad41ff961874faaa93fe5f1ef6f86db670",
    "report audit: a Magic transcript puts its verdict at the end, and we read the front",
    "measured on .112 through the .102 hop, read-only, no fetch in that shared clone",
    "harvest/worktree-triage-jharvest",
    "also contained by harvest/rescue-reanchor-heads"),
}
lines = open(TSV, encoding="utf-8").read().split("\n")
hit = {k: 0 for k in CORR}; out = []
for i, ln in enumerate(lines):
    if i == 0 or not ln.strip():
        out.append(ln); continue
    f = ln.split("\t"); assert len(f) == 3, f"line {i+1} is not 3 columns"
    if f[0] in CORR:
        v = f[1]; f[2] += CORR[f[0]]; assert f[1] == v; hit[f[0]] += 1; ln = "\t".join(f)
    out.append(ln)
missing = [k for k, n in hit.items() if n != 1]
if missing: sys.exit("REFUSED: not exactly one row for: " + ", ".join(missing))
open(TSV, "w", encoding="utf-8").write("\n".join(out))
print("appended to", len(CORR), "rows; sha256 now",
      hashlib.sha256(open(TSV,'rb').read()).hexdigest()[:16])
