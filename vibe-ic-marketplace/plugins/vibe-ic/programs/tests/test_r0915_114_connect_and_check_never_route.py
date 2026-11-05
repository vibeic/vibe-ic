"""The PG reconnect block connects and checks; it does not route. R-0915-114.

MEASURED on subservient x gf180mcuD as a DIE and reproduced on spm x
gf180mcuD (lanes icsub2 and icspm5, two ICs): the block answered a
PG-terminal delta with a rip-and-relay of EVERY SIGNAL WIRE -- `detailed_route`
with no net list, the guide wrapper global-routing every net first -- and that
re-route is the step that fails. subservient dies `[ERROR DRT-1231] Pin
u_core/_3245_/ZN does not have access point`; spm's first pass dies DRT-0206
with 99 checkConnectivity breaks, ZERO of them on a supply net.

It was never owed. `_vic_pg_on_no_net` counts ONLY POWER/GROUND terminals, so
the delta is PG-only by construction -- ties, fillers, decaps, diodes, spares,
whose PG pins reach the rails BY ABUTMENT -- and `global_connect` lays no
geometry: MEASURED 9498 PG shapes before it and 9498 after, on this design's
own database.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))




SRC = (Path(__file__).resolve().parents[1]
       / "phase3_one_shot_runner.py").read_text()






















# ── (b) the antenna stage answers for its own wires ───────────────────────






def test_the_antenna_stage_still_tries_its_native_reroute_first():
    assert "-reroute" in SRC, "the fork's tool-native incremental path stays"
