#!/usr/bin/env python3
"""The build-to die, solved as a FIXED POINT instead of probed.

§6 sizes the build-to die by applying the flow's utilisation target to each arm's
measured post-hold `movable + fixed` area. That area contains a term that scales
with the die you evaluate it at (the tapcell/PDN lattice), so the answer moves with
the probe. §6 hedged this as "mildly self-referential ... 1.5 %". The FOURTH arm
lands outside the range that hedge produced, so the hedge is wrong and the effect
has to be solved rather than bounded.

Both die-dependent terms turn out to be exactly linear in the CORE AREA, measured
at four dies, so the fixed point has a closed form. Nothing here is fitted with a
free parameter: `f` is a ratio measured four times and `S` is a constant that is
IDENTICAL to the last published digit at all four dies.

Inputs are the arms' own OpenROAD `DPL-0006/0007/0008` lines, nothing else.
"""

print("NOTE — SUPERSEDED BY A FIFTH ARM (J76): this file solves the fixed point at "
      "FOUR dies and its top figure, 6164.9 um / 2.154x, is the build-to top as it "
      "stood BEFORE arm 5. The published answer is 6138.8-6171.2 um / 2.145-2.156x, "
      "from controls/resolve_five.py, which reads the five arms' raw logs instead "
      "of this file's typed table. Every number below is correct FOR FOUR ARMS.")

import math

# die_um: (core_area, movable_initial, fixed_initial, movable_posthold, fixed_posthold)
ARMS = {
    3300: (10677204.74, 5674818.11,  427172.75, 6035072.38,  525609.91),
    3800: (14201741.03, 5683500.12,  568754.37, 6054418.68,  667191.53),
    4200: (17375223.13, 5634457.16,  694464.69, 5995578.53,  792901.85),
    5153: (26226686.62, 5656393.79, 1048172.88, 6035684.84, 1146610.04),
}
UTIL   = 0.25    # phase3_one_shot_runner.py:12604  _AUTO_DIE_TARGET_UTIL
RING2  = 752.0   # 2 * (350 um pad-ring depth + 26 um PAD_EDGE_SPACING), §1
PADFLR = 2862.0  # die_edge_min(111 pads), §0

print("=== 1. the two die-dependent terms, MEASURED at four dies ===")
print(f"{'die':>5} {'core mm2':>9} {'fix_init':>9} {'f=fix/core':>11} "
      f"{'fix_ph':>9} {'S=fix_ph-fix_init':>18}")
fs, Ss = [], []
for d,(c,mi,fi,mp,fp) in ARMS.items():
    f = fi/c; S = fp-fi; fs.append(f); Ss.append(S)
    print(f"{d:>5} {c/1e6:9.3f} {fi:9.0f} {f:11.6f} {fp:9.0f} {S:18.2f}")
f_lo,f_hi = min(fs),max(fs); S_lo,S_hi = min(Ss),max(Ss)
print(f"\n  f  spans {f_lo:.6f}..{f_hi:.6f}  = {100*(f_hi-f_lo)/f_lo:.3f} % — the tapcell/PDN lattice")
print(f"  S  spans {S_lo:.2f}..{S_hi:.2f}  = {S_hi-S_lo:.2f} um2 — the spare/dont-touch block, IDENTICAL")
f = sum(fs)/len(fs); S = sum(Ss)/len(Ss)

print("\n=== 2. the model reproduces every measured fixed area ===")
print(f"{'die':>5} {'fix_ph measured':>16} {'f*core+S predicted':>19} {'err':>8}")
for d,(c,mi,fi,mp,fp) in ARMS.items():
    pred = f*c + S
    print(f"{d:>5} {fp:16.2f} {pred:19.2f} {100*(pred-fp)/fp:7.3f}%")

MV = [mp for (_,_,_,mp,_) in ARMS.values()]
M_lo, M_hi, M_mu = min(MV), max(MV), sum(MV)/len(MV)
print(f"\n  post-hold MOVABLE area: {M_lo:.0f} .. {M_hi:.0f}  ({100*(M_hi-M_lo)/M_lo:.2f} % span, four dies)")

def die_from_probe(area_ph):
    core = math.sqrt(area_ph/UTIL)
    return core, core+RING2

print("\n=== 3. what §6 published: the rule evaluated AT each probe die ===")
print(f"{'probe die':>9} {'posthold mm2':>13} {'core um':>9} {'DIE um':>8} {'/2862':>7}")
for d,(c,mi,fi,mp,fp) in ARMS.items():
    core,die = die_from_probe(mp+fp)
    print(f"{d:>9} {(mp+fp)/1e6:13.4f} {core:9.1f} {die:8.0f} {die/PADFLR:7.3f}x")
print("  ^ monotone increasing with the probe. It is an unconverged iteration,")
print("    not a range — the answer's own core is larger than every probe used.")

print("\n=== 4. the FIXED POINT: A* = (M + f*A* + S)/UTIL ===")
def fixed_point(M):
    A = 4.0*(M+S)/(1.0-f/UTIL)      # UTIL=0.25 -> 1/UTIL=4
    core = math.sqrt(A); return A, core, core+RING2
for lbl,M in (("movable low ",M_lo),("movable mean",M_mu),("movable high",M_hi)):
    A,core,die = fixed_point(M)
    print(f"  {lbl}  core_area {A/1e6:7.3f} mm2   core {core:7.1f} um   DIE {die:7.1f} um "
          f"({die*die/1e6:6.2f} mm2)  {die/PADFLR:.3f}x")

print("\n  iterate from the smallest probe to show it converges there:")
A = ARMS[3300][0]
for i in range(7):
    A = 4.0*(M_mu + f*A + S); core = math.sqrt(A)
    print(f"    iter {i+1}: core_area {A/1e6:7.3f} mm2  core {core:7.1f}  DIE {core+RING2:7.1f}")

print("\n=== 5. the OTHER reading: the flow's own auto-die formula ===")
print("  phase3_one_shot_runner.py:13497  side = sqrt(cells*avg_cell / util)")
print("  -- cells*avg_cell is the NETLIST's cells, i.e. movable only; no tapcell,")
print("     no spare, no PDN. Applied to the measured movable area:")
for lbl,M in (("movable low ",M_lo),("movable mean",M_mu),("movable high",M_hi)):
    core = math.sqrt(M/UTIL); die = core+RING2
    print(f"  {lbl}  core {core:7.1f} um   DIE {die:7.1f} um ({die*die/1e6:6.2f} mm2)  {die/PADFLR:.3f}x")

print("\n=== 6. the bracket the two readings define ===")
lo = math.sqrt(M_lo/UTIL)+RING2
hi = fixed_point(M_hi)[2]
print(f"  {lo:.0f} um ({lo/PADFLR:.2f}x)  ..  {hi:.0f} um ({hi/PADFLR:.2f}x)   "
      f"[{lo*lo/1e6:.1f} .. {hi*hi/1e6:.1f} mm2]")
print(f"  pad floor {PADFLR:.0f} um ({PADFLR*PADFLR/1e6:.2f} mm2). Both ends are CORE-limited.")
