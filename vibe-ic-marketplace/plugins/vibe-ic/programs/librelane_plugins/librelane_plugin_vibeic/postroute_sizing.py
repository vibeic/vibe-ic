"""Routed-parasitic sizing followed by the flow's ordinary native routing steps."""
from decimal import Decimal
from pathlib import Path
from typing import Optional

from librelane.config import Variable
from librelane.state import DesignFormat
from librelane.steps import Step
from librelane.steps.openroad import RCX, ResizerStep

from .postroute_repair import PostRouteRepair


@Step.factory.register()
class RCXBeforeRepair(RCX):
    id = "Vibeic.RCXBeforeRepair"
    name = "Extract parasitics before routed sizing"


_SIZING_VARS = {
    "VIBEIC_PRR_SETUP_MARGIN", "VIBEIC_PRR_HOLD_MARGIN",
    "VIBEIC_PRR_SETUP_MAX_BUFFER_PCT", "VIBEIC_PRR_HOLD_MAX_BUFFER_PCT",
    "VIBEIC_PRR_SETUP_REPAIR_TNS_PCT", "VIBEIC_PRR_SETUP_SEQUENCE",
    "VIBEIC_PRR_MAX_WIRE_LENGTH", "VIBEIC_PRR_SLEW_MARGIN_PCT",
    "VIBEIC_PRR_CAP_MARGIN_PCT",
}


@Step.factory.register()
class PostRouteSizing(ResizerStep):
    id = "Vibeic.PostRouteSizing"
    name = "Repair timing on routed parasitics"
    inputs = [DesignFormat.ODB, DesignFormat.SPEF]
    config_vars = ResizerStep.config_vars + [
        var for var in PostRouteRepair.config_vars if var.name in _SIZING_VARS
    ] + [
        Variable(
            "VIBEIC_PRR_RECOVER_POWER_PCT", Optional[Decimal],
            "Native repair_timing -recover_power percentage, called separately "
            "before ordinary setup/hold repair. Unset disables recovery; native "
            "zero still attempts at least one endpoint.",
            units="%",
        ),
        Variable(
            "VIBEIC_PRR_MAX_UTIL_PCT", Optional[Decimal],
            "Native repair_timing -max_utilization for each recovery/setup/hold call.",
            units="%",
        ),
        Variable(
            "VIBEIC_PRR_LIMIT_SIZING_AREA", Optional[Decimal],
            "Native set_opt_config candidate/current cell-area ratio. "
            "Unset inherits the native setting.",
        ),
        Variable(
            "VIBEIC_PRR_LIMIT_SIZING_LEAKAGE", Optional[Decimal],
            "Native set_opt_config candidate/current cell-leakage ratio. "
            "Unset inherits the native setting.",
        ),
    ]

    def get_script_path(self):
        return str(Path(__file__).with_suffix(".tcl"))

    def run(self, state_in, **kwargs):
        kwargs, env = self.extract_env(kwargs)
        env["VIBEIC_ROUTED_SPEFS"] = self.value_to_tcl(state_in[DesignFormat.SPEF])
        views, metrics = super().run(state_in, env=env, **kwargs)
        if metrics.get("vibeic__postroute__changed") == 0:
            # Keep the input's fillers, wires and extracted parasitics together.
            return {}, {"vibeic__postroute__changed": 0}
        return views, metrics
