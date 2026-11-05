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
BRANCHES = {
    "D31": ("flow109_analog_floorplan.native", "input/flow109/D31.json",
            "declared die/core rectangles, macro GDS/LEF views and placements are required"),
    "D32": ("pad_ring_gen.main", "phase3/stage3/pnr/floorplan.def",
            "native die floorplan DEF and pad assignment are required"),
    "D42": ("analog_a6_native_pv.run_block_pv", "",
            "die-level routed GDS, LVS reference and installed-PDK DRC/LVS decks are required"),
    "D43": ("gds_antenna_deck_check.run", "",
            "streamed die GDS and a PDK antenna deck are required"),
    "D47": ("magic_extract_spice_emit.emit", "",
            "routed die geometry and a declared Magic extraction technology/style are required"),
    "D48": ("analog_bound_measurements.run_measurements", "input/flow109/D48.json",
            "coupled extracted netlist, aggressor/victim testbench and measurement limits are required"),
    "D54": ("analog_native_physical._resim", "",
            "native A14 post-layout measurements and original pre/post correlation limits are required"),
    "D56": ("analog_native_em.supply_wave_statistics", "input/flow109/D56.json",
            "native supply-current waveforms, supply voltages and declared mission windows are required"),
    "D57": ("ir_drop_budget_check.evaluate", "input/flow109/D57.json",
            "native rail-voltage measurements, supply voltage and original IR-drop budget are required"),
    "D58": ("analog_native_em.grade_case", "input/flow109/D58.json",
            "native branch currents, routed conductor dimensions and PDK EM limits are required"),
    "D60": ("analog_hardmacro_gds_emit.run", "",
            "die-level Magic layout with pad/power integration is required for die stream-out"),
    "D69": ("flow109_final_extract._execute_analog", "input/flow109/D69.json",
            "final filled die GDS, logical net census and declared extraction technology/corners are required"),
    "D70": ("flow109_final_electrical._execute_analog", "input/flow109/D70.json",
            "final extracted die netlist, mission testbench and original electrical limits are required"),
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


def _branch(step, project, directory, options, run):
    native, prerequisite, reason = BRANCHES[step]
    if step == "D31":
        report = directory / "D31_native.json"
        script = (
            "import json,sys\nfrom pathlib import Path\n"
            "sys.path.insert(0,sys.argv[1])\nimport flow109_analog_floorplan as native\n"
            "project,output,report=map(Path,sys.argv[2:])\n"
            "try:\n native.native(project,output,True)\n result=native.native(project,output,False)\n"
            "except (OSError,ValueError,ImportError,KeyError) as exc:\n"
            " result={'status':'NOT_MEASURED','reason':str(exc)}\n"
            "report.write_text(json.dumps(result))\n"
            "sys.exit(1 if result.get('status')=='FAIL' else 0)\n")
        execution = run("@" + sys.executable, ["-c", script, str(HERE), str(project),
                        str(directory), str(report)], outputs=[str(report)])
        result = _read(report, {}) or {}
        return {"status": result.get("status", "NOT_MEASURED"),
                "detail": result.get("reason") or "KLayout native die floorplan placement and geometry",
                "metrics": {key: value for key, value in result.items() if _number(value)},
                "outputs": [str(report), str(directory / "floorplan.gds")], "executions": [execution],
                "native_ran": result.get("status") in ("PASS", "FAIL")}
    if step == "D54":
        from analog_a7_post_layout_resim_check import _check_specs, DEFAULT_MAX_DELTA_PCT

        rows, outputs, deltas = [], [], []
        for block in declared_blocks(project):
            name = block.get("name") or block.get("block")
            prior = options["previous_results"].get("A14", {}).get(name, {})
            values = prior.get("metrics") or {}
            measured, _ = _check_specs(values.get("specs") or [])
            status = prior.get("status", "NOT_MEASURED")
            if not measured:
                status = "NOT_MEASURED"
            elif any(delta > DEFAULT_MAX_DELTA_PCT for delta in measured):
                status = "FAIL"
            rows.append({"block": name, "status": status, "max_delta_pct": max(measured) if measured else None})
            deltas.extend(measured)
            outputs.extend(prior.get("outputs") or [])
        status = ("FAIL" if any(row["status"] == "FAIL" for row in rows) else
                  "PASS" if rows and all(row["status"] == "PASS" for row in rows) else "NOT_MEASURED")
        return {"status": status, "detail": "Read existing A14 native pre/post comparisons" if deltas else reason,
                "metrics": {"max_delta_pct": max(deltas) if deltas else None, "blocks": rows},
                "outputs": outputs, "reused_native": bool(deltas)}
    if step in ("D32", "D43"):
        program = "pad_ring_gen.py" if step == "D32" else "gds_antenna_deck_check.py"
        report = directory / (step + "_native.json")
        execution = run(program, [str(project), "--json", str(report)], outputs=[str(report)])
        doc = _read(report, {}) or {}
        status = doc.get("verdict") or doc.get("status") or doc.get("result")
        status = status if status in ("PASS", "FAIL") else "NOT_MEASURED"
        if execution["returncode"] and status == "PASS":
            status = "NOT_MEASURED"
        return {"status": status, "detail": doc.get("reason") or doc.get("detail") or reason,
                "metrics": doc.get("metrics") or doc.get("summary") or {},
                "outputs": [str(report)], "executions": [execution]}
    absent = prerequisite and not (project / prerequisite).is_file()
    detail = f"{step}: {reason}"
    if absent:
        detail += "; missing " + prerequisite
    else:
        detail += f"; {native} has no direct die-level invocation without the legacy flow context"
    return {"status": "NOT_MEASURED", "detail": detail, "outputs": []}


def execute(project, directory, tool, commands, *, state=None, config=None):
    import analog_native_flow as native
    from analog_one_shot_runner import _effective_analog_pdk

    project, directory = Path(project).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    step = str(tool.get("native_step") or "").split(".")[-1]
    if step not in (*ANALOG_STEPS, *BRANCHES):
        return commands.result(detail="unsupported native analog step: " + step)
    settings = _read(project / "input/analog_flow.json", {}) or {}
    features = {**_features(project), **settings.get("features", {}), **tool.get("features", {})}
    options = {"container": "", "image": "", "transport": "HOST", "config": settings,
               "features": features, "previous_results": _previous_results(project),
               "pdk": _effective_analog_pdk(SimpleNamespace(pdk=settings.get("pdk", "")), project),
               "cpus": min(8, int(settings.get("cpus", 4))), "workers": 1,
               "attempt_dir": str(directory), "active_blocks": settings.get("active_blocks", [])}
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
                          else _branch(step, project, directory, options, run))
                name = block.get("name") or block.get("block") if block is not None else "die"
                row = {"step": step, "block": name, **result}
                rows.append(row)
                ran = result.get("native_ran", len(commands.records) > before or result.get("reused_native") is True)
                status = result.get("status", "NOT_MEASURED")
                if not ran and status == "PASS":
                    status = "NOT_MEASURED"
                native_steps.append({"name": f"{step}.{name}", "ran": ran, "status": status,
                                     "exit_code": next((r["exit_code"] for r in commands.records[before:]
                                                        if r["exit_code"]), 0) if ran else None,
                                     "reused": result.get("reused_native", False),
                                     "reason": result.get("detail", "")})
                reports.extend(result.get("outputs") or [])
                values = result.get("metrics")
                if isinstance(values, dict):
                    metrics[name] = {**values, "native_executed": ran,
                                     "native_step": step,
                                     "native_report": str(directory / "analog_results.json")}
                    if len(population) == 1:
                        metrics.update(values)
                    for key, value in values.items():
                        if _number(value):
                            metrics[f"{name}.{key}"] = value
            if not population:
                native_steps.append({"name": step, "ran": False, "exit_code": None,
                                     "status": "NOT_MEASURED", "reason": "declared analog blocks are absent"})
    except (OSError, ValueError, TypeError, KeyError) as exc:
        native_steps.append({"name": step, "ran": False, "exit_code": None,
                             "status": "NOT_MEASURED", "reason": str(exc)})
    report = directory / "analog_results.json"
    report.write_text(json.dumps({"step": step, "blocks": rows}, indent=2) + "\n")
    result = commands.result(metrics, [report, *reports], "; ".join(row.get("reason", "") for row in native_steps))
    result["native_steps"] = native_steps
    if step == "A19" or any(row.get("reused") for row in native_steps):
        result["ran"] = any(row["ran"] for row in native_steps)
        result["exit_code"] = 0 if result["ran"] else None
    return result
