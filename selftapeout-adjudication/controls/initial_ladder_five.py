#!/usr/bin/env python3
"""J73 — the INITIAL ladder at FIVE dies, cut at the verdict line.

An earlier version of this table split the log at `PNR_STAGE: cts` and so swept up
the tapcell-prune and spare-tieoff legalizations that run AFTER the verdict — which
reported 5153 as 1/364 in 100.84 s where its rung 5 was 282/282 in 2 878.10 s.  The
cut is now at the verdict line itself."""
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from logcut import initial_ladder          # J78: the rule has ONE home, not three
ARMS = [(3300, "proj/edge_llm_matmul_accel/phase3/stage3/pnr/openroad.log"),
        (3800, "proj/matmul_d3800/phase3/stage3/pnr/openroad.log"),
        (4200, "meas/matmul_fullflow/fullflow_4200.log"),
        (5153, "meas/matmul_fullflow/fullflow_5153.log"),
        (5434, "meas/matmul_fullflow/fullflow_5434.log")]
VERDICT = re.compile(r"INITIAL_DPL_LEGALIZE_(OK|FAILED)[^\n]*")

print(f"{'die':>5} {'util_i':>7} {'residual':>9} {'recovered':>10} {'rung-5 s':>10} {'verdict':>7}")
for die, p in ARMS:
    txt = open(p, errors="replace").read()
    body = initial_ladder(txt)                  # cuts AT the verdict, not after it
    m = VERDICT.search(body)
    rec = re.findall(r"diamond recovery: recovered (\d+)/(\d+) stuck cells", body)
    rt  = re.findall(r"DPL-0500\] Runtime:\s*([\d.]+)s", body)
    ut  = re.findall(r"DPL-0009\] Utilization:\s*([\d.]+)%", body)
    n, d = rec[-1] if rec else ("-", "-")
    v = m.group(1) if m else "open"
    print(f"{die:>5} {ut[0]+'%' if ut else '-':>7} {d:>9} {n:>10} "
          f"{rt[-1] if rt else '-':>10} {v:>7}")
print("\nall-or-nothing: every recovery is 0/N or N/N; no partial at any die.")
