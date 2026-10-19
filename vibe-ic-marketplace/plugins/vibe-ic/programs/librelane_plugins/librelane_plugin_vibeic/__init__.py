"""vibe-ic's LibreLane plugin: custom steps that travel with the tool flow.

LibreLane imports every top-level module named ``librelane_plugin_*`` it finds
on ``sys.path`` (``librelane/plugins.py``), and each module registers its steps
with ``Step.factory``. The plugin ships inside the vibe-ic plugin (never in the
vibeic/librelane fork): the step's logic is vibe-ic's own Design-for-ECO
policy, it imports vibe-ic's plan builder (``programs/_spare_plan.py``), and it
must move with the plugin version that the gates reading its output belong to.
``librelane_contract`` mounts ``programs/`` read-only and puts
``programs/librelane_plugins`` on ``PYTHONPATH`` for exactly the steps whose id
starts with ``Vibeic.`` -- nothing else sees it.

``Vibeic.InsertSpareCells`` (flow step 18) runs after
``OpenROAD.DetailedPlacement``: it inserts the Design-for-ECO spare pool,
legalizes only the spares, ties every floating spare input to that spare's own
tie-low driver, connects the spares' supply pins explicitly, locks them FIRM,
marks them dont_touch, and records ``check_placement``'s count. See
``insert_spare_cells.py``.

``Vibeic.GateLevelSim`` (flow step 29, T106) consumes the state
``OpenROAD.STAPostPNR`` leaves -- the netlist it timed and its per-corner SDFs
(``write_sdf -include_typ -divider . -corner <c>``) -- and re-runs the design's
own executed L10 suite against each corner SDF in Icarus Verilog
(``iverilog -gspecify -ginterconnect``, ``vvp -sdf-info``). It JUDGES
NOTHING: what it runs comes from ``VIBEIC_GLS_MANIFEST``
(``sdf_gate_sim.tool_arm_manifest``: bound testbenches, the model closure of
the PDK's declared Verilog models, compile flags); it records each run's exit
codes and transcript paths (``gls_runs.json``). The verdict -- every case
passed, delays applied > 0, SDF ERROR = 0 -- is
``sdf_gate_sim.judge_tool_arm`` on the host, where the transcript grammar is
calibrated.

``Vibeic.ClockPathDriveSizing`` (flow step 19, T98) runs after
``OpenROAD.CTS``: the #2160 clock-path drive sizing, see its class docstring
and ``clock_path_drive_sizing.tcl``.

``Vibeic.DetailedRoutingSeeded`` and ``Vibeic.NamedViolationReroute`` (flow
step 21, mig99): the router seed as a declared PPA lever, and the targeted
reroute of the nets the router's own report names. See ``routing.py``.

``Vibeic.FinishingXOR`` (flow step 37.3, mig105) and ``Vibeic.DatabaseUnit``
(flow step 37.5ic, mig105): finishing never removes or covers design geometry,
and the stream's UNITS is the declared grid. See ``signoff.py``.

``Vibeic.PostRouteRepair`` (flow step 32, T102) runs after
``OpenROAD.DetailedRouting``: one candidate of the post-route repair, on the
routed ODB; ``programs/librelane_postroute_repair.py`` measures and adopts or
rolls it back. See ``postroute_repair.py``.
"""
from __future__ import annotations

import json
import os
import subprocess
from decimal import Decimal
from typing import List, Optional, Tuple

from librelane.common import Path
from librelane.config import Variable
from librelane.state import DesignFormat, State
from librelane.steps.common_variables import dpl_variables
from librelane.steps.odb import OdbpyStep
from librelane.steps.openroad import OpenROADStep
from librelane.steps.step import MetricsUpdate, Step, StepError, ViewsUpdate

__all__ = ["InsertSpareCells", "GateLevelSim", "ClockPathDriveSizing",
           "ExternalCaptureLaunchRetap"]


