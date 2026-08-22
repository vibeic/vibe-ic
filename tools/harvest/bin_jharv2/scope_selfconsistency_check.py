#!/usr/bin/env python3
"""SCOPE.md's census table must add up, and the prose around it must agree with it.

Three times this session a table was updated and the sentences summarising it were not:
  - the heading said "six reachable hosts" above a seven-row table
  - "1416 of 13308 is 11%" sat one line under a total reading 14,196
  - the README index described SCOPE.md with the superseded figure

Those are the sentences a reader quotes. readme_numbers_check.py gates README.md; nothing gated
this, so it was caught by hand each time -- which is not a method, it is luck plus a habit.

Checks:
  1. the per-host rows sum to the total row (bounded rows use >= and must not make the total exceed)
  2. the host count named in the heading equals the number of rows
  3. the percentage in the prose matches judged/total to the nearest whole number
  4. no superseded totals linger anywhere in the file

Fails if it finds no table at all: a regex that stops matching must not read as a clean document.
"""
import os, re, sys

def num(s):
    """First integer in the cell. Cells carry annotations -- '≥888 (depth-4 lower bound)' -- and a
    strict int() on the whole cell raises rather than reading the number that is plainly there."""
    m = re.search(r'([\d,]+)', s.replace('**', ''))
    if not m: raise ValueError(f"no number in cell: {s!r}")
    return int(m.group(1).replace(',', ''))

def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'tools/harvest'
    p = os.path.join(base, 'SCOPE.md')
    full = open(p).read()
    # SCOPE.md holds more than one table with `.105`-style row labels -- the untracked-file sweep has
    # one too. An unscoped row regex matched 9 rows across both and reported a total mismatch that
    # was the CHECK's error, not the document's. Slice to the census section first.
    m = re.search(r'^## Measured[^\n]*\n(.*?)(?=^## )', full, re.M | re.S)
    if not m:
        print("  *** census section not found -- the check is vacuous ***"); return 2
    txt = m.group(0)
    rows = re.findall(r'^\|\s*(\.\d+)[^|]*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$', txt, re.M)
    if not rows:
        print("  *** no per-host rows matched -- the check is vacuous ***"); return 2
    tot = re.search(r'^\|\s*\*\*total[^|]*\*\*\s*\|\s*\*\*([^|]+?)\*\*\s*\|\s*\*\*([^|]+?)\*\*\s*\|\s*\*\*([^|]+?)\*\*\s*\|', txt, re.M)
    if not tot:
        print("  *** no total row matched -- the check is vacuous ***"); return 2
    bad = 0
    s_check = sum(num(r[1]) for r in rows)
    s_jud   = sum(num(r[2]) for r in rows)
    t_check, t_jud = num(tot.group(1)), num(tot.group(2))
    print(f"  rows: {len(rows)}   summed checkouts={s_check} judged={s_jud}")
    print(f"  total row:          checkouts={t_check} judged={t_jud}")
    if s_check != t_check: print(f"  WRONG total checkouts: rows sum to {s_check}, total says {t_check}"); bad += 1
    if s_jud   != t_jud:   print(f"  WRONG total judged: rows sum to {s_jud}, total says {t_jud}"); bad += 1
    m = re.search(r'census[^\n]*?\b(all seven|seven|six|five|four|three)\b', full)
    words = {'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'all seven': 7}
    if m:
        claimed = words[m.group(1)]
        print(f"  heading claims {claimed} hosts, table has {len(rows)}")
        if claimed != len(rows): print("  WRONG host count in the heading"); bad += 1
    else:
        print("  MISSING host-count claim in the heading"); bad += 1
    pm = re.search(r'\*\*([\d,]+) of (?:at least )?([\d,]+) is about (\d+)%', full)
    if pm:
        j, t, pc = num(pm.group(1)), num(pm.group(2)), int(pm.group(3))
        real = round(100.0 * j / t)
        print(f"  prose: {j} of {t} = {pc}%   recomputed {real}%")
        if j != t_jud or t != t_check: print("  WRONG prose totals disagree with the table"); bad += 1
        if abs(real - pc) > 1: print(f"  WRONG percentage: says {pc}%, computes {real}%"); bad += 1
    else:
        print("  MISSING percentage claim"); bad += 1
    for stale in ('13,308', '13308', '1,416 of', '1416 of'):
        if stale in full: print(f"  STALE token still present: {stale}"); bad += 1
    print(f"  problems: {bad}")
    return 1 if bad else 0

if __name__ == '__main__':
    sys.exit(main())
