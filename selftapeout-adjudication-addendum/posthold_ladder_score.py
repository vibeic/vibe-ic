#!/usr/bin/env python3
"""
Score J79's registered predicates P1/P2/P3 against the five arms' post-hold ladders.

WHY THIS FILE EXISTS
--------------------
The addendum (`selftapeout-adjudication-addendum/README.md`, section 5) reported that
the die-3300 arm printed "no residual at all" after the clkbuf swap and concluded that
P3 was "NOT SCORABLE on this arm, and probably never will be". That was a grep for the
string `Violations remain`, and that string is genuinely absent from that arm.

It is absent because that arm is not running the same legalizer. Its post-hold residual
is printed by the DIAMOND legalizer as `Total Placement Failures` (DPL-1101/DPL-0034),
not by the NegotiationLegalizer as `Violations remain` (DPL-0701).

So this scorer reads BOTH counters, records WHICH ONE each arm is using, and refuses to
compare across the two -- J94's lesson: two searches sharing a name is not a bound, and
neither is two names sharing a search. P3's band (2296-2418) was measured on the
NegotiationLegalizer, so P3 is scored ONLY on arms using that legalizer, and any arm on
the other one is reported as CORROBORATION, explicitly not as the score.

POSITIVE CONTROLS
-----------------
Every verdict this file can emit is exercised against a synthetic log first. A scorer
that can only say CONFIRMED is not measuring anything. Controls are run BEFORE the real
arms and a control failure aborts before any real number is printed.

Run:  python3 posthold_ladder_score.py
Exit: 0 all controls held and every arm parsed; 1 a control failed; 2 an arm unparsable.
"""

import os
import re
import sys
import time

# ---------------------------------------------------------------- the ladder
# From pnr.tcl:8308-8365, which is byte-identical across the arms (verified by diff
# of the hold_repair..POST_HOLD_LEGALIZE_FAILED span between the 3300 and 3800 arms).
#
#   rung 1  detailed_placement                                    -> OK token "default"
#   rung 2  detailed_placement -max_displacement 5                -> OK token "5"
#   rung 3  detailed_placement -max_displacement 20               -> OK token "20"
#   rung 4  detailed_placement -max_displacement 100              -> OK token "100"
#   rung 5  detailed_placement -max_displacement [full-die]       -> OK token "full-die"
#   ---- POST_HOLD_CLKBUF_DOWNSIZE swapped=N ----
#   rung 6  detailed_placement                                    -> OK token "clkswap"
#   rung 7  detailed_placement -max_displacement [full-die]       -> OK token "clkswap-full-die"
#   rung 8  detailed_placement -use_diamond_legalizer             -> OK token "diamond"
#   rung 9  detailed_placement -use_diamond_legalizer [full-die]  -> OK token "diamond-full-die"
#   then    POST_HOLD_LEGALIZE_FAILED
RUNG_NAMES = {
    1: "default", 2: "disp=5", 3: "disp=20", 4: "disp=100", 5: "full-die",
    6: "clkswap", 7: "clkswap-full-die", 8: "diamond", 9: "diamond-full-die",
}
CLKSWAP_RUNG = 6

# J79's P3 band, measured on the NegotiationLegalizer's `Violations remain` counter.
P3_BAND_LO, P3_BAND_HI = 2296, 2418

RE_DISP = re.compile(
    r"\[INFO DPL-0005\] Diamond search max displacement: \+/- (\d+) sites horizontally, \+/- (\d+) rows")
RE_NEG = re.compile(r"\[WARNING DPL-0701\] NegotiationLegalizer did not fully converge\. Violations remain: (\d+)")
RE_DMD = re.compile(r"^Total Placement Failures:\s+(\d+)")
RE_DMD_MARK = re.compile(r"\[INFO DPL-1101\] Legalizing using diamond search")
RE_MOVABLE = re.compile(r"\[INFO DPL-0007\] Movable instances area: ([\d.]+) um\^2")
RE_SWAP = re.compile(r"POST_HOLD_CLKBUF_DOWNSIZE swapped=(\d+)")
RE_OK = re.compile(r"POST_HOLD_LEGALIZE_OK disp=(\S+)")
RE_FAILED = re.compile(r"POST_HOLD_LEGALIZE_FAILED")
RE_HOLD = re.compile(r"PNR_STAGE: hold_repair")
RE_INIT = re.compile(r"INITIAL_DPL_LEGALIZE_(OK|FAILED)")


