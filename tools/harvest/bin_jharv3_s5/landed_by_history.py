#!/usr/bin/env python3
"""Did this worktree's content already reach main? Asked against main's HISTORY, not its tip.

WHY THE TIP IS THE WRONG QUESTION, AND WHY THIS ROW-RULE WAS WRONG 17 TIMES.
Shard C's rule R2 calls a worktree unlanded when a file in it differs from
`git show origin/main:<path>`. That is main's TIP. vibe-ic squash-lands and then keeps
moving: a branch whose work landed on 2026-08-04 differs from the tip of 2026-08-22 in
exactly the same way an unlanded branch does. The brief's own warning -- "a branch whose
content is fully on main still shows as ahead" -- has a second half nobody wrote down:
a branch whose content is fully on main also still shows as DIFFERENT.

THE QUESTION THAT SEPARATES THEM. For every path the head holds: did main's history ever
hold exactly these bytes AT THIS PATH? If yes for every path, everything in the worktree
reached main and deleting it destroys nothing. If no for even one, it holds work main
never had.

TWO TRAPS THIS HITS, BOTH MEASURED HERE:
  * `git rev-list --objects <main>` names each blob under ONE path, so a (path, blob)
    index built from it proves presence and CANNOT prove absence -- 109 of main's own tip
    files are "missing" from such an index because a sibling path holds the same bytes.
  * `git rev-list <main> -- <path>` applies history simplification: for one file here it
    returned 7 commits and hid the one that held the content. `--full-history` returned
    14 and found it. A search that stops at the simplified list reports NOWHERE for
    content that is plainly there.

usage:  landed_by_history.py <head> [repo] [main]      |      landed_by_history.py --self-test
"""
import subprocess, sys

def g(repo, *a):
    return subprocess.run(['git', '-C', repo, *a], capture_output=True, text=True)

def main_blob_index(repo, main):
    """(path, blob) pairs reachable from main, plus the blob-only set. Presence-only."""
    out = g(repo, 'rev-list', '--objects', main).stdout
    pairs, blobs = set(), set()
    for line in out.split('\n'):
        if ' ' not in line:
            continue
        sha, path = line.split(' ', 1)
        pairs.add(f'{path}\t{sha}')
        blobs.add(sha)
    return pairs, blobs

def ever_at_path(repo, main, path, blob, pairs, cache):
    if f'{path}\t{blob}' in pairs:
        return True, ''
    key = (path, blob)
    if key in cache:
        return cache[key]
    # --full-history: the simplified list hides commits that held other versions
    for c in g(repo, 'rev-list', '--full-history', main, '--', path).stdout.split():
        if g(repo, 'rev-parse', '-q', '--verify', f'{c}:{path}').stdout.strip() == blob:
            cache[key] = (True, c)
            return True, c
    cache[key] = (False, '')
    return False, ''

def tracked(repo, head):
    pairs = []
    for line in g(repo, 'ls-tree', '-r', head).stdout.split('\n'):
        if not line.strip():
            continue
        meta, path = line.split('\t', 1)
        mode, typ, sha = meta.split()
        if typ == 'blob':
            pairs.append((path, sha))
    return pairs

def classify(repo, main, head, pairs=None, blobs=None):
    if pairs is None:
        pairs, blobs = main_blob_index(repo, main)
    files = tracked(repo, head)
    if not files:
        return {'verdict': 'REFUSED', 'why': 'the head tracks 0 files -- nothing was examined'}
    cache = {}
    novel_bytes = [p for p, s in files if s not in blobs]
    diff = [x for x in g(repo, 'diff', '--name-only', main, head).stdout.split('\n') if x.strip()]
    held, novel, holder = 0, [], ''
    for path in diff:
        b = g(repo, 'rev-parse', '-q', '--verify', f'{head}:{path}').stdout.strip()
        if not b:
            continue                       # main has it, this head does not: nothing held here
        ok, c = ever_at_path(repo, main, path, b, pairs, cache)
        if ok:
            held += 1
            holder = holder or c
        else:
            novel.append(path)
    return {'verdict': 'CONTENT_REACHED_MAIN' if not novel else 'HOLDS_CONTENT_MAIN_NEVER_HAD',
            'tracked': len(files), 'differs_from_tip': len(diff), 'held_at_path': held,
            'novel': novel, 'novel_bytes': len(novel_bytes), 'example_holder': holder}

