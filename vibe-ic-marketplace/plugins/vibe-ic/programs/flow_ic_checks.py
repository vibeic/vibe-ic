from __future__ import annotations

import json
import math
import os
from decimal import Decimal
from pathlib import Path
from typing import Optional

from librelane.config import Variable
from librelane.state import DesignFormat
from librelane.steps import Step, StepError, StepException


def timing_folder(state):
    sdfs = state.get(DesignFormat.SDF) or {}
    paths = list(sdfs.values()) if isinstance(sdfs, dict) else [sdfs]
    folders = {Path(str(path)).parent.parent for path in paths}
    if len(folders) != 1:
        raise StepException("NOT_MEASURED: native post-route timing output is missing or ambiguous")
    return folders.pop()


def completed(process, name):
    if process is None:
        raise StepException(f"NOT_MEASURED: native {name} executable is unavailable")
    if process.returncode:
        raise StepError(f"Native {name} exited with code {process.returncode}")
    return process


@Step.factory.register()
class SignalIntegrity(Step):
    id = "VibeIC.SignalIntegrity"
    name = "Native Miller-bounded signal timing"
    inputs = [DesignFormat.NETLIST, DesignFormat.SDC, DesignFormat.SPEF, DesignFormat.SDF]
    outputs = []

    def run(self, state_in, **kwargs):
        import si_mcf_sta
        from path_spice_tool import worst_setup_corner
        from librelane_contract import Refusal

        folder = timing_folder(state_in)
        try:
            corner = worst_setup_corner(folder)
        except Refusal as exc:
            raise StepException(f"NOT_MEASURED: {exc}") from exc
        config = self.config.copy(DEFAULT_CORNER=corner)
        libraries = self.toolbox.filter_views(config, config["LIB"])
        libraries += self.toolbox.filter_views(config, config.get("PAD_LIBS") or {})
        spefs = self.toolbox.filter_views(config, state_in[DesignFormat.SPEF])
        if not libraries or len(spefs) != 1:
            raise StepException("NOT_MEASURED: SI needs native corner Liberty and coupling SPEF")
        voltage = self.toolbox.get_lib_voltage(str(libraries[0]))
        if voltage is None or not math.isfinite(float(voltage)) or voltage <= 0:
            raise StepException("NOT_MEASURED: SI corner Liberty has no nominal supply voltage")
        root = Path(self.step_dir).resolve()
        result = si_mcf_sta.run(Path(self.config["DESIGN_DIR"]),
            spef=str(spefs[0]), netlist=str(state_in[DesignFormat.NETLIST]),
            sdc=str(state_in[DesignFormat.SDC]), liberty=str(libraries[0]),
            top=self.config["DESIGN_NAME"], macro_libs=list(map(str, libraries[1:])),
            vdd_v=float(voltage), out_json=root / "si_mcf_sta.json", work_dir=root / "native")
        codes = [result.get("windows_rc"), result.get("nominal", {}).get("sta_rc")]
        codes += [row.get("sta_rc") for row in result.get("corners", {}).values()]
        if any(code not in (None, 0) for code in codes):
            raise StepError("Native OpenSTA signal-integrity run failed; see si_mcf_sta.json")
        metrics = {"si_coupling_pairs": result.get("coupling_pairs")}
        for kind in ("setup", "hold"):
            value = result.get("corners", {}).get(kind, {}).get("worst_slack_after_ns")
            if isinstance(value, (int, float)) and math.isfinite(value):
                metrics[f"si_{kind}_slack_ns"] = value
        return {}, metrics