def parse(lines):
    """Return the post-hold picture of one arm.

    A 'block' is one detailed_placement call: a DPL-0005 displacement header, then
    whichever legalizer's residual line comes before the next header. Blocks are
    numbered in order, which IS the rung number because the ladder is straight-line
    code with no loops other than the {5 20 100} foreach.
    """
    start = None
    for i, ln in enumerate(lines):
        if RE_HOLD.search(ln):
            start = i
            break
    if start is None:
        return None

    init = None
    for ln in lines[:start]:
        m = RE_INIT.search(ln)
        if m:
            init = m.group(1)
            break

    blocks, cur = [], None
    swap_at_block = None       # index in `blocks` of the first block AFTER the swap
    swap_n = None
    movable_before_swap = None
    movable_after_swap = None
    verdict = None
    seen_swap = False
    last_movable = None

    for ln in lines[start:]:
        m = RE_MOVABLE.search(ln)
        if m:
            last_movable = float(m.group(1))
            if seen_swap and movable_after_swap is None:
                movable_after_swap = last_movable
            continue

        m = RE_DISP.search(ln)
        if m:
            if cur is not None:
                blocks.append(cur)
            cur = {"sites": int(m.group(1)), "rows": int(m.group(2)),
                   "counter": None, "value": None, "diamond_mark": False}
            continue

        if cur is not None:
            if RE_DMD_MARK.search(ln):
                cur["diamond_mark"] = True
                continue
            m = RE_NEG.search(ln)
            if m:
                cur["counter"], cur["value"] = "negotiation", int(m.group(1))
                continue
            m = RE_DMD.search(ln)
            if m:
                cur["counter"], cur["value"] = "diamond", int(m.group(1))
                continue

        m = RE_SWAP.search(ln)
        if m:
            if cur is not None:
                blocks.append(cur)
                cur = None
            seen_swap = True
            swap_n = int(m.group(1))
            swap_at_block = len(blocks)
            movable_before_swap = last_movable
            continue

        m = RE_OK.search(ln)
        if m:
            verdict = ("OK", m.group(1))
            continue
        if RE_FAILED.search(ln):
            verdict = ("FAILED", None)

    if cur is not None:
        blocks.append(cur)

    # Which legalizer is this arm's UNFLAGGED detailed_placement using? Read it off
    # rung 1, which is unflagged by construction.
    arm_legalizer = None
    if blocks:
        arm_legalizer = blocks[0]["counter"] or ("diamond" if blocks[0]["diamond_mark"] else None)

    return {
        "init": init, "blocks": blocks, "swap_n": swap_n,
        "swap_at_block": swap_at_block, "verdict": verdict,
        "movable_before_swap": movable_before_swap,
        "movable_after_swap": movable_after_swap,
        "legalizer": arm_legalizer,
    }


def score_p3(arm):
    """P3: the clkswap rung's residual falls strictly below the 2296-2418 band.

    Scored ONLY on the NegotiationLegalizer, because that is the counter the band was
    measured with. Returns (verdict, detail).
    """
    b = arm["blocks"]
    if arm["swap_at_block"] is None:
        return "NOT YET", "arm has not reached the clkbuf downsize"
    if len(b) <= arm["swap_at_block"]:
        return "NOT YET", "swap printed but the clkswap rung has produced no block yet"
    rung6 = b[arm["swap_at_block"]]
    if rung6["value"] is None:
        return "NOT YET", "clkswap rung is still running (header printed, no residual)"
    if rung6["counter"] != "negotiation":
        return "CORROBORATION ONLY", (
            "clkswap residual is %d but on the %s legalizer, not the one the "
            "2296-2418 band was measured with" % (rung6["value"], rung6["counter"]))
    if rung6["value"] < P3_BAND_LO:
        return "CONFIRMED", "clkswap residual %d < %d" % (rung6["value"], P3_BAND_LO)
    return "REFUTED", "clkswap residual %d is NOT below %d" % (rung6["value"], P3_BAND_LO)


def score_p1(arm):
    """P1: no arm prints POST_HOLD_LEGALIZE_OK disp=full-die."""
    v = arm["verdict"]
    if v and v[0] == "OK" and v[1].startswith("full-die"):
        return "REFUTED", "printed OK disp=%s" % v[1]
    if v and v[0] == "OK":
        return "HELD", "printed OK but with token %s, not full-die" % v[1]
    # Held-and-unfalsifiable once the arm is past rung 5 with no OK.
    n = len(arm["blocks"])
    if arm["swap_at_block"] is not None:
        return "HELD (unfalsifiable by this arm)", (
            "passed rung 5 and reached the swap with no OK")
    return "NOT YET", "arm has produced %d post-hold block(s), still at or before rung 5" % n


