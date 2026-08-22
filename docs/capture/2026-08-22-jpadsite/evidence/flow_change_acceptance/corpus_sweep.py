"""Corpus sweep: the new site discovery over EVERY PDK tree the image ships.
A gate that fires on a legitimately-complete PDK is a bug in the gate."""
import sys, json, pathlib
sys.path.insert(0, "/plugin/programs")
import _pad_ring as PR

ROOT = "/foss/pdks"
rows, problems = [], []
for tree in sorted(p.name for p in pathlib.Path(ROOT).iterdir() if p.is_dir()):
    lefs  = PR.discover_io_lefs(ROOT, tree)
    decls = PR.discover_io_site_declarations(ROOT, tree)
    lib   = PR.IoLibrary(lefs, decls)
    d = lib.as_dict()
    rows.append({
        "tree": tree, "n_io_lefs": len(lefs),
        "lef_site_records": d["n_sites"],
        "lef_pad_class_sites": d["pad_class_sites"],
        "tech_view_configs": len(d["site_declarations"]),
        "declared_sites": d["declared_pad_class_sites"],
        "resolvable_pad_sites": d["pad_class_sites_resolvable"],
        "conflicts": d["site_declaration_conflicts"],
    })
    # A conflict is the ONLY thing the new code can refuse on. On a real PDK
    # it is a false positive unless two libraries genuinely disagree.
    if d["site_declaration_conflicts"]:
        problems.append(tree)
    # every declared site must round-trip through resolve_site as CLASS PAD
    for n in d["declared_pad_class_sites"]:
        r = lib.resolve_site(n)
        if not r or r["class"] != "PAD" or not r["size"]:
            problems.append(f"{tree}:{n}")

# THE DENOMINATOR IS PART OF THE VERDICT.
# A sweep that scanned nothing has zero false positives too, and "CLEAN" would
# be a green earned by looking at nothing — a property of the HOST, not of the
# code. So the verdict states what it examined, and an empty sweep is
# NOT OBSERVED, never CLEAN.
informative = [r for r in rows if r["n_io_lefs"]]
print(json.dumps({"root": ROOT, "trees_swept": len(rows),
                  "trees_with_an_io_library": len(informative),
                  "false_positives": problems, "rows": rows}, indent=2))
print()
if not rows:
    print(f"SWEEP VERDICT: NOT OBSERVED — no PDK tree under {ROOT}. "
          f"Nothing was scanned, so nothing was established.")
elif not informative:
    print(f"SWEEP VERDICT: NOT OBSERVED — {len(rows)} tree(s) under {ROOT}, "
          f"0 of them ship an IO cell library. There was nothing this check "
          f"could have fired on, so a green here means only that it looked.")
elif problems:
    print(f"SWEEP VERDICT: BUG IN THE GATE ({len(informative)} tree(s) with an "
          f"IO library): {problems}")
else:
    print(f"SWEEP VERDICT: CLEAN — 0 false positives over {len(rows)} tree(s), "
          f"{len(informative)} of which ship an IO cell library and could have "
          f"fired.")
