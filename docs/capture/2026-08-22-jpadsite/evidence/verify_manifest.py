#!/usr/bin/env python3
"""Verify MANIFEST.sha256, which is NOT in `sha256sum -c` format.

The file is named .sha256 and `sha256sum -c` reads ZERO lines from it and says
so only on stderr; a reader who runs the obvious command and skims can take an
empty result for a clean one.  This parses the real format:

    <relative/path> <size>B sha256:<64 hex>

Ten evidence files are .log/.def and the repo's .gitignore drops them at
`git add`, so a checkout of the bundle branch legitimately lacks them.  Those
are declared in OMITTED_BY_GITIGNORE.md, which is GENERATED from `git ls-files`
rather than hand-listed.  This verifier reads that declaration and treats such a
file as an EXPECTED absence -- reported by name, never silently -- so the one
manifest verifies both the private tree (all files present) and the published
branch (ten declared-absent).  An absence that is NOT declared is still a FAIL,
and a declared file that IS present is verified normally.

rc 0 PASS  every listed file present-and-matching, or absent-and-declared
rc 1 FAIL  a mismatch, an UNdeclared absence, or a file on disk absent from the
           manifest
rc 2 UNDETERMINED  manifest unreadable, parsed to zero entries, or the omission
           declaration is missing while files are absent (names which)
"""
import hashlib, pathlib, re, sys

LINE = re.compile(r'^(\S+)\s+(\d+)B\s+sha256:([0-9a-f]{64})\s*$')

def main(argv):
    here = pathlib.Path(argv[1] if len(argv) > 1 else '.').resolve()
    man = here / 'MANIFEST.sha256'
    try:
        raw = man.read_text(encoding='utf-8').split('\n')
    except OSError as e:
        print("UNDETERMINED: could not read %s (%s)" % (man, e)); return 2

    entries, junk = [], []
    for ln in raw:
        if not ln.strip() or ln.lstrip().startswith('#'):
            continue
        m = LINE.match(ln)
        (entries.append(m.groups()) if m else junk.append(ln[:70]))
    if not entries:
        print("UNDETERMINED: %s parsed to 0 entries -- an empty manifest "
              "verifies nothing. Unparsed lines: %d" % (man, len(junk)))
        return 2

    # the declared-omitted set, generated from `git ls-files`, never hand-listed
    omit_doc = here / 'OMITTED_BY_GITIGNORE.md'
    declared = set()
    if omit_doc.is_file():
        for m in re.finditer(r'[A-Za-z0-9_./-]+\.(?:log|def)',
                             omit_doc.read_text(encoding='utf-8')):
            declared.add(m.group(0))

    bad, expected_absent = [], []
    for rel, size, digest in entries:
        f = here / rel
        if not f.is_file():
            if rel in declared:
                expected_absent.append(rel)
            elif not omit_doc.is_file():
                why = ("the omission declaration itself is missing"
                       if rel == omit_doc.name else
                       "and there is no OMITTED_BY_GITIGNORE.md to say "
                       "whether that is expected")
                print("UNDETERMINED: %s is absent -- %s. Regenerate it with "
                      "gen_omitted.py." % (rel, why))
                return 2
            else:
                bad.append((rel, 'absent and NOT declared omitted'))
            continue
        b = f.read_bytes()
        if len(b) != int(size):
            bad.append((rel, 'size %d != %s' % (len(b), size))); continue
        h = hashlib.sha256(b).hexdigest()
        if h != digest:
            bad.append((rel, 'sha256 %s != %s' % (h[:12], digest[:12])))

    listed = {e[0] for e in entries}
    on_disk = {str(p.relative_to(here)) for p in here.rglob('*')
               if p.is_file() and p.name != 'MANIFEST.sha256'}
    uncited = sorted(on_disk - listed)

    print("manifest %s: %d entry(ies), %d unparsed line(s)"
          % (man.name, len(entries), len(junk)))
    print("  verified: %d   expected-absent (declared): %d   "
          "bad: %d   uncited on disk: %d"
          % (len(entries) - len(bad) - len(expected_absent),
             len(expected_absent), len(bad), len(uncited)))
    for r in expected_absent:
        print("  ABSENT-BY-DESIGN  %s (gitignore; declared)" % r)
    for r, why in bad:     print("  BAD      %s (%s)" % (r, why))
    for r in uncited:      print("  UNCITED  %s" % r)
    if junk:
        for j in junk[:5]: print("  UNPARSED %s" % j)
    if bad or uncited or junk:
        print("FAIL"); return 1
    print("PASS: %d file(s) match by size and digest, %d declared-absent by "
          "gitignore; nothing uncited."
          % (len(entries) - len(expected_absent), len(expected_absent)))
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
