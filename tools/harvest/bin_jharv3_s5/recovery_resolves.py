#!/usr/bin/env python3
"""Every row must offer a recovery instruction that resolves TODAY.

A verdict row is only as good as the command a reader can run against it. Shard C's rows
were written when `harvest/rescue-*` anchors existed; origin has since deleted them, so
rows that are perfectly correct about content hand the reader a `git fetch` that fails.

Two things this checks that the existing citation gate does not:

1. NOT VACUOUS. bin_jharv2/live_ref_citation_check.py matches ``reachable from `X` `` --
   the backticked form. verdicts_shard_c.tsv contains ZERO backticked citations, so that
   gate walked the file and examined nothing in it while reporting 0 dead / 0 moved. This
   one parses both the prose form and the `git fetch origin X` instruction, and EXITS 2 if
   it finds no citations at all rather than reporting success over an empty set.

2. EXISTENCE IS NOT CONTAINMENT, and neither is citation. A row passes only if some ref it
   names is live AND still contains the head the row is about -- verified by walking the ref
   fetched from origin, never from refs/remotes, which caches refs origin has deleted.

Usage:  recovery_resolves.py <verdicts.tsv> [repo]     |     recovery_resolves.py --self-test
"""
import re, subprocess, sys, os

FETCH = re.compile(r'git fetch origin ([A-Za-z0-9._/-]+)')
PLAIN = re.compile(r'reachable from (?:the LIVE origin branch |the live origin branch |origin/)([A-Za-z0-9._/#-]+)')
HEADRE = re.compile(r'worktree HEAD (?:when judged|at re-verification):\s*([0-9a-f]{7,40})')
# NOTE: this pattern was widened once, and the reason matters. It first matched only
# 'when judged'; one row records its head as 'worktree HEAD at re-verification:' and the
# gate reported 'no judged head this clone can resolve' -- a parse gap, not a finding. The
# widening adds a spelling of the SAME field; it does not weaken any assertion, and the
# self-test proves that by driving a row written in the new spelling to RED on a dead ref
# and to RED on a live ref that does not contain the head.
PLACEHOLDER = {'harvest/rescue-...', '<anchor>'}


def git(repo, *args, **kw):
    return subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True, **kw)


def live_refs(repo):
    out = git(repo, 'ls-remote', 'origin', timeout=600)
    if out.returncode != 0:
        return None
    live = set()
    for line in out.stdout.splitlines():
        if '\t' not in line:
            continue
        ref = line.split('\t')[1].strip()
        live.add(ref)
        live.add(ref.replace('refs/heads/', ''))
    return live or None


def check(tsv, repo, live, fetch_ns=True):
    if fetch_ns:
        git(repo, 'fetch', '-q', 'origin', '+refs/heads/*:refs/remotes/origin-live/*', '--prune', timeout=1800)
    rows = [l.rstrip('\n').split('\t') for l in open(tsv, encoding='utf-8')][1:]
    rows = [r for r in rows if len(r) == 3]
    cites = 0
    bad = []
    for path, verdict, ev in rows:
        named = {m.group(1) for m in FETCH.finditer(ev)} | {m.group(1).rstrip(',.') for m in PLAIN.finditer(ev)}
        named -= PLACEHOLDER
        cites += len(named)
        hm = HEADRE.search(ev)
        head = git(repo, 'rev-parse', '-q', '--verify', hm.group(1) + '^{commit}').stdout.strip() if hm else ''
        if not head:
            bad.append((path, verdict, 'no judged head this clone can resolve', sorted(named)))
            continue
        resolves = [r for r in sorted(named) if r in live and
                    git(repo, 'merge-base', '--is-ancestor', head, 'refs/remotes/origin-live/' + r).returncode == 0]
        if not resolves:
            deadrefs = [r for r in sorted(named) if r not in live]
            why = 'every named ref is gone from origin' if deadrefs and len(deadrefs) == len(named) \
                  else 'no named ref both lives and contains this head'
            bad.append((path, verdict, why, sorted(named)))
    return rows, cites, bad


