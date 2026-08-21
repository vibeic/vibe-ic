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
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phase3_one_shot_runner import (  # noqa: E402
    _build_macro_pdn_grid_tcl,
    _macro_pdn_grid_plan,
    _macro_pg_ports_from_lef,
)

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


def test_a_design_with_no_hard_macro_emits_nothing():
    """Byte-identical pnr.tcl for every design that has no hard macro."""
    assert _macro_pdn_grid_plan([], TECH_LEF, STRIPES, "L1") is None
    assert _build_macro_pdn_grid_tcl(None) == ""


def test_plan_picks_one_strap_layer_that_crosses_the_other():
    plan = _macro_pdn_grid_plan([MACRO_LEF], TECH_LEF, STRIPES, "L1")
    assert plan is not None
    assert plan["pin_layer"] == "L3"
    # lowest strap above the pin layer, and its partner is the OTHER strap
    assert plan["strap_layer"] == "L4"
    assert plan["partner_layer"] == "L5"
    tcl = _build_macro_pdn_grid_tcl(plan)
    # exactly ONE add_pdn_stripe: two would make the macro grid self-sufficient
    assert len(re.findall(r"add_pdn_stripe -grid macro_grid", tcl)) == 1
    assert "-layer L4 " in tcl
    assert "add_pdn_stripe -grid macro_grid -layer L5" not in tcl


def test_pitch_comes_from_the_narrowest_port_a_pattern_can_still_cross():
    plan = _macro_pdn_grid_plan([MACRO_LEF], TECH_LEF, STRIPES, "L1")
    # floor = 2*width + layer min width  = 2*1.12 + 0.28
    assert plan["pitch_floor"] == pytest.approx(2.52)
    # the 0.6um slivers are below the floor; the 12um ports set the pitch
    assert plan["pitch"] == pytest.approx(12.0)


def test_ports_no_legal_pitch_can_reach_are_reported_not_dropped():
    plan = _macro_pdn_grid_plan([MACRO_LEF], TECH_LEF, STRIPES, "L1")
    assert plan["unreachable"] == [("BLOCKA", "PWRA", 0.6)]


def test_no_strap_layer_above_the_pin_layer_means_no_plan():
    """A macro whose pins are on (or above) the top strap cannot be strapped
    from above; say so by planning nothing rather than emitting a grid that
    connects to nothing."""
    high = MACRO_LEF.replace("LAYER L3 ;", "LAYER L5 ;")
    assert _macro_pdn_grid_plan([high], TECH_LEF, STRIPES, "L1") is None


def test_a_single_strap_layer_gives_no_partner_and_so_no_macro_grid():
    """With only one strap layer there is nothing for the macro grid to bond
    into; emitting it anyway builds the island this rule exists to avoid."""
    one = [{"layer": "L4", "width": 1.12, "pitch": 22.4, "offset": 5.6}]
    assert _macro_pdn_grid_plan([MACRO_LEF], TECH_LEF, one, "L1") is None


def test_macro_with_no_pg_pins_plans_nothing():
    sig_only = """
MACRO BLOCKB
    CLASS BLOCK ;
    SIZE 10 BY 10 ;
    PIN A
        DIRECTION INPUT ;
        USE SIGNAL ;
        PORT
         LAYER L3 ;
          RECT 0 0 1 1 ;
        END
    END A
END BLOCKB
"""
    assert _macro_pdn_grid_plan([sig_only], TECH_LEF, STRIPES, "L1") is None


def test_horizontal_strap_measures_the_port_across_its_own_direction():
    """The extent that matters is the one ACROSS the strap: a horizontal strap
    is crossed by a port's HEIGHT, not its width. Measuring the wrong axis
    picks a pitch that cannot reach anything."""
    # make the lowest strap above the pins horizontal by strapping L5 and L4
    # with the pins on L2 (vertical), so the lowest strap above is L3 (horiz).
    stripes = [{"layer": "L3", "width": 1.0, "pitch": 20.0, "offset": 0},
               {"layer": "L4", "width": 1.0, "pitch": 20.0, "offset": 0}]
    lef = MACRO_LEF.replace("LAYER L3 ;", "LAYER L2 ;")
    plan = _macro_pdn_grid_plan([lef], TECH_LEF, stripes, "L1")
    assert plan["strap_layer"] == "L3"
    # ports are 10 / 0.6 / 0.6 TALL; floor = 2*1.0 + 0.28 = 2.28
    assert plan["pitch"] == pytest.approx(10.0)
    assert [u[1] for u in plan["unreachable"]] == ["GNDA", "PWRA"]


def test_rendered_tcl_is_syntactically_what_pdngen_expects():
    plan = _macro_pdn_grid_plan([MACRO_LEF], TECH_LEF, STRIPES, "L1")
    tcl = _build_macro_pdn_grid_tcl(plan)
    assert "define_pdn_grid -macro -name macro_grid" in tcl
    assert "-cells {BLOCKA}" in tcl
    assert "-grid_over_pg_pins" in tcl
    assert "add_pdn_connect -grid macro_grid -layers {L3 L4}" in tcl
    assert "add_pdn_connect -grid macro_grid -layers {L4 L5}" in tcl
    # every line is a comment or an indented pdn command / continuation
    for line in tcl.splitlines():
        s = line.strip()
        assert s.startswith("#") or s.startswith("define_pdn_grid") \
            or s.startswith("add_pdn_") or s.startswith("-cells"), line
