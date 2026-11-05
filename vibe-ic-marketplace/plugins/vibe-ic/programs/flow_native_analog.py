"""Connect the native analog producers to the current flow's command runner."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
ANALOG_STEPS = tuple(f"A{number:02d}" for number in range(1, 20))
NATIVE_STEPS = dict(zip((
    "analog_specifications", "analog_model_qualification", "analog_testability_and_trim_plan",
    "analog_topology", "analog_netlist_and_sizing", "analog_measurement_testbench",
    "analog_pre_layout_nominal_performance", "analog_pre_layout_pvt_and_operating_range",
    "analog_pre_layout_statistics", "calibration_algorithm_verification", "analog_layout",
    "analog_block_physical_verification", "analog_parasitic_extraction", "analog_post_layout_performance",
    "analog_post_layout_statistics", "analog_reliability", "analog_characterized_views",
    "analog_top_interconnect_pads_and_power", "analog_block_signoff",
), ANALOG_STEPS))
BRANCHES = {
    "die_floorplan_and_macros", "io_pad_ring_and_power_distribution", "routed_candidate_physical_checks",
    "antenna_checks", "candidate_parasitic_extraction", "candidate_signal_integrity",
    "post_layout_spice_correlation", "candidate_power_analysis", "candidate_ir_drop",
    "candidate_electromigration", "stream_out", "final_geometry_rc_and_pex", "final_electrical_analysis",
}


def _read(path, default=None):
    if not Path(path).is_file():
        return default
    return json.loads(Path(path).read_text())


def _block_declaration(project):
    project = Path(project)
    paths = [(project / "phase1/generated_docs/L5_ADI_SPEC.json", "analog_blocks"),
             (project / "phase3/analog/analog_block_list.json", "blocks"),
             (project / "analog/analog_block_list.json", "blocks"),
             (project / "phase1/analog/analog_block_list.json", "blocks")]
    for path, key in paths:
        body = _read(path)
        rows = body.get(key) if isinstance(body, dict) else body
        if rows is None:
            continue
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"analog block declaration must be an object list: {path}")
        names = [row.get("name") or row.get("block") for row in rows]
        if any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", name)
               or name in (".", "..") for name in names) or len(names) != len(set(names)):
            raise ValueError(f"analog blocks must have unique usable names: {path}")
        return path, rows
    return paths[0][0], []


def declared_blocks(project):
    """Read source declarations without materializing a second declaration."""
    return _block_declaration(project)[1]


def _previous_results(project):
    previous = {}
    for path in sorted((project / "steps").glob("**/analog_results.json")):
        for row in (_read(path, {}) or {}).get("blocks", []):
            step, name = row.get("step"), row.get("block")
            if step in ANALOG_STEPS and name:
                previous.setdefault(step, {})[name] = row
    return previous


def command_bridge(commands, project):
    def run(program, argv, *, cwd=None, outputs=None, input_text=None):
        command = ([program[1:]] if program.startswith("@") else [sys.executable, str(HERE / program)])
        command += [str(value) for value in argv]
        started = time.perf_counter()
        before = len(commands.records)
        kwargs = {"cwd": cwd or project}
        if input_text is not None:
            kwargs["input_text"] = input_text
        completed = commands.run(command, **kwargs)
        paths = [str(path) for path in outputs or []]
        return {"returncode": completed.returncode if completed is not None else 127,
                "stdout": completed.stdout if completed is not None else "",
                "stderr": completed.stderr if completed is not None else f"executable unavailable: {command[0]}",
                "log": commands.records[-1]["log"] if len(commands.records) > before else None,
                "duration_s": time.perf_counter() - started, "outputs": paths,
                "missing_outputs": [path for path in paths if not Path(path).is_file()]}
    return run


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _spec_rows(block):
    body = block.get("spec")
    specs = body.get("specs", body) if isinstance(body, dict) else []
    if isinstance(specs, dict):
        return [{"name": name, **value} for name, value in specs.items() if isinstance(value, dict)]
    return [row for row in specs if isinstance(row, dict)] if isinstance(specs, list) else []


def _features(project):
    features = {}
    for path in sorted((project / "phase1/generated_docs").glob("L*.json")):
        document = _read(path, {})
        if not isinstance(document, dict):
            continue
        for values in (document, document.get("fields", {}), document.get("features", {})):
            if isinstance(values, dict):
                features.update({key: value for key, value in values.items() if type(value) is bool})
    return features


def _source_unit_value(value, key, spec, native_units=None):
    from analog_a3_netlist_emit import _row_unit_scale
    from analog_a5_layout_emit import _CURRENT_UNIT_MA
    from analog_a9_cosim_emit import _UNIT_HZ

    unit = str(spec.get("unit") or spec.get("units") or "").strip()
    native_unit = str(native_units or "").strip()
    if not unit and not native_unit:
        return value, ""
    if key in {"vout", "vin", "vref", "vdd", "dropout", "vindiff"}:
        wanted = _row_unit_scale({"unit": unit}) if unit else 1.0
        native = _row_unit_scale({"unit": native_unit}) if native_unit else 1.0
    elif key in {"iout", "iq"}:
        wanted = _CURRENT_UNIT_MA.get(unit.casefold(), None) if unit else 1e3
        native = _CURRENT_UNIT_MA.get(native_unit.casefold(), None) if native_unit else 1e3
    elif key == "fclk":
        wanted = _UNIT_HZ.get(unit.casefold()) if unit else 1.0
        native = _UNIT_HZ.get(native_unit.casefold()) if native_unit else 1.0
    elif key in {"snr", "sndr", "psrr"}:
        wanted = 1.0 if unit.casefold() == "db" else None
        native = 1.0 if not native_unit or native_unit.casefold() == "db" else None
    elif key in {"enob", "resolution", "osr", "order"}:
        accepted = {"bit", "bits", "count", "ratio", "1", ""}
        wanted = 1.0 if unit.casefold() in accepted else None
        native = 1.0 if native_unit.casefold() in accepted else None
    elif native_unit and native_unit == unit:
        wanted = native = 1.0
    else:
        wanted = native = None
    if wanted is None or native is None:
        return None, "native measurement units cannot be converted to the declared spec unit"
    return value * native / wanted, ""


def declared_spec_checks(project, *, config=None, metrics=None):
    """Compare every source spec with each real corner's native number."""
    from analog_real_corner_sweep import normalize_spec_label, resolve_spec, _verdict
    from corner_yield_vs_spec_check import _corner_measured, _violates

    project = Path(project)
    source, blocks = _block_declaration(project)
    checks = []
    for block in blocks:
        name = block.get("name") or block.get("block")
        kind = block.get("type") or block.get("block_type")
        report = project / "phase3/analog" / name / "corner_results.json"
        if not report.is_file():
            report = project / "analog" / name / "corner_results.json"
        measured = _read(report, {}) or {}
        current = (metrics or {}).get(name)
        if isinstance(current, dict) and current.get("native_step") != "A08":
            corners = current.get("corners")
            if corners:
                corners = [{"executed": current.get("native_executed") is True, **corner}
                           for corner in corners if isinstance(corner, dict)]
            else:
                corners = [{"name": "native", "measurements": current,
                            "executed": current.get("native_executed") is True}]
            report = Path(current.get("native_report") or report)
        else:
            corners = measured.get("corners") or measured.get("pvt_grid") or [{}]
        target = resolve_spec(project, name, kind)
        for spec in _spec_rows(block):
            label = str(spec.get("name") or spec.get("spec") or "unnamed")
            key = normalize_spec_label(label, kind) or label.casefold()
            limit = {field: spec[field] for field in ("min", "max", "target") if field in spec}
            for corner in corners:
                if not isinstance(corner, dict):
                    continue
                actual = _corner_measured(corner)
                for field in ("measurements", "meas"):
                    actual.update(corner.get(field) or {} if isinstance(corner.get(field), dict) else {})
                normalized = {normalize_spec_label(k, kind) or str(k).casefold(): v for k, v in actual.items()}
                for native_key, canonical in (("vout_v", "vout"), ("sndr_db", "sndr"),
                                               ("snr_db", "snr"), ("psrr_db", "psrr")):
                    if native_key in actual:
                        normalized.setdefault(canonical, actual[native_key])
                value = normalized.get(key)
                native_value, unit_reason = value, ""
                units = corner.get("units") or measured.get("units") or {}
                native_unit = units.get(key) if isinstance(units, dict) else None
                if _number(value):
                    value, unit_reason = _source_unit_value(value, key, spec, native_unit)
                executed = (corner["simulator_run"] is True if "simulator_run" in corner else
                            corner.get("executed") is True or isinstance(corner.get("execution"), dict)
                            and corner["execution"].get("returncode") == 0)
                status, reason = "NOT_MEASURED", "native SPICE number is missing"
                if unit_reason:
                    reason = unit_reason
                if _number(value) and executed:
                    lo, hi = spec.get("min"), spec.get("max")
                    malformed = any(edge in spec and spec[edge] is not None and not _number(spec[edge])
                                    for edge in ("min", "max", "target"))
                    if malformed:
                        reason = "original numeric spec bound is malformed"
                    elif _number(lo) or _number(hi):
                        status = "FAIL" if _violates(value, lo if _number(lo) else None,
                                                     hi if _number(hi) else None) else "PASS"
                        reason = "native SPICE number compared with original L5 bounds"
                    elif (_number(spec.get("target")) and target.get("key") == key
                          and target.get("target_source") == "L5" and _number(target.get("tol"))):
                        limit["tolerance"] = target["tol"]
                        status = _verdict({key: value}, target)
                        reason = "native SPICE number compared with original target and native tolerance"
                    else:
                        reason = "original numeric bounds or target tolerance are missing"
                elif _number(value):
                    reason = "corner has no executed SPICE result; derived numbers are not measurements"
                    value = None
                checks.append({"metric": f"{name}.{label}", "block": name, "name": label,
                               "value": value if _number(value) else None, "limit": limit,
                               "native_value": native_value if _number(native_value) else None,
                               "native_unit": native_unit,
                               "unit": spec.get("unit"), "corner": corner.get("name") or corner.get("corner"),
                               "status": status, "source": str(source), "report": str(report),
                               "reason": reason})
    return checks


