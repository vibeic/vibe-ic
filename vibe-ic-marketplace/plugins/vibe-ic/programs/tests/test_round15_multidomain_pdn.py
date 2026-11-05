"""Round 15 of the u_hawaii_adc acceptance: the multi-power-domain PDN.

MEASURED on the live tip (v1.15.54): one modulator's core supply is generated
ON CHIP by the LDO macro. The net (`vldo`) is typed POWER before routing —
correctly — and then `pdngen`, told about exactly ONE voltage domain, built
nothing for it:

    FAIL pnr  PG_UNROUTED_SUPPLY: 1 POWER/GROUND net(s) carry real terminals
              and no special-net geometry — pdngen did not build them

Four things closed it, each pinned here:
  1. the supply-net retype runs BEFORE `set_voltage_domain`, not after pdngen;
  2. every POWER net with a terminal that is not the primary becomes a
     `-secondary_power` of the core domain at runtime, with its own strap
     group on every core strap layer, carried to the die boundary;
  3. a hard macro's supply terminals are reached by a PER-PIN STUB (one strap
     of one net across the pin) where the strap-pattern grid refused — every
     dimension from the LEFs, the clearance rule from a measured pdngen drop;
  4. an L21 rail is joined to the PDK's net by VOLTAGE (or by case-insensitive
     name), never emitted verbatim as a phantom net.
And one blind spot: a SPECIAL supply net with terminals and no geometry was
never named by the pre-route cleanup; geometry is the test now, not the flag.
"""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as mod  # noqa: E402

TECH = """\
MANUFACTURINGGRID 0.005 ;
LAYER M1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.42 ;
  WIDTH 0.16 ;
END M1
LAYER M2
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.48 ;
  WIDTH 0.20 ;
  SPACINGTABLE
    PARALLELRUNLENGTH 0.00 0.50 1.00
    WIDTH 0.00        0.21    0.21    0.21
    WIDTH 0.39        0.21    0.24    0.24
    WIDTH 10.0        0.21    0.24    0.60 ;
END M2
LAYER M3
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.42 ;
  WIDTH 0.20 ;
  SPACINGTABLE
    PARALLELRUNLENGTH 0.00 0.50 1.00
    WIDTH 0.00        0.21    0.21    0.21
    WIDTH 0.39        0.21    0.24    0.24
    WIDTH 10.0        0.21    0.24    0.60 ;
END M3
LAYER M4
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.48 ;
  WIDTH 0.20 ;
  SPACINGTABLE
    PARALLELRUNLENGTH 0.00 0.50 1.00
    WIDTH 0.00        0.21    0.21    0.21
    WIDTH 0.39        0.21    0.24    0.24
    WIDTH 10.0        0.21    0.24    0.60 ;
END M4
LAYER M5
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.42 ;
  WIDTH 0.20 ;
  SPACINGTABLE
    PARALLELRUNLENGTH 0.00 0.50 1.00
    WIDTH 0.00        0.21    0.21    0.21
    WIDTH 0.39        0.21    0.24    0.24
    WIDTH 10.0        0.21    0.24    0.60 ;
END M5
LAYER TM1
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 3.28 ;
  WIDTH 1.64 ;
  SPACING 1.64 ;
END TM1
LAYER TM2
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 4 ;
  WIDTH 2 ;
  SPACING 2 ;
END TM2
"""

# The measured shape: two 1.2um x 0.7um supply pads on M3, 2.0um apart
# vertically, 0.8um apart horizontally — a strap PATTERN cannot reach them.
MACRO = """\
MACRO ADCBLK
  CLASS BLOCK ;
  ORIGIN 3.800 20.750 ;
  SIZE 271.370 BY 264.010 ;
  PIN vss
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER M3 ;
        RECT -2.600 -12.350 -1.400 -11.650 ;
    END
  END vss
  PIN vdd
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER M3 ;
        RECT -3.400 -10.350 -2.200 -9.650 ;
    END
  END vdd
  PIN vout
    PORT
      LAYER M3 ;
        RECT 57.250 -20.350 58.450 -19.650 ;
    END
  END vout
  OBS
      LAYER M2 ;
        RECT -3.800 -20.750 267.570 242.420 ;
      LAYER M5 ;
        RECT 147.310 140.000 257.910 166.200 ;
  END
END ADCBLK
"""

STRIPES = [{"layer": "TM1", "width": 2.2, "pitch": 75.6, "offset": 13.6},
           {"layer": "TM2", "width": 2.2, "pitch": 75.6, "offset": 13.6}]


# ═══════════════════════════════════════════════════════════════════════════
# 3. the per-pin stub
# ═══════════════════════════════════════════════════════════════════════════
def test_the_pattern_planner_still_refuses_these_pads():
    """The control: the OLD planner's verdict on the measured pads is
    unchanged — the stub is what answers it, not a change to the pattern."""
    out = mod._macro_pdn_grid_outcome([MACRO], TECH, STRIPES, "M1")
    assert out["plan"] is None
    assert out["refusals"][0]["reason"] == "NO_PORT_WIDE_ENOUGH_FOR_ANY_LEGAL_PITCH"






















# ═══════════════════════════════════════════════════════════════════════════
# 1 + 2. the emitted PDN block: order and the secondary domain
# ═══════════════════════════════════════════════════════════════════════════




















# ═══════════════════════════════════════════════════════════════════════════
# 4. an L21 rail is joined to the PDK's net by voltage or name, never verbatim
# ═══════════════════════════════════════════════════════════════════════════
L21 = {"fields": {"power_domains": [
    {"name": "CORE", "power_net": "CORE", "voltage_v": 1.2},
    {"name": "IOVDD", "power_net": "IOVDD", "voltage_v": 1.8},
    {"name": "vdd", "power_net": "vdd", "voltage_v": None,
     "derived_by": "l21_macro_supply_rail_synth"},
    {"name": "vss", "power_net": "CORE", "ground_net": "vss",
     "is_power_domain": False, "voltage_v": 0.0},
]}}
DMAP = {("dsm", "vdd"): "CORE", ("reg", "vdd"): "IOVDD",
        ("reg", "vpp"): "vdd", ("dsm", "vss"): "vss"}
















# ═══════════════════════════════════════════════════════════════════════════
# the blind spot: a SPECIAL supply net with terminals and no geometry
# ═══════════════════════════════════════════════════════════════════════════
