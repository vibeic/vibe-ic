#!/usr/bin/env python3
"""A row that says a worktree is safe to delete BECAUSE its commit is reachable from `origin/<ref>`
is only safe while that ref exists. On 2026-08-22 every `harvest/rescue-*` ref was gone from origin
while this clone's refs/remotes still listed 529 of them, and nine worktrees whose rows read
ON_REMOTE had been deleted with their commits on no origin ref at all.

Checks ONLY survivability citations -- the `reachable from \\`origin/X\\`` form. It deliberately does
NOT flag every mention of a deleted branch: rows legitimately quote the branch a worktree was on, the
subject of a tip commit, and (since the incident) the name of the anchor that was deleted. A sweep
that flags all of those reported 383 defects in my files, every one of which was the audit trail of
the fix. The claim is what must be live, not the prose.

Authority is `git ls-remote`, never refs/remotes -- that cache is what made the original failure
invisible. PR heads count: refs/pull/N/head preserves a commit exactly as a branch does, and
`ls-remote --heads` does not list them.
"""
import csv, glob, os, re, subprocess, sys

CITE = re.compile(r'reachable from `(?:origin/)?([^`]+)`')

def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'tools/harvest'
    repo = sys.argv[2] if len(sys.argv) > 2 else '/home/reyerchu/vibe-ic'
    out = subprocess.run(['git', '-C', repo, 'ls-remote', 'origin'],
                         capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        print("  cannot reach origin -- refusing to check against refs/remotes"); return 2
    live = set()
    for line in out.stdout.splitlines():
        parts = line.split('\t')
        if len(parts) == 2:
            live.add(parts[1].replace('refs/heads/', ''))
            live.add(parts[1])
    if not live:
        print("  origin advertised NOTHING -- refusing, every citation would read dead"); return 2
    total = dead = 0
    bad_by_ref = {}
    for p in sorted(glob.glob(os.path.join(base, '*.tsv'))):
        rows = list(csv.reader(open(p), delimiter='\t'))
        for r in rows[1:]:
            blob = '\t'.join(r)
            for m in CITE.finditer(blob):
                ref = m.group(1)
                total += 1
                if ref in live or ref.replace('refs/pull/', '').replace('/head', '') in live:
                    continue
                if ref.startswith('refs/pull/'):
                    continue
                dead += 1
                bad_by_ref.setdefault((os.path.basename(p), ref), 0)
                bad_by_ref[(os.path.basename(p), ref)] += 1
    print(f"  origin advertises {len(live)} ref names")
    print(f"  survivability citations : {total}")
    print(f"  citing a DEAD ref       : {dead}")
    for (f, ref), n in sorted(bad_by_ref.items(), key=lambda x: -x[1])[:10]:
        print(f"      {n:4}  {f}  ->  {ref}")
    if total == 0:
        print("  *** no survivability citations found -- the check is vacuous ***")
        return 2
    return 1 if dead else 0

if __name__ == '__main__':
    sys.exit(main())
