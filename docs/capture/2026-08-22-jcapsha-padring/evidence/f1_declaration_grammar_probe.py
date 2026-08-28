"""Formulation 3, FIXED: falsify against the DECLARATION GRAMMAR, not a substring.

The bare substring version over-fires -- measured on both real PDKs, a short
generic name hits unrelated files. The step already knows what a DECLARATION of
the thing looks like (it has a parser for it), so the falsification must use
that parser. Same question, no free-text grep.
"""
import sys, pathlib, importlib.util
spec = importlib.util.spec_from_file_location("pr", "/w/_pad_ring_post.py")
PR = importlib.util.module_from_spec(spec); spec.loader.exec_module(PR)

ROOT = pathlib.Path("/foss/pdks")
for pdk in ("gf180mcuD", "sky130A"):
    tree = ROOT / pdk
    if not tree.is_dir():
        continue
    print("=== %s" % pdk)
    # what the DECLARATION GRAMMAR finds in the views a libs.ref-only run skipped
    decls = {}
    for cfg in PR.discover_io_site_declarations(str(ROOT), pdk):
        decls.update(PR.parse_pad_site_declarations(
            pathlib.Path(cfg).read_text(errors="replace")))
    print("    declared-in-unread-view names: %s" % sorted(decls))
    for label, name in [
            ("real site declared in the tech view",
             "GF_IO_Site" if pdk == "gf180mcuD" else "sky130_io"),
            ("exists NOWHERE (true absence)", "zz_no_such_site_zz"),
            ("SHORT generic name (the FP risk)", "io"),
            ("plausible-but-absent name", "core")]:
        fires = name in decls
        print("    %-38s %-22r -> %s" % (
            label, name, ("FIRES (size %s)" % (decls[name],)) if fires else "silent"))
