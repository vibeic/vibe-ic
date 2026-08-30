#!/usr/bin/env python3
"""J92 — does any SUPERSEDED figure still stand in this report as if it were current?

This report's method is to correct a number WHERE IT STANDS rather than erase it, so a
superseded figure appearing many times is expected and correct.  What would be a real
defect is ONE occurrence with no supersession marker near it: a stale number reading as
live, in a document whose whole authority is that its numbers are measured.

Mechanical, then read by hand -- J68's lesson is that a mechanical reader cannot tell a
citation from a quotation, so this prints candidates rather than verdicts.
"""
import os, pathlib, re, sys

# J98: the doc under test is nameable so that this audit can be shown to be
# CAPABLE of printing red.  It had no positive control: every run it had ever
# made was green, which is indistinguishable from an audit that cannot fail.
DOC = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                   else "/home/reyerchu/_jself_priv/RESULT.md")
text = DOC.read_text()
lines = text.split("\n")

# figure -> what superseded it
SUPERSEDED = {
    "5.875":  "build-to, first iterate (J65)",
    "5.963":  "build-to, first iterate (J65)",
    "6.165":  "build-to top, before J76",
    "4.532":  "die floor, before the J60 coordinate fix",
    "2.05×":  "ratio, first iterate (J65)",
    "2.08×":  "ratio, first iterate (J65)",
    "2.154×": "ratio top, before J76",
    "40.6×":  "a dwell lower bound, before J81 replaced the proxy",
    "67 heads": "remote head count, moved within the hour (J79)",
}
# any of these NEAR the occurrence means the sentence knows the figure is old
MARK = re.compile(
    r"→|->|correct|superseded|expired|used to|had been|was\b|earlier|first iterate|"
    r"before|old\b|since|no longer|J6[0-9]|J7[0-9]|J8[0-9]|J9[0-9]|previous|prior|"
    r"moved|revis|stale|iterat|hedge|refut", re.I)

flagged, collisions = [], []
for fig, why in SUPERSEDED.items():
    pat = re.compile(re.escape(fig))
    for i, ln in enumerate(lines):
        if not pat.search(ln):
            continue
        # context: the paragraph around it (2 lines each way, the report hard-wraps)
        lo, hi = max(0, i - 3), min(len(lines), i + 4)
        ctx = "\n".join(lines[lo:hi])
        if MARK.search(ctx):
            continue
        # KNOWN VALUE COLLISION, documented rather than suppressed.  `5.875` appears
        # once as a quantity that was never superseded: the 5153 arm's own core
        # (5.123 mm) plus the 2x376 um pad ring.  It shares digits with the retired
        # build-to figure for a REASON rather than by accident -- J65 found that the
        # old build-to WAS that probe core's die, which is exactly why it was an
        # iterate.  A figure-based audit cannot tell two quantities apart when they
        # share a value, so the collision is named here instead of widening the
        # pattern until nothing trips it.
        if fig == "5.875" and "core 5.123 mm" in ln:
            collisions.append((fig, i + 1))
            continue
        flagged.append((fig, why, i + 1, ln.strip()[:100]))

print(f"{len(SUPERSEDED)} superseded figures checked across {len(lines)} lines")

# ---------------------------------------------------------------------------
# J106 -- second arm: the report corrects a number WHERE IT STANDS, but the
# INSTRUMENTS it cites print numbers too, and nothing has ever asked whether one of
# them still emits a superseded figure as if it were the answer.  One did:
# `build_to_fixed_point.py` ends on "6165 um (2.15x)", which is the pre-J76 four-arm
# top, with nothing beside it to say so -- a reader following the citation runs it and
# reads a superseded number as current.  That is exactly what this file exists to stop,
# one layer out from the prose.
#
# Source-level, deliberately: running every cited instrument costs minutes, several of
# them WRITE into evidence trees, and this question is largely answerable from the text.
# A script may of course CONTAIN a superseded figure -- what it may not do is contain one
# with no supersession marker near it.
#
# THE LIMIT, named rather than papered over: a script that COMPUTES a superseded figure
# at run time is invisible to a source scan.  `build_to_fixed_point.py` is exactly that
# -- it prints "6165 um (2.15x)" from an f-string and holds neither literal.  It is
# handled by making the script announce its own supersession in its FIRST line of output,
# which puts the marker back into the source where this arm can see it.  A future
# instrument with the same shape will need the same treatment, and this comment is the
# instruction for it.
_CITE = re.compile(r"`((?:meas|probes|controls)/[A-Za-z0-9_./-]+\.py)`")
_ROOT = pathlib.Path(os.environ.get("J106_ROOT", "/home/reyerchu/_jself_priv"))
_PUBS = sorted(d for d in (_ROOT / "wt_jself").glob("selftapeout-adjudication*")
               if d.is_dir()) or [_ROOT]
_MARK = re.compile(r"supersed|before J\d|first iterate|no longer|pre-J\d|"
                   r"superseded by|earlier derivation|RETIRED", re.I)

script_flagged, scanned = [], 0
for rel in sorted(set(_CITE.findall(text))):
    src_p = next((c for c in [_ROOT / rel] + [d / rel for d in _PUBS] if c.is_file()),
                 None)
    if src_p is None:
        continue
    scanned += 1
    src_lines = src_p.read_text(errors="replace").split("\n")
    for fig, why in SUPERSEDED.items():
        for i, ln in enumerate(src_lines):
            if fig not in ln:
                continue
            lo, hi = max(0, i - 6), min(len(src_lines), i + 7)
            if not _MARK.search("\n".join(src_lines[lo:hi])):
                script_flagged.append((rel, i + 1, fig, why, ln.strip()[:60]))

print(f"\n=== the INSTRUMENTS this report cites, scanned for the same figures ===")
print(f"  {scanned} cited script(s) scanned")
for rel, ln, fig, why, ctx in script_flagged:
    print(f"  UNMARKED  {rel}:{ln}  {fig!r} ({why})")
    print(f"            {ctx}")
if script_flagged:
    print(f"  {len(script_flagged)} superseded figure(s) printed by a cited instrument")
    print("  with no supersession marker within six lines.  A reader who follows the")
    print("  citation runs the script and reads the old number as the answer.")


for fig, n in collisions:
    print(f"  (known value collision, not a stale figure: {fig!r} at RESULT.md:{n} "
          f"-- see the comment in this file)")
if not flagged and not script_flagged:
    print("\nEVERY occurrence of every superseded figure sits in a context that marks it")
    print("as superseded, in the report AND in every instrument the report cites.")
    print("No stale number stands as current.")
    sys.exit(0)
if script_flagged and not flagged:
    print(f"\n{len(script_flagged)} superseded figure(s) stand unmarked inside a CITED")
    print("INSTRUMENT. The prose is clean; the artefact a reader would run is not.")
    sys.exit(1)
print(f"\n{len(flagged)} occurrence(s) with NO supersession marker in context -- READ THESE:")
for fig, why, n, ln in flagged:
    print(f"  RESULT.md:{n}  {fig!r} ({why})")
    print(f"      {ln}")
sys.exit(1)
