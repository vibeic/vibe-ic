"""Step 32's custom step: the post-detailed-route repair (T102).

LibreLane's Classic/Chip flows repair timing only BEFORE detailed routing
(`OpenROAD.ResizerTimingPostGRT`); nothing runs repair_timing on the routed
design.  `Vibeic.PostRouteRepair` does, between `OpenROAD.DetailedRouting`
and `OpenROAD.RCX`, on the routed ODB:

1. parasitics from the router's own wires: OpenRCX with every declared
   `RCX_RULESETS` entry, each SPEF read back onto the STA corners its pattern
   names, then the vibeic/OpenROAD fork's `estimate_parasitics
   -detailed_routing` (without it the resizer's repair moves fall back to
   Steiner estimates, or segfault on stock OpenROAD).  The fork flag is
   probed against a bogus control flag; an OpenROAD that rejects it refuses
   `VIBEIC_PRR_TOOL_INCAPABLE`;
2. `repair_design`, then `repair_timing -setup`, then `repair_timing -hold`
   (hold after setup, never at setup's expense);
3. the changed cells legalized (LibreLane's own `dpl.tcl`), every created
   cell connected to its declared supply (`global_connect` with the rules the
   database carries plus `VIBEIC_PRR_PG_RULES_TCL`), and an ECO route: only
   the nets touching a created, resized or moved cell lose their wires and
   are routed again (`detailed_route -nets`);
4. antenna residue: when the ECO route added antenna-violating nets,
   OpenROAD's `repair_antennas` (the PDK's DIODE_CELL) and a scoped route of
   the new diodes' nets only;
5. re-verify: the ECO route's DRC count, `check_antennas`, and the
   before/after census on the same parasitics.

It JUDGES NOTHING and adopts nothing.  One run is one CANDIDATE; the
candidate is measured by `OpenROAD.RCX` + `OpenROAD.STAPostPNR` and adopted
or rolled back by `programs/librelane_postroute_repair.py` through
`_ppa/closure.py` (the `timing.repair_setup` actuator).  Rollback is keeping
the input state: this step never writes over it.

Shipped with the plugin, not the vibeic/librelane fork: the step is vibe-ic's
closure policy on top of the tools, and its parameters come from vibe-ic's
actuator registry.
"""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Optional, Tuple

from librelane.config import Variable
from librelane.state import DesignFormat, State
from librelane.steps.openroad import RCX, DetailedRouting, ResizerStep, _get_process_limit
from librelane.steps.step import MetricsUpdate, Step, ViewsUpdate

__all__ = ["PostRouteRepair"]

_DRT_VARS = ("DRT_THREADS", "DRT_OPT_ITERS", "DRT_ANTENNA_REPAIR_MARGIN")


