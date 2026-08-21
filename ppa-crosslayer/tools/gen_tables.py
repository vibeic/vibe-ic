#!/usr/bin/env python3
"""Render the RESULT.md tables from records/summary.json, so no figure in the
prose exists that no artefact carries."""
import json, sys
from pathlib import Path
ROOT = Path("/home/reyerchu/_jxlayer")
S = json.loads((ROOT / "records" / "summary.json").read_text())
T = S["trials"]
BASE = T["b000"]["objective_um2"]
EQ = S["equivalence"]

ADMITTED = {k for k, v in EQ.items() if v["status"] == "PASS"}
ADMITTED.add("base")


def verdict(v):
    r = v["rtl_variant"]
    if r == "base":
        return "n/a (baseline RTL)"
    e = EQ.get(r)
    if not e:
        return "NOT RUN"
    return f"{e['status']} ({e['proven']}/{e['compared']})"


def arm(v):
    if v["rtl_variant"] == "base" and v["synthesis_strategy"] == "none":
        return "PnR-only"
    return "cross-layer"


rows = sorted(T.values(), key=lambda v: (v["objective_um2"] is None,
                                         v["objective_um2"] or 0))
print("| trial | arm | rtl_variant | synth strategy | density | spare | "
      "objective µm² | Δ vs default | synth area µm² | post-route power W | "
      "rewrite-equivalence |")
print("|---|---|---|---|---|---|---:|---:|---:|---:|---|")
for v in rows:
    o = v["objective_um2"]
    d = f"{100*(o-BASE)/BASE:+.2f}%" if o else "—"
    ov = f"**{o:.0f}**" if o else f"NOT_MEASURED"
    sa = f"{v['synth_area_um2']:.1f}" if v.get("synth_area_um2") else "—"
    pw = f"{v['power_postroute_w']:.6f}" if v.get("power_postroute_w") else "—"
    adm = verdict(v)
    print(f"| `{v['trial']}` | {arm(v)} | `{v['rtl_variant']}` | "
          f"`{v['synthesis_strategy']}` | {v['placement_density']} | "
          f"{v['spare_cell_density']} | {ov} | {d} | {sa} | {pw} | {adm} |")
print()
print(f"{S['counts']['measured']} of {S['counts']['total']} candidates produced a "
      f"MEASURED objective; {S['counts']['not_measured']} did not and every one "
      f"is in the table with its reason.")