def _branch(name, project, directory, options, run):
    if name == "post_layout_spice_correlation":
        from analog_a7_post_layout_resim_check import _check_specs, DEFAULT_MAX_DELTA_PCT
        rows, outputs, deltas = [], [], []
        for block in declared_blocks(project):
            block_name = block.get("name") or block.get("block")
            prior = options["previous_results"].get("A14", {}).get(block_name, {})
            measured, _ = _check_specs((prior.get("metrics") or {}).get("specs") or [])
            status = prior.get("status", "NOT_MEASURED")
            if not measured:
                status = "NOT_MEASURED"
            elif any(delta > DEFAULT_MAX_DELTA_PCT for delta in measured):
                status = "FAIL"
            rows.append({"block": block_name, "status": status,
                         "max_delta_pct": max(measured) if measured else None})
            deltas.extend(measured)
            outputs.extend(prior.get("outputs") or [])
        status = ("FAIL" if any(row["status"] == "FAIL" for row in rows) else
                  "PASS" if rows and all(row["status"] == "PASS" for row in rows) else "NOT_MEASURED")
        return {"status": status,
                "detail": "Existing native pre/post comparison" if deltas else
                          "No native post-layout SPICE comparison was produced by the earlier analog step.",
                "metrics": {"max_delta_pct": max(deltas) if deltas else None, "blocks": rows},
                "outputs": outputs, "reused_native": bool(deltas)}
    from flow_native_analog_die import execute as die
    return die(name, project, directory, run, state=options["state"],
               config=options["native_config"], route=options["route"])


