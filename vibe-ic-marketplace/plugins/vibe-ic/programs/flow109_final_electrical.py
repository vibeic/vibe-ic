"""Native final timing, static IR/EM and analog mission measurements."""

from __future__ import annotations

import json
from pathlib import Path
import re
import uuid

from _atomic_artefact import write_json
import em_current_density_check as em_check
import librelane_ir_antenna as ir_tool
import librelane_signoff as signoff
import librelane_postroute as postroute
from librelane_contract import Refusal, _load, project_path

IR_LIMIT_PCT = 5.0
SCHEMA = "vibeic.flow109.final-electrical.v1"


class ElectricalError(ValueError):
    def __init__(self, code, detail, *, status="NOT_MEASURED"):
        self.code, self.status = code, status
        super().__init__(f"{code}: {detail}")


def _bound(project, ref):
    value = ref["path"] if isinstance(ref, dict) else ref
    path = project_path(Path(project), value)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _record(project, path):
    return {"path": str(Path(path))}


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ElectricalError("D70_REQUIRED_INPUT_ABSENT", str(path)) from exc
    if not isinstance(value, dict):
        raise ElectricalError("D70_REQUIRED_INPUT_INVALID", str(path))
    return value


def _required_corner_population(value):
    """Return the declared scene population, rejecting absent/duplicate names."""
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(corner, str) and corner for corner in value)
        or len(value) != len(set(value))
    ):
        raise ElectricalError(
            "D70_REQUIRED_CORNERS_ABSENT", "nonempty unique required_corners required"
        )
    return set(value)


def judge_ir_em(text, nets):
    """One corner's native PSM report per net, against 5 percent VDD and PDK Jmax."""
    rows = {}
    for net in nets:
        match = re.search(rf"=== PSM_NET {re.escape(net)} ===(.*?)(?:=== PSM_NET|\Z)", text, re.S)
        body = match.group(1) if match else ""
        found = {
            key: re.search(pattern, body)
            for key, pattern in (
                ("drop_v", r"Worstcase IR drop: *(\S+) V"),
                ("drop_pct", r"Percentage drop *: *(\S+) %"),
                ("em_utilization_pct", r"Worst utilization *: *(\S+) %"),
                ("em_violations", r"Violations *: *(\d+)"),
                ("em_no_limit", r"No J-limit \(skipped\): *(\d+)"),
                ("em_verdict", r"Verdict *: *(\S+)"),
            )
        }
        row = {
            key: (
                (value.group(1) if key == "em_verdict" else float(value.group(1)))
                if value
                else None
            )
            for key, value in found.items()
        }
        row["ir_status"] = (
            "NOT_MEASURED"
            if row["drop_pct"] is None
            else "FAIL" if row["drop_pct"] > IR_LIMIT_PCT else "PASS"
        )
        row["em_status"] = (
            "FAIL"
            if row["em_verdict"] == "FAIL" or (row["em_violations"] or 0) > 0
            else (
                "PASS"
                if row["em_verdict"] == "PASS" and row["em_no_limit"] == 0
                else "NOT_MEASURED"
            )
        )
        rows[net] = row
    return rows


def _roll_up(statuses):
    statuses = list(statuses)
    return (
        "FAIL"
        if "FAIL" in statuses
        else "PASS" if statuses and set(statuses) == {"PASS"} else "NOT_MEASURED"
    )


