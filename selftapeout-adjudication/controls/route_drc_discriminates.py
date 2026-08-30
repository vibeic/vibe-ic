#!/usr/bin/env python3
"""J101 — does the runner's route-convergence gate DISCRIMINATE, or does it only ever
say `NOT DETERMINED`?

The die-3300 arm's runner printed:

    [pnr] ROUTE_DRC NEITHER: route__drc_errors: NOT DETERMINED -- neither the tool's
          metrics nor its log carried this number. That is not a reading of zero.

Quoted alone that is worth nothing.  A gate with one output is indistinguishable from
a gate that cannot reach any other, and "it refuses to fabricate a zero" is only a
finding if it is capable of NOT refusing.

So the check is a COMPARISON, not a read: take the state off each arm's runner log
and require that the two arms produce DIFFERENT states.  Identical states -> the
instrument is not separating them and this file says so and exits 1.

The second half asks WHY they differ, from the arms' own PnR logs rather than from
the runner's summary of them: the count of routing-violation lines there.  A gate
saying NOT DETERMINED over a log with thousands of them would be a gate that is
simply broken.

chip-AGNOSTIC: the runner's own marker and OpenROAD's own message codes.
"""
import re
import subprocess
import sys

STATE = re.compile(r"\[pnr\] ROUTE_DRC (\w+):\s*(.*)")
# OpenROAD's own routing-residual lines.  DRT-0199 is the per-iteration violation
# count; the prose form is what the runner's fallback parser reads.
RESIDUAL = re.compile(r"Completing.*with .* violation|DRT-0199")


def state_of(runner_log):
    try:
        with open(runner_log, errors="replace") as f:
            hits = [STATE.search(l) for l in f]
    except OSError:
        return None, f"(runner log unreadable: {runner_log})"
    hits = [h for h in hits if h]
    if not hits:
        return "NO_LINE", "the runner printed no ROUTE_DRC line at all"
    return hits[-1].group(1), hits[-1].group(2).strip()


def residuals(pnr_log):
    try:
        n = 0
        with open(pnr_log, errors="replace") as f:
            for line in f:
                if RESIDUAL.search(line):
                    n += 1
        return n
    except OSError:
        return None


def main(argv):
    if len(argv) != 5:
        raise SystemExit("usage: route_drc_discriminates.py "
                         "<armA_runner.log> <armA_pnr.log> "
                         "<armB_runner.log> <armB_pnr.log>")
    arms = [(argv[1], argv[2]), (argv[3], argv[4])]
    seen = []
    for runner, pnr in arms:
        st, detail = state_of(runner)
        n = residuals(pnr)
        seen.append(st)
        print(f"  {runner}")
        print(f"    ROUTE_DRC state      : {st}")
        print(f"    detail               : {detail[:150]}")
        print(f"    routing-residual lines in its PnR log: "
              f"{'unreadable' if n is None else n}")
        print()

    if any(s is None for s in seen):
        print("INCONCLUSIVE: an arm's runner log could not be read.")
        return 2
    if seen[0] == seen[1]:
        print(f"NOT DISCRIMINATING: both arms report `{seen[0]}`, so this gate is not "
              f"separating them and its refusal on either is not evidence.")
        return 1
    print(f"DISCRIMINATES: the two arms report DIFFERENT states, `{seen[0]}` and "
          f"`{seen[1]}` — so `NOT DETERMINED` is a reading this gate ARRIVED at, not "
          f"the only thing it can say.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
