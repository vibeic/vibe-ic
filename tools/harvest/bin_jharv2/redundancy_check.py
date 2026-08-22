#!/usr/bin/env python3
"""How many INDEPENDENT refs on origin still carry the rescued set?

Folding 14 rescue anchors into this branch was a real improvement -- 14 separately-deletable refs
became 1 that also carries the verdicts. But it also concentrated the risk: one `git push --delete`
on this branch would take the deliverable, 2950 rescued commits and 4929 preserved files together.
Trading fourteen fragile refs for one is only better if the one is more durable, and it is not; it
is the same kind of ref.

So the property to hold is REDUNDANCY, and this measures it. Requires at least MIN_REFS distinct
origin refs to carry the set, and prints them, so a drop from three to one is visible before it
becomes a drop to zero.

A tag counts separately from a branch on purpose: they are removed by different commands, and the
failure this guards against is a sweep that deletes branches matching a pattern.

Authority is `git ls-remote` for existence, then per-ref containment locally. Refuses if origin
cannot be reached -- checking redundancy against a cache is how the original loss stayed invisible.
"""
import os, subprocess, sys

MIN_REFS = 2

def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'tools/harvest'
    repo = sys.argv[2] if len(sys.argv) > 2 else '/home/reyerchu/vibe-ic'
    man = os.path.join(base, 'rescued_commits.txt')
    want = [l.strip() for l in open(man) if l.strip()]
    if not want:
        print("  *** manifest empty -- nothing to check ***"); return 2
    # a fixed, spread sample: full containment per ref is a full object walk per ref
    sample = [want[0], want[len(want)//4], want[len(want)//2], want[3*len(want)//4], want[-1]]
    ls = subprocess.run(['git', '-C', repo, 'ls-remote', 'origin'], capture_output=True, text=True)
    if ls.returncode != 0:
        print("  cannot reach origin -- refusing to measure redundancy against a cache"); return 2
    refs = []
    for line in ls.stdout.splitlines():
        p = line.split('\t')
        if len(p) == 2 and not p[1].endswith('^{}'):
            refs.append((p[1], p[0]))
    if not refs:
        print("  origin advertised nothing -- refusing"); return 2
    subprocess.run(['git', '-C', repo, 'fetch', '-q', 'origin',
                    '+refs/heads/*:refs/remotes/origin-live/*',
                    '+refs/tags/*:refs/remotes/origin-tags/*'], capture_output=True)
    carriers = []
    for name, sha in refs:
        ok = True
        for c in sample:
            r = subprocess.run(['git', '-C', repo, 'merge-base', '--is-ancestor', c, sha],
                               capture_output=True)
            if r.returncode != 0:
                ok = False; break
        if ok:
            carriers.append(name)
    print(f"  manifest {len(want)} commits, sampled {len(sample)}")
    print(f"  origin refs carrying the whole sample: {len(carriers)} (need >= {MIN_REFS})")
    for c in carriers:
        print(f"      {c}")
    if len(carriers) < MIN_REFS:
        print(f"  *** redundancy has fallen to {len(carriers)} -- one deletion from total loss ***")
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
