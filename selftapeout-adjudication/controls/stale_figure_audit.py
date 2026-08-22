#!/usr/bin/env python3
"""J92 — does any SUPERSEDED figure still stand in this report as if it were current?

This report's method is to correct a number WHERE IT STANDS rather than erase it, so a
superseded figure appearing many times is expected and correct.  What would be a real
defect is ONE occurrence with no supersession marker near it: a stale number reading as
live, in a document whose whole authority is that its numbers are measured.

Mechanical, then read by hand -- J68's lesson is that a mechanical reader cannot tell a
citation from a quotation, so this prints candidates rather than verdicts.
"""
import re, sys, pathlib

DOC = pathlib.Path("/home/reyerchu/_jself_priv/RESULT.md")
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
for fig, n in collisions:
    print(f"  (known value collision, not a stale figure: {fig!r} at RESULT.md:{n} "
          f"-- see the comment in this file)")
if not flagged:
    print("\nEVERY occurrence of every superseded figure sits in a context that marks it")
    print("as superseded. No stale number stands as current.")
    sys.exit(0)
print(f"\n{len(flagged)} occurrence(s) with NO supersession marker in context -- READ THESE:")
for fig, why, n, ln in flagged:
    print(f"  RESULT.md:{n}  {fig!r} ({why})")
    print(f"      {ln}")
sys.exit(1)
