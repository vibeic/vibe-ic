import json, os, re, sys
OUT, DIE_UM, UNITS = sys.argv[1], float(sys.argv[2]), 1000
bits=[]
for ln in open("/design/netlist.v"):
    m=re.match(r"\s*(input|output|inout)\s+(?:wire\s+)?(?:\[(\d+):(\d+)\]\s*)?(\w+)\s*;", ln)
    if not m: continue
    if m.group(2) is None: bits.append(m.group(4))
    else:
        hi,lo=int(m.group(2)),int(m.group(3)); st=-1 if hi>=lo else 1
        bits+= [f"{m.group(4)}[{i}]" for i in range(hi,lo+st,st)]
assert len(bits)==77
PDK="/foss/pdks/sky130A"; cfg=open(f"{PDK}/libs.tech/librelane/sky130_ef_io/config.tcl").read()
one=lambda v: re.search(rf'set ::env\({v}\)\s+"([^"]+)"', cfg).group(1)
site, csite, edge = one("PAD_SITE_NAME"), one("PAD_CORNER_SITE_NAME"), float(one("PAD_EDGE_SPACING"))
corner = one("PAD_CORNER")
fillers=[w.rstrip(chr(92)) for w in re.search(r'set ::env\(PAD_FILLERS\)\s+"\\\n(.*?)"', cfg, re.S).group(1).split()]
pad_master="sky130_ef_io__gpiov2_pad"          # the PDK's own PAD_CELLS "sky130_io*" 80,200
# THE DESIGN'S DECLARED GROUPING (L3 / L9 9.2.1)
N=[b for b in bits if b.startswith("address") or b.startswith("write_data")]
S=[b for b in bits if b.startswith("read_data") or b=="error"]
E=[b for b in bits if b in ("clk","reset_n")]; W=[b for b in bits if b in ("cs","we")]
assert (len(N),len(S),len(E),len(W))==(40,33,2,2)
sides={"S":S,"E":E,"N":N,"W":W}
inst=lambda b:"pad_"+b.replace("[","_").replace("]","")
os.makedirs(f"{OUT}/phase3/stage3/pnr",exist_ok=True); D=int(DIE_UM*UNITS)
comps=[f"- {inst(b)} {pad_master} + UNPLACED ;" for s in sides for b in sides[s]]
pins="\n".join(f"- {b} + NET {b} + DIRECTION INPUT + USE SIGNAL\n  + LAYER met2 ( -70 -70 ) ( 70 70 ) + PLACED ( 1000 1000 ) N ;" for b in bits)
open(f"{OUT}/phase3/stage3/pnr/floorplan.def","w").write(
 f'VERSION 5.8 ;\nDIVIDERCHAR "/" ;\nBUSBITCHARS "[]" ;\nDESIGN sha256 ;\nUNITS DISTANCE MICRONS {UNITS} ;\n'
 f"DIEAREA ( 0 0 ) ( {D} {D} ) ;\nCOMPONENTS {len(comps)} ;\n"+"\n".join(comps)+
 f"\nEND COMPONENTS\nPINS {len(bits)} ;\n{pins}\nEND PINS\nEND DESIGN\n")
json.dump({"PAD_SOUTH":[inst(b) for b in S],"PAD_EAST":[inst(b) for b in E],
 "PAD_NORTH":[inst(b) for b in N],"PAD_WEST":[inst(b) for b in W],
 "PAD_SITE_NAME":site,"PAD_CORNER_SITE_NAME":csite,"PAD_EDGE_SPACING":edge,
 "PAD_ROTATION_HORIZONTAL":"R0","PAD_ROTATION_VERTICAL":"R0","PAD_ROTATION_CORNER":"R0",
 "PAD_CORNER":corner,"PAD_FILLERS":fillers,"SIGNAL_MAP":{inst(b):b for s in sides for b in sides[s]}},
 open(f"{OUT}/phase3/stage3/pnr/pad_assignment.json","w"), indent=2)
print(f"  built: die {DIE_UM} um | pad {pad_master} | corner {corner} | edge {edge} | fillers {len(fillers)}")
