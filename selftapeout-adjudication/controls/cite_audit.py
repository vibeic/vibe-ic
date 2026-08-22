#!/usr/bin/env python3
"""J68 — re-resolve EVERY file:line coordinate this report publishes.

The coordinates are EXTRACTED FROM RESULT.md, not typed into this script: a checker
that audits a list I remember writing tests my memory, not the report.  Each one is
resolved against the tree its sentence is about and the line's actual text printed.
Run from /home/reyerchu/_jself_priv."""
import re, subprocess, pathlib, sys

WT   = pathlib.Path("wt/vibe-ic-marketplace/plugins/vibe-ic")
PNR  = pathlib.Path("proj/edge_llm_matmul_accel/phase3/stage3/pnr/pnr.tcl")
PDK  = pathlib.Path("/home/reyerchu/_gf180_priv/pdk/ciel/gf180mcu/versions/"
                    "f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7/gf180mcuD/libs.tech/"
                    "ngspice/sm141064.ngspice")
MAIN_PADRING = "bc16efe053e99f7bbcbd498305d29187d6338419"   # main a4caccefe blob

# basename -> resolver.  pad_ring_gen.py is deliberately BOTH trees: section 7's
# sentence is about main, and the point of J68 is that the bare form does not say so.
def _local(p):
    return lambda: p.read_text(errors="replace").splitlines()
def _blob(sha):
    return lambda: subprocess.run(
        ["git", "-C", "wt/vibe-ic-marketplace", "cat-file", "-p", sha],
        capture_output=True, text=True).stdout.splitlines()

TREES = {
    "pnr.tcl":                    [("run", _local(PNR))],
    "phase3_one_shot_runner.py":  [("wt",  _local(WT / "programs/phase3_one_shot_runner.py"))],
    "pad_ring_gen.py":            [("wt",  _local(WT / "programs/pad_ring_gen.py")),
                                   ("main a4caccefe", _blob(MAIN_PADRING))],
    "sm141064.ngspice":           [("pdk", _local(PDK))],
    "test_auto_die_avg_cell_source_is_disclosed.py":
                                  [("wt",  _local(WT / "programs/tests/"
                                     "test_auto_die_avg_cell_source_is_disclosed.py"))],
}

txt = pathlib.Path("RESULT.md").read_text()
# `name.ext:NNN` and the bare continuation form `:NNN` (which inherits the last name)
tokens = re.findall(r"`?([A-Za-z0-9_./-]+\.(?:py|tcl|ngspice)):(\d+)"
                    r"(?:-(\d+))?`?|`:(\d+)`", txt)
cites, last = [], None
for name, ln, ln2, bare in tokens:
    if name:
        last = name.split("/")[-1]
        cites.append((last, int(ln)))
        if ln2: cites.append((last, int(ln2)))
    elif bare and last:
        cites.append((last, int(bare)))
cites = sorted(set(cites))

unresolved, missing_tree = 0, 0
for base, ln in cites:
    trees = TREES.get(base)
    if not trees:
        print(f"NO RESOLVER   {base}:{ln}"); unresolved += 1; continue
    hits = []
    for tag, get in trees:
        lines = get()
        ok = 1 <= ln <= len(lines)
        hits.append((tag, ok, lines[ln-1].strip()[:86] if ok else f"(file has {len(lines)} lines)"))
    for tag, ok, text in hits:
        print(f"{'OK ' if ok else 'OUT'}  {base}:{ln:<6} [{tag}] | {text}")
    if not any(ok for _, ok, _ in hits):
        unresolved += 1
    elif len(hits) > 1 and not all(ok for _, ok, _ in hits):
        missing_tree += 1

print(f"\n{len(cites)} published coordinates; {unresolved} resolve in NO tree; "
      f"{missing_tree} resolve in only SOME of the trees the report cites "
      f"(these need the tree named in the sentence).")
sys.exit(1 if unresolved else 0)
