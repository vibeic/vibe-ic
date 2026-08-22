#!/usr/bin/env python3
"""J76 — the fixed point re-solved on FIVE arms, every input re-extracted from the
raw OpenROAD logs.  Nothing here is copied from RESULT.md or from _j67/arm5_verdict.py."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from logcut import initial_ladder, post_hold
os.chdir("/home/reyerchu/_jself_priv")

ARMS = [(3300, "proj/edge_llm_matmul_accel/phase3/stage3/pnr/openroad.log"),
        (3800, "proj/matmul_d3800/phase3/stage3/pnr/openroad.log"),
        (4200, "meas/matmul_fullflow/fullflow_4200.log"),
        (5153, "meas/matmul_fullflow/fullflow_5153.log"),
        (5434, "meas/matmul_fullflow/fullflow_5434.log")]
P = {"core": r"DPL-0006\] Core area:\s+([\d.]+)",
     "mov":  r"DPL-0007\] Movable instances area:\s+([\d.]+)",
     "fix":  r"DPL-0008\] Fixed instances area within core:\s+([\d.]+)",
     "util": r"DPL-0009\] Utilization:\s+([\d.]+)%"}
UTIL, RING = 0.25, 376.0
PAD_FLOOR = 2862.0

def first_block(seg):
    cur, out = {}, None
    for line in seg.splitlines():
        for k, p in P.items():
            m = re.search(p, line)
            if m:
                cur[k] = float(m.group(1))
                if k == "util" and out is None: out = dict(cur)
                if k == "util": cur = {}
    return out

rows = []
print(f"{'die':>5} {'core mm2':>9} {'mov_init':>11} {'fix_init':>11} {'mov_ph':>11} "
      f"{'fix_ph':>11} {'f':>9} {'S':>10} {'util_ph':>8}")
for die, path in ARMS:
    txt = open(path, errors="replace").read()
    i = first_block(initial_ladder(txt))
    ph = first_block(post_hold(txt))
    if not ph:
        print(f"{die:>5}  (no post-hold block yet)"); continue
    f, S = i["fix"] / ph["core"], ph["fix"] - i["fix"]
    rows.append((die, ph["core"], ph["mov"], f, S))
    print(f"{die:>5} {ph['core']/1e6:>9.4f} {i['mov']:>11.2f} {i['fix']:>11.2f} "
          f"{ph['mov']:>11.2f} {ph['fix']:>11.2f} {f:>9.6f} {S:>10.2f} {ph['util']:>7.1f}%")

movs = [r[2] for r in rows]; fs = [r[3] for r in rows]; Ss = [r[4] for r in rows]
cores = [r[1] for r in rows]
fm, Sm = sum(fs)/len(fs), sum(Ss)/len(Ss)
mean = sum(movs)/len(movs)
print(f"\nN = {len(rows)} arms")
print(f"mov_ph : {min(movs):.2f} .. {max(movs):.2f}   spread {(max(movs)-min(movs))/mean*100:.2f} % of mean")
print(f"         monotone in core? {'YES' if movs == sorted(movs) else 'NO'}   "
      f"order by core: {[round(m/1e6,4) for m in movs]}")
print(f"f      : {min(fs):.6f} .. {max(fs):.6f}   mean {fm:.6f}")
print(f"S      : {min(Ss):.2f} .. {max(Ss):.2f}   spread {max(Ss)-min(Ss):.4f}")
print(f"core   : {min(cores)/1e6:.3f} .. {max(cores)/1e6:.3f} mm2   "
      f"growth {(max(cores)/min(cores)-1)*100:.1f} %")
print(f"\nA* = (M + S)/(UTIL - f)   with UTIL={UTIL}, f={fm:.6f}, S={Sm:.2f}")
for nm, M in (("low ", min(movs)), ("mean", mean), ("high", max(movs))):
    A = (M + Sm)/(UTIL - fm); die = A**0.5 + 2*RING
    print(f"  movable {nm}  M={M:11.2f}  core {A**0.5:7.1f}  DIE {die:7.1f} um "
          f"({die*die/1e6:6.3f} mm2)  {die/PAD_FLOOR:.3f}x pad floor")
print("\npublished before this rung: 6138.9 / 6154.2 / 6164.9 um = 2.145x / 2.150x / 2.154x")