@Step.factory.register()
class InsertSpareCells(OdbpyStep):
    """Design-for-ECO spare-cell pool, inserted into the placed database."""

    id = "Vibeic.InsertSpareCells"
    name = "Insert Design-for-ECO Spare Cells"

    inputs = [DesignFormat.ODB]
    outputs = [DesignFormat.ODB, DesignFormat.DEF, DesignFormat.NETLIST,
               DesignFormat.POWERED_NETLIST]

    config_vars = dpl_variables + [
        Variable(
            "VIBEIC_SPARE_PLAN",
            Optional[Path],
            "A spare plan written by `_spare_plan.build_spare_cells_plan` "
            "(names, classes, cells, target positions). When set, exactly "
            "these spares are inserted, so a caller that reserves their names "
            "elsewhere (the route deck) agrees with the database.",
        ),
        Variable(
            "VIBEIC_SPARE_DENSITY",
            Optional[Decimal],
            "Spare density as a fraction of the placed logic cells. Used to "
            "build the plan in-step from the placed database when "
            "VIBEIC_SPARE_PLAN is unset; 0 inserts nothing.",
        ),
        Variable(
            "VIBEIC_SPARE_TIELO_CELL",
            Optional[str],
            "Tie-low `cell/pin` that drives each spare's floating inputs. "
            "Defaults to the PDK's SYNTH_TIELO_CELL.",
        ),
    ]

    def get_script_path(self) -> str:
        return os.path.join(os.path.dirname(__file__), "insert_spare_cells.py")

    def _report_path(self) -> str:
        return os.path.join(self.step_dir, "spare_cells.json")

    def get_command(self) -> List[str]:
        assert self.config_path is not None, "get_command called before start()"
        design = self.config["DESIGN_NAME"]
        return super().get_command() + [
            "--step-config", self.config_path,
            "--report", self._report_path(),
            "--output-nl", os.path.join(self.step_dir, f"{design}.nl.v"),
            "--output-pnl", os.path.join(self.step_dir, f"{design}.pnl.v"),
        ]

    def run(self, state_in: State, **kwargs) -> Tuple[ViewsUpdate, MetricsUpdate]:
        views, metrics = super().run(state_in, **kwargs)
        design = self.config["DESIGN_NAME"]
        views[DesignFormat.NETLIST] = Path(os.path.join(self.step_dir, f"{design}.nl.v"))
        views[DesignFormat.POWERED_NETLIST] = Path(
            os.path.join(self.step_dir, f"{design}.pnl.v"))
        with open(self._report_path(), encoding="utf8") as stream:
            record = json.load(stream)
        measured = record.get("measured", {})
        metrics = dict(metrics)
        for key, value in (
                ("vibeic__spare__planned", record.get("count")),
                ("vibeic__spare__inserted", measured.get("inserted")),
                ("vibeic__spare__tieoff__candidates", measured.get("tieoff_candidates")),
                ("vibeic__spare__tieoff__connected", measured.get("tieoff_connected")),
                ("vibeic__spare__pg__unconnected", measured.get("pg_unconnected")),
                ("vibeic__spare__check_placement__violations",
                 measured.get("check_placement_violations"))):
            if isinstance(value, int):
                metrics[key] = value
        violations = measured.get("check_placement_violations")
        if not isinstance(violations, int) or violations:
            # Same contract as OpenROAD.DetailedPlacement: an illegal database
            # never leaves the step. The record above stays for the reader.
            raise StepError(
                f"{self.id}: check_placement reported {violations!r} "
                f"violation(s) after spare insertion; see {self._report_path()}")
        return views, metrics


# Step 24 (lane mig101): the IR gate and the fork's transient solve.
from .ir_drop import IRDropChecker, TransientIR  # noqa: E402,F401

__all__ += ["IRDropChecker", "TransientIR"]

# Steps 37.3 and 37.5ic (lane mig105): the finishing XOR and the database-unit
# check over LibreLane's own streams.
from .signoff import DatabaseUnit, FinishingXOR  # noqa: E402,F401

__all__ += ["FinishingXOR", "DatabaseUnit"]

# Step 21 (lane mig99): the declared-seed detailed route and the named-violation
# reroute after it.
from .routing import DetailedRoutingSeeded, NamedViolationReroute  # noqa: E402,F401

__all__ += ["DetailedRoutingSeeded", "NamedViolationReroute"]

# Step 32 (lane mig102): the post-detailed-route repair.
from .postroute_repair import PostRouteRepair  # noqa: E402,F401

__all__ += ["PostRouteRepair"]

# Step 17: close the fanout of buffers created by RepairDesignPostGPL before
# DetailedPlacement and all later physical stages consume the placed state.
from .postgpl_fanout_closure import PostGPLFanoutClosure  # noqa: E402,F401

__all__ += ["PostGPLFanoutClosure"]


