#!/usr/bin/env python3
"""J104 — `abuts: true` is a FIELD NAME.  How much of the ring actually touches?

Section 4 of this report says `caravel_user_project` gets "a real placed, **abutting**
ring", and cites `abuts: true` from the step's own `padring.json`.  The tool's word is
not the physical thing: `abuts` is its name for **no gap is unfillable**, and the same
file records `fillers_placed = null` under an `unperformed` key that says, in the
program's own words, *"an absent placement is not a placement of none"*.

So this counts, per side, how many gaps are literally zero -- and checks the flow's own
`unfillable: []` claim ARITHMETICALLY instead of quoting it:

  1. the gaps on a side sum to exactly that side's `space_for_fill`
  2. every gap is a whole multiple of the SMALLEST declared filler
  3. `unfillable` is empty
  4. a side's slack is either 0 or exactly one pad width -- which is the same quantity
     the perimeter probe's negative control removes when it makes the die refuse

Exit 0 if every probe satisfies all four; 1 if any does not; 2 if it found no probes.
Env `J104_PROBES` points it at another directory of probe trees, for perturbation.
"""
import json
import os
import pathlib
import sys

PROBES = pathlib.Path(os.environ.get(
    "J104_PROBES", "/home/reyerchu/_jself_priv/meas"))
PAD_W = int(os.environ.get("J104_PAD_WIDTH_DBU", "150000"))

trees = sorted(p for p in PROBES.glob("_probe_*_at")
               if (p / "reports/phase3/padring.json").is_file())
if not trees:
    print(f"no probe trees with a padring.json under {PROBES}")
    print("An empty census is not a clean one.")
    sys.exit(2)

bad, skipped = [], []
# A probe tree can hold a FAIL -- `_probe_caravel_padfacing_at` is a 2187 um run that
# refuses, 57 of 75 pads placed and no `W` spacing block at all, because the step stops
# where it cannot continue.  Censusing a refused ring as if it were a placed one would
# be reading a partial artefact as a whole one.  They are LISTED, never dropped.
census = []
for t in trees:
    j = json.loads((t / "reports/phase3/padring.json").read_text())
    if j.get("verdict") != "PASS":
        skipped.append((t.name[len("_probe_"):-len("_at")], j.get("verdict"),
                        len(j.get("pads", [])), j.get("die", {}).get("box")))
        continue
    census.append((t, j))

print(f"{'design':<24} {'side':<4} {'gaps':<5} {'touch':<6} {'slack_dbu':<10} "
      f"{'=space_for_fill':<16} {'multiple of min filler':<22}")
for t, j in census:
    name = t.name[len("_probe_"):-len("_at")]
    ab, sp = j["abutment"], j["spacing"]
    mf = min(ab["filler_widths_dbu"])
    if ab["unfillable"]:
        bad.append((name, "-", f"unfillable is not empty: {ab['unfillable'][:3]}"))
    for side, gl in ab["gaps"].items():
        touch = sum(1 for g in gl if g == 0)
        slack = sum(gl)
        want = sp[side]["space_for_fill"]
        ok_sum = slack == want
        ok_mul = all(g % mf == 0 for g in gl)
        ok_pad = slack in (0, PAD_W)
        print(f"{name:<24} {side:<4} {len(gl):<5} {touch:<6} {slack:<10} "
              f"{str(ok_sum):<16} {str(ok_mul):<22}")
        if not ok_sum:
            bad.append((name, side, f"gaps sum to {slack}, space_for_fill says {want}"))
        if not ok_mul:
            bad.append((name, side,
                        f"a gap is not a multiple of the smallest filler ({mf} dbu)"))
        if not ok_pad:
            bad.append((name, side,
                        f"slack {slack} is neither 0 nor one pad width ({PAD_W})"))

print(f"\n  {len(census)} PASS probe tree(s) censused of {len(trees)} found; "
      f"smallest declared filler is the divisor in each")
if skipped:
    print("\n=== probe trees that did NOT place a ring — listed, not dropped ===")
    for name, verdict, npads, box in skipped:
        um = (box[2] / 2000) if box else None
        print(f"  {name:<24} verdict={verdict:<6} pads_placed={npads:<5} "
              f"die={um} um")
print("\n=== what 'abutting' means, per design ===")
for t, j in census:
    name = t.name[len("_probe_"):-len("_at")]
    ab = j["abutment"]
    sides_touching = [s for s, gl in ab["gaps"].items() if all(g == 0 for g in gl)]
    n = len(ab["gaps"])
    fp = j.get("fillers_placed")
    print(f"  {name:<24} literally touching on {len(sides_touching)}/{n} side(s) "
          f"{''.join(sorted(sides_touching)) or '-':<5} fillers_placed={fp}")

print()
if bad:
    print(f"{len(bad)} abutment claim(s) do not hold arithmetically:")
    for n, s, why in bad:
        print(f"    {n} {s}: {why}")
    sys.exit(1)
print("Every ring's gaps sum to its own declared fill space, every gap is a whole")
print("multiple of the smallest declared filler, nothing is unfillable, and every")
print("side's slack is either zero or exactly one pad width. `abuts: true` is earned")
print("-- and it still does not mean the cells touch, which is why the census above")
print("prints how many sides actually do.")
sys.exit(0)
