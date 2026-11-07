from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
import time

from librelane.state import DesignFormat
from librelane.steps import StepError, StepException
from librelane.steps.openroad import GeneratePDN, OpenROADStep

from flow_config import _load, _native_pdn_numbers
from flow_pdn_current import current_settings


class RipUpPDN(OpenROADStep):
    id = "Vibeic.RipUpPDN"
    name = "Remove the existing power grid"
    inputs = [DesignFormat.ODB]
    outputs = [DesignFormat.ODB, DesignFormat.DEF]

    def get_script_path(self):
        return str(Path(__file__).with_suffix(".tcl"))


def resize(project, config, state, toolbox, directory, on_tool_run):
    if not config.get("PDN_CORE_RING_CONNECT_TO_PADS"):
        return config, state
    raw = config.to_raw_dict()
    power = _load(project / "steps/post_cts_timing_repair/result.json").get("native_metrics", {})
    key = "power__total__corner:" + raw["DEFAULT_CORNER"]
    metrics = {key: power[key]} if key in power else {}
    extent = raw.get("DIE_AREA") or raw.get("CORE_AREA")
    span = max(float(extent[2]) - float(extent[0]), float(extent[3]) - float(extent[1])) if extent else None
    settings = current_settings(project, raw, span, metrics=metrics)
    widths = ("PDN_VWIDTH", "PDN_HWIDTH", "PDN_CORE_RING_VWIDTH", "PDN_CORE_RING_HWIDTH")
    if not any(Decimal(str(settings.get(key, raw[key]))) > Decimal(str(raw[key])) for key in widths):
        return config, state
    config = config.copy(**_native_pdn_numbers(settings))
    for step_class in (RipUpPDN, GeneratePDN):
        destination = (directory / step_class.id.lower().replace(".", "_")).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        step = step_class(config, state)
        started = time.perf_counter()
        code, ran, status, detail = None, False, "NOT_MEASURED", ""
        working_directory = Path.cwd()
        try:
            os.chdir(destination)
            state = step.start(toolbox=toolbox, step_dir=str(destination))
            code, ran, status = 0, True, "PASS"
        except StepError as exc:
            code = getattr(getattr(exc, "underlying_error", None), "returncode", 1) or 1
            ran, status, detail = True, "FAIL", str(exc)
            raise
        except (StepException, FileNotFoundError) as exc:
            detail = str(exc)
            raise
        finally:
            os.chdir(working_directory)
            on_tool_run({"name": step_class.id, "ran": ran, "exit_code": code, "status": status,
                "tool_seconds": time.perf_counter() - started, "detail": detail, "reports": str(destination)})
    return config, state