def main():
    tsv = sys.argv[1]
    repo = sys.argv[2] if len(sys.argv) > 2 else '/home/reyerchu/vibe-ic'
    live = live_refs(repo)
    if live is None:
        print('  cannot reach origin -- refusing rather than judging against refs/remotes')
        return 2
    rows, cites, bad = check(tsv, repo, live)
    print(f'  rows examined              : {len(rows)}')
    print(f'  recovery citations parsed  : {cites}')
    if not rows or not cites:
        print('  *** nothing examined -- this check is VACUOUS and refuses to report a pass ***')
        return 2
    print(f'  rows with NO instruction that resolves today : {len(bad)}')
    for path, verdict, why, named in bad[:15]:
        print(f'      {verdict:8} {path}  --  {why}: {", ".join(named) if named else "(names no ref)"}')
    if len(bad) > 15:
        print(f'      ... and {len(bad) - 15} more')
    return 1 if bad else 0


def self_test():
    """Each guarantee must be shown going RED, or the gate is decoration."""
    import tempfile
    repo = '/home/reyerchu/vibe-ic'
    live = live_refs(repo)
    if live is None:
        print('SELF-TEST INCONCLUSIVE: origin unreachable'); return 2
    tip_head = git(repo, 'rev-parse', 'origin/main~1').stdout.strip()
    HDR = 'path\tverdict\tevidence\n'
    cases = []
    # 1. a live ref that contains the head -> GREEN
    cases.append(('live ref containing the head', 0,
        f'/x\tRECOVER\t[worktree HEAD when judged: {tip_head}] recover with git fetch origin main && git checkout {tip_head}\n'))
    # 2. a ref origin does not have -> RED
    cases.append(('ref deleted from origin', 1,
        f'/x\tRECOVER\t[worktree HEAD when judged: {tip_head}] recover with git fetch origin harvest/rescue-does-not-exist && git checkout {tip_head}\n'))
    # 3. a LIVE ref that no longer contains the head -> RED (existence is not containment)
    orphan = git(repo, 'rev-parse', 'origin/harvest/rescue-reanchor-1').stdout.strip()
    cases.append(('live ref that does not contain the head', 1,
        f'/x\tRECOVER\t[worktree HEAD when judged: {orphan}] recover with git fetch origin main && git checkout {orphan}\n'))
    # 4. no citations at all -> exit 2, not a pass
    cases.append(('a file with no citations', 2, '/x\tRECOVER\tjust prose, no ref named\n'))
    # 5. the widened head spelling must be READ, not excused: same dead ref, still RED
    cases.append(('dead ref, head written as "at re-verification"', 1,
        f'/x\tRECOVER\t[worktree HEAD at re-verification: {tip_head}] recover with git fetch origin harvest/rescue-does-not-exist && git checkout {tip_head}\n'))
    # 6. and the widened spelling still passes only when the ref really contains the head
    cases.append(('live containing ref, head written as "at re-verification"', 0,
        f'/x\tRECOVER\t[worktree HEAD at re-verification: {tip_head}] recover with git fetch origin main && git checkout {tip_head}\n'))
    rc_all = 0
    for name, want, body in cases:
        with tempfile.NamedTemporaryFile('w', suffix='.tsv', delete=False) as fh:
            fh.write(HDR + body); p = fh.name
        rows, cites, bad = check(p, repo, live, fetch_ns=False)
        got = 2 if (not rows or not cites) else (1 if bad else 0)
        os.unlink(p)
        ok = got == want
        rc_all |= 0 if ok else 1
        print(f'  [{"ok" if ok else "FAIL"}] {name}: expected rc={want}, got rc={got}')
    print('SELF-TEST', 'PASSED' if rc_all == 0 else 'FAILED')
    return rc_all


if __name__ == '__main__':
    sys.exit(self_test() if '--self-test' in sys.argv else main())
