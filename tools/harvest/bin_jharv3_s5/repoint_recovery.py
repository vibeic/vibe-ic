#!/usr/bin/env python3
"""Append a recovery instruction that resolves today to every row whose named anchors
origin has deleted. Append-only, verdict-preserving; every claim it writes is measured
first and the row is left untouched if the measurement does not support the claim."""
import re, subprocess, sys
sys.path.insert(0, '/home/reyerchu/_harv_priv/wt/tools/harvest/bin_jharv3_s5')
from recovery_resolves import FETCH, PLAIN, HEADRE, PLACEHOLDER, live_refs, git

TSV = '/home/reyerchu/_harv_priv/wt/tools/harvest/verdicts_shard_c.tsv'
REPO = '/home/reyerchu/vibe-ic'
BRANCH = 'harvest/worktree-triage-jharvest'
STAMP = '2026-08-22T06:40Z (jharv3, fifth session)'

live = live_refs(REPO)
if not live:
    sys.exit('REFUSED: origin unreachable; a recovery claim measured against refs/remotes is worthless')
tip = git(REPO, 'ls-remote', 'origin', 'refs/heads/' + BRANCH).stdout.split('\t')[0].strip()
git(REPO, 'fetch', '-q', 'origin', BRANCH, timeout=1800)
if not git(REPO, 'cat-file', '-e', tip + '^{commit}').returncode == 0:
    sys.exit('REFUSED: could not fetch the branch tip to walk it')

lines = open(TSV, encoding='utf-8').read().split('\n')
out, fixed, skipped = [], 0, []
for i, ln in enumerate(lines):
    if i == 0 or not ln.strip():
        out.append(ln); continue
    f = ln.split('\t')
    assert len(f) == 3, f'line {i+1} is not 3 columns'
    named = ({m.group(1) for m in FETCH.finditer(f[2])} |
             {m.group(1).rstrip(',.') for m in PLAIN.finditer(f[2])}) - PLACEHOLDER
    hm = HEADRE.search(f[2])
    head = git(REPO, 'rev-parse', '-q', '--verify', hm.group(1) + '^{commit}').stdout.strip() if hm else ''
    if not head:
        skipped.append((f[0], 'no resolvable judged head')); out.append(ln); continue
    resolves = [r for r in sorted(named) if r in live and
                git(REPO, 'merge-base', '--is-ancestor', head,
                    'refs/remotes/origin-live/' + r).returncode == 0]
    if resolves:
        out.append(ln); continue                      # already has a path that works
    if git(REPO, 'merge-base', '--is-ancestor', head, tip).returncode != 0:
        skipped.append((f[0], 'head NOT on the branch either -- needs preservation, not a re-point'))
        out.append(ln); continue                      # never write a recovery claim that is false
    dead = sorted(r for r in named if r not in live)
    deadtxt = ('the ref(s) this row names for recovery -- ' + ', '.join(dead) +
               ' -- have been deleted from origin') if dead else \
              ('no ref this row names both lives and still contains this head')
    verdict_before = f[1]
    f[2] += (f"  ***RECOVERY RE-POINTED {STAMP}: {deadtxt} (checked with `git ls-remote`, which "
             f"advertises {len(live)//2} refs, none of them these), so every `git fetch origin ...` "
             f"instruction above FAILS today. The content is not lost and the verdict is unchanged: this "
             f"row's judged HEAD {head[:12]} is contained by the LIVE origin branch {BRANCH} (tip {tip[:9]} "
             f"when checked), verified by walking that ref after fetching it, not from refs/remotes. The "
             f"instruction that resolves today: git fetch origin {BRANCH} && git checkout {head}. Gate: "
             f"bin_jharv3_s5/recovery_resolves.py, which parses the `git fetch origin X` form as well as the "
             f"prose form and EXITS 2 rather than reporting a pass when it parses no citation at all -- the "
             f"existing citation gate matches only the backticked form, of which this file contains none, so "
             f"it walked this file and examined nothing in it.***")
    assert f[1] == verdict_before
    out.append('\t'.join(f)); fixed += 1

open(TSV, 'w', encoding='utf-8').write('\n'.join(out))
print(f'rows re-pointed: {fixed}')
for p, why in skipped:
    print(f'  SKIPPED (no claim written): {p} -- {why}')