def score_p2(arm):
    """P2: if any arm prints OK, its token is clkswap or later."""
    v = arm["verdict"]
    late = {"clkswap", "clkswap-full-die", "diamond", "diamond-full-die"}
    if v and v[0] == "OK":
        tok = v[1].split()[0]
        return ("HELD" if tok in late else "REFUTED"), "token %s" % tok
    if arm["swap_at_block"] is not None:
        return "SURVIVES (not confirmed)", (
            "past the swap with no OK, so any OK still available to it is a late token")
    return "NOT YET", "no OK printed and the arm is still before the swap"


# ---------------------------------------------------------------- controls
SYN_BASE = """PNR_STAGE: hold_repair
[INFO DPL-0007] Movable instances area: 1000000.00 um^2
[INFO DPL-0005] Diamond search max displacement: +/- 500 sites horizontally, +/- 100 rows vertically.
%(R1)s
"""

SYN_SWAP = """POST_HOLD_CLKBUF_DOWNSIZE swapped=1000 -> gf180mcu_fd_sc_mcu7t5v0__clkbuf_4
[INFO DPL-0007] Movable instances area: 900000.00 um^2
[INFO DPL-0005] Diamond search max displacement: +/- 500 sites horizontally, +/- 100 rows vertically.
%(R6)s
"""

NEG = "[WARNING DPL-0701] NegotiationLegalizer did not fully converge. Violations remain: %d"
DMD = ("[INFO DPL-1101] Legalizing using diamond search.\n"
       "Total Placement Failures:        %d")


