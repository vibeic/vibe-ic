#!/usr/bin/env python3
"""J102 — this report keeps TWO trees of its own instruments.  Do they agree?

Every control in this report lives twice: once under `meas/_jNN/`, where it was written
and where the report CITES it, and once under `selftapeout-adjudication/controls/`,
which is the copy on the remote and the only copy a reader off this host can run.  The
J96 census moved instruments into `controls/` and nothing has ever asked whether the
two copies still say the same thing.

They did not.  On the run that motivated this file, `meas/_j79/decay_ledger.py` -- the
path RESULT.md publishes as "the decay ledger" -- printed **2 published readings MOVED**
while the `controls/` copy of the same instrument printed **none moved**.  The two reds
were both pre-J100 pins that J100 had already corrected in the other copy.  A citation
that resolves to a stale instrument is worse than no citation: it hands a reader two
alarms that are false, in a report whose whole method is that a red means something.

So the question is asked of EVERY pair, in both directions, by comparing BYTES:

  * every instrument path CITED in RESULT.md must resolve -- under the private
    root, or under one of the published trees                             (else red)
  * every cited instrument with a same-named twin in the published tree
    must be byte-identical to it                                          (else red)
  * every instrument in ANY published tree with a same-named twin anywhere
    under meas/ must be byte-identical to it                              (else red)

The third arm is the one that matters most, because it does not depend on my having
remembered to cite the file.  Drift is found by enumerating the directories, never from
a list typed here -- `controls_can_fail.py` was wrong in exactly that way first.

This file states NO opinion about which copy is right.  It reports that they differ and
where; deciding which is current is a judgement, and a judgement is not a control's job.

Env overrides `J102_ROOT` / `J102_PUB` exist so the census can point it at synthetic
trees and require the verdict to flip.

Run from anywhere.
"""
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(os.environ.get("J102_ROOT", "/home/reyerchu/_jself_priv"))
DOC = ROOT / "RESULT.md"

# The PUBLISHED TREES are ENUMERATED, never typed.  The first version of this file named
# two subdirectories -- `controls` and `probes` -- and therefore could not see
# `selftapeout-adjudication-addendum/`, which holds a third copy of the registered
# predicate and a fourth drifted pair.  A hand-typed candidate list is the exact defect
# `controls_can_fail.py` was fixed for, committed again inside the instrument written to
# catch copies that disagree.  Everything under wt_jself matching the published-tree
# name is a published tree.
if "J102_PUB" in os.environ:
    PUB_ROOTS = [pathlib.Path(os.environ["J102_PUB"])]
else:
    PUB_ROOTS = sorted(
        d for d in (ROOT / "wt_jself").glob("selftapeout-adjudication*") if d.is_dir())

CITE = re.compile(r"`((?:meas|probes|controls)/[A-Za-z0-9_./-]+\.(?:py|sh))`")

rows = []          # (state, left, right, detail)
bad = set()        # deduplicated (left, right) of every non-AGREE pair


def emit(state, left, right, detail=""):
    """Record a pair.  The RED COUNT IS DEDUPLICATED, because the same pair is reached
    twice -- once via the citation and once via the name sweep -- and a headline that
    counts a pair twice is a summary contradicting its own rows, which is the defect
    J86 and J92 caught in this report and J96 caught inside an instrument."""
    rows.append((state, left, right, detail))
    if state not in ("AGREE", "NO-TWIN"):
        bad.add((left, right))


def pub_rel(p):
    """A path shown relative to whichever published tree it came from."""
    for r in PUB_ROOTS:
        try:
            return f"{r.name}/{p.relative_to(r)}" if len(PUB_ROOTS) > 1 \
                else str(p.relative_to(r))
        except ValueError:
            continue
    return str(p)


def twins_in_pub():
    """basename -> [paths] for everything runnable in EVERY published tree."""
    out = {}
    for r in PUB_ROOTS:
        for p in sorted(r.rglob("*")):
            if p.is_file() and p.suffix in (".py", ".sh"):
                out.setdefault(p.name, []).append(p)
    return out


def twins_in_meas():
    out = {}
    d = ROOT / "meas"
    if d.is_dir():
        for p in sorted(d.rglob("*")):
            if p.is_file() and p.suffix in (".py", ".sh"):
                out.setdefault(p.name, []).append(p)
    return out


pub = twins_in_pub()
meas = twins_in_meas()

print("=== arm 1+2: every instrument path CITED in RESULT.md ===")
cited = sorted(set(CITE.findall(DOC.read_text(errors="replace")))) if DOC.is_file() else []
if not cited:
    print("  no cited instrument paths found — the citation regex matched nothing.")
    print("  That is a broken instrument, not a clean report.")
    sys.exit(2)
for c in cited:
    # The report cites in TWO namespaces: `meas/...` is relative to ROOT, and
    # `controls/...` / `probes/...` is relative to a published tree.  The first version
    # resolved everything against ROOT and reported its own citation as CITED-MISSING --
    # an instrument reddening on a path that is perfectly fine, which is the false alarm
    # this whole finding is about.
    cands = [ROOT / c] + [r / c for r in PUB_ROOTS]
    src = next((x for x in cands if x.is_file()), None)
    if src is None:
        emit("CITED-MISSING", c, "-",
             "resolves under neither the private root nor any published tree")
        continue
    for t in pub.get(pathlib.Path(c).name, []):
        rel = pub_rel(t)
        if src.read_bytes() == t.read_bytes():
            emit("AGREE", c, str(rel))
        else:
            emit("DRIFTED", c, str(rel),
                 f"{len(src.read_bytes())} B vs {len(t.read_bytes())} B")
    if pathlib.Path(c).name not in pub:
        emit("NO-TWIN", c, "-", "cited copy only; nothing to disagree with")

print(f"  {len(cited)} cited path(s) checked")

print("\n=== arm 3: every instrument in the published tree, twin found by NAME ===")
checked = 0
for name, paths in sorted(pub.items()):
    for t in paths:
        for m in meas.get(name, []):
            checked += 1
            rel = pub_rel(t)
            if t.read_bytes() == m.read_bytes():
                emit("AGREE", str(m.relative_to(ROOT)), str(rel))
            else:
                emit("DRIFTED", str(m.relative_to(ROOT)), str(rel),
                     f"{len(m.read_bytes())} B vs {len(t.read_bytes())} B")
print(f"  {checked} name-matched pair(s) checked")

print("\n=== every pair, deduplicated ===")
seen = set()
for state, left, right, detail in rows:
    key = (left, right)
    if key in seen:
        continue
    seen.add(key)
    if state == "AGREE":
        continue
    print(f"  {state:<14} {left:<48} {right:<28} {detail}")
print(f"  ({len(set((l, r) for s, l, r, _ in rows if s == 'AGREE'))} AGREE pair(s) not listed)")

print()
if bad:
    print(f"{len(bad)} instrument pair(s) DRIFTED or MISSING (deduplicated).")
    print("Two copies of one instrument that disagree mean the report cites a file whose")
    print("output nobody has checked.  Reconcile them, or say beside the citation which")
    print("copy the sentence was measured with.")
    sys.exit(1)
print("Every cited instrument exists, and every instrument that lives in two places is")
print("byte-identical in both.  A reader following a citation runs what I ran.")
sys.exit(0)