@Step.factory.register()
class SpiceCorrelation(Step):
    id = "VibeIC.SpiceCorrelation"
    name = "Native extracted path SPICE correlation"
    inputs = [DesignFormat.NETLIST, DesignFormat.SDC, DesignFormat.SPEF, DesignFormat.SDF]
    outputs = []
    config_vars = [Variable("SPICE_EXTRESIST_MINDELAY_PS", Optional[Decimal],
        "Native Magic minimum cell RC delay in ps; 0 retains small signal networks. "
        "Omit to preserve Magic's default.", default=None, units="ps")]

    def run(self, state_in, **kwargs):
        from path_spice_tool import run_case_correlation
        from librelane_contract import Refusal

        extraction_options = {}
        if (mindelay := self.config.get("SPICE_EXTRESIST_MINDELAY_PS")) is not None:
            extraction_options["extresist_mindelay_ps"] = float(mindelay)
        try:
            result = run_case_correlation(Path(self.config["DESIGN_DIR"]),
                os.environ.get("VIBEIC_EDA_IMAGE", ""), Path(str(self.config["PDK_ROOT"])),
                self.config["PDK"], sta_step_dir=timing_folder(state_in), **extraction_options)
        except Refusal as exc:
            raise StepException(f"NOT_MEASURED: {exc}") from exc
        (Path(self.step_dir) / "spice_correlation.json").write_text(json.dumps(result, indent=2) + "\n")
        rows = result.get("paths", [])
        if result.get("sta_rc") not in (None, 0) or any(
                row.get("sim_rc", row.get("simulator_execution", {}).get("rc")) not in (None, 0)
                for row in rows):
            raise StepError("Native SPICE correlation tool failed; see spice_correlation.json")
        metrics = {}
        failures = sum(row.get("verdict") in {"MISMATCH", "CRITICAL_MISMATCH"} for row in rows)
        if failures or result.get("verdict") == "PASS":
            metrics["spice_correlation_errors"] = failures
        return {}, metrics


@Step.factory.register()
class ElectricalRules(Step):
    id = "VibeIC.ElectricalRules"
    name = "Native PDK CVC electrical rules"
    inputs = [DesignFormat.SPICE, DesignFormat.NETLIST]
    outputs = []

    def run(self, state_in, **kwargs):
        from flow_native_adapters import Commands
        from phase3_one_shot_runner import _parse_native_cvc_report

        root = Path(self.step_dir).resolve()
        pdk = Path(str(self.config["PDK_ROOT"])) / self.config["PDK"]
        recipe = pdk / "libs.tech/librelane/cvc"
        library = self.config["STD_CELL_LIBRARY"]
        cdl = pdk / f"libs.ref/{library}/cdl/{library}.cdl"
        materials = [recipe / name for name in ("cvcrc", "models", "cdl.awk", "power.awk")]
        if any(not path.is_file() for path in [*materials, cdl]):
            raise StepException("NOT_MEASURED: selected PDK CVC recipe or standard-cell CDL is unavailable")
        power, ground = self.config["VDD_NETS"], self.config["GND_NETS"]
        if len(power) != 1 or len(ground) != 1:
            raise StepException("NOT_MEASURED: PDK CVC recipe needs one declared supply pair")
        commands = Commands(root)
        cleaned = completed(commands.run(["awk", "-f", recipe / "cdl.awk", state_in[DesignFormat.SPICE]]), "CDL conversion")
        (root / "design.cdl").write_text(cleaned.stdout + "\n" + cdl.read_text())
        supplies = completed(commands.run(["awk", "-v", f"vdd={power[0]}", "-v", f"gnd={ground[0]}",
            "-f", recipe / "power.awk", state_in[DesignFormat.NETLIST]]), "CVC power declaration")
        (root / "top.power").write_text(supplies.stdout)
        top = self.config["DESIGN_NAME"]
        text = (recipe / "cvcrc").read_text()
        for old, new in (("$CVC_SCRIPTS_DIR/models", recipe / "models"),
                         ("$signoff_tmpfiles/$DESIGN_NAME.cdl", root / "design.cdl"),
                         ("$signoff_tmpfiles/$CVC_TOP.power", root / "top.power"),
                         ("$signoff_reports/$CVC_TOP.rpt", root / "report.rpt"),
                         ("$DESIGN_NAME", top)):
            text = text.replace(old, str(new))
        config = root / "cvcrc"
        config.write_text(text)
        completed(commands.run(["cvc_rv", config]), "CVC")
        report = root / "report.rpt"
        parsed = _parse_native_cvc_report(report.read_text() if report.is_file() else "")
        (root / "cvc.json").write_text(json.dumps(parsed, indent=2) + "\n")
        metrics = {}
        total = parsed["counts"].get("Total")
        if parsed["result"] in {"PASS", "FAIL"} or total:
            metrics["cvc_electrical_errors"] = total
        for name in ("instances", "nets", "devices"):
            if parsed[name] is not None:
                metrics[f"cvc_{name}"] = parsed[name]
        return {}, metrics
