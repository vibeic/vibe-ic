"""FALSE-POSITIVE test for F1 formulation 3, on the REAL open PDKs.

The predicate greps the UNREAD views for the refused NAME. I asserted it stays
silent when the refusal is correct. A substring grep can hit a name
INCIDENTALLY, so that assertion needs measuring, not asserting.
"""
import pathlib
ROOT = pathlib.Path("/foss/pdks")
for pdk in ("gf180mcuD", "sky130A"):
    tree = ROOT / pdk
    if not tree.is_dir():
        print("=== %s: absent" % pdk); continue
    views = sorted(p.name for p in tree.iterdir() if p.is_dir())
    print("=== %s  views: %s" % (pdk, views))
    unread = [tree / v for v in views if v != "libs.ref"]
    probes = [
        ("real site declared in the tech view",
         "GF_IO_Site" if pdk == "gf180mcuD" else "sky130_io"),
        ("exists NOWHERE (true absence)", "zz_no_such_site_zz"),
        ("SHORT generic name (the FP risk)", "io"),
        ("plausible-but-absent name", "core"),
    ]
    for label, name in probes:
        hit = None
        for d in unread:
            for f in d.rglob("*"):
                if f.is_file() and f.stat().st_size < 8000000:
                    try:
                        if name in f.read_text(errors="replace"):
                            hit = str(f.relative_to(tree)); break
                    except OSError:
                        pass
            if hit:
                break
        verdict = ("FIRES: " + hit) if hit else "silent"
        print("    %-38s %-22r -> %s" % (label, name, verdict))
