"""benchmark-spm-asap7 — regression pins for the ASAP7 / PDK-agnostic HIGH
cluster in phase3_one_shot_runner.py:

  * #162 A1 — named registry PDK resolution + B3 (#176) loud-warn on a
    registry-declared-but-unbranched name (never a silent sky130A fallback).
  * #163 A2 — merge the 5 split ASAP7 Liberty functional groups into one
    ``library{}`` (union of cells, dedup, renamed) so synth sees the DFFs.
  * #177 A3 — a cached synth netlist is reused ONLY when its masters exist in
    the ACTIVE PDK liberty (no wrong-PDK provenance laundering).
  * #164 A4 — SDC numerics scale into the liberty's declared time/cap units
    (ASAP7 ps/fF) while an ns/pF PDK (sky130) stays byte-identical.
  * #165 A5 — ``place_pins`` hor/ver layers derive from the tech LEF routing
    DIRECTIONs (ASAP7 M2=HOR/M3=VER, the OPPOSITE of sky130) with a legacy
    fallback.
  * #167 A7 — the staged tech LEF normalizes a negative routing-layer OFFSET
    to its non-negative pitch-equivalent (ASAP7 M2 OFFSET -0.27 ≡ 0).
  * #158 — the auto die-sizer floors the die side at the IO-pin perimeter.

chip/PDK-AGNOSTIC: synthetic Liberty / tech-LEF fixtures only; no chip/SKU
literal. Every fixture mirrors the real ASAP7 token shapes.
"""
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# ---------------------------------------------------------------------------
# #162 A1 / #176 B3 — registry resolution, no silent sky130A fallback
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# #163 A2 — merge split Liberty groups
# ---------------------------------------------------------------------------
_GRP_A = """\
library (asap7sc7p5t_SIMPLE) {
  time_unit : "1ps";
  cell (INVx1_ASAP7_75t_R) { area : 0.1 ; pin(Y){direction:output;} }
  cell (BUFx2_ASAP7_75t_R) { area : 0.2 ; pin(Y){direction:output;} }
}
"""
_GRP_B = """\
library (asap7sc7p5t_SEQ) {
  cell (DFFHQNx1_ASAP7_75t_R) { area : 0.5 ; ff(IQ,IQN){} }
  cell (BUFx2_ASAP7_75t_R) { area : 0.2 ; pin(Y){direction:output;} }
}
"""


def test_a2_merge_unions_cells_dedups_and_renames_library():
    merged = R._merge_liberty_texts(_GRP_A, [_GRP_B], lib_name="asap7_merged")
    # DFF from the SEQ group is now present (the whole point — synth sees FFs)
    assert "DFFHQNx1_ASAP7_75t_R" in merged
    assert "INVx1_ASAP7_75t_R" in merged
    # library renamed to the merged name
    assert "library (asap7_merged)" in merged
    # BUFx2 appears in BOTH groups but is deduped to a SINGLE cell block
    assert merged.count("cell (BUFx2_ASAP7_75t_R)") == 1


# ---------------------------------------------------------------------------
# #177 A3 — no wrong-PDK provenance laundering
# ---------------------------------------------------------------------------
_LIB_ASAP7 = ("library(x){\n cell (INVx1_ASAP7_75t_R){}\n"
              " cell (DFFHQNx1_ASAP7_75t_R){}\n}\n")








# ---------------------------------------------------------------------------
# #164 A4 — SDC unit scaling
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# #165 A5 — pin-layer direction resolution
# ---------------------------------------------------------------------------
_ASAP7_TLEF = """\
LAYER M1
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
LAYER M2
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
LAYER M3
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
"""
_SKY_TLEF = """\
LAYER met1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
LAYER met2
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
LAYER met3
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
"""








# ---------------------------------------------------------------------------
# #167 A7 — negative-OFFSET normalization in the staged tech LEF
# ---------------------------------------------------------------------------
_TLEF_NEG_OFFSET = """\
LAYER M1
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
 OFFSET 0.0 ;
 PITCH 0.036 ;
LAYER M2
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
 OFFSET -0.27 ;
 PITCH 0.045 ;
"""




# ---------------------------------------------------------------------------
# #158 — pin-perimeter die floor
# ---------------------------------------------------------------------------
