"""v1.3.83 — commercial-PDK sign-off bridge regressions (commercial_pdk_v1382/v1383fix
close-loop):

1. streamout must force macro_resolution_mode=2 (commercial LEFs ship no
   FOREIGN, so macro_layout_files was silently ignored -> GDS held ZERO
   std-cell FEOL -> vacuous FEOL PASSes + phantom min-area on pin rects).
2. bridge/signoff_config.json drives the std-cell exclusion marker + dummy
   fill; discovery lands them on PdkConfig.
3. step_lvs: calibre-binary-absent must FALL THROUGH to the open-source
   Magic+netgen route when the bridge ships the tech (STRONG DOCTRINE — no
   commercial-EDA-tool excuse), not dead-end ENV_UNAVAILABLE.
4. dashboard web daemon retries ports and records the actually-bound URL
   (a stale daemon on 8787 used to silently serve the PREVIOUS run).
"""
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: A LOOK INTERVAL and two LOOK COUNTS — never a runtime bound. Nothing here
#: decides "too slow"; the only thing that ends a wait is the subject making no
#: forward progress at all.
_LOOK_S = 0.1
_STALL_LOOKS = 300
_MAX_LOOKS = 200_000


#: CLK_TCK once — `/proc` reports thread CPU in clock ticks.






def test_pdkconfig_has_signoff_bridge_fields():
    pdk = p3.PdkConfig(name="x", liberty="l", tech_lef="t", cell_lef="c",
                       cell_gds=None, site="s", drc_deck=None)
    assert pdk.stdcell_marker_layer is None
    assert pdk.bridge_magicrc is None
    assert pdk.bridge_netgen_setup is None
    assert pdk.dummy_fill is None










_TECH_LEF = (
    "LAYER MET1\n  TYPE ROUTING ;\n  WIDTH 0.23 ;\n  SPACING 0.23 ;\n"
    "  SPACING 0.6 RANGE 10.001 100000 ;\n  MINWIDTH 0.23 ;\nEND MET1\n"
    "LAYER MET2\n  TYPE ROUTING ;\n  SPACING 0.28 ;\nEND MET2\n")