def self_test():
    repo, main = '/home/reyerchu/vibe-ic', 'a4caccefeab577a5337f1854c9c857e4d7a2bd42'
    pairs, blobs = main_blob_index(repo, main)
    ok = True
    # 1. main's own tip must come back reached (and non-vacuously)
    r = classify(repo, main, main, pairs, blobs)
    c1 = r['verdict'] == 'CONTENT_REACHED_MAIN' and r['tracked'] > 1000
    print(f'  [{"ok" if c1 else "FAIL"}] main tip reaches main over {r["tracked"]} tracked files')
    ok &= c1
    # 2. a head with real unlanded work must come back holding it
    r2 = classify(repo, main, 'af1072b95b8f1eedbb59a7ac0fc4c0b083e34cbf', pairs, blobs)
    c2 = r2['verdict'] == 'HOLDS_CONTENT_MAIN_NEVER_HAD' and bool(r2['novel'])
    print(f'  [{"ok" if c2 else "FAIL"}] a known-unlanded head holds {len(r2["novel"])} paths main never had')
    ok &= c2
    # 3. the simplification trap: the file that reported NOWHERE under simplified history
    p = 'vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_signoff_medlow_backlog_gaps.py'
    b = g(repo, 'rev-parse', '31fb2c1efe49b8f2579fce73d1f18d1a60ca0cd5:' + p).stdout.strip()
    simple = any(g(repo, 'rev-parse', '-q', '--verify', f'{c}:{p}').stdout.strip() == b
                 for c in g(repo, 'rev-list', main, '--', p).stdout.split())
    full, holder = ever_at_path(repo, main, p, b, set(), {})
    c3 = (not simple) and full
    print(f'  [{"ok" if c3 else "FAIL"}] simplified history hides the holder ({simple}), '
          f'--full-history finds it ({holder[:12]})')
    ok &= c3
    # 4. a (path, blob) index from rev-list --objects cannot prove absence
    tip = tracked(repo, main)
    missing = [p for p, s in tip if f'{p}\t{s}' not in pairs]
    c4 = len(missing) > 0
    print(f'  [{"ok" if c4 else "FAIL"}] the path-keyed index misses {len(missing)} of main\'s OWN '
          f'tip files, so a miss is not absence')
    ok &= c4
    # 5. an empty measurement must refuse, not pass
    empty = g(repo, 'hash-object', '-t', 'tree', '/dev/null').stdout.strip()
    c5 = classify(repo, main, g(repo, 'commit-tree', empty, '-m', 'empty').stdout.strip())['verdict'] == 'REFUSED'
    print(f'  [{"ok" if c5 else "FAIL"}] a head tracking 0 files is REFUSED, not passed')
    ok &= c5
    print('SELF-TEST', 'PASSED' if ok else 'FAILED')
    return 0 if ok else 1

if __name__ == '__main__':
    if '--self-test' in sys.argv:
        sys.exit(self_test())
    head = sys.argv[1]
    repo = sys.argv[2] if len(sys.argv) > 2 else '/home/reyerchu/vibe-ic'
    mn = sys.argv[3] if len(sys.argv) > 3 else 'origin/main'
    r = classify(repo, g(repo, 'rev-parse', mn).stdout.strip(), head)
    print(r['verdict'], {k: v for k, v in r.items() if k not in ('verdict', 'novel')})
    for p in r.get('novel', [])[:10]:
        print('   never on main at that path:', p)
    sys.exit(0 if r['verdict'] == 'CONTENT_REACHED_MAIN' else 1)
