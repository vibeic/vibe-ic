#!/usr/bin/env python3
"""Does the clkbuf downsize move the published build-to die? Measured, then declined.

Two arms have now run the POST_HOLD_CLKBUF_DOWNSIZE rung and printed the movable area
on both sides of it. That is the first time this report has had a measured post-swap
area, and it raises a fair question about a number it publishes:

    the build-to die (6.139-6.171 mm) is sized from each arm's post-hold movable area.
    The swap makes that area 2.7 % SMALLER. Why has the die not come down?

This file answers it with the arithmetic rather than with a sentence, and then says
why the smaller number is NOT the one to publish.

CONTROL FIRST: the fixed-point rule is re-implemented here, and it must reproduce
meas/_fixedpoint/build_to_fixed_point.py's published 6138.9 / 6164.9 um to 0.1 um
before any counterfactual is printed. A rule that cannot reproduce the number it is
about to revise is not the same rule.

Run:  python3 downsize_die_sensitivity.py
Exit: 0 control held; 1 control failed.
"""

import math
import sys

# ---- constants, identical to meas/_fixedpoint/build_to_fixed_point.py -------
UTIL = 0.25       # phase3_one_shot_runner.py  _AUTO_DIE_TARGET_UTIL
RING2 = 752.0     # 2 * (350 um pad-ring depth + 26 um PAD_EDGE_SPACING)
PADFLR = 2862.0   # die_edge_min(111 pads)

# die: (core_area, movable_initial, fixed_initial, movable_posthold, fixed_posthold)
ARMS = {
    3300: (10677204.74, 5674818.11,  427172.75, 6035072.38,  525609.91),
    3800: (14201741.03, 5683500.12,  568754.37, 6054418.68,  667191.53),
    4200: (17375223.13, 5634457.16,  694464.69, 5995578.53,  792901.85),
    5153: (26226686.62, 5656393.79, 1048172.88, 6035684.84, 1146610.04),
}

# The two arms that have RUN the downsize, from their own DPL-0007 lines either side
# of POST_HOLD_CLKBUF_DOWNSIZE. Not modelled, not extrapolated -- read off the logs.
SWAP_MEASURED = {
    3300: (6035072.38, 5871407.05, 2098),
    3800: (6054418.68, 5891043.11, 2089),
}

f = sum(fi / c for c, _, fi, _, _ in
        ((v[0], v[1], v[2], v[3], v[4]) for v in ARMS.values())) / len(ARMS)
S = sum(fp - fi for _, _, fi, _, fp in
        ((v[0], v[1], v[2], v[3], v[4]) for v in ARMS.values())) / len(ARMS)


def fixed_point(M):
    """A* = (M + f*A* + S)/UTIL, solved."""
    A = 4.0 * (M + S) / (1.0 - f / UTIL)
    core = math.sqrt(A)
    return A, core, core + RING2


def main():
    MV = [v[3] for v in ARMS.values()]
    M_lo, M_hi = min(MV), max(MV)

    print("=== CONTROL: reproduce the published fixed point ===")
    lo_die = fixed_point(M_lo)[2]
    hi_die = fixed_point(M_hi)[2]
    print("  f = %.6f   S = %.2f um2" % (f, S))
    print("  movable low  %10.2f -> DIE %7.1f um   (published 6138.9)" % (M_lo, lo_die))
    print("  movable high %10.2f -> DIE %7.1f um   (published 6164.9)" % (M_hi, hi_die))
    ok = abs(lo_die - 6138.9) < 0.1 and abs(hi_die - 6164.9) < 0.1
    print("  -> %s\n" % ("CONTROL HELD" if ok else "*** CONTROL FAILED ***"))
    if not ok:
        return 1

    print("=== WHAT THE SWAP ACTUALLY FREED, on the two arms that ran it ===")
    deltas = []
    for d, (pre, post, n) in sorted(SWAP_MEASURED.items()):
        dd = pre - post
        deltas.append(dd)
        print("  die %-5d swapped=%-5d  %12.2f -> %12.2f  = -%9.2f um2  (-%.3f %%)"
              % (d, n, pre, post, dd, 100.0 * dd / pre))
    dmean = sum(deltas) / len(deltas)
    print("  the two agree to %.2f um2 (%.3f %% of the reduction)\n"
          % (max(deltas) - min(deltas),
             100.0 * (max(deltas) - min(deltas)) / dmean))

    print("=== THE COUNTERFACTUAL: size the die from the POST-swap area instead ===")
    print("  %-14s %-12s %-12s %-9s %-9s %s"
          % ("", "M pre-swap", "M post-swap", "DIE pre", "DIE post", "change"))
    for lbl, M in (("movable low ", M_lo), ("movable high", M_hi)):
        d_pre = fixed_point(M)[2]
        d_post = fixed_point(M - dmean)[2]
        print("  %-14s %12.2f %12.2f %9.1f %9.1f  %+.1f um (%+.3f %%)"
              % (lbl, M, M - dmean, d_pre, d_post, d_post - d_pre,
                 100.0 * (d_post - d_pre) / d_pre))
    band_pre = (fixed_point(M_lo)[2], fixed_point(M_hi)[2])
    band_post = (fixed_point(M_lo - dmean)[2], fixed_point(M_hi - dmean)[2])
    print("\n  published band  %.3f - %.3f mm   (%.3fx - %.3fx the pad floor)"
          % (band_pre[0] / 1000, band_pre[1] / 1000,
             band_pre[0] / PADFLR, band_pre[1] / PADFLR))
    print("  counterfactual  %.3f - %.3f mm   (%.3fx - %.3fx)"
          % (band_post[0] / 1000, band_post[1] / 1000,
             band_post[0] / PADFLR, band_post[1] / PADFLR))
    print("  the whole effect is %.1f um on a %.0f um die = %.2f %%"
          % (band_pre[0] - band_post[0], band_pre[0],
             100.0 * (band_pre[0] - band_post[0]) / band_pre[0]))

    print("""
=== AND WHY THE PUBLISHED NUMBER KEEPS THE PRE-SWAP AREA ===

  POST_HOLD_CLKBUF_DOWNSIZE is not an area optimisation. It is the ladder's
  LAST-RESORT LEGALISATION RESCUE: it reaches into a placed, CTS-ed, hold-repaired
  block and swaps every clkbuf wider than clkbuf_4 down to clkbuf_4 -- 2 089 and
  2 098 clock buffers on these two arms -- for no reason other than that the
  legaliser could not otherwise fit them.

  Sizing the die from what that leaves would be quoting a die that only holds the
  design AFTER its clock tree has been weakened to make it fit, and quoting it
  without the timing that weakening costs. No arm has re-timed after the swap; the
  ladder does not ask it to.

  So the build-to die stays sized from the design the flow actually intends to
  build -- clock tree as CTS sized it -- and the 2.7 %% the rescue frees is
  recorded here as the cost of the rescue rather than banked as a smaller chip.
  It is worth %.1f um of die edge, and it is not taken.

  The verdict does not move either way: %.3f mm and %.3f mm are both far above the
  2.862 mm pad floor, so `edge_llm_matmul_accel` is CORE-limited under either
  reading. That is the only thing the six rows turn on.""" % (
        band_pre[0] - band_post[0], band_post[0] / 1000, band_pre[0] / 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
