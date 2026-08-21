import sys
from pathlib import Path
P = Path.home()/".claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.9.82/programs"
sys.path.insert(0, str(P))
import phase3_one_shot_runner as R

TOP="sha256"
HOST=Path("/home/reyerchu/_agent_scratch_sha256sky/g3eco")
PNR=HOST/"phase3/stage3/pnr"; ECO=HOST/"phase3/stage3/eco"
CW="/work/g3eco"                                    # container view
LIBD="/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd"
corner_libs={"SS":f"{LIBD}/lib/sky130_fd_sc_hd__ss_100C_1v60.lib",
             "TT":f"{LIBD}/lib/sky130_fd_sc_hd__tt_025C_1v80.lib",
             "FF":f"{LIBD}/lib/sky130_fd_sc_hd__ff_n40C_1v95_ccsnoise.lib"}
spefd=HOST/"phase3/stage3/extracted/spef_corners"
corner_spefs={c:f"{CW}/phase3/stage3/extracted/spef_corners/{TOP}.{c}.spef"
              for c in R._SPEF_CORNERS if (spefd/f"{TOP}.{c}.spef").is_file()}
start_def,basis=R._eco_start_point(PNR,TOP)
tcl=R._build_eco_repair_tcl(
    TOP, f"{LIBD}/techlef/sky130_fd_sc_hd__nom.tlef", f"{LIBD}/lef/sky130_fd_sc_hd.lef",
    corner_libs["TT"], f"{CW}/phase3/stage3/pnr", f"{CW}/phase3/stage3/eco", "met",
    corner_libs=corner_libs,
    start_def_c=f"{CW}/phase3/stage3/pnr/{start_def.name}",
    post_route_start=basis.startswith("post_route"),
    corner_spefs_c=corner_spefs, captables_c={},
    filler_masters=list(R._SKY130_FILLER_MASTERS))
out=ECO/"eco_timing_repair.tcl"; out.write_text(tcl)
print("basis          :",basis,"start:",start_def.name)
print("spef corners   :",sorted(corner_spefs))
print("deck bytes     :",len(tcl),"-> ",out)
print("mentions #766  :",tcl.count("766"))
print("read_def line  :",[l for l in tcl.splitlines() if l.startswith("read_def")])
print("read_spef lines:",[l for l in tcl.splitlines() if "read_spef" in l])
print("remove_fillers :","remove_fillers" in tcl)
