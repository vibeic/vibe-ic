#!/usr/bin/env python3
"""J79 — a predicate for the POST-HOLD VERDICT, registered while no arm has printed one.

The report's one stated-open item is that no arm has printed `POST_HOLD_LEGALIZE_OK`
or `_FAILED`.  All five have been sitting on rung 5 (the full-die displacement rung)
for hours.  This file writes down what rung the answer will come from, and WHY, before
any of them answers -- so the rule cannot be shaped to the result.

THE LADDER (`pnr.tcl:8308-8364`), nine rungs:
  1 detailed_placement                      (default displacement)
  2 -max_displacement 5
  3 -max_displacement 20
  4 -max_displacement 100
  5 -max_displacement <full die>            <- where all five arms are now
  6 clkbuf downsize to clkbuf_4, then detailed_placement
  7 the same, full-die displacement
  8 -use_diamond_legalizer
  9 -use_diamond_legalizer, full-die

THE REASON, which is the part that can be wrong:
  Rungs 1-4 raise the displacement bound 5 -> 20 -> 100 sites, a 20x growth, and the
  residual moves by AT MOST 12 cells in ~2350 (die 3800: 2352 -> 2352 -> 2344 -> 2340;
  dies 4200 / 5153 / 5434: no change at all).  So DISPLACEMENT is not what binds --
  there is no legal site to displace to, at any radius.
  ^^^ THAT LAST SENTENCE IS REFUTED -- see J81.  It is left here UNEDITED because a
  predicate rewritten after its subject starts answering is not a predicate any more.
  At full-die radius there ARE legal sites: the die-4200 arm has recovered 255 of 2 296
  (11.1 %) inside rung 5 and taken its phase-2 illegal count to 2 035.  What the
  evidence supports is the weaker claim that 2 035 of 2 296 have no legal site anywhere
  on the whole die, bought at over ten hours of one core.  P1/P2/P3 themselves are
  claims about what the rung PRINTS and are untouched by this.  Rung 5 is the same algorithm
  with the bound removed, so it should not legalize either.
  What binds is AREA.  J53 measured the cause: CTS instantiated the ROOT clock-buffer
  master 2 055 times at 28.000 um against clkbuf_4's 7.840 um, which is 225 337 um^2 =
  82.3 % of everything CTS and hold repair added.  Rung 6 downsizes exactly those --
  2 089 matching instances, 163 376 um^2, ~60 % of the increase.  That is the first
  rung that changes the AREA rather than the search.

PREDICTIONS
  P1  No arm prints `POST_HOLD_LEGALIZE_OK disp=full-die`.            (sharp)
  P2  If any arm prints OK at all, the token is one of
      {clkswap, clkswap-full-die, diamond, diamond-full-die}.          (sharp)
  P3  At the clkswap rung the printed residual is STRICTLY BELOW the
      2296-2418 band rungs 1-5 have held at all four measured dies.    (directional,
      and the weakest of the three -- it assumes the residual tracks excess area,
      which is a hypothesis this report has NOT established.)

FALSIFIERS, so this is not unfalsifiable:
  P1 dies if any arm prints `disp=full-die`.  P2 dies with it.  P3 dies if a clkswap
  rung prints a residual >= 2296.  An arm printing `POST_HOLD_LEGALIZE_FAILED` after
  all nine rungs refutes none of them -- it is consistent with all three, and is
  recorded as SILENT rather than counted as a pass.
"""
import os, re, sys, time

os.chdir("/home/reyerchu/_jself_priv")
ARMS = [(3300, "proj/edge_llm_matmul_accel/phase3/stage3/pnr/openroad.log"),
        (3800, "proj/matmul_d3800/phase3/stage3/pnr/openroad.log"),
        (4200, "meas/matmul_fullflow/fullflow_4200.log"),
        (5153, "meas/matmul_fullflow/fullflow_5153.log"),
        (5434, "meas/matmul_fullflow/fullflow_5434.log")]
BAND_LO, BAND_HI = 2296, 2418
LATER = {"clkswap", "clkswap-full-die", "diamond", "diamond-full-die"}

sys.path.insert(0, os.path.abspath("meas/_j68"))
from logcut import post_hold

print(f"asked at {time.strftime('%Y-%m-%dT%H:%M:%S%z')}")
answered, p1_dead, p2_dead, p3_dead, p3_seen = [], False, False, False, []
for die, p in ARMS:
    txt = open(p, errors="replace").read()
    ph = post_hold(txt)
    v = re.search(r"POST_HOLD_LEGALIZE_(OK disp=(\S+)|FAILED)", txt)
    swap = re.search(r"POST_HOLD_CLKBUF_DOWNSIZE swapped=(\d+)", txt)
    r = re.findall(r"Violations remain:\s*(\d+)", ph)
    print(f"  die {die:>4}  rungs printed={len(r):<2} residuals={' -> '.join(r) or '-':<38} "
          f"clkswap={'yes ' + swap.group(1) if swap else 'no':<10} "
          f"verdict={v.group(0) if v else 'none yet'}")
    if v:
        answered.append((die, v.group(0)))
        tok = v.group(2)
        if tok == "full-die":
            p1_dead = True; p2_dead = True
        elif tok and tok not in LATER and not v.group(0).endswith("FAILED"):
            p2_dead = True
    if swap:
        # Cut at the MARKER, never at a rung COUNT.  The first version of this line
        # said `r[5:]`, i.e. "the residuals after the five pre-swap rungs" -- but rung
        # 5 emits nothing until it finishes, so the count is 4 while the arm is inside
        # it and the slice would have silently read the wrong rungs.  That is J78's
        # defect a fourth time; corrected here at 15:4x, while the predicate was still
        # unanswered (0 of 5 arms past rung 5), so no answer could have shaped it.
        after = re.findall(r"Violations remain:\s*(\d+)",
                           ph.split("POST_HOLD_CLKBUF_DOWNSIZE")[-1])
        for x in map(int, after):
            p3_seen.append((die, x))
            if x >= BAND_LO:
                p3_dead = True

print()
if not answered and not p3_seen:
    print("NOT YET — 0 of 5 arms have printed a post-hold verdict and none has reached")
    print("the clkswap rung.  Registered, unanswered.  Re-run this file, do not rewrite it.")
    sys.exit(2)
print(f"P1 (no OK at disp=full-die)          : {'REFUTED' if p1_dead else 'HELD so far'}")
print(f"P2 (any OK comes from rung 6 or later): {'REFUTED' if p2_dead else 'HELD so far'}")
print(f"P3 (clkswap residual < {BAND_LO})        : "
      f"{'REFUTED' if p3_dead else ('HELD so far' if p3_seen else 'no clkswap rung yet')}"
      + (f"   seen={p3_seen}" if p3_seen else ""))
if answered:
    print("\nanswered:", answered)
sys.exit(0)