@Step.factory.register()
class PostRouteRepair(ResizerStep):
    """Post-detailed-route repair on the routed ODB (flow step 32)."""

    id = "Vibeic.PostRouteRepair"
    name = "Post-Route Timing Repair (vibe-ic step 32)"

    inputs = [DesignFormat.ODB]
    outputs = [DesignFormat.ODB, DesignFormat.DEF, DesignFormat.NETLIST,
               DesignFormat.POWERED_NETLIST]

    config_vars = (
        ResizerStep.config_vars
        + [v for v in DetailedRouting.config_vars if v.name in _DRT_VARS]
        + [v for v in RCX.config_vars if v.name == "RCX_RULESETS"]
        + [
            Variable(
                "VIBEIC_PRR_SETUP_MARGIN",
                Decimal,
                "Setup slack margin for repair_timing -setup (and the setup "
                "margin hold repair must keep).",
                default=0,
                units="ns",
            ),
            Variable(
                "VIBEIC_PRR_SETUP_SEQUENCE",
                str,
                "OpenROAD repair_timing setup move sequence. 'default' keeps "
                "the tool's own sequence; 'sizeup,swap' changes cell masters "
                "without creating setup buffers on the routed design.",
                default="default",
            ),
            Variable(
                "VIBEIC_PRR_MOVE_SEQUENCE",
                str,
                "Repair operation order; hold_first is the one native-failure retry.",
                default="standard",
            ),
            Variable(
                "VIBEIC_PRR_HOLD_MARGIN",
                Decimal,
                "Hold slack margin for repair_timing -hold.",
                default=0,
                units="ns",
            ),
            Variable(
                "VIBEIC_PRR_SETUP_MAX_BUFFER_PCT",
                Decimal,
                "repair_timing -setup -max_buffer_percent.",
                default=5,
                units="%",
            ),
            Variable(
                "VIBEIC_PRR_HOLD_MAX_BUFFER_PCT",
                Decimal,
                "repair_timing -hold -max_buffer_percent (the hold-fix "
                "skill's 5 % guardrail is the default).",
                default=5,
                units="%",
            ),
            Variable(
                "VIBEIC_PRR_SETUP_REPAIR_TNS_PCT",
                Optional[Decimal],
                "repair_timing -setup -repair_tns (percent of violating "
                "endpoints); unset leaves the tool's default.",
                units="%",
            ),
            Variable(
                "VIBEIC_PRR_MAX_WIRE_LENGTH",
                Optional[Decimal],
                "repair_design -max_wire_length; unset leaves the tool's "
                "default (no wire-length buffering).",
                units="µm",
            ),
            Variable(
                "VIBEIC_PRR_SLEW_MARGIN_PCT",
                Optional[Decimal],
                "repair_design -slew_margin.",
                units="%",
            ),
            Variable(
                "VIBEIC_PRR_CAP_MARGIN_PCT",
                Optional[Decimal],
                "repair_design -cap_margin.",
                units="%",
            ),
            Variable(
                "VIBEIC_PRR_BOUNDED_DRIVE_STRENGTH",
                bool,
                "After an exact native no-op with measured max-slew residue, "
                "try the smallest legal functionally-equivalent linked-Liberty "
                "master that measurably improves the violating net.",
                default=False,
            ),
            Variable(
                "VIBEIC_PRR_TARGETED_CAP_BUFFER",
                bool,
                "Split a bounded subset of the live max-capacitance data "
                "net's ODB load pins with native insert_buffer.",
                default=False,
            ),
            Variable(
                "VIBEIC_PRR_MAX_FANOUT",
                Optional[int],
                "The fanout cap sign-off judges: the strictest set_max_fanout "
                "of the SDC this step reads (supplied by the caller with its "
                "source). repair_design meets it; every later repair in the "
                "step must keep it. Unset: the SDC declares none.",
            ),
            Variable(
                "VIBEIC_PRR_ECO_EXPANSIONS",
                int,
                "How many times a refused ECO route (the fork's DRT-0712: the "
                "scoped route added a whole-design violation) may take up the "
                "nets that share a violation with a routed net and route "
                "again.",
                default=2,
            ),
            Variable(
                "VIBEIC_PRR_ANTENNA_REPAIR",
                bool,
                "When the ECO route added antenna-violating nets, run "
                "OpenROAD's repair_antennas with the PDK's DIODE_CELL and "
                "route only the new diodes' nets again (scoped, guarded).",
                default=True,
            ),
            Variable(
                "VIBEIC_PRR_CENSUS_ONLY",
                bool,
                "Take the input census (parasitics, slack, design rules, "
                "antenna) and repair nothing: the measurement of the input "
                "route on the same instrument every candidate is measured on.",
                default=False,
            ),
            Variable(
                "VIBEIC_PRR_PG_RULES_TCL",
                Optional[str],
                "A Tcl file of add_global_connection rules (the direct deck's "
                "own, when the database came from it); registered before any "
                "cell is created.",
            ),
            Variable(
                "VIBEIC_PRR_REFILL_TCL",
                Optional[str],
                "The Tcl that re-inserts the fillers this step removed (the "
                "direct deck's own fill policy, when the database came from "
                "it). Unset: LibreLane's DECAP_CELLS/FILL_CELLS, and only when "
                "the input carried fillers.",
            ),
        ]
    )

    def get_script_path(self) -> str:
        return os.path.join(os.path.dirname(__file__), "postroute_repair.tcl")

    def run(self, state_in: State, **kwargs) -> Tuple[ViewsUpdate, MetricsUpdate]:
        kwargs, env = self.extract_env(kwargs)
        env["DRT_THREADS"] = env.get("DRT_THREADS", str(_get_process_limit()))
        views, metrics = super().run(state_in, env=env, **kwargs)
        if metrics.get("vibeic__prr__changed") == 0:
            # The script stopped before writing anything: the candidate IS
            # the input database, byte for byte.
            views = {fmt: state_in[fmt] for fmt in self.outputs
                     if state_in.get(fmt) is not None}
        return views, metrics
