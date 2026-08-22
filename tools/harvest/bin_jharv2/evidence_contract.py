#!/usr/bin/env python3
"""THE MACHINE I NEVER WROTE.

jharv3: "I wrote it for a human reader and shipped it as machine-checkable evidence without ever
writing the machine." That was my sentence about my own grammar, and it is the sharper version of
"found nothing and parsed nothing print the same thing" — checkable-by-a-stranger was satisfied
for a human and ASSUMED for a machine, and the assumption went untested because nobody wrote the
consumer.

So: parse my grammar, and re-resolve every claim against CURRENT origin/main.

  sha256(<path>) = <64hex> here, <64hex> on main
  sha256(<path>) = <64hex> here, (origin/main has no file at this path) on main

Reports coverage as a number. A row it cannot parse is reported as DID NOT CHECK, never as
passing — jharv3's shape, because a checker that silently skips what it does not understand
reports a smaller, cleaner, wrong total.
"""
import re, subprocess, sys, hashlib, os

R = os.environ.get("VIBEIC_REPO", "/home/reyerchu/vibe-ic")
# My own generator emits TWO phrasings for "main does not have this path", and the first version
# of this checker knew one of them -- so 78 well-formed rows were reported DID_NOT_CHECK. An
# auditor out of date with its subject, on a grammar I wrote myself.
ABSENT = r"\(origin/main has no file at this path\)|\(no such path on origin/main\)"
PAT = re.compile(r"sha256\(([^)]+)\)\s*=\s*([0-9a-f]{64})\s+here,\s*(" + ABSENT + r"|[0-9a-f]{64})\s+on main")

def main_sha(path):
    r = subprocess.run(["git", "-C", R, "show", f"origin/main:{path}"], capture_output=True)
    if r.returncode != 0:
        return None
    return hashlib.sha256(r.stdout).hexdigest()

tot = parsed = agree = disagree = nc = 0
for f in sys.argv[1:]:
    n = p = a = d = noclaim = 0
    for ln in open(f, encoding="utf-8", errors="replace").read().splitlines()[1:]:
        c = ln.split("\t")
        if len(c) < 3 or c[1] != "RECOVER":
            continue
        n += 1
        # A row that says UNDETERMINED makes NO evidence claim by design -- it names the missing
        # input instead. Counting those as DID_NOT_CHECK conflates "no claim to check" with
        # "claim I could not read", and only the second is a defect.
        if "UNDETERMINED (" in c[2]:
            noclaim += 1
            continue
        m = PAT.search(c[2])
        if not m:
            continue
        p += 1
        path, claimed_main = m.group(1), m.group(3)
        actual = main_sha(path)
        if claimed_main.startswith("("):   # either absent-phrasing
            ok = actual is None
        else:
            ok = (actual == claimed_main)
        if ok:
            a += 1
        else:
            d += 1
            if d <= 3:
                print(f"  DISAGREES {os.path.basename(f)} {c[0]}")
                print(f"    {path}\n    row says main={claimed_main[:16]}  actual={(actual or 'absent')[:16]}")
    print(f"{os.path.basename(f):<38} RECOVER={n:<4} parsed={p:<4} agree={a:<4} disagree={d:<3} "
          f"no_claim_by_design={noclaim} DID_NOT_CHECK={n-p-noclaim}")
    tot += n; parsed += p; agree += a; disagree += d; nc += noclaim
assert tot > 0, "no RECOVER rows found at all — the parser, not the data, is wrong"
print(f"TOTAL RECOVER={tot} parsed={parsed} agree={agree} disagree={disagree} "
      f"no_claim_by_design={nc} DID_NOT_CHECK={tot-parsed-nc}")
sys.exit(1 if disagree else 0)
