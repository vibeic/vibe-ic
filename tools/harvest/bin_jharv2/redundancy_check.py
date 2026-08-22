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
    # The sample is a PRE-FILTER only. It used to be the whole test, and that is the same narrowness
    # that let a live-but-moved ref pass the citation gate: a ref holding these 5 and missing the
    # other 2958 would have been counted a full carrier. Candidates that pass the sample are then
    # verified by FULL containment -- one object walk each, affordable because there are a handful.
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
            carriers.append((name, sha))
    print(f"  manifest {len(want)} commits; {len(carriers)} ref(s) passed the {len(sample)}-commit pre-filter")
    full = []
    for name, sha in carriers:
        # walk the SHA, not the origin ref NAME. An origin ref name need not resolve locally --
        # measured: the mirror branch reported "cannot walk" and was silently dropped from the
        # carrier count, understating redundancy 3 -> 2. A gate that quietly loses a carrier is the
        # same defect as one that quietly counts a partial one.
        walk = subprocess.run(['git', '-C', repo, 'rev-list', '--objects', '--no-object-names', sha],
                              capture_output=True, text=True)
        if walk.returncode != 0:
            print(f"      {name}: object {sha[:11]} not present locally -- fetch it before judging"); continue
        reach = set(walk.stdout.split())
        missing = sum(1 for c in want if c not in reach)
        if missing == 0:
            print(f"      {name}  carries all {len(want)}")
            full.append(name)
        else:
            print(f"      {name}  PARTIAL -- missing {missing} of {len(want)}; not counted")
    carriers = full
    print(f"  refs carrying the WHOLE manifest: {len(carriers)} (need >= {MIN_REFS})")
    if len(carriers) < MIN_REFS:
        print(f"  *** redundancy has fallen to {len(carriers)} -- one deletion from total loss ***")
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
