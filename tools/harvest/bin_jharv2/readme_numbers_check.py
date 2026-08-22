#!/usr/bin/env python3
"""Every count printed in README.md must equal the file it describes.

An index is the artefact most likely to go stale and least likely to be re-read, and a wrong count
in it is worse than no count -- it is a measured-looking claim nobody re-measures. This parses the
`| file.tsv | N |` rows out of the README and compares N to the actual row count.

Fails if it finds ZERO rows to check: a regex that stops matching is indistinguishable from a
README that is entirely correct.
"""
import csv, os, re, sys

def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'tools/harvest'
    md = os.path.join(base, 'README.md')
    txt = open(md).read()
    pat = re.compile(r'^\|\s*\[?`([A-Za-z0-9_.\-]+\.tsv)`\]?[^|]*\|\s*\*{0,2}([0-9,]+)\*{0,2}\s*\|', re.M)
    hits = pat.findall(txt)
    if not hits:
        print("  *** no `| file.tsv | N |` rows matched -- the check is vacuous ***")
        return 2
    bad = 0
    for fname, n in hits:
        p = os.path.join(base, fname)
        if not os.path.exists(p):
            print(f"  MISSING  {fname} named in README but not present"); bad += 1; continue
        actual = sum(1 for _ in open(p)) - 1
        claimed = int(n.replace(',', ''))
        ok = actual == claimed
        print(f"  {'ok  ' if ok else 'WRONG'} {fname:36} README={claimed:5}  actual={actual:5}")
        if not ok: bad += 1
    # PROSE claims. The table gate above caught none of these: within hours of writing this index
    # four prose numbers were stale -- two because I added files to the directory it describes, two
    # because the files it counts changed underneath. A number in prose is exactly as load-bearing
    # as one in a table and rots faster, because nothing regenerates it.
    import subprocess, collections
    def rows(fn, delim='\t'):
        with open(os.path.join(base, fn)) as f:
            return list(csv.reader(f, delimiter=delim))[1:]
    def count_ext(ext):
        # os.walk, NOT a hardcoded subdirectory list. The first version listed
        # bin/bin_jharv2/bin_jharv3/shard_c and reported 64 scripts where the directory holds 70 --
        # a checker whose own enumeration is incomplete produces a confident wrong "actual" and
        # blames the document. Enumerate the tree; do not name its parts.
        n = 0
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != '.git']
            n += sum(1 for f in files if f.endswith(ext))
        return n
    def deletion_bound():
        return sum(1 for r in rows('verdicts_all.tsv') if len(r) > 2 and r[2] in ('LANDED', 'ABANDON'))
    def vacuous_in_joined():
        return sum(1 for r in rows('verdicts_joined.tsv')
                   if len(r) >= 5 and 'all 0 file(s)' in r[3] and r[2] in ('LANDED', 'ABANDON', 'DROP'))
    WORDS = {'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,
             'eleven':11,'twelve':12,'thirteen':13,'fourteen':14,'fifteen':15}
    def gates_declared():
        with open(os.path.join(base, 'bin_jharv2', 'check_all.sh')) as f:
            return sum(1 for l in f if l.startswith('add "'))
    CLAIMS = [
        (r'(\d+) markdown files',                 lambda: count_ext('.md')),
        (r'and (\d+) scripts',                    lambda: count_ext('.sh') + count_ext('.py')),
        (r'\*\*authorise deletion\*\* — (\d+) rows do', deletion_bound),
        (r'deletion-bound — (\d+) of \d+',        vacuous_in_joined),
    ]
    # The gate COUNT is itself a prose claim, and it was not checked. It is written as a word
    # ("Twelve gates"), which is why the digit-matching claims above never covered it -- a gate that
    # only sees digits cannot see a number spelled out.
    wm = re.search(r'\b(' + '|'.join(WORDS) + r') gates\b', txt, re.I)
    if wm:
        claimed_g = WORDS[wm.group(1).lower()]
        actual_g = gates_declared()
        ok = claimed_g == actual_g
        print(f"  {'ok  ' if ok else 'WRONG'} /<word> gates/  README={claimed_g}  actual={actual_g}")
        if not ok: bad += 1
        checked_prose_extra = 1
    else:
        print("  MISSING  no '<word> gates' claim in the README"); bad += 1
        checked_prose_extra = 0
    print("  -- prose claims --")
    checked_prose = 0
    for rx, fn in CLAIMS:
        m = re.search(rx, txt)
        if not m:
            print(f"  MISSING  no prose match for /{rx}/ -- the claim moved or was reworded"); bad += 1; continue
        checked_prose += 1
        claimed, actual = int(m.group(1)), fn()
        ok = claimed == actual
        print(f"  {'ok  ' if ok else 'WRONG'} /{rx}/  README={claimed}  actual={actual}")
        if not ok: bad += 1
    if checked_prose == 0:
        print("  *** no prose claims matched -- that half of the check is vacuous ***")
        return 2
    print(f"  checked {len(hits)} table counts + {checked_prose + checked_prose_extra} prose claims, {bad} wrong")
    return 1 if bad else 0

if __name__ == '__main__':
    sys.exit(main())
