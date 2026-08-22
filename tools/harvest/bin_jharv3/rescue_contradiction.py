#!/usr/bin/env python3
"""A verdict that contradicts a rescue ref is a hard error, in ANY shard file.

Why this exists. Four rows in verdicts_shard_a.tsv say LANDED -- the verdict that
means "already on main, safe to delete" -- over working trees that hold bytes
main does not have. They were measured on .120 and the content is preserved on
`harvest/rescue-120-falselanded-*`. But the correction cannot be delivered: the
shard's owner is unreachable from here and from jharv2, and verdicts_joined.tsv,
which is what a downstream executor actually reads, is DERIVED from the per-shard
files -- so every regeneration re-propagates the wrong verdict, and a paragraph
in a markdown file propagates nowhere.

Prose does not survive regeneration. A check does. Rather than edit another
agent's deliverable -- which would silently diverge from whatever its owner
regenerates -- this turns the finding into a gate: if origin holds a rescue ref
saying a path's working tree was NOT landed, then no shard file may call that
path LANDED or ABANDON.

The refs are the authority, not this script's opinion: each names its worktree in
its own commit message, and the ref only exists because the content was measured
and pushed.
"""
import re, subprocess, sys

R = "/home/reyerchu/vibe-ic"
DELETION_BOUND = {"LANDED", "ABANDON"}


def git(*a, check=True):
    p = subprocess.run(["git", "-C", R, *a], capture_output=True, text=True)
    if check and p.returncode != 0:
        sys.exit(f"git {' '.join(a)} failed: {p.stderr.strip()}")
    return p.stdout


def rescue_paths():
    """{worktree path -> ref} for every falselanded rescue ref ON ORIGIN.

    ls-remote, not refs/remotes: the tracking cache outlives branches origin has
    deleted, and a stale cache would let this gate pass on a ref that is gone.
    """
    out, found = git("ls-remote", "--heads", "origin", "harvest/rescue-*falselanded*"), {}
    for line in out.strip().split("\n"):
        if not line.strip():
            continue
        sha, ref = line.split("\t")
        short = ref.replace("refs/heads/", "")
        git("fetch", "-q", "origin", short)
        msg = git("log", "-1", "--format=%B", "FETCH_HEAD")
        # (\S+) swallows the sentence punctuation. The first version of this
        # gate captured "/home/reyerchu/_wt_1486," WITH THE COMMA, matched no
        # row, and reported 0 contradictions -- a PASS produced by a parser
        # defect, over four rows that really are wrong. A false green is worse
        # than the four false reds this night has already produced: a red gets
        # investigated, a green gets believed.
        m = re.search(r"uncommitted work in (\S+?)[,.;:]?(?:\s|$)", msg)
        if m:
            found[m.group(1)] = short
        else:
            print(f"  note: {short} names no worktree in its message; not gating on it")
    return found


def main():
    guarded = rescue_paths()
    if not guarded:
        print("no falselanded rescue refs on origin — nothing to gate")
        return 0
    print(f"rescue refs on origin naming a worktree: {len(guarded)}")

    problems = 0
    for shard in ("a", "b", "c"):
        f = f"tools/harvest/verdicts_shard_{shard}.tsv"
        try:
            body = git("show", f"FETCH_HEAD_BRANCH:{f}", check=False)
        except SystemExit:
            body = ""
        if not body:
            body = git("show", f"origin/harvest/worktree-triage-jharvest:{f}", check=False)
        if not body:
            print(f"  {f}: not present, skipped")
            continue
        hits = 0
        for ln in body.split("\n"):
            parts = ln.split("\t")
            if len(parts) < 2:
                continue
            path, verdict = parts[0], parts[1]
            if path in guarded and verdict in DELETION_BOUND:
                print(f"CONTRADICTION {f}: {path} says {verdict}, but {guarded[path]} "
                      f"preserves uncommitted content that is not on main")
                hits += 1
        problems += hits
        print(f"  shard {shard}: {hits} contradiction(s)")

    if problems:
        print(f"\nFAIL: {problems} row(s) call a path deletion-safe that a rescue ref contradicts.")
        print("Fix the verdict, or delete the rescue ref if it was made in error — not both silently.")
        return 1
    print("\nOK: no shard file contradicts a rescue ref")
    return 0


if __name__ == "__main__":
    sys.exit(main())
