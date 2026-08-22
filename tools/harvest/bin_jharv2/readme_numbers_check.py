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
    def _add_lines():
        with open(os.path.join(base, 'bin_jharv2', 'check_all.sh')) as f:
            return [l for l in f if l.startswith('add "')]
    def gates_declared():
        return len(_add_lines())
    def offline_gates():
        """Gates needing nothing but the checkout.

        Derived by classifying check_all.sh, not counted by hand -- the hand-written number was
        seven when the answer was eight, and it drifts every time a gate is added. Fails closed:
        a gate whose script cannot be located raises rather than being assumed offline, because
        the assumption that makes the count pass is the one that makes it wrong."""
        # Assembled from fragments on purpose. Written as one literal, this file matches its OWN
        # pattern, classifies itself as a network gate, and returns 7 -- which is exactly the stale
        # number the check exists to catch. A checker that reads itself must not recognise itself.
        NET = re.compile('|'.join(['ls-' + 'remote', 'ssh' + ' ', 'git ' + 'fetch', 'git ' + 'clone']))
        n = 0
        for line in _add_lines():
            scripts = re.findall(r'\$B/([A-Za-z0-9_.-]+\.(?:sh|py))', line)
            if not scripts:
                raise RuntimeError(f'cannot locate the script for gate: {line.strip()[:60]}')
            net = False
            for sc in scripts:
                fp = os.path.join(base, 'bin_jharv2', sc)
                if not os.path.exists(fp):
                    raise RuntimeError(f'gate script named but absent: {sc}')
                if NET.search(open(fp, encoding='utf-8', errors='replace').read()):
                    net = True
            if not net: n += 1
        return n
    def manifest_commits():
        with open(os.path.join(base, 'rescued_commits.txt')) as f:
            return sum(1 for l in f if l.strip())
    CLAIMS = [
        (r'(\d+) markdown files',                 lambda: count_ext('.md')),
        (r'and (\d+) scripts',                    lambda: count_ext('.sh') + count_ext('.py')),
        (r'\*\*authorise deletion\*\* — (\d+) rows do', deletion_bound),
        (r'deletion-bound — (\d+) of \d+',        vacuous_in_joined),
        # The manifest count appeared twice in prose as 2950 while the file held 3039. Nothing
        # regenerated either sentence, and the table gate above cannot see a number in a paragraph.
        (r'the ([\d,]+) commits in\s+`?rescued_commits', manifest_commits),
        (r'all ([\d,]+) while every file',        manifest_commits),
    ]
    # Spelled-out counts, matched as word OR digit. Kept separate from CLAIMS because every
    # occurrence must agree, not just the first one found.
    WORDCLAIMS = [
        (r'\b(%s|\d+) gates\b' % '|'.join(WORDS), gates_declared),
        (r'\b(%s|\d+) need nothing but the checkout' % '|'.join(WORDS), offline_gates),
    ]
    # The gate COUNT is itself a prose claim, written as a word ("Twelve gates"), which is why the
    # digit-matching claims never covered it -- a check that only sees digits cannot see a number
    # spelled out. And re.search stops at the FIRST match: a second, contradicting occurrence three
    # paragraphs down passed silently. Every occurrence is checked.
    checked_prose_extra = 0
    for rx, fn in WORDCLAIMS:
        ms = list(re.finditer(rx, txt, re.I))
        if not ms:
            print(f"  MISSING  no claim matching /{rx[:34]}../ in the README"); bad += 1; continue
        try:
            actual_g = fn()
        except RuntimeError as e:
            print(f"  *** cannot derive actual for /{rx[:34]}../: {e} ***"); bad += 1; continue
        for m in ms:
            tok = m.group(1).lower()
            claimed_g = WORDS[tok] if tok in WORDS else int(tok)
            ok = claimed_g == actual_g
            print(f"  {'ok  ' if ok else 'WRONG'} /{rx[:30]}../ occurrence at {m.start():5}  "
                  f"README={claimed_g}  actual={actual_g}")
            if not ok: bad += 1
            checked_prose_extra += 1
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
