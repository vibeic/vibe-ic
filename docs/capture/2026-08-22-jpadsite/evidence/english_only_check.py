#!/usr/bin/env python3
"""Grade the brief's "English only in repo artefacts" constraint on RESULT.md.

The constraint and quotation-integrity pull in opposite directions: the design's
own L-documents are not in English, and altering a quotation to satisfy a style
rule falsifies evidence.  This grades the resolution actually used -- the
quotation stays byte-exact and an English rendering sits beside it -- so a reader
who reads no CJK can still read every claim, and a reader who does can check the
quote against the source.

rc 0 PASS  every CJK run is inside a quotation and has a rendering within 3 lines
rc 1 FAIL  a CJK run with no rendering, or outside a quotation
rc 2 UNDETERMINED  the file could not be read (names what it could not read)
"""
import re, sys, pathlib

CJK = re.compile(r'[一-鿿]+')
# an English rendering is introduced by (= "...") or by a "-- not ... " gloss
REND = re.compile(r'\(=\s*"|"\s*=\s*"|— not\b|-- not\b')

def main(argv):
    target = pathlib.Path(argv[1] if len(argv) > 1 else
                          '/home/reyerchu/_jpadsite_priv/RESULT.md')
    try:
        lines = target.read_text(encoding='utf-8').split('\n')
    except OSError as e:
        print("UNDETERMINED: could not read %s (%s)" % (target, e))
        return 2
    if not lines or not any(lines):
        print("UNDETERMINED: %s is empty -- an empty scan is not a clean scan"
              % target)
        return 2

    hits = [(i, ln) for i, ln in enumerate(lines, 1) if CJK.search(ln)]
    if not hits:
        print("NOT OBSERVED: no CJK in %s. Either the constraint is trivially "
              "met or this is the wrong file -- refusing to call that PASS."
              % target)
        return 2

    bad = []
    for n, ln in hits:
        window = '\n'.join(lines[max(0, n - 2): n + 3])
        quoted = ('"' in ln) or ('`' in ln)
        rendered = bool(REND.search(window))
        if not (quoted and rendered):
            bad.append((n, ln.strip()[:80],
                        'not in a quotation' if not quoted
                        else 'no English rendering within 3 lines'))

    runs = sum(len(CJK.findall(ln)) for _, ln in hits)
    print("scanned %s: %d line(s) carrying %d CJK run(s)"
          % (target.name, len(hits), runs))
    for n, _ in hits:
        print("  line %d: quoted + rendered" % n
              if not any(b[0] == n for b in bad) else "  line %d: UNRENDERED" % n)
    if bad:
        print("FAIL: %d unrendered site(s)" % len(bad))
        for n, s, why in bad:
            print("  line %d (%s): %s" % (n, why, s))
        return 1
    print("PASS: every CJK run is a verbatim quotation with an adjacent English "
          "rendering; no quotation was altered to satisfy the constraint.")
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