def execute(project, directory, tool, commands, *, state=None, config=None, route=None):
    import analog_native_flow as native
    from analog_one_shot_runner import _effective_analog_pdk

    project, directory = Path(project).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    name = tool.get("step", "")
    step = NATIVE_STEPS.get(name, name)
    if name not in NATIVE_STEPS and name not in BRANCHES:
        return commands.result(detail="unsupported native analog step: " + name)
    features = {**_features(project), **tool.get("features", {})}
    options = {"container": "", "image": "", "transport": "HOST", "config": {},
               "features": features, "previous_results": _previous_results(project),
               "pdk": str((config or {}).get("PDK") or _effective_analog_pdk(SimpleNamespace(pdk=""), project)),
               "cpus": 8, "workers": 1,
               "attempt_dir": str(directory), "active_blocks": [],
               "state": state, "native_config": config or {}, "route": route or {}}
    run = command_bridge(commands, project)
    rows, reports, metrics, native_steps = [], [], {}, []
    try:
        blocks = declared_blocks(project)
        if step == "A19":
            checks = declared_spec_checks(project, config=config)
            metrics["spec_results"] = checks
            reports.extend(dict.fromkeys(row["report"] for row in checks if Path(row["report"]).is_file()))
            native_steps = [{"name": row["metric"], "ran": row["value"] is not None,
                             "exit_code": 0 if row["value"] is not None else None,
                             "reused": True, **row} for row in checks]
            if not checks:
                native_steps = [{"name": step, "ran": False, "exit_code": None,
                                 "status": "NOT_MEASURED", "reason": "declared L5 numeric analog specs are absent"}]
        else:
            population = blocks if step in ANALOG_STEPS else [None]
            for block in population:
                before = len(commands.records)
                result = (native._dispatch(step, project, block, options, run) if block is not None
                          else _branch(name, project, directory, options, run))
                block_name = block.get("name") or block.get("block") if block is not None else "die"
                row = {"step": step, "block": block_name, **result}
                rows.append(row)
                ran = result.get("native_ran", len(commands.records) > before or result.get("reused_native") is True)
                status = result.get("status", "NOT_MEASURED")
                if not ran and status == "PASS":
                    status = "NOT_MEASURED"
                native_steps.append({"name": f"{step}.{block_name}", "ran": ran, "status": status,
                                     "exit_code": next((r["exit_code"] for r in commands.records[before:]
                                                        if r["exit_code"]), 0) if ran else None,
                                     "reused": result.get("reused_native", False),
                                     "reason": result.get("detail", "")})
                reports.extend(result.get("outputs") or [])
                values = result.get("metrics")
                if isinstance(values, list):
                    values = {"measurements": values}
                if isinstance(values, dict):
                    metrics[block_name] = {**values, "native_executed": ran,
                                     "native_step": step,
                                     "native_report": str(directory / "analog_results.json")}
                    if len(population) == 1:
                        metrics.update(values)
                    for key, value in values.items():
                        if _number(value):
                            metrics[f"{block_name}.{key}"] = value
            if not population:
                native_steps.append({"name": step, "ran": False, "exit_code": None,
                                     "status": "NOT_MEASURED", "reason": "declared analog blocks are absent"})
    except (OSError, ValueError, TypeError, KeyError) as exc:
        native_steps.append({"name": step, "ran": False, "exit_code": None,
                             "status": "NOT_MEASURED", "reason": str(exc)})
    report = directory / "analog_results.json"
    from flow_engine import write_json
    write_json(report, {"step": step, "blocks": rows})
    result = commands.result(metrics, [report, *reports], "; ".join(row.get("reason", "") for row in native_steps))
    result["native_steps"] = native_steps
    result["ran"] = any(row["ran"] for row in native_steps)
    if not result["ran"]:
        result["exit_code"] = None
    elif result["exit_code"] is None:
        result["exit_code"] = 0
    return result
