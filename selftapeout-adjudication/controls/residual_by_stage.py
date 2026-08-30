#!/usr/bin/env python3
"""J100 — attribute every legalizer residual to the PnR STAGE it was printed in.

J99 read a flat list of `Total Placement Failures:` values off the die-3300 arm and
the list did not end where the report said it did: after the nine-rung post-hold
ladder terminates at 274, four MORE values follow.  A flat list cannot say whether
those belong to the ladder (which would contradict "all nine rungs spent") or to the
stages after it (which would be a different fact entirely).  So do not read a flat
list.  Segment the log by its own `PNR_STAGE:` markers and attribute each residual to
the stage it was printed inside.

The distinction this makes is load-bearing: "the residual is stuck at 274" and "the
residual GROWS to 308 once the downstream stages start inserting cells" are different
claims, and only the second one is true.

CONTROL, and it is the reason this is a control and not a reporter: the segmentation
is only meaningful if the markers are there.  Run against a log with its `PNR_STAGE:`
lines stripped, every residual lands in one bucket and the program must REFUSE rather
than report a single stage confidently.  `--self-test` does exactly that and requires
the refusal.

chip-AGNOSTIC: `PNR_STAGE:` and the legalizers' own counter strings.  No chip, PDK,
cell or die literal.
"""
import re
import sys

STAGE = re.compile(r"^PNR_STAGE:\s*(\S+)")
VERDICT = re.compile(r"^(POST_HOLD_LEGALIZE_\w+|INITIAL_DPL_LEGALIZE_\w+)")
# the two legalizers keep separate counters; NEVER compare across them (J96)
COUNTERS = (("diamond", re.compile(r"Total Placement Failures:\s+(\d+)")),
            ("negotiation", re.compile(r"Violations remain: (\d+)")))


def segment(lines):
    """[(stage, kind, value_or_verdict)] in file order."""
    stage, out = "(before first PNR_STAGE)", []
    for line in lines:
        m = STAGE.match(line.strip())
        if m:
            stage = m.group(1)
            continue
        v = VERDICT.match(line.strip())
        if v:
            out.append((stage, "verdict", v.group(1)))
            continue
        for kind, rx in COUNTERS:
            m = rx.search(line)
            if m:
                out.append((stage, kind, int(m.group(1))))
                break
    return out


def report(path, lines):
    events = segment(lines)
    stages = []
    for stage, kind, val in events:
        if not stages or stages[-1][0] != stage:
            stages.append((stage, []))
        stages[-1][1].append((kind, val))

    print(f"{path}")
    n_stages = len({s for s, _ in stages})
    print(f"  {len(events)} residual/verdict event(s) across {n_stages} stage(s)\n")
    mixed = 0
    for stage, evs in stages:
        counters = sorted({k for k, _ in evs if k != "verdict"})
        verd = [v for k, v in evs if k == "verdict"]
        if not counters:
            print(f"  {stage:<34} [{'-':<11}] (verdict only)"
                  + (f"   {verd}" if verd else ""))
            continue
        # A stage may run BOTH legalizers -- the die-3800 arm's post-hold ladder does,
        # switching to diamond at rung 8.  Chaining those into one arrow sequence is
        # exactly the cross-counter comparison this file exists to prevent (J96), so
        # each counter gets its OWN line and the stage is flagged.
        if len(counters) > 1:
            mixed += 1
        for i, k in enumerate(counters):
            vals = " -> ".join(str(v) for kk, v in evs if kk == k)
            label = stage if i == 0 else ""
            note = "  <- MIXED: do NOT chain across these lines" if (
                len(counters) > 1 and i == 0) else ""
            print(f"  {label:<34} [{k:<11}] {vals}"
                  + (f"   {verd}" if (verd and i == len(counters) - 1) else "") + note)
    if mixed:
        print(f"\n  {mixed} stage(s) ran BOTH legalizers; their values are split above "
              f"and must not be read as one sequence.")
    if n_stages <= 1 and len(events) > 1:
        print("\nREFUSED: every event fell in ONE bucket, so this log carries no usable "
              "`PNR_STAGE:` segmentation and the attribution above is not evidence.")
        return 2
    print("\nEach row is ONE stage. Values within a row share a counter; values in "
          "different rows may not.")
    return 0


def self_test():
    """Strip the markers and require the refusal."""
    src = open(sys.argv[2], errors="replace").read().splitlines()
    stripped = [l for l in src if not STAGE.match(l.strip())]
    print("=== SELF-TEST: same log, `PNR_STAGE:` lines removed — expect REFUSED ===")
    rc = report("(markers stripped)", stripped)
    if rc != 2:
        print("*** CONTROL FAILED: it did not refuse an unsegmentable log.")
        return 1
    print("\nCONTROL OK: it refuses when the segmentation it depends on is absent.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: residual_by_stage.py <openroad.log> [more...]\n"
                         "       residual_by_stage.py --self-test <openroad.log>")
    if sys.argv[1] == "--self-test":
        sys.exit(self_test())
    rc = 0
    for p in sys.argv[1:]:
        rc |= report(p, open(p, errors="replace").read().splitlines())
        print()
    sys.exit(rc)
