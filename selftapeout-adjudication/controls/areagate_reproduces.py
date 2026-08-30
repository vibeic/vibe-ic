#!/usr/bin/env python3
"""J105 — §4a's four-row area-gate table, re-run; and the trap that it did not, at first.

Section 4a publishes the flow's OWN `area_total_vs_budget_check` refusing
`edge_llm_accel` at rc 1 — the SECOND reason that row is NOT FEASIBLE, and the one that
is the flow's judgement rather than my arithmetic. So it has to re-run.

Run bare against the stored evidence trees it returns **rc 2 INCOMPLETE on all four**,
including the row published as rc 1. Nothing had changed about the verdicts: the stored
trees were missing **both** inputs the run had supplied —

  * the AUTHORITY, `L19_CONSTRAINTS_PDK.json fields.die_area_budget_um`, taken from each
    design's own document (`edge_llm_accel` L9:35 *"Die size | 2400 × 2400 µm"*,
    `caravel_user_project` L9:12 *"DIE_AREA = [0, 0, 2920, 3520] µm"*), written into the
    tree at run time and not kept;
  * the flag `--area-unit-um2`, without which the gate refuses to assert a unit the
    producing artefact declines to assert — `stats.json` says `chip_area_unit` is a
    *"cell-library area unit"*, not µm².

Either one missing turns a FAIL into an INCOMPLETE, which is a **different tier, not a
milder one**. An evidence tree that cannot reproduce its own stored output is the same
defect as a citation that resolves to a stale copy (J102): the artefact is there and it
does not say what the sentence beside it says.

This pins the four tiers against trees that now carry their authority, and proves the
two silent-tier-change paths are the ones named above.

Env `J105_TREES` points at another directory of reconstructed trees, for perturbation.
"""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path("/home/reyerchu/_jself_priv")
TREES = pathlib.Path(os.environ.get("J105_TREES", str(ROOT / "meas/_j105")))
GATE = ROOT / "wt/vibe-ic-marketplace/plugins/vibe-ic/programs/area_total_vs_budget_check.py"

# (design, expected rc, a substring the published quote contains)
PUBLISHED = [
    ("edge_llm_accel",       1, "AREA_TOTAL_OVER_DECLARED_DIE"),
    ("edge_llm_accel",       1, "5.57x"),
    ("caravel_user_project", 0, "utilization 0.0005"),
    ("ibex",                 2, "INCOMPLETE"),
    ("opentitan_aes",        2, "INCOMPLETE"),
]


def gate(tree, unit_flag=True):
    cmd = [sys.executable, str(GATE), str(tree)]
    if unit_flag:
        cmd.append("--area-unit-um2")
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


bad, seen = [], set()
print("=== the four published tiers, re-run on trees that carry their authority ===")
for design, want_rc, needle in PUBLISHED:
    tree = TREES / f"areagate_{design}"
    if not tree.is_dir():
        bad.append((design, f"no reconstructed tree at {tree}"))
        print(f"  MISSING   {design:<22} {tree}")
        continue
    rc, out = gate(tree)
    ok = rc == want_rc and needle in out
    if design not in seen:
        seen.add(design)
    print(f"  {'OK' if ok else '*** DIFFERS ***':<16} {design:<22} rc={rc} "
          f"(published {want_rc})  contains {needle!r}: {needle in out}")
    if not ok:
        bad.append((design, f"rc={rc} want {want_rc}; {needle!r} present={needle in out}"))

print("\n=== the two paths that silently change the TIER ===")
t = TREES / "areagate_edge_llm_accel"
if t.is_dir():
    rc_nounit, out_nounit = gate(t, unit_flag=False)
    print(f"  without --area-unit-um2      rc={rc_nounit} "
          f"(INCOMPLETE: {'INCOMPLETE' in out_nounit})")
    l19 = list(t.glob("**/L19*.json"))
    moved = []
    for f in l19:
        f.rename(f.with_suffix(".json.hidden"))
        moved.append(f)
    rc_nol19, out_nol19 = gate(t)
    for f in moved:
        f.with_suffix(".json.hidden").rename(f)
    print(f"  with the L19 authority gone  rc={rc_nol19} "
          f"(INCOMPLETE: {'INCOMPLETE' in out_nol19})")
    if not (rc_nounit == 2 and rc_nol19 == 2):
        bad.append(("edge_llm_accel",
                    "removing the unit flag or the authority did NOT produce rc 2, so "
                    "the trap this control documents is not the trap"))
    rc_back, _ = gate(t)
    if rc_back != 1:
        bad.append(("edge_llm_accel",
                    f"the tree did not come back to rc 1 after the perturbation "
                    f"(got {rc_back}) — this control damaged its own input"))
    else:
        print(f"  restored                     rc={rc_back} (back to the published tier)")
else:
    bad.append(("edge_llm_accel", "no tree to perturb"))

print()
if bad:
    print(f"{len(bad)} published area-gate row(s) do not reproduce:")
    for d, why in bad:
        print(f"    {d}: {why}")
    sys.exit(1)
print("All four tiers reproduce — rc 1 / rc 0 / rc 2 / rc 2 — on trees that carry the")
print("authority the run was given, and both ways of losing that authority produce a")
print("DIFFERENT TIER rather than a milder verdict.")
sys.exit(0)