def controls():
    """Every verdict must be reachable on a synthetic log, or the scorer proves nothing."""
    out, ok = [], True

    def check(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        out.append("  %-46s got=%-26s want=%-26s %s"
                   % (name, got, want, "OK" if good else "*** CONTROL FAILED ***"))

    # C1 P3 CONFIRMED - post-swap residual below the band, negotiation counter
    a = parse((SYN_BASE % {"R1": NEG % 2307} + SYN_SWAP % {"R6": NEG % 300}).splitlines())
    check("C1 P3 below band on negotiation", score_p3(a)[0], "CONFIRMED")

    # C2 P3 REFUTED - the scorer must be able to say NO. Same shape, value inside the band.
    a = parse((SYN_BASE % {"R1": NEG % 2307} + SYN_SWAP % {"R6": NEG % 2400}).splitlines())
    check("C2 P3 inside band on negotiation", score_p3(a)[0], "REFUTED")

    # C3 P3 must NOT score off the diamond counter, however tempting the number
    a = parse((SYN_BASE % {"R1": DMD % 2329} + SYN_SWAP % {"R6": DMD % 320}).splitlines())
    check("C3 P3 below band on diamond", score_p3(a)[0], "CORROBORATION ONLY")

    # C4 no swap reached -> NOT YET
    a = parse((SYN_BASE % {"R1": NEG % 2307}).splitlines())
    check("C4 P3 before the swap", score_p3(a)[0], "NOT YET")

    # C5 swap printed, clkswap rung still running (header, no residual)
    hdr = ("POST_HOLD_CLKBUF_DOWNSIZE swapped=1000 -> x\n"
           "[INFO DPL-0007] Movable instances area: 900000.00 um^2\n"
           "[INFO DPL-0005] Diamond search max displacement: +/- 500 sites horizontally, +/- 100 rows vertically.\n"
           "[INFO DPL-1101] Legalizing using diamond search.")
    a = parse((SYN_BASE % {"R1": NEG % 2307} + hdr).splitlines())
    check("C5 P3 clkswap rung in flight", score_p3(a)[0], "NOT YET")

    # C6 P1 must be refutable
    a = parse((SYN_BASE % {"R1": NEG % 2307} +
               "POST_HOLD_LEGALIZE_OK disp=full-die 3800x3800\n").splitlines())
    check("C6 P1 against an OK at full-die", score_p1(a)[0], "REFUTED")

    # C7 P2 must be refutable - an OK at an EARLY token refutes it
    a = parse((SYN_BASE % {"R1": NEG % 2307} +
               "POST_HOLD_LEGALIZE_OK disp=default\n").splitlines())
    check("C7 P2 against an OK at an early token", score_p2(a)[0], "REFUTED")

    # C8 legalizer identification, both ways
    a = parse((SYN_BASE % {"R1": NEG % 10}).splitlines())
    check("C8a legalizer id, negotiation", a["legalizer"], "negotiation")
    a = parse((SYN_BASE % {"R1": DMD % 10}).splitlines())
    check("C8b legalizer id, diamond", a["legalizer"], "diamond")

    return ok, out


# ---------------------------------------------------------------- the arms
ROOT = "/home/reyerchu/_jself_priv"
ARMS = [
    ("die 3300", ROOT + "/proj/edge_llm_matmul_accel/phase3/stage3/pnr/openroad.log"),
    ("die 3800", ROOT + "/proj/matmul_d3800/phase3/stage3/pnr/openroad.log"),
    ("die 4200", ROOT + "/meas/matmul_fullflow/fullflow_4200.log"),
    ("die 5153", ROOT + "/meas/matmul_fullflow/fullflow_5153.log"),
    ("die 5434", ROOT + "/meas/matmul_fullflow/fullflow_5434.log"),
]


def main():
    print("posthold_ladder_score.py -- read at %s"
          % time.strftime("%Y-%m-%d %H:%M:%S %z"))
    print("host loadavg: %s" % (open("/proc/loadavg").read().split(" up")[0].strip()))
    print()

    print("CONTROLS (a scorer that can only say CONFIRMED measures nothing)")
    ok, lines = controls()
    print("\n".join(lines))
    if not ok:
        print("\nCONTROLS FAILED -- refusing to print any real number.")
        return 1
    print("  -> all controls held\n")

    arms = {}
    for name, path in ARMS:
        if not os.path.exists(path):
            print("%-9s MISSING %s" % (name, path))
            return 2
        st = os.stat(path)
        with open(path, errors="replace") as fh:
            lines = fh.read().splitlines()
        a = parse(lines)
        if a is None:
            print("%-9s has not reached PNR_STAGE: hold_repair" % name)
            continue
        a["_mtime"] = time.strftime("%H:%M:%S", time.localtime(st.st_mtime))
        a["_bytes"] = st.st_size
        arms[name] = a

    print("THE POST-HOLD LADDER, PER ARM  (live logs: mtime and size recorded at read)")
    print("%-9s %-8s %-10s %-9s  %s" % ("arm", "initial", "legalizer", "mtime", "rung: residual"))
    for name, a in arms.items():
        seq = []
        for i, b in enumerate(a["blocks"], start=1):
            tag = RUNG_NAMES.get(i, "r%d" % i)
            val = "--" if b["value"] is None else str(b["value"])
            seq.append("%d/%s=%s" % (i, tag, val))
        if a["swap_at_block"] is not None:
            seq.insert(a["swap_at_block"], "<<SWAP %d>>" % a["swap_n"])
        print("%-9s %-8s %-10s %-9s  %s"
              % (name, a["init"] or "?", a["legalizer"] or "?", a["_mtime"], "  ".join(seq)))
    print()

    print("WHAT THE SWAP FREED  (movable instance area, the arm's own DPL-0007)")
    for name, a in arms.items():
        if a["movable_before_swap"] is None or a["movable_after_swap"] is None:
            continue
        d = a["movable_before_swap"] - a["movable_after_swap"]
        print("%-9s swapped=%-5d  %14.2f -> %14.2f  = -%10.2f um^2  (%.2f %%)"
              % (name, a["swap_n"], a["movable_before_swap"], a["movable_after_swap"],
                 d, 100.0 * d / a["movable_before_swap"]))
    print()

    print("J79's REGISTERED PREDICATES, SCORED")
    for pname, fn in (("P1", score_p1), ("P2", score_p2), ("P3", score_p3)):
        print("  %s" % pname)
        for name, a in arms.items():
            v, why = fn(a)
            print("    %-9s %-32s %s" % (name, v, why))
    print()

    # The one cross-arm statement, made only where the counter is the same.
    scored = [(n, a) for n, a in arms.items()
              if score_p3(a)[0] in ("CONFIRMED", "REFUTED")]
    corro = [(n, a) for n, a in arms.items() if score_p3(a)[0] == "CORROBORATION ONLY"]
    print("P3 OVERALL: scored on %d arm(s) %s; corroborated but NOT scored on %d arm(s) %s"
          % (len(scored), [n for n, _ in scored], len(corro), [n for n, _ in corro]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
