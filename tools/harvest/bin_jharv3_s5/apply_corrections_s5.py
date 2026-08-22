#!/usr/bin/env python3
"""Append this session's corrections to shard-C evidence. Append-only: no prior
evidence string is altered, and no verdict token is rewritten by this script --
it refuses if any correction would change a verdict."""
import sys, hashlib
TSV = "/home/reyerchu/_harv_priv/wt/tools/harvest/verdicts_shard_c.tsv"
TIP = "eb4d4f8bc9982354d580044b49044a9e73172461"
MAIN = "a4caccefeab577a5337f1854c9c857e4d7a2bd42"
STAMP = "2026-08-22T06:05Z (jharv3, fifth session)"

def pres(sha, anchor, extra=""):
    return (f"  ***PRESERVATION RESTORED {STAMP}, measured against origin at that moment: the "
        f"correction above states that this head is \"contained by NO live origin ref at all\" and that its "
        f"only copies are this directory and a local object store. That was true when it was written and it is "
        f"not true now. HEAD {sha[:12]} IS contained by the LIVE origin branch harvest/worktree-triage-jharvest, "
        f"tip {TIP[:9]} read with `git ls-remote --heads origin` and not from refs/remotes, with containment "
        f"verified by walking that tip (`merge-base --is-ancestor`), folded in at {anchor}. A recovery "
        f"instruction that resolves today: git fetch origin harvest/worktree-triage-jharvest && git checkout {sha}. "
        f"The verdict is unchanged; what changed is that it no longer depends on a local object store surviving.{extra}***")

def drift(old, new, tree, subject, where, contained_by_main):
    tail = (" The new head is itself contained by origin/main." if contained_by_main
            else f" The new head is contained by the live origin branch harvest/worktree-triage-jharvest (tip {TIP[:9]}).")
    return (f"  ***HEAD DRIFT RE-MEASURED {STAMP}, {where}: this directory's HEAD has MOVED since judging, "
        f"{old[:12]} -> {new[:12]} (\"{subject}\"), so the head this row cites is no longer the head on disk. "
        f"The verdict is re-derived AT THE NEW HEAD and LANDED still holds -- by content, not by ancestry: the new "
        f"head's entire snapshot is tree {tree}, which is one of the 2944 distinct tree hashes reachable from "
        f"origin/main {MAIN[:9]}, i.e. this exact byte-for-byte snapshot exists on main. The directory is clean at "
        f"the new head -- 0 tracked modifications and 0 untracked files under `git status --porcelain -uall` -- so "
        f"its whole content IS that snapshot and deleting it destroys nothing main lacks.{tail}***")

CORR = {
 "/home/reyerchu/_jcapture": drift("b3628c8da99b212aa5fe371396c5945de84588f6",
    "b6aaf660853105a793ee90fcf6fe39c07851ce1b", "f7da1cd5fbcc0d6a0e17ffd32096c1c01a8569a6",
    "RESULT.md: the requests section is the '## REQUESTS TO THE LANDER' heading the brief asks for",
    "measured on .108, the host that owns it", False),
 "/home/reyerchu/_jd3": drift("a00f53f2094812041c8aa6094f27058bc1b14ddd",
    "66e0806689ecebaca790e037418676fad45b9de6", "c51f225c440bc7b418516e1382537d340921fcee",
    "d3 parity(step 31): the manifest was short, not the declaration",
    "measured on .112 through the .102 hop, read-only, no fetch in that shared clone", True),
 "/home/reyerchu/_dens_priv/wt-jdrc1177": pres("6aa0d6abf1762c84710a5970d67fac623cbc82ad", "6feae9385"),
 "/home/reyerchu/_tim_priv/wt-jsetup-timing": pres("66085fbf5545eb6a7be48493556fb5b8cb1e5617", "6feae9385"),
 "/home/reyerchu/_agentjob_lgate/gate": pres("bd20fc88d40bab2628686b4d2f8d24d28e7be81b", "cc7bc9bba"),
 "/home/reyerchu/_v1126": pres("a7b1ed913e21485660bfa3d9d5ba69042dabaea4", "cc7bc9bba",
    extra=" This also lifts the exposure the 04:52Z correction recorded: the ABANDON no longer rests solely on "
          "its twin /home/reyerchu/_i_solo_1126 being kept -- the content it authorises deleting is on origin in "
          "its own right."),
}

lines = open(TSV, encoding="utf-8").read().split("\n")
before = hashlib.sha256(open(TSV,'rb').read()).hexdigest()
hit = {k: 0 for k in CORR}
out = []
for i, ln in enumerate(lines):
    if i == 0 or not ln.strip():
        out.append(ln); continue
    f = ln.split("\t")
    assert len(f) == 3, f"line {i+1} is not 3 columns"
    if f[0] in CORR:
        v_before = f[1]
        f[2] = f[2] + CORR[f[0]]
        assert f[1] == v_before, "a correction must not rewrite a verdict token"
        hit[f[0]] += 1
        ln = "\t".join(f)
    out.append(ln)
missing = [k for k, n in hit.items() if n != 1]
if missing:
    sys.exit("REFUSED: these paths did not match exactly one row: " + ", ".join(missing))
open(TSV, "w", encoding="utf-8").write("\n".join(out))
print(f"appended to {len(CORR)} rows; sha256 {before[:16]} -> "
      f"{hashlib.sha256(open(TSV,'rb').read()).hexdigest()[:16]}")
