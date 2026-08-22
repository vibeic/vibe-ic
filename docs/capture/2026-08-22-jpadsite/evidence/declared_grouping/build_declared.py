"""Build the pad-ring input for sha256 on gf180mcuD from DECLARED facts only.

Every value below is either (a) read out of the PDK's own files, (b) read out
of the design's own synthesised netlist, or (c) the die the re-adjudication
measured. The ONE thing this script chooses is how the design's 77 port bits
split across the four sides — a pin-out decision the design has never made —
and it chooses the balanced split in the netlist's own port order and says so.
"""
import json, os, re, sys

OUT = sys.argv[1]
ROT_V = sys.argv[2] if len(sys.argv) > 2 else "R0"
NETLIST = "/design/netlist.v"
DIE_UM = 2262.0            # the re-adjudication's measured die
UNITS = 1000

# ── the design's own ports, in the netlist's own order ─────────────────────
t = open(NETLIST).read()
bits = []
for ln in t.splitlines():
    m = re.match(r"\s*(input|output|inout)\s+(?:wire\s+)?(?:\[(\d+):(\d+)\]\s*)?(\w+)\s*;", ln)
    if not m:
        continue
    if m.group(2) is None:
        bits.append(m.group(4))
    else:
        hi, lo = int(m.group(2)), int(m.group(3))
        step = -1 if hi >= lo else 1
        bits += [f"{m.group(4)}[{i}]" for i in range(hi, lo + step, step)]
assert len(bits) == 77, len(bits)

# ── the PDK's own declarations, parsed from its files ──────────────────────
PDK = "/foss/pdks/gf180mcuD"
cfg_io = open(f"{PDK}/libs.tech/librelane/gf180mcu_fd_io/config.tcl").read()
cfg_top = open(f"{PDK}/libs.tech/librelane/config.tcl").read()
lib = re.search(r"set ::env\(PAD_CELL_LIBRARY\)\s+(\S+)", cfg_top).group(1)
def one(var, text=cfg_io):
    return re.search(rf'set ::env\({var}\)\s+"([^"]+)"', text).group(1)
site = one("PAD_SITE_NAME"); corner_site = one("PAD_CORNER_SITE_NAME")
edge = float(one("PAD_EDGE_SPACING"))
corner_master = one("PAD_CORNER").replace("$::env(PAD_CELL_LIBRARY)", lib)
fillers = [w.replace("$::env(PAD_CELL_LIBRARY)", lib).rstrip("\\") for w in
           re.search(r'set ::env\(PAD_FILLERS\)\s+"\\\n(.*?)"', cfg_io, re.S)
           .group(1).split()]
# the bidirectional IO master the PDK's own PAD_PLACE_IO_TERMINALS names
pad_master = f"{lib}__bi_t"

# ── the one choice, stated: a balanced split in the netlist's port order ───
# THE DESIGN'S OWN DECLARED GROUPING (L3 "Physical Pad Placement", L9 9.2.1):
#   N = address[7:0] + write_data[31:0] (40)   S = read_data[31:0] + error (33)
#   E = clk, reset_n (2)                       W = cs, we (2)
byname = {b: b for b in bits}
N = [b for b in bits if b.startswith("address") or b.startswith("write_data")]
S = [b for b in bits if b.startswith("read_data") or b == "error"]
E = [b for b in bits if b in ("clk", "reset_n")]
W = [b for b in bits if b in ("cs", "we")]
assert len(N)==40 and len(S)==33 and len(E)==2 and len(W)==2, (len(N),len(S),len(E),len(W))
sides = {"S": S, "E": E, "N": N, "W": W}
inst = lambda b: "pad_" + b.replace("[", "_").replace("]", "")

os.makedirs(f"{OUT}/phase3/stage3/pnr", exist_ok=True)
D = int(DIE_UM * UNITS)
comps = [f"- u_core {lib}__cor + PLACED ( 1000000 1000000 ) N ;"]
comps = [f"- {inst(b)} {pad_master} + UNPLACED ;" for s in sides for b in sides[s]]
pins = "\n".join(
    f"- {b} + NET {b} + DIRECTION INPUT + USE SIGNAL\n"
    f"  + LAYER Metal2 ( -70 -70 ) ( 70 70 ) + PLACED ( 1000 1000 ) N ;"
    for b in bits)
open(f"{OUT}/phase3/stage3/pnr/floorplan.def", "w").write(
    f'VERSION 5.8 ;\nDIVIDERCHAR "/" ;\nBUSBITCHARS "[]" ;\n'
    f"DESIGN sha256 ;\nUNITS DISTANCE MICRONS {UNITS} ;\n"
    f"DIEAREA ( 0 0 ) ( {D} {D} ) ;\n"
    f"COMPONENTS {len(comps)} ;\n" + "\n".join(comps) + "\nEND COMPONENTS\n"
    f"PINS {len(bits)} ;\n{pins}\nEND PINS\nEND DESIGN\n")

conf = {
    "PAD_SOUTH": [inst(b) for b in sides["S"]],
    "PAD_EAST":  [inst(b) for b in sides["E"]],
    "PAD_NORTH": [inst(b) for b in sides["N"]],
    "PAD_WEST":  [inst(b) for b in sides["W"]],
    "PAD_SITE_NAME": site, "PAD_CORNER_SITE_NAME": corner_site,
    "PAD_EDGE_SPACING": edge,
    "PAD_ROTATION_HORIZONTAL": "R0",   # librelane default; the PDK sets none
    "PAD_ROTATION_VERTICAL": ROT_V,
    "PAD_ROTATION_CORNER": "R0",
    "PAD_CORNER": corner_master, "PAD_FILLERS": fillers,
    "SIGNAL_MAP": {inst(b): b for s in sides for b in sides[s]},
}
open(f"{OUT}/phase3/stage3/pnr/pad_assignment.json", "w").write(
    json.dumps(conf, indent=2))
print(json.dumps({"pad_master": pad_master, "corner": corner_master,
                  "site": site, "corner_site": corner_site,
                  "edge_spacing_um": edge, "fillers": fillers,
                  "pads_per_side": {s: len(v) for s, v in sides.items()},
                  "die_um": DIE_UM, "PAD_ROTATION_VERTICAL": ROT_V}, indent=2))