@Step.factory.register()
class GateLevelSim(Step):
    """SDF-annotated gate-level simulation of the design's L10 suite, one run
    per case per STA corner SDF."""

    id = "Vibeic.GateLevelSim"
    name = "Gate-Level Simulation (vibe-ic L10 suite x STA corner SDFs)"
    inputs = [DesignFormat.NETLIST, DesignFormat.SDF]
    outputs = []

    config_vars = [
        Variable("VIBEIC_GLS_MANIFEST", Path,
                 "The gate-level suite manifest (sdf_gate_sim.tool_arm_manifest)."),
        Variable("VIBEIC_GLS_TIMEOUT_S", int,
                 "Wall-clock limit for one compile or one simulation, seconds.",
                 default=900),
    ]

    def run(self, state_in: State, **kwargs) -> Tuple[ViewsUpdate, MetricsUpdate]:
        with open(str(self.config["VIBEIC_GLS_MANIFEST"])) as stream:
            manifest = json.load(stream)
        netlist = str(state_in[DesignFormat.NETLIST])
        sdfs = state_in[DesignFormat.SDF] or {}
        if not isinstance(sdfs, dict):
            sdfs = {"default": sdfs}
        limit = int(self.config["VIBEIC_GLS_TIMEOUT_S"])
        runs = []
        for corner in sorted(sdfs):
            folder = os.path.join(self.step_dir, corner)
            os.makedirs(folder, exist_ok=True)
            for case in manifest["cases"]:
                cid = case["id"]
                with open(case["testbench"]) as stream:
                    tb_text = stream.read()
                tb = os.path.join(folder, f"{cid}_tb.v")
                with open(tb, "w") as stream:
                    stream.write(tb_text.replace(manifest["sdf_placeholder"],
                                                 str(sdfs[corner])))
                vvp = os.path.join(folder, f"{cid}.vvp")
                compile_log = os.path.join(folder, f"{cid}.compile.log")
                stdout = os.path.join(folder, f"{cid}.stdout.log")
                argv = (["iverilog", *manifest["compile_flags"].split(),
                         "-s", case["module"], "-o", vvp, tb, netlist,
                         manifest["stubs"], *manifest["models"]])
                compile_rc = self._run(argv, compile_log, limit)
                sim_rc = None
                if compile_rc == 0:
                    sim_rc = self._run(["vvp", vvp, "-sdf-info"], stdout, limit,
                                       cwd=folder)
                runs.append({"corner": corner, "case": cid, "sdf": str(sdfs[corner]),
                             "compile_rc": compile_rc, "sim_rc": sim_rc,
                             "compile_log": compile_log, "stdout": stdout})
        with open(os.path.join(self.step_dir, "gls_runs.json"), "w") as stream:
            json.dump({"manifest": str(self.config["VIBEIC_GLS_MANIFEST"]),
                       "netlist": netlist, "runs": runs}, stream, indent=2)
        return {}, {"vibeic__gls__run__count": len(runs),
                    "vibeic__gls__corner__count": len(sdfs)}

    @staticmethod
    def _run(argv, log: str, limit: int, cwd=None) -> int:
        with open(log, "w") as sink:
            try:
                return subprocess.run(argv, stdout=sink, stderr=subprocess.STDOUT,
                                      cwd=cwd, timeout=limit).returncode
            except subprocess.TimeoutExpired:
                sink.write(f"\nVIBEIC_GLS_TIMEOUT after {limit} s\n")
                return 124


@Step.factory.register()
class ClockPathDriveSizing(OpenROADStep):
    """Size the clock-path cells that neither CTS nor the resizer owns (#2160).

    TritonCTS starts its tree at the first cell it may buffer and the OpenROAD
    resizer excludes clock-network cells, so a cell upstream of the CTS root
    (the DFT test-clock multiplexer on subservient x gf180mcuD: 2.00 ns, 30 %
    of the insertion delay) is sized by nobody.  This step runs right after
    ``OpenROAD.CTS`` on its ODB.  The algorithm is the runner's own
    ``_clock_path_drive_sizing_tcl`` (one copy): the caller writes it to
    ``VIBEIC_CLKPATH_SIZING_TCL``.  ``VIBEIC_CLKPATH_PRECTS_INSTANCES`` lists
    every instance of the CTS step's INPUT ODB, one per line: the set CTS did
    not create, which is how a CTS buffer is told from a cell nobody owns.
    """

    id = "Vibeic.ClockPathDriveSizing"
    name = "Clock-path drive sizing (vibe-ic #2160)"

    config_vars = OpenROADStep.config_vars + [
        Variable(
            "VIBEIC_CLKPATH_PRECTS_INSTANCES",
            Path,
            "Instance names of the ODB that OpenROAD.CTS read, one per line.",
        ),
        Variable(
            "VIBEIC_CLKPATH_SIZING_TCL",
            Path,
            "The sizing pass, emitted by phase3_one_shot_runner."
            "_clock_path_drive_sizing_tcl.",
        ),
        Variable(
            "VIBEIC_CLKPATH_MAX_FANOUT",
            Optional[int],
            "The declared MAX_FANOUT_CONSTRAINT for CTS-created clock-tree "
            "branches; unset means no internal-tree fanout repair.",
        ),
        Variable(
            "VIBEIC_CLKPATH_CTS_BUFFERS",
            Optional[List[str]],
            "The resolved CTS non-inverting buffer roles (CTS_CLK_BUFFERS plus "
            "CTS_ROOT_BUFFER) from this exact CTS configuration.",
        ),
    ]

    def get_script_path(self) -> str:
        return os.path.join(os.path.dirname(__file__), "clock_path_drive_sizing.tcl")


@Step.factory.register()
class ExternalCaptureLaunchRetap(OpenROADStep):
    """Try measured CTS root retaps for externally captured outputs.

    Runs on ClockPathDriveSizing's state, before PostCTS timing repair. The
    pre-CTS snapshot identifies CTS-created buffers without cell-name rules.
    Each register trial is retained only after setup and hold measurement.
    """

    id = "Vibeic.ExternalCaptureLaunchRetap"
    name = "External capture launch retap"

    config_vars = OpenROADStep.config_vars + [
        Variable(
            "VIBEIC_CLKPATH_PRECTS_INSTANCES",
            Path,
            "Instance names of the ODB that OpenROAD.CTS read, one per line.",
        ),
    ]

    def get_script_path(self) -> str:
        return os.path.join(os.path.dirname(__file__),
                            "external_capture_launch_retap_step.tcl")

# Step 9 mapped-product implementation transform.
from .postmap_repair import PostMapRepair  # noqa: E402,F401
__all__ += ["PostMapRepair"]
