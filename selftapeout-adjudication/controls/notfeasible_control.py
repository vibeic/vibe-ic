#!/usr/bin/env python3
"""J79 — the two NOT FEASIBLE verdicts, re-run from their SOURCES as a standing control.

These are the only two tiers in the report that REFUSE a chip, so they are the two
where a failure to reproduce would move a verdict.  J59 and J67 ran this by hand on
two earlier dispatches; a hand-run control is a control you have to remember, so the
rule now lives in a file that prints PASS/FAIL against the published readings.

Nothing here reads RESULT.md.  Every expected value below is typed from what the
report PUBLISHES, so a disagreement is a disagreement between the report and the
tree, which is the whole point.
"""
import os, re, sys, glob

PDK  = os.environ.get("J79_PDK", "/home/reyerchu/_gf180_priv/pdk/gf180mcuD")
FRAM = os.environ.get("J79_FRAM",
        "/home/reyerchu/_gf180_priv/bdata/ic/edge_llm_accel/input/pdk_local/fakeram45")

EXPECT = {
    "flavors": 13,
    "tokens": ["03v3", "05v0", "06v0", "10v0"],
    "files_naming_1v2": 0,
    "corner_libs_absent": ["cornerMOShv.lib", "cornerMOSlv.lib", "cornerRES.lib", "cornerCAP.lib"],
    "fakeram_views": 3,
    "fakeram_obs_records": 587,
    "mask_views": 0,
}

fails = []
def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name:34} got={got!r}")
    if not ok:
        print(f"        expected={want!r}")
        fails.append(name)

print(f"=== u_hawaii_adc : the PROCESS half ===  ({PDK})")

# device flavors: .lib/.spice model sections under libs.tech/ngspice
flavors = set()
for p in glob.glob(f"{PDK}/libs.tech/ngspice/**/*", recursive=True):
    if not os.path.isfile(p):
        continue
    try:
        txt = open(p, errors="replace").read()
    except OSError:
        continue
    for m in re.finditer(r"^\s*\.subckt\s+([np]fet_\w+)", txt, re.M | re.I):
        flavors.add(m.group(1).lower())
flavors = sorted(flavors)
print("  flavors:", " ".join(flavors))
check("device flavors in libs.tech/ngspice", len(flavors), EXPECT["flavors"])

tokens = sorted({t for f in flavors for t in re.findall(r"\d\dv\d", f)})
check("voltage tokens across all flavors", tokens, EXPECT["tokens"])

# any file under libs.tech naming a 1.2 V device or corner
# NOTE (the first version of this check was WRONG and the control caught it):
#   `1\.2\s*v` case-insensitively matches "V1.2 Via1 spacing = 0.26" -- a DRC RULE
#   NUMBER followed by the layer name, inside a BINARY .gds test fixture.  A rule id
#   is not a voltage, and a text predicate run over a GDS matches noise.  So: text
#   files only, and the V must be a unit (not the first letter of "Via").
#   The positive control below also showed `\b1v2\b` does NOT match `nfet_1v2`,
#   because `_` is a word character -- so the bound is on DIGITS, not on \b.
pat = re.compile(r"(?<![0-9a-zA-Z])1v2(?![0-9])|1p2(?![0-9])|1\.2\s*V(?![A-Za-z])")
hits = []
for p in glob.glob(f"{PDK}/libs.tech/**/*", recursive=True):
    if not os.path.isfile(p):
        continue
    if pat.search(os.path.basename(p)):
        hits.append(p); continue
    try:
        raw = open(p, "rb").read()
    except OSError:
        continue
    if b"\x00" in raw[:8192]:          # binary: not a place a device name is written
        continue
    if pat.search(raw.decode("utf-8", "replace")):
        hits.append(p)
check("files naming 1.2 V under libs.tech", len(hits), EXPECT["files_naming_1v2"])
if hits:
    for h in hits[:5]:
        print("        hit:", h)

present = [c for c in EXPECT["corner_libs_absent"]
           if glob.glob(f"{PDK}/**/{c}", recursive=True)]
check("corner libs PRESENT (want none)", present, [])

print(f"\n=== edge_llm_accel : the UNSTREAMABLE-MACRO half ===  ({FRAM})")
views = sorted(os.path.basename(p) for p in glob.glob(f"{FRAM}/*") if os.path.isfile(p))
print("  views:", " ".join(views))
check("views present", len(views), EXPECT["fakeram_views"])

lef = open(f"{FRAM}/fakeram45_2048x39.lef", errors="replace").read()
for line in lef.splitlines():
    if line.strip().startswith(("VERSION", "MACRO", "SIZE", "CLASS")):
        print("  |", line.strip())
n_obs = len(re.findall(r"^\s*(OBS|LAYER|RECT)\b", lef, re.M))
check("OBS/LAYER/RECT records in the LEF", n_obs, EXPECT["fakeram_obs_records"])

root = os.environ.get("J79_DESIGN_ROOT", "/home/reyerchu/_gf180_priv/bdata/ic/edge_llm_accel")
mask = [p for p in glob.glob(f"{root}/**/*", recursive=True)
        if p.lower().endswith((".gds", ".gds.gz", ".oas", ".oasis"))]
check("mask-level views under the design tree", len(mask), EXPECT["mask_views"])

print()
if fails:
    print(f"CONTROL FAILED — {len(fails)} reading(s) moved: {fails}")
    print("A verdict may move.  Do NOT publish until this is resolved.")
    sys.exit(1)
print("CONTROL HELD — both NOT FEASIBLE verdicts reproduce from their sources.")
