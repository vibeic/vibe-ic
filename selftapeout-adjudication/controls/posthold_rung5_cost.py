#!/usr/bin/env python3
"""J75 — pricing the post-hold rung-5 wait against each arm's OWN initial rung 5.

CAVEATS, first, because the number is only as good as them:
  * the rung emits nothing until it finishes, so the log's last-write time is when
    the arm ENTERED it — the elapsed below is a LOWER BOUND on the rung's cost;
  * that entry time is an mtime, a proxy, not a timestamp OpenROAD printed;
  * the four arms ran under a host load that moved between ~15 and ~112, so these
    are not comparable to each other as CPU costs, only as "how long has this one
    been in there".
The cut rule is imported from logcut.py rather than re-implemented — the first
version of this script re-made the exact defect J73 had caught an hour earlier."""
import sys, os, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from logcut import initial_ladder, post_hold

ARMS = [(3300, "proj/edge_llm_matmul_accel/phase3/stage3/pnr/openroad.log", 5124.72, "FAILED"),
        (3800, "proj/matmul_d3800/phase3/stage3/pnr/openroad.log",          1076.56, "OK"),
        (4200, "meas/matmul_fullflow/fullflow_4200.log",                     848.15, "OK"),
        (5153, "meas/matmul_fullflow/fullflow_5153.log",                    2878.10, "OK"),
        (5434, "meas/matmul_fullflow/fullflow_5434.log",                    3299.09, "OK")]
os.chdir("/home/reyerchu/_jself_priv")
now = time.time()
print(f"{'die':>5} {'init rung5 s':>13} {'init resid':>11} {'ph resid':>9} "
      f"{'ph rung5 elapsed':>17} {'ratio >=':>9} {'init verdict':>13}")
for die, p, ti, v in ARMS:
    txt = open(p, errors="replace").read()
    ri = re.findall(r"Violations remain:\s*(\d+)", initial_ladder(txt))
    rp = re.findall(r"Violations remain:\s*(\d+)", post_hold(txt))
    nblk = len(re.findall(r"DPL-0006\] Core area", post_hold(txt)))
    done = re.search(r"POST_HOLD_LEGALIZE_(OK|FAILED)[^\n]*", txt)
    el = now - os.path.getmtime(p); h, m = int(el//3600), int(el % 3600//60)
    print(f"{die:>5} {ti:>13.2f} {ri[-1] if ri else '-':>11} {rp[-1] if rp else '-':>9} "
          f"{f'{h}h {m:02d}m':>17} {el/ti:>8.1f}x {v:>13}"
          + ("" if not done else f"   -> {done.group(0)}"))
    # `assert nblk == 5` was itself time-dependent (J78's class): the instant an arm
    # leaves rung 5 the count becomes 6 and a correct run would abort.  The invariant
    # is "at least at rung 5", which only ever gets more true.
    assert nblk >= 5 or done, f"die {die}: {nblk} post-hold blocks, expected >=5"
n_open = sum(1 for d, p, t, v in ARMS
             if not re.search(r"POST_HOLD_LEGALIZE_", open(p, errors="replace").read()))
print(f"\n{n_open} of {len(ARMS)} are on post-hold rung 5 or later with no "
      f"POST_HOLD_LEGALIZE_* printed.")
# the range used to be typed in as "3x-41x" and went stale the moment a fifth arm
# joined at 0.8x -- a hard-coded summary of a moving measurement is the same defect
# one layer up, so it is computed.
_r = sorted((now - os.path.getmtime(p)) / t for d, p, t, v in ARMS)
print(f"Same rung, ~7-9x the residual, already {_r[0]:.1f}x-{_r[-1]:.1f}x the initial")
print("rung's cost at the SAME die, and not terminating.")
