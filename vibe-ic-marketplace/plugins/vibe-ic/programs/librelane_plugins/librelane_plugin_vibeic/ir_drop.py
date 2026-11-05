"""Step 24's custom steps: the IR gate and the fork's transient solve.

`Vibeic.IRDropChecker` fails a LibreLane run unless every declared supply net
was analysed and the worst static IR drop over ALL of them is within the
declared budget (`ir_rules`, the same function vibe-ic's host-side judge
applies).  `Vibeic.TransientIR` runs the vibeic/OpenROAD fork's
`analyze_power_grid -transient` on `OpenROAD.IRDropReport`'s basis and reads
it with `dynamic_ir_vectored_emit`'s own parsers (`transient`).  Shipped with
the plugin: they are vibe-ic's gate and vibe-ic's fork command, not changes to
LibreLane.
"""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, Tuple

from librelane.config import Variable
from librelane.state import DesignFormat, State
from librelane.steps.openroad import OpenROADStep
from librelane.steps.step import MetricsUpdate, Step, StepError, StepException, ViewsUpdate

from .ir_rules import ir_findings
from .transient import transient_blocks, transient_findings

__all__ = ["IRDropChecker", "TransientIR"]


@Step.factory.register()
class IRDropChecker(Step):
    """Fails unless every declared supply net was analysed and the worst
    static IR drop over ALL of them is within the declared budget.

    Reads the per-net PSM metrics `OpenROAD.IRDropReport` leaves in the
    state; never the first-net-only `ir__drop__worst`.  An undeclared
    budget or an undetermined supply voltage fails as NOT_MEASURED rather
    than passing.
    """

    id = "Vibeic.IRDropChecker"
    name = "vibe-ic IR Drop Checker"
    long_name = "vibe-ic static IR budget and net-coverage checker"
    inputs = []
    outputs = []

    config_vars = [
        Variable(
            "VIBEIC_IR_BUDGET_PCT",
            Optional[Decimal],
            "Static IR budget as a percent of the supply voltage, from "
            "the design's declaration (vibe-ic pdk.ir_budget_pct, else "
            "ir_drop_budget_check's documented default).",
        ),
    ]

    def run(self, state_in: State, **kwargs) -> Tuple[ViewsUpdate, MetricsUpdate]:
        libs = self.toolbox.filter_views(self.config, self.config.get("LIB", self.config.get("CELL_LIBS")))
        supply = self.toolbox.get_lib_voltage(str(libs[0])) if libs else None
        budget = self.config.get("VIBEIC_IR_BUDGET_PCT")
        doc = ir_findings(dict(state_in.metrics), self.config.get("VDD_NETS") or [],
                          self.config.get("GND_NETS") or [],
                          float(supply) if supply else None,
                          float(budget) if budget is not None else None)
        if doc["verdict"] != "PASS":
            self.err(f"IR {doc['verdict']}: {doc.get('reason')}")
            raise StepError(f"vibe-ic IR {doc['verdict']}: {doc.get('reason')}")
        metrics: MetricsUpdate = {
            "vibeic__ir__analysed_net__count": len(doc["analysed_nets"]),
            "vibeic__ir__drop__worst__pct": Decimal(str(round(doc["worst_drop_pct"], 6))),
            "vibeic__ir__budget__pct": Decimal(str(doc["budget_pct"])),
        }
        return {}, metrics


@Step.factory.register()
class TransientIR(OpenROADStep):
    """The vibeic/OpenROAD fork's `analyze_power_grid -transient` on every
    VDD and GND net, on IRDropReport's basis (ODB, SDC, SPEF, resistance,
    sources).  The period is the design's own SDC clock.  With no on-die
    capacitance the solve is quasi-static -- a fixed scaling of the static
    drop -- and the record says so (`scaled_static_bound`).  With a decap it
    is genuine only when every net's droop is measurably below its
    quasi-static reference (`decap_effect`). Missing dynamic data or a decap
    the solve did not model as declared stays NOT_MEASURED.
    """

    id = "Vibeic.TransientIR"
    name = "vibe-ic Transient IR"
    long_name = "vibe-ic transient (dynamic) IR drop, OpenROAD PSM fork"
    inputs = [DesignFormat.ODB, DesignFormat.SPEF]
    outputs = []

    config_vars = OpenROADStep.config_vars + [
        Variable("VSRC_LOC_FILES", Optional[Dict[str, Path]],
                 "Map of power and ground nets to PSM location files."),
        Variable("VIBEIC_TRANSIENT_STEPS", Optional[int],
                 "Time steps per period for the transient solve."),
        Variable("VIBEIC_DECAP_CAP", Optional[Decimal],
                 "On-die decoupling capacitance in farads, passed to the tool "
                 "in the session's capacitance unit and read back; each net "
                 "is also solved quasi-static as the reference its effect is "
                 "measured against.  None -> quasi-static only."),
    ]

    def get_script_path(self):
        return os.path.join(os.path.dirname(__file__), "transient_ir.tcl")

    def run(self, state_in: State, **kwargs) -> Tuple[ViewsUpdate, MetricsUpdate]:
        import dynamic_ir_vectored_emit as dyn  # the emitter's own readers
        kwargs, env = self.extract_env(kwargs)
        spefs = self.toolbox.filter_views(self.config, state_in[DesignFormat.SPEF])
        if len(spefs) != 1:
            raise StepException(f"NOT_MEASURED: expected one SPEF for the default corner, got {len(spefs)}")
        libs = self.toolbox.filter_views(self.config, self.config.get("LIB", self.config.get("CELL_LIBS")))
        voltage = self.toolbox.get_lib_voltage(str(libs[0])) if libs else None
        if not voltage:
            raise StepException("NOT_MEASURED: no supply voltage from the library")
        sdc = state_in.get(DesignFormat.SDC) or self.config.get("PNR_SDC_FILE")
        period, period_source = dyn.derive_period_ns(Path(str(sdc)) if sdc else None)
        env["LIB_VOLTAGE"] = str(voltage)
        env["CURRENT_SPEF_DEFAULT_CORNER"] = str(spefs[0])
        env["_VIBEIC_PERIOD"] = str(period)
        views, metrics = super().run(state_in, env=env, **kwargs)
        report = open(os.path.join(self.step_dir, "transient_ir.rpt")).read()
        nets = [*(self.config.get("VDD_NETS") or []), *(self.config.get("GND_NETS") or [])]
        nets = list(dict.fromkeys([*nets, *(net for kind, net in transient_blocks(report) if kind == "psm")]))
        decap = self.config.get("VIBEIC_DECAP_CAP")
        doc = transient_findings(report, nets, float(voltage), period, period_source,
                                 decap_f=float(decap) if decap is not None else None)
        with open(os.path.join(self.step_dir, "transient_ir.json"), "w") as stream:
            json.dump(doc, stream, indent=2)
        if doc["verdict"] != "MEASURED":
            self.err(f"transient IR: {doc['reason']}")
            raise StepException(f"NOT_MEASURED: vibe-ic transient IR: {doc['reason']}")
        for net, row in doc["per_net"].items():
            metrics[f"vibeic__ir_dynamic__drop__worst__net:{net}"] = Decimal(
                str(row["dynamic_drop_v"]))
        metrics["vibeic__ir_dynamic__drop__worst"] = Decimal(str(doc["worst_dynamic_drop_v"]))
        metrics["vibeic__ir_dynamic__scaled_static_bound"] = int(doc["scaled_static_bound"])
        return views, metrics