def _native_ir_em(project, native, odb, sdc, spefs, sta_folder, corners, folder):
    """OpenROAD PSM IR and power-grid EM on the final State, at each max-RC corner."""
    config = _load(sta_folder / "config.json")
    vdd, gnd = list(config.get("VDD_NETS") or []), list(config.get("GND_NETS") or [])
    mounts = [(Path(native["pdk_root"]).resolve(), ir_tool.PDK_GUEST_ROOT)]
    folder.mkdir(parents=True, exist_ok=True)
    tech_lef = ir_tool._host_path(
        config["TECH_LEFS"][ir_tool._pattern_for("nom_", config["TECH_LEFS"])], mounts
    )
    limits = folder / "em_limits_pdk.txt"
    limits.write_text(em_check.native_limits(tech_lef.read_text(), 0.0, native["pdk"]))
    pads = ir_tool.declared_supply_pads(project)
    sources = (
        ir_tool.declared_sources(
            ir_tool.supply_geometry(
                project, native["image"], odb, vdd + gnd, pads["instances"], folder, mounts
            ),
            vdd,
            gnd,
        )["sources"]
        if pads["declared"]
        else None
    )
    result = {
        "scope": "static IR and power-grid EM, max RC scene",
        "ir_limit_pct": IR_LIMIT_PCT,
        "em_limit": "PDK Jmax",
        "em_limits_file": _record(project, limits),
        "corners": {},
    }
    for corner in sorted(c for c in corners if c.startswith("max_")):
        volts = re.search(r"(\d+)v(\d+)$", corner)
        if volts is None:
            raise ElectricalError("D70_CORNER_VOLTAGE_UNREADABLE", corner)
        voltage = float(f"{volts.group(1)}.{volts.group(2)}")
        libs = [
            lib
            for key in ("LIB", "PAD_LIBS")
            if config.get(key)
            for lib in config[key].get(ir_tool._pattern_for(corner, config[key]), [])
        ]
        vsrc = (
            ir_tool.write_vsrc(
                sources, {net: voltage if net in vdd else 0.0 for net in sources}, folder / corner
            )
            if sources
            else {}
        )
        tcl = [f"read_liberty {lib}" for lib in libs] + [
            f"read_db {odb}",
            f"read_sdc {sdc}",
            f"read_spef {spefs['max']}",
            "set_propagated_clock [all_clocks]",
            "report_power",
        ]
        tcl += [
            f"set_pdnsim_net_voltage -net {net} -voltage {voltage if net in vdd else 0}"
            for net in vdd + gnd
        ]
        for net in vdd + gnd:
            source = f" -vsrc {vsrc[net]}" if net in vsrc else ""
            tcl += [
                f'puts "=== PSM_NET {net} ==="',
                f"analyze_power_grid -net {net}{source}",
                f"check_current_density -net {net} -em_limits_file {limits} "
                f"-em_report {folder}/em_{corner}_{net}.csv{source} -allow_reuse",
            ]
        script, log = folder / f"ir_em_{corner}.tcl", folder / f"ir_em_{corner}.log"
        script.write_text("\n".join(tcl) + "\nexit\n")
        rc = ir_tool._run_openroad(project, native["image"], script, log, mounts)
        nets = judge_ir_em(log.read_text(errors="replace"), vdd + gnd)
        if rc:
            nets = {
                net: {
                    **row,
                    "ir_status": "NOT_MEASURED" if row["ir_status"] == "PASS" else row["ir_status"],
                    "em_status": "NOT_MEASURED" if row["em_status"] == "PASS" else row["em_status"],
                }
                for net, row in nets.items()
            }
        result["corners"][corner] = {
            "rc": rc,
            "voltage_v": voltage,
            "log": _record(project, log),
            "nets": nets,
        }
    rows = [row for corner in result["corners"].values() for row in corner["nets"].values()]
    result.update(
        ir_status=_roll_up(row["ir_status"] for row in rows),
        em_status=_roll_up(row["em_status"] for row in rows),
    )
    return result


def _scan_timing(project, groups, native, state):
    statuses, modes = [], {}
    for group in groups:
        mode = group["mode"]
        if mode not in ("shift", "capture"):
            raise ValueError("Scan timing mode must be shift or capture")
        corners = sorted({row["corner"] for row in group["scenarios"]})
        libraries = [str(_bound(project, p)) for p in group["libraries"]]
        sdc = _bound(project, group["sdc"])
        scope = "scan-final-" + mode + "-" + uuid.uuid4().hex
        overlay = {
            "SIGNOFF_SDC_FILE": (str(sdc), "native mode SDC"),
            "STA_CORNERS": (corners, "design mode corners"),
            "CELL_LIBS": ({c: libraries for c in corners}, "mode timing libraries"),
            "DEFAULT_CORNER": (corners[0], "first selected mode corner"),
        }
        run = signoff.run(
            project,
            native["image"],
            Path(native["pdk_root"]),
            native["pdk"],
            routed_def=_bound(project, state["def"]),
            routed_odb=_bound(project, state["odb"]),
            netlist=_bound(project, state["nl"]),
            sdc=sdc,
            extract=False,
            time=True,
            direct_spefs={k: _bound(project, v) for k, v in state["spef"].items()},
            lane=scope,
            config_folder=scope + "-config",
            config_overlay=overlay,
        )
        measured = signoff.corner_timing(Path(run["sta"]))
        judged = signoff.judge_timing(measured)
        status = judged["verdict"]
        if set(measured) != set(corners) and status != "FAIL":
            status = "NOT_MEASURED"
        statuses.append(status)
        modes.setdefault(mode, []).append(
            {"corners": measured, "judgment": judged, "status": status, "folder": run["sta"]}
        )
    if set(modes) != {"shift", "capture"}:
        statuses.append("NOT_MEASURED")
    return {"status": _roll_up(statuses), "modes": modes}


