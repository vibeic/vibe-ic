#!/usr/bin/env python3
"""Verify MANIFEST.sha256, which is NOT in `sha256sum -c` format.

The file is named .sha256 and `sha256sum -c` reads ZERO lines from it and says
so only on stderr; a reader who runs the obvious command and skims can take an
empty result for a clean one.  This parses the real format:

    <relative/path> <size>B sha256:<64 hex>

rc 0 PASS  every listed file present, size and digest match, none uncited
rc 1 FAIL  a mismatch, a missing file, or a file on disk absent from the manifest
rc 2 UNDETERMINED  manifest unreadable or parsed to zero entries (names which)
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

    bad = []
    for rel, size, digest in entries:
        f = here / rel
        if not f.is_file():
            bad.append((rel, 'absent')); continue
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
    print("  verified: %d   mismatched/absent: %d   uncited on disk: %d"
          % (len(entries) - len(bad), len(bad), len(uncited)))
    for r, why in bad:     print("  BAD      %s (%s)" % (r, why))
    for r in uncited:      print("  UNCITED  %s" % r)
    if junk:
        for j in junk[:5]: print("  UNPARSED %s" % j)
    if bad or uncited or junk:
        print("FAIL"); return 1
    print("PASS: %d file(s) match by size and digest; nothing uncited."
          % len(entries))
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
