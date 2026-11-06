"""A placed hard macro's supply pins need a grid of their own.

`pdngen` builds one grid per `define_pdn_grid`. The core grid straps the
standard-cell rows and does nothing to a hard macro's supply pins, because
those pins are not on the rows. `define_pdn_grid -macro` is the only construct
that reaches them, and the flow emitted none — so a macro placed FIXED, with
its pins bound BY NAME to the rails, arrived at power analysis with no
conductor on them at all:

    [INFO  PDN-0001] Inserting grid: grid           <- one grid, the core's
    [WARNING PSM-0038] Unconnected shape on net <rail> at (...), layer: <pin layer>
    [WARNING PSM-0039] Unconnected instance <inst>/<pin> at (...).
    [ERROR   PSM-0069] Check connectivity failed on <rail>.

Both rules the plan encodes were measured, not reasoned:

  * straps on BOTH core strap layers make the macro grid self-sufficient and it
    bonds to itself — the net goes from one electrical island to two, with the
    macro pins in the smaller one. One strap layer, perpendicular to the core's
    other strap, leaves it nothing to bond to except the core.
  * a strap PATTERN cannot be guaranteed to cross a port narrower than its own
    pitch, and `pdngen` refuses a pitch below 2*width+spacing. Ports below that
    are reported rather than silently missed.
"""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phase3_one_shot_runner import _macro_pg_ports_from_lef

# A two-layer-plus stack: L1 rails, L2/L3/L4 routing, alternating directions.
TECH_LEF = """
LAYER L1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.56 ;
  WIDTH 0.23 ;
END L1
LAYER L2
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.66 ;
  WIDTH 0.28 ;
END L2
LAYER L3
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.56 ;
  WIDTH 0.28 ;
END L3
LAYER L4
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.56 ;
  WIDTH 0.28 ;
END L4
LAYER L5
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.61 ;
  WIDTH 0.44 ;
END L5
"""

# One macro. Supply pins on L3. Each pin has a WIDE port (12um across) and a
# SLIVER port (0.6um across) — the shape a real hard macro's boundary pins take.
MACRO_LEF = """
MACRO BLOCKA
    CLASS BLOCK ;
    SIZE 400 BY 140 ;
    PIN PWRA
        DIRECTION INPUT ;
        USE POWER ;
        PORT
         LAYER L3 ;
          RECT 0 80 0.6 90 ;
        END
        PORT
         LAYER L3 ;
          RECT 160 0 172 0.6 ;
        END
    END PWRA
    PIN GNDA
        DIRECTION INPUT ;
        USE GROUND ;
        PORT
         LAYER L3 ;
          RECT 120 0 132 0.6 ;
        END
    END GNDA
    PIN SIGA
        DIRECTION INPUT ;
        USE SIGNAL ;
        PORT
         LAYER L3 ;
          RECT 10 10 20 20 ;
        END
    END SIGA
END BLOCKA
"""

STRIPES = [{"layer": "L4", "width": 1.12, "pitch": 22.4, "offset": 5.6},
           {"layer": "L5", "width": 1.76, "pitch": 24.4, "offset": 6.1}]


def test_pg_ports_are_read_with_their_sizes():
    ports = _macro_pg_ports_from_lef(MACRO_LEF)
    assert {(p["pin"], p["use"]) for p in ports} == {
        ("PWRA", "POWER"), ("GNDA", "GROUND")}, "SIGNAL pins must not appear"
    assert all(p["master"] == "BLOCKA" and p["layer"] == "L3" for p in ports)
    # the sizes are the load-bearing part
    assert sorted(round(p["w"], 3) for p in ports) == [0.6, 12.0, 12.0]
