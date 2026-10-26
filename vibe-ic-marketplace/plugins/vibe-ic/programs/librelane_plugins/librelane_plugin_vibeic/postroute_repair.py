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
actuator registry. ``Vibeic.PostRouteRepairAdoption`` composes this candidate
with same-view native measurement for flows that use ``meta.substituting_steps``;
the candidate-only ID remains the host closure controller's actuator.
"""
from __future__ import annotations

import json
import hashlib
import os
import sys
from decimal import Decimal
from fnmatch import fnmatchcase
from pathlib import Path as FilePath
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Type

from librelane.common import Path
from librelane.config import Variable
from librelane.state import DesignFormat, State
from librelane.steps.openroad import (
    RCX, CheckAntennas, DetailedRouting, ResizerStep, STAPostPNR,
    _get_process_limit,
)
from librelane.steps.step import MetricsUpdate, Step, StepError, ViewsUpdate

__all__ = ["PostRouteRepair", "PostRouteRepairAdoption"]

_DRT_VARS = ("DRT_THREADS", "DRT_OPT_ITERS", "DRT_ANTENNA_REPAIR_MARGIN")
_DIAGNOSTIC_SCHEMA = "vibeic.postroute_diagnostic_spef_authority.v1"


def _sha256(path: FilePath) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _identity(path: Any) -> Dict[str, str]:
    resolved = FilePath(str(path)).resolve(strict=True)
    return {"path": str(resolved), "sha256": _sha256(resolved)}


def _tcl_word(value: str) -> str:
    if any(character in value for character in "{}\x00"):
        raise StepError("PRR_DIAGNOSTIC_AUTHORITY_TCL_UNSAFE: path/pattern contains a brace")
    return "{" + value + "}"


def _diagnostic_spef_env(
        config: Mapping[str, Any], odb: Any, netlist: Any) -> Dict[str, str]:
    """Validate fixture-only electrical evidence, never extracted-RCX/signoff authority."""
    authority_value = config.get("VIBEIC_PRR_DIAGNOSTIC_SPEF_AUTHORITY")
    if authority_value is None:
        return {}
    try:
        authority_path = FilePath(str(authority_value)).resolve(strict=True)
        authority = json.loads(authority_path.read_text())
        if set(authority) != {"schema", "design_name", "input_odb",
                              "input_netlists", "scenes"}:
            raise ValueError("authority fields are not exact")
        if authority["schema"] != _DIAGNOSTIC_SCHEMA:
            raise ValueError("authority schema mismatch")
        if authority["design_name"] != str(config.get("DESIGN_NAME")):
            raise ValueError("design identity mismatch")
        if authority["input_odb"] != _identity(odb):
            raise ValueError("input ODB identity mismatch")
        if authority["input_netlists"] != [_identity(netlist)]:
            raise ValueError("canonical State NETLIST identity mismatch")
        corners = config.get("STA_CORNERS") or []
        if not isinstance(corners, (list, tuple)) or not corners or not all(
                isinstance(corner, str) and corner for corner in corners):
            raise ValueError("declared corner population is absent")
        scenes = authority["scenes"]
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("diagnostic scene population is absent")
        covered = []
        mapping = []
        for scene in scenes:
            if not isinstance(scene, dict) or set(scene) != {"pattern", "corners", "spef"}:
                raise ValueError("diagnostic scene fields are not exact")
            pattern, declared, spef = scene["pattern"], scene["corners"], scene["spef"]
            if not isinstance(pattern, str) or not pattern:
                raise ValueError("diagnostic scene pattern is absent")
            matched = [corner for corner in corners if fnmatchcase(corner, pattern)]
            if declared != matched or not matched:
                raise ValueError(f"diagnostic scene/corner mismatch for {pattern}")
            if any(corner in covered for corner in matched):
                raise ValueError(f"diagnostic scene overlap for {pattern}")
            if spef != _identity(spef.get("path") if isinstance(spef, dict) else ""):
                raise ValueError(f"diagnostic SPEF identity mismatch for {pattern}")
            covered.extend(matched)
            mapping.extend((_tcl_word(pattern), _tcl_word(spef["path"])))
        if covered != list(corners):
            raise ValueError("diagnostic scene population is incomplete or reordered")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise StepError(f"PRR_DIAGNOSTIC_AUTHORITY_REFUSED: {exc}") from exc
    return {
        "VIBEIC_PRR_DIAGNOSTIC_SPEFS": " ".join(mapping),
        "VIBEIC_PRR_DIAGNOSTIC_AUTHORITY_SHA256": _sha256(authority_path),
    }


@Step.factory.register()
class PostRouteRepair(ResizerStep):
    """Post-detailed-route repair on the routed ODB (flow step 32)."""

    id = "Vibeic.PostRouteRepair"
    name = "Post-Route Timing Repair (vibe-ic step 32)"

    inputs = [DesignFormat.ODB, DesignFormat.NETLIST]
    outputs = [DesignFormat.ODB, DesignFormat.DEF, DesignFormat.NETLIST,
               DesignFormat.POWERED_NETLIST]

    config_vars = (
        ResizerStep.config_vars
        + [v for v in DetailedRouting.config_vars if v.name in _DRT_VARS]
        + [v for v in RCX.config_vars if v.name == "RCX_RULESETS"]
        + [
            Variable(
                "VIBEIC_PRR_DIAGNOSTIC_SPEF_AUTHORITY",
                Optional[Path],
                "Receipt binding diagnostic SPEF hashes and scenes to the "
                "exact design, input ODB and canonical State NETLIST. The "
                "receipt describes that netlist but cannot select it. Unset keeps "
                "ordinary OpenRCX extraction. This fixture-only evidence is "
                "never native-extracted RCX or tapeout/signoff authority.",
            ),
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
        env.pop("VIBEIC_PRR_DIAGNOSTIC_SPEFS", None)
        env.pop("VIBEIC_PRR_DIAGNOSTIC_AUTHORITY_SHA256", None)
        env.update(_diagnostic_spef_env(
            self.config,
            state_in[DesignFormat.ODB],
            state_in[DesignFormat.NETLIST],
        ))
        env["DRT_THREADS"] = env.get("DRT_THREADS", str(_get_process_limit()))
        views, metrics = super().run(state_in, env=env, **kwargs)
        if metrics.get("vibeic__prr__changed") == 0:
            # The script stopped before writing anything: the candidate IS
            # the input database, byte for byte.
            views = {fmt: state_in[fmt] for fmt in self.outputs
                     if state_in.get(fmt) is not None}
        return views, metrics


def _unique_config_vars(*steps: Type[Step]):
    """Return the exact config union for baseline/candidate measurement."""
    result, seen = [], set()
    for step in steps:
        for variable in step.config_vars:
            if variable.name not in seen:
                result.append(variable)
                seen.add(variable.name)
    return result


@Step.factory.register()
class PostRouteRepairAdoption(Step):
    """BLOCKING native baseline/candidate measurement and state adoption.

    ``Vibeic.PostRouteRepair`` remains the single-candidate actuator consumed
    by the host closure controller. A complete native flow inserts this step
    after ``OpenROAD.DetailedRouting`` through ``meta.substituting_steps``.
    The input and candidate traverse the same CheckAntennas, RCX and
    STAPostPNR steps. Only a measured, non-regressing improvement advances;
    a worse candidate returns the measured input state, and an incomplete
    input measurement blocks the flow.
    """

    id = "Vibeic.PostRouteRepairAdoption"
    name = "Post-Route Repair with Native Adoption"
    inputs = list(PostRouteRepair.inputs)
    outputs = list(dict.fromkeys(
        [*PostRouteRepair.outputs, *CheckAntennas.outputs,
         *RCX.outputs, *STAPostPNR.outputs]))
    config_vars = _unique_config_vars(
        PostRouteRepair, CheckAntennas, RCX, STAPostPNR)
    _measurement_steps = (CheckAntennas, RCX, STAPostPNR)

    def _start_child(self, child_type: Type[Step], state: State,
                     folder: str) -> State:
        child = child_type(self.config, state)
        return child.start(toolbox=self.toolbox,
                           step_dir=os.path.join(self.step_dir, folder))

    def _measure(self, state: State, prefix: str) -> State:
        measured = state
        for index, child_type in enumerate(self._measurement_steps, 1):
            measured = self._start_child(
                child_type, measured,
                f"{prefix}-{index:02d}-{child_type.id.lower().replace('.', '-')}")
        return measured

    @staticmethod
    def _antenna(metrics: Dict[str, Any]) -> Optional[Tuple[int, int]]:
        values = tuple(metrics.get(summary, metrics.get(native)) for summary, native in (
            ("antenna_nets", "antenna__violating__nets"),
            ("antenna_pins", "antenna__violating__pins")))
        if any(type(value) is not int or value < 0 for value in values):
            return None
        return values  # type: ignore[return-value]

    @staticmethod
    def _adoption_decision(baseline: Dict[str, Any],
                           candidate: Dict[str, Any],
                           repair_metrics: Dict[str, Any],
                           trigger: Dict[str, Any]) -> Tuple[str, str]:
        """Conservative subset of run_in_chain's existing admission rules."""
        if trigger.get("action") == "SKIP":
            return "NO_REPAIR", "input timing and DRV are measured clean"
        if trigger.get("action") != "RUN":
            return "NOT_MEASURED", "input timing/DRV trigger is incomplete"
        if baseline.get("unmeasured_corners") or candidate.get("unmeasured_corners"):
            return "ROLLED_BACK", "candidate comparison has unmeasured STA corners"

        before_ant = PostRouteRepairAdoption._antenna(baseline)
        after_ant = PostRouteRepairAdoption._antenna(candidate)
        if before_ant is None or after_ant is None:
            return "ROLLED_BACK", "candidate antenna comparison is unmeasured"
        if any(after > before for before, after in zip(before_ant, after_ant)):
            return "ROLLED_BACK", "candidate regressed antenna violations"

        route_values = tuple(repair_metrics.get(key) for key in (
            "vibeic__prr__before__unrouted__count",
            "vibeic__prr__after__unrouted__count",
            "vibeic__prr__unrouted__added"))
        if any(type(value) is not int or value < 0 for value in route_values):
            return "ROLLED_BACK", "candidate route census is unmeasured"
        route_before, route_after, route_added = route_values
        if route_added != max(0, route_after - route_before) or route_added:
            return "ROLLED_BACK", "candidate added unrouted nets"

        improved = after_ant < before_ant
        for kind in ("slew", "cap", "fanout"):
            for corner, before in (baseline.get("drv", {}).get(kind, {}) or {}).items():
                after = (candidate.get("drv", {}).get(kind, {}) or {}).get(corner)
                if type(before) is not int or type(after) is not int:
                    return "ROLLED_BACK", "candidate DRV comparison is unmeasured"
                if after > before:
                    return "ROLLED_BACK", f"candidate regressed {kind} at {corner}"
                improved = improved or after < before
        for field in ("setup_ws", "hold_ws"):
            for corner, before in (baseline.get(field, {}) or {}).items():
                after = (candidate.get(field, {}) or {}).get(corner)
                if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
                    return "ROLLED_BACK", "candidate timing comparison is unmeasured"
                if after < before:
                    return "ROLLED_BACK", f"candidate regressed {field} at {corner}"
                improved = improved or after > before
        if not improved:
            return "ROLLED_BACK", "candidate has no measured timing, DRV, or antenna improvement"
        return "ADOPTED", "candidate improved without timing, DRV, antenna, or route regression"

    @staticmethod
    def _views(state: State) -> ViewsUpdate:
        views: ViewsUpdate = {}
        for fmt in PostRouteRepairAdoption.outputs:
            value = state.get_by_df(fmt)
            if value is not None:
                views[fmt] = value
        return views

    def run(self, state_in: State, **kwargs) -> Tuple[ViewsUpdate, MetricsUpdate]:
        programs = str(FilePath(__file__).resolve().parents[2])
        if programs not in sys.path:
            sys.path.insert(0, programs)
        import librelane_postroute_repair as policy

        corners: Sequence[str] = tuple(self.config["STA_CORNERS"] or [])
        baseline_state = self._measure(state_in, "baseline")
        baseline = policy.summarize(dict(baseline_state.metrics), corners)
        before_ant = self._antenna(dict(baseline_state.metrics))
        if before_ant is not None:
            baseline.update(antenna_nets=before_ant[0], antenna_pins=before_ant[1])
        trigger = policy.measured_repair_trigger(baseline)

        candidate_state = None
        candidate = None
        repair_metrics: Dict[str, Any] = {}
        if trigger["action"] == "RUN":
            candidate_raw = self._start_child(
                PostRouteRepair, state_in, "candidate-01-vibeic-postrouterepair")
            repair_metrics = {key: value for key, value in candidate_raw.metrics.items()
                              if key.startswith("vibeic__prr__")}
            candidate_state = self._measure(candidate_raw, "candidate")
            candidate = policy.summarize(dict(candidate_state.metrics), corners)
            after_ant = self._antenna(dict(candidate_state.metrics))
            if after_ant is not None:
                candidate.update(antenna_nets=after_ant[0], antenna_pins=after_ant[1])

        decision, reason = self._adoption_decision(
            baseline, candidate or baseline, repair_metrics, trigger)
        record = {"schema": "vibeic.native_postroute_adoption.v1",
                  "step": self.id,
                  "verdict": "NOT_MEASURED" if decision == "NOT_MEASURED" else "PASS",
                  "decision": decision, "reason": reason,
                  "trigger": trigger, "baseline": baseline,
                  "candidate": candidate, "repair_metrics": repair_metrics}
        record_path = os.path.join(self.step_dir, "postroute_adoption.json")
        with open(record_path, "w") as stream:
            json.dump(record, stream, indent=2)
        if decision == "NOT_MEASURED":
            raise StepError(f"{self.id}: BLOCKING input measurement incomplete; "
                            f"see {record_path}")
        adopted = candidate_state if decision == "ADOPTED" else baseline_state
        assert adopted is not None
        metrics = dict(adopted.metrics)
        metrics.update({"vibeic__prr__native__adopted": int(decision == "ADOPTED"),
                        "vibeic__prr__native__rolled_back": int(decision == "ROLLED_BACK"),
                        "vibeic__prr__native__no_repair": int(decision == "NO_REPAIR")})
        return self._views(adopted), metrics