def execute(project, context):
    if context.get("analog"):
        return _execute_analog(project, context)
    import librelane_contract as contract
    from _prestream_native import signoff_inputs, final_state

    project = Path(project).resolve()
    attempt = project / "reports/phase3/final-electrical" / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    result = {"component_status": "NOT_MEASURED", "native_started": False}
    try:
        required = _required_corner_population(context["required_corners"])
        views = signoff_inputs(project, "odb", "def", "netlist", "sdc")
        selected = final_state(project, streamed=True)
        config_path = context.get("config_path") or selected.parent / "config.json"
        config = contract._load(contract.project_path(project, config_path))
        state = contract._load(selected)
        pdk = config["PDK"]
        image = contract.resolve_image(project)
        root = contract.resolve_pdk_root(project, pdk, image=image)
        if not root:
            raise ValueError("Native PDK root is required")
        native = {"image": image, "pdk_root": str(root), "pdk": pdk}
        spefs = {
            signoff.rc_corner(k): _bound(project, v)
            for k, v in (context.get("spefs") or state["spef"]).items()
        }
        result["native_started"] = True
        run = signoff.run(
            project,
            image,
            Path(root),
            pdk,
            routed_def=views["def"],
            routed_odb=views["odb"],
            netlist=views["netlist"],
            sdc=views["sdc"],
            extract=False,
            time=True,
            direct_spefs=spefs,
            lane="native-final-electrical",
        )
        folder = Path(run["sta"])
        corners = signoff.corner_timing(folder)
        timing = signoff.judge_timing(corners)
        timed = _load(folder / "state_out.json")
        sdfs = postroute.corner_sdfs(timed)
        population = "PASS" if required == set(corners) == set(sdfs) else "NOT_MEASURED"
        ir_em = _native_ir_em(
            project, native, views["odb"], views["sdc"], spefs, folder, corners, attempt / "ir_em"
        )
        statuses = [timing["verdict"], population, ir_em["ir_status"], ir_em["em_status"]]
        if context.get("requires_scan"):
            scan = _scan_timing(project, context.get("scan_groups", []), native, timed)
            result["scan_timing"] = scan
            statuses.append(scan["status"])
        result.update(
            component_status=_roll_up(statuses),
            corners=corners,
            timing_judgment=timing,
            corner_population_status=population,
            ir_em=ir_em,
            sta_state=str(folder / "state_out.json"),
            sdfs={k: str(v) for k, v in sdfs.items()},
            dynamic_ir_status="NOT_MEASURED",
            signal_em_status="NOT_MEASURED",
            thermal_status="NOT_MEASURED",
        )
    except Refusal as exc:
        result.update(
            component_status="FAIL" if exc.code == "LL_STEP_FAILED" else "NOT_MEASURED",
            reason=exc.code,
            detail=str(exc),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update(detail=str(exc))
    write_json(attempt / "result.json", result)
    return result


def _analog_inputs(project, options):
    import math
    import corner_yield_vs_spec_check as limits

    corners = _required_corner_population(options["required_corners"])
    scenarios = options["scenarios"]
    netlists = {
        corner: _bound(project, path) for corner, path in options["simulation_netlists"].items()
    }
    if (
        not scenarios
        or len({s["id"] for s in scenarios}) != len(scenarios)
        or {s["corner"] for s in scenarios} != corners
        or not corners <= set(netlists)
    ):
        raise ValueError("Each design mission corner needs a simulation netlist and scenario")
    resolved = []
    for setting in scenarios:
        paths = {k: _bound(project, setting[k]) for k in ("testbench", "bindings", "load", "spec")}
        binding = _read(paths["bindings"])
        temperature = (binding.get("analysis") or {}).get("temperature_c")
        if type(temperature) not in (int, float) or not math.isfinite(temperature):
            raise ValueError("Mission temperature is required")
        bounds = limits._spec_limits(_read(paths["spec"]))
        if (
            not bounds
            or set(bounds) != set(binding.get("measurements") or {})
            or any(
                not math.isfinite(v)
                for limit in bounds.values()
                for v in limit.values()
                if v is not None
            )
            or any(
                v["min"] is not None and v["max"] is not None and v["min"] > v["max"]
                for v in bounds.values()
            )
        ):
            raise ValueError("Finite mission limits and measurement names are required")
        resolved.append((setting, paths, binding, bounds, netlists[setting["corner"]]))
    return resolved


def _analog_native_values(project, record, binding):
    """Reopen actual producer input closure and raw measurements, not scalar status."""
    import math
    import analog_native_sim as sim
    import analog_real_corner_sweep as sweep

    if not record.get("executions"):
        raise ElectricalError("D70_ANALOG_NATIVE_RESULT_ABSENT", "No simulator invocation")
    transcript = "\n".join(sim._log_text(e) for e in record["executions"])
    if any(e.get("returncode") != 0 for e in record["executions"]) or any(
        sweep._scan_analysis_failures(transcript)
    ):
        return "FAIL", {}
    if (
        record.get("status") != "PASS"
        or (record.get("temperature") or {}).get("matched") is not True
    ):
        raise ElectricalError("D70_ANALOG_NATIVE_MEASUREMENT_INCOMPLETE", record.get("detail", ""))
    values = {k.casefold(): v for k, v in sweep.native_meas_rows(transcript).items()}
    for match in sweep._MEAS_LINE_RE.finditer(transcript):
        for key, value in sweep._KV_RE.findall(match.group(1)):
            values.setdefault(key.casefold(), float(value))
    if any(
        name not in values
        or not math.isfinite(values[name])
        or record.get("measurements", {}).get(name) != values[name]
        for name in binding["measurements"]
    ):
        raise ElectricalError(
            "D70_ANALOG_RAW_MEASUREMENT_MISSING", "finite named native values required"
        )
    return "PASS", {name: values[name] for name in binding["measurements"]}


def _execute_analog(project, context):
    import analog_native_sim as sim
    import corner_yield_vs_spec_check as limits
    from analog_native_flow import NativeCommands
    import librelane_contract as contract

    project = Path(project).resolve()
    attempt = project / "reports/phase3/final-analog-mission" / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    result = {"component_status": "NOT_MEASURED", "native_started": False, "scenarios": []}
    statuses = []
    try:
        options = context["analog"]
        image = options.get("image") or contract.resolve_image(project)
        run = NativeCommands(project, attempt, "", image)
        for index, (setting, paths, binding, bounds, netlist) in enumerate(
            _analog_inputs(project, options)
        ):
            destination = attempt / ("mission-" + str(index))
            argv = [
                str(project),
                "--netlist",
                str(netlist),
                "--testbench",
                str(paths["testbench"]),
                "--bindings",
                str(paths["bindings"]),
                "--out",
                str(destination),
                "--container",
                "",
                "--image",
                image,
            ]
            result["native_started"] = True
            execution = run("analog_bound_measurements.py", argv)
            record = _read(destination / "result.json")
            status, measured = _analog_native_values(project, record, binding)
            violations = [
                name
                for name, bound in bounds.items()
                if name in measured and limits._violates(measured[name], bound["min"], bound["max"])
            ]
            if violations:
                status = "FAIL"
            statuses.append(status)
            result["scenarios"].append(
                {
                    "id": setting["id"],
                    "corner": setting["corner"],
                    "status": status,
                    "values": measured,
                    "violations": violations,
                    "report": str(destination / "result.json"),
                    "execution": execution,
                }
            )
        unsupported = [
            k for k in ("thermal", "aging", "signal_em", "em") if options.get(k) is not None
        ]
        if unsupported:
            statuses.append("NOT_MEASURED")
        result.update(component_status=_roll_up(statuses), unsupported_requirements=unsupported)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update(
            component_status="FAIL" if "FAIL" in statuses else "NOT_MEASURED", detail=str(exc)
        )
    write_json(attempt / "result.json", result)
    return result
