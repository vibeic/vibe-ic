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
    print(f"  checked {len(hits)} counts, {bad} wrong")
    return 1 if bad else 0

if __name__ == '__main__':
    sys.exit(main())
