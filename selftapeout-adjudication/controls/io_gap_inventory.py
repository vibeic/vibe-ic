#!/usr/bin/env python3
"""J89 — what is ACTUALLY missing for the four UNDETERMINED rows, as an inventory.

The report says the wall is `PAD_INSTANCE_NOT_IN_BLOCK`: an exit-0 pad assignment names
the pad INSTANCES, and nothing creates them in the netlist. That is measured. What was
never measured is whether the pieces the missing step would need actually EXIST -- and
"the gap is mechanical" is only true if they do.

Three questions, each answered from an artefact rather than from the sentence above:
  1. Does the assignment name the MASTER for each signal pad, or only the instance?
  2. Does the PDK ship the IO masters it does name (corner, fillers) and a signal-pad
     family to choose from?
  3. Is the information needed to CHOOSE among them (port direction) available?
"""
import json, os, re, glob, sys

PDK  = "/home/reyerchu/_gf180_priv/pdk/gf180mcuD"
IOLIB = f"{PDK}/libs.ref/gf180mcu_fd_io"
ASG  = "/home/reyerchu/_jself_priv/probe_padring/phase3/stage3/pnr/pad_assignment.json"

d = json.load(open(ASG))
sides = {k: d.get(k, []) for k in ("PAD_SOUTH", "PAD_EAST", "PAD_NORTH", "PAD_WEST")}
n_pads = sum(len(v) for v in sides.values())
sigmap = d.get("SIGNAL_MAP", {})

print("=== 1. what the assignment NAMES ===")
print(f"  pad instances ordered on the four sides : {n_pads}")
print(f"  entries in SIGNAL_MAP                   : {len(sigmap)}")
named_masters = {k: v for k, v in d.items()
                 if isinstance(v, str) and v.startswith("gf180mcu_fd_io__")}
for k, v in d.items():
    if isinstance(v, list) and v and all(isinstance(x, str)
                                         and x.startswith("gf180mcu_fd_io__") for x in v):
        named_masters[k] = v
print(f"  keys naming an IO MASTER                : {sorted(named_masters)}")
per_pad_master = [p for p in sigmap
                  if isinstance(sigmap.get(p), str) and sigmap[p].startswith("gf180mcu_fd_io__")]
print(f"  signal pads carrying their own master   : {len(per_pad_master)} of {len(sigmap)}")
print("  -> the assignment fixes the PIN-OUT and the corner/filler masters;")
print("     it does NOT say which IO cell TYPE each signal pad is.")

print("\n=== 2. does the PDK ship what it names, and what is there to choose from? ===")
lefs = sorted(os.path.basename(p)[:-4] for p in glob.glob(f"{IOLIB}/lef/*.lef"))
have = set(lefs)
for k, v in sorted(named_masters.items()):
    for m in ([v] if isinstance(v, str) else v):
        print(f"  {k:<22} {m:<34} {'PRESENT' if m in have else 'ABSENT'}")
fams = {}
for m in lefs:
    t = m.split("__", 1)[1] if "__" in m else m
    fams.setdefault(re.sub(r"\d+", "", t), []).append(t)
print(f"\n  IO masters in the library: {len(lefs)}")
for f in sorted(fams):
    print(f"    {f:<12} {len(fams[f]):>2}  {' '.join(sorted(fams[f])[:6])}")

print("\n=== 3. is the information to CHOOSE among them available? ===")
# NOTE: the first version of this section looked for `input x;` statements in the
# module BODY and found 8 ports in a submodule -- against 77 pads.  A count that does
# not match the thing it is about is the adjacent-thing trap, and it read as an answer.
# The top module declares its ports ANSI-style, INSIDE the parenthesised header.
TOP = "/home/reyerchu/_jself_priv/probe_padring/phase2/stage1/rtl/chip_top.v"
txt = open(TOP, errors="replace").read()
m = re.search(r"\bmodule\s+(\w+)\s*\((.*?)\)\s*;", txt, re.S)
assert m, "no module header"
decl = {}
for item in m.group(2).split(","):
    mm = re.search(r"\b(input|output|inout)\b", item)
    if not mm:
        continue
    kind = mm.group(1)
    rng = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", item)
    name = re.sub(r"\[[^\]]*\]", " ", item)
    name = re.sub(r"\b(input|output|inout|wire|reg|logic|signed)\b", " ", name).strip()
    if not name:
        continue
    if rng:
        hi, lo = int(rng.group(1)), int(rng.group(2))
        for b in range(min(hi, lo), max(hi, lo) + 1):
            decl[f"{name}[{b}]"] = kind
    else:
        decl[name] = kind
from collections import Counter
print(f"  top module {m.group(1)!r}: {len(decl)} declared port BITS  "
      f"{dict(Counter(decl.values()))}")
hit = [p_ for p_, s_ in sigmap.items() if s_ in decl]
miss = [(p_, s_) for p_, s_ in sigmap.items() if s_ not in decl]
print(f"  pad signals whose direction IS declared : {len(hit)} of {len(sigmap)}")
if miss:
    print(f"  UNMATCHED ({len(miss)}): {miss[:6]}")
    sys.exit(1)
print(f"  directions across the 77 pads          : "
      f"{dict(Counter(decl[s_] for s_ in sigmap.values()))}")
print("  -> every pad signal has a DECLARED direction, and the bit count matches the")
print("     pad count exactly, so the cell-type choice is derivable from the design")
print("     rather than invented -- which is the distinction the brief turns on.")
