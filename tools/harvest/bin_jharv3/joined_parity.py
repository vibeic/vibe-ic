#!/usr/bin/env python3
"""A shard's verdict and the joined view's verdict for the same path must agree.

    usage: joined_parity.py [--joined FILE] [--shard-dir DIR]
    env:   VIBEIC_REPO, VIBEIC_REF   as in contract_check.py

WHY. verdicts_joined.tsv is what a downstream executor actually reads, and it is
DERIVED from the per-shard files. jharv2 found 1083 decided rows that never reach
it at all. This is the other half: rows that DO reach it carrying a DIFFERENT
verdict from the shard file they came from.

Six shard-C rows disagree with the joined view right now, and three disagree in
the direction that gets a directory deleted -- the shard file says RECOVER and
the joined view says LANDED:

    /home/reyerchu/_jd3            292 lines at its head vs 218 on current main
    /home/reyerchu/_a1456          one tracked uncommitted edit, on no ref at all
    /home/reyerchu/AI_IC_design/wt_jwire2   named file differs; 20+ commits since

All three were re-measured against current origin/main before this was written.
The shard file is right and the consumable is wrong.

Editing the joined file would not hold -- it regenerates, and the disagreement
would come back silently with nothing to say it had ever been noticed. A gate
holds. This one is red until the two agree.

TWO KINDS OF DISAGREEMENT, AND THIS GATE CANNOT TELL THEM APART.
  (1) The consumable is STALE -- regenerated from an older snapshot. The three
      rows above are this, and so is /home/reyerchu/_jintent/wt in shard B (head
      c5c2e228244, 6 of 6 owned files differing from current main, measured by
      jharv2 on .114 and confirmed here from the commit rather than taken on
      report). Four confirmed deletion-bound errors in the consumable.
  (2) The HOST MOVED between the two measurements. /home/reyerchu/_jcpath2/wt_new
      has gone ABANDON -> RECOVER -> ABANDON across three measurements because
      it and its sibling genuinely diverged and re-converged; both now sit at
      c0ecd5f1310, tree 5bf932a9082, both clean. BOTH files were correct when
      written and neither needs fixing.
So this reports the disagreement and its DIRECTION and stops there. Deciding
which kind it is means going back to the host -- which is why every shard-C row
carries the head it was judged at and says "re-measure before acting". A row that
flaps across regenerations is evidence about the DIRECTORY, not about the file.

PROVING A GATE. This script refuses if either input yields zero rows, because
"found nothing" and "parsed nothing" print the same thing -- which is the whole
lesson of tonight. It was proved in both directions before being shipped: red on
the real files with a count measured independently, green on a joined file
patched to agree, red again when the patch is removed.
"""
import os
import subprocess
import sys

DEFAULT_REF = "origin/harvest/worktree-triage-jharvest"
JOINED = "tools/harvest/verdicts_joined.tsv"
# in the joined schema: host, path, verdict, evidence, shard
J_PATH, J_VERDICT = 1, 2
# a shard file's verdict is deletion-bound if acting on it removes a directory
DELETION_BOUND = {"LANDED", "ABANDON"}


def die(msg):
    sys.exit(f"joined_parity: {msg}")


def find_repo():
    if os.environ.get("VIBEIC_REPO"):
        return os.environ["VIBEIC_REPO"]
    here = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.run(["git", "-C", here, "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    if p.returncode == 0 and p.stdout.strip():
        return p.stdout.strip()
    die(f"cannot locate the vibe-ic clone from {here}; set VIBEIC_REPO")


REPO = find_repo()
REF = os.environ.get("VIBEIC_REF", DEFAULT_REF)


def git(*a, check=True):
    p = subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True)
    if check and p.returncode != 0:
        die(f"git {' '.join(a)} failed: {p.stderr.strip()}")
    return p.stdout


def read(rel, override=None):
    if override:
        try:
            return open(override, encoding="utf-8").read()
        except OSError as e:
            die(f"cannot read {override}: {e}")
    return git("show", f"{REF}:{rel}", check=False)


def main():
    argv = sys.argv[1:]
    joined_override = shard_dir = None
    while argv:
        a = argv.pop(0)
        if a == "--joined":
            joined_override = argv.pop(0)
        elif a == "--shard-dir":
            shard_dir = argv.pop(0)
        else:
            die(f"unknown argument {a!r}")

    if REF.startswith("origin/"):
        git("fetch", "-q", "origin", REF[len("origin/"):], check=False)

    jbody = read(JOINED, joined_override)
    jmap = {}
    for ln in jbody.split("\n")[1:]:
        f = ln.split("\t")
        if len(f) > J_VERDICT and f[J_PATH].startswith("/"):
            jmap[f[J_PATH]] = f[J_VERDICT]
    if not jmap:
        die(f"parsed 0 paths from the joined view -- refusing to report parity "
            f"about a file I could not read")
    print(f"joined view: {len(jmap)} paths")

    total_rows = disagree = absent = dangerous = 0
    for shard in ("a", "b", "c"):
        rel = f"tools/harvest/verdicts_shard_{shard}.tsv"
        override = os.path.join(shard_dir, f"verdicts_shard_{shard}.tsv") if shard_dir else None
        if override and not os.path.exists(override):
            override = None
        body = read(rel, override)
        rows = [l for l in body.split("\n")[1:] if l.strip()]
        if not rows:
            die(f"parsed 0 rows from {rel} -- refusing to report parity about it")
        total_rows += len(rows)
        d = a_ = 0
        for ln in rows:
            f = ln.split("\t")
            if len(f) < 2:
                continue
            path, verdict = f[0], f[1]
            if path not in jmap:
                a_ += 1
                continue
            if jmap[path] != verdict:
                d += 1
                danger = verdict not in DELETION_BOUND and jmap[path] in DELETION_BOUND
                if danger:
                    dangerous += 1
                print(f"DISAGREE shard {shard}: {path}  shard says {verdict}, "
                      f"joined says {jmap[path]}"
                      f"{'   <-- DELETION-BOUND IN THE JOINED VIEW ONLY' if danger else ''}")
        disagree += d
        absent += a_
        print(f"  shard {shard}: {len(rows)} rows, {d} disagree, {a_} absent from joined")

    print(f"\ntotal {total_rows} shard rows: {disagree} disagree, {absent} absent")
    if dangerous:
        print(f"{dangerous} of the disagreements are the direction that deletes a "
              f"directory: the shard file says keep and the consumable says drop.")
    if disagree:
        print("\nFAIL: the consumable contradicts the deliverable it is derived from.")
        return 1
    print("\nOK: no shard row disagrees with the joined view")
    return 0


if __name__ == "__main__":
    sys.exit(main())
