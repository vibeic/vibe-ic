#!/usr/bin/env python3
"""J90 — join the per-chip direction split onto the IO library, and ask whether the
published pad-limited die floor can move under the cell-type choice J89 found missing.

`padring_die_floor.py` computed every design's pad-limited die edge with ONE pad width,
`pad_w_um = 75.0`.  J89 then found that the assignment does NOT fix the cell TYPE per pad
and that the library carries several families -- so the obvious question is whether the
floor depends on a choice nobody has made.  If it does, six published numbers are
conditional on it.  Measured from the PDK's own LEFs rather than assumed.
"""
import glob, json, os, re
from collections import Counter

IOLEF = "/home/reyerchu/_gf180_priv/pdk/gf180mcuD/libs.ref/gf180mcu_fd_io/lef"
FLOOR = "/home/reyerchu/_jself_priv/meas/padring_die_floor.json"

w = {}
for f in sorted(glob.glob(f"{IOLEF}/*.lef")):
    t = open(f, errors="replace").read()
    m = re.search(r"^\s*SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", t, re.M)
    if m:
        w[os.path.basename(f)[:-4]] = (float(m.group(1)), float(m.group(2)))

SIGNAL = {k: v for k, v in w.items()
          if not re.search(r"__(fill|brk|cor)", k)}
print("=== every SIGNAL-carrying IO master, from the PDK's own LEF ===")
for k, (a, b) in sorted(SIGNAL.items()):
    print(f"  {k:<34} {a:8.3f} x {b:8.3f} um")
widths = sorted({a for a, _ in SIGNAL.values()})
print(f"\n  distinct widths among them: {widths}")
uniform = len(widths) == 1
print(f"  UNIFORM: {uniform}"
      + ("" if uniform else "  <- the floor DOES depend on the cell-type choice"))

# the family each direction must use, from the library's own contents
fams = sorted(SIGNAL)
has_out_only = [k for k in fams if re.search(r"__out", k)]
print(f"\n  output-only masters in the library: {has_out_only or 'NONE'}"
      "  -> outputs must use a bidirectional cell")
need = {"input": [k for k in fams if "__in_" in k],
        "output": [k for k in fams if "__bi_" in k],
        "inout": [k for k in fams if "__bi_" in k],
        "analog": [k for k in fams if "__asig" in k]}
for d, ks in need.items():
    print(f"  {d:<7} -> {', '.join(os.path.basename(k) for k in ks) or 'NONE'}")

print("\n=== per design: the mix the missing step would instantiate ===")
data = json.load(open(FLOOR))
pad_w = data["pad_w_um"]
print(f"  (published floor used pad_w_um = {pad_w})")
print(f"{'design':<24}{'in':>7}{'out':>7}{'inout':>7}{'bits':>7}   floor moves?")
for d in data["designs"]:
    b = d.get("bits_by_direction") or {}
    tot = sum(b.values())
    covered = all(need[k] for k in ("input", "output", "inout") if b.get(k))
    moves = "NO" if (uniform and covered) else "YES -- CHECK"
    print(f"{d['name']:<24}{b.get('input',0):>7}{b.get('output',0):>7}"
          f"{b.get('inout',0):>7}{tot:>7}   {moves}")
print()
if uniform:
    print(f"Every signal-carrying master is {widths[0]:.3f} um wide, so the pad-limited")
    print("die floor is INVARIANT to the cell-type mapping J89 found missing: no choice")
    print("that step could make moves any of the six published floors by one micron.")
else:
    print("The floor is NOT invariant; the published numbers are conditional.")
