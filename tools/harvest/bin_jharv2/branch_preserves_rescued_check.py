#!/usr/bin/env python3
"""Every commit in rescued_commits.txt must be reachable from THIS branch.

On 2026-08-22 all 14 harvest/rescue-* refs were deleted from origin, and 2945 commits -- including
nine whose worktrees had also been deleted -- were left reachable from nothing origin advertised.
They were re-anchored, and then folded into this branch as extra parents, so the one ref nobody
deletes without deleting the verdicts is also the ref that preserves the content those verdicts
describe.

This asserts that property still holds. A rebase, a squash, or an amend that drops the extra parents
would silently un-preserve all of them while every file in the tree stayed identical -- the fold
commit carries the branch's own tree, so nothing in a diff would show it.

Fails if the manifest is empty: a check with nothing to check passes trivially.
"""
import os, subprocess, sys

def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'tools/harvest'
    repo = sys.argv[2] if len(sys.argv) > 2 else '.'
    rev  = sys.argv[3] if len(sys.argv) > 3 else 'HEAD'
    man = os.path.join(base, 'rescued_commits.txt')
    want = [l.strip() for l in open(man) if l.strip()]
    if not want:
        print("  *** manifest is empty -- nothing to check, so this would pass on anything ***")
        return 2
    have = subprocess.run(['git', '-C', repo, 'rev-list', '--no-object-names', '--objects', rev],
                          capture_output=True, text=True)
    if have.returncode != 0:
        print(f"  cannot walk {rev}"); return 2
    reach = set(have.stdout.split())
    # The PRESERVE tips are a second, separate category: whole trees of content that is on no
    # commit anywhere else (pruned checkouts, stashes). They were left out of the first fold and
    # were unreachable from this branch until 2026-08-22 -- the same one-deletion-from-gone shape
    # as the rescue anchors, and the more fragile of the two, because pruned-checkout content is
    # on no commit BY DEFINITION.
    tips_path = os.path.join(base, 'preserved_tips.tsv')
    tips = []
    if os.path.exists(tips_path):
        with open(tips_path) as f:
            for i, line in enumerate(f):
                if i == 0 or not line.strip():
                    continue
                parts = line.rstrip('\n').split('\t')
                if len(parts) >= 3:
                    tips.append((parts[0], parts[1], parts[2]))
    missing = [c for c in want if c not in reach]
    print(f"  manifest        : {len(want)} commits")
    print(f"  reachable from {rev}: {len(want) - len(missing)}")
    print(f"  MISSING         : {len(missing)}")
    for c in missing[:10]:
        print(f"      {c}")
    tip_missing = []
    for c, ref, nf in tips:
        ok = c in reach
        print(f"  {'ok  ' if ok else 'MISSING'} preserve tip {ref} ({nf} files)")
        if not ok:
            tip_missing.append(ref)
    if tips_path and not tips:
        print("  note: no preserve tips declared")
    return 1 if (missing or tip_missing) else 0

if __name__ == '__main__':
    sys.exit(main())
